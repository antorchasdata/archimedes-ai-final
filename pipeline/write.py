"""
04_write.py — Write enriched requirements to Excel and optionally to LeanIX.

Excel output:
  - Writes columns H–P onto the original Excel file (preserving all other columns)
  - Auto-detects the ID column and header row (same logic as 01_extract.py)

LeanIX output (optional, set LEANIX_PUSH=true):
  - Creates / updates Application fact sheets
  - Links them to Business Capability fact sheets (creates BCs if missing)
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


# ── LeanIX writer ─────────────────────────────────────────────────────────────

def write_leanix(enriched: list[dict[str, Any]], bcs_index: dict[str, str]) -> None:
    """
    Push enriched requirements to LeanIX:
      - Upsert Application fact sheets (one per requirement)
      - Upsert Business Capability fact sheets (from bcs field)
      - Link Applications → Business Capabilities

    Requires env vars: LEANIX_API_TOKEN, LEANIX_WORKSPACE_ID, LEANIX_BASE_URL
    """
    import requests  # local import — only needed when LeanIX push is enabled

    base_url  = os.environ["LEANIX_BASE_URL"].rstrip("/")
    token     = os.environ["LEANIX_API_TOKEN"]
    workspace = os.environ["LEANIX_WORKSPACE_ID"]

    # Obtain OAuth bearer token
    auth_resp = requests.post(
        f"{base_url}/services/mtm/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=("apitoken", token),
        timeout=30,
    )
    auth_resp.raise_for_status()
    bearer = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}

    graphql_url = f"{base_url}/services/pathfinder/v1/graphql"

    def _graphql(query: str, variables: dict) -> dict:
        resp = requests.post(
            graphql_url,
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # Cache: full_bc_path → LeanIX fact sheet ID
    bc_id_cache: dict[str, str] = {}

    def _upsert_bc(full_path: str) -> str:
        if full_path in bc_id_cache:
            return bc_id_cache[full_path]

        domain, _, bc_name = full_path.partition(" / ")
        display_name = bc_name or full_path

        result = _graphql(
            """
            mutation CreateBC($name: String!) {
              createFactSheet(input: {name: $name, type: BusinessCapability}) {
                factSheet { id }
              }
            }
            """,
            {"name": display_name},
        )
        fs_id = result["data"]["createFactSheet"]["factSheet"]["id"]
        bc_id_cache[full_path] = fs_id
        logger.debug("LeanIX BC created: %s → %s", display_name, fs_id)
        return fs_id

    def _upsert_application(req: dict) -> str:
        result = _graphql(
            """
            mutation CreateApp($name: String!, $desc: String!) {
              createFactSheet(input: {name: $name, type: Application, description: $desc}) {
                factSheet { id }
              }
            }
            """,
            {"name": req["id"], "desc": req.get("comment", "")[:2000]},
        )
        return result["data"]["createFactSheet"]["factSheet"]["id"]

    def _link_app_to_bc(app_id: str, bc_id: str) -> None:
        _graphql(
            """
            mutation LinkAppBC($appId: ID!, $bcId: ID!) {
              createRelation(
                factSheetId: $appId,
                relationType: relApplicationToBusinessCapability,
                targetFactSheetId: $bcId
              ) { id }
            }
            """,
            {"appId": app_id, "bcId": bc_id},
        )

    for req in enriched:
        if req.get("_error"):
            logger.warning("Skipping %s — enrichment error", req["id"])
            continue
        try:
            app_id = _upsert_application(req)
            for bc_short in req.get("bcs", []):
                full_path = bcs_index.get(bc_short, bc_short)
                bc_id = _upsert_bc(full_path)
                _link_app_to_bc(app_id, bc_id)
            logger.info("LeanIX: pushed %s", req["id"])
        except Exception as e:
            logger.error("LeanIX push failed for %s: %s", req["id"], e)


# ── Main ──────────────────────────────────────────────────────────────────────

def write(
    enriched_path: str | Path,
    template_path: str | Path,
    output_dir: str | Path = "output",
    push_leanix: bool = False,
) -> Path:
    enriched_path = Path(enriched_path)
    template_path = Path(template_path)
    output_dir    = Path(output_dir)

    enriched  = json.loads(enriched_path.read_text())
    bcs_index = _load_bcs_index()

    # Excel
    out_excel = output_dir / f"{template_path.stem}_enriched.xlsx"
    write_excel(enriched, template_path, out_excel, bcs_index)

    # LeanIX (optional)
    if push_leanix or os.getenv("LEANIX_PUSH", "").lower() == "true":
        logger.info("Pushing to LeanIX …")
        write_leanix(enriched, bcs_index)

    return out_excel


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) < 3:
        print("Usage: python 04_write.py <reqs_enriched.json> <template.xlsx> [output_dir]")
        sys.exit(1)
    out = write(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "output")
    print(f"Written → {out}")
