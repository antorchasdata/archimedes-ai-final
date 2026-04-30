# Prompt Design

## Overview

The enrichment prompt in `knowledge/prompt_template.txt` is the core of the pipeline. It instructs Claude to act as a senior SAP architect and produce a structured JSON object for each requirement. This document explains every design decision.

---

## Persona

```
You are a senior SAP S/4HANA Enterprise Architect with deep expertise in SAP Reference Business Architecture (RBA) and SAP Reference Solution Architecture (RSA).
```

**Why:** Claude produces more accurate SAP field values (t-codes, movement numbers, module paths) when given an explicit expert persona. Without it, output tends to be generic and lacks SAP-specific technical depth.

---

## Input section

```
Requirement ID: {req_id}
Description: {description}
Area (if known): {area}
```

The `area` field is optional — many client files have it, but the pipeline fills it as empty string if absent. The prompt handles this gracefully because Claude is instructed to default to S/4HANA when unsure.

---

## Catalog injection

Both catalogs (`sap_rba_catalog.json` short_name_index and `sap_rsa_catalog.json` applications) are injected directly into the prompt at runtime. This has two advantages:

1. **Catalog control** — you can add new BC aliases or RSA entries by editing the JSON files without touching the prompt or code.
2. **Grounding** — Claude sees the exact allowed values and is less likely to hallucinate BC names or RSA app names.

The short_name_index (flat dict of `"short name" → "Domain / leaf BC"`) is used instead of the full nested catalog because it is more compact and the flat form matches the output format expected.

---

## Output format enforcement

The prompt asks for a JSON object and shows the exact schema. We wrap it in a markdown code block in the *example* but instruct Claude to return "ONLY a valid JSON object, no markdown, no explanation".

In practice Claude often returns a markdown code fence anyway. The enricher in `pipeline/enrich.py` strips these with a regex before parsing:

```python
text = re.sub(r"^```(?:json)?\s*", "", text.strip())
text = re.sub(r"\s*```$", "", text)
```

---

## Field-by-field rules

### `module`

Follows the SAP module path convention used in project documentation:

```
SAP S/4HANA – Finance (FI) / Asset Accounting (FI-AA)
```

This format helps readers identify the submodule quickly without needing to know SAP module codes by heart.

### `bcs`

The most sensitive field. Two design decisions:

**1. Exactly 2 BCs (updated to 1–3):**
The validator now accepts 1–3 BCs. The prompt still says "EXACTLY 2" because empirically Claude produces better results with a concrete number. If a requirement clearly spans 3 areas, the validator won't reject 3 items.

**2. No domain roots:**
The prompt explicitly forbids domain roots (e.g., `"Sourcing and Procurement"`) and requires leaf BCs. The validator enforces this by checking that every resolved full path contains `/`. The prompt includes a correct/incorrect example to reinforce this.

**Why two distinct BCs?**
A single BC would lose the cross-functional nature of many requirements. Three or more BCs would make the data noisy and hard to aggregate in LeanIX reports.

### `rsa`

The exact-match requirement is critical for LeanIX integration — the RSA name becomes a tag or linked fact sheet in LeanIX. Any variation (e.g., `"SAP Ariba"` instead of `"SAP Ariba, SAP S/4HANA"`) breaks downstream linking.

The `licensing = "Adicional"` constraint is enforced both in the prompt and in the validator. This mirrors the billing model: any SAP product beyond the base S/4HANA license requires "Adicional" licensing classification.

### `comment`

The comment is the highest-value output. It must satisfy:

| Requirement | Rationale |
|---|---|
| Functional mechanism (2–4 sentences) | Gives architects enough context to evaluate coverage without reading SAP help |
| SAP movement numbers | Movement numbers (101, 261, etc.) are the precise identifiers that consultants use — generic descriptions are insufficient |
| T-codes with descriptions | Client-facing deliverables need t-codes to map requirements to SAP screens |
| Fiori app with ID | The `(F0842A)` pattern is machine-detectable by the validator; it ensures the Fiori layer is covered |
| 2 OSS Notes with titles | OSS Notes are the authoritative SAP knowledge base. Requiring titles (not just numbers) forces the model to provide context, making the notes useful and verifiable |
| No URLs | SAP Help Portal URLs expire or change. The comment should be self-contained |
| Spanish language | Client deliverables are in Spanish; SAP technical terms stay in English/German as they appear in SAP systems |

---

## Examples section

The prompt includes CORRECT vs INCORRECT examples for `bcs`, `rsa`, and `comment`. These are the most common failure modes observed during prompt development:

- **bcs incorrect:** Using a domain root instead of a leaf BC
- **rsa incorrect:** Abbreviating the RSA name ("Ariba" instead of "SAP Ariba, SAP S/4HANA")
- **comment incorrect:** Including a URL, or citing an OSS Note without a title

---

## Iteration history

| Version | Change | Reason |
|---|---|---|
| v1 | Basic field list, no catalog injection | First draft — produced hallucinated BC names |
| v2 | Added RBA catalog injection | Reduced BC hallucination significantly |
| v3 | Added RSA catalog, exact-match instruction | Eliminated RSA name variations |
| v4 | Added OSS Note title requirement | Notes without titles were unverifiable |
| v5 | Added `([A-Z]\d{4,5}[A-Z]?)` Fiori pattern instruction | Validator-testable format |
| v6 | Added correct/incorrect examples | Reduced domain root BCs and URL inclusions |

---

## Updating the prompt

1. Edit `knowledge/prompt_template.txt` directly.
2. Run a test batch: `python pipeline/enrich.py` on a small sample (5–10 requirements).
3. Check `output/reqs_enriched.json` for quality.
4. Run `pytest tests/` to ensure the validator still works.
5. If adding new catalog entries, update `knowledge/sap_rba_catalog.json` or `knowledge/sap_rsa_catalog.json` — no code changes needed.

---

## Catalog maintenance

### Adding a new BC alias

Edit `knowledge/sap_rba_catalog.json` — add to both `catalog` and `short_name_index`:

```json
"short_name_index": {
  ...
  "My New BC Alias": "Domain Name / Leaf BC Name"
}
```

The validator uses `short_name_index` for lookup, so the alias will be accepted immediately.

### Adding a new RSA application

Edit `knowledge/sap_rsa_catalog.json`:

```json
{
  "applications": [
    ...
    {"name": "SAP BTP, SAP S/4HANA", "use_when": "When the requirement needs BTP services"}
  ]
}
```

The validator will accept the new name on the next run.
