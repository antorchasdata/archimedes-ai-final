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
