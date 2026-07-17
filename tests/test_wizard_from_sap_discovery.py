"""Tests for /baseline/from-sap-discovery and the SAP Discovery routes."""
from __future__ import annotations

import json
import uuid as _uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from archimedes_wizard import app, _sessions, OUTPUT_DIR


def _make_session(client_name: str = "Acme") -> tuple[str, Path]:
    session_id = str(_uuid.uuid4())
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    _sessions[session_id] = {
        "client_name": client_name,
        "output_dir":  session_dir,
        "out_baseline": None,
        "out_target":   None,
        "workspace": {"base_url": "https://demo.leanix.net", "api_token": "tok"},
    }
    return session_id, session_dir


def test_from_sap_discovery_404_when_session_missing():
    tc = TestClient(app)
    r = tc.post("/api/session/missing/baseline/from-sap-discovery",
                json={"crm_id": "0001234567"})
    assert r.status_code == 404


def test_from_sap_discovery_starts_integration_and_returns_pending():
    sid, session_dir = _make_session()
    tc = TestClient(app)

    fake_integ = {
        "id": "afdae8b4-c707-4924-b1d9-e550d696288e",
        "service": "SLIS",
        "name": "Internal SAP Landscape Data",
        "active": True,
        "dataSync": {"status": "ACTIVE", "lastSuccesfulRun": "2026-07-17T09:00:00Z"},
        "selectedCustomers": ["37327"],
    }

    with patch("archimedes_wizard.sap_discovery") as sd_mod:
        sd_mod.Client.return_value = MagicMock()
        sd_mod.discover_integration.return_value = fake_integ

        r = tc.post(f"/api/session/{sid}/baseline/from-sap-discovery",
                    json={})
    assert r.status_code == 200
    body = r.json()
    assert body["integration"]["id"] == fake_integ["id"]
    assert body["integration"]["service"] == "SLIS"


def test_sap_discovery_status_returns_orchestrator_result():
    sid, session_dir = _make_session()
    (session_dir / "sap_discovery").mkdir(parents=True, exist_ok=True)
    (session_dir / "sap_discovery" / "integration.json").write_text(
        json.dumps({"integration_id": "int-42", "origin": "sap-extension"})
    )
    tc = TestClient(app)

    with patch("archimedes_wizard.sap_discovery") as sd_mod:
        sd_mod.Client.return_value = MagicMock()
        sd_mod.poll_status.return_value = {
            "status": "ready", "inbox_count": 5,
            "action_needed": 4, "review_needed": 1,
        }
        r = tc.get(f"/api/session/{sid}/baseline/sap-discovery/status")

    assert r.status_code == 200
    assert r.json()["status"] == "ready"
    assert r.json()["inbox_count"] == 5


def test_sap_discovery_process_runs_orchestrator_and_returns_summary():
    sid, session_dir = _make_session()
    (session_dir / "sap_discovery").mkdir(parents=True, exist_ok=True)
    (session_dir / "sap_discovery" / "integration.json").write_text(
        json.dumps({"integration_id": "int-42", "origin": "sap-extension"})
    )
    tc = TestClient(app)

    with patch("archimedes_wizard.sap_discovery") as sd_mod:
        sd_mod.Client.return_value = MagicMock()
        sd_mod.make_create_factsheet_bridge.return_value = lambda p: {"id": "fs-x"}
        sd_mod.process_inbox.return_value = {
            "applied": ["d-high"], "failed": [], "pending_review": ["d-low"],
        }
        sd_mod.build.return_value = {
            "html": session_dir / "sap_discovery" / "report.html",
            "json": session_dir / "sap_discovery" / "report.json",
        }
        r = tc.post(f"/api/session/{sid}/baseline/sap-discovery/process",
                    json={"catalog": {"SAP S/4HANA Cloud": {}}})

    body = r.json()
    assert body["applied"] == 1
    assert body["pending_review"] == 1
    assert body["report_url"].endswith("/sap-discovery/report")


def test_sap_discovery_apply_review_forwards_decisions():
    sid, session_dir = _make_session()
    (session_dir / "sap_discovery").mkdir(parents=True, exist_ok=True)
    (session_dir / "sap_discovery" / "integration.json").write_text(
        json.dumps({"integration_id": "int-42", "origin": "sap-extension"})
    )
    tc = TestClient(app)

    with patch("archimedes_wizard.sap_discovery") as sd_mod:
        sd_mod.Client.return_value = MagicMock()
        sd_mod.apply_review.return_value = {
            "applied": ["d-low"], "failed": [], "pending_review": [],
        }
        sd_mod.build.return_value = {
            "html": session_dir / "sap_discovery" / "report.html",
            "json": session_dir / "sap_discovery" / "report.json",
        }
        decisions = [
            {"item_id": "d-low", "action": "link",
             "target_type": "Application", "target_id": "fs-1"},
        ]
        r = tc.post(
            f"/api/session/{sid}/baseline/sap-discovery/apply-review",
            json={"decisions": decisions},
        )

    assert r.status_code == 200
    call = sd_mod.apply_review.call_args
    # apply_review is now called positionally: (client, session_dir, decisions)
    assert call.args[2] == decisions
