"""Resolves Application/ITComponent names against the LeanIX Reference Catalog
before fact sheets are created, so the staging Excel carries catalog
externalIds and rows are created already linked to the catalog.

Public API:
    ReferenceCatalogResolver(base_url, api_token, interactive=True).resolve(...)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


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

    def cleanup(self) -> None:
        """Archive probe fact sheets. Always safe to call (idempotent)."""
        return
