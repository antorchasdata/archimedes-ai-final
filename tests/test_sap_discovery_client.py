"""Unit tests for pipeline.sap_discovery.client (rewired to real discovery-sap API)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.sap_discovery.client import (
    Client,
    DiscoveryDetail,
    DiscoveryItem,
    IntegrationNotFoundError,
    Node,
    Relation,
    Suggestion,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _mock_response(status_code: int = 200, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.raise_for_status = MagicMock()
    r.json = MagicMock(return_value=json_data if json_data is not None else {})
    return r


@pytest.fixture
def client():
    return Client("https://demo.leanix.net/", "LXT_TESTTOKEN")


@pytest.fixture(autouse=True)
def _mock_bearer():
    with patch("pipeline.sap_discovery.client.get_bearer", return_value="BEARER123"):
        yield


# ---------------------------------------------------------------------------
# 1. find_active_slis_integration — happy path
# ---------------------------------------------------------------------------
def test_find_active_slis_integration_returns_first(client):
    payload = _load("sap_integration_list.json")
    with patch("pipeline.sap_discovery.client.requests.get") as mget:
        mget.return_value = _mock_response(200, json_data=payload)

        result = client.find_active_slis_integration()

    assert result["service"] == "SLIS"
    assert result["active"] is True
    assert result["name"] == "Internal SAP Landscape Data"

    # URL: trailing slash on base_url was stripped in constructor
    called_url = mget.call_args.args[0] if mget.call_args.args else mget.call_args.kwargs.get("url")
    assert called_url == "https://demo.leanix.net/services/discovery-sap/v1/integrations"

    # Headers: Bearer + JSON content-type
    headers = mget.call_args.kwargs.get("headers", {})
    assert headers.get("Authorization", "").startswith("Bearer ")
    assert headers.get("Content-Type") == "application/json"


# ---------------------------------------------------------------------------
# 2. find_active_slis_integration — empty list raises
# ---------------------------------------------------------------------------
def test_find_active_slis_integration_raises_when_none(client):
    with patch("pipeline.sap_discovery.client.requests.get") as mget:
        mget.return_value = _mock_response(200, json_data=[])

        with pytest.raises(IntegrationNotFoundError) as excinfo:
            client.find_active_slis_integration()

    msg = str(excinfo.value)
    assert "Internal SAP Landscape Data" in msg or "SLIS" in msg


# ---------------------------------------------------------------------------
# 3. find_active_slis_integration — ignores inactive / wrong-service entries
# ---------------------------------------------------------------------------
def test_find_active_slis_integration_ignores_inactive(client):
    payload = [
        {"id": "a", "service": "SLIS", "active": False},
        {"id": "b", "service": "OTHER", "active": True},
    ]
    with patch("pipeline.sap_discovery.client.requests.get") as mget:
        mget.return_value = _mock_response(200, json_data=payload)

        with pytest.raises(IntegrationNotFoundError):
            client.find_active_slis_integration()


# ---------------------------------------------------------------------------
# 4. list_inbox — unwraps {"data":{"discoveryItems":[...]}} envelope
# ---------------------------------------------------------------------------
def test_list_inbox_unwraps_data_envelope(client):
    payload = _load("sap_inbox_list.json")
    with patch("pipeline.sap_discovery.client.requests.get") as mget:
        mget.return_value = _mock_response(200, json_data=payload)

        items = client.list_inbox()

    assert isinstance(items, list)
    assert len(items) == 3
    assert all(isinstance(i, DiscoveryItem) for i in items)
    first = items[0]
    assert first.linking_status == "not_linked"
    assert len(first.nodes) > 0


# ---------------------------------------------------------------------------
# 5. list_inbox — forwards status → linkingStatus + limit via params
# ---------------------------------------------------------------------------
def test_list_inbox_forwards_status_as_linkingStatus_param(client):
    empty_payload = {"data": {"discoveryItems": []}}
    with patch("pipeline.sap_discovery.client.requests.get") as mget:
        mget.return_value = _mock_response(200, json_data=empty_payload)

        client.list_inbox(status="not_linked", limit=25)

    params = mget.call_args.kwargs.get("params", {})
    assert params.get("linkingStatus") == "not_linked"
    assert params.get("limit") == 25

    called_url = mget.call_args.args[0] if mget.call_args.args else mget.call_args.kwargs.get("url")
    assert called_url == (
        "https://demo.leanix.net/services/discovery-linking/v2/"
        "discovery_sap/discoveryItems"
    )


# ---------------------------------------------------------------------------
# 6. get_item — parses the full DiscoveryItem dataclass from fixture
# ---------------------------------------------------------------------------
def test_get_item_returns_full_dataclass(client):
    raw = _load("sap_item_detail.json")
    # The captured fixture is wrapped in {"data": {...}}; the client also unwraps
    # via .get("data", {}). If fixture were bare object we'd wrap manually.
    if "data" in raw and isinstance(raw["data"], dict) and "id" in raw["data"]:
        payload = raw
    else:
        payload = {"data": raw}

    item_id = "01517494-3ae2-4a3f-bf76-c467c680aecb"
    with patch("pipeline.sap_discovery.client.requests.get") as mget:
        mget.return_value = _mock_response(200, json_data=payload)

        item = client.get_item(item_id)

    assert isinstance(item, DiscoveryItem)
    assert item.display_name
    assert len(item.nodes) >= 1
    for node in item.nodes:
        assert isinstance(node, Node)
        assert node.node_id
        assert isinstance(node.suggestions, list)

    called_url = mget.call_args.args[0] if mget.call_args.args else mget.call_args.kwargs.get("url")
    assert called_url.endswith(f"/discoveryItems/{item_id}")


# ---------------------------------------------------------------------------
# 7. bulk_link + bulk_reject — send {"ids": [...]} to the right endpoints
# ---------------------------------------------------------------------------
def test_bulk_link_uses_ids_body(client):
    with patch("pipeline.sap_discovery.client.requests.put") as mput:
        mput.return_value = _mock_response(200, json_data={"applied": [], "failed": []})

        client.bulk_link(["a", "b", "c"])

        link_url = mput.call_args.args[0] if mput.call_args.args else mput.call_args.kwargs.get("url")
        assert link_url.endswith(
            "/services/discovery-linking/v2/discovery_sap/discoveryItems/link"
        )
        assert mput.call_args.kwargs.get("json") == {"ids": ["a", "b", "c"]}

        # Same test also covers bulk_reject
        mput.reset_mock()
        mput.return_value = _mock_response(200, json_data={"applied": [], "failed": []})
        client.bulk_reject(["x"])

        reject_url = mput.call_args.args[0] if mput.call_args.args else mput.call_args.kwargs.get("url")
        assert reject_url.endswith(
            "/services/discovery-linking/v2/discovery_sap/discoveryItems/reject"
        )
        assert mput.call_args.kwargs.get("json") == {"ids": ["x"]}


# ---------------------------------------------------------------------------
# 8. set_link_selection — PUT /discoveryItems/{id}/link with linksPerNode body
# ---------------------------------------------------------------------------
def test_set_link_selection_puts_links_per_node(client):
    links = {
        "n1": {"factSheetId": "fs1"},
        "n2": {"factSheetName": "New", "factSheetType": "ITComponent"},
    }

    with patch("pipeline.sap_discovery.client.requests.put") as mput:
        mput.return_value = _mock_response(200, json_data={})

        client.set_link_selection("item-1", links_per_node=links, cross_item_links=None)

    called_url = mput.call_args.args[0] if mput.call_args.args else mput.call_args.kwargs.get("url")
    assert called_url.endswith("/discoveryItems/item-1/link")

    body = mput.call_args.kwargs.get("json")
    assert body == {"linksPerNode": links, "crossItemLinks": {}}

    headers = mput.call_args.kwargs.get("headers", {})
    assert headers.get("Authorization", "").startswith("Bearer ")
    assert headers.get("Content-Type") == "application/json"
