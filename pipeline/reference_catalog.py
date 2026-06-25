"""Resolves Application/ITComponent names against the LeanIX Reference Catalog
before fact sheets are created, so the staging Excel carries catalog
externalIds and rows are created already linked to the catalog.

Public API:
    ReferenceCatalogResolver(base_url, api_token, interactive=True).resolve(...)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_name(name: str) -> str:
    """Lower-case + collapse whitespace. Used for cache keys and exact-match."""
    return _WHITESPACE_RE.sub(" ", name.strip().lower())


_SOURCE_BY_TYPE = {"Application": "saas", "ITComponent": "ltls"}
_PREFIX_BY_TYPE = {"Application": "lx_APP_", "ITComponent": "lx_ITC_"}


def _source_for_type(fs_type: str) -> str:
    try:
        return _SOURCE_BY_TYPE[fs_type]
    except KeyError as exc:
        raise ValueError(
            f"Reference Catalog only supports Application and ITComponent, got {fs_type!r}"
        ) from exc


def _external_id_prefix(fs_type: str) -> str:
    return _PREFIX_BY_TYPE[fs_type]


@dataclass
class ResolvedMatch:
    """Result of resolving a single name against the catalog."""
    name: str
    external_id: str | None = None
    catalog_uuid: str | None = None
    display_name: str | None = None
    confidence: str = "NONE"   # VERYHIGH | HIGH | MEDIUM | LOW | NONE
    status: str = "CUSTOM"     # LINKED | CUSTOM
    fields: dict[str, Any] = field(default_factory=dict)


class ReferenceCatalogResolver:
    """Pre-creation Reference Catalog resolver."""

    def __init__(
        self,
        base_url: str,
        api_token: str,
        interactive: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.interactive = interactive
        self._cache: dict[tuple[str, str], ResolvedMatch] = {}
        self._probe_ids: dict[str, str] = {}    # fs_type -> probe FS UUID
        self._no_probe_mode = False
        self._skip_all_prompts = False

    def resolve(self, fs_type: str, names: list[str]) -> dict[str, ResolvedMatch]:
        """Resolve a list of names. Returns dict keyed by original name."""
        raise NotImplementedError

    # ── HTTP layer ─────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

    def _search_by_name(self, fs_type: str, name: str) -> list[dict]:
        """GET /fact-sheets?q=<name>. Returns list (possibly empty) on success
        or [] on any error. Never raises."""
        if len(name.strip()) < 2:
            return []
        source = _source_for_type(fs_type)
        url = (
            f"{self.base_url}/services/reference-data/v1/source/{source}/fact-sheets"
        )
        params = {"q": name, "factSheetType": fs_type, "fuzzy": "false"}
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("Catalog search failed for %r (%s)", name, exc)
            return []

    _FIELDS_TO_COPY = ("description", "lxHostingType", "productCategory")

    def _fetch_detail(self, fs_type: str, external_id: str) -> dict[str, Any]:
        """GET /fact-sheets/<id>. Returns flattened dict:
            { 'description': ..., 'fields': {'lxHostingType': ..., 'productCategory': ..., 'provider': ...} }
        Returns {} on any error. Never raises."""
        source = _source_for_type(fs_type)
        url = (
            f"{self.base_url}/services/reference-data/v1/source/{source}/fact-sheets/"
            f"{external_id}"
        )
        try:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.warning("Catalog detail fetch failed for %s (%s)", external_id, exc)
            return {}

        fields_dict: dict[str, Any] = {}
        for entry in body.get("fields", []) or []:
            n = entry.get("name")
            if n in self._FIELDS_TO_COPY:
                fields_dict[n] = entry.get("value")

        # Provider lives in relations
        for rel in body.get("relations", []) or []:
            if rel.get("name") in ("relApplicationToProvider", "relITComponentToProvider"):
                target = rel.get("targetFactSheet") or {}
                fields_dict["provider"] = target.get("displayName")
                break

        return {
            "description": body.get("description"),
            "fields": fields_dict,
        }

    # ── GraphQL probe lifecycle ────────────────────────────────────────────

    def _gql(self, query: str, variables: dict | None = None) -> dict | None:
        """POST to pathfinder GraphQL. Returns data dict on success, None on error."""
        url = f"{self.base_url}/services/pathfinder/v1/graphql"
        body = {"query": query, "variables": variables or {}}
        try:
            resp = requests.post(url, headers=self._headers(), json=body, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("errors"):
                logger.warning("GraphQL errors: %s", payload["errors"])
                return None
            return payload.get("data")
        except Exception as exc:
            logger.warning("GraphQL call failed: %s", exc)
            return None

    def _probe_create(self, fs_type: str, name: str) -> str | None:
        query = (
            "mutation($name:String!,$type:FactSheetType!){"
            "createFactSheet(input:{name:$name,type:$type}){factSheet{id}}}"
        )
        data = self._gql(query, {"name": name, "type": fs_type})
        if not data:
            return None
        return ((data.get("createFactSheet") or {}).get("factSheet") or {}).get("id")

    def _probe_rename(self, fs_id: str, new_name: str) -> bool:
        query = (
            "mutation($id:ID!,$patches:[Patch]!){"
            "updateFactSheet(id:$id,patches:$patches,comment:\"probe rename\"){"
            "factSheet{id}}}"
        )
        variables = {
            "id": fs_id,
            "patches": [{"op": "replace", "path": "/name", "value": new_name}],
        }
        data = self._gql(query, variables)
        return bool(data and data.get("updateFactSheet"))

    def _probe_archive(self, fs_id: str) -> bool:
        query = (
            "mutation($id:ID!,$patches:[Patch]!){"
            "updateFactSheet(id:$id,patches:$patches,comment:\"probe cleanup\"){"
            "factSheet{id}}}"
        )
        variables = {
            "id": fs_id,
            "patches": [{"op": "replace", "path": "/status", "value": "ARCHIVED"}],
        }
        data = self._gql(query, variables)
        return bool(data and data.get("updateFactSheet"))

    def cleanup(self) -> None:
        """Archive probe fact sheets. Always safe to call (idempotent)."""
        return
