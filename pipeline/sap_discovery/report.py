"""pipeline.sap_discovery.report — HTML + JSON report renderer.

Reads decisions.json + execution_log.json + integration.json from session_dir
and writes report.html + report.json in the same directory.
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path


def _load(path: Path) -> object:
    return json.loads(path.read_text()) if path.exists() else None


def _row(item_id: str, extra: dict) -> str:
    return (
        f"<tr><td>{escape(item_id)}</td>"
        f"<td>{escape(extra.get('confidence', ''))}</td>"
        f"<td>{escape(extra.get('reason', ''))}</td></tr>"
    )


def _pending_card(decision: dict) -> str:
    item_id = decision["item_id"]
    return (
        "<div class='card'>"
        f"<h3>{escape(item_id)}</h3>"
        f"<p>{escape(decision.get('reason', ''))}</p>"
        f"<select name='action-{escape(item_id)}'>"
        "<option value='link'>Link to existing fact sheet</option>"
        "<option value='reject'>Reject</option>"
        "</select>"
        f"<input name='target-{escape(item_id)}' placeholder='Target fact sheet id' />"
        "</div>"
    )


def build(session_dir: Path) -> dict:
    integration = _load(session_dir / "integration.json") or {}
    decisions = _load(session_dir / "decisions.json") or []
    log = _load(session_dir / "execution_log.json") or {
        "applied": [], "failed": [], "pending_review": [],
    }

    decisions_by_id = {d["item_id"]: d for d in decisions}
    applied = [decisions_by_id.get(i, {"item_id": i}) for i in log.get("applied", [])]
    pending_review = [
        decisions_by_id.get(i, {"item_id": i}) for i in log.get("pending_review", [])
    ]
    failed = log.get("failed", [])

    summary = {
        "applied": len(applied),
        "pending_review": len(pending_review),
        "failed": len(failed),
        "integration_id": integration.get("integration_id"),
        "crm_id": integration.get("crm_id"),
    }

    json_out = {
        "summary": summary,
        "applied": applied,
        "pending_review": pending_review,
        "failed": failed,
    }
    json_path = session_dir / "report.json"
    json_path.write_text(json.dumps(json_out, indent=2, default=str))

    html_parts: list[str] = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>SAP Internal Discovery — Review</title>",
        "<style>body{font-family:system-ui;margin:2em;} table{border-collapse:collapse;}"
        "td,th{border:1px solid #ddd;padding:6px 10px;} .card{border:1px solid #ccc;"
        "padding:12px;margin:8px 0;border-radius:6px;}</style></head><body>",
        f"<h1>SAP Internal Discovery — Session</h1>",
        f"<p>Integration <code>{escape(str(summary['integration_id']))}</code> · "
        f"CRM <code>{escape(str(summary['crm_id']))}</code></p>",
        f"<p><b>Applied:</b> {summary['applied']} · "
        f"<b>Pending review:</b> {summary['pending_review']} · "
        f"<b>Failed:</b> {summary['failed']}</p>",
        "<h2>Applied</h2><table><tr><th>Item</th><th>Confidence</th><th>Reason</th></tr>",
    ]
    for d in applied:
        html_parts.append(_row(d.get("item_id", ""), d))
    html_parts.append("</table>")

    html_parts.append("<h2>Pending review</h2><form method='post' action='./apply-review'>")
    for d in pending_review:
        html_parts.append(_pending_card(d))
    html_parts.append("<button type='submit'>Apply selections</button></form>")
    html_parts.append("</body></html>")

    html_path = session_dir / "report.html"
    html_path.write_text("".join(html_parts))
    return {"html": html_path, "json": json_path}
