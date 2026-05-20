"""
archimedes_wizard.py — FastAPI backend for the Archimedes AI step-by-step wizard.

Endpoints:
  GET  /                                  → serve archimedes_wizard.html
  GET  /api/config                        → feature flags (leanix configured?)
  POST /api/session                       → create session (Step 0: client name)
  GET  /api/session/{id}/catalog          → catalog status (Step 1)
  POST /api/session/{id}/baseline         → baseline generation (Step 2)
  POST /api/session/{id}/lift-shift/resolve → Lift & Shift: resolve app names → Material Numbers (Step 2b)
  POST /api/session/{id}/lift-shift/convert → Lift & Shift: convert SKUs to RISE targets (Step 2b)
  POST /api/session/{id}/requirements     → requirements Excel (Step 3)
  POST /api/session/{id}/contrast         → SAP Help Portal contrast (Step 3b, optional)
  POST /api/session/{id}/pdf              → PDF extraction (Step 4)
  POST /api/session/{id}/images           → image extraction (Step 5)
  POST /api/session/{id}/generate         → generate LeanIX outputs (Step 6)
  POST /api/session/{id}/push             → import to LeanIX (Step 7)
  POST /api/session/{id}/push-kpi        → 🍪 easter egg: generate + import KPI Achievement Excel
  GET  /api/session/{id}/download/{key}   → download generated file

Usage:
    python3 archimedes_wizard.py
    → http://localhost:8767
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import uuid
import webbrowser
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
WIZARD_HTML = BASE_DIR / "archimedes_wizard.html"
OUTPUT_DIR  = BASE_DIR / "output" / "sessions"

sys.path.insert(0, str(BASE_DIR))

# ── Pipeline imports ──────────────────────────────────────────────────────────
from pipeline.catalog       import _catalog_info, RBA_PATH, RSA_PATH
from pipeline.footprint     import generate_baseline
from pipeline.extract       import extract
from pipeline.enrich        import enrich
from pipeline.validate      import validate
from pipeline.write         import write, write_leanix_excel_from_xlsx, push_leanix
from pipeline.pdf_extract   import extract_pdf_factsheets
from pipeline.image_extract import extract_image_factsheets
from pipeline.help_contrast      import run_contrast, print_contrast_summary
from pipeline.lift_shift    import (
    get_material_session, check_session,
    resolve_app_to_skus, get_deployment_modes,
    convert_to_rise, resolve_prerequisites,
)
from pipeline.industry_reference import (
    get_industry_reference, compute_whitespace,
    add_reference_to_target_excel, derive_relations_for_products, INDUSTRIES
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s — %(message)s")
logger = logging.getLogger("archimedes.wizard")

# ── Anthropic client (shared) ─────────────────────────────────────────────────
_anthropic_client = None

def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client

MODEL = os.getenv("ENRICH_MODEL", "claude-sonnet-4-6")

# ── Session store ─────────────────────────────────────────────────────────────
# session_id → dict with pipeline state
_sessions: dict[str, dict] = {}

def _session(session_id: str) -> dict:
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return _sessions[session_id]


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Archimedes Wizard", docs_url=None, redoc_url=None)


# ── Static ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_wizard():
    return WIZARD_HTML.read_text(encoding="utf-8")


@app.get("/cookie_monster.png")
async def serve_cookie_monster():
    p = BASE_DIR / "cookie_monster.png"
    return FileResponse(path=str(p), media_type="image/png")


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    leanix_ok = bool(os.environ.get("LEANIX_API_TOKEN") and os.environ.get("LEANIX_BASE_URL"))
    anthropic_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return {"ok": True, "leanix_configured": leanix_ok, "anthropic_configured": anthropic_ok, "model": MODEL}


# ── Step 0 — Create session ───────────────────────────────────────────────────

@app.post("/api/session")
async def create_session(body: dict):
    client_name = (body.get("client_name") or "").strip()
    if not client_name:
        raise HTTPException(status_code=400, detail="client_name is required")

    session_id = str(uuid.uuid4())
    output_dir = OUTPUT_DIR / session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    _sessions[session_id] = {
        "client_name":       client_name,
        "output_dir":        output_dir,
        "baseline_result":   None,
        "req_excel_path":    None,
        "req_enriched_xlsx": None,
        "target_json_path":  None,
        "pdf_factsheets":    None,
        "image_factsheets":  None,
        "out_baseline":      None,
        "out_target":        None,
        "out_supplementary": None,
        "lift_shift_result": None,
    }

    logger.info("Session created: %s  client=%s", session_id, client_name)
    return {"ok": True, "session_id": session_id, "client_name": client_name}


# ── Step 1 — Catalog status ───────────────────────────────────────────────────

@app.get("/api/session/{session_id}/catalog")
async def catalog_status(session_id: str):
    _session(session_id)  # validate session exists

    result = {}
    for label, path in [("rba", RBA_PATH), ("rsa", RSA_PATH)]:
        if not path.exists():
            result[label] = {"error": f"Not found: {path}"}
        else:
            result[label] = _catalog_info(path)

    return {"ok": True, **result}


# ── Step 2 — Baseline / Footprint ─────────────────────────────────────────────

@app.post("/api/session/{session_id}/baseline")
async def run_baseline(
    session_id: str,
    onprem_file: Optional[UploadFile] = File(None),
    cloud_file:  Optional[UploadFile] = File(None),
):
    sess = _session(session_id)

    if not onprem_file and not cloud_file:
        return {"ok": True, "skipped": True, "n_total": 0}

    out_dir = sess["output_dir"]
    onprem_path = cloud_path = None

    if onprem_file and onprem_file.filename:
        onprem_path = out_dir / "onprem_systems.xlsx"
        onprem_path.write_bytes(await onprem_file.read())

    if cloud_file and cloud_file.filename:
        cloud_path = out_dir / "cloud_systems.xlsx"
        cloud_path.write_bytes(await cloud_file.read())

    if not onprem_path and not cloud_path:
        return {"ok": True, "skipped": True, "n_total": 0}

    client_name  = sess["client_name"]
    baseline_out = out_dir / f"{client_name}_baseline.xlsx"

    try:
        result = await asyncio.to_thread(
            generate_baseline,
            output_path=baseline_out,
            client_name=client_name,
            onprem_path=onprem_path,
            cloud_path=cloud_path,
        )
    except Exception as exc:
        logger.exception("Baseline error")
        raise HTTPException(status_code=500, detail=str(exc))

    sess["baseline_result"] = result
    sess["out_baseline"]    = baseline_out

    return {
        "ok":           True,
        "skipped":      False,
        "n_onprem":     result["n_onprem"],
        "n_cloud":      result["n_cloud"],
        "n_total":      result["n_total"],
        "download_url": f"/api/session/{session_id}/download/baseline",
    }


# ── Step 2b — Lift & Shift: Resolve ───────────────────────────────────────────

@app.post("/api/session/{session_id}/lift-shift/resolve")
async def lift_shift_resolve(session_id: str):
    """
    Phase 1: Read app names from the baseline Excel, resolve each to a Material Number
    via the SAP Material Mapping API (Claude picks best candidate when multiple exist).
    Also returns the union of available deployment modes across all resolved SKUs.
    """
    sess = _session(session_id)
    baseline_path = sess.get("out_baseline")
    if not baseline_path or not Path(baseline_path).exists():
        raise HTTPException(status_code=400, detail="Baseline not generated yet — complete Step 2 first.")

    # Extract app names from baseline Excel (col C = name, starting row 3)
    try:
        import openpyxl
        wb = openpyxl.load_workbook(baseline_path)
        ws = wb["Applications"]
        app_names = [
            row[2] for row in ws.iter_rows(min_row=3, values_only=True)
            if row[2] and str(row[2]).strip()
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read baseline Excel: {exc}")

    if not app_names:
        raise HTTPException(status_code=400, detail="No applications found in the baseline Excel.")

    # Build material session (Chrome cookies)
    mat_session = get_material_session()
    if not check_session(mat_session):
        raise HTTPException(
            status_code=503,
            detail="SAP Material Mapping Tool session expired — open Chrome with the app and retry."
        )

    # Resolve names → SKUs (Claude picks best candidate)
    try:
        resolved = await asyncio.to_thread(resolve_app_to_skus, app_names, mat_session)
    except Exception as exc:
        logger.exception("Lift & Shift resolve error")
        raise HTTPException(status_code=500, detail=str(exc))

    # Get deployment modes across all resolved SKUs
    skus = [r["selected"] for r in resolved if r["selected"]]
    try:
        modes = await asyncio.to_thread(get_deployment_modes, skus, mat_session)
    except Exception as exc:
        logger.exception("Lift & Shift deployment modes error")
        modes = []

    # Store mat_session is not serialisable; store resolved list in session
    sess["lift_shift_resolved"] = resolved
    sess["lift_shift_modes"]    = modes

    return {
        "ok":       True,
        "resolved": resolved,
        "modes":    modes,
        "n_apps":   len(app_names),
        "n_found":  sum(1 for r in resolved if r["selected"]),
        "n_not_found": sum(1 for r in resolved if not r["selected"]),
    }


# ── Step 2b — Lift & Shift: Convert ───────────────────────────────────────────

@app.post("/api/session/{session_id}/lift-shift/convert")
async def lift_shift_convert(session_id: str, body: dict):
    """
    Phase 2: Given user-confirmed mappings and chosen deployment mode,
    run the conversion and return target materials + prerequisites.

    Body: {
      "mappings": [{"app_name": str, "selected": str (matnr)}],
      "deployment_mode": str
    }
    """
    sess = _session(session_id)
    mappings        = body.get("mappings", [])
    deployment_mode = body.get("deployment_mode", "").strip()

    if not mappings:
        raise HTTPException(status_code=400, detail="mappings is required.")
    if not deployment_mode:
        raise HTTPException(status_code=400, detail="deployment_mode is required.")

    mat_session = get_material_session()
    if not check_session(mat_session):
        raise HTTPException(
            status_code=503,
            detail="SAP Material Mapping Tool session expired — open Chrome with the app and retry."
        )

    try:
        conversions = await asyncio.to_thread(convert_to_rise, mappings, deployment_mode, mat_session)
    except Exception as exc:
        logger.exception("Lift & Shift convert error")
        raise HTTPException(status_code=500, detail=str(exc))

    # Resolve all unique prerequisite SKUs to names
    all_prereq_skus = list({sku for c in conversions for sku in c["prereq_list"]})
    try:
        prereq_names = await asyncio.to_thread(resolve_prerequisites, all_prereq_skus, mat_session)
        prereq_map   = {p["matnr"]: p["maktx"] for p in prereq_names}
    except Exception:
        prereq_map = {}

    # Enrich conversions with resolved prereq names
    for c in conversions:
        c["prereq_resolved"] = [
            {"matnr": sku, "maktx": prereq_map.get(sku, sku)}
            for sku in c["prereq_list"]
        ]

    sess["lift_shift_result"] = {
        "deployment_mode": deployment_mode,
        "conversions":     conversions,
    }

    return {
        "ok":          True,
        "conversions": conversions,
        "n_converted": len(conversions),
        "deployment_mode": deployment_mode,
    }


# ── Step 3 — Requirements Excel ───────────────────────────────────────────────

@app.post("/api/session/{session_id}/requirements")
async def run_requirements(
    session_id: str,
    req_file: Optional[UploadFile] = File(None),
    no_validate: bool = Form(False),
):
    sess = _session(session_id)

    if not req_file or not req_file.filename:
        return {"ok": True, "skipped": True}

    out_dir     = sess["output_dir"]
    client_name = sess["client_name"]
    req_path    = out_dir / req_file.filename
    req_path.write_bytes(await req_file.read())
    sess["req_excel_path"] = req_path

    # Detect if already enriched (cols O/P populated from row 9)
    import openpyxl as _xl
    wb_check = _xl.load_workbook(str(req_path))
    ws_check = wb_check.active
    already_enriched = any(
        ws_check.cell(r, 15).value or ws_check.cell(r, 16).value
        for r in range(9, min(15, ws_check.max_row + 1))
    )

    if already_enriched:
        sess["req_enriched_xlsx"] = req_path
        n_rows = sum(
            1 for r in range(9, ws_check.max_row + 1)
            if ws_check.cell(r, 2).value
        )
        return {
            "ok":              True,
            "skipped":         False,
            "already_enriched": True,
            "n_requirements":  n_rows,
            "validation_ok":   True,
        }

    # Run extract → enrich → (validate) pipeline
    try:
        raw_path = await asyncio.to_thread(extract, req_path, out_dir)
        enriched_path = await asyncio.to_thread(enrich, raw_path, out_dir)

        validation_ok       = True
        validation_warnings = 0
        if not no_validate:
            validation_ok = await asyncio.to_thread(validate, enriched_path, out_dir)

        sess["target_json_path"] = enriched_path

        enriched_data = json.loads(enriched_path.read_text())
        n_requirements = len([r for r in enriched_data if not r.get("_error")])

        return {
            "ok":               True,
            "skipped":          False,
            "already_enriched": False,
            "n_requirements":   n_requirements,
            "validation_ok":    validation_ok,
        }

    except Exception as exc:
        logger.exception("Requirements error")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Step 3b — SAP Help Portal Contrast (optional) ────────────────────────────

@app.post("/api/session/{session_id}/contrast")
async def run_help_contrast(session_id: str):
    sess = _session(session_id)

    target_json      = sess.get("target_json_path")
    req_enriched_xlsx = sess.get("req_enriched_xlsx")
    out_dir          = sess["output_dir"]

    # If pre-enriched xlsx (no JSON), build a minimal JSON from cols O/P for contrast
    if not target_json and req_enriched_xlsx:
        import openpyxl as _xl
        wb = _xl.load_workbook(str(req_enriched_xlsx))
        ws = wb.active
        reqs = []
        for r in range(9, ws.max_row + 1):
            req_id = ws.cell(r, 2).value
            rsa    = ws.cell(r, 16).value  # col P
            desc   = ws.cell(r, 3).value or ""
            if req_id and rsa:
                reqs.append({"_source_id": str(req_id), "rsa": str(rsa), "description": str(desc)})
        if not reqs:
            return {"ok": True, "skipped": True, "reason": "No RSA products found in Excel"}
        tmp_json = out_dir / "reqs_for_contrast.json"
        tmp_json.write_text(json.dumps(reqs, ensure_ascii=False, indent=2))
        target_json = tmp_json

    if not target_json:
        return {"ok": True, "skipped": True, "reason": "No enriched requirements available"}

    try:
        report_path = await asyncio.to_thread(run_contrast, target_json, out_dir)
        sess["out_contrast"] = report_path

        report      = json.loads(report_path.read_text())
        validated   = sum(1 for r in report if r["validated"])
        unvalidated = sum(1 for r in report if not r["validated"] and r["rsa_product"])
        skipped     = sum(1 for r in report if not r["rsa_product"])

        return {
            "ok":            True,
            "skipped":       False,
            "n_total":       len(report),
            "n_validated":   validated,
            "n_unvalidated": unvalidated,
            "n_skipped":     skipped,
            "download_url":  f"/api/session/{session_id}/download/contrast",
        }
    except Exception as exc:
        logger.exception("SAP Help contrast error")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Step 3c — Industry Reference Architecture / Whitespace ───────────────────

@app.get("/api/industries")
async def list_industries():
    return {"ok": True, "industries": [{"key": k, "label": v} for k, v in INDUSTRIES.items()]}


@app.post("/api/session/{session_id}/industry-reference")
async def run_industry_reference(session_id: str, body: dict):
    sess = _session(session_id)

    industry_key = (body.get("industry_key") or "").strip()
    if not industry_key:
        raise HTTPException(status_code=400, detail="industry_key is required")

    # Fetch reference products from SAP API Hub
    try:
        reference = await asyncio.to_thread(get_industry_reference, industry_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Industry reference fetch error")
        raise HTTPException(status_code=500, detail=str(exc))

    # Compute whitespace against baseline AND target
    baseline_path = sess.get("out_baseline")
    target_path   = sess.get("out_target")
    whitespace = await asyncio.to_thread(
        compute_whitespace, reference["products"], baseline_path, target_path
    )

    sess["industry_reference"] = {
        "industry_key":   industry_key,
        "industry_label": reference["industry_label"],
        "whitespace":     whitespace,
    }

    return {
        "ok":             True,
        "industry_key":   industry_key,
        "industry_label": reference["industry_label"],
        "n_reference":    reference["n_products"],
        "whitespace":     whitespace,
    }


@app.post("/api/session/{session_id}/industry-reference/apply")
async def apply_industry_reference(session_id: str, body: dict):
    sess = _session(session_id)

    selected: list[str] = body.get("selected_products", [])
    if not selected:
        return {"ok": True, "skipped": True, "n_added": 0}

    ref = sess.get("industry_reference", {})
    industry_label = ref.get("industry_label", body.get("industry_label", "Reference"))
    out_dir = sess["output_dir"]
    client_name = sess["client_name"]

    # Create or reuse target Excel
    out_target = sess.get("out_target")
    if not out_target or not out_target.exists():
        # Create a minimal target Excel
        import openpyxl as xl
        out_target = out_dir / f"{client_name}_target_leanix.xlsx"
        wb = xl.Workbook()
        ws = wb.active
        ws.title = "Application"
        ws.append(["type", "displayName", "description", "tags"])
        wb.save(str(out_target))
        sess["out_target"] = out_target

    try:
        # Derive BC/ITC relations via Claude API
        relations = await asyncio.to_thread(
            derive_relations_for_products,
            selected, industry_label, _get_anthropic(), MODEL,
        )
        await asyncio.to_thread(
            add_reference_to_target_excel, out_target, selected, industry_label, client_name, relations
        )
    except Exception as exc:
        logger.exception("Apply industry reference error")
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "ok":           True,
        "skipped":      False,
        "n_added":      len(selected),
        "download_url": f"/api/session/{session_id}/download/target",
    }


# ── Step 4 — PDF ──────────────────────────────────────────────────────────────

@app.post("/api/session/{session_id}/pdf")
async def run_pdf(
    session_id: str,
    pdf_file: Optional[UploadFile] = File(None),
):
    sess = _session(session_id)

    if not pdf_file or not pdf_file.filename:
        return {"ok": True, "skipped": True}

    out_dir     = sess["output_dir"]
    client_name = sess["client_name"]
    pdf_path    = out_dir / pdf_file.filename
    pdf_path.write_bytes(await pdf_file.read())

    try:
        result = await asyncio.to_thread(
            extract_pdf_factsheets,
            pdf_path, client_name, _get_anthropic(), MODEL,
        )
    except Exception as exc:
        logger.exception("PDF extract error")
        raise HTTPException(status_code=500, detail=str(exc))

    sess["pdf_factsheets"] = result

    return {
        "ok":                       True,
        "skipped":                  False,
        "summary":                  result.get("summary", ""),
        "n_applications":           len(result.get("applications", [])),
        "n_business_capabilities":  len(result.get("business_capabilities", [])),
        "n_organizations":          len(result.get("organizations", [])),
        "n_initiatives":            len(result.get("initiatives", [])),
        "n_it_components":          len(result.get("it_components", [])),
    }


# ── Step 5 — Images / Diagrams ────────────────────────────────────────────────

@app.post("/api/session/{session_id}/images")
async def run_images(
    session_id: str,
    images: list[UploadFile] = File(default=[]),
):
    sess = _session(session_id)

    valid = [f for f in images if f and f.filename]
    if not valid:
        return {"ok": True, "skipped": True}

    out_dir     = sess["output_dir"]
    client_name = sess["client_name"]
    saved_paths = []

    for f in valid:
        p = out_dir / f.filename
        p.write_bytes(await f.read())
        saved_paths.append(p)

    try:
        result = await asyncio.to_thread(
            extract_image_factsheets,
            saved_paths, client_name, _get_anthropic(), MODEL,
        )
    except Exception as exc:
        logger.exception("Image extract error")
        raise HTTPException(status_code=500, detail=str(exc))

    sess["image_factsheets"] = result

    return {
        "ok":                       True,
        "skipped":                  False,
        "n_files_processed":        len(saved_paths),
        "diagram_type":             result.get("diagram_type", ""),
        "summary":                  result.get("summary", ""),
        "n_applications":           len(result.get("applications", [])),
        "n_business_capabilities":  len(result.get("business_capabilities", [])),
        "n_it_components":          len(result.get("it_components", [])),
        "n_interfaces":             len(result.get("interfaces", [])),
    }


# ── Step 6 — Generate outputs ─────────────────────────────────────────────────

@app.post("/api/session/{session_id}/generate")
async def run_generate(session_id: str):
    sess        = _session(session_id)
    client_name = sess["client_name"]
    out_dir     = sess["output_dir"]
    outputs     = []

    # Baseline (already generated in Step 2, just expose download link)
    if sess.get("out_baseline") and sess["out_baseline"].exists():
        br = sess["baseline_result"] or {}
        outputs.append({
            "key":          "baseline",
            "label":        "Baseline AS-IS",
            "description":  "Applications actuales (on-premise + cloud) — importar en LeanIX",
            "filename":     sess["out_baseline"].name,
            "download_url": f"/api/session/{session_id}/download/baseline",
            "stats":        f"{br.get('n_total', 0)} apps ({br.get('n_onprem', 0)} on-prem + {br.get('n_cloud', 0)} cloud)",
        })

    # Target — requirements → LeanIX Excel
    out_target = None
    try:
        if sess.get("req_enriched_xlsx"):
            out_target = out_dir / f"{client_name}_target_leanix.xlsx"
            await asyncio.to_thread(
                write_leanix_excel_from_xlsx,
                sess["req_enriched_xlsx"], out_target, client_name,
            )
        elif sess.get("target_json_path") and sess.get("req_excel_path"):
            enriched_xlsx, out_target = await asyncio.to_thread(
                write,
                sess["target_json_path"], sess["req_excel_path"], out_dir, client_name,
            )

        if out_target and out_target.exists():
            sess["out_target"] = out_target
            import openpyxl as _xl
            wb = _xl.load_workbook(str(out_target))
            stats_parts = []
            for sh in ["Application", "BusinessCapability", "Initiative", "ITComponent"]:
                if sh in wb.sheetnames:
                    n = wb[sh].max_row - 2
                    if n > 0:
                        stats_parts.append(f"{sh[:3]}: {n}")
            outputs.append({
                "key":          "target",
                "label":        "Target TO-BE",
                "description":  "Fact sheets derivados de requerimientos — importar en LeanIX",
                "filename":     out_target.name,
                "download_url": f"/api/session/{session_id}/download/target",
                "stats":        "  |  ".join(stats_parts),
            })
    except Exception as exc:
        logger.exception("Generate target error")
        raise HTTPException(status_code=500, detail=str(exc))

    # Supplementary JSON (PDF + images)
    supplementary = {}
    if sess.get("pdf_factsheets"):
        supplementary["from_pdf"] = sess["pdf_factsheets"]
    if sess.get("image_factsheets"):
        supplementary["from_images"] = sess["image_factsheets"]

    if supplementary:
        out_supp = out_dir / f"{client_name}_supplementary_factsheets.json"
        out_supp.write_text(json.dumps(supplementary, ensure_ascii=False, indent=2))
        sess["out_supplementary"] = out_supp
        n_apps = len(supplementary.get("from_pdf", {}).get("applications", [])) + \
                 len(supplementary.get("from_images", {}).get("applications", []))
        outputs.append({
            "key":          "supplementary",
            "label":        "Fact sheets adicionales (PDF + imágenes)",
            "description":  "Revisar manualmente antes de importar en LeanIX",
            "filename":     out_supp.name,
            "download_url": f"/api/session/{session_id}/download/supplementary",
            "stats":        f"{n_apps} apps identificadas",
        })

    # Lift & Shift Target Excel (written as the main Target file)
    ls_result = sess.get("lift_shift_result")
    if ls_result and ls_result.get("conversions"):
        try:
            from pipeline.write import write_leanix_excel
            ls_convs    = ls_result["conversions"]
            ls_out_path = out_dir / f"{client_name}_target_leanix.xlsx"
            await asyncio.to_thread(
                write_leanix_excel,
                [],        # no enriched requirements — apps come from lift_shift param
                {},        # no bcs_index
                ls_out_path,
                client_name,
                lift_shift=ls_convs,
            )
            sess["out_target"]    = ls_out_path
            sess["out_liftshift"] = ls_out_path
            n_ls = len({c.get("target_matnr") for c in ls_convs})
            n_prereqs = len({p["matnr"] for c in ls_convs for p in c.get("prereq_resolved", [])})
            outputs.append({
                "key":          "target",
                "label":        "Target TO-BE (Lift & Shift)",
                "description":  f"RISE conversion targets ({ls_result.get('deployment_mode','')}) — importar en LeanIX como TO-BE",
                "filename":     ls_out_path.name,
                "download_url": f"/api/session/{session_id}/download/target",
                "stats":        f"{n_ls} targets · {n_prereqs} prerequisites",
            })
        except Exception as exc:
            logger.exception("Lift & Shift generate error")

    if not outputs:
        raise HTTPException(status_code=400, detail="No hay datos para generar. Completa al menos el Paso 2 o el Paso 3.")

    return {"ok": True, "outputs": outputs}


# ── Step 7 — Import to LeanIX ─────────────────────────────────────────────────

@app.post("/api/session/{session_id}/push")
async def run_push(session_id: str, body: dict):
    sess = _session(session_id)

    if not os.environ.get("LEANIX_API_TOKEN") or not os.environ.get("LEANIX_BASE_URL"):
        raise HTTPException(status_code=400, detail="LEANIX_API_TOKEN y/o LEANIX_BASE_URL no configurados en .env")

    client_name    = sess["client_name"]
    push_baseline  = body.get("push_baseline", False)
    push_target    = body.get("push_target", False)
    pushed = []
    errors = []

    if push_baseline and sess.get("out_baseline"):
        try:
            await asyncio.to_thread(push_leanix, sess["out_baseline"], client_name)
            pushed.append("baseline")
        except Exception as exc:
            errors.append(f"Baseline: {exc}")

    if push_target and sess.get("out_target"):
        try:
            await asyncio.to_thread(push_leanix, sess["out_target"], client_name)
            pushed.append("target")
        except Exception as exc:
            errors.append(f"Target: {exc}")

    return {
        "ok":     not errors,
        "pushed": pushed,
        "errors": errors,
    }


# ── Step 9 Easter Egg — KPI Achievement Import ────────────────────────────────

@app.post("/api/session/{session_id}/push-kpi")
async def run_push_kpi(session_id: str):
    """🍪 Easter egg: generate KPI Achievement Excel and import it into LeanIX."""
    sess = _session(session_id)

    if not os.environ.get("LEANIX_API_TOKEN") or not os.environ.get("LEANIX_BASE_URL"):
        raise HTTPException(status_code=400, detail="LEANIX_API_TOKEN y/o LEANIX_BASE_URL no configurados en .env")

    client_name = sess["client_name"]
    out_dir     = sess["output_dir"]
    kpi_path    = out_dir / "kpi_achievement_leanix.xlsx"

    # ── Generate the KPI Excel into the session output dir ──────────────────
    def _build_kpi():
        import sys
        sys.path.insert(0, str(BASE_DIR))
        import importlib, types

        # Import generate_kpi_excel and override OUTPUT_PATH to session dir
        import generate_kpi_excel as _kpi_mod
        original_path = _kpi_mod.OUTPUT_PATH
        _kpi_mod.OUTPUT_PATH = kpi_path
        try:
            _kpi_mod.build()
        finally:
            _kpi_mod.OUTPUT_PATH = original_path

    await asyncio.to_thread(_build_kpi)

    if not kpi_path.exists():
        raise HTTPException(status_code=500, detail="Error generando el fichero KPI Achievement Excel.")

    # ── Push to LeanIX in order: Objective → BusinessCapability → Application → Initiative ──
    try:
        await asyncio.to_thread(push_leanix, kpi_path, client_name)
    except Exception as exc:
        return {"ok": False, "errors": [str(exc)], "path": str(kpi_path)}

    sess["out_kpi"] = kpi_path
    return {
        "ok":       True,
        "pushed":   ["kpi_achievement"],
        "path":     str(kpi_path),
        "stats": {
            "objectives":           5,
            "business_capabilities": 91,
            "applications":          100,
            "initiatives":           5,
        },
    }


# ── Downloads ─────────────────────────────────────────────────────────────────

_DOWNLOAD_KEYS = {
    "baseline":      "out_baseline",
    "target":        "out_target",
    "supplementary": "out_supplementary",
    "contrast":      "out_contrast",
    "liftshift":     "out_liftshift",
}

@app.get("/api/session/{session_id}/download/{key}")
async def download_file(session_id: str, key: str):
    sess = _session(session_id)

    if key not in _DOWNLOAD_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown download key: {key!r}")

    path: Optional[Path] = sess.get(_DOWNLOAD_KEYS[key])
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail=f"File not yet generated for key: {key!r}")

    media = "application/json" if path.suffix == ".json" else \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(path=str(path), filename=path.name, media_type=media)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("""
╔══════════════════════════════════════════════════════╗
║        Archimedes AI — Wizard Server                 ║
║  URL: http://localhost:8767                          ║
║  Press Ctrl+C to stop                               ║
╚══════════════════════════════════════════════════════╝
""")
    import threading
    threading.Timer(1.2, lambda: webbrowser.open("http://localhost:8767")).start()
    uvicorn.run(app, host="127.0.0.1", port=8767, log_level="warning")
