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
