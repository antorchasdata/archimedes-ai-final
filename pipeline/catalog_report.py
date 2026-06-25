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
from html import escape as _html_escape
from typing import Literal
from urllib.parse import quote


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


_STATUS_ORDER = {"LINKED": 0, "REVIEW": 1, "CUSTOM": 2}


def sort_rows(rows: list[ReportRow]) -> list[ReportRow]:
    return sorted(rows, key=lambda r: (_STATUS_ORDER.get(r.status, 99), r.type, r.name))


def count_rows(rows: list[ReportRow]) -> dict[str, int]:
    out = {"LINKED": 0, "REVIEW": 0, "CUSTOM": 0}
    for r in rows:
        out[r.status] = out.get(r.status, 0) + 1
    return out


def build_fs_url(base_url: str, workspace: str, fs_type: str, uuid: str | None) -> str | None:
    if not uuid:
        return None
    base = (base_url or "").rstrip("/")
    return f"{base}/{workspace}/factsheet/{fs_type}/{uuid}"


def build_catalog_search_url(base_url: str, workspace: str, name: str) -> str:
    base = (base_url or "").rstrip("/")
    return f"{base}/{workspace}/inventory/referenceCatalog?q={quote(name)}"


_HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>Catalog Linking Review — {client}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 24px; color: #222; }}
  h1 {{ margin: 0 0 12px 0; font-size: 1.4rem; }}
  .counts {{ margin: 8px 0 20px 0; font-size: 0.95rem; }}
  .counts .pill {{ display: inline-block; padding: 4px 10px; border-radius: 12px; margin-right: 8px; }}
  .pill-linked {{ background: #d4edda; color: #155724; }}
  .pill-review {{ background: #fff3cd; color: #856404; }}
  .pill-custom {{ background: #f8d7da; color: #721c24; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ padding: 8px 10px; border-bottom: 1px solid #eee; text-align: left; vertical-align: top; }}
  th {{ background: #f6f6f6; font-weight: 600; }}
  .row-linked {{ background: #f4fbf6; }}
  .row-review {{ background: #fffaeb; }}
  .row-custom {{ background: #fdf2f3; }}
  .actions a {{ margin-right: 8px; }}
  .failed-tag {{ color: #b00020; font-weight: 600; }}
  .btn {{ display: inline-block; padding: 6px 12px; background: #0070f3; color: white; text-decoration: none; border-radius: 4px; }}
</style>
</head><body>
<h1>Catalog Linking Review — {client}</h1>
<div class="counts">
  <span class="pill pill-linked">🟢 {n_linked} linked</span>
  <span class="pill pill-review">🟡 {n_review} to review</span>
  <span class="pill pill-custom">🔴 {n_custom} custom</span>
</div>
<table>
<thead><tr>
  <th>Status</th><th>Name</th><th>Type</th><th>Suggested catalog match</th><th>externalId</th><th>Actions</th>
</tr></thead>
<tbody>
{rows}
</tbody></table>
</body></html>
"""


def _row_html(r: ReportRow, base_url: str, workspace: str) -> str:
    status_label = {
        "LINKED": f"🟢 LINKED ({r.confidence or '-'})",
        "REVIEW": f"🟡 REVIEW ({r.confidence or '-'})",
        "CUSTOM": f"🔴 CUSTOM ({r.confidence or 'NONE'})",
    }[r.status]
    if r.push_failed:
        status_label = f'<span class="failed-tag">⚠️ PUSH FAILED</span> · {status_label}'

    suggested = (
        f"{_html_escape(r.suggested_name)} ({r.suggested_score:.2f})"
        if r.suggested_name and r.suggested_score is not None
        else (_html_escape(r.suggested_name) if r.suggested_name else "—")
    )
    external_id = _html_escape(r.external_id) if r.external_id else "—"

    fs_url = build_fs_url(base_url, workspace, r.type, r.fs_uuid)
    actions: list[str] = []
    if fs_url:
        actions.append(f'<a href="{fs_url}" target="_blank">Open FS</a>')
    if r.status == "REVIEW":
        search_url = build_catalog_search_url(base_url, workspace, r.name)
        actions.append(f'<a href="{search_url}" target="_blank">Search catalog</a>')
    actions_html = " ".join(actions) if actions else "—"

    cls = {"LINKED": "row-linked", "REVIEW": "row-review", "CUSTOM": "row-custom"}[r.status]
    return (
        f'<tr class="row {cls}">'
        f'<td>{status_label}</td>'
        f'<td>{_html_escape(r.name)}</td>'
        f'<td>{_html_escape(r.type)}</td>'
        f'<td>{suggested}</td>'
        f'<td>{external_id}</td>'
        f'<td class="actions">{actions_html}</td>'
        f'</tr>'
    )


def render_html(resolution: dict, uuid_map: dict, client_name: str) -> str:
    rows = sort_rows(build_rows(resolution, uuid_map))
    counts = count_rows(rows)
    base_url = (uuid_map or {}).get("base_url", "")
    workspace = (uuid_map or {}).get("workspace", "")
    rows_html = "\n".join(_row_html(r, base_url, workspace) for r in rows)
    return _HTML_TEMPLATE.format(
        client=_html_escape(client_name),
        n_linked=counts.get("LINKED", 0),
        n_review=counts.get("REVIEW", 0),
        n_custom=counts.get("CUSTOM", 0),
        rows=rows_html,
    )
