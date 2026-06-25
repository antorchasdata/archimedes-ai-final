# pipeline/catalog_report.py
"""
pipeline/catalog_report.py — Catalog linking review report renderer.

Pure rendering: takes the resolver's catalog_resolution_report.json plus a
push_uuid_map.json and produces an HTML + XLSX report listing each entry's
linking status and direct links to its LeanIX fact sheet.

No HTTP. No LeanIX calls. Two inputs → two output files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Status = Literal["LINKED", "REVIEW", "CUSTOM"]


@dataclass
class ReportRow:
    name: str
    type: str
    status: Status
    confidence: str
    external_id: str | None
    suggested_name: str | None
    suggested_score: float | None
    fs_uuid: str | None
    push_failed: bool


def build_rows(resolution: dict, uuid_map: dict) -> list[ReportRow]:
    """Join resolution entries with uuid_map → list of ReportRow."""
    entries = resolution.get("entries", []) or []
    if not entries:
        return []
    uuid_entries = (uuid_map or {}).get("entries") or {}
    failed_keys = {
        _entry_key(f)
        for f in (uuid_map or {}).get("failed", []) or []
    }

    rows: list[ReportRow] = []
    for e in entries:
        key = _entry_key(e)
        uuid_entry = uuid_entries.get(key) or {}
        status = _classify(e)
        rows.append(ReportRow(
            name=e.get("name") or "",
            type=e.get("type") or "",
            status=status,
            confidence=e.get("confidence") or "",
            external_id=e.get("external_id"),
            suggested_name=e.get("suggested_name"),
            suggested_score=e.get("suggested_score"),
            fs_uuid=uuid_entry.get("uuid"),
            push_failed=key in failed_keys,
        ))
    return rows


def _entry_key(entry: dict) -> str:
    """Canonical join key between resolution entries and uuid_map entries."""
    return f"{entry.get('type')}::{entry.get('name')}"


def _classify(entry: dict) -> Status:
    status = (entry.get("status") or "").upper()
    confidence = (entry.get("confidence") or "").upper()
    if status == "LINKED":
        return "LINKED"
    if confidence in ("HIGH", "MEDIUM"):
        return "REVIEW"
    return "CUSTOM"
