# SAP Internal Discovery Integration — Design

**Date:** 2026-07-16
**Author:** SAP EA Practice (Archimedes AI)
**Status:** Draft — pending user review

> **Implementation status (as of Task 16 completion):** unit tests green.
> Runtime validation pending against a live demo workspace with
> Internal SAP Landscape Data enabled. Blockers to close v1:
> 1. Verify `{origin}` candidate list; adjust `Client._ORIGIN_CANDIDATES` if needed.
> 2. Verify body schema of `POST /discovery-sap-extension/v1/integrations`
>    against the workspace's `/v3/api-docs`.
> 3. Verify v2 Beta enabled in workspace, else confirm v1 fallback covers bulk_link/reject as well.

## Context

SAP LeanIX EA Delivery workspaces (internal-only) now support the **Internal SAP Landscape Data** integration, which replaces Cloud ALM for internal use cases. It populates the SAP Discovery inbox with System fact sheets discovered across the SAP corporate landscape for a given customer (identified by CRM ID / ERP ID).

Today, Archimedes populates the Baseline AS-IS by scraping ONE360 (Cloud Systems, OnPrem, Purchased Solutions) via Playwright MCP. This flow is fragile: browser session drift, file naming, download timing, CAPTCHA risk.

The new integration exposes the inbox and the linking workflow through REST APIs:

- `POST /services/discovery-sap-extension/v1/integrations`
- `PUT  /services/discovery-linking/v2/{origin}/settings/autoLinking`
- `GET  /services/discovery-linking/v2/{origin}/discoveryItems`
- `PUT  /services/discovery-linking/v2/{origin}/discoveryItems/link`
- `PUT  /services/discovery-linking/v2/{origin}/discoveryItems/reject`

This unlocks **Vía B**: Archimedes both **configures the integration** and **processes the inbox** end-to-end, replacing the ONE360 export flow for customers where the new integration is available.

## Goals

1. New parallel route in **Step 2 (Baseline)** of the wizard: user picks either **ONE360** (existing) or **SAP Internal Discovery** (new).
2. Two-phase asynchronous execution: configure integration → wait 5–10 min → process inbox.
3. Hybrid linking policy: enable LeanIX autolinking + Archimedes applies its own heuristics to `action_needed` / `review_needed` items + produces a review report with confirmable actions (same UX as Step 8 catalog linking).
4. Cover Application + IT Component + Provider fact sheets. Create missing fact sheets when the inbox proposes `create_and_link`.
5. Manual customer identification via CRM ID / ERP ID input (no CCC hierarchy dependency in v1).

## Non-goals

- Replacing ONE360 flow entirely. Both routes coexist. ONE360 remains for customers without Internal SAP Landscape Data enabled.
- Deep integration with Cloud ALM (this integration is mutually exclusive with Cloud ALM).
- Webhook-based orchestration (out of scope — no `DISCOVERY_ITEM_*` webhook event exists; polling is fine).
- Automatic CCC hierarchy fetch and subsidiary selection (deferred to v2).

## Architecture

New Python package `pipeline/sap_discovery/` following the existing project pattern (`catalog.py` + `catalog_report.py` + `reference_catalog.py`).

```
pipeline/sap_discovery/
├── __init__.py           # Public API: start_integration, poll_status, process_inbox, build_report, apply_review
├── client.py             # REST client (discovery-sap-extension + discovery-linking v2, v1 fallback)
├── matcher.py            # Pure matching heuristics → MatchDecision
├── orchestrator.py       # Two-phase orchestrator, uses client + matcher + write.py
└── report.py             # HTML/JSON report with confirmable actions
```

**Responsibility boundaries:**

- `client.py` — the only module that performs HTTP against LeanIX. Callers receive deserialized dicts/dataclasses. Reuses `pipeline.leanix_auth.get_bearer` for OAuth bearer.
- `matcher.py` — pure functions. Input: `(DiscoveryItem, candidate_catalogs)`. Output: `MatchDecision`. No I/O — trivial to unit-test.
- `orchestrator.py` — coordinates client + matcher + `pipeline.write` (for creating missing fact sheets). Persists state under `output/<session_id>/sap_discovery/`.
- `report.py` — reads persisted state, produces `report.html` + `report.json`. Same pattern as `pipeline/catalog_report.py`.

## Data contracts

### `DiscoveryItem`

```python
@dataclass
class DiscoveryItem:
    id: str                        # discovery item id
    display_name: str              # e.g. "SAP S/4HANA Cloud - PROD"
    classification: str            # SaaS_Product | SaaS_ERP | OnPrem_System | OnPrem_ERP
    product: str                   # "SAP S/4HANA Cloud"
    system_role: str | None        # PROD | DEVELOP | TEST
    status: str                    # linked | action_needed | review_needed | rejected
    suggested_links: dict          # {"application": [...], "itcomponent": [...], "provider": [...]}
                                   #   each item: {"factsheet_id": str | None, "name": str, "label": "existing" | "create_and_link"}
    raw: dict                      # complete payload for matcher fallback
```

### `MatchDecision`

```python
@dataclass
class MatchDecision:
    item_id: str
    action: Literal["link", "create_and_link", "reject", "review"]
    target_type: Literal["Application", "ITComponent", "Provider"] | None
    target_id: str | None          # None if action == "create_and_link" or "reject"
    create_payload: dict | None    # only if action == "create_and_link"
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    reason: str                    # human-readable, rendered in the report
```

### Matcher decision rules (v1)

- **HIGH** → LeanIX suggests an existing match (`label="existing"`) AND classification is known → `action="link"`, executed automatically.
- **MEDIUM** → LeanIX suggests `create_and_link` AND product is present in RBA/RSA catalog → `action="create_and_link"`, executed automatically.
- **LOW / ambiguous** → multiple candidates OR unknown classification → `action="review"`, added to report for human confirmation.
- Items arriving with `status="linked"` (already autolinked by LeanIX) are skipped entirely.

### Persisted state (per session)

Directory: `output/<session_id>/sap_discovery/`

| File | Content |
|------|---------|
| `integration.json` | `{integration_id, crm_id, created_at, autolinking_enabled, origin}` |
| `inbox_snapshot.json` | List of `DiscoveryItem` as returned by API |
| `decisions.json` | List of `MatchDecision` |
| `execution_log.json` | `{applied: [...], failed: [...], pending_review: [...]}` |
| `report.html` / `report.json` | Final report |

## Two-phase flow

### Phase 1 — configure integration

**Endpoint:** `POST /api/session/{sid}/baseline/from-sap-discovery`

**Body:** `{crm_id: str, enable_autolinking: bool = True}`

**Steps:**

1. `client.create_integration(crm_id)` →
   `POST /services/discovery-sap-extension/v1/integrations`
   body: `{customerIdentifiers: [{type: "CRM", id: crm_id}]}`
2. If `enable_autolinking`: `client.set_autolinking(origin, True)` →
   `PUT /services/discovery-linking/v2/{origin}/settings/autoLinking`
3. Persist `integration.json`. Mark `status="pending"`.
4. Immediate response: `{integration_id, status: "pending", eta_seconds: 600}`.
5. Wizard shows spinner + enables **Check inbox** button after 5 minutes.

### Poll — is inbox ready?

**Endpoint:** `GET /api/session/{sid}/baseline/sap-discovery/status`

**Steps:**

1. `client.list_inbox(status="all", limit=1)` — if count ≥ 1 and any item has a recent `updated_at`, integration has produced data.
2. Response: `{status: "ready" | "pending" | "empty", inbox_count: N, action_needed: X, review_needed: Y}`.

### Phase 2 — process inbox

**Endpoint:** `POST /api/session/{sid}/baseline/sap-discovery/process`

**Steps:**

1. `client.list_inbox(status="action_needed,review_needed")` → list of `DiscoveryItem`. Persist `inbox_snapshot.json`.
2. For each item: `matcher.decide(item, catalog_rba, catalog_rsa)` → `MatchDecision`. Persist `decisions.json`.
3. Execute **HIGH** and **MEDIUM** decisions:
   - `link`: `client.bulk_link([{item_id, target_type, target_id}])` →
     `PUT /services/discovery-linking/v2/{origin}/discoveryItems/link`
   - `create_and_link`: `pipeline.write.create_factsheet(create_payload)` → obtain `target_id` → add to bulk link batch.
   - Bulk emitted in chunks of 50 items.
4. **LOW / review** decisions remain in `execution_log.pending_review`.
5. `report.build(session_id)` → generates `report.html` + `report.json`.
6. Response: `{applied: N, pending_review: M, report_url: "/session/{sid}/sap-discovery/report"}`.

### Phase 3 — human confirmation

- Report HTML renders `pending_review` as cards with dropdowns (link to FS X / reject / create new) and an **Apply selections** button. Same pattern as Step 8 catalog linking review.
- `POST /api/session/{sid}/baseline/sap-discovery/apply-review` receives `{decisions: [{item_id, action, target_id}]}` and executes the same bulk link / reject flow.
- Explicit residual rejects: `PUT /services/discovery-linking/v2/{origin}/discoveryItems/reject`.

## Error handling

| Situation | Handling |
|-----------|----------|
| `create_integration` returns `409 Conflict` (Cloud ALM already active) | Clear error to user with instructions to disable Cloud ALM first. |
| `{origin}` unknown | Discovered at runtime via `GET /discovery-linking/v2/discoveryItems` probing, cached per workspace. Bootstrap tries candidates `sap-extension` → `internal-sap` → `sap-landscape`. |
| `list_inbox` empty after 15 min | Status `empty`. Suggest reviewing CCC hierarchy or retrying. |
| Partial failures in bulk link | Failed ids go to `execution_log.failed` with API error message. Report renders them in red. |
| v2 Beta not enabled in workspace | `client` falls back to `discovery-linking/v1` (`/link`, `/reject`, `/bulk-link`). Detected at runtime (v2 404 → v1). |

## Testing strategy

TDD per module (project standard per `CLAUDE.md`):

- **`client.py`** — `requests-mock` or `responses`. One test per endpoint. Verify auth headers, body shape, 4xx/5xx handling. No network.
- **`matcher.py`** — table-driven pure tests. Fixture `DiscoveryItem` + fixture RBA/RSA catalog → assert `MatchDecision`. Cases: HIGH exact, MEDIUM create_and_link, LOW ambiguous, item already linked (skip), unknown classification.
- **`orchestrator.py`** — `client` and `write` mocked. Covers phase 1 full flow, phase 2 full flow, chunking, partial bulk failures, idempotent `apply-review`.
- **`report.py`** — snapshot tests of HTML + JSON output.
- **Wizard routes** — FastAPI `TestClient` integration tests with orchestrator mocked. Fake session → `/from-sap-discovery` → `/status` → `/process` → `/apply-review`.

## Runtime validations required before v1 release

1. **Correct `{origin}` value** for Internal SAP Landscape Data. Candidates: `sap-extension` | `internal-sap` | `sap-landscape`. Blocking for phase 2.
2. **Real body schema** of `POST /discovery-sap-extension/v1/integrations`. Fetch `GET /services/discovery-sap-extension/v3/api-docs` at wizard boot and validate. Update `client.create_integration` if it differs.
3. **v2 Beta enabled** in target workspace. Fallback to v1 endpoints if not.
4. **Autolinking behavior** — verify that enabling it after integration creation does not re-process already-inboxed items.

**Smoke test:** internal SAP demo workspace with Internal SAP Landscape Data already validated by PM Discovery team. Known CRM ID. Run full flow, compare inbox pre/post.

## Residual risks

- `discovery-sap-extension/v1` is v1; `discovery-linking/v2` is Beta. Both may change. Risk mitigated by isolating REST calls in `client.py` — orchestrator and matcher are stable.
- No `DISCOVERY_ITEM_*` webhook event exists. Polling is the only option in v1.
- Autolinking may over-link in edge cases. Report always shows every applied decision so the user can audit.

## Out of scope for this spec

- Automatic CCC hierarchy fetch (v2).
- Reprocessing inbox updates ("Review needed" status changes over time — v2).
- Multi-tenant orchestration (running multiple integrations for the same session — v2).

## Open questions to resolve during implementation

- Does `PUT /discoveryItems/link` accept a batch payload, or must we loop? (First implementation task: probe the endpoint.)
- Does creating a `create_and_link` fact sheet via `pipeline.write` risk duplicating with LeanIX's own "Create & Link" side effect? Verify by inspecting whether the inbox item retains a linkable target after `create_factsheet`.
