import json
from pathlib import Path
from fastapi.testclient import TestClient

from archimedes_wizard import app, _sessions, OUTPUT_DIR


def test_catalog_report_404_when_session_missing():
    client = TestClient(app)
    resp = client.get("/api/session/does-not-exist/catalog-report")
    assert resp.status_code == 404


def test_catalog_report_xlsx_404_when_session_missing():
    client = TestClient(app)
    resp = client.get("/api/session/does-not-exist/catalog-report.xlsx")
    assert resp.status_code == 404


import uuid as _uuid
import openpyxl

def _make_session(client_name="Acme"):
    """Construct a complete session fixture with both JSON inputs."""
    session_id = str(_uuid.uuid4())
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "catalog_resolution_report.json").write_text(json.dumps({
        "entries": [{"name": "L", "type": "Application", "status": "LINKED",
                     "confidence": "VERYHIGH", "external_id": "lx_APP_1"}]
    }))
    (session_dir / "push_uuid_map.json").write_text(json.dumps({
        "workspace": "demo-eu-3",
        "base_url":  "https://demo-eu-3.leanix.net",
        "entries":   {"Application::L": {"uuid": "ll-1", "created": True}},
        "failed":    [],
    }))
    _sessions[session_id] = {
        "client_name": client_name,
        "output_dir":  session_dir,
        "out_baseline": None,
        "out_target":   None,
    }
    return session_id, session_dir


def test_catalog_report_html_returns_200_when_files_present():
    session_id, _ = _make_session()
    client = TestClient(app)
    resp = client.get(f"/api/session/{session_id}/catalog-report")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Catalog Linking Review" in resp.text
    assert "Acme" in resp.text


def test_catalog_report_xlsx_returns_200_when_files_present():
    session_id, session_dir = _make_session()
    client = TestClient(app)
    resp = client.get(f"/api/session/{session_id}/catalog-report.xlsx")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    # Verify the xlsx file exists on disk and is valid
    xlsx_path = session_dir / "catalog_report.xlsx"
    assert xlsx_path.exists()
    wb = openpyxl.load_workbook(xlsx_path)
    assert wb.sheetnames == ["Catalog Report"]


def test_catalog_report_404_when_no_push():
    """Session exists, but no push_uuid_map.json."""
    session_id = str(_uuid.uuid4())
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    _sessions[session_id] = {
        "client_name": "Acme",
        "output_dir":  session_dir,
        "out_baseline": None, "out_target": None,
    }
    client = TestClient(app)
    resp = client.get(f"/api/session/{session_id}/catalog-report")
    assert resp.status_code == 404
    assert "push_uuid_map.json not found" in resp.text


def test_session_state_includes_step8_available_true_when_uuid_map_present(monkeypatch):
    monkeypatch.setenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "true")
    session_id, _ = _make_session()
    client = TestClient(app)
    resp = client.get(f"/api/session/{session_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("step8_available") is True


def test_session_state_step8_unavailable_when_resolver_disabled(monkeypatch):
    monkeypatch.setenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "false")
    session_id, _ = _make_session()
    client = TestClient(app)
    resp = client.get(f"/api/session/{session_id}")
    body = resp.json()
    assert body.get("step8_available") is False


def test_session_state_step8_unavailable_when_no_uuid_map(monkeypatch):
    monkeypatch.setenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "true")
    session_id = str(_uuid.uuid4())
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    _sessions[session_id] = {
        "client_name": "Acme",
        "output_dir":  session_dir,
        "out_baseline": None, "out_target": None,
    }
    client = TestClient(app)
    resp = client.get(f"/api/session/{session_id}")
    body = resp.json()
    assert body.get("step8_available") is False
