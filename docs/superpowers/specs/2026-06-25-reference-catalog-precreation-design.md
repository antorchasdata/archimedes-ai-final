# Reference Catalog pre-creation resolution — design spec

**Date:** 2026-06-25
**Author:** Archimedes AI team
**Status:** Draft for review

## Context and problem

Internal LeanIX guidelines require that Applications and IT Components created in a
workspace be linked to the official **Reference Catalog** (`saas` source for
Applications, `ltls` source for IT Components) at creation time — not patched in
afterwards.

Today Archimedes does the opposite: the staging Excel is generated from
Claude-enriched names, the push creates plain custom fact sheets, and only **after**
the push does `_link_apps_to_catalog` (`pipeline/write.py:1769`) call
`POST /services/reference-data/v1/source/{saas|ltls}/batch-links` to attach catalog
entries on `VERYHIGH` confidence matches. Anything below `VERYHIGH` stays a custom
fact sheet pending manual review.

This is not compliant with the guideline. The Excel rows themselves carry no catalog
identifier, so the audit trail of "this app was created from a catalog entry" is
weak.

## Goal

Resolve every Application/ITComponent name against the Reference Catalog **before
writing the staging Excel**, so each row carries its catalog `externalId`
(`lx_APP_NNNNNN` / `lx_ITC_NNNNNN`) where a match exists, and the push creates
fact sheets that are already linked to the catalog. Below the resolver-decided
confidence threshold, fall back gracefully to custom fact sheets — never block
the pipeline.

## Non-goals

- Changing the Claude enrichment flow (`pipeline/enrich.py`). Catalog resolution
  is orthogonal.
- Adding new fact sheet types to the catalog flow beyond Application and
  ITComponent (BusinessCapability catalog exists but is out of scope here).
- Removing the existing post-push `_link_apps_to_catalog` — it remains as a
  safety net for rows that ship without an `externalId`.

## API endpoints used

All endpoints documented in
`leanix__ea__application-reference-catalog-api.md` and
`leanix__ea__itc-reference-catalog-api.md` (internal/undocumented LeanIX APIs,
Admin token required).

| Purpose | Method + Path |
|---|---|
| Token | `POST /services/mtm/v1/oauth2/token` (`grant_type=client_credentials`) |
| Search by name | `GET /services/reference-data/v1/source/{saas\|ltls}/fact-sheets?q=<name>&factSheetType=<type>&fuzzy=false` |
| Confidence (probe) | `POST /services/reference-data/v1/source/{saas\|ltls}/batch-links` |
| Fetch catalog detail | `GET /services/reference-data/v1/source/{saas\|ltls}/fact-sheets/<externalId>` |
| Probe FS create/update/archive | GraphQL `pathfinder` mutations |

Key constraint: `batch-links` requires a workspace fact sheet UUID — the only way
to obtain a real `confidenceLevel` for an arbitrary name is the **Probe Pattern**
documented by LeanIX (create temp FS → batch-links → archive).

## Design

### New module: `pipeline/reference_catalog.py`

Encapsulates all Reference Catalog logic. Public API:

```python
@dataclass
class ResolvedMatch:
    name: str
    external_id: str | None        # lx_APP_NNNNNN / lx_ITC_NNNNNN
    catalog_uuid: str | None
    display_name: str | None       # canonical catalog name (may differ from input)
    confidence: str                # VERYHIGH | HIGH | MEDIUM | LOW | NONE
    status: str                    # LINKED | CUSTOM
    fields: dict                   # description, hostingType, productCategory, provider

class ReferenceCatalogResolver:
    def __init__(self, base_url: str, api_token: str, interactive: bool = True): ...
    def resolve(self, fs_type: str, names: list[str]) -> dict[str, ResolvedMatch]: ...
    def cleanup(self) -> None:   # archive probe FSs
```

`fs_type` accepts `"Application"` or `"ITComponent"`. The resolver picks the right
source (`saas`/`ltls`) internally.

### Integration point

In `pipeline/write.py:write_leanix_excel` (line 367), immediately after the
deduplicated app and ITC lists are built and before the workbook is written:

```
apps_dedup, itcs_dedup = ...                                # existing code
resolver = ReferenceCatalogResolver(base_url, token)        # NEW
app_matches = resolver.resolve("Application", apps_dedup)
itc_matches = resolver.resolve("ITComponent", itcs_dedup)
# … rows are decorated with external_id / catalog fields before _xl.save() …
resolver.cleanup()
```

`base_url` and `token` come from the same `_get_bearer` path as
`_link_apps_to_catalog`.

The Excel gains the following columns (optional — push reads them only if
present, so backwards compatibility is preserved):

| Column | Sheet | Purpose |
|---|---|---|
| `externalId` | Application, ITComponent | `lx_APP_*` / `lx_ITC_*` when LINKED |
| `catalog_confidence` | Application, ITComponent | `VERYHIGH \| HIGH \| MEDIUM \| LOW \| NONE` |
| `catalog_status` | Application, ITComponent | `LINKED \| CUSTOM` |

For LINKED rows the resolver also overwrites `description`, `lxHostingType`,
`productCategory`, `provider` in the row with the catalog's values (catalog wins
on match).

### Push consumes `externalId`

`pipeline/push_ldif.py` and the GraphQL push path in `write.py` read `externalId`
from each row. When present, the `createFactSheet` payload includes
`externalId` so LeanIX automatically attaches the catalog link at creation time.
When absent, behavior is unchanged.

### `_link_apps_to_catalog` remains as a safety net

The existing post-push function (`write.py:1769`) keeps running, but skips any
fact sheet whose row already carried an `externalId`. It only resolves entries
that arrived as CUSTOM — handles the case where the resolver was unavailable or
failed.

## Resolution algorithm

For each name:

```
Step 1 — Lightweight lookup (no probe)
   GET /services/reference-data/v1/source/{saas|ltls}/fact-sheets
       ?q=<name>&factSheetType=<type>&fuzzy=false
   → candidate list (≤ 50)

Step 2 — Heuristic decision
   a) 0 candidates                       → status=CUSTOM,  confidence=NONE.  Stop.
   b) ≥1 candidate AND any candidate's displayName equals name
      (case-insensitive, whitespace-normalized):
                                         → status=LINKED,  confidence=VERYHIGH.
                                           Fetch full fields via
                                           GET /fact-sheets/{externalId}.  Stop.
   c) Otherwise                          → continue to Step 3.

Step 3 — Probe against batch-links (only for ambiguous names)
   3a) Ensure probe FS exists for this type:
       "_archimedes_probe_application" / "_archimedes_probe_itcomponent"
       Created lazily on first ambiguous name.
   3b) GraphQL: updateFactSheet(probe_id, name=<name>)
   3c) POST /batch-links
       { factSheets:[{id:probe_id, name:<name>, catalogStatus:"n/a"}],
         numMatches:3 }
   3d) Read top suggestion's confidenceLevel.

Step 4 — Confidence-based decision
   VERYHIGH                  → status=LINKED, auto-link.
   HIGH or MEDIUM            → interactive CLI prompt:
                                "Link '<name>' to '<catalog displayName>'
                                 (confidence=HIGH)? [Y/n/s(kip all)]"
                                Y → LINKED
                                n → CUSTOM
                                s → set skip-all flag; rest of run treats
                                    HIGH/MEDIUM as CUSTOM with no prompt
   LOW or NONE               → CUSTOM
   If LINKED                 → GET /fact-sheets/{externalId} for full fields.

Step 5 — Local cache
   output/<client>/.catalog_cache.json keyed by (fs_type, normalize(name)).
   Reused across runs for the same client. Cache writes are atomic
   (write to .tmp + rename) so an interrupted run cannot corrupt it.

Step 6 — Cleanup
   resolver.cleanup() archives probe FSs (status=ARCHIVED).
   Also runs at __init__: searches for FSs named "_archimedes_probe_*"
   and archives any orphans from previous failed runs.
```

### Interactivity rules

- `ReferenceCatalogResolver(interactive=False)` OR `not sys.stdin.isatty()` →
  HIGH/MEDIUM are silently treated as CUSTOM. Only VERYHIGH auto-links.
- `s` (skip-all) is one-shot per resolver instance — does not persist across
  runs.

### Catalog-wins policy

When `status=LINKED`, the row's `description`, `lxHostingType`, `productCategory`,
and `provider` fields are overwritten with the catalog's values from
`GET /fact-sheets/{externalId}`. Other Claude-derived fields (lifecycle,
businessCriticality, BC links, comments) are preserved.

## Error handling

Principle: **the pipeline never fails because of the Reference Catalog.** Every
failure mode degrades to `status=CUSTOM` for the affected name(s), the Excel is
generated regardless, and the existing post-push `_link_apps_to_catalog` provides
a second chance.

| Failure | Detection | Response |
|---|---|---|
| Token unobtainable (403/auth) | `_get_bearer` raises | Log warning, **all** names → CUSTOM. Pipeline continues. |
| `GET ?q=` returns 404/5xx | HTTP exception | That name → CUSTOM. Others unaffected. |
| Probe `createFactSheet` fails | GraphQL exception | Resolver enters **no-probe mode**: only Step 2 heuristic applies. Warn once. |
| `batch-links` returns 400/5xx | HTTP exception | That name → CUSTOM. Probe FS retained for next name. |
| `updateFactSheet` (probe rename) fails | GraphQL exception | Recreate probe FS with new name; archive old. Two consecutive failures → no-probe mode. |
| Archive on cleanup fails | GraphQL exception | Log warning with orphan FS id. Next run's init cleanup will retry. Pipeline does NOT fail. |
| API call >30s | requests timeout | That name → CUSTOM. Retry with backoff (3 attempts: 2s/4s/8s). |
| Rate limit 429 | status code | Exponential backoff with jitter, up to 3 retries. Then CUSTOM. |
| Non-interactive context | `interactive=False` or no TTY | HIGH/MEDIUM → CUSTOM silently. Only VERYHIGH auto-links. |

### Logging

End-of-resolve summary log line:

```
Reference Catalog Application: 47 names — 12 LINKED via exact-match,
  8 LINKED via probe+VERYHIGH, 5 LINKED via probe+HIGH(confirmed),
  22 CUSTOM. Probe API calls: 13.
```

Per-name detail written to `output/<client>/catalog_resolution_report.json`
for audit.

## Testing

### Unit tests — `tests/test_reference_catalog.py`

Mock `requests` (via `responses` or `unittest.mock`). Cover:

- `test_exact_match_no_probe` — 1 candidate, exact displayName → VERYHIGH, no batch-links call.
- `test_zero_candidates_custom` — empty `[]` → CUSTOM/NONE.
- `test_ambiguous_triggers_probe` — multiple partial candidates → batch-links invoked.
- `test_probe_veryhigh_auto_link` — confidence VERYHIGH → LINKED with no prompt.
- `test_probe_high_interactive_accept` — confidence HIGH + stdin "y" → LINKED.
- `test_probe_high_interactive_reject` — confidence HIGH + stdin "n" → CUSTOM.
- `test_probe_skip_all` — stdin "s" → subsequent HIGH/MEDIUM go to CUSTOM silently.
- `test_probe_low_custom` — confidence LOW → CUSTOM, no prompt.
- `test_non_interactive_mode` — `interactive=False` → HIGH/MEDIUM → CUSTOM.
- `test_cache_hit_skips_api` — second resolve of same name → zero API calls.
- `test_token_failure_all_custom` — bearer fails → all names CUSTOM, no raise.
- `test_probe_create_fails_degrades` — createFactSheet raises → no-probe mode activated.
- `test_cleanup_archives_probes` — `cleanup()` issues mutation with `status=ARCHIVED`.
- `test_initial_cleanup_finds_orphans` — orphan probes from prior runs archived at `__init__`.
- `test_normalization_idempotent` — "SAP S/4HANA" and "sap s/4hana" hit the same cache key.
- `test_fields_overwrite_from_catalog` — LINKED match copies description, hostingType into row.

### Integration tests — `tests/test_write_with_catalog.py`

Mock `ReferenceCatalogResolver` entirely. Verify `write_leanix_excel` produces
correct Excel output:

- `test_excel_carries_external_id` — LINKED apps → `externalId` column populated.
- `test_custom_apps_no_external_id` — CUSTOM apps → `externalId` empty.
- `test_catalog_fields_in_excel` — catalog `description`, `hostingType` appear on LINKED rows.
- `test_resolver_failure_pipeline_continues` — resolver raises → Excel still generated, no `externalId`s.

### Coverage target

- `pipeline/reference_catalog.py` ≥ 85% line coverage.
- All fail-safe branches covered explicitly, not just the happy path.

### Out of scope

Manual smoke testing against a real demo workspace is **not** part of this
deliverable. If needed later, it can be added as a separate task.

## Open questions

None at design-approval time.

## Rollout

1. Land `pipeline/reference_catalog.py` + tests behind a feature flag
   (`ARCHIMEDES_USE_CATALOG_RESOLVER=true`, default off).
2. Run one real customer pipeline with the flag enabled, compare staging Excel
   diff and post-push behavior with current behavior.
3. Flip the default to `on`; keep flag for emergency disable.
4. After two successful customer runs, remove the flag.
