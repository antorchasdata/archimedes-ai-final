"""pipeline.sap_discovery.matcher — pure decision logic for the inbox.

Consumes a DiscoveryItem plus a lookup catalog (dict[product_name -> metadata]) and
produces a MatchDecision. No I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pipeline.sap_discovery.client import DiscoveryItem

Action = Literal["link", "create_and_link", "reject", "review"]
TargetType = Literal["Application", "ITComponent", "Provider"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


@dataclass
class MatchDecision:
    item_id: str
    action: Action
    target_type: TargetType | None
    target_id: str | None
    create_payload: dict | None
    confidence: Confidence
    reason: str


_TARGET_ORDER: list[tuple[str, TargetType]] = [
    ("application", "Application"),
    ("itcomponent", "ITComponent"),
    ("provider", "Provider"),
]


def _first_target_with_candidates(item: DiscoveryItem) -> tuple[TargetType, list[dict]] | None:
    for key, target_type in _TARGET_ORDER:
        entries = item.suggested_links.get(key) or []
        if entries:
            return target_type, entries
    return None


def decide(item: DiscoveryItem, catalog: dict) -> MatchDecision:
    if item.status == "linked":
        return MatchDecision(
            item_id=item.id,
            action="reject",
            target_type=None,
            target_id=None,
            create_payload=None,
            confidence="HIGH",
            reason="Item already linked by LeanIX autolinking",
        )

    hit = _first_target_with_candidates(item)
    if hit is None:
        return MatchDecision(
            item_id=item.id,
            action="review",
            target_type=None,
            target_id=None,
            create_payload=None,
            confidence="LOW",
            reason="No suggested links from LeanIX",
        )

    target_type, entries = hit
    existing = [e for e in entries if e.get("label") == "existing"]
    creates = [e for e in entries if e.get("label") == "create_and_link"]

    if len(existing) == 1:
        return MatchDecision(
            item_id=item.id,
            action="link",
            target_type=target_type,
            target_id=existing[0]["factsheet_id"],
            create_payload=None,
            confidence="HIGH",
            reason=f"Single existing {target_type} match: {existing[0]['name']}",
        )

    if len(existing) > 1:
        return MatchDecision(
            item_id=item.id,
            action="review",
            target_type=target_type,
            target_id=None,
            create_payload=None,
            confidence="LOW",
            reason=f"{len(existing)} candidate {target_type} fact sheets — manual review",
        )

    if creates and item.product in catalog:
        create = creates[0]
        return MatchDecision(
            item_id=item.id,
            action="create_and_link",
            target_type=target_type,
            target_id=None,
            create_payload={
                "type": target_type,
                "name": create.get("name") or item.product,
                "product": item.product,
                "classification": item.classification,
            },
            confidence="MEDIUM",
            reason=f"Create & Link {target_type} for known product '{item.product}'",
        )

    return MatchDecision(
        item_id=item.id,
        action="review",
        target_type=target_type,
        target_id=None,
        create_payload=None,
        confidence="LOW",
        reason=f"Ambiguous or unknown product '{item.product}' — manual review",
    )
