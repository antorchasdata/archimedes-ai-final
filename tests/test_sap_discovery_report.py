"""Tests for pipeline.sap_discovery.report."""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.sap_discovery import report


def _seed(session_dir: Path) -> None:
    (session_dir / "integration.json").write_text(json.dumps({
        "id": "afdae8b4-c707-4924-b1d9-e550d696288e",
        "service": "SLIS",
        "name": "Internal SAP Landscape Data",
        "active": True,
        "dataSync": {
            "status": "ACTIVE",
            "lastSuccesfulRun": "2026-07-17T09:00:00Z",
        },
        "selectedCustomers": ["37327"],
    }))
    (session_dir / "decisions.json").write_text(json.dumps([
        {
            "item_id": "d-high",
            "action": "link",
            "links_per_node": {"n-app": {"factSheetId": "fs-app-1"}},
            "creates": [],
            "confidence": "HIGH",
            "reason": "All editable nodes have a single existing candidate",
        },
        {
            "item_id": "d-low",
            "action": "review",
            "links_per_node": {},
            "creates": [],
            "confidence": "LOW",
            "reason": "Missing or heterogeneous suggestions across editable nodes",
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
