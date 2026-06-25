# Reference Catalog Resolver Auth Fix — Design Spec

**Date:** 2026-06-25
**Status:** Approved
**Branch target:** `feature/catalog-resolver-auth-fix`

## Problem

`pipeline/reference_catalog.py:104` builds the Authorization header by
embedding the raw `LEANIX_API_TOKEN` (`LXT_…`) as a Bearer token:

```python
"Authorization": f"Bearer {self.api_token}",
```

LeanIX REST services do not accept the raw API token. They require an
OAuth2 access token (JWT) obtained via the `client_credentials` flow at
`POST /services/mtm/v1/oauth2/token` using HTTP Basic with
`apitoken:<API_TOKEN>`. Every Reference Catalog call therefore returns
`403 Forbidden` and every name resolves to `CUSTOM`, defeating the
purpose of the resolver.

The bug slipped past the existing 65 unit tests because every test
patches `requests.get/post` at the call site — none exercise the actual
auth header construction against a real or simulated token endpoint.

Verified live against `demo-eu-3.leanix.net`: with the OAuth handshake
done by `curl`, `GET …/reference-data/v1/source/saas/fact-sheets?q=SAP+S/4HANA`
returns HTTP 200 with valid candidates (`lx_APP_019278`). The endpoint
and token are correct; only the header was wrong.

## Existing duplication

The codebase already has two private copies of the OAuth handshake:

- `pipeline/write.py` — `_get_bearer(base_url, api_token)` + module-level
  `_token_cache` dict.
- `pipeline/push_ldif.py` — same function, same cache, separate module.

Both implementations are identical and would be a third time duplicated
if the resolver inlined its own copy.

## Goal

1. Resolver makes Reference Catalog calls with a valid OAuth bearer.
2. Eliminate auth duplication: single shared helper for the entire
   pipeline.
3. Keep the resolver's defensive error handling — bad credentials must
   still degrade gracefully (every name → `CUSTOM`), never crash the
   pipeline.
4. New behavior is covered by tests so the next person who touches the
   auth path can't regress it silently.

## Non-goals

- No changes to the Reference Catalog REST URLs, request bodies, or
  response parsing.
- No changes to the resolver's confidence-tier logic or probe lifecycle.
- No changes to the LDIF push behavior beyond swapping the import.
- No documentation changes to `README.md` (the `LEANIX_API_TOKEN` env
  var already implies OAuth; readers don't need to know that the
  handshake moved into a new module).

## Architecture

Extract OAuth into `pipeline/leanix_auth.py` as the single source of
truth. `write.py`, `push_ldif.py`, and `reference_catalog.py` all import
from it. Module-level cache stays inside `leanix_auth` so all three
callers share one cached token per process.

```
pipeline/leanix_auth.py  ← _token_cache + get_bearer()
        ▲                                       ▲                                       ▲
        │                                       │                                       │
pipeline/write.py          pipeline/push_ldif.py        pipeline/reference_catalog.py
```

## Module contract — `pipeline/leanix_auth.py`

```python
"""Shared LeanIX OAuth2 client_credentials bearer cache."""
from __future__ import annotations
import time
import requests

_token_cache: dict = {"token": None, "expires_at": 0.0}


def get_bearer(base_url: str, api_token: str) -> str:
    """Return a valid Bearer JWT for LeanIX REST calls.

    Caches the token at module level and refreshes when within 60s of
    expiry. Raises requests.HTTPError on token-endpoint failure — callers
    decide what to do (most wrap in try/except and degrade gracefully).
    """
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    resp = requests.post(
        f"{base_url}/services/mtm/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=("apitoken", api_token),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    return _token_cache["token"]
```

Behavior is byte-identical to the two existing private copies — same
endpoint, same Basic auth tuple, same `expires_in` fallback (3600),
same 60s safety margin.

## Caller changes

### `pipeline/reference_catalog.py`

Before:

```python
def _headers(self) -> dict:
    return {
        "Authorization": f"Bearer {self.api_token}",
        "Accept": "application/json",
    }
```

After:

```python
from pipeline.leanix_auth import get_bearer  # module-level import

def _headers(self) -> dict:
    return {
        "Authorization": f"Bearer {get_bearer(self.base_url, self.api_token)}",
        "Accept": "application/json",
    }
```

`_headers` is the only place the resolver assembles auth, so this is
the only edit needed in this file.

### `pipeline/write.py` and `pipeline/push_ldif.py`

In each:

1. Delete the private `_get_bearer` function and its `_token_cache` dict.
2. Add `from pipeline.leanix_auth import get_bearer`.
3. Rename all in-module call sites from `_get_bearer(...)` to
   `get_bearer(...)`.

No behavior changes; pure deduplication.

## Error handling

`get_bearer` raises `requests.HTTPError` (and `RequestException`
subclasses) on token endpoint failures. Existing callers handle this
in two compatible ways:

- **Resolver:** every method that uses `_headers()` (`_search_by_name`,
  `_fetch_detail`, `_batch_links`) already wraps the request in
  `try/except` and returns `[]`/`{}`/`None` on any exception. Bad
  credentials propagate up as exceptions inside the `try` block →
  silently degrade to `CUSTOM`. No new error paths.
- **`write.py` / `push_ldif.py`:** existing callers do not currently
  wrap `_get_bearer`. After the rename, behavior is identical — auth
  failures still surface as exceptions to the top-level caller, which
  is acceptable for a CLI invocation.

## Testing

### New file `tests/test_leanix_auth.py`

Five tests with a fixture that resets `_token_cache` before each test
to prevent bleed:

1. `test_get_bearer_calls_token_endpoint_with_basic_auth` — patches
   `requests.post` to return `{"access_token": "JWT", "expires_in": 3600}`,
   asserts URL is `…/services/mtm/v1/oauth2/token`, `data` is
   `{"grant_type": "client_credentials"}`, `auth=("apitoken", "tok")`,
   return value is `"JWT"`.
2. `test_get_bearer_returns_cached_within_window` — first call
   populates cache; patches `time.time` to a value within `expires_at - 60`
   and verifies `requests.post` is called exactly once across both
   invocations.
3. `test_get_bearer_refreshes_when_near_expiry` — first call populates
   cache with `expires_in=120`; patches `time.time` to a value beyond
   `expires_at - 60`; second call must re-POST.
4. `test_get_bearer_raises_on_http_error` — token endpoint returns
   401; `requests.HTTPError` propagates.
5. `test_get_bearer_handles_missing_expires_in` — response omits
   `expires_in`; cache uses 3600 fallback.

### `tests/test_reference_catalog.py` — one new test

```python
def test_headers_uses_get_bearer():
    """Resolver must call get_bearer() instead of using the raw API token."""
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch("pipeline.reference_catalog.get_bearer",
               return_value="JWT_FAKE") as gb:
        headers = r._headers()
    assert headers["Authorization"] == "Bearer JWT_FAKE"
    gb.assert_called_once_with("https://x", "tok")
```

All 49 existing resolver tests stay untouched: they patch
`requests.get/post` at the call site, bypassing `_headers()` network
behavior, so they continue to pass unchanged. The new test is the
contract test that prevents a future regression to the raw-token
pattern.

### `tests/test_write_with_catalog.py` — no changes

The seven tests in this file mock `ReferenceCatalogResolver` itself or
patch `write_mod._get_bearer`. None reach the new module. After the
refactor, `write.py`'s `_get_bearer` reference is replaced with
`get_bearer` from `leanix_auth`, so the existing
`patch.object(write_mod, "_get_bearer", …)` in
`test_link_apps_skips_rows_with_external_id` needs to be updated to
`patch.object(write_mod, "get_bearer", …)`. That's one line.

## Verification gates

1. **Unit:** `pytest tests/ -q` → 65 (existing) + 5 (auth) + 1
   (resolver header contract) = **71 passing**.
2. **Syntax:** `python3 -m py_compile pipeline/leanix_auth.py
   pipeline/reference_catalog.py pipeline/write.py pipeline/push_ldif.py`
   → clean.
3. **Smoke (manual, post-merge):** rerun the wizard on Acciona with
   `ARCHIMEDES_USE_CATALOG_RESOLVER=true`. Expected log lines:
   `Reference Catalog Application: N names — X LINKED, Y CUSTOM` with
   `X > 0`. Expected file: `output/Acciona/catalog_resolution_report.json`
   with at least one `"status": "LINKED"` entry. Expected Excel:
   `output/Acciona/Acciona_target_leanix.xlsx` sheet `Application`
   column `externalId` populated with `lx_APP_…` for the matched rows.

## Rollback

If the new module breaks something in production:
`git revert <merge-sha>` restores the previous state — the three
callers go back to their private `_get_bearer` copies (still buggy in
the resolver) and the new file is gone. No data migrations, no schema
changes, no caches to invalidate beyond the in-process token cache
which dies with the process.
