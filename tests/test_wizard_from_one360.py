"""Tests for the /baseline/from-one360 and /baseline/one360-status endpoints."""

from __future__ import annotations

import uuid as _uuid
from pathlib import Path

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
    }
    return session_id, session_dir


# ── /baseline/from-one360 ──────────────────────────────────────────────────────


def test_from_one360_404_when_session_missing():
    client = TestClient(app)
    resp = client.post(
        "/api/session/does-not-exist/baseline/from-one360",
        json={"onprem_path": "/nope", "cloud_path": "/nope"},
    )
    assert resp.status_code == 404


def test_from_one360_400_when_no_paths_provided():
    session_id, _ = _make_session()
    client = TestClient(app)
    resp = client.post(
        f"/api/session/{session_id}/baseline/from-one360",
        json={},
    )
    assert resp.status_code == 400


def test_from_one360_400_when_path_does_not_exist(tmp_path):
    session_id, _ = _make_session()
    client = TestClient(app)
    resp = client.post(
        f"/api/session/{session_id}/baseline/from-one360",
        json={"onprem_path": str(tmp_path / "missing.xlsx")},
    )
    assert resp.status_code == 400


def test_from_one360_copies_files_and_runs_baseline(tmp_path, monkeypatch):
    session_id, session_dir = _make_session()

    onprem_src = tmp_path / "System-Landscape-Details-Table-2024-01-15.xlsx"
    onprem_src.write_bytes(b"fake-onprem")
    cloud_src = tmp_path / "Cloud-Systems-Table-2024-01-15.xlsx"
    cloud_src.write_bytes(b"fake-cloud")
    contracts_src = tmp_path / "Purchased-Solutions-Table-LPR-2024-01-15.xlsx"
    contracts_src.write_bytes(b"fake-contracts")

    captured: dict = {}

    def fake_generate_baseline(*, output_path, client_name, onprem_path=None, cloud_path=None):
        captured["output_path"] = output_path
        captured["client_name"] = client_name
        captured["onprem_path"] = onprem_path
        captured["cloud_path"] = cloud_path
        return {"n_onprem": 3, "n_cloud": 5, "n_total": 8}

    monkeypatch.setattr("archimedes_wizard.generate_baseline", fake_generate_baseline)

    client = TestClient(app)
    resp = client.post(
        f"/api/session/{session_id}/baseline/from-one360",
        json={
            "onprem_path": str(onprem_src),
            "cloud_path": str(cloud_src),
            "contracts_path": str(contracts_src),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["n_onprem"] == 3
    assert body["n_cloud"] == 5
    assert body["n_total"] == 8
    assert body["download_url"] == f"/api/session/{session_id}/download/baseline"

    # Files copied into session dir under canonical names
    assert (session_dir / "onprem_systems.xlsx").read_bytes() == b"fake-onprem"
    assert (session_dir / "cloud_systems.xlsx").read_bytes() == b"fake-cloud"
    assert (session_dir / "purchased_solutions.xlsx").read_bytes() == b"fake-contracts"

    # Contracts remembered on session for downstream steps
    assert _sessions[session_id]["contracts_source"] == session_dir / "purchased_solutions.xlsx"

    # generate_baseline received the copied paths
    assert captured["onprem_path"] == session_dir / "onprem_systems.xlsx"
    assert captured["cloud_path"] == session_dir / "cloud_systems.xlsx"
    assert captured["client_name"] == "Acme"


def test_from_one360_accepts_only_cloud(tmp_path, monkeypatch):
    session_id, session_dir = _make_session()
    cloud_src = tmp_path / "Cloud-Systems-Table-2024-01-15.xlsx"
    cloud_src.write_bytes(b"cloud-only")

    def fake_generate_baseline(*, output_path, client_name, onprem_path=None, cloud_path=None):
        assert onprem_path is None
        assert cloud_path is not None
        return {"n_onprem": 0, "n_cloud": 2, "n_total": 2}

    monkeypatch.setattr("archimedes_wizard.generate_baseline", fake_generate_baseline)

    client = TestClient(app)
    resp = client.post(
        f"/api/session/{session_id}/baseline/from-one360",
        json={"cloud_path": str(cloud_src)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["n_total"] == 2
    assert not (session_dir / "onprem_systems.xlsx").exists()
    assert (session_dir / "cloud_systems.xlsx").read_bytes() == b"cloud-only"


# ── /baseline/one360-status ────────────────────────────────────────────────────


def test_one360_status_404_when_session_missing():
    client = TestClient(app)
    resp = client.get("/api/session/does-not-exist/baseline/one360-status")
    assert resp.status_code == 404


def test_one360_status_all_missing_initially(tmp_path, monkeypatch):
    session_id, _ = _make_session()
    monkeypatch.setenv("ARCHIMEDES_ONE360_DIR", str(tmp_path))

    client = TestClient(app)
    resp = client.get(f"/api/session/{session_id}/baseline/one360-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["downloaded"] == {"cloud": False, "onprem": False, "contracts": False}
    assert body["dir"] == str(tmp_path)


def test_one360_status_detects_downloaded_files(tmp_path, monkeypatch):
    session_id, _ = _make_session()
    (tmp_path / "Cloud-Systems-Table-2024-01-15.xlsx").write_bytes(b"")
    (tmp_path / "System-Landscape-Details-Table-2024-01-15.xlsx").write_bytes(b"")
    (tmp_path / "Purchased-Solutions-Table-LPR-2024-01-15.xlsx").write_bytes(b"")
    monkeypatch.setenv("ARCHIMEDES_ONE360_DIR", str(tmp_path))

    client = TestClient(app)
    resp = client.get(f"/api/session/{session_id}/baseline/one360-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["downloaded"] == {"cloud": True, "onprem": True, "contracts": True}


def test_one360_status_returns_matched_paths(tmp_path, monkeypatch):
    session_id, _ = _make_session()
    cloud = tmp_path / "Cloud-Systems-Table-2024-01-15.xlsx"
    cloud.write_bytes(b"")
    monkeypatch.setenv("ARCHIMEDES_ONE360_DIR", str(tmp_path))

    client = TestClient(app)
    resp = client.get(f"/api/session/{session_id}/baseline/one360-status")
    body = resp.json()
    assert body["paths"]["cloud"] == str(cloud)
    assert body["paths"]["onprem"] is None
    assert body["paths"]["contracts"] is None
