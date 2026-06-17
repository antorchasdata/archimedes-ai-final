# LPR Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `knowledge/sap_lpr_catalog.json` from MXP Core Model and integrate it as an offline fallback in `lift_shift.py` and as enrichment in `write.py`.

**Architecture:** A standalone build script queries MXP Core Model for `logical_product` + `license_material` entries, applies a static RSA-name alias table, and writes a JSON lookup. `lift_shift.py` loads this JSON as a fallback when OData RISE session is unavailable. `write.py` reads it at Step 4 to set `externalId` and `lprId` on Application fact sheets.

**Tech Stack:** Python 3.9+, `requests`, `python-dotenv`, `pytest`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `pipeline/build_lpr_catalog.py` | Create | Query MXP, build and write `sap_lpr_catalog.json` |
| `knowledge/sap_lpr_catalog.json` | Generated | Lookup table: RSA name → LPR → Material IDs |
| `pipeline/lift_shift.py` | Modify | Add `resolve_app_to_skus_offline()` + fallback in `resolve_app_to_skus()` |
| `pipeline/write.py` | Modify | Add `_load_lpr_catalog()`, `_enrich_with_lpr()`, call in Application sheet loop |
| `tests/test_lpr_catalog.py` | Create | Unit tests for offline lookup and write enrichment |
| `.claude/commands/update-lpr-catalog.md` | Create | `/update-lpr-catalog` slash command |

---

## Task 1: Build script `pipeline/build_lpr_catalog.py`

**Files:**
- Create: `pipeline/build_lpr_catalog.py`

- [ ] **Step 1: Create the file with imports, constants, and alias table**

```python
"""
pipeline/build_lpr_catalog.py — Builds knowledge/sap_lpr_catalog.json
from MXP Core Model (worksphere 6e3c9171).

Usage:
    python3 pipeline/build_lpr_catalog.py
    python3 pipeline/build_lpr_catalog.py --dry-run

Requires:
    MXP_TOKEN in .env  (Bearer token)
    or MXP_BASE_URL if a proxy with auth is already in place
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

MXP_BASE_URL  = os.getenv("MXP_BASE_URL", "https://mxpresso.cfapps.eu10-004.hana.ondemand.com")
MXP_TOKEN     = os.getenv("MXP_TOKEN", "")

WORKSPHERE_ID      = "6e3c9171-5cd4-4a71-b77e-4a43ffb0cdc1"   # MXP Core Model
ENTITY_LPR         = "172e4357-6cda-4417-9444-15617c29c3ca"   # logical_product
ENTITY_LIC_MAT     = "67dc1ef6-5f3d-43e6-9442-45c838d05d46"   # license_material

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"
LPR_PATH      = KNOWLEDGE_DIR / "sap_lpr_catalog.json"

PAGE_SIZE = 100

# RSA canonical name (from sap_rsa_catalog.json) → Logical Product ID
_RSA_TO_LPR: dict[str, str] = {
    "SAP S/4HANA Cloud":                                                     "LPR243",
    "SAP S/4HANA Cloud Private Edition":                                     "LPR943",
    "SAP S/4HANA":                                                           "LPR244",
    "SAP S/4HANA Cloud Private Edition, enterprise management":              "LPR245",
    "SAP S/4HANA Finance for group reporting":                               "LPR852",
    "SAP S/4HANA Finance for receivables management":                        "LPR349",
    "SAP S/4HANA Finance for advanced payment management":                   "LPR802",
    "SAP S/4HANA for central finance":                                       "LPR350",
    "SAP S/4HANA for central procurement":                                   "LPR903",
    "SAP S/4HANA for enterprise contract management":                        "LPR863",
    "SAP S/4HANA for advanced ATP":                                          "LPR925",
    "SAP S/4HANA Supply Chain for transportation management":                "LPR333",
    "SAP S/4HANA Supply Chain for extended service parts planning":          "LPR938",
    "SAP S/4HANA Manufacturing for production engineering and operations":   "LPR284",
    "SAP S/4HANA Cloud Private Edition, product lifecycle management":       "LPR295",
    "SAP S/4HANA Cloud Private Edition, extended warehouse management":      "LPR330",
    "SAP S/4HANA Cloud Public Edition, group reporting":                     "LPR644",
    "SAP S/4HANA Cloud Public Edition, receivables management":              "LPR1081",
    "SAP S/4HANA Cloud Public Edition, advanced variant configuration":      "LPR711",
    "SAP SuccessFactors Employee Central":                                   "LPR390",
    "SAP Ariba Sourcing":                                                    "LPR486",
    "SAP Analytics Cloud":                                                   "LPR201",
    "SAP Integrated Business Planning":                                      "LPR307",
    "SAP Transportation Management":                                         "LPR333",
    "SAP Portfolio and Project Management":                                  "LPR307",
    "SAP Master Data Governance":                                            "LPR266",
    "SAP Business Technology Platform":                                      "LPR879",
    "SAP Concur":                                                            "LPR390",
    "SAP Fieldglass":                                                        "LPR390",
}
```

- [ ] **Step 2: Add HTTP helper and query function**

```python
def _headers() -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if MXP_TOKEN:
        h["Authorization"] = f"Bearer {MXP_TOKEN}"
    return h


def _query_all(entity_id: str, selected_fields: list[str],
               search_criteria: dict | None = None,
               status: str = "published") -> list[dict]:
    """Download all entries from an entity with top/skip pagination."""
    url = (f"{MXP_BASE_URL}/api/mxp/workspheres/{WORKSPHERE_ID}"
           f"/entities/{entity_id}/entries")
    results: list[dict] = []
    skip = 0
    while True:
        params: dict = {
            "top": PAGE_SIZE,
            "skip": skip,
            "status": status,
            "selectedFields": ",".join(selected_fields),
        }
        if search_criteria:
            params["searchCriteria"] = json.dumps(search_criteria)
        resp = requests.get(url, headers=_headers(), params=params, timeout=30)
        if resp.status_code == 401:
            print("ERROR 401 — Token MXP inválido. Configura MXP_TOKEN en .env")
            sys.exit(1)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        results.extend(batch)
        print(f"  [{entity_id[:8]}] {len(results)} descargados...", end="\r")
        if len(batch) < PAGE_SIZE:
            break
        skip += PAGE_SIZE
    print()
    return results
```

- [ ] **Step 3: Add build function**

```python
def build_lpr_catalog(lpr_entries: list[dict], lic_entries: list[dict]) -> dict:
    """
    Build lpr_index and rsa_name_index from raw MXP entries.

    lpr_entries: logical_product rows (already filtered to SAPPR, non-archived)
    lic_entries: all license_material rows with logical_product relation
    """
    # Build map: lpr_id → list of Material_IDs
    lpr_to_materials: dict[str, list[str]] = defaultdict(list)
    for lic in lic_entries:
        mat_id = lic.get("Material_ID", "").strip()
        lp = lic.get("logical_product") or {}
        lpr_id = lp.get("Logical_Product_ID") or lp.get("id", "")
        if mat_id and lpr_id:
            lpr_to_materials[lpr_id].append(mat_id)

    lpr_index: dict[str, dict] = {}
    for lpr in lpr_entries:
        lpr_id = lpr.get("Logical_Product_ID") or lpr.get("id", "")
        if not lpr_id:
            continue
        successor_obj = lpr.get("successor") or {}
        successor_id = successor_obj.get("Logical_Product_ID") or successor_obj.get("id") or None

        lpr_index[lpr_id] = {
            "lpr_id":           lpr_id,
            "lpr_name":         lpr.get("lpr_name_merged") or lpr.get("name", ""),
            "deployment_mode":  lpr.get("deployment_mode", ""),
            "price_list_status": lpr.get("price_list_status", ""),
            "eppm_status":      lpr.get("eppm_status", ""),
            "is_industry_cloud": lpr.get("is_industry_cloud", False),
            "successor":        successor_id,
            "material_ids":     sorted(set(lpr_to_materials.get(lpr_id, []))),
        }

    # Build RSA name index using alias table
    rsa_name_index: dict[str, str] = {}
    for rsa_name, lpr_id in _RSA_TO_LPR.items():
        if lpr_id in lpr_index:
            rsa_name_index[rsa_name] = lpr_id

    today = datetime.now().strftime("%Y-%m")
    return {
        "version": today,
        "source":  (f"MXP Core Model (6e3c9171) — auto-generated "
                    f"{datetime.now().strftime('%Y-%m-%d')}"),
        "stats": {
            "total_lpr":  len(lpr_index),
            "mapped_rsa": len(rsa_name_index),
        },
        "lpr_index":      lpr_index,
        "rsa_name_index": rsa_name_index,
    }
```

- [ ] **Step 4: Add main function**

```python
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Builds sap_lpr_catalog.json from MXP Core Model")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show stats only, do not write file")
    args = parser.parse_args()

    print("=" * 60)
    print("Archimedes — Build LPR Catalog from MXP Core Model")
    print("=" * 60)

    if not MXP_TOKEN:
        print("\nAVISO: MXP_TOKEN no configurado en .env\n")

    print("\n[1/3] Descargando Logical Products (SAPPR)...")
    lpr_entries = _query_all(
        ENTITY_LPR,
        selected_fields=[
            "Logical_Product_ID", "name", "lpr_name_merged",
            "deployment_mode", "price_list_status", "eppm_status",
            "is_industry_cloud", "successor",
        ],
    )
    # Filter: only SAP Products, exclude To be Archived
    lpr_entries = [
        e for e in lpr_entries
        if e.get("eppm_status") != "To be Archived"
    ]
    print(f"      → {len(lpr_entries)} Logical Products")

    print("\n[2/3] Descargando License Materials...")
    lic_entries = _query_all(
        ENTITY_LIC_MAT,
        selected_fields=["Material_ID", "name", "material_status",
                         "price_list_status", "logical_product"],
    )
    print(f"      → {len(lic_entries)} License Materials")

    print("\n[3/3] Construyendo catálogo...")
    catalog = build_lpr_catalog(lpr_entries, lic_entries)
    print(f"      LPR index:     {catalog['stats']['total_lpr']} productos")
    print(f"      RSA mappings:  {catalog['stats']['mapped_rsa']} nombres mapeados")

    if args.dry_run:
        print("\n[DRY RUN] No se escribe fichero.")
        print("\nSample lpr_index:")
        for k, v in list(catalog["lpr_index"].items())[:3]:
            print(f"  {k}: {v['lpr_name']} — {len(v['material_ids'])} materials")
        print("\nSample rsa_name_index:")
        for k, v in list(catalog["rsa_name_index"].items())[:5]:
            print(f"  '{k}' → {v}")
        return

    LPR_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2))
    print(f"\n✅ Escrito: {LPR_PATH}")
    print(f"   {catalog['stats']['total_lpr']} LPRs | "
          f"{catalog['stats']['mapped_rsa']} RSA mappings ({catalog['version']})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Commit**

```bash
git add pipeline/build_lpr_catalog.py
git commit -m "feat(lpr): add build_lpr_catalog.py — MXP Core Model → sap_lpr_catalog.json"
```

---

## Task 2: Unit tests for `build_lpr_catalog`

**Files:**
- Create: `tests/test_lpr_catalog.py`

- [ ] **Step 1: Write failing tests for `build_lpr_catalog()`**

```python
"""tests/test_lpr_catalog.py — Tests for LPR catalog build and lookup."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.build_lpr_catalog import build_lpr_catalog, _RSA_TO_LPR

# ── Fixtures ──────────────────────────────────────────────────────────────────

_LPR_ENTRIES = [
    {
        "Logical_Product_ID": "LPR243",
        "name": "SAP S/4HANA Cloud Public Edition",
        "lpr_name_merged": "SAP S/4HANA Cloud Public Edition",
        "deployment_mode": "Public",
        "price_list_status": "On Price List",
        "eppm_status": "Active",
        "is_industry_cloud": False,
        "successor": None,
    },
    {
        "Logical_Product_ID": "LPR943",
        "name": "SAP S/4HANA Cloud Private Edition",
        "lpr_name_merged": "SAP S/4HANA Cloud Private Edition",
        "deployment_mode": "Private",
        "price_list_status": "On Price List",
        "eppm_status": "Active",
        "is_industry_cloud": False,
        "successor": None,
    },
    {
        "Logical_Product_ID": "LPR999",
        "name": "Archived Product",
        "lpr_name_merged": "Archived Product",
        "deployment_mode": "Private",
        "price_list_status": "Stopped",
        "eppm_status": "To be Archived",
        "is_industry_cloud": False,
        "successor": None,
    },
]

_LIC_ENTRIES = [
    {
        "Material_ID": "50130591",
        "name": "Implementation for S/4HANA Cloud, Public",
        "material_status": "A0",
        "price_list_status": "On Price List",
        "logical_product": {"Logical_Product_ID": "LPR243", "id": "LPR243"},
    },
    {
        "Material_ID": "50130953",
        "name": "RDS Data Migr S/4HANA Cloud",
        "material_status": "A0",
        "price_list_status": "On Price List",
        "logical_product": {"Logical_Product_ID": "LPR243", "id": "LPR243"},
    },
    {
        "Material_ID": "50157055",
        "name": "SAP S/4HANA accelerated implement for NA",
        "material_status": "A0",
        "price_list_status": "On Price List",
        "logical_product": {"Logical_Product_ID": "LPR943", "id": "LPR943"},
    },
]


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_lpr_index_built():
    catalog = build_lpr_catalog(_LPR_ENTRIES, _LIC_ENTRIES)
    assert "LPR243" in catalog["lpr_index"]
    assert "LPR943" in catalog["lpr_index"]


def test_lpr_fields_complete():
    catalog = build_lpr_catalog(_LPR_ENTRIES, _LIC_ENTRIES)
    entry = catalog["lpr_index"]["LPR243"]
    assert entry["lpr_id"] == "LPR243"
    assert entry["lpr_name"] == "SAP S/4HANA Cloud Public Edition"
    assert entry["deployment_mode"] == "Public"
    assert entry["price_list_status"] == "On Price List"
    assert entry["eppm_status"] == "Active"
    assert entry["is_industry_cloud"] is False
    assert entry["successor"] is None


def test_material_ids_collected():
    catalog = build_lpr_catalog(_LPR_ENTRIES, _LIC_ENTRIES)
    mat_ids = catalog["lpr_index"]["LPR243"]["material_ids"]
    assert "50130591" in mat_ids
    assert "50130953" in mat_ids
    assert len(mat_ids) == 2


def test_material_ids_deduplicated():
    # Duplicate material entry for same LPR
    lic_with_dup = _LIC_ENTRIES + [_LIC_ENTRIES[0]]
    catalog = build_lpr_catalog(_LPR_ENTRIES, _LIC_ENTRIES + [_LIC_ENTRIES[0]])
    assert catalog["lpr_index"]["LPR243"]["material_ids"].count("50130591") == 1


def test_rsa_name_index_maps_known_names():
    catalog = build_lpr_catalog(_LPR_ENTRIES, _LIC_ENTRIES)
    # "SAP S/4HANA Cloud" → LPR243 (from _RSA_TO_LPR)
    assert catalog["rsa_name_index"]["SAP S/4HANA Cloud"] == "LPR243"
    assert catalog["rsa_name_index"]["SAP S/4HANA Cloud Private Edition"] == "LPR943"


def test_rsa_name_index_skips_unknown_lpr():
    # LPR999 not in _RSA_TO_LPR — should not appear in rsa_name_index
    catalog = build_lpr_catalog(_LPR_ENTRIES, _LIC_ENTRIES)
    assert "Archived Product" not in catalog["rsa_name_index"].values()


def test_stats_correct():
    catalog = build_lpr_catalog(_LPR_ENTRIES, _LIC_ENTRIES)
    # LPR999 is included in lpr_index (filtering happens in main(), not build)
    assert catalog["stats"]["total_lpr"] == 3
    assert catalog["stats"]["mapped_rsa"] == 2


def test_lpr_without_materials_has_empty_list():
    catalog = build_lpr_catalog(_LPR_ENTRIES, [])
    assert catalog["lpr_index"]["LPR243"]["material_ids"] == []


def test_alias_table_has_no_placeholder_values():
    for name, lpr_id in _RSA_TO_LPR.items():
        assert lpr_id.startswith("LPR"), f"Bad alias: {name!r} → {lpr_id!r}"
        assert "..." not in lpr_id, f"Placeholder in alias: {name!r} → {lpr_id!r}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/I519409/dev/archimedes-ai
python3 -m pytest tests/test_lpr_catalog.py -v 2>&1 | head -30
```

Expected: `ImportError` or `ModuleNotFoundError` on `build_lpr_catalog`.

- [ ] **Step 3: Run tests after Task 1 is complete to verify they pass**

```bash
python3 -m pytest tests/test_lpr_catalog.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_lpr_catalog.py
git commit -m "test(lpr): unit tests for build_lpr_catalog"
```

---

## Task 3: Offline fallback in `lift_shift.py`

**Files:**
- Modify: `pipeline/lift_shift.py`

- [ ] **Step 1: Add `_load_lpr_catalog()` helper near top of file (after logger line)**

Add after `logger = logging.getLogger(__name__)`:

```python
_LPR_CATALOG_PATH = Path(__file__).parent.parent / "knowledge" / "sap_lpr_catalog.json"
_lpr_catalog_cache: dict | None = None


def _load_lpr_catalog() -> dict:
    """Load sap_lpr_catalog.json once and cache in module variable."""
    global _lpr_catalog_cache
    if _lpr_catalog_cache is None:
        if not _LPR_CATALOG_PATH.exists():
            logger.warning("sap_lpr_catalog.json not found at %s", _LPR_CATALOG_PATH)
            _lpr_catalog_cache = {"lpr_index": {}, "rsa_name_index": {}}
        else:
            _lpr_catalog_cache = json.loads(_LPR_CATALOG_PATH.read_text())
    return _lpr_catalog_cache
```

- [ ] **Step 2: Add `resolve_app_to_skus_offline()` after `resolve_app_to_skus()`**

Add after the closing of `resolve_app_to_skus()` (after line 171):

```python
def resolve_app_to_skus_offline(app_names: list[str]) -> list[dict]:
    """
    Resolve app names to Material Numbers using local sap_lpr_catalog.json.
    Fallback when OData RISE session is unavailable.

    Returns same structure as resolve_app_to_skus() with resolved_by="lpr_catalog".
    """
    catalog = _load_lpr_catalog()
    rsa_index: dict[str, str] = catalog.get("rsa_name_index", {})      # RSA name → LPR ID
    lpr_index: dict[str, dict] = catalog.get("lpr_index", {})           # LPR ID → entry

    # Build case-insensitive lookup
    rsa_lower: dict[str, str] = {k.lower(): v for k, v in rsa_index.items()}

    results = []
    for app_name in app_names:
        clean = _strip_sid(app_name)

        # Exact match first, then case-insensitive
        lpr_id = rsa_index.get(clean) or rsa_lower.get(clean.lower())

        if not lpr_id:
            results.append({
                "app_name":        app_name,
                "clean_name":      clean,
                "candidates":      [],
                "selected":        "",
                "selected_maktx":  "",
                "resolved_by":     "not_found",
            })
            logger.debug("LPR catalog: no match for '%s'", clean)
            continue

        lpr_entry = lpr_index.get(lpr_id, {})
        material_ids = lpr_entry.get("material_ids", [])
        selected = material_ids[0] if material_ids else ""
        lpr_name = lpr_entry.get("lpr_name", clean)

        results.append({
            "app_name":        app_name,
            "clean_name":      clean,
            "candidates":      [{"matnr": m, "maktx": lpr_name} for m in material_ids],
            "selected":        selected,
            "selected_maktx":  lpr_name,
            "resolved_by":     "lpr_catalog",
        })

    return results
```

- [ ] **Step 3: Modify `resolve_app_to_skus()` to use offline fallback**

In `resolve_app_to_skus()`, change the function signature and add the session check at the top. The current signature is:

```python
def resolve_app_to_skus(app_names: list[str], session: requests.Session) -> list[dict]:
```

Replace the entire function body opening (before the `results = []` line) with:

```python
def resolve_app_to_skus(app_names: list[str], session: requests.Session | None = None) -> list[dict]:
    """
    Resolve a list of application names to Material Numbers.

    If session is None or check_session() fails, falls back to resolve_app_to_skus_offline().

    Returns list of:
      {
        "app_name":    str,   # original name from baseline
        "clean_name":  str,   # after SID strip
        "candidates":  [{matnr, maktx}, ...],
        "selected":    str,   # best candidate chosen by Claude (or first if only one)
        "selected_maktx": str,
        "resolved_by": "exact" | "claude" | "manual" | "lpr_catalog" | "not_found"
      }
    """
    if session is None or not check_session(session):
        logger.info("OData session unavailable — using LPR catalog offline fallback")
        return resolve_app_to_skus_offline(app_names)
```

(The rest of the function body — `results = []`, the for loop — stays unchanged.)

- [ ] **Step 4: Add tests for offline lookup to `tests/test_lpr_catalog.py`**

Append to the test file:

```python
# ── Offline lookup tests ──────────────────────────────────────────────────────

def test_resolve_offline_exact_match(tmp_path, monkeypatch):
    """resolve_app_to_skus_offline returns material_ids[0] on exact RSA match."""
    import pipeline.lift_shift as ls

    catalog = {
        "rsa_name_index": {"SAP S/4HANA Cloud": "LPR243"},
        "lpr_index": {
            "LPR243": {
                "lpr_id": "LPR243",
                "lpr_name": "SAP S/4HANA Cloud Public Edition",
                "material_ids": ["50130591", "50130953"],
            }
        },
    }
    # Patch the cache
    monkeypatch.setattr(ls, "_lpr_catalog_cache", catalog)

    results = ls.resolve_app_to_skus_offline(["SAP S/4HANA Cloud"])
    assert len(results) == 1
    r = results[0]
    assert r["selected"] == "50130591"
    assert r["resolved_by"] == "lpr_catalog"
    assert r["clean_name"] == "SAP S/4HANA Cloud"


def test_resolve_offline_case_insensitive(monkeypatch):
    import pipeline.lift_shift as ls

    catalog = {
        "rsa_name_index": {"SAP S/4HANA Cloud": "LPR243"},
        "lpr_index": {
            "LPR243": {
                "lpr_id": "LPR243",
                "lpr_name": "SAP S/4HANA Cloud Public Edition",
                "material_ids": ["50130591"],
            }
        },
    }
    monkeypatch.setattr(ls, "_lpr_catalog_cache", catalog)

    results = ls.resolve_app_to_skus_offline(["sap s/4hana cloud"])
    assert results[0]["resolved_by"] == "lpr_catalog"


def test_resolve_offline_strips_sid(monkeypatch):
    import pipeline.lift_shift as ls

    catalog = {
        "rsa_name_index": {"SAP S/4HANA Cloud": "LPR243"},
        "lpr_index": {
            "LPR243": {"lpr_id": "LPR243", "lpr_name": "X", "material_ids": ["50130591"]},
        },
    }
    monkeypatch.setattr(ls, "_lpr_catalog_cache", catalog)

    results = ls.resolve_app_to_skus_offline(["SAP S/4HANA Cloud (ECP)"])
    assert results[0]["resolved_by"] == "lpr_catalog"
    assert results[0]["clean_name"] == "SAP S/4HANA Cloud"


def test_resolve_offline_not_found(monkeypatch):
    import pipeline.lift_shift as ls

    monkeypatch.setattr(ls, "_lpr_catalog_cache",
                        {"rsa_name_index": {}, "lpr_index": {}})

    results = ls.resolve_app_to_skus_offline(["Unknown App"])
    assert results[0]["resolved_by"] == "not_found"
    assert results[0]["selected"] == ""


def test_resolve_offline_empty_material_ids(monkeypatch):
    import pipeline.lift_shift as ls

    catalog = {
        "rsa_name_index": {"SAP S/4HANA Cloud": "LPR243"},
        "lpr_index": {
            "LPR243": {"lpr_id": "LPR243", "lpr_name": "X", "material_ids": []},
        },
    }
    monkeypatch.setattr(ls, "_lpr_catalog_cache", catalog)

    results = ls.resolve_app_to_skus_offline(["SAP S/4HANA Cloud"])
    assert results[0]["selected"] == ""
    assert results[0]["resolved_by"] == "lpr_catalog"
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_lpr_catalog.py -v
```

Expected: all 14 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/lift_shift.py tests/test_lpr_catalog.py
git commit -m "feat(lpr): add offline fallback resolve_app_to_skus_offline in lift_shift"
```

---

## Task 4: Write enrichment in `write.py`

**Files:**
- Modify: `pipeline/write.py`

- [ ] **Step 1: Add `_load_lpr_catalog()` and `_enrich_with_lpr()` to `write.py`**

Add after the `KNOWLEDGE_DIR` line (line 42), before `COL_H`:

```python
LPR_CATALOG_PATH = KNOWLEDGE_DIR / "sap_lpr_catalog.json"


def _load_lpr_catalog() -> dict:
    """Load sap_lpr_catalog.json. Returns empty structure if not found."""
    if not LPR_CATALOG_PATH.exists():
        logger.debug("sap_lpr_catalog.json not found — LPR enrichment disabled")
        return {"lpr_index": {}, "rsa_name_index": {}}
    return json.loads(LPR_CATALOG_PATH.read_text())


def _enrich_with_lpr(row: dict, lpr_catalog: dict) -> None:
    """
    In-place: set externalId and lprId on an Application fact sheet row
    if the displayName matches an RSA name in rsa_name_index.

    row: dict representing one Application row (has key "name" for display name)
    lpr_catalog: loaded sap_lpr_catalog.json dict
    """
    rsa_index: dict[str, str] = lpr_catalog.get("rsa_name_index", {})
    lpr_index: dict[str, dict] = lpr_catalog.get("lpr_index", {})

    name = row.get("name", "")
    lpr_id = rsa_index.get(name)
    if not lpr_id:
        return

    entry = lpr_index.get(lpr_id, {})
    material_ids = entry.get("material_ids", [])

    if material_ids:
        row["externalId"] = material_ids[0]
    row["lprId"] = lpr_id
    logger.debug("LPR enriched '%s' → %s (externalId=%s)",
                 name, lpr_id, material_ids[0] if material_ids else "")
```

- [ ] **Step 2: Call `_enrich_with_lpr` in the Application sheet loop**

Find the Application sheet row builder (around line 547):

```python
            "alias": "", "externalId": "",
```

The full row dict is assigned to a variable before being appended. Find where the Application rows dict is built and add the enrichment call after the dict is constructed. The relevant block looks like:

```python
            row = {
                "id": "", "type": "Application", "name": app_name,
                ...
                "alias": "", "externalId": "",
                ...
            }
```

After that `row = { ... }` block, add:

```python
            _enrich_with_lpr(row, lpr_catalog)
```

Also load the catalog once before the loop. Find where the Application sheet loop starts (look for `seen_apps` or `ws_app`) and add before it:

```python
    lpr_catalog = _load_lpr_catalog()
```

- [ ] **Step 3: Add enrichment tests to `tests/test_lpr_catalog.py`**

Append to the test file:

```python
# ── Write enrichment tests ────────────────────────────────────────────────────

def test_enrich_with_lpr_sets_external_id():
    from pipeline.write import _enrich_with_lpr

    catalog = {
        "rsa_name_index": {"SAP S/4HANA Cloud": "LPR243"},
        "lpr_index": {
            "LPR243": {
                "lpr_id": "LPR243",
                "lpr_name": "SAP S/4HANA Cloud Public Edition",
                "material_ids": ["50130591", "50130953"],
            }
        },
    }
    row = {"name": "SAP S/4HANA Cloud", "externalId": ""}
    _enrich_with_lpr(row, catalog)
    assert row["externalId"] == "50130591"
    assert row["lprId"] == "LPR243"


def test_enrich_with_lpr_no_match_is_noop():
    from pipeline.write import _enrich_with_lpr

    catalog = {"rsa_name_index": {}, "lpr_index": {}}
    row = {"name": "Unknown App", "externalId": ""}
    _enrich_with_lpr(row, catalog)
    assert row["externalId"] == ""
    assert "lprId" not in row


def test_enrich_with_lpr_no_materials_skips_external_id():
    from pipeline.write import _enrich_with_lpr

    catalog = {
        "rsa_name_index": {"SAP S/4HANA Cloud": "LPR243"},
        "lpr_index": {
            "LPR243": {"lpr_id": "LPR243", "lpr_name": "X", "material_ids": []},
        },
    }
    row = {"name": "SAP S/4HANA Cloud", "externalId": ""}
    _enrich_with_lpr(row, catalog)
    assert row["externalId"] == ""   # no material_ids → no externalId
    assert row["lprId"] == "LPR243"  # lprId still set


def test_load_lpr_catalog_missing_returns_empty(tmp_path, monkeypatch):
    from pipeline import write
    monkeypatch.setattr(write, "LPR_CATALOG_PATH", tmp_path / "nonexistent.json")
    catalog = write._load_lpr_catalog()
    assert catalog == {"lpr_index": {}, "rsa_name_index": {}}
```

- [ ] **Step 4: Run all tests**

```bash
python3 -m pytest tests/test_lpr_catalog.py -v
```

Expected: all 18 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/write.py tests/test_lpr_catalog.py
git commit -m "feat(lpr): enrich Application fact sheets with externalId/lprId in write.py"
```

---

## Task 5: Slash command `/update-lpr-catalog`

**Files:**
- Create: `.claude/commands/update-lpr-catalog.md`

- [ ] **Step 1: Create the command file**

```markdown
# /update-lpr-catalog

Update the LPR catalog (`knowledge/sap_lpr_catalog.json`) from MXP Core Model
using the current MCP session.

## Steps

1. Query MXP Core Model (worksphere `6e3c9171`) for all Logical Products:
   - Entity: `logical_product` (`172e4357`)
   - Fields: `Logical_Product_ID`, `name`, `lpr_name_merged`, `deployment_mode`,
     `price_list_status`, `eppm_status`, `is_industry_cloud`, `successor`
   - Filter: exclude `eppm_status = "To be Archived"`

2. For each Logical Product, collect linked License Materials:
   - Entity: `license_material` (`67dc1ef6`)
   - Fields: `Material_ID`, `name`, `material_status`, `logical_product`

3. Build `lpr_index` and `rsa_name_index` using the alias table in
   `pipeline/build_lpr_catalog.py` (`_RSA_TO_LPR`)

4. Write `knowledge/sap_lpr_catalog.json`

5. Report: total LPRs, RSA mappings, sample entries

## Notes

- Requires active MXP MCP session (mxp-mcp server must be running)
- Token-based alternative: set `MXP_TOKEN` in `.env` and run
  `python3 pipeline/build_lpr_catalog.py`
- RSA name aliases are defined in `_RSA_TO_LPR` in `pipeline/build_lpr_catalog.py`
  — extend that dict for new products
```

- [ ] **Step 2: Commit**

```bash
git add .claude/commands/update-lpr-catalog.md
git commit -m "feat(lpr): add /update-lpr-catalog slash command"
```

---

## Task 6: Run full test suite and verify

- [ ] **Step 1: Run all tests**

```bash
cd /Users/I519409/dev/archimedes-ai
python3 -m pytest tests/ -v
```

Expected: all tests PASS, no regressions in `test_validate.py`.

- [ ] **Step 2: Smoke-test build script (dry run)**

```bash
python3 pipeline/build_lpr_catalog.py --dry-run
```

Expected output (approximate):
```
============================================================
Archimedes — Build LPR Catalog from MXP Core Model
============================================================

[1/3] Descargando Logical Products (SAPPR)...
      → N Logical Products
[2/3] Descargando License Materials...
      → M License Materials
[3/3] Construyendo catálogo...
      LPR index:     N productos
      RSA mappings:  K nombres mapeados

[DRY RUN] No se escribe fichero.

Sample lpr_index:
  LPR243: SAP S/4HANA Cloud Public Edition — 3 materials
  ...

Sample rsa_name_index:
  'SAP S/4HANA Cloud' → LPR243
  ...
```

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: final LPR catalog integration — tests passing"
```
