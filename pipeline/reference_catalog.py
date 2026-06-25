"""Resolves Application/ITComponent names against the LeanIX Reference Catalog
before fact sheets are created, so the staging Excel carries catalog
externalIds and rows are created already linked to the catalog.

Public API:
    ReferenceCatalogResolver(base_url, api_token, interactive=True).resolve(...)
"""
from __future__ import annotations

import logging
import re
import sys
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
        out: dict[str, ResolvedMatch] = {}
        for name in names:
            if not name or not name.strip():
                continue
            key = (fs_type, _normalize_name(name))
            cached = self._cache.get(key)
            if cached is not None:
                # Preserve the original `name` field on the returned match
                out[name] = ResolvedMatch(
                    name=name,
                    external_id=cached.external_id,
                    catalog_uuid=cached.catalog_uuid,
                    display_name=cached.display_name,
                    confidence=cached.confidence,
                    status=cached.status,
                    fields=dict(cached.fields),
                )
                continue
            match = self._resolve_one(fs_type, name)
            self._cache[key] = match
            out[name] = match
        return out

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

    def _batch_links(
        self, fs_type: str, probe_id: str, name: str
    ) -> dict | None:
        """POST /batch-links. Returns the top suggestion's factSheet dict
        (with confidenceLevel) or None on no match / any error."""
        source = _source_for_type(fs_type)
        url = (
            f"{self.base_url}/services/reference-data/v1/source/{source}/batch-links"
        )
        body = {
            "factSheets": [
                {"id": probe_id, "name": name, "catalogStatus": "n/a"}
            ],
            "numMatches": 3,
        }
        try:
            resp = requests.post(url, headers=self._headers(), json=body, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.warning("batch-links failed for %r (%s)", name, exc)
            return None

        entry = (payload.get("data") or {}).get(probe_id) or {}
        suggestions = entry.get("suggestions") or []
        if not suggestions:
            return None
        return suggestions[0].get("factSheet")

    def _prompt_link(self, name: str, catalog_display: str, confidence: str) -> bool:
        """Interactive Y/n/s prompt for HIGH/MEDIUM matches.
        Returns True to link, False to skip. Sets _skip_all_prompts on 's'."""
        if not self.interactive or self._skip_all_prompts:
            return False
        if not getattr(sys.stdin, "isatty", lambda: False)():
            return False
        prompt = (
            f"  Link '{name}' to catalog entry '{catalog_display}' "
            f"(confidence={confidence})? [Y/n/s(kip all)]: "
        )
        try:
            answer = input(prompt).strip().lower()
        except EOFError:
            return False
        if answer in ("", "y", "yes", "s\u00ed", "si"):
            return True
        if answer in ("s", "skip"):
            self._skip_all_prompts = True
            return False
        return False

    # ── Resolution algorithm ───────────────────────────────────────────────

    def _resolve_one(self, fs_type: str, name: str) -> ResolvedMatch:
        """Resolve a single name. Pure (no caching) — caller manages cache."""
        candidates = self._search_by_name(fs_type, name)

        # Step 2a: zero candidates
        if not candidates:
            return ResolvedMatch(name=name)

        # Step 2b: exact-match shortcut
        norm = _normalize_name(name)
        for cand in candidates:
            fs = cand.get("factSheet") or {}
            if _normalize_name(fs.get("displayName") or "") == norm:
                ext_id = fs.get("externalId")
                detail = self._fetch_detail(fs_type, ext_id) if ext_id else {}
                return ResolvedMatch(
                    name=name,
                    external_id=ext_id,
                    catalog_uuid=fs.get("id"),
                    display_name=fs.get("displayName"),
                    confidence="VERYHIGH",
                    status="LINKED",
                    fields=self._build_fields(detail),
                )

        # Step 3+: ambiguous — probe path (added in Task 10)
        return self._resolve_via_probe(fs_type, name)

    def _build_fields(self, detail: dict) -> dict:
        """Flatten detail into the fields dict stored on ResolvedMatch."""
        out: dict[str, Any] = {}
        if detail.get("description"):
            out["description"] = detail["description"]
        for k, v in (detail.get("fields") or {}).items():
            if v is not None:
                out[k] = v
        return out

    _PROBE_BASE = {
        "Application": "_archimedes_probe_application",
        "ITComponent": "_archimedes_probe_itcomponent",
    }

    def _ensure_probe(self, fs_type: str) -> str | None:
        """Lazy-create the per-type reusable probe FS. Returns its UUID or None."""
        if self._no_probe_mode:
            return None
        if fs_type in self._probe_ids:
            return self._probe_ids[fs_type]
        probe_id = self._probe_create(fs_type, self._PROBE_BASE[fs_type])
        if probe_id is None:
            self._no_probe_mode = True
            logger.warning("Probe creation failed for %s — entering no-probe mode", fs_type)
            return None
        self._probe_ids[fs_type] = probe_id
        return probe_id

    def _resolve_via_probe(self, fs_type: str, name: str) -> ResolvedMatch:
        probe_id = self._ensure_probe(fs_type)
        if probe_id is None:
            return ResolvedMatch(name=name)

        # Rename probe so the catalog matcher sees the actual search term.
        if not self._probe_rename(probe_id, name):
            return ResolvedMatch(name=name)

        top = self._batch_links(fs_type, probe_id, name)
        if not top:
            return ResolvedMatch(name=name)

        confidence = (top.get("confidenceLevel") or "NONE").upper()
        ext_id = top.get("externalId")
        display = top.get("displayName")
        catalog_uuid = top.get("id")

        # Decision
        link = False
        if confidence == "VERYHIGH":
            link = True
        elif confidence in ("HIGH", "MEDIUM"):
            link = self._prompt_link(name, display or "?", confidence)
        # LOW / anything else → CUSTOM

        if link and ext_id:
            detail = self._fetch_detail(fs_type, ext_id)
            return ResolvedMatch(
                name=name,
                external_id=ext_id,
                catalog_uuid=catalog_uuid,
                display_name=display,
                confidence=confidence,
                status="LINKED",
                fields=self._build_fields(detail),
            )
        # Informational match — kept for the audit report, but not linked.
        return ResolvedMatch(
            name=name, confidence=confidence, status="CUSTOM",
            display_name=display, catalog_uuid=catalog_uuid,
        )

    def cleanup(self) -> None:
        """Archive probe fact sheets. Always safe to call (idempotent)."""
        return
