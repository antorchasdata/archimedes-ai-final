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

# SAP Application → IT Components (technology stack, well-known SAP standard mapping)
# ITC name follows SAP LeanIX reference catalog conventions.
# Each tuple: (itc_name, hosting_type)
_APP_TO_ITCS: dict[str, list[tuple[str, str]]] = {
    "SAP S/4HANA": [
        ("SAP HANA Database", "onPremise"),
        ("SAP ABAP Platform", "onPremise"),
        ("SAP NetWeaver Application Server", "onPremise"),
        ("SAP Fiori", "onPremise"),
    ],
    "SAP S/4HANA Cloud": [
        ("SAP HANA Database", "saas"),
        ("SAP Business Technology Platform", "paas"),
        ("SAP Fiori", "saas"),
    ],
    "SAP Analytics Cloud": [
        ("SAP Business Technology Platform", "paas"),
        ("SAP HANA Database", "saas"),
    ],
    "SAP Integration Suite": [
        ("SAP Business Technology Platform", "paas"),
        ("SAP Cloud Integration", "paas"),
        ("SAP API Management", "paas"),
    ],
    "SAP Ariba Sourcing": [
        ("SAP Ariba Network", "saas"),
        ("SAP Business Technology Platform", "paas"),
    ],
    "SAP Ariba Procurement": [
        ("SAP Ariba Network", "saas"),
        ("SAP Business Technology Platform", "paas"),
    ],
    "SAP Integrated Business Planning": [
        ("SAP Business Technology Platform", "paas"),
        ("SAP HANA Database", "saas"),
    ],
    "SAP Transportation Management": [
        ("SAP HANA Database", "onPremise"),
        ("SAP ABAP Platform", "onPremise"),
        ("SAP NetWeaver Application Server", "onPremise"),
    ],
    "SAP Global Trade Services": [
        ("SAP HANA Database", "onPremise"),
        ("SAP ABAP Platform", "onPremise"),
        ("SAP NetWeaver Application Server", "onPremise"),
    ],
    "SAP SuccessFactors": [
        ("SAP Business Technology Platform", "paas"),
        ("SAP SuccessFactors Platform", "saas"),
    ],
    "SAP Concur": [
        ("SAP Business Technology Platform", "paas"),
    ],
    "SAP Fieldglass": [
        ("SAP Business Technology Platform", "paas"),
    ],
    "SAP Customer Experience": [
        ("SAP Business Technology Platform", "paas"),
        ("SAP Commerce Cloud", "saas"),
    ],
    "SAP ERP": [
        ("SAP HANA Database", "onPremise"),
        ("SAP ABAP Platform", "onPremise"),
        ("SAP NetWeaver Application Server", "onPremise"),
    ],
    "SAP Business One": [
        ("SAP HANA Database", "onPremise"),
    ],
    "SAP Datasphere": [
        ("SAP Business Technology Platform", "paas"),
        ("SAP HANA Database", "saas"),
    ],
}

def _itcs_for_apps(app_names: list[str]) -> list[tuple[str, str]]:
    """Return deduplicated (itc_name, hosting_type) tuples for a list of app names."""
    seen: set[str] = set()
    result = []
    for app in app_names:
        for itc_name, hosting in _APP_TO_ITCS.get(app, []):
            if itc_name not in seen:
                seen.add(itc_name)
                result.append((itc_name, hosting))
    return result

# ── Shared Excel formatting helpers ───────────────────────────────────────────

_COLOR_MANDATORY = "002A86"
_COLOR_OPTIONAL  = "0070F2"
_COLOR_RELATION  = "107E3E"
_COLOR_READONLY  = "A9B4BE"
_COLOR_TRANS_ROW = "EAF4FF"
_COLOR_DATA_ROW  = "F5F9FF"

_HEADER_COLORS = {
    "mandatory": _COLOR_MANDATORY,
    "optional":  _COLOR_OPTIONAL,
    "relation":  _COLOR_RELATION,
    "readonly":  _COLOR_READONLY,
}


def _sheet_header(ws: Any, columns: list[tuple[str, str, str, int]]) -> None:
    """
    Write LeanIX-format header rows to a worksheet.
    columns: list of (technical_key, translation, category, width)
    """
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    for col_idx, (key, label, cat, width) in enumerate(columns, start=1):
        c1 = ws.cell(row=1, column=col_idx, value=key)
        c1.font  = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
        c1.fill  = PatternFill("solid", fgColor=_HEADER_COLORS.get(cat, _COLOR_OPTIONAL))
        c1.alignment = Alignment(horizontal="left", vertical="center")

        c2 = ws.cell(row=2, column=col_idx, value=label)
        c2.font  = Font(name="Calibri", bold=True, color="223548", size=9)
        c2.fill  = PatternFill("solid", fgColor=_COLOR_TRANS_ROW)
        c2.alignment = Alignment(horizontal="left", vertical="center")

        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 18


def _sheet_row(ws: Any, row_idx: int, values: list, bg: str = _COLOR_DATA_ROW) -> None:
    from openpyxl.styles import Font, PatternFill, Alignment
    for col_idx, val in enumerate(values, start=1):
        c = ws.cell(row=row_idx, column=col_idx, value=val or "")
        c.font  = Font(name="Calibri", size=9, color="223548")
        c.fill  = PatternFill("solid", fgColor=bg)
        c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
    ws.row_dimensions[row_idx].height = 16


# ── Column schemas per fact sheet type ────────────────────────────────────────

# (technical_key, translation, category, width)
_COLS_APPLICATION = [
    ("id",                              "ID",                        "readonly",  36),
    ("type",                            "Type",                      "mandatory", 14),
    ("name",                            "Name",                      "mandatory", 40),
    ("description",                     "Description",               "optional",  55),
    ("alias",                           "Alias",                     "optional",  14),
    ("externalId",                      "External ID",               "optional",  18),
    ("lifecycle_phase",                 "Lifecycle Phase",           "optional",  16),
    ("lifecycle_startDate",             "Lifecycle Start Date",      "optional",  20),
    ("lifecycle_endDate",               "Lifecycle End Date",        "optional",  18),
    ("businessCriticality",             "Business Criticality",      "optional",  22),
    ("functionalSuitability",           "Functional Fit",            "optional",  20),
    ("technicalSuitability",            "Technical Fit",             "optional",  20),
    ("lxHostingType",                   "Hosting Type",              "optional",  18),
    ("lxState",                         "Quality Seal",              "optional",  14),
    ("tags",                            "Tags",                      "optional",  35),
    ("relApplicationToBusinessCapability", "Business Capabilities",  "relation",  60),
    ("relApplicationToITComponent",     "IT Components",             "relation",  45),
    ("relToParent",                     "Parent Application",        "relation",  30),
]

_COLS_BC = [
    ("id",          "ID",          "readonly",  36),
    ("type",        "Type",        "mandatory", 14),
    ("name",        "Name",        "mandatory", 55),
    ("description", "Description", "optional",  60),
    ("lxState",     "Quality Seal","optional",  14),
    ("tags",        "Tags",        "optional",  35),
    ("relToParent", "Parent BC",   "relation",  55),
]

_COLS_INITIATIVE = [
    ("id",                                  "ID",                        "readonly",  36),
    ("type",                                "Type",                      "mandatory", 14),
    ("name",                                "Name",                      "mandatory", 45),
    ("description",                         "Description",               "optional",  60),
    ("lifecycle_phase",                     "Lifecycle Phase",           "optional",  16),
    ("lxState",                             "Quality Seal",              "optional",  14),
    ("tags",                                "Tags",                      "optional",  35),
    ("relInitiativeToApplication",          "Applications",              "relation",  45),
    ("relInitiativeToBusinessCapability",   "Business Capabilities",     "relation",  60),
]

_COLS_ITC = [
    ("id",          "ID",          "readonly",  36),
    ("type",        "Type",        "mandatory", 14),
    ("name",        "Name",        "mandatory", 40),
    ("description", "Description", "optional",  55),
    ("lxHostingType","Hosting Type","optional",  18),
    ("lxState",     "Quality Seal","optional",  14),
    ("tags",        "Tags",        "optional",  35),
]


def write_leanix_excel(
    enriched: list[dict[str, Any]],
    bcs_index: dict[str, str],
    output_path: Path,
    client_name: str,
    supplementary: dict | None = None,
) -> None:
    """
    Write a LeanIX-importable multi-sheet Excel with proper format:

      Sheet "Application"         — deduplicated RSA apps (TO-BE)
      Sheet "BusinessCapability"  — deduplicated leaf BCs from requirements
      Sheet "Initiative"          — one row per requirement
      Sheet "ITComponent"         — ITCs where derivable
      Sheet "ReadMe"              — import instructions

    Row 1: technical keys (colored headers)
    Row 2: human-readable translations
    Row 3+: data rows

    supplementary: optional dict from pdf_extract / image_extract containing
      keys "from_pdf" and/or "from_images", each with lists "applications",
      "business_capabilities", "initiatives", "it_components". These are merged
      into the respective sheets (deduplicated by name).
    """
    import openpyxl

    # ── Collect data from enriched requirements ────────────────────────────────
    seen_apps: dict[str, dict] = {}   # app_name → {lifecycle, bcs, itcs}
    seen_bcs:  dict[str, str]  = {}   # bc_leaf_name → full_path
    _init_groups: dict[str, dict] = {}  # group_key → aggregated initiative data

    for req in enriched:
        if req.get("_error"):
            continue

        # Resolve BCs
        bcs_resolved: list[str] = []
        for bc_short in req.get("bcs", []):
            full_path = bcs_index.get(bc_short, bc_short)
            parts     = full_path.split(" / ")
            bc_leaf   = parts[-1] if parts else full_path
            seen_bcs[bc_leaf] = full_path
            bcs_resolved.append(bc_leaf)

        rsa_name = req.get("rsa", "SAP S/4HANA")
        lifecycle = _LIFECYCLE_MAP.get(req.get("coverage", ""), "plan")

        # Upsert application — collect ITCs from static mapping
        app_itcs = {itc for itc, _ in _APP_TO_ITCS.get(rsa_name, [])}
        if rsa_name not in seen_apps:
            seen_apps[rsa_name] = {
                "name":       rsa_name,
                "lifecycle":  lifecycle,
                "bcs":        set(bcs_resolved),
                "itcs":       app_itcs,
            }
        else:
            seen_apps[rsa_name]["bcs"].update(bcs_resolved)
            # promote lifecycle: active > phaseIn > plan
            order = {"active": 0, "phaseIn": 1, "plan": 2}
            if order.get(lifecycle, 2) < order.get(seen_apps[rsa_name]["lifecycle"], 2):
                seen_apps[rsa_name]["lifecycle"] = lifecycle

        # Accumulate initiative data, grouped by _group when present
        group_key = req.get("_group") or req["id"]
        if group_key not in _init_groups:
            _init_groups[group_key] = {
                "name":      group_key,
                "lifecycle": lifecycle,
                "apps":      set(),
                "bcs":       set(),
                "n_reqs":    0,
            }
        g = _init_groups[group_key]
        g["apps"].add(rsa_name)
        g["bcs"].update(bcs_resolved)
        g["n_reqs"] += 1
        # promote lifecycle: active > phaseIn > plan
        order = {"active": 0, "phaseIn": 1, "plan": 2}
        if order.get(lifecycle, 2) < order.get(g["lifecycle"], 2):
            g["lifecycle"] = lifecycle

    # Build initiative list from grouped data
    initiatives: list[dict] = []
    for group_key, g in _init_groups.items():
        initiatives.append({
            "name":      g["name"],
            "description": f"{g['n_reqs']} requirements — client: {client_name}",
            "lifecycle": g["lifecycle"],
            "app":       ";".join(sorted(g["apps"])),
            "bcs":       ";".join(sorted(g["bcs"])),
        })

    # Build deduplicated ITC list from all seen apps
    seen_itcs: dict[str, str] = {}  # itc_name → hosting_type
    for app_name in seen_apps:
        for itc_name, hosting in _APP_TO_ITCS.get(app_name, []):
            if itc_name not in seen_itcs:
                seen_itcs[itc_name] = hosting

    # ── Merge supplementary fact sheets (from PDF / images) ───────────────────
    supp_initiatives: list[dict] = []
    if supplementary:
        for source_key in ("from_pdf", "from_images"):
            source = supplementary.get(source_key, {})
            if not source:
                continue

            for app in source.get("applications", []):
                name = (app.get("name") or "").strip()
                if name and name not in seen_apps:
                    seen_apps[name] = {
                        "name":      name,
                        "lifecycle": "plan",
                        "bcs":       set(),
                        "itcs":      set(),
                    }

            for bc in source.get("business_capabilities", []):
                name = (bc.get("name") or "").strip()
                if name and name not in seen_bcs:
                    seen_bcs[name] = bc.get("path") or name

            for itc in source.get("it_components", []):
                name = (itc.get("name") or "").strip()
                if name and name not in seen_itcs:
                    seen_itcs[name] = itc.get("hosting_type") or "onPremise"

            for init in source.get("initiatives", []):
                name = (init.get("name") or "").strip()
                if name:
                    supp_initiatives.append({
                        "name":      name,
                        "description": (init.get("description") or f"Derived from {source_key}. Client: {client_name}.")[:2000],
                        "lifecycle": init.get("lifecycle_phase") or "plan",
                        "app":       init.get("relInitiativeToApplication") or "",
                        "bcs":       init.get("relInitiativeToBusinessCapability") or "",
                    })

        if supplementary:
            logger.info(
                "Supplementary merged: +%d apps, +%d BCs, +%d ITCs, +%d initiatives",
                sum(len(supplementary.get(k, {}).get("applications", [])) for k in ("from_pdf", "from_images")),
                sum(len(supplementary.get(k, {}).get("business_capabilities", [])) for k in ("from_pdf", "from_images")),
                sum(len(supplementary.get(k, {}).get("it_components", [])) for k in ("from_pdf", "from_images")),
                len(supp_initiatives),
            )

    tags = "Target"
    wb = openpyxl.Workbook()

    # ── Sheet: Application ─────────────────────────────────────────────────────
    ws_app = wb.active
    ws_app.title = "Application"
    ws_app.freeze_panes = "C3"
    _sheet_header(ws_app, _COLS_APPLICATION)
    keys_app = [c[0] for c in _COLS_APPLICATION]

    for row_idx, (app_name, app) in enumerate(sorted(seen_apps.items()), start=3):
        bcs_str  = ";".join(sorted(app["bcs"]))
        itcs_str = ";".join(sorted(app.get("itcs", set())))
        vals = {
            "id": "", "type": "Application", "name": app_name,
            "description": f"TO-BE application derived from requirements analysis. Client: {client_name}.",
            "alias": "", "externalId": "",
            "lifecycle_phase": "plan", "lifecycle_startDate": "", "lifecycle_endDate": "",
            "businessCriticality": "businessCritical", "functionalSuitability": "",
            "technicalSuitability": "", "lxHostingType": "saas", "lxState": "DRAFT",
            "tags": tags,
            "relApplicationToBusinessCapability": bcs_str,
            "relApplicationToITComponent": itcs_str, "relToParent": "",
        }
        _sheet_row(ws_app, row_idx, [vals.get(k, "") for k in keys_app])

    # ── Sheet: BusinessCapability ──────────────────────────────────────────────
    ws_bc = wb.create_sheet("BusinessCapability")
    ws_bc.freeze_panes = "C3"
    _sheet_header(ws_bc, _COLS_BC)
    keys_bc = [c[0] for c in _COLS_BC]

    for row_idx, (bc_leaf, full_path) in enumerate(sorted(seen_bcs.items()), start=3):
        parts  = full_path.split(" / ")
        parent = " / ".join(parts[:-1]) if len(parts) > 1 else ""
        vals = {
            "id": "", "type": "BusinessCapability", "name": bc_leaf,
            "description": full_path,
            "lxState": "DRAFT", "tags": tags, "relToParent": parent,
        }
        _sheet_row(ws_bc, row_idx, [vals.get(k, "") for k in keys_bc])

    # ── Sheet: Initiative ──────────────────────────────────────────────────────
    ws_init = wb.create_sheet("Initiative")
    ws_init.freeze_panes = "C3"
    _sheet_header(ws_init, _COLS_INITIATIVE)
    keys_init = [c[0] for c in _COLS_INITIATIVE]

    for row_idx, init in enumerate(initiatives + supp_initiatives, start=3):
        vals = {
            "id": "", "type": "Initiative", "name": init["name"],
            "description": init["description"],
            "lifecycle_phase": init["lifecycle"],
            "lxState": "DRAFT", "tags": tags,
            "relInitiativeToApplication":        init["app"],
            "relInitiativeToBusinessCapability": init["bcs"],
        }
        _sheet_row(ws_init, row_idx, [vals.get(k, "") for k in keys_init])

    # ── Sheet: ITComponent ─────────────────────────────────────────────────────
    ws_itc = wb.create_sheet("ITComponent")
    ws_itc.freeze_panes = "C3"
    _sheet_header(ws_itc, _COLS_ITC)
    keys_itc = [c[0] for c in _COLS_ITC]

    for row_idx, (itc_name, hosting) in enumerate(sorted(seen_itcs.items()), start=3):
        vals = {
            "id": "", "type": "ITComponent", "name": itc_name,
            "description": f"SAP technology component supporting TO-BE applications. Client: {client_name}.",
            "lxHostingType": hosting, "lxState": "DRAFT", "tags": tags,
        }
        _sheet_row(ws_itc, row_idx, [vals.get(k, "") for k in keys_itc])

    # ── Sheet: ReadMe ──────────────────────────────────────────────────────────
    readme = wb.create_sheet("ReadMe")
    from openpyxl.styles import Font, Alignment
    readme_rows = [
        (f"LeanIX Import — Target TO-BE ({client_name})", True,  "002A86", 13),
        ("Source: Requirements analysis via Archimedes AI + SAP RBA/RSA catalogs", False, "223548", 9),
        ("", False, "223548", 9),
        ("IMPORT ORDER", True, "002A86", 10),
        ("1. BusinessCapability", False, "223548", 9),
        ("2. ITComponent", False, "223548", 9),
        ("3. Application", False, "223548", 9),
        ("4. Initiative", False, "223548", 9),
        ("", False, "223548", 9),
        ("IMPORT RULES", True, "002A86", 10),
        ("- Leave 'id' column EMPTY — new fact sheets will be created.", False, "223548", 9),
        ("- Relations use EXACT display names of existing LeanIX fact sheets.", False, "223548", 9),
        ("- Multiple relation values separated by semicolon (;) without spaces.", False, "223548", 9),
        ("- 'lxState' = DRAFT — approve manually after review.", False, "223548", 9),
        ("- Import via: Inventory > Inventory Tools > Import from Excel", False, "223548", 9),
        ("", False, "223548", 9),
        ("STATS", True, "002A86", 10),
        (f"Applications: {len(seen_apps)}", False, "223548", 9),
        (f"Business Capabilities: {len(seen_bcs)}", False, "223548", 9),
        (f"IT Components: {len(seen_itcs)}", False, "223548", 9),
        (f"Initiatives: {len(initiatives) + len(supp_initiatives)}", False, "223548", 9),
    ]
    for r_idx, (text, bold, color, size) in enumerate(readme_rows, start=1):
        c = readme.cell(row=r_idx, column=1, value=text)
        c.font = Font(name="Calibri", size=size, bold=bold, color=color)
        c.alignment = Alignment(horizontal="left", wrap_text=True)
    readme.column_dimensions["A"].width = 80

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
    logger.info(
        "LeanIX target: %d apps, %d BCs, %d initiatives → %s",
        len(seen_apps), len(seen_bcs), len(initiatives), output_path,
    )


# ── LeanIX writer ─────────────────────────────────────────────────────────────

# GraphQL fragments reused across mutations
_QUERY_FS_BY_NAME = """
query FindFS($type: String!, $name: String!) {
  allFactSheets(
    filter: {
      facetFilters: [{ facetKey: "FactSheetTypes", keys: [$type] }]
      fullTextSearch: $name
    }
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
mutation CreateFS($type: FactSheetType!, $name: String!) {
  createFactSheet(input: { type: $type, name: $name }) {
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

_QUERY_TAGS = """
query GetTags {
  allTags { edges { node { id name } } }
}
"""

_QUERY_TAG_GROUPS = """
query GetTagGroups {
  allTagGroups { edges { node { id name restrictToFactSheetTypes } } }
}
"""

_MUTATION_CREATE_TAG = """
mutation CreateTag($name: String!, $groupId: ID) {
  createTag(name: $name, tagGroupId: $groupId) {
    id name
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
mutation CreateRelation($from: ID!, $to: ID!, $relType: RelationName!) {
  upsertRelation(
    from: { id: $from }
    to: { id: $to }
    type: $relType
  ) { fromFactSheetId }
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
        result = _gql(_QUERY_TAGS, {})
        for edge in result.get("data", {}).get("allTags", {}).get("edges", []):
            if edge["node"]["name"] == tag_name:
                return edge["node"]["id"]
        # Pick first unrestricted tag group
        groups_result = _gql(_QUERY_TAG_GROUPS, {})
        edges = groups_result.get("data", {}).get("allTagGroups", {}).get("edges", [])
        group_id = None
        for e in edges:
            if not e["node"].get("restrictToFactSheetTypes"):
                group_id = e["node"]["id"]
                break
        if group_id is None and edges:
            group_id = edges[0]["node"]["id"]
        result = _gql(_MUTATION_CREATE_TAG, {"name": tag_name, "groupId": group_id})
        return result["data"]["createTag"]["id"]

    def _tag_fs(fs_id: str, tag_id: str) -> None:
        try:
            _gql(_MUTATION_ADD_TAG, {
                "id": fs_id,
                "patches": [{"op": "add", "path": "/tags",
                             "value": json.dumps([{"tagId": tag_id}])}],
            })
        except Exception as exc:
            logger.warning("LeanIX: skipping tag for %s — %s", fs_id, exc)

    # ── Fact sheet helpers ────────────────────────────────────────────────────
    def _find_by_name(fs_type: str, name: str) -> str | None:
        result = _gql(_QUERY_FS_BY_NAME, {"type": fs_type, "name": name})
        for edge in result["data"]["allFactSheets"]["edges"]:
            if edge["node"]["displayName"] == name:
                return edge["node"]["id"]
        return None

    def _create_fs(fs_type: str, name: str, desc: str = "") -> str:
        result = _gql(_MUTATION_CREATE_FS, {"type": fs_type, "name": name})
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
                         "value": json.dumps({"phases": [{"phase": phase}]})}],
        })

    def _create_relation(from_id: str, to_id: str, rel_type: str) -> None:
        _gql(_MUTATION_CREATE_RELATION,
             {"from": from_id, "to": to_id, "relType": rel_type})

    # ── Read staging Excel ────────────────────────────────────────────────────
    wb = openpyxl.load_workbook(str(staging_path))

    def _sheet_rows(sheet_name: str) -> list[dict]:
        # Accept both plural (old format) and singular (new format) sheet names
        _singular = {
            "Initiatives": "Initiative",
            "Applications": "Application",
            "BusinessCapabilities": "BusinessCapability",
        }
        name = sheet_name if sheet_name in wb.sheetnames else _singular.get(sheet_name, sheet_name)
        ws     = wb[name]
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
        # Set lifecycle if present
        lc = row.get("lifecycle_phase") or row.get("lifecycle")
        if lc:
            _set_lifecycle(app_id, str(lc).strip())
        # Link → BCs
        bc_rel_raw = row.get("relApplicationToBusinessCapability") or ""
        for bc_name in str(bc_rel_raw).split(","):
            bc_name = bc_name.strip()
            if bc_name and bc_name in bc_id_cache:
                _create_relation(app_id, bc_id_cache[bc_name],
                                 "relApplicationToBusinessCapability")
        logger.debug("LeanIX App %s '%s'", "created" if created else "found", name)

    # 3. Upsert Initiatives + relations
    pushed = failed = 0
    for row in init_rows:
        req_id = str(row.get("id", "")).strip()
        if not req_id:
            continue
        try:
            init_name = str(row.get("name", req_id)).strip()
            initiative_id, created = _upsert(
                "Initiative",
                init_name,
                desc=str(row.get("description", "")),
            )
            if created:
                _tag_fs(initiative_id, tag_id)

            # lifecycle — accept both column names
            lifecycle_val = (
                row.get("lifecycle_phase") or row.get("lifecycle") or "plan"
            )
            _set_lifecycle(initiative_id, str(lifecycle_val).strip())

            # Link → BCs — accept both column names
            bcs_raw = row.get("relInitiativeToBusinessCapability") or row.get("bcs") or ""
            for bc_name in str(bcs_raw).split(","):
                bc_name = bc_name.strip()
                if bc_name and bc_name in bc_id_cache:
                    _create_relation(initiative_id, bc_id_cache[bc_name],
                                     "relInitiativeToBusinessCapability")

            # Link → Application — accept both column names
            rsa_name = (
                row.get("relInitiativeToApplication") or row.get("rsa") or ""
            )
            rsa_name = str(rsa_name).strip()
            if rsa_name and rsa_name in app_id_cache:
                _create_relation(initiative_id, app_id_cache[rsa_name],
                                 "relInitiativeToApplication")

            logger.info("LeanIX: %s initiative '%s'", "created" if created else "updated", init_name)
            pushed += 1

        except Exception as exc:
            logger.error("LeanIX: failed to push %s — %s", req_id, exc)
            failed += 1

    logger.info("LeanIX push complete: %d pushed, %d failed", pushed, failed)


# ── Main ──────────────────────────────────────────────────────────────────────

def write_leanix_excel_from_xlsx(
    enriched_xlsx: Path,
    output_path: Path,
    client_name: str,
    header_row: int = 8,
    data_start_row: int = 9,
    supplementary: dict | None = None,
) -> None:
    """
    Generate a LeanIX-importable Excel directly from an enriched Requerimientos Excel
    (as produced by map_requirements.py).

    Column mapping (1-based):
      B(2)=req_id, H(8)=coverage, I(9)=module, N(14)=comment, O(15)=BCs full path, P(16)=RSA app

    BCs are stored as full paths separated by ' | ', e.g.:
      'Corporate / Finance / Accounting and Financial Close | Corporate / Asset Management / ...'

    RSA column may contain comma-separated canonical app names, e.g.:
      'SAP S/4HANA, SAP Analytics Cloud' → two separate Application rows.
    Each name is resolved against the RSA catalog name_index for exact canonical spelling.
    """
    import openpyxl as _xl

    # Load RSA name_index for canonical resolution: lowercase → canonical
    rsa_catalog   = json.loads((KNOWLEDGE_DIR / "sap_rsa_catalog.json").read_text())
    rsa_name_index = rsa_catalog.get("name_index", {})  # {lowercase: canonical}

    def _canonical_rsa(name: str) -> str:
        """Return exact canonical RSA name, or original if not found in catalog."""
        return rsa_name_index.get(name.strip().lower(), name.strip())

    wb_in = _xl.load_workbook(str(enriched_xlsx))
    ws_in = wb_in.active

    enriched: list[dict] = []
    for r in range(data_start_row, ws_in.max_row + 1):
        req_id   = ws_in.cell(r, 2).value
        proceso  = ws_in.cell(r, 1).value   # col A = proceso (initiative group)
        coverage = ws_in.cell(r, 8).value
        module   = ws_in.cell(r, 9).value
        comment  = ws_in.cell(r, 14).value
        bcs_raw  = ws_in.cell(r, 15).value
        rsa_raw  = ws_in.cell(r, 16).value
        if not req_id:
            continue

        # Parse BCs: 'Domain / Area / Leaf | Domain / Area / Leaf2'
        bcs_parsed: list[str] = []
        if bcs_raw:
            for part in str(bcs_raw).split("|"):
                part = part.strip()
                segments = [s.strip() for s in part.split("/")]
                if len(segments) >= 2:
                    bcs_parsed.append(part)   # keep full path for resolution

        # Split comma-separated RSA string into individual canonical app names
        rsa_apps: list[str] = []
        if rsa_raw:
            for part in str(rsa_raw).split(","):
                canonical = _canonical_rsa(part.strip())
                if canonical:
                    rsa_apps.append(canonical)
        if not rsa_apps:
            rsa_apps = ["SAP S/4HANA"]

        # Group key: use proceso (col A) as initiative grouping
        group = str(proceso or "").strip() or str(req_id).strip()

        # Emit one record per canonical RSA app (same BCs apply to all)
        for app_name in rsa_apps:
            enriched.append({
                "id":       str(req_id).strip(),
                "_group":   group,
                "coverage": str(coverage or ""),
                "module":   str(module or ""),
                "comment":  str(comment or "")[:2000],
                "bcs_full": bcs_parsed,
                "rsa":      app_name,
            })

    # Build intermediate enriched dicts compatible with write_leanix_excel
    # Map full BC paths to leaf names
    def _leaf(full_path: str) -> str:
        parts = [s.strip() for s in full_path.split("/")]
        return parts[-1] if parts else full_path

    bcs_index_full: dict[str, str] = {}   # leaf → full_path (deduplicated)
    enriched_compat: list[dict] = []

    for row in enriched:
        bc_leaves = []
        for fp in row["bcs_full"]:
            leaf = _leaf(fp)
            bcs_index_full[leaf] = fp
            bc_leaves.append(leaf)
        enriched_compat.append({
            "id":       row["id"],
            "_group":   row.get("_group", row["id"]),
            "bcs":      bc_leaves,
            "rsa":      row["rsa"],
            "coverage": row["coverage"],
            "comment":  row["comment"],
            "module":   row["module"],
        })

    write_leanix_excel(enriched_compat, bcs_index_full, output_path, client_name, supplementary=supplementary)


def write(
    enriched_path: str | Path,
    template_path: str | Path,
    output_dir: str | Path = "output",
    client_name: str = "unknown",
    supplementary: dict | None = None,
) -> tuple[Path, Path]:
    """
    Run the write step:
      1. Write client Excel (columns H–P on original template)  → <stem>_enriched.xlsx
      2. Write LeanIX importable Excel (multi-sheet, formatted) → <client>_target_leanix.xlsx

    Returns (client_excel_path, leanix_target_path).
    Push to LeanIX separately with push_leanix().
    """
    enriched_path = Path(enriched_path)
    template_path = Path(template_path)
    output_dir    = Path(output_dir)

    enriched  = json.loads(enriched_path.read_text())
    bcs_index = _load_bcs_index()

    out_excel  = output_dir / f"{template_path.stem}_enriched.xlsx"
    out_target = output_dir / f"{client_name}_target_leanix.xlsx"

    write_excel(enriched, template_path, out_excel, bcs_index)
    write_leanix_excel(enriched, bcs_index, out_target, client_name, supplementary=supplementary)

    return out_excel, out_target


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
