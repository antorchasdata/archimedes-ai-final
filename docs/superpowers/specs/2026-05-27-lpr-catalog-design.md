# Design: SAP LPR Catalog — RSA → Material ID lookup

**Date:** 2026-05-27
**Status:** Approved
**Scope:** New `sap_lpr_catalog.json` + build script + integration in `lift_shift.py` and `write.py`

---

## Problem

The RSA catalog (`sap_rsa_catalog.json`) contains canonical SAP product names (515 entries) but no Material IDs or Logical Product IDs (LPR). The `lift_shift.py` module resolves app names → Material Numbers via a live OData RISE API that requires browser cookies. When that session is unavailable, resolution fails entirely. Additionally, LeanIX fact sheets lack `externalId` / `lpr_id` enrichment that would tie them back to SAP's commercial catalog.

---

## Solution

Build a standalone lookup table `knowledge/sap_lpr_catalog.json` sourced from MXP Core Model (worksphere `6e3c9171`), mapping RSA product names → Logical Product ID (LPR) → Material IDs. Integrate it as:

1. **Offline fallback** in `lift_shift.py` when OData session is unavailable
2. **Enrichment** in `pipeline/write.py` (Step 4) to populate `externalId` and `lpr_id` on Application fact sheets

---

## Architecture

### New file: `pipeline/build_lpr_catalog.py`

Standalone script (same pattern as `catalog_mxp.py`). Requires MXP session (via MCP or token).

**Steps:**
1. Query MXP Core Model entity `logical_product` (`172e4357`) from worksphere `6e3c9171`
   - Filter: `eppm_product_category = "SAPPR"`, exclude `eppm_status = "To be Archived"`
   - Fields: `Logical_Product_ID`, `name`, `lpr_name_merged`, `deployment_mode`, `price_list_status`, `eppm_status`, `is_industry_cloud`, `successor`
2. For each logical_product, query `license_material` (`67dc1ef6`) filtered by `logical_product.id`
   - Fields: `Material_ID`, `name`, `material_status`, `price_list_status`
   - Collect all `Material_ID` values → `material_ids[]`
3. Apply `_RSA_TO_LPR` alias table (see below) to build `rsa_name_index`
4. Write `knowledge/sap_lpr_catalog.json`

**Alias table `_RSA_TO_LPR`** (RSA canonical name → LPR ID):
```python
_RSA_TO_LPR = {
    "SAP S/4HANA Cloud":                         "LPR243",
    "SAP S/4HANA Cloud Private Edition":         "LPR943",
    "SAP S/4HANA":                               "LPR244",  # Enterprise Management
    "SAP S/4HANA Cloud Private Edition, enterprise management": "LPR245",
    "SAP Ariba Sourcing":                        "LPR...",  # filled at build time
    "SAP SuccessFactors Employee Central":       "LPR390",
    # ... extended as catalog grows
}
```

Keys are exact RSA `name` values. Unknown mappings are left out of `rsa_name_index` (not an error).

### Output: `knowledge/sap_lpr_catalog.json`

```json
{
  "version": "2026-05",
  "source": "MXP Core Model (6e3c9171) — auto-generated YYYY-MM-DD",
  "stats": {
    "total_lpr": 45,
    "mapped_rsa": 38
  },
  "lpr_index": {
    "LPR243": {
      "lpr_id": "LPR243",
      "lpr_name": "SAP S/4HANA Cloud Public Edition",
      "deployment_mode": "Public",
      "price_list_status": "On Price List",
      "eppm_status": "Active",
      "is_industry_cloud": false,
      "successor": null,
      "material_ids": ["50130591", "50130953", "50141984"]
    }
  },
  "rsa_name_index": {
    "SAP S/4HANA Cloud": "LPR243",
    "SAP S/4HANA Cloud Private Edition": "LPR943"
  }
}
```

`material_ids` contains all `Material_ID` values from `license_material` linked to this LPR, regardless of status. First entry is used as `externalId`.

---

## Integration: `lift_shift.py`

Add `resolve_app_to_skus_offline(app_names: list[str]) -> list[dict]`:
- Loads `sap_lpr_catalog.json` (cached in module-level variable, loaded once)
- For each name: strip SID suffix (reuses `_strip_sid()`), then lookup in `rsa_name_index` (exact match, then case-insensitive)
- Returns same structure as `resolve_app_to_skus()` with `resolved_by = "lpr_catalog"` and `selected = material_ids[0]`

Modified `resolve_app_to_skus()` flow:
```
check_session() → True  → existing OData path (unchanged)
               → False → resolve_app_to_skus_offline()
```

No changes to `convert_to_rise()` or `get_deployment_modes()` — they still require live session.

---

## Integration: `pipeline/write.py`

In the Application fact sheet generation loop (Step 4):
- After building each fact sheet dict, call `_enrich_with_lpr(fs, lpr_catalog)`
- `_enrich_with_lpr` looks up `fs["displayName"]` in `rsa_name_index`
- On match: sets `fs["externalId"] = material_ids[0]` and `fs["lprId"] = lpr_id`
- No match: no-op (field stays absent, does not break import)

The LPR catalog is loaded once at the start of the write step.

---

## Error handling

| Scenario | Behavior |
|---|---|
| `sap_lpr_catalog.json` missing | `resolve_app_to_skus_offline` logs warning, returns `resolved_by = "not_found"` for all |
| LPR has no material_ids | `externalId` stays absent; `lpr_id` still populated |
| RSA name not in `rsa_name_index` | No-op, logged at DEBUG level |
| MXP query fails during build | Script exits with error, existing JSON unchanged |

---

## Files changed

| File | Change |
|---|---|
| `pipeline/build_lpr_catalog.py` | **New** — build script |
| `knowledge/sap_lpr_catalog.json` | **New** — generated artifact |
| `pipeline/lift_shift.py` | **Modified** — add `resolve_app_to_skus_offline()`, fallback logic |
| `pipeline/write.py` | **Modified** — add `_enrich_with_lpr()`, call in Application loop |
| `.claude/commands/update-lpr-catalog.md` | **New** — slash command `/update-lpr-catalog` |

---

## Out of scope

- Fuzzy matching or Claude-based disambiguation (deferred)
- Updating `catalog_mxp.py` to embed LPR data in RSA catalog
- `convert_to_rise()` offline equivalent (requires full RISE mapping table)
