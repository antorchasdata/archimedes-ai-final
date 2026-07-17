"""Tests for pipeline.sap_discovery.matcher — pure decision logic."""
from __future__ import annotations

from pipeline.sap_discovery.client import DiscoveryItem, Node, Suggestion
from pipeline.sap_discovery.matcher import MatchDecision, decide


def _sugg(fs_type="Application", fs_id="fs-1", name="Foo", display=None, subtype=None):
    return Suggestion(fs_type, fs_id, name, display or name, subtype)


def _node(node_id="n1", node_type="Application", name="Foo",
          locked=False, editable=True, suggestions=None):
    return Node(
        node_id=node_id,
        node_type=node_type,
        node_name=name,
        catalog_name=None,
        node_category=None,
        is_selected=True,
        is_selection_locked=locked,
        lock_reason=("Catalog" if locked else None),
        can_be_edited=editable,
        suggestions=suggestions or [],
    )


def _item(nodes, linking_status="not_linked", committed=False, review_status=None):
    return DiscoveryItem(
        id="it-1",
        display_name="Test",
        priority=None,
        linking_status=linking_status,
        linking_status_committed=committed,
        review_status=review_status,
        source={},
        discovery_details=[],
        nodes=nodes,
        relations=[],
        raw={},
    )


def test_linked_item_is_rejected():
    item = _item(nodes=[_node()], linking_status="linked")
    d = decide(item)
    assert isinstance(d, MatchDecision)
    assert d.action == "reject"
    assert d.confidence == "HIGH"
    assert "already linked" in d.reason.lower()


def test_committed_no_review_is_rejected():
    item = _item(nodes=[_node()], committed=True, review_status=None)
    d = decide(item)
    assert d.action == "reject"
    assert d.confidence == "HIGH"
    assert "committed" in d.reason.lower()


def test_all_editable_single_with_id_auto_links():
    # Include a locked node that should be ignored by the decision logic.
    locked = _node(
        node_id="locked-1",
        locked=True,
        editable=False,
        suggestions=[_sugg(fs_id="fs-locked")],
    )
    n1 = _node(node_id="n1", suggestions=[_sugg(fs_id="fs-1", name="A")])
    n2 = _node(node_id="n2", suggestions=[_sugg(fs_id="fs-2", name="B")])
    item = _item(nodes=[locked, n1, n2])
    d = decide(item)
    assert d.action == "link"
    assert d.confidence == "HIGH"
    assert d.links_per_node == {
        "n1": {"factSheetId": "fs-1"},
        "n2": {"factSheetId": "fs-2"},
    }
    assert d.creates == []


def test_multiple_suggestions_with_id_needs_review():
    n1 = _node(
        node_id="n-ambig",
        suggestions=[
            _sugg(fs_id="fs-1", name="A"),
            _sugg(fs_id="fs-2", name="B"),
        ],
    )
    item = _item(nodes=[n1])
    d = decide(item)
    assert d.action == "review"
    assert d.confidence == "MEDIUM"
    assert "n-ambig" in d.reason


def test_all_editable_single_no_id_creates_and_links():
    n1 = _node(
        node_id="n1",
        suggestions=[_sugg(fs_type="Application", fs_id=None, name="AppA")],
    )
    n2 = _node(
        node_id="n2",
        suggestions=[_sugg(fs_type="ITComponent", fs_id=None, name="CompB")],
    )
    item = _item(nodes=[n1, n2])
    d = decide(item)
    assert d.action == "create_and_link"
    assert d.confidence == "MEDIUM"
    assert d.links_per_node == {
        "n1": {"factSheetName": "AppA", "factSheetType": "Application"},
        "n2": {"factSheetName": "CompB", "factSheetType": "ITComponent"},
    }
    assert len(d.creates) == 2
    assert {"nodeId": "n1", "factSheetType": "Application", "factSheetName": "AppA"} in d.creates
    assert {"nodeId": "n2", "factSheetType": "ITComponent", "factSheetName": "CompB"} in d.creates


def test_no_editable_nodes_needs_review():
    locked = _node(node_id="l1", locked=True, editable=False,
                   suggestions=[_sugg(fs_id="fs-1")])
    non_editable = _node(node_id="l2", locked=False, editable=False,
                         suggestions=[_sugg(fs_id="fs-2")])
    item = _item(nodes=[locked, non_editable])
    d = decide(item)
    assert d.action == "review"
    assert d.confidence == "LOW"
    assert "no editable nodes" in d.reason.lower()


def test_heterogeneous_suggestions_needs_review():
    n1 = _node(
        node_id="n1",
        suggestions=[_sugg(fs_id="fs-1", name="Existing")],
    )
    n2 = _node(
        node_id="n2",
        suggestions=[_sugg(fs_id=None, name="ToCreate")],
    )
    item = _item(nodes=[n1, n2])
    d = decide(item)
    assert d.action == "review"
    assert d.confidence == "LOW"
    assert "heterogeneous" in d.reason.lower() or "missing" in d.reason.lower()
