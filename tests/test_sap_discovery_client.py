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
