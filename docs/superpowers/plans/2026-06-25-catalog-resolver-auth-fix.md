# Catalog Resolver Auth Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the Reference Catalog resolver so it authenticates with a valid OAuth2 bearer JWT instead of the raw LeanIX API token, by extracting the OAuth handshake into a shared `pipeline/leanix_auth.py` module reused by the resolver, `write.py`, and `push_ldif.py`.

**Architecture:** New module `pipeline/leanix_auth.py` owns the `client_credentials` token exchange and an in-process token cache. Three callers (resolver, write, push_ldif) drop their private auth code and import `get_bearer`. Behavior is byte-identical to the existing `_get_bearer` copies in `write.py` and `push_ldif.py` — same endpoint, same Basic auth tuple, same 60s safety margin, same 3600 fallback.

**Tech Stack:** Python 3, `requests` (already in deps), `pytest` + `unittest.mock` (already in deps). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-25-catalog-resolver-auth-fix-design.md`

---

## File Structure

**Create:**
- `pipeline/leanix_auth.py` — single source of truth for OAuth bearer + cache
- `tests/test_leanix_auth.py` — 5 unit tests covering token endpoint call, caching, refresh, error propagation, fallback

**Modify:**
- `pipeline/reference_catalog.py` — `_headers()` uses `get_bearer` instead of raw token (lines 102-106)
- `pipeline/write.py` — delete private `_get_bearer` + `_token_cache` (lines 936-966), import from `leanix_auth`, rename all 7 in-module call sites
- `pipeline/push_ldif.py` — delete private `_get_bearer` + `_token_cache` (lines 52-70), import from `leanix_auth`, rename the 1 in-module call site (line 347)
- `tests/test_reference_catalog.py` — add `test_headers_uses_get_bearer` contract test
- `tests/test_write_with_catalog.py` — rename one `patch.object` target from `_get_bearer` to `get_bearer` (line 177)

---

### Task 1: Create `pipeline/leanix_auth.py` with failing tests

**Files:**
- Create: `pipeline/leanix_auth.py`
- Create: `tests/test_leanix_auth.py`

- [ ] **Step 1: Write the first failing test — token endpoint call shape**

Create `tests/test_leanix_auth.py` with this content:

```python
"""Tests for pipeline.leanix_auth — shared OAuth2 bearer cache."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from pipeline import leanix_auth


@pytest.fixture(autouse=True)
def _reset_token_cache():
    """Reset the module-level token cache before every test."""
    leanix_auth._token_cache["token"] = None
    leanix_auth._token_cache["expires_at"] = 0.0
    yield
    leanix_auth._token_cache["token"] = None
    leanix_auth._token_cache["expires_at"] = 0.0


def test_get_bearer_calls_token_endpoint_with_basic_auth():
    """First call POSTs to /services/mtm/v1/oauth2/token with Basic auth and returns access_token."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "JWT", "expires_in": 3600}
    mock_resp.raise_for_status.return_value = None

    with patch("pipeline.leanix_auth.requests.post", return_value=mock_resp) as post:
        token = leanix_auth.get_bearer("https://x.leanix.net", "tok")

    assert token == "JWT"
    post.assert_called_once()
    args, kwargs = post.call_args
    assert args[0] == "https://x.leanix.net/services/mtm/v1/oauth2/token"
    assert kwargs["data"] == {"grant_type": "client_credentials"}
    assert kwargs["auth"] == ("apitoken", "tok")
    assert kwargs["timeout"] == 30
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_leanix_auth.py::test_get_bearer_calls_token_endpoint_with_basic_auth -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.leanix_auth'`

- [ ] **Step 3: Create the minimal `pipeline/leanix_auth.py`**

Create `pipeline/leanix_auth.py` with this content:

```python
"""Shared LeanIX OAuth2 client_credentials bearer cache.

All LeanIX REST callers (Reference Catalog resolver, write pipeline,
LDIF push) authenticate by exchanging the workspace API token for an
OAuth access token at /services/mtm/v1/oauth2/token. Keeping the
handshake in one place avoids the three-way duplication that existed
previously and prevents auth drift between callers.
"""
from __future__ import annotations

import time

import requests

_token_cache: dict = {"token": None, "expires_at": 0.0}


def get_bearer(base_url: str, api_token: str) -> str:
    """Return a valid Bearer JWT for LeanIX REST calls.

    Caches the token at module level and refreshes when within 60s of
    expiry. Raises requests.HTTPError on token-endpoint failure —
    callers decide what to do (most wrap in try/except and degrade
    gracefully).
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

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_leanix_auth.py::test_get_bearer_calls_token_endpoint_with_basic_auth -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add pipeline/leanix_auth.py tests/test_leanix_auth.py
git commit -m "feat(auth): add shared LeanIX OAuth bearer module with first test"
```

---

### Task 2: Add cache-hit test

**Files:**
- Modify: `tests/test_leanix_auth.py`

- [ ] **Step 1: Append the cache-hit test**

Append this test to `tests/test_leanix_auth.py`:

```python
def test_get_bearer_returns_cached_within_window():
    """Second call within (expires_at - 60s) must NOT re-POST."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "JWT1", "expires_in": 3600}
    mock_resp.raise_for_status.return_value = None

    with patch("pipeline.leanix_auth.requests.post", return_value=mock_resp) as post, \
         patch("pipeline.leanix_auth.time.time", return_value=1000.0):
        # First call populates the cache with expires_at = 1000 + 3600 = 4600
        first = leanix_auth.get_bearer("https://x", "tok")
        # Second call at t=2000 is well within (4600 - 60) — must reuse cache
        with patch("pipeline.leanix_auth.time.time", return_value=2000.0):
            second = leanix_auth.get_bearer("https://x", "tok")

    assert first == "JWT1"
    assert second == "JWT1"
    assert post.call_count == 1
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_leanix_auth.py::test_get_bearer_returns_cached_within_window -v`
Expected: PASS — `get_bearer` already implements caching from Task 1.

- [ ] **Step 3: Commit**

```bash
git add tests/test_leanix_auth.py
git commit -m "test(auth): cover bearer cache hit within validity window"
```

---

### Task 3: Add refresh-on-near-expiry test

**Files:**
- Modify: `tests/test_leanix_auth.py`

- [ ] **Step 1: Append the refresh test**

Append this test to `tests/test_leanix_auth.py`:

```python
def test_get_bearer_refreshes_when_near_expiry():
    """When time() is past (expires_at - 60s), get_bearer must re-POST."""
    first_resp = MagicMock()
    first_resp.json.return_value = {"access_token": "JWT_OLD", "expires_in": 120}
    first_resp.raise_for_status.return_value = None
    second_resp = MagicMock()
    second_resp.json.return_value = {"access_token": "JWT_NEW", "expires_in": 3600}
    second_resp.raise_for_status.return_value = None

    with patch("pipeline.leanix_auth.requests.post",
               side_effect=[first_resp, second_resp]) as post:
        # First call at t=1000 → expires_at = 1120, refresh window starts at 1060
        with patch("pipeline.leanix_auth.time.time", return_value=1000.0):
            first = leanix_auth.get_bearer("https://x", "tok")
        # Second call at t=1100 → inside the 60s safety margin, MUST refresh
        with patch("pipeline.leanix_auth.time.time", return_value=1100.0):
            second = leanix_auth.get_bearer("https://x", "tok")

    assert first == "JWT_OLD"
    assert second == "JWT_NEW"
    assert post.call_count == 2
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_leanix_auth.py::test_get_bearer_refreshes_when_near_expiry -v`
Expected: PASS — `get_bearer` already implements the 60s refresh window.

- [ ] **Step 3: Commit**

```bash
git add tests/test_leanix_auth.py
git commit -m "test(auth): cover bearer refresh inside the 60s safety margin"
```

---

### Task 4: Add HTTPError propagation test

**Files:**
- Modify: `tests/test_leanix_auth.py`

- [ ] **Step 1: Append the error-propagation test**

Append this test to `tests/test_leanix_auth.py`:

```python
def test_get_bearer_raises_on_http_error():
    """raise_for_status() failures propagate; callers wrap in try/except."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = requests.HTTPError("401")

    with patch("pipeline.leanix_auth.requests.post", return_value=mock_resp):
        with pytest.raises(requests.HTTPError):
            leanix_auth.get_bearer("https://x", "bad")

    # Cache must remain empty after a failed handshake
    assert leanix_auth._token_cache["token"] is None
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_leanix_auth.py::test_get_bearer_raises_on_http_error -v`
Expected: PASS — `raise_for_status()` runs before `_token_cache` is populated.

- [ ] **Step 3: Commit**

```bash
git add tests/test_leanix_auth.py
git commit -m "test(auth): cover HTTPError propagation on token endpoint failure"
```

---

### Task 5: Add `expires_in` fallback test

**Files:**
- Modify: `tests/test_leanix_auth.py`

- [ ] **Step 1: Append the fallback test**

Append this test to `tests/test_leanix_auth.py`:

```python
def test_get_bearer_handles_missing_expires_in():
    """When the response omits expires_in, the cache uses the 3600s fallback."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "JWT"}  # no expires_in
    mock_resp.raise_for_status.return_value = None

    with patch("pipeline.leanix_auth.requests.post", return_value=mock_resp), \
         patch("pipeline.leanix_auth.time.time", return_value=1000.0):
        token = leanix_auth.get_bearer("https://x", "tok")

    assert token == "JWT"
    assert leanix_auth._token_cache["expires_at"] == 1000.0 + 3600
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_leanix_auth.py::test_get_bearer_handles_missing_expires_in -v`
Expected: PASS — implementation uses `data.get("expires_in", 3600)`.

- [ ] **Step 3: Run the entire new auth test file to confirm all 5 pass together**

Run: `pytest tests/test_leanix_auth.py -v`
Expected: PASS — 5 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_leanix_auth.py
git commit -m "test(auth): cover 3600s fallback when expires_in is missing"
```

---

### Task 6: Switch `reference_catalog._headers()` to use `get_bearer` (TDD)

**Files:**
- Test: `tests/test_reference_catalog.py`
- Modify: `pipeline/reference_catalog.py:102-106`

- [ ] **Step 1: Write the failing contract test**

Open `tests/test_reference_catalog.py` and find the imports block at the top. Confirm `from unittest.mock import patch` is already imported (it is — the file uses `patch` extensively). Then append this test at the end of the file:

```python
def test_headers_uses_get_bearer():
    """Resolver must call get_bearer() instead of using the raw API token as Bearer."""
    from pipeline.reference_catalog import ReferenceCatalogResolver

    r = ReferenceCatalogResolver("https://x.leanix.net", "tok", interactive=False)
    with patch("pipeline.reference_catalog.get_bearer",
               return_value="JWT_FAKE") as gb:
        headers = r._headers()

    assert headers["Authorization"] == "Bearer JWT_FAKE"
    gb.assert_called_once_with("https://x.leanix.net", "tok")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_reference_catalog.py::test_headers_uses_get_bearer -v`
Expected: FAIL — `AttributeError: module 'pipeline.reference_catalog' has no attribute 'get_bearer'` (because the resolver still uses raw `self.api_token`).

- [ ] **Step 3: Edit `pipeline/reference_catalog.py` to import and use `get_bearer`**

In `pipeline/reference_catalog.py`, find line 16 (`import requests`) and add the new import on the line after it:

Before (lines 16-17):
```python
import requests

```

After:
```python
import requests

from pipeline.leanix_auth import get_bearer

```

Then replace lines 102-106:

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
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {get_bearer(self.base_url, self.api_token)}",
            "Accept": "application/json",
        }
```

- [ ] **Step 4: Run the contract test to verify it now passes**

Run: `pytest tests/test_reference_catalog.py::test_headers_uses_get_bearer -v`
Expected: PASS.

- [ ] **Step 5: Run the full resolver test suite to confirm no regressions**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS — all existing resolver tests still pass (they patch `requests.get/post` at the call site, bypassing `_headers()` network behavior).

- [ ] **Step 6: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "fix(catalog): authenticate Reference Catalog calls with OAuth bearer

Previously the resolver embedded the raw LXT_... API token as Bearer,
which every LeanIX REST endpoint rejects with 403. Switch to the
shared get_bearer() helper that performs the client_credentials
exchange and caches the resulting JWT.

Adds a contract test that locks in the get_bearer call site so a
future regression to the raw-token pattern is caught immediately."
```

---

### Task 7: Migrate `pipeline/push_ldif.py` to shared `get_bearer`

**Files:**
- Modify: `pipeline/push_ldif.py:52-70` (delete), `pipeline/push_ldif.py:347` (rename call site)

- [ ] **Step 1: Read the current file to confirm line numbers**

Run: `pytest tests/ -q -k "push_ldif or push" 2>&1 | tail -20`
Expected: Note the current passing tests touching push_ldif (for sanity check after the edit).

- [ ] **Step 2: Delete the private `_get_bearer` and `_token_cache` block**

In `pipeline/push_ldif.py`, delete lines 52-70 inclusive. The lines to remove are:

```python
_token_cache: dict = {"token": None, "expires_at": 0.0}


def _get_bearer(base_url: str, api_token: str) -> str:
    """Return a Bearer JWT for LeanIX REST calls; cached until near expiry."""
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

(If your editor's line numbers drift due to surrounding context, identify the block by its `_token_cache: dict = …` opening line and the closing `return _token_cache["token"]` plus the trailing blank line. Delete that entire block.)

- [ ] **Step 3: Add the import at the top of the file**

Find the imports section of `pipeline/push_ldif.py` (the block of `import …` and `from … import …` lines after the module docstring). Add this line in alphabetical order with the other `from pipeline …` imports if any, otherwise at the end of the import block:

```python
from pipeline.leanix_auth import get_bearer
```

- [ ] **Step 4: Rename the in-module call site**

Search the file for `_get_bearer(` (one remaining call site, previously at line 347). Replace each occurrence with `get_bearer(`. There is exactly one call:

Before:
```python
    bearer  = _get_bearer(_base_url, _api_token)
```

After:
```python
    bearer  = get_bearer(_base_url, _api_token)
```

- [ ] **Step 5: Verify no stale references remain**

Run: `grep -n "_get_bearer\|_token_cache" pipeline/push_ldif.py || echo OK`
Expected: `OK` (no matches).

- [ ] **Step 6: Verify the file still compiles**

Run: `python3 -m py_compile pipeline/push_ldif.py`
Expected: no output (clean).

- [ ] **Step 7: Run the full test suite to confirm nothing broke**

Run: `pytest tests/ -q`
Expected: All tests pass — the rename is internal to `push_ldif.py` and no test patches `push_ldif._get_bearer`.

- [ ] **Step 8: Commit**

```bash
git add pipeline/push_ldif.py
git commit -m "refactor(push_ldif): use shared leanix_auth.get_bearer

Drops the private _get_bearer + _token_cache copy in favor of the
shared module. Behavior unchanged — same endpoint, same Basic auth,
same 60s margin, same 3600 fallback."
```

---

### Task 8: Migrate `pipeline/write.py` to shared `get_bearer`

**Files:**
- Modify: `pipeline/write.py:936-966` (delete), 7 in-module call sites (rename)
- Modify: `tests/test_write_with_catalog.py:177` (rename patch target)

- [ ] **Step 1: Update the test that patches `_get_bearer` BEFORE the rename**

In `tests/test_write_with_catalog.py`, find line 177:

Before:
```python
    with patch.object(write_mod, "_get_bearer", return_value="fake-token"), \
```

After:
```python
    with patch.object(write_mod, "get_bearer", return_value="fake-token"), \
```

This is the only test that mocks the bearer helper in `write_mod`.

- [ ] **Step 2: Run the updated test BEFORE editing `write.py` to confirm it fails (proves the rename is load-bearing)**

Run: `pytest tests/test_write_with_catalog.py::test_link_apps_skips_rows_with_external_id -v`
Expected: FAIL — `AttributeError: <module 'pipeline.write'> does not have the attribute 'get_bearer'` (the module still exposes `_get_bearer`).

- [ ] **Step 3: Delete the private `_get_bearer` and `_token_cache` block in `pipeline/write.py`**

In `pipeline/write.py`, delete lines 936-966 inclusive. The block to remove is:

```python
_token_cache: dict = {"token": None, "expires_at": 0.0}


def _get_bearer(base_url: str, api_token: str) -> str:
    """Return a valid Bearer JWT for LeanIX REST calls.

    Caches the token at module level and refreshes when within 60s of
    expiry. Re-raises requests exceptions so callers can degrade
    gracefully (most wrap calls in try/except).
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

Identify the block by its `_token_cache: dict = …` opening line and the closing `return _token_cache["token"]`. Delete that entire block including any docstring inside.

- [ ] **Step 4: Add the import at the top of `pipeline/write.py`**

Find the existing line:

```python
from pipeline.reference_catalog import ReferenceCatalogResolver, ResolvedMatch
```

Add immediately after it:

```python
from pipeline.leanix_auth import get_bearer
```

- [ ] **Step 5: Rename all in-module call sites from `_get_bearer` to `get_bearer`**

Run a global replace across `pipeline/write.py` ONLY (not other files). The 7 call sites are at lines 982, 1014, 1058, 1104, 1737, 1796, 1930, 2096 (and the comment at 1098). Replace every occurrence of `_get_bearer` (with the leading underscore) with `get_bearer` (without the underscore).

Concretely, the replacements are:

```
_get_bearer(base_url, api_token)   →   get_bearer(base_url, api_token)
_get_bearer(base_url, token)       →   get_bearer(base_url, token)
```

And the comment:

```
# ── Authenticate (token auto-refreshes via _get_bearer) ───────────────────
```

becomes:

```
# ── Authenticate (token auto-refreshes via get_bearer) ────────────────────
```

- [ ] **Step 6: Verify no stale references remain**

Run: `grep -n "_get_bearer\|_token_cache" pipeline/write.py || echo OK`
Expected: `OK` (no matches).

- [ ] **Step 7: Verify the file still compiles**

Run: `python3 -m py_compile pipeline/write.py`
Expected: no output (clean).

- [ ] **Step 8: Re-run the patched test — it should now pass**

Run: `pytest tests/test_write_with_catalog.py::test_link_apps_skips_rows_with_external_id -v`
Expected: PASS — `write_mod.get_bearer` now exists (imported from `leanix_auth`) and is patchable.

- [ ] **Step 9: Run the entire test suite**

Run: `pytest tests/ -q`
Expected: All tests pass — target 71 passing (65 existing + 5 new auth + 1 new resolver contract).

- [ ] **Step 10: Commit**

```bash
git add pipeline/write.py tests/test_write_with_catalog.py
git commit -m "refactor(write): use shared leanix_auth.get_bearer

Drops the private _get_bearer + _token_cache copy in favor of the
shared module. Renames all 7 in-module call sites and updates the
single test that patches the helper. Behavior unchanged."
```

---

### Task 9: Verification gates

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite, full output**

Run: `pytest tests/ -v`
Expected: 71 passed (65 existing + 5 leanix_auth + 1 reference_catalog contract). Zero failures, zero errors.

- [ ] **Step 2: Compile-check all four touched modules**

Run: `python3 -m py_compile pipeline/leanix_auth.py pipeline/reference_catalog.py pipeline/write.py pipeline/push_ldif.py`
Expected: no output (clean).

- [ ] **Step 3: Confirm no duplicate auth code remains in the pipeline**

Run: `grep -rn "_get_bearer\|_token_cache" pipeline/ tests/ || echo OK`
Expected: `OK` (no matches). The shared module uses `get_bearer` (no leading underscore) and `_token_cache` is now ONLY in `pipeline/leanix_auth.py`.

If the grep returns matches inside `pipeline/leanix_auth.py` only (because the cache variable is named `_token_cache` there), that is fine — it's the single source of truth now. Check the matches explicitly:

Run: `grep -rn "_token_cache" pipeline/`
Expected: matches ONLY in `pipeline/leanix_auth.py`.

- [ ] **Step 4: Manual smoke test on Acciona**

This is a manual gate, not a test. Confirm the wizard is still configured for the resolver:

Run: `grep ARCHIMEDES_USE_CATALOG_RESOLVER /Users/I519409/dev/archimedes-ai/.env`
Expected: `ARCHIMEDES_USE_CATALOG_RESOLVER=true`

Restart the wizard process so it picks up the new code:

Run: `pkill -f archimedes_wizard.py; sleep 1; (cd /Users/I519409/dev/archimedes-ai && nohup python3 archimedes_wizard.py > /tmp/archimedes_wizard.log 2>&1 &)`
Expected: process restarts. Confirm with `pgrep -af archimedes_wizard.py`.

In the browser at http://127.0.0.1:8767, run the wizard end-to-end for Acciona again. Then inspect the log:

Run: `grep -E "Reference Catalog Application|LINKED|CUSTOM" /tmp/archimedes_wizard.log`
Expected: a line such as `Reference Catalog Application: N names — X LINKED, Y CUSTOM` with `X > 0`. If X is still 0, the OAuth handshake is not happening — re-check Task 6 Step 3 edits.

Also confirm the artifact:

Run: `ls -la /Users/I519409/dev/archimedes-ai/output/Acciona/catalog_resolution_report.json && jq '[.[] | select(.status == "LINKED")] | length' /Users/I519409/dev/archimedes-ai/output/Acciona/catalog_resolution_report.json`
Expected: file exists, integer > 0.

- [ ] **Step 5: Commit the manual-gate evidence (none — verification only)**

No commit. If the manual smoke test reveals a regression, file it as a follow-up — do NOT amend earlier task commits.

---

## Rollback

If the merged change breaks production:

```bash
git revert <merge-sha>
```

This restores the previous state: the three callers go back to their private `_get_bearer` copies (still buggy in the resolver), and `pipeline/leanix_auth.py` and `tests/test_leanix_auth.py` are removed. No data migrations, no schema changes, no caches to invalidate beyond the in-process token cache which dies with the process.
