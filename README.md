# Archimedes AI

AI-powered orchestrator that automates SAP LeanIX population from client data. Converts OnPrem/Cloud inventories, requirements Excel files, PDFs, and architecture diagrams into LeanIX-importable Excel files — covering the full EA cycle: AS-IS Baseline + TO-BE Target.

**Engine**: Claude API (`claude-sonnet-4-6`) + SAP RBA catalog (756 BCs, 22 domains) + SAP RSA catalog (324 products)

---

## What it produces

| Output file | Content |
|---|---|
| `<client>_baseline.xlsx` | AS-IS applications with `Baseline;OnPremise` / `Baseline;Cloud` tags |
| `<client>_target_leanix.xlsx` | TO-BE: Application, BusinessCapability, Initiative, ITComponent sheets |
| `<client>_supplementary_factsheets.json` | Fact sheets extracted from PDFs and diagrams (also merged into target Excel) |

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
# Edit .env — set ANTHROPIC_API_KEY at minimum

# 3. Run interactive pipeline
python3 run.py pipeline --client <client_name>
```

The pipeline prompts for each input file and can skip any step.

---

## Pipeline — 5 steps

```
STEP 0  Catalog check       — verifies RBA/RSA version, offers update
STEP 1  Baseline AS-IS      — OnPrem + Cloud Excel → <client>_baseline.xlsx
STEP 2  Requirements TO-BE  — Excel → Claude API (RBA/RSA mapping) → enriched output
        + PDF extraction    — PDFs → Claude API → supplementary fact sheets
STEP 3  Images/diagrams     — PNG/JPG → Claude Vision → apps and IT components
STEP 4  Output generation   — multi-sheet LeanIX Excel (Application, BC, Initiative, ITC)
STEP 5  LeanIX import       — optional GraphQL push (BC → ITC → App → Initiative)
```

---

## Commands

```bash
# Full interactive pipeline (recommended)
python3 run.py pipeline --client <name>

# Enrich only (extract → enrich → validate → write)
python3 run.py enrich <requirements.xlsx> --client <name>

# Push a previously generated staging Excel to LeanIX
python3 run.py push <client_target_leanix.xlsx> --client <name>
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `LEANIX_API_TOKEN` | For push | LeanIX API token |
| `LEANIX_BASE_URL` | For push | LeanIX instance URL |
| `ENRICH_MODEL` | No (default: `claude-sonnet-4-6`) | Claude model ID |
| `ENRICH_BATCH_SIZE` | No (default: `10`) | Requirements per batch |
| `ENRICH_MAX_RETRIES` | No (default: `3`) | Retries on API error |
| `LOG_LEVEL` | No (default: `INFO`) | Python logging level |
| `ARCHIMEDES_USE_CATALOG_RESOLVER` | No (default: `false`) | Set to `true`/`1`/`yes` to resolve Application & ITComponent names against the LeanIX Reference Catalog **before** the staging Excel is written. When enabled, matched rows carry an `externalId` (e.g. `lx_APP_000123`) so fact sheets are created already linked to the official catalog entry. Requires `LEANIX_BASE_URL` + `LEANIX_API_TOKEN`. |

### Reference Catalog resolver (optional)

When `ARCHIMEDES_USE_CATALOG_RESOLVER=true`, the writer queries the LeanIX
Reference Catalog (sources `saas` for Application, `ltls` for ITComponent)
and decorates each row with the catalog `externalId` if a confident match
is found. Two long-lived probe fact sheets named
`_archimedes_probe_application` and `_archimedes_probe_itcomponent` are
created on first use and archived at the end of the run (cleanup is
idempotent). An audit JSON file `catalog_resolution_report.json` is
written next to the staging Excel listing every resolved name with its
confidence and `LINKED`/`CUSTOM` status.

---

## Architecture

```
archimedes-ai/
├── run.py                      # CLI orchestrator (pipeline / enrich / push)
├── pipeline/
│   ├── catalog.py              # Step 0 — RBA/RSA version check
│   ├── footprint.py            # Step 1 — Baseline AS-IS from OnPrem/Cloud Excel
│   ├── extract.py              # Step 2 — parse requirements Excel
│   ├── enrich.py               # Step 2 — Claude API enrichment with catalog subsetting
│   ├── validate.py             # Step 2 — quality gate
│   ├── write.py                # Step 4 — Excel + LeanIX output + GraphQL push
│   ├── pdf_extract.py          # Step 2 — PDF → fact sheets via Claude API
│   └── image_extract.py        # Step 3 — diagrams → fact sheets via Claude Vision
├── knowledge/
│   ├── sap_rba_catalog.json    # 756 BCs, 22 domains (v2026-05)
│   ├── sap_rsa_catalog.json    # 324 SAP products (v2026-05)
│   └── prompt_template.txt     # Enrichment prompt template
├── archimedes_wizard.py        # Web wizard UI (guided pipeline)
├── archimedes_chat.py          # Conversational interface for enriched data
└── output/
    └── <client>/               # All outputs per client engagement
```

---

## Key design decisions

- **Catalog subsetting**: before enrichment, a pre-scan call identifies relevant RBA L1 domains. Only BCs from those domains are sent in each enrichment prompt — reducing catalog tokens by ~70-80%.
- **Checkpoint/resume**: enrichment writes a checkpoint every 10 requirements. If the run is interrupted, the next execution resumes from where it left off instead of starting over.
- **Supplementary merge**: fact sheets extracted from PDFs and images are automatically merged into the final `target_leanix.xlsx` — no manual copy-paste needed.
- **Idempotent LeanIX push**: Applications, Business Capabilities, and Initiatives all use upsert logic — re-running the pipeline against the same workspace updates existing fact sheets instead of creating duplicates.
- **Client name sanitization**: `--client` values are sanitized before use in file paths to prevent path traversal.

---

## Proven results — Acciona

| Phase | Metric | Result |
|---|---|---|
| Baseline AS-IS | Total applications | 37 apps |
| Baseline AS-IS | On-Premise | 14 apps (`Baseline;OnPremise`) |
| Baseline AS-IS | Cloud | 23 apps (`Baseline;Cloud`) |
| Requirements | Rows analyzed | 462 rows |
| Target TO-BE | SAP applications | 7 canonical RSA apps |
| Target TO-BE | Business Capabilities | 20 leaf BCs with parent hierarchy |
| Target TO-BE | Initiatives | 9 (grouped by process) |
| Target TO-BE | IT Components | 8 ITCs |

Time to populate LeanIX: **minutes**, vs. 2–3 days manual.

---

## Running tests

```bash
pytest tests/ -v
```

---

## Input formats

- **OnPrem/Cloud Systems Excel**: any Excel with application names and hosting info
- **Requirements Excel**: any Excel with ID + description columns (auto-detected)
- **PDF**: proposals, RFPs, architecture reports — Claude extracts fact sheets
- **Images**: PNG/JPG architecture diagrams — Claude Vision extracts apps and IT components
