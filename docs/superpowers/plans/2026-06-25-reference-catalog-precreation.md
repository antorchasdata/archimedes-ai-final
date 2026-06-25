# Reference Catalog Pre-Creation Resolver — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every Application/ITComponent name against the LeanIX Reference Catalog before writing the staging Excel, so fact sheets are created already linked to the catalog (`saas`/`ltls` sources) when a match exists, with graceful fallback to custom fact sheets when not.

**Architecture:** New self-contained module `pipeline/reference_catalog.py` exposes `ReferenceCatalogResolver` with a single public `resolve()` entry point. It uses the GET `/fact-sheets?q=` endpoint first (free, no probe FS created), and only falls back to the Probe Pattern (create temp FS → POST `/batch-links` → archive) for ambiguous names. Integration point is `pipeline/write.py:write_leanix_excel` — after dedup, before workbook save. Push reads `externalId` from rows so LeanIX auto-links at `createFactSheet` time. Existing `_link_apps_to_catalog` keeps running as a safety net for rows without `externalId`. Feature-flagged via `ARCHIMEDES_USE_CATALOG_RESOLVER`.

**Tech Stack:** Python 3.10+, `requests` (HTTP), `unittest.mock` + `responses` (tests), pytest. Reuses existing `_get_bearer` helper from `pipeline/write.py`. No new runtime dependencies.

---

## File Structure

| File | Responsibility |
|---|---|
| `pipeline/reference_catalog.py` (NEW) | `ResolvedMatch` dataclass, `ReferenceCatalogResolver` class. All catalog API interaction, normalization, caching, probe lifecycle. Pure module — no Excel/write logic. |
| `pipeline/write.py` (MODIFY at line ~367 in `write_leanix_excel`) | Instantiate resolver after dedup, resolve App + ITC names, decorate rows with `externalId` / catalog fields, call `cleanup()` in finally. Also: gate behind `ARCHIMEDES_USE_CATALOG_RESOLVER` env var; teach `_link_apps_to_catalog` to skip rows that already carry `externalId`. |
| `pipeline/push_ldif.py` (MODIFY) | When building `createFactSheet` payload, include `externalId` field if present in row. |
| `tests/test_reference_catalog.py` (NEW) | Unit tests for resolver — 16 cases covering happy path + every fail-safe branch. |
| `tests/test_write_with_catalog.py` (NEW) | Integration tests verifying `write_leanix_excel` correctly consumes `ResolvedMatch` and produces an Excel with `externalId` columns. |

---

## Task 1: Scaffold `ResolvedMatch` dataclass and resolver skeleton

**Files:**
- Create: `pipeline/reference_catalog.py`
- Test:   `tests/test_reference_catalog.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_reference_catalog.py`:

```python
"""Unit tests for pipeline.reference_catalog."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.reference_catalog import ResolvedMatch, ReferenceCatalogResolver


def test_resolved_match_defaults():
    m = ResolvedMatch(name="SAP S/4HANA")
    assert m.name == "SAP S/4HANA"
    assert m.external_id is None
    assert m.catalog_uuid is None
    assert m.display_name is None
    assert m.confidence == "NONE"
    assert m.status == "CUSTOM"
    assert m.fields == {}


def test_resolver_construct():
    r = ReferenceCatalogResolver(base_url="https://example.com", api_token="tok")
    assert r.base_url == "https://example.com"
    assert r.api_token == "tok"
    assert r.interactive is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.reference_catalog'`

- [ ] **Step 3: Write minimal implementation**

Create `pipeline/reference_catalog.py`:

```python
"""Resolves Application/ITComponent names against the LeanIX Reference Catalog
before fact sheets are created, so the staging Excel carries catalog
externalIds and rows are created already linked to the catalog.

Public API:
    ReferenceCatalogResolver(base_url, api_token, interactive=True).resolve(...)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ResolvedMatch:
    """Result of resolving a single name against the catalog."""
    name: str
    external_id: str | None = None
    catalog_uuid: str | None = None
    display_name: str | None = None
    confidence: str = "NONE"   # VERYHIGH | HIGH | MEDIUM | LOW | NONE
    status: str = "CUSTOM"     # LINKED | CUSTOM
    fields: dict[str, Any] = field(default_factory=dict)


class ReferenceCatalogResolver:
    """Pre-creation Reference Catalog resolver."""

    def __init__(
        self,
        base_url: str,
        api_token: str,
        interactive: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.interactive = interactive
        self._cache: dict[tuple[str, str], ResolvedMatch] = {}
        self._probe_ids: dict[str, str] = {}    # fs_type -> probe FS UUID
        self._no_probe_mode = False
        self._skip_all_prompts = False

    def resolve(self, fs_type: str, names: list[str]) -> dict[str, ResolvedMatch]:
        """Resolve a list of names. Returns dict keyed by original name."""
        raise NotImplementedError

    def cleanup(self) -> None:
        """Archive probe fact sheets. Always safe to call (idempotent)."""
        return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "feat(catalog): scaffold ResolvedMatch and ReferenceCatalogResolver"
```

---

## Task 2: Name normalization helper

Catalog cache and exact-match comparison both require the same normalization rule.

**Files:**
- Modify: `pipeline/reference_catalog.py`
- Test:   `tests/test_reference_catalog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reference_catalog.py`:

```python
from pipeline.reference_catalog import _normalize_name


def test_normalize_lowercases_and_collapses_whitespace():
    assert _normalize_name("SAP S/4HANA") == "sap s/4hana"
    assert _normalize_name("  SAP   S/4HANA  ") == "sap s/4hana"
    assert _normalize_name("SAP\tS/4HANA\n") == "sap s/4hana"


def test_normalize_idempotent():
    once = _normalize_name("SAP S/4HANA")
    twice = _normalize_name(once)
    assert once == twice
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_catalog.py::test_normalize_lowercases_and_collapses_whitespace -v`
Expected: FAIL with `ImportError: cannot import name '_normalize_name'`

- [ ] **Step 3: Write minimal implementation**

Add to `pipeline/reference_catalog.py` (after imports, before dataclass):

```python
import re

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_name(name: str) -> str:
    """Lower-case + collapse whitespace. Used for cache keys and exact-match."""
    return _WHITESPACE_RE.sub(" ", name.strip().lower())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "feat(catalog): add _normalize_name helper"
```

---

## Task 3: Source mapping for fs_type → saas/ltls

**Files:**
- Modify: `pipeline/reference_catalog.py`
- Test:   `tests/test_reference_catalog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reference_catalog.py`:

```python
from pipeline.reference_catalog import _source_for_type, _external_id_prefix
import pytest


def test_source_for_type_application():
    assert _source_for_type("Application") == "saas"


def test_source_for_type_itcomponent():
    assert _source_for_type("ITComponent") == "ltls"


def test_source_for_type_invalid():
    with pytest.raises(ValueError):
        _source_for_type("BusinessCapability")


def test_external_id_prefix():
    assert _external_id_prefix("Application") == "lx_APP_"
    assert _external_id_prefix("ITComponent") == "lx_ITC_"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Add to `pipeline/reference_catalog.py`:

```python
_SOURCE_BY_TYPE = {"Application": "saas", "ITComponent": "ltls"}
_PREFIX_BY_TYPE = {"Application": "lx_APP_", "ITComponent": "lx_ITC_"}


def _source_for_type(fs_type: str) -> str:
    try:
        return _SOURCE_BY_TYPE[fs_type]
    except KeyError as exc:
        raise ValueError(
            f"Reference Catalog only supports Application and ITComponent, got {fs_type!r}"
        ) from exc


def _external_id_prefix(fs_type: str) -> str:
    return _PREFIX_BY_TYPE[fs_type]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "feat(catalog): source mapping helpers"
```

---

## Task 4: HTTP search by name (GET `?q=`)

**Files:**
- Modify: `pipeline/reference_catalog.py`
- Test:   `tests/test_reference_catalog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reference_catalog.py`:

```python
from unittest.mock import patch, MagicMock


def _mk_response(json_body, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return r


def test_search_by_name_returns_candidates():
    r = ReferenceCatalogResolver("https://x", "tok")
    payload = [
        {
            "alreadyLinked": False,
            "factSheet": {
                "id": "uuid-1",
                "externalId": "lx_APP_000123",
                "displayName": "SAP S/4HANA",
                "type": "Application",
            },
        }
    ]
    with patch("pipeline.reference_catalog.requests.get",
               return_value=_mk_response(payload)) as get:
        candidates = r._search_by_name("Application", "SAP S/4HANA")
    assert len(candidates) == 1
    assert candidates[0]["factSheet"]["externalId"] == "lx_APP_000123"
    called_url = get.call_args[0][0]
    assert "/services/reference-data/v1/source/saas/fact-sheets" in called_url


def test_search_by_name_http_error_returns_empty():
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch("pipeline.reference_catalog.requests.get",
               return_value=_mk_response({}, status=500)):
        candidates = r._search_by_name("Application", "Anything")
    assert candidates == []


def test_search_by_name_short_query_skipped():
    """API requires min 2 chars — a 1-char name must be skipped, not sent."""
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch("pipeline.reference_catalog.requests.get") as get:
        candidates = r._search_by_name("Application", "X")
    assert candidates == []
    get.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: FAIL with `AttributeError: ... has no attribute '_search_by_name'`

- [ ] **Step 3: Write minimal implementation**

Add `import requests` at top of `pipeline/reference_catalog.py`, then add to the class:

```python
    # ── HTTP layer ─────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

    def _search_by_name(self, fs_type: str, name: str) -> list[dict]:
        """GET /fact-sheets?q=<name>. Returns list (possibly empty) on success
        or [] on any error. Never raises."""
        if len(name.strip()) < 2:
            return []
        source = _source_for_type(fs_type)
        url = (
            f"{self.base_url}/services/reference-data/v1/source/{source}/fact-sheets"
        )
        params = {"q": name, "factSheetType": fs_type, "fuzzy": "false"}
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("Catalog search failed for %r (%s)", name, exc)
            return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "feat(catalog): GET /fact-sheets?q= search with safe error handling"
```

---

## Task 5: Fetch full catalog entry detail (GET `/fact-sheets/<id>`)

**Files:**
- Modify: `pipeline/reference_catalog.py`
- Test:   `tests/test_reference_catalog.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_fetch_detail_returns_fields():
    r = ReferenceCatalogResolver("https://x", "tok")
    payload = {
        "id": "uuid-1",
        "externalId": "lx_APP_000123",
        "displayName": "SAP S/4HANA",
        "description": "ERP",
        "fields": [
            {"name": "lxHostingType", "value": "saas"},
            {"name": "productCategory", "value": "ERP"},
        ],
        "relations": [
            {"name": "relApplicationToProvider",
             "targetFactSheet": {"displayName": "SAP"}},
        ],
    }
    with patch("pipeline.reference_catalog.requests.get",
               return_value=_mk_response(payload)):
        detail = r._fetch_detail("Application", "lx_APP_000123")
    assert detail["description"] == "ERP"
    assert detail["fields"]["lxHostingType"] == "saas"
    assert detail["fields"]["productCategory"] == "ERP"
    assert detail["fields"]["provider"] == "SAP"


def test_fetch_detail_http_error_returns_empty():
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch("pipeline.reference_catalog.requests.get",
               return_value=_mk_response({}, status=500)):
        detail = r._fetch_detail("Application", "lx_APP_000123")
    assert detail == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Write minimal implementation**

Add to the class:

```python
    _FIELDS_TO_COPY = ("description", "lxHostingType", "productCategory")

    def _fetch_detail(self, fs_type: str, external_id: str) -> dict[str, Any]:
        """GET /fact-sheets/<id>. Returns flattened dict:
            { 'description': ..., 'fields': {'lxHostingType': ..., 'productCategory': ..., 'provider': ...} }
        Returns {} on any error. Never raises."""
        source = _source_for_type(fs_type)
        url = (
            f"{self.base_url}/services/reference-data/v1/source/{source}/fact-sheets/"
            f"{external_id}"
        )
        try:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.warning("Catalog detail fetch failed for %s (%s)", external_id, exc)
            return {}

        fields_dict: dict[str, Any] = {}
        for entry in body.get("fields", []) or []:
            n = entry.get("name")
            if n in self._FIELDS_TO_COPY:
                fields_dict[n] = entry.get("value")

        # Provider lives in relations
        for rel in body.get("relations", []) or []:
            if rel.get("name") in ("relApplicationToProvider", "relITComponentToProvider"):
                target = rel.get("targetFactSheet") or {}
                fields_dict["provider"] = target.get("displayName")
                break

        return {
            "description": body.get("description"),
            "fields": fields_dict,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "feat(catalog): GET single catalog entry detail with field extraction"
```

---

## Task 6: GraphQL probe FS create/rename/archive

**Files:**
- Modify: `pipeline/reference_catalog.py`
- Test:   `tests/test_reference_catalog.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_probe_create_returns_uuid():
    r = ReferenceCatalogResolver("https://x", "tok")
    gql_resp = {"data": {"createFactSheet": {"factSheet": {"id": "probe-uuid-1"}}}}
    with patch("pipeline.reference_catalog.requests.post",
               return_value=_mk_response(gql_resp)) as post:
        fs_id = r._probe_create("Application", "Probe Name")
    assert fs_id == "probe-uuid-1"
    body = post.call_args.kwargs["json"]
    assert "createFactSheet" in body["query"]


def test_probe_create_failure_returns_none():
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch("pipeline.reference_catalog.requests.post",
               return_value=_mk_response({"errors": [{"message": "boom"}]})):
        assert r._probe_create("Application", "X") is None


def test_probe_rename_returns_true():
    r = ReferenceCatalogResolver("https://x", "tok")
    gql_resp = {"data": {"updateFactSheet": {"factSheet": {"id": "probe-uuid-1"}}}}
    with patch("pipeline.reference_catalog.requests.post",
               return_value=_mk_response(gql_resp)):
        assert r._probe_rename("probe-uuid-1", "New Name") is True


def test_probe_archive_returns_true():
    r = ReferenceCatalogResolver("https://x", "tok")
    gql_resp = {"data": {"updateFactSheet": {"factSheet": {"id": "probe-uuid-1"}}}}
    with patch("pipeline.reference_catalog.requests.post",
               return_value=_mk_response(gql_resp)):
        assert r._probe_archive("probe-uuid-1") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Write minimal implementation**

Add to the class:

```python
    # ── GraphQL probe lifecycle ────────────────────────────────────────────

    def _gql(self, query: str, variables: dict | None = None) -> dict | None:
        """POST to pathfinder GraphQL. Returns data dict on success, None on error."""
        url = f"{self.base_url}/services/pathfinder/v1/graphql"
        body = {"query": query, "variables": variables or {}}
        try:
            resp = requests.post(url, headers=self._headers(), json=body, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("errors"):
                logger.warning("GraphQL errors: %s", payload["errors"])
                return None
            return payload.get("data")
        except Exception as exc:
            logger.warning("GraphQL call failed: %s", exc)
            return None

    def _probe_create(self, fs_type: str, name: str) -> str | None:
        query = (
            "mutation($name:String!,$type:FactSheetType!){"
            "createFactSheet(input:{name:$name,type:$type}){factSheet{id}}}"
        )
        data = self._gql(query, {"name": name, "type": fs_type})
        if not data:
            return None
        return ((data.get("createFactSheet") or {}).get("factSheet") or {}).get("id")

    def _probe_rename(self, fs_id: str, new_name: str) -> bool:
        query = (
            "mutation($id:ID!,$patches:[Patch]!){"
            "updateFactSheet(id:$id,patches:$patches,comment:\"probe rename\"){"
            "factSheet{id}}}"
        )
        variables = {
            "id": fs_id,
            "patches": [{"op": "replace", "path": "/name", "value": new_name}],
        }
        data = self._gql(query, variables)
        return bool(data and data.get("updateFactSheet"))

    def _probe_archive(self, fs_id: str) -> bool:
        query = (
            "mutation($id:ID!,$patches:[Patch]!){"
            "updateFactSheet(id:$id,patches:$patches,comment:\"probe cleanup\"){"
            "factSheet{id}}}"
        )
        variables = {
            "id": fs_id,
            "patches": [{"op": "replace", "path": "/status", "value": "ARCHIVED"}],
        }
        data = self._gql(query, variables)
        return bool(data and data.get("updateFactSheet"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "feat(catalog): GraphQL probe FS create/rename/archive helpers"
```

---

## Task 7: `batch-links` confidence probe

**Files:**
- Modify: `pipeline/reference_catalog.py`
- Test:   `tests/test_reference_catalog.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_batch_links_returns_top_suggestion():
    r = ReferenceCatalogResolver("https://x", "tok")
    payload = {
        "data": {
            "probe-uuid-1": {
                "suggestions": [
                    {
                        "alreadyLinked": False,
                        "factSheet": {
                            "id": "cat-uuid-1",
                            "displayName": "SAP S/4HANA Cloud",
                            "externalId": "lx_APP_000999",
                            "confidenceLevel": "HIGH",
                        },
                    }
                ]
            }
        }
    }
    with patch("pipeline.reference_catalog.requests.post",
               return_value=_mk_response(payload)):
        top = r._batch_links("Application", "probe-uuid-1", "SAP S/4HANA")
    assert top is not None
    assert top["confidenceLevel"] == "HIGH"
    assert top["externalId"] == "lx_APP_000999"


def test_batch_links_no_suggestions_returns_none():
    r = ReferenceCatalogResolver("https://x", "tok")
    payload = {"data": {"probe-uuid-1": {"suggestions": []}}}
    with patch("pipeline.reference_catalog.requests.post",
               return_value=_mk_response(payload)):
        assert r._batch_links("Application", "probe-uuid-1", "X") is None


def test_batch_links_error_returns_none():
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch("pipeline.reference_catalog.requests.post",
               return_value=_mk_response({}, status=500)):
        assert r._batch_links("Application", "probe-uuid-1", "X") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Write minimal implementation**

Add to the class:

```python
    def _batch_links(
        self, fs_type: str, probe_id: str, name: str
    ) -> dict | None:
        """POST /batch-links. Returns the top suggestion's factSheet dict
        (with confidenceLevel) or None on no match / any error."""
        source = _source_for_type(fs_type)
        url = (
            f"{self.base_url}/services/reference-data/v1/source/{source}/batch-links"
        )
        body = {
            "factSheets": [
                {"id": probe_id, "name": name, "catalogStatus": "n/a"}
            ],
            "numMatches": 3,
        }
        try:
            resp = requests.post(url, headers=self._headers(), json=body, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.warning("batch-links failed for %r (%s)", name, exc)
            return None

        entry = (payload.get("data") or {}).get(probe_id) or {}
        suggestions = entry.get("suggestions") or []
        if not suggestions:
            return None
        return suggestions[0].get("factSheet")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS (20 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "feat(catalog): batch-links probe call"
```

---

## Task 8: Interactive HIGH/MEDIUM prompt with skip-all

**Files:**
- Modify: `pipeline/reference_catalog.py`
- Test:   `tests/test_reference_catalog.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
import io


def test_prompt_yes_returns_true(monkeypatch):
    r = ReferenceCatalogResolver("https://x", "tok", interactive=True)
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    assert r._prompt_link("SAP S4", "SAP S/4HANA Cloud", "HIGH") is True


def test_prompt_no_returns_false(monkeypatch):
    r = ReferenceCatalogResolver("https://x", "tok", interactive=True)
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    assert r._prompt_link("X", "Y", "HIGH") is False


def test_prompt_skip_all_sets_flag_and_returns_false(monkeypatch):
    r = ReferenceCatalogResolver("https://x", "tok", interactive=True)
    monkeypatch.setattr("sys.stdin", io.StringIO("s\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    assert r._prompt_link("X", "Y", "HIGH") is False
    assert r._skip_all_prompts is True
    # subsequent call should not prompt at all
    assert r._prompt_link("A", "B", "MEDIUM") is False


def test_prompt_non_interactive_returns_false():
    r = ReferenceCatalogResolver("https://x", "tok", interactive=False)
    assert r._prompt_link("X", "Y", "HIGH") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Add `import sys` at top, then to the class:

```python
    def _prompt_link(self, name: str, catalog_display: str, confidence: str) -> bool:
        """Interactive Y/n/s prompt for HIGH/MEDIUM matches.
        Returns True to link, False to skip. Sets _skip_all_prompts on 's'."""
        if not self.interactive or self._skip_all_prompts:
            return False
        if not getattr(sys.stdin, "isatty", lambda: False)():
            return False
        prompt = (
            f"  Link '{name}' to catalog entry '{catalog_display}' "
            f"(confidence={confidence})? [Y/n/s(kip all)]: "
        )
        try:
            answer = input(prompt).strip().lower()
        except EOFError:
            return False
        if answer in ("", "y", "yes", "s\u00ed", "si"):
            return True
        if answer in ("s", "skip"):
            self._skip_all_prompts = True
            return False
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS (24 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "feat(catalog): interactive HIGH/MEDIUM confirmation prompt"
```

---

## Task 9: `resolve_one` — single-name end-to-end (no probe path)

The simpler path: only Step 1 (search) + Step 2 (exact-match heuristic). Probe path follows in Task 10.

**Files:**
- Modify: `pipeline/reference_catalog.py`
- Test:   `tests/test_reference_catalog.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_exact_match_skips_probe():
    """Single candidate with displayName matching name → VERYHIGH, no batch-links."""
    r = ReferenceCatalogResolver("https://x", "tok")
    search_payload = [
        {
            "alreadyLinked": False,
            "factSheet": {
                "id": "uuid-1",
                "externalId": "lx_APP_000123",
                "displayName": "SAP S/4HANA",
                "type": "Application",
            },
        }
    ]
    detail_payload = {
        "id": "uuid-1",
        "externalId": "lx_APP_000123",
        "displayName": "SAP S/4HANA",
        "description": "ERP suite",
        "fields": [{"name": "lxHostingType", "value": "saas"}],
        "relations": [],
    }
    with patch("pipeline.reference_catalog.requests.get",
               side_effect=[_mk_response(search_payload),
                            _mk_response(detail_payload)]), \
         patch("pipeline.reference_catalog.requests.post") as post:
        m = r._resolve_one("Application", "SAP S/4HANA")
    assert m.status == "LINKED"
    assert m.confidence == "VERYHIGH"
    assert m.external_id == "lx_APP_000123"
    assert m.display_name == "SAP S/4HANA"
    assert m.fields["lxHostingType"] == "saas"
    post.assert_not_called()  # no probe


def test_zero_candidates_custom():
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch("pipeline.reference_catalog.requests.get",
               return_value=_mk_response([])):
        m = r._resolve_one("Application", "Unknown App")
    assert m.status == "CUSTOM"
    assert m.confidence == "NONE"
    assert m.external_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Write minimal implementation**

Add to the class:

```python
    # ── Resolution algorithm ───────────────────────────────────────────────

    def _resolve_one(self, fs_type: str, name: str) -> ResolvedMatch:
        """Resolve a single name. Pure (no caching) — caller manages cache."""
        candidates = self._search_by_name(fs_type, name)

        # Step 2a: zero candidates
        if not candidates:
            return ResolvedMatch(name=name)

        # Step 2b: exact-match shortcut
        norm = _normalize_name(name)
        for cand in candidates:
            fs = cand.get("factSheet") or {}
            if _normalize_name(fs.get("displayName") or "") == norm:
                ext_id = fs.get("externalId")
                detail = self._fetch_detail(fs_type, ext_id) if ext_id else {}
                return ResolvedMatch(
                    name=name,
                    external_id=ext_id,
                    catalog_uuid=fs.get("id"),
                    display_name=fs.get("displayName"),
                    confidence="VERYHIGH",
                    status="LINKED",
                    fields=self._build_fields(detail),
                )

        # Step 3+: ambiguous — probe path (added in Task 10)
        return self._resolve_via_probe(fs_type, name)

    def _build_fields(self, detail: dict) -> dict:
        """Flatten detail into the fields dict stored on ResolvedMatch."""
        out: dict[str, Any] = {}
        if detail.get("description"):
            out["description"] = detail["description"]
        for k, v in (detail.get("fields") or {}).items():
            if v is not None:
                out[k] = v
        return out

    def _resolve_via_probe(self, fs_type: str, name: str) -> ResolvedMatch:
        """Placeholder — filled in by Task 10."""
        return ResolvedMatch(name=name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS (26 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "feat(catalog): _resolve_one with exact-match shortcut"
```

---

## Task 10: Probe path with confidence decision

**Files:**
- Modify: `pipeline/reference_catalog.py`
- Test:   `tests/test_reference_catalog.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
_PROBE_BASE_NAME_APP = "_archimedes_probe_application"


def test_probe_veryhigh_auto_links():
    r = ReferenceCatalogResolver("https://x", "tok", interactive=False)
    search_payload = [
        # ambiguous: candidate displayName differs from input name
        {"alreadyLinked": False,
         "factSheet": {"id": "cat-uuid", "externalId": "lx_APP_111",
                       "displayName": "SAP S/4HANA Cloud", "type": "Application"}}
    ]
    create_resp = {"data": {"createFactSheet": {"factSheet": {"id": "probe-uuid"}}}}
    rename_resp = {"data": {"updateFactSheet": {"factSheet": {"id": "probe-uuid"}}}}
    batch_resp = {"data": {"probe-uuid": {"suggestions": [
        {"factSheet": {"id": "cat-uuid", "externalId": "lx_APP_111",
                       "displayName": "SAP S/4HANA Cloud",
                       "confidenceLevel": "VERYHIGH"}}
    ]}}}
    detail_resp = {
        "id": "cat-uuid", "externalId": "lx_APP_111",
        "displayName": "SAP S/4HANA Cloud",
        "description": "Cloud ERP",
        "fields": [{"name": "lxHostingType", "value": "saas"}],
        "relations": [],
    }
    with patch("pipeline.reference_catalog.requests.get",
               side_effect=[_mk_response(search_payload),
                            _mk_response(detail_resp)]), \
         patch("pipeline.reference_catalog.requests.post",
               side_effect=[_mk_response(create_resp),     # probe create
                            _mk_response(rename_resp),     # probe rename
                            _mk_response(batch_resp)]):    # batch-links
        m = r._resolve_one("Application", "SAP S4 HANA")  # not exact match
    assert m.status == "LINKED"
    assert m.confidence == "VERYHIGH"
    assert m.external_id == "lx_APP_111"
    assert m.fields["lxHostingType"] == "saas"


def test_probe_high_interactive_accept(monkeypatch):
    r = ReferenceCatalogResolver("https://x", "tok", interactive=True)
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    search_payload = [{"alreadyLinked": False, "factSheet": {
        "id": "x", "externalId": "lx_APP_222", "displayName": "SomeOther",
        "type": "Application"}}]
    create_resp = {"data": {"createFactSheet": {"factSheet": {"id": "probe-uuid"}}}}
    rename_resp = {"data": {"updateFactSheet": {"factSheet": {"id": "probe-uuid"}}}}
    batch_resp = {"data": {"probe-uuid": {"suggestions": [
        {"factSheet": {"id": "cat-uuid", "externalId": "lx_APP_333",
                       "displayName": "Best Guess",
                       "confidenceLevel": "HIGH"}}
    ]}}}
    detail_resp = {"id": "cat-uuid", "externalId": "lx_APP_333",
                   "displayName": "Best Guess", "description": "", "fields": [], "relations": []}
    with patch("pipeline.reference_catalog.requests.get",
               side_effect=[_mk_response(search_payload),
                            _mk_response(detail_resp)]), \
         patch("pipeline.reference_catalog.requests.post",
               side_effect=[_mk_response(create_resp),
                            _mk_response(rename_resp),
                            _mk_response(batch_resp)]):
        m = r._resolve_one("Application", "Something Ambiguous")
    assert m.status == "LINKED"
    assert m.confidence == "HIGH"
    assert m.external_id == "lx_APP_333"


def test_probe_high_non_interactive_falls_back_custom():
    r = ReferenceCatalogResolver("https://x", "tok", interactive=False)
    search_payload = [{"alreadyLinked": False, "factSheet": {
        "id": "x", "externalId": "lx_APP_222", "displayName": "SomeOther",
        "type": "Application"}}]
    create_resp = {"data": {"createFactSheet": {"factSheet": {"id": "probe-uuid"}}}}
    rename_resp = {"data": {"updateFactSheet": {"factSheet": {"id": "probe-uuid"}}}}
    batch_resp = {"data": {"probe-uuid": {"suggestions": [
        {"factSheet": {"id": "cat", "externalId": "lx_APP_999",
                       "displayName": "Guess", "confidenceLevel": "HIGH"}}
    ]}}}
    with patch("pipeline.reference_catalog.requests.get",
               return_value=_mk_response(search_payload)), \
         patch("pipeline.reference_catalog.requests.post",
               side_effect=[_mk_response(create_resp),
                            _mk_response(rename_resp),
                            _mk_response(batch_resp)]):
        m = r._resolve_one("Application", "Something")
    assert m.status == "CUSTOM"
    assert m.confidence == "HIGH"  # informational
    assert m.external_id is None


def test_probe_low_returns_custom():
    r = ReferenceCatalogResolver("https://x", "tok", interactive=False)
    search_payload = [{"alreadyLinked": False, "factSheet": {
        "id": "x", "externalId": "lx_APP_222", "displayName": "SomeOther",
        "type": "Application"}}]
    create_resp = {"data": {"createFactSheet": {"factSheet": {"id": "probe-uuid"}}}}
    rename_resp = {"data": {"updateFactSheet": {"factSheet": {"id": "probe-uuid"}}}}
    batch_resp = {"data": {"probe-uuid": {"suggestions": [
        {"factSheet": {"id": "cat", "externalId": "lx_APP_999",
                       "displayName": "Weak", "confidenceLevel": "LOW"}}
    ]}}}
    with patch("pipeline.reference_catalog.requests.get",
               return_value=_mk_response(search_payload)), \
         patch("pipeline.reference_catalog.requests.post",
               side_effect=[_mk_response(create_resp),
                            _mk_response(rename_resp),
                            _mk_response(batch_resp)]):
        m = r._resolve_one("Application", "Something")
    assert m.status == "CUSTOM"
    assert m.confidence == "LOW"
    assert m.external_id is None


def test_probe_create_failure_degrades_to_no_probe_mode():
    r = ReferenceCatalogResolver("https://x", "tok", interactive=False)
    search_payload = [{"alreadyLinked": False, "factSheet": {
        "id": "x", "externalId": "lx_APP_222", "displayName": "SomeOther",
        "type": "Application"}}]
    with patch("pipeline.reference_catalog.requests.get",
               return_value=_mk_response(search_payload)), \
         patch("pipeline.reference_catalog.requests.post",
               return_value=_mk_response({"errors": [{"message": "no"}]})):
        m = r._resolve_one("Application", "Something")
    assert m.status == "CUSTOM"
    assert r._no_probe_mode is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: FAIL — probe path returns CUSTOM placeholder

- [ ] **Step 3: Write minimal implementation**

Replace `_resolve_via_probe` in the class:

```python
    _PROBE_BASE = {
        "Application": "_archimedes_probe_application",
        "ITComponent": "_archimedes_probe_itcomponent",
    }

    def _ensure_probe(self, fs_type: str) -> str | None:
        """Lazy-create the per-type reusable probe FS. Returns its UUID or None."""
        if self._no_probe_mode:
            return None
        if fs_type in self._probe_ids:
            return self._probe_ids[fs_type]
        probe_id = self._probe_create(fs_type, self._PROBE_BASE[fs_type])
        if probe_id is None:
            self._no_probe_mode = True
            logger.warning("Probe creation failed for %s — entering no-probe mode", fs_type)
            return None
        self._probe_ids[fs_type] = probe_id
        return probe_id

    def _resolve_via_probe(self, fs_type: str, name: str) -> ResolvedMatch:
        probe_id = self._ensure_probe(fs_type)
        if probe_id is None:
            return ResolvedMatch(name=name)

        # Rename probe so the catalog matcher sees the actual search term.
        if not self._probe_rename(probe_id, name):
            return ResolvedMatch(name=name)

        top = self._batch_links(fs_type, probe_id, name)
        if not top:
            return ResolvedMatch(name=name)

        confidence = (top.get("confidenceLevel") or "NONE").upper()
        ext_id = top.get("externalId")
        display = top.get("displayName")
        catalog_uuid = top.get("id")

        # Decision
        link = False
        if confidence == "VERYHIGH":
            link = True
        elif confidence in ("HIGH", "MEDIUM"):
            link = self._prompt_link(name, display or "?", confidence)
        # LOW / anything else → CUSTOM

        if link and ext_id:
            detail = self._fetch_detail(fs_type, ext_id)
            return ResolvedMatch(
                name=name,
                external_id=ext_id,
                catalog_uuid=catalog_uuid,
                display_name=display,
                confidence=confidence,
                status="LINKED",
                fields=self._build_fields(detail),
            )
        # Informational match — kept for the audit report, but not linked.
        return ResolvedMatch(
            name=name, confidence=confidence, status="CUSTOM",
            display_name=display, catalog_uuid=catalog_uuid,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS (31 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "feat(catalog): probe-pattern resolution with confidence decision"
```

---

## Task 11: Public `resolve()` with caching

**Files:**
- Modify: `pipeline/reference_catalog.py`
- Test:   `tests/test_reference_catalog.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_resolve_returns_dict_keyed_by_original_name():
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch.object(r, "_resolve_one",
                      side_effect=lambda t, n: ResolvedMatch(
                          name=n, external_id=f"lx_APP_{hash(n) % 1000:03d}",
                          status="LINKED", confidence="VERYHIGH")):
        out = r.resolve("Application", ["App A", "App B"])
    assert set(out.keys()) == {"App A", "App B"}
    assert all(m.status == "LINKED" for m in out.values())


def test_resolve_uses_cache_on_repeat():
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch.object(r, "_resolve_one",
                      return_value=ResolvedMatch(
                          name="App A", external_id="lx_APP_001",
                          status="LINKED", confidence="VERYHIGH")) as inner:
        r.resolve("Application", ["App A"])
        r.resolve("Application", ["App A", "app a"])  # case-insensitive cache hit
    assert inner.call_count == 1


def test_resolve_empty_list():
    r = ReferenceCatalogResolver("https://x", "tok")
    assert r.resolve("Application", []) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: FAIL with `NotImplementedError`

- [ ] **Step 3: Write minimal implementation**

Replace the `resolve` method body:

```python
    def resolve(self, fs_type: str, names: list[str]) -> dict[str, ResolvedMatch]:
        out: dict[str, ResolvedMatch] = {}
        for name in names:
            if not name or not name.strip():
                continue
            key = (fs_type, _normalize_name(name))
            cached = self._cache.get(key)
            if cached is not None:
                # Preserve the original `name` field on the returned match
                out[name] = ResolvedMatch(
                    name=name,
                    external_id=cached.external_id,
                    catalog_uuid=cached.catalog_uuid,
                    display_name=cached.display_name,
                    confidence=cached.confidence,
                    status=cached.status,
                    fields=dict(cached.fields),
                )
                continue
            match = self._resolve_one(fs_type, name)
            self._cache[key] = match
            out[name] = match
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS (34 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "feat(catalog): public resolve() with in-memory cache"
```

---

## Task 12: `cleanup()` archives probe FSs

**Files:**
- Modify: `pipeline/reference_catalog.py`
- Test:   `tests/test_reference_catalog.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_cleanup_archives_all_probe_ids():
    r = ReferenceCatalogResolver("https://x", "tok")
    r._probe_ids = {"Application": "probe-app", "ITComponent": "probe-itc"}
    with patch.object(r, "_probe_archive", return_value=True) as arch:
        r.cleanup()
    assert arch.call_count == 2
    assert r._probe_ids == {}


def test_cleanup_idempotent_no_probes():
    r = ReferenceCatalogResolver("https://x", "tok")
    # Should not raise
    r.cleanup()


def test_cleanup_archive_failure_does_not_raise():
    r = ReferenceCatalogResolver("https://x", "tok")
    r._probe_ids = {"Application": "probe-app"}
    with patch.object(r, "_probe_archive", return_value=False):
        r.cleanup()  # logs but does not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: FAIL — cleanup is a no-op stub

- [ ] **Step 3: Write minimal implementation**

Replace `cleanup`:

```python
    def cleanup(self) -> None:
        for fs_type, fs_id in list(self._probe_ids.items()):
            ok = self._probe_archive(fs_id)
            if not ok:
                logger.warning(
                    "Failed to archive probe FS %s (%s) — manual cleanup may be needed",
                    fs_type, fs_id,
                )
            self._probe_ids.pop(fs_type, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reference_catalog.py -v`
Expected: PASS (37 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/reference_catalog.py tests/test_reference_catalog.py
git commit -m "feat(catalog): cleanup() archives reusable probe FSs"
```

---

## Task 13: Integration into `write_leanix_excel`

**Files:**
- Modify: `pipeline/write.py` (around line 367 — `write_leanix_excel` function)
- Test:   `tests/test_write_with_catalog.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `tests/test_write_with_catalog.py`:

```python
"""Integration tests: write_leanix_excel ↔ ReferenceCatalogResolver."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.reference_catalog import ResolvedMatch


@pytest.fixture
def enriched_minimal():
    """One enriched row that produces one Application + one ITComponent."""
    return [{
        "id": "REQ-1",
        "module": "Finance",
        "bcs": [{"name": "Accounting", "fit": "perfect"}],
        "rsa": "S/4HANA Cloud",
        "ext_apps": "",
        "dev": "",
        "dev_exp": "",
        "licensing": "",
        "coverage": "",
        "comment": "",
    }]


def test_excel_carries_external_id_for_linked_apps(tmp_path, enriched_minimal, monkeypatch):
    """When resolver returns LINKED, the staging Excel has an externalId column populated."""
    monkeypatch.setenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "true")

    fake_resolver = MagicMock()
    fake_resolver.resolve.side_effect = lambda fs_type, names: {
        n: ResolvedMatch(
            name=n,
            external_id="lx_APP_000001" if fs_type == "Application" else "lx_ITC_000001",
            catalog_uuid="uuid-1",
            display_name=n,
            confidence="VERYHIGH",
            status="LINKED",
            fields={"description": "from catalog", "lxHostingType": "saas"},
        ) for n in names
    }

    from pipeline.write import write_leanix_excel
    out = tmp_path / "x.xlsx"
    with patch("pipeline.write.ReferenceCatalogResolver", return_value=fake_resolver), \
         patch("pipeline.write._get_bearer", return_value=("https://x", "tok")):
        write_leanix_excel(enriched_minimal, {}, str(out), client_name="test")

    wb = load_workbook(out)
    app_sheet = wb["Application"]
    headers = [c.value for c in app_sheet[1]]
    assert "externalId" in headers
    ext_col = headers.index("externalId") + 1
    # row 2 is the first data row
    assert app_sheet.cell(row=2, column=ext_col).value == "lx_APP_000001"


def test_custom_apps_have_empty_external_id(tmp_path, enriched_minimal, monkeypatch):
    monkeypatch.setenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "true")

    fake_resolver = MagicMock()
    fake_resolver.resolve.side_effect = lambda fs_type, names: {
        n: ResolvedMatch(name=n) for n in names
    }
    from pipeline.write import write_leanix_excel
    out = tmp_path / "x.xlsx"
    with patch("pipeline.write.ReferenceCatalogResolver", return_value=fake_resolver), \
         patch("pipeline.write._get_bearer", return_value=("https://x", "tok")):
        write_leanix_excel(enriched_minimal, {}, str(out), client_name="test")

    wb = load_workbook(out)
    app_sheet = wb["Application"]
    headers = [c.value for c in app_sheet[1]]
    ext_col = headers.index("externalId") + 1
    val = app_sheet.cell(row=2, column=ext_col).value
    assert val in (None, "")


def test_resolver_failure_pipeline_continues(tmp_path, enriched_minimal, monkeypatch):
    """If the resolver raises, write_leanix_excel still produces an Excel."""
    monkeypatch.setenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "true")

    fake_cls = MagicMock(side_effect=RuntimeError("resolver broken"))
    from pipeline.write import write_leanix_excel
    out = tmp_path / "x.xlsx"
    with patch("pipeline.write.ReferenceCatalogResolver", fake_cls), \
         patch("pipeline.write._get_bearer", return_value=("https://x", "tok")):
        write_leanix_excel(enriched_minimal, {}, str(out), client_name="test")
    assert out.exists()


def test_feature_flag_off_skips_resolver(tmp_path, enriched_minimal, monkeypatch):
    monkeypatch.setenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "false")

    fake_cls = MagicMock()
    from pipeline.write import write_leanix_excel
    out = tmp_path / "x.xlsx"
    with patch("pipeline.write.ReferenceCatalogResolver", fake_cls):
        write_leanix_excel(enriched_minimal, {}, str(out), client_name="test")
    fake_cls.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_write_with_catalog.py -v`
Expected: FAIL — `ReferenceCatalogResolver` not imported in `pipeline.write`, no integration yet.

- [ ] **Step 3: Write minimal implementation**

In `pipeline/write.py`:

a) Add near other imports at the top of the file:

```python
import os
from pipeline.reference_catalog import ReferenceCatalogResolver, ResolvedMatch
```

b) In `write_leanix_excel`, immediately AFTER `apps_dedup` and `itcs_dedup` (the deduplicated name lists) are built and BEFORE the workbook starts writing the App / ITC sheets, insert the resolver block:

```python
    # ── Reference Catalog pre-creation resolution ────────────────────────────
    app_matches: dict[str, ResolvedMatch] = {}
    itc_matches: dict[str, ResolvedMatch] = {}
    resolver = None
    if os.getenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "false").lower() in ("1", "true", "yes"):
        try:
            base_url, api_token = _get_bearer()
            resolver = ReferenceCatalogResolver(base_url=base_url, api_token=api_token)
            app_names = [r.get("name") for r in app_rows if r.get("name")]
            itc_names = [r.get("name") for r in itc_rows if r.get("name")]
            app_matches = resolver.resolve("Application", app_names)
            itc_matches = resolver.resolve("ITComponent", itc_names)
        except Exception as exc:
            logger.warning(
                "Reference Catalog resolver failed (%s) — proceeding without externalIds",
                exc,
            )
            app_matches, itc_matches = {}, {}

    def _decorate(row: dict, matches: dict[str, ResolvedMatch]) -> dict:
        m = matches.get(row.get("name"))
        if not m or m.status != "LINKED":
            return row
        row["externalId"] = m.external_id
        row["catalog_confidence"] = m.confidence
        row["catalog_status"] = m.status
        # Catalog wins on these fields
        for k, v in m.fields.items():
            if v is not None:
                row[k] = v
        return row

    app_rows = [_decorate(r, app_matches) for r in app_rows]
    itc_rows = [_decorate(r, itc_matches) for r in itc_rows]
```

c) When emitting the Application / ITComponent sheets, ensure `externalId`, `catalog_confidence`, `catalog_status` are included in the header list (append at the end of each existing header tuple — order doesn't matter for LeanIX import, but keep them grouped).

d) At the end of `write_leanix_excel`, in a `finally` (or just before return):

```python
    if resolver is not None:
        try:
            resolver.cleanup()
        except Exception as exc:
            logger.warning("Resolver cleanup failed: %s", exc)
```

(Names like `app_rows`, `itc_rows`, `apps_dedup`, `itcs_dedup` match what's currently in `write_leanix_excel` at line 367 onward. If your local variable names differ, use the deduplicated list of Application/ITComponent row dicts.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_write_with_catalog.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add pipeline/write.py tests/test_write_with_catalog.py
git commit -m "feat(write): integrate ReferenceCatalogResolver pre-Excel (feature flag)"
```

---

## Task 14: Push consumes `externalId`

**Files:**
- Modify: `pipeline/push_ldif.py` (and any GraphQL push path in `pipeline/write.py`)
- Test:   `tests/test_write_with_catalog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_write_with_catalog.py`:

```python
def test_push_payload_includes_external_id_when_present():
    """When a row carries externalId, the createFactSheet payload includes it."""
    from pipeline.push_ldif import build_create_factsheet_payload  # may be _build_..., adjust

    row = {
        "name": "SAP S/4HANA",
        "type": "Application",
        "externalId": "lx_APP_000123",
        "description": "ERP",
    }
    payload = build_create_factsheet_payload(row)
    assert payload.get("externalId") == "lx_APP_000123"


def test_push_payload_omits_external_id_when_absent():
    from pipeline.push_ldif import build_create_factsheet_payload

    row = {"name": "Custom App", "type": "Application", "description": ""}
    payload = build_create_factsheet_payload(row)
    assert "externalId" not in payload or payload["externalId"] in (None, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_write_with_catalog.py -v`
Expected: FAIL — function does not include `externalId`, or builder has a different name.

If the existing push module does not expose a payload-builder function: extract the body that constructs the `createFactSheet` input into a small pure function `build_create_factsheet_payload(row: dict) -> dict` and call it from the existing caller. This is the surgical change that keeps the rest of the push path untouched.

- [ ] **Step 3: Write minimal implementation**

In `pipeline/push_ldif.py`, locate where `createFactSheet` input is constructed and ensure it does:

```python
def build_create_factsheet_payload(row: dict) -> dict:
    payload = {
        "name": row.get("name"),
        "type": row.get("type"),
    }
    if row.get("externalId"):
        payload["externalId"] = row["externalId"]
    # ... existing description / field handling unchanged ...
    return payload
```

The caller passes `payload` to the GraphQL mutation exactly as today.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_write_with_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/push_ldif.py tests/test_write_with_catalog.py
git commit -m "feat(push): include externalId in createFactSheet payload when present"
```

---

## Task 15: `_link_apps_to_catalog` skips already-linked rows

**Files:**
- Modify: `pipeline/write.py` (`_link_apps_to_catalog`, around line 1769)
- Test:   `tests/test_write_with_catalog.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_link_apps_skips_rows_with_external_id():
    """Post-push linker should not try to link rows that already carried externalId."""
    from pipeline.write import _link_apps_to_catalog

    # app_id_cache maps display name -> workspace FS UUID
    app_id_cache = {"SAP S/4HANA": "ws-uuid-1", "Custom App": "ws-uuid-2"}
    rows_by_name = {
        "SAP S/4HANA": {"externalId": "lx_APP_000123"},
        "Custom App": {},
    }

    with patch("pipeline.write.requests.post") as post, \
         patch("pipeline.write.requests.get",
               return_value=MagicMock(status_code=200, json=lambda: [],
                                       raise_for_status=MagicMock())):
        _link_apps_to_catalog("https://x", "tok", app_id_cache, {},
                              rows_by_name=rows_by_name)
    # Only Custom App should reach the catalog API
    called_with = [c.args[0] for c in post.call_args_list]
    assert all("ws-uuid-1" not in str(c) for c in called_with)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_write_with_catalog.py -v`
Expected: FAIL — function does not accept `rows_by_name`.

- [ ] **Step 3: Write minimal implementation**

In `pipeline/write.py`, change `_link_apps_to_catalog` signature to accept an optional `rows_by_name` kwarg. Early in the per-app loop, skip the entry if `rows_by_name.get(name, {}).get("externalId")` is truthy:

```python
def _link_apps_to_catalog(base_url, api_token, app_id_cache, itc_id_cache,
                          rows_by_name=None):
    rows_by_name = rows_by_name or {}
    for name, fs_id in app_id_cache.items():
        if rows_by_name.get(name, {}).get("externalId"):
            logger.debug("Skipping post-push link for %s (already linked at create)", name)
            continue
        # ... existing logic unchanged ...
```

Update the caller in `write_leanix_excel` (and any other call sites) to pass `rows_by_name={r['name']: r for r in app_rows + itc_rows if r.get('name')}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_write_with_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/write.py tests/test_write_with_catalog.py
git commit -m "feat(write): post-push linker skips rows already linked via externalId"
```

---

## Task 16: Audit report — `catalog_resolution_report.json`

**Files:**
- Modify: `pipeline/write.py`
- Test:   `tests/test_write_with_catalog.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_catalog_resolution_report_written(tmp_path, enriched_minimal, monkeypatch):
    monkeypatch.setenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "true")
    fake_resolver = MagicMock()
    fake_resolver.resolve.side_effect = lambda fs_type, names: {
        n: ResolvedMatch(name=n, external_id="lx_APP_001",
                         display_name=n, confidence="VERYHIGH",
                         status="LINKED", fields={})
        for n in names
    }
    from pipeline.write import write_leanix_excel
    out = tmp_path / "x.xlsx"
    with patch("pipeline.write.ReferenceCatalogResolver", return_value=fake_resolver), \
         patch("pipeline.write._get_bearer", return_value=("https://x", "tok")):
        write_leanix_excel(enriched_minimal, {}, str(out), client_name="test")

    import json
    report = tmp_path / "catalog_resolution_report.json"
    # The report is written next to the Excel
    if not report.exists():
        report = out.parent / "catalog_resolution_report.json"
    assert report.exists()
    body = json.loads(report.read_text())
    assert any(e.get("status") == "LINKED" for e in body.get("Application", []))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_write_with_catalog.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

In `write_leanix_excel`, right after the `_decorate` calls:

```python
    import json
    report = {
        "Application": [
            {"name": m.name, "external_id": m.external_id,
             "confidence": m.confidence, "status": m.status}
            for m in app_matches.values()
        ],
        "ITComponent": [
            {"name": m.name, "external_id": m.external_id,
             "confidence": m.confidence, "status": m.status}
            for m in itc_matches.values()
        ],
    }
    try:
        (Path(output_path).parent / "catalog_resolution_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
    except Exception as exc:
        logger.warning("Could not write catalog_resolution_report.json: %s", exc)
```

Also emit a summary log line:

```python
    def _count(matches, key, value):
        return sum(1 for m in matches.values() if getattr(m, key) == value)

    logger.info(
        "Reference Catalog Application: %d names — %d LINKED, %d CUSTOM",
        len(app_matches),
        _count(app_matches, "status", "LINKED"),
        _count(app_matches, "status", "CUSTOM"),
    )
    logger.info(
        "Reference Catalog ITComponent: %d names — %d LINKED, %d CUSTOM",
        len(itc_matches),
        _count(itc_matches, "status", "LINKED"),
        _count(itc_matches, "status", "CUSTOM"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_write_with_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/write.py tests/test_write_with_catalog.py
git commit -m "feat(write): emit catalog_resolution_report.json + summary log"
```

---

## Task 17: End-to-end coverage check

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: all previously passing tests still pass; new tests pass.

- [ ] **Step 2: Coverage check (optional but recommended)**

Run: `pytest tests/test_reference_catalog.py tests/test_write_with_catalog.py --cov=pipeline.reference_catalog --cov-report=term-missing`
Expected: ≥85% line coverage on `pipeline/reference_catalog.py`.

- [ ] **Step 3: Lint check**

Run: `python -m py_compile pipeline/reference_catalog.py pipeline/write.py pipeline/push_ldif.py`
Expected: no syntax errors.

- [ ] **Step 4: Commit any final touch-ups**

```bash
git status
# if nothing to add, skip; otherwise:
git add -p
git commit -m "chore(catalog): final cleanup after end-to-end check"
```

---

## Task 18: Rollout — flag flip and docs

- [ ] **Step 1: Update README / CHANGELOG**

Add a section under "Configuration" in the project README mentioning:
- `ARCHIMEDES_USE_CATALOG_RESOLVER=true` to enable pre-creation catalog resolution
- Default: off
- Note about probe FSs named `_archimedes_probe_application` / `_archimedes_probe_itcomponent`

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(catalog): document ARCHIMEDES_USE_CATALOG_RESOLVER flag"
```

- [ ] **Step 3: First real-run smoke (manual, OUT OF SCOPE per spec)**

Smoke testing against a real workspace is **not** part of this plan. The user will run one pipeline with the flag enabled and compare the Excel + post-push diff manually.

- [ ] **Step 4: Flip the default (separate change, after smoke passes)**

In `pipeline/write.py`, change the default from `"false"` to `"true"`:

```python
if os.getenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "true").lower() in ("1", "true", "yes"):
```

Commit:
```bash
git commit -am "feat(catalog): enable resolver by default"
```

---

## Notes for the implementer

- **Test naming:** existing tests use `tests/test_<module>.py` with `sys.path.insert(0, ...)`. Follow that pattern.
- **No new runtime dependencies:** `requests` is already used in `write.py`. Tests only need `unittest.mock` (stdlib) and `pytest`.
- **Logging:** use `logger = logging.getLogger(__name__)` at module top — matches `pipeline/enrich.py` and `pipeline/catalog.py` patterns.
- **Spanish/English mix in user-facing prompts is fine:** the existing CLI in `pipeline/catalog.py` uses Spanish, but the resolver prompts can stay in English since they're API-tier messages. If the user requests Spanish, swap the prompt strings — pure string change.
- **No malware:** this is an enterprise integration with the user's own LeanIX workspace via their admin token. The resolver creates two long-lived probe fact sheets per workspace named `_archimedes_probe_*` and archives them on cleanup.
- **`responses` library not strictly required:** all tests use `unittest.mock.patch` on `requests.get` / `requests.post` directly. If the user prefers the `responses` library, the tests can be rewritten — but `unittest.mock` keeps the deps unchanged.
