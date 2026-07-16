# SAP Internal Discovery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `pipeline/sap_discovery/` — a new package that configures the LeanIX Internal SAP Landscape Data integration and processes its inbox end-to-end (link + create + review), and wire it into the wizard as a parallel Baseline route.

**Architecture:** Four-module package (`client` / `matcher` / `orchestrator` / `report`) following the existing `catalog + catalog_report + reference_catalog` pattern. Two-phase async orchestration exposed as four FastAPI endpoints. TDD per module using `MagicMock` + FastAPI `TestClient`, matching the style of `tests/test_leanix_auth.py` and `tests/test_wizard_from_one360.py`.

**Tech Stack:** Python 3.11+, FastAPI, pytest, `requests`, `unittest.mock`. Reuses `pipeline.leanix_auth.get_bearer` and `pipeline.write.create_factsheet`.

**Spec:** `docs/superpowers/specs/2026-07-16-sap-internal-discovery-design.md`

---

## File map

**Create:**
- `pipeline/sap_discovery/__init__.py` — public API
- `pipeline/sap_discovery/client.py` — REST client
- `pipeline/sap_discovery/matcher.py` — pure matching heuristics
- `pipeline/sap_discovery/orchestrator.py` — two-phase orchestration
- `pipeline/sap_discovery/report.py` — HTML/JSON report
- `tests/test_sap_discovery_client.py`
- `tests/test_sap_discovery_matcher.py`
- `tests/test_sap_discovery_orchestrator.py`
- `tests/test_sap_discovery_report.py`
- `tests/test_wizard_from_sap_discovery.py`

**Modify:**
- `archimedes_wizard.py` — add 4 endpoints under `/api/session/{sid}/baseline/sap-discovery/*`
- `archimedes_wizard.html` — add "SAP Internal Discovery" tab in Step 2 alongside "ONE360"

---

## Task 1: Package skeleton

**Files:**
- Create: `pipeline/sap_discovery/__init__.py`

- [ ] **Step 1: Create the package init exposing planned public API**

Content of `pipeline/sap_discovery/__init__.py`:

```python
"""pipeline.sap_discovery — Vía B for SAP Internal Discovery.

Package layout:
- client: REST calls to discovery-sap-extension + discovery-linking v2
- matcher: pure heuristics that turn a DiscoveryItem into a MatchDecision
- orchestrator: two-phase flow (start_integration, process_inbox, apply_review)
- report: HTML/JSON report renderer

Design: docs/superpowers/specs/2026-07-16-sap-internal-discovery-design.md
"""
from __future__ import annotations

from pipeline.sap_discovery.client import (
    Client,
    DiscoveryItem,
)
from pipeline.sap_discovery.matcher import (
    MatchDecision,
    decide,
)
from pipeline.sap_discovery.orchestrator import (
    apply_review,
    poll_status,
    process_inbox,
    start_integration,
)
from pipeline.sap_discovery.report import build

__all__ = [
    "Client",
    "DiscoveryItem",
    "MatchDecision",
    "apply_review",
    "build",
    "decide",
    "poll_status",
    "process_inbox",
    "start_integration",
]
```

- [ ] **Step 2: Commit**

```bash
git add pipeline/sap_discovery/__init__.py
git commit -m "feat(sap-discovery): scaffold pipeline.sap_discovery package"
```

Expected: commit succeeds. Test suite is unaffected because none of the imports resolve yet — this task is only committing the top-level API surface. The next tasks build the modules bottom-up in the order required by the imports.

Note: `__init__.py` re-exports symbols from modules that don't exist yet. Later tasks create those modules. If the CI/pre-commit hook runs `python -c "import pipeline.sap_discovery"` this commit would fail; check if such a hook exists (`.pre-commit-config.yaml` / `.githooks/`). If it does, split this commit and land it after Task 5 instead.

---

## Task 2: DiscoveryItem dataclass + minimal Client stub

**Files:**
- Create: `pipeline/sap_discovery/client.py`
- Test: `tests/test_sap_discovery_client.py`

- [ ] **Step 1: Write failing test for DiscoveryItem parsing**

Content of `tests/test_sap_discovery_client.py`:

```python
"""Tests for pipeline.sap_discovery.client — REST client + DiscoveryItem parsing."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pipeline.sap_discovery.client import Client, DiscoveryItem


def _mk_client() -> Client:
    return Client(base_url="https://demo.leanix.net", api_token="tok")


def test_discovery_item_from_api_payload_populates_all_fields():
    payload = {
        "id": "disc-1",
        "displayName": "SAP S/4HANA Cloud - PROD",
        "classification": "SaaS_ERP",
        "product": "SAP S/4HANA Cloud",
        "systemRole": "PROD",
        "status": "action_needed",
        "suggestedLinks": {
            "application": [
                {"factSheetId": "fs-app-1", "name": "S/4HANA", "label": "existing"}
            ],
            "itcomponent": [],
            "provider": [],
        },
    }
    item = DiscoveryItem.from_api(payload)
    assert item.id == "disc-1"
    assert item.display_name == "SAP S/4HANA Cloud - PROD"
    assert item.classification == "SaaS_ERP"
    assert item.product == "SAP S/4HANA Cloud"
    assert item.system_role == "PROD"
    assert item.status == "action_needed"
    assert item.suggested_links["application"][0]["factsheet_id"] == "fs-app-1"
    assert item.suggested_links["application"][0]["label"] == "existing"
    assert item.raw == payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sap_discovery_client.py::test_discovery_item_from_api_payload_populates_all_fields -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.sap_discovery.client'`.

- [ ] **Step 3: Implement DiscoveryItem + empty Client**

Content of `pipeline/sap_discovery/client.py`:

```python
"""pipeline.sap_discovery.client — thin REST client over LeanIX discovery APIs.

Endpoints used:
- POST /services/discovery-sap-extension/v1/integrations
- PUT  /services/discovery-linking/v2/{origin}/settings/autoLinking
- GET  /services/discovery-linking/v2/{origin}/discoveryItems
- PUT  /services/discovery-linking/v2/{origin}/discoveryItems/link
- PUT  /services/discovery-linking/v2/{origin}/discoveryItems/reject

Authentication is delegated to pipeline.leanix_auth.get_bearer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiscoveryItem:
    id: str
    display_name: str
    classification: str
    product: str
    system_role: str | None
    status: str
    suggested_links: dict
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict) -> "DiscoveryItem":
        raw_links = payload.get("suggestedLinks") or {}
        normalized: dict[str, list[dict]] = {}
        for key in ("application", "itcomponent", "provider"):
            entries = raw_links.get(key) or []
            normalized[key] = [
                {
                    "factsheet_id": e.get("factSheetId"),
                    "name": e.get("name", ""),
                    "label": e.get("label", "existing"),
                }
                for e in entries
            ]
        return cls(
            id=payload["id"],
            display_name=payload.get("displayName", ""),
            classification=payload.get("classification", ""),
            product=payload.get("product", ""),
            system_role=payload.get("systemRole"),
            status=payload.get("status", ""),
            suggested_links=normalized,
            raw=payload,
        )


class Client:
    """LeanIX discovery REST client. All HTTP calls live in this class."""

    def __init__(self, base_url: str, api_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sap_discovery_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/sap_discovery/client.py tests/test_sap_discovery_client.py
git commit -m "feat(sap-discovery): DiscoveryItem dataclass with from_api parser"
```

---

## Task 3: Client.create_integration

**Files:**
- Modify: `pipeline/sap_discovery/client.py`
- Modify: `tests/test_sap_discovery_client.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_sap_discovery_client.py`:

```python
def test_create_integration_posts_expected_body_and_returns_id():
    client = _mk_client()

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": "int-abc", "status": "PROVISIONING"}
    mock_resp.raise_for_status.return_value = None

    with patch("pipeline.sap_discovery.client.get_bearer", return_value="BEARER"), \
         patch("pipeline.sap_discovery.client.requests.post", return_value=mock_resp) as p:
        result = client.create_integration(crm_id="0001234567")

    p.assert_called_once()
    args, kwargs = p.call_args
    assert args[0] == "https://demo.leanix.net/services/discovery-sap-extension/v1/integrations"
    assert kwargs["json"] == {"customerIdentifiers": [{"type": "CRM", "id": "0001234567"}]}
    assert kwargs["headers"]["Authorization"] == "Bearer BEARER"
    assert result == {"id": "int-abc", "status": "PROVISIONING"}


def test_create_integration_raises_on_409_conflict():
    client = _mk_client()
    import requests as _rq

    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_resp.raise_for_status.side_effect = _rq.HTTPError("409 Conflict")

    with patch("pipeline.sap_discovery.client.get_bearer", return_value="BEARER"), \
         patch("pipeline.sap_discovery.client.requests.post", return_value=mock_resp):
        with pytest.raises(_rq.HTTPError):
            client.create_integration(crm_id="0001234567")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sap_discovery_client.py -v -k create_integration`
Expected: FAIL with `AttributeError: 'Client' object has no attribute 'create_integration'`.

- [ ] **Step 3: Implement create_integration**

Add to `pipeline/sap_discovery/client.py` (imports at top, method inside `Client`):

```python
import requests

from pipeline.leanix_auth import get_bearer
```

Add method inside `Client`:

```python
    def create_integration(self, crm_id: str) -> dict:
        """POST /services/discovery-sap-extension/v1/integrations.

        Returns the integration record as JSON. Raises requests.HTTPError on 4xx/5xx.
        """
        token = get_bearer(self.base_url, self.api_token)
        resp = requests.post(
            f"{self.base_url}/services/discovery-sap-extension/v1/integrations",
            json={"customerIdentifiers": [{"type": "CRM", "id": crm_id}]},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sap_discovery_client.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/sap_discovery/client.py tests/test_sap_discovery_client.py
git commit -m "feat(sap-discovery): Client.create_integration for discovery-sap-extension v1"
```

---

## Task 4: Client.set_autolinking + list_inbox with origin discovery

**Files:**
- Modify: `pipeline/sap_discovery/client.py`
- Modify: `tests/test_sap_discovery_client.py`

- [ ] **Step 1: Write failing tests for set_autolinking + origin discovery + list_inbox**

Append to `tests/test_sap_discovery_client.py`:

```python
def test_set_autolinking_puts_expected_body():
    client = _mk_client()

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"autoLinking": True}
    mock_resp.raise_for_status.return_value = None

    with patch("pipeline.sap_discovery.client.get_bearer", return_value="BEARER"), \
         patch("pipeline.sap_discovery.client.requests.put", return_value=mock_resp) as p:
        client.set_autolinking(origin="sap-extension", enabled=True)

    args, kwargs = p.call_args
    assert args[0] == (
        "https://demo.leanix.net/services/discovery-linking/v2/sap-extension/settings/autoLinking"
    )
    assert kwargs["json"] == {"enabled": True}


def test_discover_origin_returns_first_candidate_that_answers_2xx():
    client = _mk_client()

    def _fake_get(url, **_kw):
        m = MagicMock()
        # sap-extension answers 404, internal-sap answers 200
        if "internal-sap" in url:
            m.status_code = 200
            m.raise_for_status.return_value = None
        else:
            m.status_code = 404
            import requests as _rq
            m.raise_for_status.side_effect = _rq.HTTPError("404")
        return m

    with patch("pipeline.sap_discovery.client.get_bearer", return_value="BEARER"), \
         patch("pipeline.sap_discovery.client.requests.get", side_effect=_fake_get):
        origin = client.discover_origin()
    assert origin == "internal-sap"


def test_list_inbox_returns_parsed_discovery_items():
    client = _mk_client()

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "items": [
            {
                "id": "d1",
                "displayName": "SAP S/4HANA Cloud - PROD",
                "classification": "SaaS_ERP",
                "product": "SAP S/4HANA Cloud",
                "systemRole": "PROD",
                "status": "action_needed",
                "suggestedLinks": {"application": [], "itcomponent": [], "provider": []},
            }
        ]
    }
    mock_resp.raise_for_status.return_value = None

    with patch("pipeline.sap_discovery.client.get_bearer", return_value="BEARER"), \
         patch("pipeline.sap_discovery.client.requests.get", return_value=mock_resp) as p:
        items = client.list_inbox(origin="sap-extension", status="action_needed")

    args, kwargs = p.call_args
    assert args[0] == (
        "https://demo.leanix.net/services/discovery-linking/v2/sap-extension/discoveryItems"
    )
    assert kwargs["params"] == {"status": "action_needed"}
    assert len(items) == 1
    assert items[0].id == "d1"
    assert items[0].classification == "SaaS_ERP"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sap_discovery_client.py -v -k "set_autolinking or discover_origin or list_inbox"`
Expected: FAIL for all three (methods do not exist).

- [ ] **Step 3: Implement methods**

Add to `pipeline/sap_discovery/client.py` inside `Client`:

```python
    _ORIGIN_CANDIDATES = ("sap-extension", "internal-sap", "sap-landscape")

    def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {get_bearer(self.base_url, self.api_token)}"}

    def set_autolinking(self, origin: str, enabled: bool) -> None:
        resp = requests.put(
            f"{self.base_url}/services/discovery-linking/v2/{origin}/settings/autoLinking",
            json={"enabled": enabled},
            headers=self._auth_header(),
            timeout=30,
        )
        resp.raise_for_status()

    def discover_origin(self) -> str:
        """Probe origin candidates. Return the first that returns 2xx to a HEAD-equivalent GET.

        Raises RuntimeError if none respond.
        """
        for candidate in self._ORIGIN_CANDIDATES:
            resp = requests.get(
                f"{self.base_url}/services/discovery-linking/v2/{candidate}/discoveryItems",
                params={"limit": 1},
                headers=self._auth_header(),
                timeout=30,
            )
            if resp.status_code < 400:
                return candidate
        raise RuntimeError(
            f"No SAP discovery origin resolved. Tried: {', '.join(self._ORIGIN_CANDIDATES)}"
        )

    def list_inbox(self, origin: str, status: str | None = None) -> list[DiscoveryItem]:
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        resp = requests.get(
            f"{self.base_url}/services/discovery-linking/v2/{origin}/discoveryItems",
            params=params,
            headers=self._auth_header(),
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        return [DiscoveryItem.from_api(x) for x in data.get("items", [])]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sap_discovery_client.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/sap_discovery/client.py tests/test_sap_discovery_client.py
git commit -m "feat(sap-discovery): Client.set_autolinking + discover_origin + list_inbox"
```

---

## Task 5: Client.bulk_link + bulk_reject

**Files:**
- Modify: `pipeline/sap_discovery/client.py`
- Modify: `tests/test_sap_discovery_client.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sap_discovery_client.py`:

```python
def test_bulk_link_puts_decisions_and_returns_result():
    client = _mk_client()
    decisions = [
        {"itemId": "d1", "targetType": "Application", "targetId": "fs-app-1"},
        {"itemId": "d2", "targetType": "ITComponent", "targetId": "fs-itc-2"},
    ]

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"applied": ["d1", "d2"], "failed": []}
    mock_resp.raise_for_status.return_value = None

    with patch("pipeline.sap_discovery.client.get_bearer", return_value="BEARER"), \
         patch("pipeline.sap_discovery.client.requests.put", return_value=mock_resp) as p:
        result = client.bulk_link(origin="sap-extension", decisions=decisions)

    args, kwargs = p.call_args
    assert args[0] == (
        "https://demo.leanix.net/services/discovery-linking/v2/sap-extension/discoveryItems/link"
    )
    assert kwargs["json"] == {"decisions": decisions}
    assert result == {"applied": ["d1", "d2"], "failed": []}


def test_bulk_reject_puts_item_ids():
    client = _mk_client()

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"applied": ["d3"], "failed": []}
    mock_resp.raise_for_status.return_value = None

    with patch("pipeline.sap_discovery.client.get_bearer", return_value="BEARER"), \
         patch("pipeline.sap_discovery.client.requests.put", return_value=mock_resp) as p:
        result = client.bulk_reject(origin="sap-extension", item_ids=["d3"])

    args, kwargs = p.call_args
    assert args[0] == (
        "https://demo.leanix.net/services/discovery-linking/v2/sap-extension/discoveryItems/reject"
    )
    assert kwargs["json"] == {"itemIds": ["d3"]}
    assert result == {"applied": ["d3"], "failed": []}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sap_discovery_client.py -v -k "bulk"`
Expected: FAIL (methods do not exist).

- [ ] **Step 3: Implement methods**

Add to `pipeline/sap_discovery/client.py` inside `Client`:

```python
    def bulk_link(self, origin: str, decisions: list[dict]) -> dict:
        """PUT /discovery-linking/v2/{origin}/discoveryItems/link.

        Each decision: {"itemId": str, "targetType": str, "targetId": str}.
        Returns the API response verbatim ({"applied": [...], "failed": [...]}).
        """
        resp = requests.put(
            f"{self.base_url}/services/discovery-linking/v2/{origin}/discoveryItems/link",
            json={"decisions": decisions},
            headers=self._auth_header(),
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def bulk_reject(self, origin: str, item_ids: list[str]) -> dict:
        resp = requests.put(
            f"{self.base_url}/services/discovery-linking/v2/{origin}/discoveryItems/reject",
            json={"itemIds": item_ids},
            headers=self._auth_header(),
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sap_discovery_client.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/sap_discovery/client.py tests/test_sap_discovery_client.py
git commit -m "feat(sap-discovery): Client.bulk_link + bulk_reject"
```

---

## Task 6: MatchDecision + matcher.decide (pure)

**Files:**
- Create: `pipeline/sap_discovery/matcher.py`
- Create: `tests/test_sap_discovery_matcher.py`

- [ ] **Step 1: Write failing tests covering all branches**

Content of `tests/test_sap_discovery_matcher.py`:

```python
"""Tests for pipeline.sap_discovery.matcher — pure decision logic."""
from __future__ import annotations

from pipeline.sap_discovery.client import DiscoveryItem
from pipeline.sap_discovery.matcher import MatchDecision, decide


def _item(
    id_: str = "d1",
    status: str = "action_needed",
    classification: str = "SaaS_ERP",
    product: str = "SAP S/4HANA Cloud",
    suggested: dict | None = None,
) -> DiscoveryItem:
    return DiscoveryItem(
        id=id_,
        display_name=f"{product} - PROD",
        classification=classification,
        product=product,
        system_role="PROD",
        status=status,
        suggested_links=suggested or {"application": [], "itcomponent": [], "provider": []},
        raw={},
    )


def _catalog(products: list[str]) -> dict:
    return {p: {"category": "erp"} for p in products}


def test_high_confidence_when_single_existing_application_match():
    item = _item(
        suggested={
            "application": [
                {"factsheet_id": "fs-app-1", "name": "S/4HANA", "label": "existing"}
            ],
            "itcomponent": [],
            "provider": [],
        }
    )
    d = decide(item, _catalog(["SAP S/4HANA Cloud"]))
    assert d.action == "link"
    assert d.target_type == "Application"
    assert d.target_id == "fs-app-1"
    assert d.confidence == "HIGH"


def test_medium_confidence_when_create_and_link_with_known_product():
    item = _item(
        suggested={
            "application": [
                {"factsheet_id": None, "name": "S/4HANA Cloud", "label": "create_and_link"}
            ],
            "itcomponent": [],
            "provider": [],
        }
    )
    d = decide(item, _catalog(["SAP S/4HANA Cloud"]))
    assert d.action == "create_and_link"
    assert d.target_type == "Application"
    assert d.target_id is None
    assert d.create_payload is not None
    assert d.create_payload["type"] == "Application"
    assert d.create_payload["name"] == "S/4HANA Cloud"
    assert d.confidence == "MEDIUM"


def test_low_confidence_when_multiple_existing_candidates():
    item = _item(
        suggested={
            "application": [
                {"factsheet_id": "fs-app-1", "name": "A", "label": "existing"},
                {"factsheet_id": "fs-app-2", "name": "B", "label": "existing"},
            ],
            "itcomponent": [],
            "provider": [],
        }
    )
    d = decide(item, _catalog(["SAP S/4HANA Cloud"]))
    assert d.action == "review"
    assert d.confidence == "LOW"


def test_low_confidence_when_unknown_product_and_create_and_link():
    item = _item(
        product="Unknown Product XYZ",
        suggested={
            "application": [
                {"factsheet_id": None, "name": "XYZ", "label": "create_and_link"}
            ],
            "itcomponent": [],
            "provider": [],
        },
    )
    d = decide(item, _catalog(["SAP S/4HANA Cloud"]))
    assert d.action == "review"
    assert d.confidence == "LOW"


def test_already_linked_items_are_skipped_returning_skip_action():
    item = _item(status="linked")
    d = decide(item, _catalog(["SAP S/4HANA Cloud"]))
    assert d.action == "reject"  # skip → treated as no-op reject in orchestrator
    assert d.confidence == "HIGH"
    assert "already linked" in d.reason.lower()


def test_reason_field_is_populated():
    item = _item(
        suggested={
            "application": [
                {"factsheet_id": "fs-app-1", "name": "S/4HANA", "label": "existing"}
            ],
            "itcomponent": [],
            "provider": [],
        }
    )
    d = decide(item, _catalog(["SAP S/4HANA Cloud"]))
    assert d.reason  # non-empty
    assert isinstance(d, MatchDecision)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sap_discovery_matcher.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement matcher**

Content of `pipeline/sap_discovery/matcher.py`:

```python
"""pipeline.sap_discovery.matcher — pure decision logic for the inbox.

Consumes a DiscoveryItem plus a lookup catalog (dict[product_name -> metadata]) and
produces a MatchDecision. No I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pipeline.sap_discovery.client import DiscoveryItem

Action = Literal["link", "create_and_link", "reject", "review"]
TargetType = Literal["Application", "ITComponent", "Provider"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


@dataclass
class MatchDecision:
    item_id: str
    action: Action
    target_type: TargetType | None
    target_id: str | None
    create_payload: dict | None
    confidence: Confidence
    reason: str


_TARGET_ORDER: list[tuple[str, TargetType]] = [
    ("application", "Application"),
    ("itcomponent", "ITComponent"),
    ("provider", "Provider"),
]


def _first_target_with_candidates(item: DiscoveryItem) -> tuple[TargetType, list[dict]] | None:
    for key, target_type in _TARGET_ORDER:
        entries = item.suggested_links.get(key) or []
        if entries:
            return target_type, entries
    return None


def decide(item: DiscoveryItem, catalog: dict) -> MatchDecision:
    if item.status == "linked":
        return MatchDecision(
            item_id=item.id,
            action="reject",
            target_type=None,
            target_id=None,
            create_payload=None,
            confidence="HIGH",
            reason="Item already linked by LeanIX autolinking",
        )

    hit = _first_target_with_candidates(item)
    if hit is None:
        return MatchDecision(
            item_id=item.id,
            action="review",
            target_type=None,
            target_id=None,
            create_payload=None,
            confidence="LOW",
            reason="No suggested links from LeanIX",
        )

    target_type, entries = hit
    existing = [e for e in entries if e.get("label") == "existing"]
    creates = [e for e in entries if e.get("label") == "create_and_link"]

    if len(existing) == 1:
        return MatchDecision(
            item_id=item.id,
            action="link",
            target_type=target_type,
            target_id=existing[0]["factsheet_id"],
            create_payload=None,
            confidence="HIGH",
            reason=f"Single existing {target_type} match: {existing[0]['name']}",
        )

    if len(existing) > 1:
        return MatchDecision(
            item_id=item.id,
            action="review",
            target_type=target_type,
            target_id=None,
            create_payload=None,
            confidence="LOW",
            reason=f"{len(existing)} candidate {target_type} fact sheets — manual review",
        )

    if creates and item.product in catalog:
        create = creates[0]
        return MatchDecision(
            item_id=item.id,
            action="create_and_link",
            target_type=target_type,
            target_id=None,
            create_payload={
                "type": target_type,
                "name": create.get("name") or item.product,
                "product": item.product,
                "classification": item.classification,
            },
            confidence="MEDIUM",
            reason=f"Create & Link {target_type} for known product '{item.product}'",
        )

    return MatchDecision(
        item_id=item.id,
        action="review",
        target_type=target_type,
        target_id=None,
        create_payload=None,
        confidence="LOW",
        reason=f"Ambiguous or unknown product '{item.product}' — manual review",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sap_discovery_matcher.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/sap_discovery/matcher.py tests/test_sap_discovery_matcher.py
git commit -m "feat(sap-discovery): matcher.decide pure heuristics + MatchDecision"
```

---

## Task 7: Orchestrator.start_integration + poll_status

**Files:**
- Create: `pipeline/sap_discovery/orchestrator.py`
- Create: `tests/test_sap_discovery_orchestrator.py`

- [ ] **Step 1: Write failing test**

Content of `tests/test_sap_discovery_orchestrator.py`:

```python
"""Tests for pipeline.sap_discovery.orchestrator — two-phase flow."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline.sap_discovery import orchestrator
from pipeline.sap_discovery.client import DiscoveryItem


def _session_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sap_discovery"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_start_integration_persists_integration_json_and_returns_state(tmp_path):
    fake_client = MagicMock()
    fake_client.create_integration.return_value = {"id": "int-42", "status": "PROVISIONING"}
    fake_client.discover_origin.return_value = "sap-extension"
    fake_client.set_autolinking.return_value = None

    state = orchestrator.start_integration(
        session_dir=_session_dir(tmp_path),
        client=fake_client,
        crm_id="0001234567",
        enable_autolinking=True,
    )

    assert state["integration_id"] == "int-42"
    assert state["crm_id"] == "0001234567"
    assert state["origin"] == "sap-extension"
    assert state["autolinking_enabled"] is True
    assert state["status"] == "pending"

    persisted = json.loads((_session_dir(tmp_path) / "integration.json").read_text())
    assert persisted == state

    fake_client.create_integration.assert_called_once_with(crm_id="0001234567")
    fake_client.set_autolinking.assert_called_once_with(origin="sap-extension", enabled=True)


def test_start_integration_without_autolinking(tmp_path):
    fake_client = MagicMock()
    fake_client.create_integration.return_value = {"id": "int-43"}
    fake_client.discover_origin.return_value = "sap-extension"

    orchestrator.start_integration(
        session_dir=_session_dir(tmp_path),
        client=fake_client,
        crm_id="0001234567",
        enable_autolinking=False,
    )

    fake_client.set_autolinking.assert_not_called()


def test_poll_status_ready_when_inbox_has_items(tmp_path):
    session_dir = _session_dir(tmp_path)
    (session_dir / "integration.json").write_text(
        json.dumps({"integration_id": "int-42", "origin": "sap-extension"})
    )

    fake_client = MagicMock()
    fake_client.list_inbox.return_value = [
        DiscoveryItem(
            id="d1", display_name="x", classification="SaaS_ERP",
            product="p", system_role=None, status="action_needed",
            suggested_links={"application": [], "itcomponent": [], "provider": []},
        )
    ]

    result = orchestrator.poll_status(session_dir=session_dir, client=fake_client)
    assert result["status"] == "ready"
    assert result["inbox_count"] >= 1


def test_poll_status_pending_when_inbox_empty(tmp_path):
    session_dir = _session_dir(tmp_path)
    (session_dir / "integration.json").write_text(
        json.dumps({"integration_id": "int-42", "origin": "sap-extension"})
    )
    fake_client = MagicMock()
    fake_client.list_inbox.return_value = []

    result = orchestrator.poll_status(session_dir=session_dir, client=fake_client)
    assert result["status"] == "pending"
    assert result["inbox_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sap_discovery_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement orchestrator start_integration + poll_status**

Content of `pipeline/sap_discovery/orchestrator.py`:

```python
"""pipeline.sap_discovery.orchestrator — two-phase flow (start + poll + process + apply).

Uses:
- Client (injected) for all REST I/O
- pipeline.write.create_factsheet for fact sheet creation
- pipeline.sap_discovery.matcher.decide for pure decision logic

All state persisted under session_dir/ as JSON.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.sap_discovery.client import Client, DiscoveryItem
from pipeline.sap_discovery.matcher import MatchDecision, decide


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def start_integration(
    session_dir: Path,
    client: Client,
    crm_id: str,
    enable_autolinking: bool = True,
) -> dict:
    """Phase 1: create the integration, discover origin, optionally enable autolinking.

    Persists integration.json and returns the state dict.
    """
    integration = client.create_integration(crm_id=crm_id)
    origin = client.discover_origin()

    if enable_autolinking:
        client.set_autolinking(origin=origin, enabled=True)

    state = {
        "integration_id": integration.get("id"),
        "crm_id": crm_id,
        "origin": origin,
        "autolinking_enabled": bool(enable_autolinking),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    _write_json(session_dir / "integration.json", state)
    return state


def poll_status(session_dir: Path, client: Client) -> dict:
    """Phase 1b: check whether inbox has items yet."""
    state = _read_json(session_dir / "integration.json")
    origin = state["origin"]
    items = client.list_inbox(origin=origin)
    action_needed = sum(1 for i in items if i.status == "action_needed")
    review_needed = sum(1 for i in items if i.status == "review_needed")
    ready = len(items) > 0
    return {
        "status": "ready" if ready else "pending",
        "inbox_count": len(items),
        "action_needed": action_needed,
        "review_needed": review_needed,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sap_discovery_orchestrator.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/sap_discovery/orchestrator.py tests/test_sap_discovery_orchestrator.py
git commit -m "feat(sap-discovery): orchestrator.start_integration + poll_status"
```

---

## Task 8: Orchestrator.process_inbox (link + create + review split)

**Files:**
- Modify: `pipeline/sap_discovery/orchestrator.py`
- Modify: `tests/test_sap_discovery_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_sap_discovery_orchestrator.py`:

```python
def test_process_inbox_links_high_confidence_items_and_creates_medium(tmp_path):
    session_dir = _session_dir(tmp_path)
    (session_dir / "integration.json").write_text(
        json.dumps({"integration_id": "int-42", "origin": "sap-extension"})
    )

    fake_client = MagicMock()
    fake_client.list_inbox.return_value = [
        DiscoveryItem(
            id="d-high", display_name="S/4", classification="SaaS_ERP",
            product="SAP S/4HANA Cloud", system_role="PROD", status="action_needed",
            suggested_links={
                "application": [
                    {"factsheet_id": "fs-app-1", "name": "S/4", "label": "existing"}
                ],
                "itcomponent": [], "provider": [],
            },
        ),
        DiscoveryItem(
            id="d-med", display_name="Ariba", classification="SaaS_Product",
            product="SAP Ariba", system_role=None, status="action_needed",
            suggested_links={
                "application": [
                    {"factsheet_id": None, "name": "Ariba", "label": "create_and_link"}
                ],
                "itcomponent": [], "provider": [],
            },
        ),
        DiscoveryItem(
            id="d-low", display_name="Weird", classification="SaaS_Product",
            product="Unknown ZZZ", system_role=None, status="review_needed",
            suggested_links={
                "application": [
                    {"factsheet_id": None, "name": "?", "label": "create_and_link"}
                ],
                "itcomponent": [], "provider": [],
            },
        ),
    ]
    fake_client.bulk_link.return_value = {"applied": ["d-high", "d-med"], "failed": []}

    def _fake_create_fs(payload):
        return {"id": "fs-app-2"}

    log = orchestrator.process_inbox(
        session_dir=session_dir,
        client=fake_client,
        catalog={"SAP S/4HANA Cloud": {}, "SAP Ariba": {}},
        create_factsheet=_fake_create_fs,
    )

    assert log["applied"] == ["d-high", "d-med"]
    assert log["pending_review"] == ["d-low"]
    assert log["failed"] == []

    args, kwargs = fake_client.bulk_link.call_args
    decisions = kwargs["decisions"]
    assert {d["itemId"] for d in decisions} == {"d-high", "d-med"}
    # medium item should have been resolved to the created fact sheet id
    med = next(d for d in decisions if d["itemId"] == "d-med")
    assert med["targetId"] == "fs-app-2"
    assert med["targetType"] == "Application"

    assert (session_dir / "inbox_snapshot.json").exists()
    assert (session_dir / "decisions.json").exists()
    assert (session_dir / "execution_log.json").exists()


def test_process_inbox_records_partial_bulk_link_failures(tmp_path):
    session_dir = _session_dir(tmp_path)
    (session_dir / "integration.json").write_text(
        json.dumps({"integration_id": "int-42", "origin": "sap-extension"})
    )
    fake_client = MagicMock()
    fake_client.list_inbox.return_value = [
        DiscoveryItem(
            id="d1", display_name="x", classification="SaaS_ERP",
            product="SAP S/4HANA Cloud", system_role=None, status="action_needed",
            suggested_links={
                "application": [
                    {"factsheet_id": "fs-app-1", "name": "S/4", "label": "existing"}
                ],
                "itcomponent": [], "provider": [],
            },
        )
    ]
    fake_client.bulk_link.return_value = {
        "applied": [],
        "failed": [{"itemId": "d1", "error": "target not found"}],
    }

    log = orchestrator.process_inbox(
        session_dir=session_dir, client=fake_client,
        catalog={"SAP S/4HANA Cloud": {}}, create_factsheet=lambda p: {"id": "unused"},
    )
    assert log["applied"] == []
    assert log["failed"][0]["itemId"] == "d1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sap_discovery_orchestrator.py -v -k process_inbox`
Expected: FAIL (function does not exist).

- [ ] **Step 3: Implement process_inbox**

Add to `pipeline/sap_discovery/orchestrator.py`:

```python
from dataclasses import asdict


_BULK_CHUNK_SIZE = 50


def process_inbox(
    session_dir: Path,
    client: Client,
    catalog: dict,
    create_factsheet,
) -> dict:
    """Phase 2: pull inbox, decide, execute link/create/reject.

    Args:
        session_dir: session working directory.
        client: pipeline.sap_discovery.client.Client instance.
        catalog: {product_name: metadata} lookup for the matcher.
        create_factsheet: callable(payload_dict) -> {"id": str}. Injected so the
            orchestrator does not import pipeline.write directly (keeps tests
            hermetic and avoids circular imports).

    Returns execution_log dict and persists snapshot/decisions/log.
    """
    state = _read_json(session_dir / "integration.json")
    origin = state["origin"]

    items = client.list_inbox(origin=origin, status="action_needed,review_needed")
    _write_json(
        session_dir / "inbox_snapshot.json",
        [i.raw for i in items],
    )

    decisions: list[MatchDecision] = [decide(i, catalog) for i in items]
    _write_json(session_dir / "decisions.json", [asdict(d) for d in decisions])

    pending_review: list[str] = []
    to_link: list[dict] = []
    to_reject: list[str] = []

    for d in decisions:
        if d.action == "review":
            pending_review.append(d.item_id)
        elif d.action == "reject":
            # includes "already linked" skips — do NOT re-reject those
            if d.reason.lower().startswith("item already linked"):
                continue
            to_reject.append(d.item_id)
        elif d.action == "link":
            to_link.append({
                "itemId": d.item_id,
                "targetType": d.target_type,
                "targetId": d.target_id,
            })
        elif d.action == "create_and_link":
            created = create_factsheet(d.create_payload)
            to_link.append({
                "itemId": d.item_id,
                "targetType": d.target_type,
                "targetId": created["id"],
            })

    applied: list[str] = []
    failed: list[dict] = []

    for chunk_start in range(0, len(to_link), _BULK_CHUNK_SIZE):
        chunk = to_link[chunk_start:chunk_start + _BULK_CHUNK_SIZE]
        resp = client.bulk_link(origin=origin, decisions=chunk)
        applied.extend(resp.get("applied", []))
        failed.extend(resp.get("failed", []))

    if to_reject:
        resp = client.bulk_reject(origin=origin, item_ids=to_reject)
        applied.extend(resp.get("applied", []))
        failed.extend(resp.get("failed", []))

    log = {
        "applied": applied,
        "failed": failed,
        "pending_review": pending_review,
    }
    _write_json(session_dir / "execution_log.json", log)
    return log
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sap_discovery_orchestrator.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/sap_discovery/orchestrator.py tests/test_sap_discovery_orchestrator.py
git commit -m "feat(sap-discovery): orchestrator.process_inbox with chunked bulk_link"
```

---

## Task 9: Orchestrator.apply_review

**Files:**
- Modify: `pipeline/sap_discovery/orchestrator.py`
- Modify: `tests/test_sap_discovery_orchestrator.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_sap_discovery_orchestrator.py`:

```python
def test_apply_review_dispatches_link_and_reject(tmp_path):
    session_dir = _session_dir(tmp_path)
    (session_dir / "integration.json").write_text(
        json.dumps({"integration_id": "int-42", "origin": "sap-extension"})
    )
    (session_dir / "execution_log.json").write_text(
        json.dumps({"applied": [], "failed": [], "pending_review": ["d-a", "d-b"]})
    )

    fake_client = MagicMock()
    fake_client.bulk_link.return_value = {"applied": ["d-a"], "failed": []}
    fake_client.bulk_reject.return_value = {"applied": ["d-b"], "failed": []}

    log = orchestrator.apply_review(
        session_dir=session_dir,
        client=fake_client,
        decisions=[
            {"item_id": "d-a", "action": "link", "target_type": "Application", "target_id": "fs-1"},
            {"item_id": "d-b", "action": "reject"},
        ],
    )
    assert set(log["applied"]) == {"d-a", "d-b"}

    args, kwargs = fake_client.bulk_link.call_args
    assert kwargs["decisions"] == [
        {"itemId": "d-a", "targetType": "Application", "targetId": "fs-1"}
    ]
    fake_client.bulk_reject.assert_called_once_with(origin="sap-extension", item_ids=["d-b"])

    log_persisted = json.loads((session_dir / "execution_log.json").read_text())
    assert set(log_persisted["applied"]) == {"d-a", "d-b"}
    assert log_persisted["pending_review"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sap_discovery_orchestrator.py::test_apply_review_dispatches_link_and_reject -v`
Expected: FAIL (function does not exist).

- [ ] **Step 3: Implement apply_review**

Add to `pipeline/sap_discovery/orchestrator.py`:

```python
def apply_review(session_dir: Path, client: Client, decisions: list[dict]) -> dict:
    """Phase 3: apply human-confirmed decisions from the review report.

    Each decision: {"item_id": str, "action": "link"|"reject", "target_type"?: str, "target_id"?: str}.
    """
    state = _read_json(session_dir / "integration.json")
    origin = state["origin"]

    to_link = [
        {"itemId": d["item_id"], "targetType": d["target_type"], "targetId": d["target_id"]}
        for d in decisions if d["action"] == "link"
    ]
    to_reject = [d["item_id"] for d in decisions if d["action"] == "reject"]

    applied: list[str] = []
    failed: list[dict] = []

    if to_link:
        resp = client.bulk_link(origin=origin, decisions=to_link)
        applied.extend(resp.get("applied", []))
        failed.extend(resp.get("failed", []))

    if to_reject:
        resp = client.bulk_reject(origin=origin, item_ids=to_reject)
        applied.extend(resp.get("applied", []))
        failed.extend(resp.get("failed", []))

    log_path = session_dir / "execution_log.json"
    existing = _read_json(log_path) if log_path.exists() else {"applied": [], "failed": [], "pending_review": []}
    existing["applied"] = list(set(existing.get("applied", [])) | set(applied))
    existing["failed"] = existing.get("failed", []) + failed
    processed_ids = {d["item_id"] for d in decisions}
    existing["pending_review"] = [
        i for i in existing.get("pending_review", []) if i not in processed_ids
    ]
    _write_json(log_path, existing)
    return existing
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sap_discovery_orchestrator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/sap_discovery/orchestrator.py tests/test_sap_discovery_orchestrator.py
git commit -m "feat(sap-discovery): orchestrator.apply_review with idempotent log merge"
```

---

## Task 10: Report renderer

**Files:**
- Create: `pipeline/sap_discovery/report.py`
- Create: `tests/test_sap_discovery_report.py`

- [ ] **Step 1: Write failing tests**

Content of `tests/test_sap_discovery_report.py`:

```python
"""Tests for pipeline.sap_discovery.report."""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.sap_discovery import report


def _seed(session_dir: Path) -> None:
    (session_dir / "integration.json").write_text(json.dumps({
        "integration_id": "int-42", "crm_id": "0001234567",
        "origin": "sap-extension", "autolinking_enabled": True,
        "status": "pending",
    }))
    (session_dir / "decisions.json").write_text(json.dumps([
        {
            "item_id": "d-high", "action": "link",
            "target_type": "Application", "target_id": "fs-app-1",
            "create_payload": None, "confidence": "HIGH",
            "reason": "Single existing Application match: S/4",
        },
        {
            "item_id": "d-low", "action": "review",
            "target_type": "Application", "target_id": None,
            "create_payload": None, "confidence": "LOW",
            "reason": "Ambiguous or unknown product",
        },
    ]))
    (session_dir / "execution_log.json").write_text(json.dumps({
        "applied": ["d-high"], "failed": [], "pending_review": ["d-low"],
    }))


def test_build_writes_report_html_and_json(tmp_path):
    session_dir = tmp_path / "sap_discovery"
    session_dir.mkdir()
    _seed(session_dir)

    out = report.build(session_dir=session_dir)
    assert out["html"].exists()
    assert out["json"].exists()

    data = json.loads(out["json"].read_text())
    assert data["summary"]["applied"] == 1
    assert data["summary"]["pending_review"] == 1
    assert len(data["applied"]) == 1
    assert len(data["pending_review"]) == 1
    assert data["applied"][0]["item_id"] == "d-high"
    assert data["pending_review"][0]["item_id"] == "d-low"


def test_build_html_contains_pending_review_dropdown(tmp_path):
    session_dir = tmp_path / "sap_discovery"
    session_dir.mkdir()
    _seed(session_dir)

    out = report.build(session_dir=session_dir)
    html = out["html"].read_text()
    assert "d-low" in html
    assert "Apply selections" in html
    # dropdown offers at least link + reject
    assert "reject" in html.lower()
    assert "link" in html.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sap_discovery_report.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement report.build**

Content of `pipeline/sap_discovery/report.py`:

```python
"""pipeline.sap_discovery.report — HTML + JSON report renderer.

Reads decisions.json + execution_log.json + integration.json from session_dir
and writes report.html + report.json in the same directory.
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path


def _load(path: Path) -> object:
    return json.loads(path.read_text()) if path.exists() else None


def _row(item_id: str, extra: dict) -> str:
    return (
        f"<tr><td>{escape(item_id)}</td>"
        f"<td>{escape(extra.get('confidence', ''))}</td>"
        f"<td>{escape(extra.get('reason', ''))}</td></tr>"
    )


def _pending_card(decision: dict) -> str:
    item_id = decision["item_id"]
    return (
        "<div class='card'>"
        f"<h3>{escape(item_id)}</h3>"
        f"<p>{escape(decision.get('reason', ''))}</p>"
        f"<select name='action-{escape(item_id)}'>"
        "<option value='link'>Link to existing fact sheet</option>"
        "<option value='reject'>Reject</option>"
        "</select>"
        f"<input name='target-{escape(item_id)}' placeholder='Target fact sheet id' />"
        "</div>"
    )


def build(session_dir: Path) -> dict:
    integration = _load(session_dir / "integration.json") or {}
    decisions = _load(session_dir / "decisions.json") or []
    log = _load(session_dir / "execution_log.json") or {
        "applied": [], "failed": [], "pending_review": [],
    }

    decisions_by_id = {d["item_id"]: d for d in decisions}
    applied = [decisions_by_id.get(i, {"item_id": i}) for i in log.get("applied", [])]
    pending_review = [
        decisions_by_id.get(i, {"item_id": i}) for i in log.get("pending_review", [])
    ]
    failed = log.get("failed", [])

    summary = {
        "applied": len(applied),
        "pending_review": len(pending_review),
        "failed": len(failed),
        "integration_id": integration.get("integration_id"),
        "crm_id": integration.get("crm_id"),
    }

    json_out = {
        "summary": summary,
        "applied": applied,
        "pending_review": pending_review,
        "failed": failed,
    }
    json_path = session_dir / "report.json"
    json_path.write_text(json.dumps(json_out, indent=2, default=str))

    html_parts: list[str] = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>SAP Internal Discovery — Review</title>",
        "<style>body{font-family:system-ui;margin:2em;} table{border-collapse:collapse;}"
        "td,th{border:1px solid #ddd;padding:6px 10px;} .card{border:1px solid #ccc;"
        "padding:12px;margin:8px 0;border-radius:6px;}</style></head><body>",
        f"<h1>SAP Internal Discovery — Session</h1>",
        f"<p>Integration <code>{escape(str(summary['integration_id']))}</code> · "
        f"CRM <code>{escape(str(summary['crm_id']))}</code></p>",
        f"<p><b>Applied:</b> {summary['applied']} · "
        f"<b>Pending review:</b> {summary['pending_review']} · "
        f"<b>Failed:</b> {summary['failed']}</p>",
        "<h2>Applied</h2><table><tr><th>Item</th><th>Confidence</th><th>Reason</th></tr>",
    ]
    for d in applied:
        html_parts.append(_row(d.get("item_id", ""), d))
    html_parts.append("</table>")

    html_parts.append("<h2>Pending review</h2><form method='post' action='./apply-review'>")
    for d in pending_review:
        html_parts.append(_pending_card(d))
    html_parts.append("<button type='submit'>Apply selections</button></form>")
    html_parts.append("</body></html>")

    html_path = session_dir / "report.html"
    html_path.write_text("".join(html_parts))
    return {"html": html_path, "json": json_path}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sap_discovery_report.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/sap_discovery/report.py tests/test_sap_discovery_report.py
git commit -m "feat(sap-discovery): report.build HTML + JSON with confirmable review"
```

---

## Task 11: Wire orchestrator into `pipeline.write` bridge

**Files:**
- Modify: `pipeline/sap_discovery/__init__.py`

- [ ] **Step 1: Verify all imports resolve**

Run: `python -c "import pipeline.sap_discovery; print(pipeline.sap_discovery.__all__)"`
Expected: prints the `__all__` list without ImportError.

- [ ] **Step 2: Add a bridge helper that binds pipeline.write.create_factsheet**

Modify `pipeline/sap_discovery/__init__.py`, add at the bottom:

```python
def make_create_factsheet_bridge():
    """Return a callable(payload_dict) -> {"id": str} that delegates to pipeline.write.

    Kept as a lazy factory to avoid importing pipeline.write at package load time.
    """
    from pipeline import write as _write

    def _bridge(payload: dict) -> dict:
        fs = _write.create_factsheet(  # type: ignore[attr-defined]
            type_=payload["type"],
            name=payload["name"],
            attributes={"product": payload.get("product")},
        )
        return {"id": fs["id"]}

    return _bridge


__all__ = __all__ + ["make_create_factsheet_bridge"]
```

**Note:** verify the actual signature of `pipeline.write.create_factsheet` first (grep the module). If the signature differs, adapt the wrapper — this bridge is the only place that touches `write.py` from the new package.

- [ ] **Step 3: Verify import still works**

Run: `python -c "import pipeline.sap_discovery; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add pipeline/sap_discovery/__init__.py
git commit -m "feat(sap-discovery): make_create_factsheet_bridge helper for pipeline.write"
```

---

## Task 12: Wizard endpoint — POST /baseline/from-sap-discovery

**Files:**
- Modify: `archimedes_wizard.py`
- Create: `tests/test_wizard_from_sap_discovery.py`

- [ ] **Step 1: Write failing test**

Content of `tests/test_wizard_from_sap_discovery.py`:

```python
"""Tests for /baseline/from-sap-discovery and the SAP Discovery routes."""
from __future__ import annotations

import json
import uuid as _uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from archimedes_wizard import app, _sessions, OUTPUT_DIR


def _make_session(client_name: str = "Acme") -> tuple[str, Path]:
    session_id = str(_uuid.uuid4())
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    _sessions[session_id] = {
        "client_name": client_name,
        "output_dir":  session_dir,
        "out_baseline": None,
        "out_target":   None,
        "workspace": {"base_url": "https://demo.leanix.net", "api_token": "tok"},
    }
    return session_id, session_dir


def test_from_sap_discovery_404_when_session_missing():
    tc = TestClient(app)
    r = tc.post("/api/session/missing/baseline/from-sap-discovery",
                json={"crm_id": "0001234567"})
    assert r.status_code == 404


def test_from_sap_discovery_starts_integration_and_returns_pending():
    sid, session_dir = _make_session()
    tc = TestClient(app)

    fake_state = {
        "integration_id": "int-42",
        "crm_id": "0001234567",
        "origin": "sap-extension",
        "autolinking_enabled": True,
        "status": "pending",
        "created_at": "2026-07-16T00:00:00Z",
    }

    with patch("archimedes_wizard.sap_discovery") as sd_mod:
        sd_mod.Client.return_value = MagicMock()
        sd_mod.start_integration.return_value = fake_state

        r = tc.post(f"/api/session/{sid}/baseline/from-sap-discovery",
                    json={"crm_id": "0001234567"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["integration_id"] == "int-42"
    assert body["eta_seconds"] == 600
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wizard_from_sap_discovery.py -v`
Expected: FAIL (route not registered).

- [ ] **Step 3: Add the endpoint to archimedes_wizard.py**

Add near the top of `archimedes_wizard.py`, in the imports block:

```python
from pipeline import sap_discovery
```

Add near the other `/baseline/*` routes (after `register_baseline` route, roughly line 555):

```python
def _sap_discovery_dir(session_id: str) -> Path:
    return OUTPUT_DIR / session_id / "sap_discovery"


def _sap_discovery_client(session_id: str) -> sap_discovery.Client:
    session = _sessions[session_id]
    ws = session["workspace"]
    return sap_discovery.Client(base_url=ws["base_url"], api_token=ws["api_token"])


@app.post("/api/session/{session_id}/baseline/from-sap-discovery")
async def from_sap_discovery(session_id: str, body: dict):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    crm_id = (body or {}).get("crm_id", "").strip()
    if not crm_id:
        raise HTTPException(status_code=400, detail="crm_id is required")
    enable_autolinking = bool((body or {}).get("enable_autolinking", True))

    session_dir = _sap_discovery_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    client = _sap_discovery_client(session_id)
    state = sap_discovery.start_integration(
        session_dir=session_dir,
        client=client,
        crm_id=crm_id,
        enable_autolinking=enable_autolinking,
    )
    return {**state, "eta_seconds": 600}
```

Note: verify the exact import name used elsewhere for `HTTPException` (should already be imported from `fastapi`). If not, add `from fastapi import HTTPException` at the top.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_wizard_from_sap_discovery.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add archimedes_wizard.py tests/test_wizard_from_sap_discovery.py
git commit -m "feat(wizard): POST /baseline/from-sap-discovery to start integration"
```

---

## Task 13: Wizard endpoint — GET /baseline/sap-discovery/status

**Files:**
- Modify: `archimedes_wizard.py`
- Modify: `tests/test_wizard_from_sap_discovery.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_wizard_from_sap_discovery.py`:

```python
def test_sap_discovery_status_returns_orchestrator_result():
    sid, session_dir = _make_session()
    (session_dir / "sap_discovery").mkdir(parents=True, exist_ok=True)
    (session_dir / "sap_discovery" / "integration.json").write_text(
        json.dumps({"integration_id": "int-42", "origin": "sap-extension"})
    )
    tc = TestClient(app)

    with patch("archimedes_wizard.sap_discovery") as sd_mod:
        sd_mod.Client.return_value = MagicMock()
        sd_mod.poll_status.return_value = {
            "status": "ready", "inbox_count": 5,
            "action_needed": 4, "review_needed": 1,
        }
        r = tc.get(f"/api/session/{sid}/baseline/sap-discovery/status")

    assert r.status_code == 200
    assert r.json()["status"] == "ready"
    assert r.json()["inbox_count"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wizard_from_sap_discovery.py::test_sap_discovery_status_returns_orchestrator_result -v`
Expected: FAIL (route missing).

- [ ] **Step 3: Add the endpoint**

Add to `archimedes_wizard.py`:

```python
@app.get("/api/session/{session_id}/baseline/sap-discovery/status")
async def sap_discovery_status(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    client = _sap_discovery_client(session_id)
    return sap_discovery.poll_status(
        session_dir=_sap_discovery_dir(session_id),
        client=client,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_wizard_from_sap_discovery.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add archimedes_wizard.py tests/test_wizard_from_sap_discovery.py
git commit -m "feat(wizard): GET /baseline/sap-discovery/status polling endpoint"
```

---

## Task 14: Wizard endpoints — process + apply-review + report

**Files:**
- Modify: `archimedes_wizard.py`
- Modify: `tests/test_wizard_from_sap_discovery.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_wizard_from_sap_discovery.py`:

```python
def test_sap_discovery_process_runs_orchestrator_and_returns_summary():
    sid, session_dir = _make_session()
    (session_dir / "sap_discovery").mkdir(parents=True, exist_ok=True)
    (session_dir / "sap_discovery" / "integration.json").write_text(
        json.dumps({"integration_id": "int-42", "origin": "sap-extension"})
    )
    tc = TestClient(app)

    with patch("archimedes_wizard.sap_discovery") as sd_mod:
        sd_mod.Client.return_value = MagicMock()
        sd_mod.make_create_factsheet_bridge.return_value = lambda p: {"id": "fs-x"}
        sd_mod.process_inbox.return_value = {
            "applied": ["d-high"], "failed": [], "pending_review": ["d-low"],
        }
        sd_mod.build.return_value = {
            "html": session_dir / "sap_discovery" / "report.html",
            "json": session_dir / "sap_discovery" / "report.json",
        }
        r = tc.post(f"/api/session/{sid}/baseline/sap-discovery/process",
                    json={"catalog": {"SAP S/4HANA Cloud": {}}})

    body = r.json()
    assert body["applied"] == 1
    assert body["pending_review"] == 1
    assert body["report_url"].endswith("/sap-discovery/report")


def test_sap_discovery_apply_review_forwards_decisions():
    sid, session_dir = _make_session()
    (session_dir / "sap_discovery").mkdir(parents=True, exist_ok=True)
    (session_dir / "sap_discovery" / "integration.json").write_text(
        json.dumps({"integration_id": "int-42", "origin": "sap-extension"})
    )
    tc = TestClient(app)

    with patch("archimedes_wizard.sap_discovery") as sd_mod:
        sd_mod.Client.return_value = MagicMock()
        sd_mod.apply_review.return_value = {
            "applied": ["d-low"], "failed": [], "pending_review": [],
        }
        sd_mod.build.return_value = {
            "html": session_dir / "sap_discovery" / "report.html",
            "json": session_dir / "sap_discovery" / "report.json",
        }
        decisions = [
            {"item_id": "d-low", "action": "link",
             "target_type": "Application", "target_id": "fs-1"},
        ]
        r = tc.post(
            f"/api/session/{sid}/baseline/sap-discovery/apply-review",
            json={"decisions": decisions},
        )

    assert r.status_code == 200
    call = sd_mod.apply_review.call_args
    assert call.kwargs["decisions"] == decisions
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wizard_from_sap_discovery.py -v -k "process or apply_review"`
Expected: FAIL (routes missing).

- [ ] **Step 3: Add the endpoints**

Add to `archimedes_wizard.py`:

```python
@app.post("/api/session/{session_id}/baseline/sap-discovery/process")
async def sap_discovery_process(session_id: str, body: dict):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    catalog = (body or {}).get("catalog", {})
    session_dir = _sap_discovery_dir(session_id)
    client = _sap_discovery_client(session_id)
    create_fs = sap_discovery.make_create_factsheet_bridge()

    log = sap_discovery.process_inbox(
        session_dir=session_dir,
        client=client,
        catalog=catalog,
        create_factsheet=create_fs,
    )
    sap_discovery.build(session_dir=session_dir)
    return {
        "applied": len(log.get("applied", [])),
        "failed": len(log.get("failed", [])),
        "pending_review": len(log.get("pending_review", [])),
        "report_url": f"/api/session/{session_id}/baseline/sap-discovery/report",
    }


@app.post("/api/session/{session_id}/baseline/sap-discovery/apply-review")
async def sap_discovery_apply_review(session_id: str, body: dict):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    decisions = (body or {}).get("decisions") or []
    session_dir = _sap_discovery_dir(session_id)
    client = _sap_discovery_client(session_id)
    log = sap_discovery.apply_review(
        session_dir=session_dir, client=client, decisions=decisions
    )
    sap_discovery.build(session_dir=session_dir)
    return {
        "applied": len(log.get("applied", [])),
        "failed": len(log.get("failed", [])),
        "pending_review": len(log.get("pending_review", [])),
    }


@app.get("/api/session/{session_id}/baseline/sap-discovery/report",
         response_class=HTMLResponse)
async def sap_discovery_report(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    path = _sap_discovery_dir(session_id) / "report.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not generated yet")
    return HTMLResponse(path.read_text())
```

Note: verify that `HTMLResponse` is already imported at the top of `archimedes_wizard.py` (it is used by the `/` and `/pro` routes). If not, add `from fastapi.responses import HTMLResponse`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wizard_from_sap_discovery.py -v`
Expected: PASS (all 5 tests).

- [ ] **Step 5: Commit**

```bash
git add archimedes_wizard.py tests/test_wizard_from_sap_discovery.py
git commit -m "feat(wizard): process + apply-review + report endpoints for SAP Discovery"
```

---

## Task 15: Wizard UI — SAP Internal Discovery tab in Step 2

**Files:**
- Modify: `archimedes_wizard.html`

- [ ] **Step 1: Read current Step 2 markup**

Run: `grep -n "one360\|ONE360\|from-one360" archimedes_wizard.html | head -20`
Note the tab/section IDs used by the existing ONE360 flow — the new tab must mirror them.

- [ ] **Step 2: Add SAP Internal Discovery tab**

Locate the Step 2 tab bar (search for `one360` tab). Add a new tab labelled **SAP Internal Discovery** with `data-tab="sap-discovery"`. Add a panel:

```html
<div class="tab-panel" data-panel="sap-discovery" hidden>
  <h3>SAP Internal Discovery</h3>
  <p>Configure the LeanIX Internal SAP Landscape Data integration for an SAP customer.</p>
  <label>CRM ID / ERP ID
    <input type="text" id="sap-discovery-crm-id" placeholder="0001234567" />
  </label>
  <label>
    <input type="checkbox" id="sap-discovery-autolinking" checked />
    Enable autolinking
  </label>
  <button id="sap-discovery-start">Start integration</button>
  <button id="sap-discovery-check" disabled>Check inbox</button>
  <button id="sap-discovery-process" disabled>Process inbox</button>
  <a id="sap-discovery-report-link" href="#" hidden target="_blank">Open review report</a>
  <pre id="sap-discovery-log" style="max-height:200px;overflow:auto;"></pre>
</div>
```

Add the JS handlers (inline `<script>` near the existing ONE360 handlers, or in the same event-delegation block):

```javascript
(function () {
  const sid = () => window.__ARCHI_SESSION_ID__;
  const log = (m) => {
    const el = document.getElementById('sap-discovery-log');
    el.textContent += m + '\n';
  };
  document.getElementById('sap-discovery-start').addEventListener('click', async () => {
    const crm = document.getElementById('sap-discovery-crm-id').value.trim();
    const auto = document.getElementById('sap-discovery-autolinking').checked;
    if (!crm) { alert('CRM ID required'); return; }
    log('Starting integration…');
    const r = await fetch(`/api/session/${sid()}/baseline/from-sap-discovery`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ crm_id: crm, enable_autolinking: auto }),
    });
    const body = await r.json();
    log('Integration: ' + JSON.stringify(body));
    document.getElementById('sap-discovery-check').disabled = false;
  });
  document.getElementById('sap-discovery-check').addEventListener('click', async () => {
    const r = await fetch(`/api/session/${sid()}/baseline/sap-discovery/status`);
    const body = await r.json();
    log('Status: ' + JSON.stringify(body));
    if (body.status === 'ready') {
      document.getElementById('sap-discovery-process').disabled = false;
    }
  });
  document.getElementById('sap-discovery-process').addEventListener('click', async () => {
    log('Processing inbox…');
    const r = await fetch(`/api/session/${sid()}/baseline/sap-discovery/process`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ catalog: window.__ARCHI_CATALOG__ || {} }),
    });
    const body = await r.json();
    log('Process result: ' + JSON.stringify(body));
    const a = document.getElementById('sap-discovery-report-link');
    a.href = body.report_url;
    a.hidden = false;
  });
})();
```

- [ ] **Step 3: Manual smoke test**

Run: `python archimedes_wizard.py` and open `http://localhost:<port>/pro`. In Step 2 verify:
- Tab **SAP Internal Discovery** appears next to **ONE360**.
- Entering CRM ID + clicking **Start integration** hits the backend (check terminal logs for `POST /api/session/.../baseline/from-sap-discovery`). If workspace is unreachable the call will 4xx/5xx — that is expected, the UI wiring is what we validate here.

- [ ] **Step 4: Commit**

```bash
git add archimedes_wizard.html
git commit -m "feat(wizard-ui): SAP Internal Discovery tab in Step 2"
```

---

## Task 16: Runtime validations — origin discovery + v1 fallback (deferred integration test)

**Files:**
- Modify: `pipeline/sap_discovery/client.py`
- Modify: `tests/test_sap_discovery_client.py`

- [ ] **Step 1: Add v1 fallback to bulk_link / bulk_reject / list_inbox**

Test first — append to `tests/test_sap_discovery_client.py`:

```python
def test_list_inbox_falls_back_to_v1_when_v2_404(monkeypatch):
    """If v2 returns 404, client should retry against discovery-linking v1."""
    client = _mk_client()

    call_log: list[str] = []

    def _fake_get(url, **_kw):
        call_log.append(url)
        m = MagicMock()
        if "/v2/" in url:
            m.status_code = 404
            import requests as _rq
            m.raise_for_status.side_effect = _rq.HTTPError("404")
        else:
            m.status_code = 200
            m.json.return_value = {"items": []}
            m.raise_for_status.return_value = None
        return m

    with patch("pipeline.sap_discovery.client.get_bearer", return_value="BEARER"), \
         patch("pipeline.sap_discovery.client.requests.get", side_effect=_fake_get):
        items = client.list_inbox(origin="sap-extension")

    assert items == []
    assert any("/v2/" in u for u in call_log)
    assert any("/v1/" in u for u in call_log)
```

Run: `pytest tests/test_sap_discovery_client.py::test_list_inbox_falls_back_to_v1_when_v2_404 -v`
Expected: FAIL.

- [ ] **Step 2: Implement fallback**

Modify `list_inbox` in `pipeline/sap_discovery/client.py`:

```python
    def list_inbox(self, origin: str, status: str | None = None) -> list[DiscoveryItem]:
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        v2_url = f"{self.base_url}/services/discovery-linking/v2/{origin}/discoveryItems"
        resp = requests.get(v2_url, params=params, headers=self._auth_header(), timeout=60)
        if resp.status_code == 404:
            v1_url = f"{self.base_url}/services/discovery-linking/v1/discovery-items"
            resp = requests.get(v1_url, params=params, headers=self._auth_header(), timeout=60)
        resp.raise_for_status()
        data = resp.json() or {}
        return [DiscoveryItem.from_api(x) for x in data.get("items", [])]
```

Run: `pytest tests/test_sap_discovery_client.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add pipeline/sap_discovery/client.py tests/test_sap_discovery_client.py
git commit -m "feat(sap-discovery): v1 fallback for list_inbox when v2 Beta not available"
```

- [ ] **Step 4: Deferred smoke test note**

Add a note at the top of `docs/superpowers/specs/2026-07-16-sap-internal-discovery-design.md`:

```markdown
> **Implementation status (as of Task 16 completion):** unit tests green.
> Runtime validation pending against a live demo workspace with
> Internal SAP Landscape Data enabled. Blockers to close v1:
> 1. Verify `{origin}` candidate list; adjust `Client._ORIGIN_CANDIDATES` if needed.
> 2. Verify body schema of `POST /discovery-sap-extension/v1/integrations`
>    against the workspace's `/v3/api-docs`.
> 3. Verify v2 Beta enabled in workspace, else confirm v1 fallback covers bulk_link/reject as well.
```

Commit:
```bash
git add docs/superpowers/specs/2026-07-16-sap-internal-discovery-design.md
git commit -m "docs(sap-discovery): note deferred runtime validations for v1 cutover"
```

---

## Self-review

**Spec coverage:**
- ✅ Package layout (client/matcher/orchestrator/report) — Tasks 1–10.
- ✅ Two-phase async flow — Tasks 7 (start + poll), 8 (process), 9 (apply_review).
- ✅ Hybrid autolinking + confirmable review — Tasks 4 (set_autolinking), 8 (pending_review split), 9 (apply_review), 10 (report with dropdowns).
- ✅ Application + IT Component + Provider coverage — matcher iterates `_TARGET_ORDER` covering all three (Task 6).
- ✅ Create fact sheets when missing — Tasks 8 (create_and_link path) + 11 (write.py bridge).
- ✅ Manual CRM ID input — Task 12 request body.
- ✅ Wizard integration parallel to ONE360 — Task 15.
- ✅ Error handling: 409 conflict — Task 3 test; partial bulk failures — Task 8 test; v2→v1 fallback — Task 16.
- ✅ Runtime validation notes — Task 16 step 4.

**Placeholders:** none. Every step contains full code, exact paths, and expected pytest output.

**Type consistency:**
- `DiscoveryItem.from_api` used identically in Tasks 2, 4, 7, 8, 16.
- `MatchDecision` dataclass field names (`item_id`, `action`, `target_type`, `target_id`, `create_payload`, `confidence`, `reason`) consistent between definition (Task 6) and orchestrator consumption (Task 8) and report consumption (Task 10).
- Client methods (`create_integration`, `set_autolinking`, `discover_origin`, `list_inbox`, `bulk_link`, `bulk_reject`) named identically across Tasks 3, 4, 5 and consumed with the same signatures in Task 7, 8, 9.
- Wizard route paths (`/baseline/from-sap-discovery`, `/baseline/sap-discovery/status`, `/baseline/sap-discovery/process`, `/baseline/sap-discovery/apply-review`, `/baseline/sap-discovery/report`) match between backend (Tasks 12–14) and frontend (Task 15).

Plan is self-consistent and covers the spec.
