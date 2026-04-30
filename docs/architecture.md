# Architecture

## Overview

Archimedes AI is a four-step sequential pipeline. Each step reads from a JSON file written by the previous step, so any step can be re-run independently.

```
run.py
  │
  ├─ extract(input_path, output_dir)  → output/reqs_raw.json
  ├─ enrich(raw_path, output_dir)     → output/reqs_enriched.json
  ├─ validate(enriched_path, ...)     → output/validation_report.json
  └─ write(enriched_path, ...)        → output/<name>_enriched.xlsx
```

---

## Step 1 — Extract (`pipeline/extract.py`)

**Input:** `.xlsx`, `.xls`, or `.pdf`
**Output:** `output/reqs_raw.json` — list of `{id, description, area}` objects

### Excel/XLS

1. Auto-detect the header row: scan the first 15 rows for the first row with ≥ 2 non-null string cells.
2. Auto-detect columns by header name using regex patterns:
   - ID column: `\b(id|req|requ|n[oº°]|num|code|ref)\b`
   - Description column: `\b(description|requirement|title|detail|name)\b`
   - Area column (optional): `\b(area|module|domain|process)\b`
3. Iterate data rows; skip rows where the ID cell is empty.

### PDF

1. Use `pdfplumber` to extract tables from each page.
2. Treat the first non-empty row as the header.
3. Apply the same column detection logic as Excel.

### Output schema

```json
[
  {"id": "REQ_001", "description": "Manage purchase orders end-to-end", "area": "MM"},
  ...
]
```

---

## Step 2 — Enrich (`pipeline/enrich.py`)

**Input:** `output/reqs_raw.json`
**Output:** `output/reqs_enriched.json`

### Process

For each requirement:

1. Build the enrichment prompt by filling `knowledge/prompt_template.txt` with:
   - `{req_id}`, `{description}`, `{area}`
   - `{rba_catalog}` — JSON dump of `knowledge/sap_rba_catalog.json`
   - `{rsa_catalog}` — JSON dump of `knowledge/sap_rsa_catalog.json`

2. Call the Claude API (`claude-sonnet-4-6` by default) and request a JSON object.

3. Parse the response:
   - Strip markdown code fences if present (```` ```json ... ``` ````)
   - Parse as JSON
   - Retry up to `ENRICH_MAX_RETRIES` times with exponential backoff on failure

4. On unrecoverable error: emit the requirement with `_error: true` and a placeholder `comment` so downstream steps can skip gracefully.

### Output schema

```json
[
  {
    "id": "REQ_001",
    "module": "SAP S/4HANA – MM",
    "bcs": ["Operational Procurement", "Procurement Contract Management"],
    "rsa": "SAP S/4HANA",
    "coverage": "Total",
    "dev": "No",
    "dev_exp": "",
    "ext_apps": "",
    "licensing": "Básico",
    "comment": "El proceso de compras en S/4HANA ..."
  }
]
```

### Rate limiting and retries

The enricher uses `ENRICH_BATCH_SIZE` (default 10) as a processing unit. Retries apply per-requirement with delays of 2, 4, 8 seconds (exponential backoff). Requirements that fail all retries are written with `"_error": true`.

---

## Step 3 — Validate (`pipeline/validate.py`)

**Input:** `output/reqs_enriched.json`
**Output:** `output/validation_report.json`, return value `bool`

### Validation rules

| # | Check | Error condition |
|---|---|---|
| 1 | Required fields | Any of `module`, `bcs`, `rsa`, `coverage`, `dev`, `licensing`, `comment` is missing or empty |
| 2 | BCS list size | `bcs` is empty or has more than 3 items |
| 3 | BCS catalog lookup | Any BC short name is not in `short_name_index` |
| 4 | BCS duplicate full paths | Two short names resolve to the same full path |
| 5 | BCS bare domain | Any full path does not contain `/` (root domain, not a leaf BC) |
| 6 | RSA name | `rsa` value not in `sap_rsa_catalog.json` |
| 7 | Licensing vs RSA | `rsa != "SAP S/4HANA"` but `licensing != "Adicional"` |
| 8 | Coverage enum | `coverage` not in `{"Total", "Parcial", "No cubierto"}` |
| 9 | Comment — no URLs | Comment contains `http://` or `https://` |
| 10 | Comment — Fiori ID | Comment does not match `([A-Z]\d{4,5}[A-Z]?)` |
| 11 | Comment — OSS Notes | Comment has fewer than 2 matches of `OSS Note XXXXXXX –` |

### Report format

```json
{
  "total": 42,
  "passed": 40,
  "failed": 2,
  "errors": {
    "REQ_007": ["REQ_007: comment missing Fiori app ID (e.g. '(F0842A)')"],
    "REQ_019": ["REQ_019: rsa 'Ariba' not in RSA catalog. ..."]
  }
}
```

`validate()` returns `True` if `failed == 0`, `False` otherwise. `run.py` exits with code 1 when validation fails, unless `--no-validate` is passed.

---

## Step 4 — Write (`pipeline/write.py`)

**Input:** `output/reqs_enriched.json` + original template file
**Output:** `output/<stem>_enriched.xlsx` + optional LeanIX push

### Excel output

1. Read the original template with `pandas` (preserving all columns).
2. Auto-detect header row and ID column (same logic as Step 1).
3. For each row in the template, look up the requirement by ID and fill columns H–P:

| Col index | Field |
|---|---|
| H (7) | coverage |
| I (8) | module |
| J (9) | dev |
| K (10) | dev_exp |
| L (11) | ext_apps |
| M (12) | licensing |
| N (13) | comment |
| O (14) | Business Capabilities — full RBA paths, `" | "` separated |
| P (15) | RSA application |

4. Write with `openpyxl` engine (preserves formatting better than xlsxwriter for edits).

### LeanIX output

Triggered by `--push-leanix` flag or `LEANIX_PUSH=true` env var.

1. **Authenticate** — POST to `/services/mtm/v1/oauth2/token` with `client_credentials` grant using `LEANIX_API_TOKEN`. Cache the bearer token.

2. **For each requirement:**
   - Create an **Application** fact sheet (name = requirement ID, description = comment truncated to 2000 chars)
   - For each BC in `bcs`:
     - Resolve short name → full path via `short_name_index`
     - Create a **BusinessCapability** fact sheet (name = leaf BC, i.e. the part after ` / `)
     - Cache BC IDs to avoid duplicate creates
   - Create `relApplicationToBusinessCapability` relations

3. Requirements with `_error: true` are skipped.

All GraphQL mutations use the LeanIX Pathfinder v1 API at `{LEANIX_BASE_URL}/services/pathfinder/v1/graphql`.

---

## Knowledge base

### `knowledge/sap_rba_catalog.json`

```json
{
  "catalog": {
    "Sourcing and Procurement": {
      "Operational Procurement": "...",
      "Procurement Contract Management": "..."
    },
    ...
  },
  "short_name_index": {
    "Operational Procurement": "Sourcing and Procurement / Operational Procurement",
    ...
  }
}
```

`short_name_index` is the primary lookup used by both the enrichment prompt and the validator. To add a new BC alias, add an entry here.

### `knowledge/sap_rsa_catalog.json`

```json
{
  "applications": [
    {"name": "SAP S/4HANA", "use_when": "..."},
    {"name": "SAP Ariba, SAP S/4HANA", "use_when": "..."},
    ...
  ]
}
```

### `knowledge/prompt_template.txt`

Master prompt for Claude enrichment. See [`prompt_design.md`](prompt_design.md).

---

## Data flow diagram

```
  ┌─────────────────────┐
  │  client_reqs.xlsx   │
  └────────┬────────────┘
           │ pandas / pdfplumber
           ▼
  ┌─────────────────────┐
  │  reqs_raw.json      │  [{id, description, area}]
  └────────┬────────────┘
           │ Claude API (claude-sonnet-4-6)
           │ + knowledge/sap_rba_catalog.json
           │ + knowledge/sap_rsa_catalog.json
           │ + knowledge/prompt_template.txt
           ▼
  ┌─────────────────────┐
  │ reqs_enriched.json  │  [{id, module, bcs, rsa, coverage, ...}]
  └────────┬────────────┘
           │ catalog validation
           ▼
  ┌────────────────────────────┐
  │ validation_report.json     │  {total, passed, failed, errors}
  └────────────────────────────┘
           │
           ▼
  ┌──────────────────────────────────────┐
  │  client_reqs_enriched.xlsx           │  cols H–P filled
  │  + LeanIX Applications + BCs (opt)  │
  └──────────────────────────────────────┘
```
