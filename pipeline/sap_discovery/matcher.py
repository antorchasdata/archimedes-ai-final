"""pipeline.sap_discovery.matcher — pure decision logic (no I/O).

Consumes a DiscoveryItem whose nodes carry pre-computed suggestions from the
LeanIX reference catalog. Produces a MatchDecision that the orchestrator
turns into set_link_selection + bulk_link/reject calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pipeline.sap_discovery.client import DiscoveryItem, Node

Action = Literal["link", "create_and_link", "reject", "review"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


@dataclass
class MatchDecision:
    item_id: str
    action: Action
    links_per_node: dict[str, dict]      # {nodeId: {"factSheetId":...} | {"factSheetName":..., "factSheetType":...}}
    creates: list[dict] = field(default_factory=list)   # [{nodeId, factSheetType, factSheetName}]
    confidence: Confidence = "LOW"
    reason: str = ""


def _editable_nodes(item: DiscoveryItem) -> list[Node]:
    return [n for n in item.nodes if n.can_be_edited and not n.is_selection_locked]


def decide(item: DiscoveryItem) -> MatchDecision:
    # Branch 1: already linked → reject HIGH
    if item.linking_status == "linked":
        return MatchDecision(
            item_id=item.id,
            action="reject",
            links_per_node={},
            creates=[],
            confidence="HIGH",
            reason="Item already linked in LeanIX",
        )

    # Branch 2: committed and no review needed → reject HIGH
    if item.linking_status_committed and item.review_status is None:
        return MatchDecision(
            item_id=item.id,
            action="reject",
            links_per_node={},
            creates=[],
            confidence="HIGH",
            reason="Committed and no review needed",
        )

    editable = _editable_nodes(item)

    # Branch 3: no editable nodes → review LOW
    if not editable:
        return MatchDecision(
            item_id=item.id,
            action="review",
            links_per_node={},
            creates=[],
            confidence="LOW",
            reason="No editable nodes",
        )

    # Branch 5 (early check): any editable node with >1 suggestion having an id
    # → ambiguous review MEDIUM. We check this before branch 4 because it
    # implies the item is not homogeneously "1 with id".
    ambiguous = [
        n for n in editable
        if len([s for s in n.suggestions if s.factsheet_id]) > 1
    ]
    if ambiguous:
        ambiguous_ids = ", ".join(n.node_id for n in ambiguous)
        return MatchDecision(
            item_id=item.id,
            action="review",
            links_per_node={},
            creates=[],
            confidence="MEDIUM",
            reason=f"Ambiguous nodes: {ambiguous_ids}",
        )

    # Branch 4: every editable node has exactly 1 suggestion with a factsheet_id
    all_single_with_id = all(
        len(n.suggestions) == 1 and n.suggestions[0].factsheet_id
        for n in editable
    )
    if all_single_with_id:
        links_per_node = {
            n.node_id: {"factSheetId": n.suggestions[0].factsheet_id}
            for n in editable
        }
        return MatchDecision(
            item_id=item.id,
            action="link",
            links_per_node=links_per_node,
            creates=[],
            confidence="HIGH",
            reason="All editable nodes have a single existing candidate",
        )

    # Branch 6: every editable node has exactly 1 suggestion with no factsheet_id
    all_single_no_id = all(
        len(n.suggestions) == 1 and n.suggestions[0].factsheet_id is None
        for n in editable
    )
    if all_single_no_id:
        links_per_node = {
            n.node_id: {
                "factSheetName": n.suggestions[0].factsheet_name,
                "factSheetType": n.suggestions[0].factsheet_type,
            }
            for n in editable
        }
        creates = [
            {
                "nodeId": n.node_id,
                "factSheetType": n.suggestions[0].factsheet_type,
                "factSheetName": n.suggestions[0].factsheet_name,
            }
            for n in editable
        ]
        return MatchDecision(
            item_id=item.id,
            action="create_and_link",
            links_per_node=links_per_node,
            creates=creates,
            confidence="MEDIUM",
            reason="All editable nodes require create-and-link",
        )

    # Branch 7: heterogeneous / missing suggestions
    return MatchDecision(
        item_id=item.id,
        action="review",
        links_per_node={},
        creates=[],
        confidence="LOW",
        reason="Missing or heterogeneous suggestions across editable nodes",
    )
