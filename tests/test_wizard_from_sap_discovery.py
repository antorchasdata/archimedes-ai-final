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

    fake_state = {
        "integration_id": "int-42",
        "crm_id": "0001234567",
        "origin": "sap-extension",
        "autolinking_enabled": True,
        "status": "pending",
        "created_at": "2026-07-16T00:00:00Z",
    }

    with patch("archimedes_wizard.sap_discovery") as sd_mod:
        sd_mod.Client.return_value = MagicMock()
        sd_mod.start_integration.return_value = fake_state

        r = tc.post(f"/api/session/{sid}/baseline/from-sap-discovery",
                    json={"crm_id": "0001234567"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["integration_id"] == "int-42"
    assert body["eta_seconds"] == 600


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
