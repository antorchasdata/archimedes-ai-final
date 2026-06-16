import pytest
from fastapi.testclient import TestClient
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from archimedes_wizard import app, _sessions

client = TestClient(app)


def test_create_session_stores_leanix_creds():
    resp = client.post("/api/session", json={
        "client_name": "TestCo",
        "leanix_base_url": "https://test.leanix.net",
        "leanix_api_token": "tok123",
    })
    assert resp.status_code == 200
    data = resp.json()
    sid = data["session_id"]
    sess = _sessions[sid]
    assert sess["leanix_base_url"] == "https://test.leanix.net"
    assert sess["leanix_api_token"] == "tok123"


def test_create_session_without_creds_leaves_none():
    resp = client.post("/api/session", json={"client_name": "TestCo2"})
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    sess = _sessions[sid]
    assert sess.get("leanix_base_url") is None
    assert sess.get("leanix_api_token") is None


def test_leanix_creds_prefers_session_over_env(monkeypatch):
    monkeypatch.setenv("LEANIX_BASE_URL", "https://env.leanix.net")
    monkeypatch.setenv("LEANIX_API_TOKEN", "env_token")
    from archimedes_wizard import _leanix_creds
    sess = {"leanix_base_url": "https://sess.leanix.net", "leanix_api_token": "sess_token"}
    base_url, api_token = _leanix_creds(sess)
    assert base_url == "https://sess.leanix.net"
    assert api_token == "sess_token"


def test_leanix_creds_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("LEANIX_BASE_URL", "https://env.leanix.net")
    monkeypatch.setenv("LEANIX_API_TOKEN", "env_token")
    from archimedes_wizard import _leanix_creds
    sess = {"leanix_base_url": None, "leanix_api_token": None}
    base_url, api_token = _leanix_creds(sess)
    assert base_url == "https://env.leanix.net"
    assert api_token == "env_token"


import json

def test_get_workspaces_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("archimedes_wizard.WORKSPACES_PATH", tmp_path / "workspaces.json")
    resp = client.get("/api/workspaces")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "workspaces": []}


def test_post_workspaces_saves_and_returns_no_token(tmp_path, monkeypatch):
    monkeypatch.setattr("archimedes_wizard.WORKSPACES_PATH", tmp_path / "workspaces.json")
    resp = client.post("/api/workspaces", json={
        "name": "Test WS", "base_url": "https://test.leanix.net", "api_token": "secret123"
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verify file written with token
    data = json.loads((tmp_path / "workspaces.json").read_text())
    assert data["workspaces"][0]["api_token"] == "secret123"

    # Verify GET response excludes token
    resp2 = client.get("/api/workspaces")
    ws_list = resp2.json()["workspaces"]
    assert len(ws_list) == 1
    assert "api_token" not in ws_list[0]
    assert ws_list[0]["name"] == "Test WS"


def test_post_workspaces_upserts_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr("archimedes_wizard.WORKSPACES_PATH", tmp_path / "workspaces.json")
    client.post("/api/workspaces", json={"name": "WS1", "base_url": "https://a.net", "api_token": "tok1"})
    client.post("/api/workspaces", json={"name": "WS1", "base_url": "https://b.net", "api_token": "tok2"})
    data = json.loads((tmp_path / "workspaces.json").read_text())
    assert len(data["workspaces"]) == 1
    assert data["workspaces"][0]["base_url"] == "https://b.net"


def test_create_session_resolves_workspace_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr("archimedes_wizard.WORKSPACES_PATH", tmp_path / "workspaces.json")
    # First save a workspace
    client.post("/api/workspaces", json={
        "name": "Prod WS",
        "base_url": "https://prod.leanix.net",
        "api_token": "prodtok",
    })
    # Now create a session using just the workspace name
    resp = client.post("/api/session", json={
        "client_name": "Acme",
        "leanix_workspace": "Prod WS",
    })
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    from archimedes_wizard import _sessions
    sess = _sessions[sid]
    assert sess["leanix_base_url"] == "https://prod.leanix.net"
    assert sess["leanix_api_token"] == "prodtok"
