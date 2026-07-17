"""LeanIX Internal SAP Landscape Data — REST client (empirically verified 2026-07-17)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

from pipeline.leanix_auth import get_bearer


_ORIGIN = "discovery_sap"       # snake_case, single origin
_SERVICE_SLIS = "SLIS"          # SAP Landscape Integration Service


class IntegrationNotFoundError(RuntimeError):
    """No active SLIS integration in this workspace."""


@dataclass
class DiscoveryDetail:
    key: str
    display_name: str
    type: str
    value: Any
    category: str | None = None

    @classmethod
    def from_api(cls, payload: dict) -> "DiscoveryDetail":
        key = payload.get("key", "")
        return cls(
            key=key,
            display_name=payload.get("keyDisplayName", key),
            type=payload.get("type", "TEXT"),
            value=payload.get("value"),
            category=payload.get("category"),
        )


@dataclass
class Suggestion:
    factsheet_type: str
    factsheet_id: str | None
    factsheet_name: str
    factsheet_display_name: str
    factsheet_subtype: str | None = None

    @classmethod
    def from_api(cls, payload: dict) -> "Suggestion":
        name = payload.get("factSheetName", "")
        return cls(
            factsheet_type=payload.get("factSheetType", ""),
            factsheet_id=payload.get("factSheetId"),
            factsheet_name=name,
            factsheet_display_name=payload.get("factSheetDisplayName", name),
            factsheet_subtype=payload.get("factSheetSubtype"),
        )


@dataclass
class Node:
    node_id: str
    node_type: str
    node_name: str
    catalog_name: str | None
    node_category: str | None
    is_selected: bool
    is_selection_locked: bool
    lock_reason: str | None
    can_be_edited: bool
    suggestions: list[Suggestion]

    @classmethod
    def from_api(cls, payload: dict) -> "Node":
        is_selected_obj = payload.get("isSelected") or {}
        is_selection_locked_obj = payload.get("isSelectionLocked") or {}
        lock_reason = is_selection_locked_obj.get("reason") if isinstance(is_selection_locked_obj, dict) else None
        suggestions_raw = payload.get("suggestions") or []
        return cls(
            node_id=payload.get("nodeId", ""),
            node_type=payload.get("nodeType", ""),
            node_name=payload.get("nodeName", ""),
            catalog_name=payload.get("catalogName"),
            node_category=payload.get("nodeCategory"),
            is_selected=bool(is_selected_obj.get("value")) if isinstance(is_selected_obj, dict) else False,
            is_selection_locked=bool(is_selection_locked_obj.get("value")) if isinstance(is_selection_locked_obj, dict) else False,
            lock_reason=lock_reason,
            can_be_edited=bool(payload.get("canBeEdited", False)),
            suggestions=[Suggestion.from_api(s) for s in suggestions_raw],
        )


@dataclass
class Relation:
    id: str
    from_node_id: str
    to_node_id: str
    relation_type: str

    @classmethod
    def from_api(cls, payload: dict) -> "Relation":
        return cls(
            id=payload.get("id", ""),
            from_node_id=payload.get("fromNodeId", ""),
            to_node_id=payload.get("toNodeId", ""),
            relation_type=payload.get("relationType", ""),
        )


@dataclass
class DiscoveryItem:
    id: str
    display_name: str
    priority: str | None
    linking_status: str
    linking_status_committed: bool
    review_status: str | None
    source: dict
    discovery_details: list[DiscoveryDetail]
    nodes: list[Node]
    relations: list[Relation]
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict) -> "DiscoveryItem":
        return cls(
            id=payload.get("id", ""),
            display_name=payload.get("displayName", ""),
            priority=payload.get("priority"),
            linking_status=payload.get("linkingStatus", "not_linked"),
            linking_status_committed=bool(payload.get("linkingStatusCommitted", False)),
            review_status=payload.get("reviewStatus"),
            source=payload.get("source") or {},
            discovery_details=[DiscoveryDetail.from_api(d) for d in (payload.get("discoveryDetails") or [])],
            nodes=[Node.from_api(n) for n in (payload.get("nodes") or [])],
            relations=[Relation.from_api(r) for r in (payload.get("relations") or [])],
            raw=payload,
        )


class Client:
    """LeanIX Internal SAP Landscape Data REST client."""

    def __init__(self, base_url: str, api_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {get_bearer(self.base_url, self.api_token)}",
            "Content-Type": "application/json",
        }

    def list_integrations(self) -> list[dict]:
        r = requests.get(
            f"{self.base_url}/services/discovery-sap/v1/integrations",
            headers=self._headers(),
            timeout=30,
        )
        r.raise_for_status()
        return r.json() or []

    def find_active_slis_integration(self) -> dict:
        matches = [
            i for i in self.list_integrations()
            if i.get("service") == _SERVICE_SLIS and i.get("active")
        ]
        if not matches:
            raise IntegrationNotFoundError(
                "No active 'Internal SAP Landscape Data' integration in this workspace. "
                "Configure it under LeanIX → Discover → Internal SAP Landscape Data first."
            )
        return matches[0]

    def list_inbox(self, *, limit: int | None = None, status: str | None = None) -> list[DiscoveryItem]:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = int(limit)
        if status:
            params["linkingStatus"] = status
        r = requests.get(
            f"{self.base_url}/services/discovery-linking/v2/{_ORIGIN}/discoveryItems",
            params=params,
            headers=self._headers(),
            timeout=60,
        )
        r.raise_for_status()
        data = (r.json() or {}).get("data", {})
        return [DiscoveryItem.from_api(x) for x in data.get("discoveryItems", [])]

    def get_item(self, item_id: str) -> DiscoveryItem:
        r = requests.get(
            f"{self.base_url}/services/discovery-linking/v2/{_ORIGIN}/discoveryItems/{item_id}",
            headers=self._headers(),
            timeout=30,
        )
        r.raise_for_status()
        return DiscoveryItem.from_api((r.json() or {}).get("data", {}))

    def set_link_selection(
        self,
        item_id: str,
        *,
        links_per_node: dict[str, dict],
        cross_item_links: dict[str, dict] | None = None,
    ) -> dict:
        r = requests.put(
            f"{self.base_url}/services/discovery-linking/v2/{_ORIGIN}/discoveryItems/{item_id}/link",
            json={"linksPerNode": links_per_node, "crossItemLinks": cross_item_links or {}},
            headers=self._headers(),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def bulk_link(self, ids: list[str]) -> dict:
        r = requests.put(
            f"{self.base_url}/services/discovery-linking/v2/{_ORIGIN}/discoveryItems/link",
            json={"ids": ids},
            headers=self._headers(),
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def bulk_reject(self, ids: list[str]) -> dict:
        r = requests.put(
            f"{self.base_url}/services/discovery-linking/v2/{_ORIGIN}/discoveryItems/reject",
            json={"ids": ids},
            headers=self._headers(),
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def preview(
        self,
        item_id: str,
        *,
        selection_per_node: list[dict],
        selection_per_relation: list[dict] | None = None,
        selection_per_related_node: list[dict] | None = None,
    ) -> dict:
        r = requests.post(
            f"{self.base_url}/services/discovery-linking/v2/{_ORIGIN}/discoveryItems/{item_id}/preview",
            json={
                "selectionPerNode": selection_per_node,
                "selectionPerRelation": selection_per_relation or [],
                "selectionPerRelatedNode": selection_per_related_node or [],
            },
            headers=self._headers(),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
