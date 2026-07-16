"""pipeline.sap_discovery.client — thin REST client over LeanIX discovery APIs.

Endpoints used:
- POST /services/discovery-sap-extension/v1/integrations
- PUT  /services/discovery-linking/v2/{origin}/settings/autoLinking
- GET  /services/discovery-linking/v2/{origin}/discoveryItems
- PUT  /services/discovery-linking/v2/{origin}/discoveryItems/link
- PUT  /services/discovery-linking/v2/{origin}/discoveryItems/reject

Authentication is delegated to pipeline.leanix_auth.get_bearer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

from pipeline.leanix_auth import get_bearer


@dataclass
class DiscoveryItem:
    id: str
    display_name: str
    classification: str
    product: str
    system_role: str | None
    status: str
    suggested_links: dict
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict) -> "DiscoveryItem":
        raw_links = payload.get("suggestedLinks") or {}
        normalized: dict[str, list[dict]] = {}
        for key in ("application", "itcomponent", "provider"):
            entries = raw_links.get(key) or []
            normalized[key] = [
                {
                    "factsheet_id": e.get("factSheetId"),
                    "name": e.get("name", ""),
                    "label": e.get("label", "existing"),
                }
                for e in entries
            ]
        return cls(
            id=payload["id"],
            display_name=payload.get("displayName", ""),
            classification=payload.get("classification", ""),
            product=payload.get("product", ""),
            system_role=payload.get("systemRole"),
            status=payload.get("status", ""),
            suggested_links=normalized,
            raw=payload,
        )


class Client:
    """LeanIX discovery REST client. All HTTP calls live in this class."""

    _ORIGIN_CANDIDATES = ("sap-extension", "internal-sap", "sap-landscape")

    def __init__(self, base_url: str, api_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token

    def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {get_bearer(self.base_url, self.api_token)}"}

    def create_integration(self, crm_id: str) -> dict:
        """POST /services/discovery-sap-extension/v1/integrations.

        Returns the integration record as JSON. Raises requests.HTTPError on 4xx/5xx.
        """
        token = get_bearer(self.base_url, self.api_token)
        resp = requests.post(
            f"{self.base_url}/services/discovery-sap-extension/v1/integrations",
            json={"customerIdentifiers": [{"type": "CRM", "id": crm_id}]},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def set_autolinking(self, origin: str, enabled: bool) -> None:
        resp = requests.put(
            f"{self.base_url}/services/discovery-linking/v2/{origin}/settings/autoLinking",
            json={"enabled": enabled},
            headers=self._auth_header(),
            timeout=30,
        )
        resp.raise_for_status()

    def discover_origin(self) -> str:
        """Probe origin candidates. Return the first that returns 2xx to a HEAD-equivalent GET.

        Raises RuntimeError if none respond.
        """
        for candidate in self._ORIGIN_CANDIDATES:
            resp = requests.get(
                f"{self.base_url}/services/discovery-linking/v2/{candidate}/discoveryItems",
                params={"limit": 1},
                headers=self._auth_header(),
                timeout=30,
            )
            if resp.status_code < 400:
                return candidate
        raise RuntimeError(
            f"No SAP discovery origin resolved. Tried: {', '.join(self._ORIGIN_CANDIDATES)}"
        )

    def list_inbox(self, origin: str, status: str | None = None) -> list[DiscoveryItem]:
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        resp = requests.get(
            f"{self.base_url}/services/discovery-linking/v2/{origin}/discoveryItems",
            params=params,
            headers=self._auth_header(),
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        return [DiscoveryItem.from_api(x) for x in data.get("items", [])]
