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
