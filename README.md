# Archimedes AI

Automated SAP requirements enrichment pipeline. Takes a client Excel or PDF with raw functional requirements and enriches each row with:

- **Module** — SAP module (MM, FI, CO, etc.)
- **Business Capabilities** — 1–3 leaf BCs from the SAP Reference Business Architecture (RBA)
- **RSA application** — exact SAP Reference Solution Architecture app name
- **Coverage / Dev / Licensing** — standard classification fields
- **Comment** — functional description with t-codes, Fiori app IDs, and OSS Note references

Optionally pushes results to a **LeanIX** workspace as Application and BusinessCapability fact sheets.

---

## Architecture

```
input (.xlsx / .pdf)
        │
        ▼
  01  extract          → output/reqs_raw.json
        │
        ▼
  02  enrich           → output/reqs_enriched.json
        │  (Claude API, claude-sonnet-4-6)
        ▼
  03  validate         → output/validation_report.json
        │  (catalog checks, comment quality gate)
        ▼
  04  write            → output/<name>_enriched.xlsx
                           └── LeanIX push (optional)
```

See [`docs/architecture.md`](docs/architecture.md) for a detailed description of each step.

---

## Quickstart

```bash
# 1. Clone and install
git clone https://github.com/antorchasdata/archimedes-ai.git
cd archimedes-ai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY

# 3. Run
python run.py path/to/requirements.xlsx
```

Output files land in `output/` by default.

---

## Usage

```
python run.py <input_file> [options]

positional arguments:
  input_file            Path to .xlsx, .xls, or .pdf input file

options:
  --no-validate         Skip the validation step (validation errors won't block output)
  --push-leanix         Push enriched results to LeanIX
  --output-dir OUTPUT   Directory for output files (default: output)
```

### Examples

```bash
# Basic run
python run.py input/client_requirements.xlsx

# Skip validation (e.g. during development)
python run.py input/reqs.xlsx --no-validate

# Push to LeanIX after enrichment
python run.py input/reqs.xlsx --push-leanix

# Custom output directory
python run.py input/reqs.pdf --output-dir results/client_abc
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key |
| `LEANIX_API_TOKEN` | Only for `--push-leanix` | — | LeanIX API token |
| `LEANIX_WORKSPACE_ID` | Only for `--push-leanix` | — | LeanIX workspace UUID |
| `LEANIX_BASE_URL` | Only for `--push-leanix` | `https://app.leanix.net` | LeanIX instance URL |
| `ENRICH_MODEL` | No | `claude-sonnet-4-6` | Claude model ID |
| `ENRICH_BATCH_SIZE` | No | `10` | Requirements per Claude API call |
| `ENRICH_MAX_RETRIES` | No | `3` | Retries on Claude API error |
| `LOG_LEVEL` | No | `INFO` | Python logging level |

Copy `.env.example` to `.env` and fill in the values.

---

## Input format

The pipeline auto-detects the structure of the input file. It looks for:

- **ID column** — a header cell matching `id`, `req`, `n°`, `num`, `code`, or `ref` (case-insensitive)
- **Description column** — a header matching `description`, `requirement`, `title`, `detail`, or `name`
- **Area column** (optional) — a header matching `area`, `module`, `domain`, or `process`

The header row is detected automatically (first row with ≥ 2 non-null string cells).

For PDFs, the pipeline extracts the first table from each page using `pdfplumber`.

---

## Output format

### `output/reqs_raw.json`

```json
[
  {"id": "REQ_001", "description": "...", "area": "MM"},
  ...
]
```

### `output/reqs_enriched.json`

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
    "comment": "..."
  },
  ...
]
```

### `output/validation_report.json`

```json
{
  "total": 42,
  "passed": 40,
  "failed": 2,
  "errors": {
    "REQ_007": ["REQ_007: comment missing Fiori app ID (e.g. '(F0842A)')"],
    "REQ_019": ["REQ_019: rsa 'Ariba' not in RSA catalog. Valid values: [...]"]
  }
}
```

### `output/<name>_enriched.xlsx`

Original template with columns H–P filled in:

| Col | Field |
|---|---|
| H | coverage |
| I | module |
| J | dev |
| K | dev_exp |
| L | ext_apps |
| M | licensing |
| N | comment |
| O | Business Capabilities (full RBA paths) |
| P | RSA application |

---

## Knowledge base

The `knowledge/` directory contains the SAP reference catalogs:

- **`sap_rba_catalog.json`** — SAP Reference Business Architecture. Used for BC name lookup and validation.
- **`sap_rsa_catalog.json`** — SAP Reference Solution Architecture. Defines valid RSA application names.
- **`prompt_template.txt`** — Master prompt sent to Claude. See [`docs/prompt_design.md`](docs/prompt_design.md) for rationale.

---

## Running tests

```bash
pytest tests/ -v
```

Tests cover the validation logic in `pipeline/validate.py`. See `tests/test_validate.py`.

---

## Project structure

```
archimedes-ai/
├── run.py                    # CLI entry point
├── requirements.txt
├── .env.example
├── pipeline/
│   ├── extract.py            # Step 1 — parse Excel/PDF
│   ├── enrich.py             # Step 2 — Claude API enrichment
│   ├── validate.py           # Step 3 — quality gate
│   └── write.py              # Step 4 — Excel + LeanIX output
├── knowledge/
│   ├── sap_rba_catalog.json
│   ├── sap_rsa_catalog.json
│   └── prompt_template.txt
├── tests/
│   └── test_validate.py
└── docs/
    ├── architecture.md
    └── prompt_design.md
```

---

## Contributing

1. Fork and create a feature branch
2. Run `pytest tests/` before submitting a PR
3. Keep prompt changes documented in `docs/prompt_design.md`
4. Do not commit `.env`, client data, or files under `output/` or `input_samples/`
