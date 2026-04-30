"""
write.py — Write enriched requirements to Excel and optionally to LeanIX.

Excel output:
  - Writes columns H–P onto the original Excel file (preserving all other columns)
  - Auto-detects the ID column and header row (same logic as extract.py)

LeanIX output (optional, --push-leanix / LEANIX_PUSH=true):
  EA model per requirement:
    Initiative  (one per requirement)
      ├─ relInitiativeToBusinessCapability → BusinessCapability (leaf BC, upsert)
      └─ relInitiativeToApplication        → Application (one per RSA, upsert)

  All fact sheets created by this pipeline carry a tag  client=<name>
  so they can be filtered and cleaned up after a demo.

  Lifecycle derived from coverage:
    Total      → active
    Parcial    → phaseIn
    No cubierto → plan

Requires env vars: LEANIX_API_TOKEN, LEANIX_WORKSPACE_ID, LEANIX_BASE_URL
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"

# Column indices in the output Excel (0-based), matching the project standard
COL_H = 7   # coverage
COL_I = 8   # module
COL_J = 9   # dev
COL_K = 10  # dev_exp
COL_L = 11  # ext_apps
COL_M = 12  # licensing
COL_N = 13  # comment
COL_O = 14  # Business Capabilities (SAP RBA)
COL_P = 15  # RSA application

_ID_PATTERNS = re.compile(r"\b(id|req|requ|n[oº°]|num|code|ref)\b", re.I)


# ── BCS resolution ────────────────────────────────────────────────────────────

def _load_bcs_index() -> dict[str, str]:
    rba = json.loads((KNOWLEDGE_DIR / "sap_rba_catalog.json").read_text())
    return rba["short_name_index"]


def bc_str(names: list[str], index: dict[str, str]) -> str:
    return " | ".join(index.get(n, n) for n in names)


# ── Excel writer ──────────────────────────────────────────────────────────────

def _detect_header_row(path: Path) -> int:
    raw = pd.read_excel(path, header=None, nrows=15)
    for i, row in raw.iterrows():
        non_null = row.dropna()
        if len(non_null) >= 2 and all(isinstance(v, str) for v in non_null):
            return int(i)
    return 0


def write_excel(
    enriched: list[dict[str, Any]],
    template_path: Path,
    output_path: Path,
    bcs_index: dict[str, str],
) -> None:
    header_row = _detect_header_row(template_path)
    df = pd.read_excel(template_path, header=None)

    # Build lookup: id → enriched dict
    lookup = {r["id"]: r for r in enriched}

    # Find ID column
    header = df.iloc[header_row]
    id_col_idx = next(
        (i for i, v in enumerate(header) if _ID_PATTERNS.search(str(v))),
        1,  # default to col B (index 1) matching original project convention
    )

    data_start = header_row + 1
    filled = 0

    for idx in range(data_start, len(df)):
        cell = df.iloc[idx, id_col_idx]
        if pd.isna(cell):
            continue
        row_id = str(cell).strip()
        if row_id not in lookup:
            continue

        m = lookup[row_id]
        df.iloc[idx, COL_H] = m.get("coverage", "")
        df.iloc[idx, COL_I] = m.get("module", "")
        df.iloc[idx, COL_J] = m.get("dev", "")
        df.iloc[idx, COL_K] = m.get("dev_exp") or float("nan")
        df.iloc[idx, COL_L] = m.get("ext_apps") or float("nan")
        df.iloc[idx, COL_M] = m.get("licensing", "")
        df.iloc[idx, COL_N] = m.get("comment", "")
        df.iloc[idx, COL_O] = bc_str(m.get("bcs", []), bcs_index)
        df.iloc[idx, COL_P] = m.get("rsa", "")
        filled += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(str(output_path), engine="openpyxl") as writer:
        df.to_excel(writer, index=False, header=False)

    logger.info("Excel: wrote %d rows → %s", filled, output_path)


# ── LeanIX staging Excel ──────────────────────────────────────────────────────

# coverage → Initiative lifecycle phase (also used by the push step)
_LIFECYCLE_MAP = {
    "Total":        "active",
    "Parcial":      "phaseIn",
    "No cubierto":  "plan",
}


def write_leanix_excel(
    enriched: list[dict[str, Any]],
    bcs_index: dict[str, str],
    output_path: Path,
    client_name: str,
) -> None:
    """
    Write a three-sheet Excel staging file for LeanIX import:

      Sheet "Initiatives"         — one row per requirement
      Sheet "BusinessCapabilities"— deduplicated leaf BCs
      Sheet "Applications"        — deduplicated RSA application names

    The file can be reviewed and hand-edited before pushing to LeanIX with
    `run.py --push-leanix <file> --client <name>`.
    """
    import openpyxl  # local import — only needed for staging Excel

    rows_init: list[dict] = []
    seen_bcs:  dict[str, str] = {}   # leaf_bc_name → full_path
    seen_apps: set[str]       = set()

    for req in enriched:
        if req.get("_error"):
            continue

        # Resolve BCs
        bcs_resolved: list[str] = []
        for bc_short in req.get("bcs", []):
            full_path  = bcs_index.get(bc_short, bc_short)
            _, _, leaf = full_path.partition(" / ")
            bc_name    = leaf or full_path
            seen_bcs[bc_name] = full_path
            bcs_resolved.append(bc_name)

        rsa_name = req.get("rsa", "SAP S/4HANA")
        seen_apps.add(rsa_name)

        rows_init.append({
            "id":          req["id"],
            "name":        req["id"],
            "description": req.get("comment", "")[:2000],
            "module":      req.get("module", ""),
            "coverage":    req.get("coverage", ""),
            "dev":         req.get("dev", ""),
            "licensing":   req.get("licensing", ""),
            "lifecycle":   _LIFECYCLE_MAP.get(req.get("coverage", ""), "plan"),
            "rsa":         rsa_name,
            "bcs":         ", ".join(bcs_resolved),
            "client":      client_name,
        })

    wb = openpyxl.Workbook()

    # Sheet 1 — Initiatives
    ws_init = wb.active
    ws_init.title = "Initiatives"
    init_cols = ["id", "name", "description", "module", "coverage", "dev",
                 "licensing", "lifecycle", "rsa", "bcs", "client"]
    ws_init.append(init_cols)
    for row in rows_init:
        ws_init.append([row[c] for c in init_cols])

    # Sheet 2 — BusinessCapabilities
    ws_bc = wb.create_sheet("BusinessCapabilities")
    ws_bc.append(["name", "full_path", "client"])
    for bc_name, full_path in sorted(seen_bcs.items()):
        ws_bc.append([bc_name, full_path, client_name])

    # Sheet 3 — Applications
    ws_app = wb.create_sheet("Applications")
    ws_app.append(["name", "client"])
    for app_name in sorted(seen_apps):
        ws_app.append([app_name, client_name])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
    logger.info(
        "LeanIX staging: %d initiatives, %d BCs, %d applications → %s",
        len(rows_init), len(seen_bcs), len(seen_apps), output_path,
    )


# ── LeanIX writer ─────────────────────────────────────────────────────────────

# GraphQL fragments reused across mutations
_QUERY_FS_BY_NAME = """
query FindFS($type: FactSheetType!, $name: String!) {
  allFactSheets(
    factSheetType: $type
    filter: { fullTextSearch: $name }
  ) {
    edges {
      node {
        id
        displayName
      }
    }
  }
}
"""

_MUTATION_CREATE_FS = """
mutation CreateFS($type: FactSheetType!, $name: String!, $desc: String!) {
  createFactSheet(input: { type: $type, name: $name, description: $desc }) {
    factSheet { id displayName }
  }
}
"""

_MUTATION_ADD_TAG = """
mutation AddTag($id: ID!, $patches: [Patch]!) {
  updateFactSheet(id: $id, patches: $patches) {
    factSheet { id }
  }
}
"""

_MUTATION_SET_LIFECYCLE = """
mutation SetLifecycle($id: ID!, $patches: [Patch]!) {
  updateFactSheet(id: $id, patches: $patches) {
    factSheet { id }
  }
}
"""

_MUTATION_CREATE_RELATION = """
mutation CreateRelation($from: ID!, $to: ID!, $relType: String!) {
  createRelation(
    factSheetId: $from
    relationType: $relType
    targetFactSheetId: $to
  ) { id }
}
"""


def write_leanix(
    staging_path: Path,
    client_name: str,
) -> None:
    """
    Push a LeanIX staging Excel (generated by write_leanix_excel) to LeanIX.

    Reads the three sheets — Initiatives, BusinessCapabilities, Applications —
    and upserts the corresponding fact sheets and relations.

    Call after reviewing/editing output/<stem>_leanix_import.xlsx.
    """
    import requests
    import openpyxl

    base_url = os.environ["LEANIX_BASE_URL"].rstrip("/")
    token    = os.environ["LEANIX_API_TOKEN"]

    # ── Authenticate ──────────────────────────────────────────────────────────
    auth_resp = requests.post(
        f"{base_url}/services/mtm/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=("apitoken", token),
        timeout=30,
    )
    auth_resp.raise_for_status()
    bearer  = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}
    gql_url = f"{base_url}/services/pathfinder/v1/graphql"

    def _gql(query: str, variables: dict) -> dict:
        resp = requests.post(
            gql_url,
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        return data

    # ── Tag ───────────────────────────────────────────────────────────────────
    def _get_or_create_tag_id(tag_name: str) -> str:
        tags_resp = requests.get(
            f"{base_url}/services/pathfinder/v1/tags",
            headers=headers, timeout=30,
        )
        tags_resp.raise_for_status()
        for tag in tags_resp.json().get("data", []):
            if tag.get("name") == tag_name:
                return tag["id"]
        groups_resp = requests.get(
            f"{base_url}/services/pathfinder/v1/tagGroups",
            headers=headers, timeout=30,
        )
        groups_resp.raise_for_status()
        groups   = groups_resp.json().get("data", [])
        group_id = groups[0]["id"] if groups else None
        create   = requests.post(
            f"{base_url}/services/pathfinder/v1/tags",
            json={"name": tag_name, "tagGroupId": group_id},
            headers=headers, timeout=30,
        )
        create.raise_for_status()
        return create.json()["data"]["id"]

    def _tag_fs(fs_id: str, tag_id: str) -> None:
        _gql(_MUTATION_ADD_TAG, {
            "id": fs_id,
            "patches": [{"op": "add", "path": "/tags",
                         "value": json.dumps([{"tagId": tag_id}])}],
        })

    # ── Fact sheet helpers ────────────────────────────────────────────────────
    def _find_by_name(fs_type: str, name: str) -> str | None:
        result = _gql(_QUERY_FS_BY_NAME, {"type": fs_type, "name": name})
        for edge in result["data"]["allFactSheets"]["edges"]:
            if edge["node"]["displayName"] == name:
                return edge["node"]["id"]
        return None

    def _create_fs(fs_type: str, name: str, desc: str = "") -> str:
        result = _gql(_MUTATION_CREATE_FS, {"type": fs_type, "name": name, "desc": desc[:2000]})
        return result["data"]["createFactSheet"]["factSheet"]["id"]

    def _upsert(fs_type: str, name: str, desc: str = "") -> tuple[str, bool]:
        existing = _find_by_name(fs_type, name)
        if existing:
            return existing, False
        return _create_fs(fs_type, name, desc), True

    def _set_lifecycle(fs_id: str, phase: str) -> None:
        _gql(_MUTATION_SET_LIFECYCLE, {
            "id": fs_id,
            "patches": [{"op": "add", "path": "/lifecycle",
                         "value": json.dumps({"asIs": {"phase": phase}})}],
        })

    def _create_relation(from_id: str, to_id: str, rel_type: str) -> None:
        _gql(_MUTATION_CREATE_RELATION,
             {"from": from_id, "to": to_id, "relType": rel_type})

    # ── Read staging Excel ────────────────────────────────────────────────────
    wb = openpyxl.load_workbook(str(staging_path))

    def _sheet_rows(sheet_name: str) -> list[dict]:
        ws     = wb[sheet_name]
        header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        return [
            {header[i]: (cell.value or "") for i, cell in enumerate(row)}
            for row in ws.iter_rows(min_row=2)
            if any(cell.value for cell in row)
        ]

    init_rows = _sheet_rows("Initiatives")
    bc_rows   = _sheet_rows("BusinessCapabilities")
    app_rows  = _sheet_rows("Applications")

    # ── Push ──────────────────────────────────────────────────────────────────
    client_tag = f"client={client_name}"
    tag_id     = _get_or_create_tag_id(client_tag)
    logger.info("LeanIX: using tag '%s' (id=%s)", client_tag, tag_id)

    # 1. Upsert BusinessCapabilities
    bc_id_cache: dict[str, str] = {}
    for row in bc_rows:
        name = str(row["name"]).strip()
        if not name:
            continue
        bc_id, created = _upsert("BusinessCapability", name)
        bc_id_cache[name] = bc_id
        if created:
            _tag_fs(bc_id, tag_id)
        logger.debug("LeanIX BC %s '%s'", "created" if created else "found", name)

    # 2. Upsert Applications
    app_id_cache: dict[str, str] = {}
    for row in app_rows:
        name = str(row["name"]).strip()
        if not name:
            continue
        app_id, created = _upsert("Application", name)
        app_id_cache[name] = app_id
        if created:
            _tag_fs(app_id, tag_id)
        logger.debug("LeanIX App %s '%s'", "created" if created else "found", name)

    # 3. Create Initiatives + relations
    pushed = failed = 0
    for row in init_rows:
        req_id = str(row.get("id", "")).strip()
        if not req_id:
            continue
        try:
            initiative_id = _create_fs(
                "Initiative",
                str(row.get("name", req_id)).strip(),
                desc=str(row.get("description", "")),
            )
            _tag_fs(initiative_id, tag_id)
            _set_lifecycle(initiative_id, str(row.get("lifecycle", "plan")).strip())

            # Link → BCs
            for bc_name in str(row.get("bcs", "")).split(","):
                bc_name = bc_name.strip()
                if bc_name and bc_name in bc_id_cache:
                    _create_relation(initiative_id, bc_id_cache[bc_name],
                                     "relInitiativeToBusinessCapability")

            # Link → Application
            rsa_name = str(row.get("rsa", "")).strip()
            if rsa_name and rsa_name in app_id_cache:
                _create_relation(initiative_id, app_id_cache[rsa_name],
                                 "relInitiativeToApplication")

            logger.info("LeanIX: pushed %s", req_id)
            pushed += 1

        except Exception as exc:
            logger.error("LeanIX: failed to push %s — %s", req_id, exc)
            failed += 1

    logger.info("LeanIX push complete: %d pushed, %d failed", pushed, failed)


# ── Main ──────────────────────────────────────────────────────────────────────

def write(
    enriched_path: str | Path,
    template_path: str | Path,
    output_dir: str | Path = "output",
    client_name: str = "unknown",
) -> tuple[Path, Path]:
    """
    Run the write step:
      1. Write client Excel (columns H–P on original template)
      2. Write LeanIX staging Excel (three-sheet import file)

    Returns (client_excel_path, leanix_staging_path).
    Push to LeanIX separately with push_leanix().
    """
    enriched_path = Path(enriched_path)
    template_path = Path(template_path)
    output_dir    = Path(output_dir)

    enriched  = json.loads(enriched_path.read_text())
    bcs_index = _load_bcs_index()

    out_excel   = output_dir / f"{template_path.stem}_enriched.xlsx"
    out_staging = output_dir / f"{client_name}_leanix_import.xlsx"

    write_excel(enriched, template_path, out_excel, bcs_index)
    write_leanix_excel(enriched, bcs_index, out_staging, client_name)

    return out_excel, out_staging


def push_leanix(staging_path: str | Path, client_name: str) -> None:
    """Push a previously generated LeanIX staging Excel to LeanIX."""
    write_leanix(Path(staging_path), client_name)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_write = sub.add_parser("write", help="Generate Excel outputs")
    p_write.add_argument("enriched")
    p_write.add_argument("template")
    p_write.add_argument("--output-dir", default="output")
    p_write.add_argument("--client", default="unknown")

    p_push = sub.add_parser("push", help="Push staging Excel to LeanIX")
    p_push.add_argument("staging")
    p_push.add_argument("--client", default="unknown")

    args = ap.parse_args()
    if args.cmd == "write":
        out, staging = write(args.enriched, args.template, args.output_dir, args.client)
        print(f"Client Excel  → {out}")
        print(f"LeanIX import → {staging}")
    else:
        push_leanix(args.staging, args.client)
        print("LeanIX push complete.")
