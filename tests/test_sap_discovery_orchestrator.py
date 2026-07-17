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
