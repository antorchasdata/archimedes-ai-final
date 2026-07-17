"""End-to-end integration tests for pipeline.sap_discovery — mocked Client."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline import sap_discovery
from pipeline.sap_discovery.client import (
    DiscoveryItem,
    IntegrationNotFoundError,
    Node,
    Suggestion,
)


def _sugg(fs_id: str | None = "fs-app-1", name: str = "SAP S/4HANA") -> Suggestion:
    return Suggestion(
        factsheet_type="Application", factsheet_id=fs_id,
        factsheet_name=name, factsheet_display_name=name,
    )


def _node(node_id: str = "n-app", suggestions=None, can_edit: bool = True,
          locked: bool = False) -> Node:
    return Node(
        node_id=node_id, node_type="Application", node_name="X",
        catalog_name=None, node_category=None,
        is_selected=True, is_selection_locked=locked, lock_reason=None,
        can_be_edited=can_edit,
        suggestions=suggestions if suggestions is not None else [],
    )


def _item(item_id: str, *, linking_status: str = "not_linked",
          nodes=None) -> DiscoveryItem:
    return DiscoveryItem(
        id=item_id, display_name=f"item-{item_id}", priority="medium",
        linking_status=linking_status,
        linking_status_committed=False,
        review_status=None,
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


# --- end-to-end flow -------------------------------------------------------

def test_detect_then_list_then_link_flow(tmp_path):
    """The happy path: detect integration → list inbox → decide → set + bulk_link."""
    session_dir = _session_dir(tmp_path)
    integ = {
        "id": "afdae8b4-c707-4924-b1d9-e550d696288e",
        "service": "SLIS", "name": "Internal SAP Landscape Data",
        "active": True,
        "dataSync": {"status": "ACTIVE", "lastSuccesfulRun": "2026-07-17T09:00:00Z"},
        "selectedCustomers": ["37327"],
    }

    fake_client = MagicMock()
    fake_client.find_active_slis_integration.return_value = integ
    fake_client.list_inbox.return_value = [
        _item("d-auto", nodes=[_node("n-app", suggestions=[_sugg("fs-app-1")])]),
    ]
    fake_client.bulk_link.return_value = {"applied": ["d-auto"], "failed": []}

    got_integ = sap_discovery.discover_integration(fake_client, session_dir)
    assert got_integ == integ
    assert (session_dir / "integration.json").exists()

    log = sap_discovery.process_inbox(fake_client, session_dir)

    fake_client.set_link_selection.assert_called_once_with(
        "d-auto", links_per_node={"n-app": {"factSheetId": "fs-app-1"}}
    )
    fake_client.bulk_link.assert_called_once_with(["d-auto"])
    fake_client.bulk_reject.assert_not_called()
    assert log["applied"] == ["d-auto"]
    assert log["pending_review"] == []


def test_missing_integration_surfaces_typed_error(tmp_path):
    """No active SLIS integration → IntegrationNotFoundError; no side-effect files."""
    session_dir = _session_dir(tmp_path)
    fake_client = MagicMock()
    fake_client.find_active_slis_integration.side_effect = IntegrationNotFoundError(
        "No active 'Internal SAP Landscape Data' integration in this workspace."
    )

    with pytest.raises(IntegrationNotFoundError):
        sap_discovery.discover_integration(fake_client, session_dir)

    assert not (session_dir / "integration.json").exists()


def test_review_items_are_persisted_but_not_applied(tmp_path):
    """Ambiguous / unresolvable items should land in pending_review, not applied."""
    session_dir = _session_dir(tmp_path)
    fake_client = MagicMock()
    fake_client.list_inbox.return_value = [
        _item("d-ambig", nodes=[_node(
            "n-app",
            suggestions=[_sugg("fs-1", "A"), _sugg("fs-2", "B")],
        )]),
        _item("d-none", nodes=[_node("n-app", suggestions=[])]),
    ]

    log = sap_discovery.process_inbox(fake_client, session_dir)

    fake_client.set_link_selection.assert_not_called()
    fake_client.bulk_link.assert_not_called()
    assert set(log["pending_review"]) == {"d-ambig", "d-none"}
    assert log["applied"] == []

    decisions = json.loads((session_dir / "decisions.json").read_text())
    assert {d["item_id"] for d in decisions} == {"d-ambig", "d-none"}
    assert all(d["action"] == "review" for d in decisions)


def test_apply_review_confirms_pending_decisions(tmp_path):
    """apply_review picks user-confirmed decisions and applies them via bulk_link/reject."""
    session_dir = _session_dir(tmp_path)
    # Seed a pending review from a prior process_inbox run.
    (session_dir / "execution_log.json").write_text(json.dumps({
        "applied": [], "failed": [], "pending_review": ["d-a", "d-b"],
    }))

    fake_client = MagicMock()
    fake_client.bulk_link.return_value = {"applied": ["d-a"], "failed": []}
    fake_client.bulk_reject.return_value = {"applied": ["d-b"], "failed": []}

    updated = sap_discovery.apply_review(fake_client, session_dir, [
        {"item_id": "d-a", "action": "link",
         "links_per_node": {"n-app": {"factSheetId": "fs-app-1"}}},
        {"item_id": "d-b", "action": "reject"},
    ])

    fake_client.set_link_selection.assert_called_once_with(
        "d-a", links_per_node={"n-app": {"factSheetId": "fs-app-1"}}
    )
    fake_client.bulk_link.assert_called_once_with(["d-a"])
    fake_client.bulk_reject.assert_called_once_with(["d-b"])
    assert set(updated["applied"]) == {"d-a", "d-b"}
    assert updated["pending_review"] == []
