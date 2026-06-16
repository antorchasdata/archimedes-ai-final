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
