"""Tests for pipeline.sap_discovery.report."""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.sap_discovery import report


def _seed(session_dir: Path) -> None:
    (session_dir / "integration.json").write_text(json.dumps({
        "integration_id": "int-42", "crm_id": "0001234567",
        "origin": "sap-extension", "autolinking_enabled": True,
        "status": "pending",
    }))
    (session_dir / "decisions.json").write_text(json.dumps([
        {
            "item_id": "d-high", "action": "link",
            "target_type": "Application", "target_id": "fs-app-1",
            "create_payload": None, "confidence": "HIGH",
            "reason": "Single existing Application match: S/4",
        },
        {
            "item_id": "d-low", "action": "review",
            "target_type": "Application", "target_id": None,
            "create_payload": None, "confidence": "LOW",
            "reason": "Ambiguous or unknown product",
        },
    ]))
    (session_dir / "execution_log.json").write_text(json.dumps({
        "applied": ["d-high"], "failed": [], "pending_review": ["d-low"],
    }))


def test_build_writes_report_html_and_json(tmp_path):
    session_dir = tmp_path / "sap_discovery"
    session_dir.mkdir()
    _seed(session_dir)

    out = report.build(session_dir=session_dir)
    assert out["html"].exists()
    assert out["json"].exists()

    data = json.loads(out["json"].read_text())
    assert data["summary"]["applied"] == 1
    assert data["summary"]["pending_review"] == 1
    assert len(data["applied"]) == 1
    assert len(data["pending_review"]) == 1
    assert data["applied"][0]["item_id"] == "d-high"
    assert data["pending_review"][0]["item_id"] == "d-low"


def test_build_html_contains_pending_review_dropdown(tmp_path):
    session_dir = tmp_path / "sap_discovery"
    session_dir.mkdir()
    _seed(session_dir)

    out = report.build(session_dir=session_dir)
    html = out["html"].read_text()
    assert "d-low" in html
    assert "Apply selections" in html
    # dropdown offers at least link + reject
    assert "reject" in html.lower()
    assert "link" in html.lower()
