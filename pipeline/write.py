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


# ── LeanIX writer ─────────────────────────────────────────────────────────────

# coverage value → LeanIX Initiative lifecycle phase
_LIFECYCLE_MAP = {
    "Total":       "active",
    "Parcial":     "phaseIn",
    "No cubierto": "plan",
}

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
    enriched: list[dict[str, Any]],
    bcs_index: dict[str, str],
    client_name: str,
) -> None:
    import requests  # local import — only needed when LeanIX push is enabled

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

    # ── Tag resolution ────────────────────────────────────────────────────────
    # Resolve (or create) the workspace tag  client=<name>
    def _get_or_create_tag_id(tag_name: str) -> str:
        """Return the LeanIX tag ID for `tag_name`, creating the tag if needed."""
        tags_resp = requests.get(
            f"{base_url}/services/pathfinder/v1/tags",
            headers=headers,
            timeout=30,
        )
        tags_resp.raise_for_status()
        for tag in tags_resp.json().get("data", []):
            if tag.get("name") == tag_name:
                return tag["id"]
        # Create tag in the default tag group
        groups_resp = requests.get(
            f"{base_url}/services/pathfinder/v1/tagGroups",
            headers=headers,
            timeout=30,
        )
        groups_resp.raise_for_status()
        groups = groups_resp.json().get("data", [])
        group_id = groups[0]["id"] if groups else None
        create_resp = requests.post(
            f"{base_url}/services/pathfinder/v1/tags",
            json={"name": tag_name, "tagGroupId": group_id},
            headers=headers,
            timeout=30,
        )
        create_resp.raise_for_status()
        return create_resp.json()["data"]["id"]

    def _tag_fact_sheet(fs_id: str, tag_id: str) -> None:
        _gql(
            _MUTATION_ADD_TAG,
            {
                "id": fs_id,
                "patches": [{"op": "add", "path": "/tags", "value": json.dumps([{"tagId": tag_id}])}],
            },
        )

    # ── Fact sheet upsert helpers ─────────────────────────────────────────────
    def _find_by_name(fs_type: str, name: str) -> str | None:
        """Return the id of the first FS of `fs_type` whose displayName exactly matches `name`."""
        result = _gql(_QUERY_FS_BY_NAME, {"type": fs_type, "name": name})
        for edge in result["data"]["allFactSheets"]["edges"]:
            if edge["node"]["displayName"] == name:
                return edge["node"]["id"]
        return None

    def _create_fs(fs_type: str, name: str, desc: str = "") -> str:
        result = _gql(_MUTATION_CREATE_FS, {"type": fs_type, "name": name, "desc": desc[:2000]})
        return result["data"]["createFactSheet"]["factSheet"]["id"]

    def _upsert(fs_type: str, name: str, desc: str = "") -> tuple[str, bool]:
        """Return (id, created). created=True if a new FS was made."""
        existing = _find_by_name(fs_type, name)
        if existing:
            return existing, False
        return _create_fs(fs_type, name, desc), True

    def _set_lifecycle(fs_id: str, phase: str) -> None:
        """Set the Initiative lifecycle to `phase` (active | phaseIn | plan)."""
        lifecycle_value = json.dumps({"asIs": {"phase": phase}})
        _gql(
            _MUTATION_SET_LIFECYCLE,
            {
                "id": fs_id,
                "patches": [{"op": "add", "path": "/lifecycle", "value": lifecycle_value}],
            },
        )

    def _create_relation(from_id: str, to_id: str, rel_type: str) -> None:
        _gql(
            _MUTATION_CREATE_RELATION,
            {"from": from_id, "to": to_id, "relType": rel_type},
        )

    # ── Main push loop ────────────────────────────────────────────────────────
    client_tag = f"client={client_name}"
    tag_id     = _get_or_create_tag_id(client_tag)
    logger.info("LeanIX: using tag '%s' (id=%s)", client_tag, tag_id)

    # Caches to avoid redundant lookups within this run
    bc_id_cache:  dict[str, str] = {}   # leaf_bc_name  → FS id
    app_id_cache: dict[str, str] = {}   # rsa_name      → FS id

    pushed = skipped = failed = 0

    for req in enriched:
        req_id = req.get("id", "UNKNOWN")

        if req.get("_error"):
            logger.warning("LeanIX: skipping %s — enrichment error", req_id)
            skipped += 1
            continue

        try:
            # 1. Upsert BusinessCapability fact sheets
            bc_ids: list[str] = []
            for bc_short in req.get("bcs", []):
                full_path  = bcs_index.get(bc_short, bc_short)
                _, _, leaf = full_path.partition(" / ")
                bc_name    = leaf or full_path

                if bc_name not in bc_id_cache:
                    bc_id, created = _upsert("BusinessCapability", bc_name)
                    bc_id_cache[bc_name] = bc_id
                    if created:
                        _tag_fact_sheet(bc_id, tag_id)
                        logger.debug("LeanIX: created BC '%s'", bc_name)
                    else:
                        logger.debug("LeanIX: found existing BC '%s'", bc_name)

                bc_ids.append(bc_id_cache[bc_name])

            # 2. Upsert Application fact sheet (one per RSA)
            rsa_name = req.get("rsa", "SAP S/4HANA")
            if rsa_name not in app_id_cache:
                app_id, created = _upsert("Application", rsa_name)
                app_id_cache[rsa_name] = app_id
                if created:
                    _tag_fact_sheet(app_id, tag_id)
                    logger.debug("LeanIX: created Application '%s'", rsa_name)
                else:
                    logger.debug("LeanIX: found existing Application '%s'", rsa_name)

            # 3. Create Initiative for this requirement
            initiative_id = _create_fs(
                "Initiative",
                req_id,
                desc=req.get("comment", ""),
            )
            _tag_fact_sheet(initiative_id, tag_id)

            # 4. Set lifecycle from coverage
            phase = _LIFECYCLE_MAP.get(req.get("coverage", ""), "plan")
            _set_lifecycle(initiative_id, phase)

            # 5. Link Initiative → BusinessCapabilities
            for bc_id in bc_ids:
                _create_relation(initiative_id, bc_id, "relInitiativeToBusinessCapability")

            # 6. Link Initiative → Application
            _create_relation(initiative_id, app_id_cache[rsa_name], "relInitiativeToApplication")

            logger.info("LeanIX: pushed %s (lifecycle=%s, bcs=%d)", req_id, phase, len(bc_ids))
            pushed += 1

        except Exception as exc:
            logger.error("LeanIX: failed to push %s — %s", req_id, exc)
            failed += 1

    logger.info(
        "LeanIX push complete: %d pushed, %d skipped, %d failed",
        pushed, skipped, failed,
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def write(
    enriched_path: str | Path,
    template_path: str | Path,
    output_dir: str | Path = "output",
    push_leanix: bool = False,
    client_name: str = "unknown",
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
        logger.info("Pushing to LeanIX (client='%s') …", client_name)
        write_leanix(enriched, bcs_index, client_name=client_name)

    return out_excel


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) < 3:
        print("Usage: python write.py <reqs_enriched.json> <template.xlsx> [output_dir] [client_name]")
        sys.exit(1)
    out = write(
        sys.argv[1],
        sys.argv[2],
        sys.argv[3] if len(sys.argv) > 3 else "output",
        client_name=sys.argv[4] if len(sys.argv) > 4 else "unknown",
    )
    print(f"Written → {out}")
