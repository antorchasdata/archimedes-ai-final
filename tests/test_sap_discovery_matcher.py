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
