"""Tests for pipeline.sap_discovery.orchestrator — real discovery-sap flow."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline.sap_discovery import orchestrator
from pipeline.sap_discovery.client import (
    DiscoveryItem,
    IntegrationNotFoundError,
    Node,
    Suggestion,
)


# --- fixture helpers -------------------------------------------------------

def _sugg(fs_id: str | None = "fs-app-1", name: str = "SAP S/4HANA",
          ftype: str = "Application") -> Suggestion:
    return Suggestion(
        factsheet_type=ftype, factsheet_id=fs_id,
        factsheet_name=name, factsheet_display_name=name,
    )


def _node(node_id: str = "n-1", ntype: str = "Application",
          suggestions: list[Suggestion] | None = None,
          can_edit: bool = True, locked: bool = False) -> Node:
    return Node(
        node_id=node_id, node_type=ntype, node_name="X",
        catalog_name=None, node_category=None,
        is_selected=True, is_selection_locked=locked, lock_reason=None,
        can_be_edited=can_edit,
        suggestions=suggestions if suggestions is not None else [],
    )


def _item(item_id: str, *, linking_status: str = "not_linked",
          committed: bool = False, review_status: str | None = None,
          nodes: list[Node] | None = None) -> DiscoveryItem:
    return DiscoveryItem(
        id=item_id, display_name=f"item-{item_id}", priority="medium",
        linking_status=linking_status,
        linking_status_committed=committed,
        review_status=review_status,
        source={"system": "SLIS", "originId": item_id},
        discovery_details=[],
        nodes=nodes if nodes is not None else [],
        relations=[],
        raw={"id": item_id},
    )


def _session_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sap_discovery"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- discover_integration --------------------------------------------------

def test_discover_integration_persists_json_and_returns_it(tmp_path):
    session_dir = _session_dir(tmp_path)
    integ = {
        "id": "afdae8b4-c707-4924-b1d9-e550d696288e",
        "service": "SLIS", "name": "Internal SAP Landscape Data",
        "active": True,
        "dataSync": {"status": "ACTIVE", "lastSuccesfulRun": "2026-07-17T09:00:00Z"},
    }
    fake_client = MagicMock()
    fake_client.find_active_slis_integration.return_value = integ

    result = orchestrator.discover_integration(fake_client, session_dir)

    assert result == integ
    persisted = json.loads((session_dir / "integration.json").read_text())
    assert persisted == integ
    fake_client.find_active_slis_integration.assert_called_once_with()


def test_discover_integration_raises_and_writes_no_file(tmp_path):
    session_dir = _session_dir(tmp_path)
    fake_client = MagicMock()
    fake_client.find_active_slis_integration.side_effect = IntegrationNotFoundError("nope")

    with pytest.raises(IntegrationNotFoundError):
        orchestrator.discover_integration(fake_client, session_dir)

    assert not (session_dir / "integration.json").exists()


# --- process_inbox ---------------------------------------------------------

def test_process_inbox_dry_run_does_no_writes(tmp_path):
    session_dir = _session_dir(tmp_path)
    fake_client = MagicMock()
    fake_client.list_inbox.return_value = [
        _item("d-high", nodes=[_node(suggestions=[_sugg("fs-app-1")])]),
    ]

    log = orchestrator.process_inbox(fake_client, session_dir, dry_run=True)

    assert log["dry_run"] is True
    assert log["applied"] == []
    fake_client.set_link_selection.assert_not_called()
    fake_client.bulk_link.assert_not_called()
    fake_client.bulk_reject.assert_not_called()
    assert (session_dir / "inbox_snapshot.json").exists()
    assert (session_dir / "decisions.json").exists()
    assert (session_dir / "execution_log.json").exists()


def test_process_inbox_calls_set_link_then_bulk_link(tmp_path):
    session_dir = _session_dir(tmp_path)
    fake_client = MagicMock()
    fake_client.list_inbox.return_value = [
        _item("d-high", nodes=[_node("n-app", suggestions=[_sugg("fs-app-1")])]),
    ]
    fake_client.bulk_link.return_value = {"applied": ["d-high"], "failed": []}

    log = orchestrator.process_inbox(fake_client, session_dir)

    fake_client.set_link_selection.assert_called_once_with(
        "d-high", links_per_node={"n-app": {"factSheetId": "fs-app-1"}}
    )
    fake_client.bulk_link.assert_called_once_with(["d-high"])
    fake_client.bulk_reject.assert_not_called()
    assert log["applied"] == ["d-high"]
    assert log["failed"] == []
    assert log["pending_review"] == []


def test_process_inbox_rejects_and_creates_in_correct_order(tmp_path):
    session_dir = _session_dir(tmp_path)
    already_linked = _item("d-linked", linking_status="linked")
    create_item = _item(
        "d-create",
        nodes=[_node("n-app", suggestions=[_sugg(fs_id=None, name="NewApp")])],
    )
    review_item = _item("d-review", nodes=[_node("n-app", suggestions=[])])

    fake_client = MagicMock()
    fake_client.list_inbox.return_value = [already_linked, create_item, review_item]
    fake_client.bulk_link.return_value = {"applied": ["d-create"], "failed": []}
    fake_client.bulk_reject.return_value = {"applied": [], "failed": []}

    created_calls: list[dict] = []

    def _fake_create(payload: dict) -> dict:
        created_calls.append(payload)
        return {"id": "fs-new-1"}

    log = orchestrator.process_inbox(
        fake_client, session_dir, create_factsheet=_fake_create
    )

    # d-linked HIGH "already linked" → skipped (no re-reject)
    fake_client.bulk_reject.assert_not_called()

    # d-create → factsheet created, then set_link_selection with new id, then bulk_link
    assert created_calls == [{"type": "Application", "name": "NewApp", "attributes": {}}]
    fake_client.set_link_selection.assert_called_once_with(
        "d-create", links_per_node={"n-app": {"factSheetId": "fs-new-1"}}
    )
    fake_client.bulk_link.assert_called_once_with(["d-create"])

    # d-review stays pending
    assert log["pending_review"] == ["d-review"]
    assert log["applied"] == ["d-create"]


def test_execution_log_reflects_applied_and_failed(tmp_path):
    session_dir = _session_dir(tmp_path)
    fake_client = MagicMock()
    fake_client.list_inbox.return_value = [
        _item("d-ok", nodes=[_node("n-app", suggestions=[_sugg("fs-app-1")])]),
        _item("d-bad", nodes=[_node("n-app", suggestions=[_sugg("fs-app-2")])]),
    ]
    fake_client.bulk_link.return_value = {
        "applied": ["d-ok"],
        "failed": [{"itemId": "d-bad", "reason": "target not found"}],
    }

    log = orchestrator.process_inbox(fake_client, session_dir)

    persisted = json.loads((session_dir / "execution_log.json").read_text())
    assert persisted == log
    assert log["applied"] == ["d-ok"]
    assert log["failed"] == [{"itemId": "d-bad", "reason": "target not found"}]
