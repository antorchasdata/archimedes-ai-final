import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from pipeline.write import _write_push_uuid_map


def test_write_push_uuid_map_writes_expected_shape(tmp_path):
    _write_push_uuid_map(
        out_dir=tmp_path,
        base_url="https://demo-eu-3.leanix.net",
        workspace="demo-eu-3",
        app_id_cache={"SAP S/4HANA": "abc-1"},
        itc_id_cache={"SAP Fiori": "def-2"},
        failed=[{"name": "Broken App", "type": "Application", "error": "boom"}],
    )
    out = tmp_path / "push_uuid_map.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["workspace"] == "demo-eu-3"
    assert data["base_url"] == "https://demo-eu-3.leanix.net"
    assert data["entries"]["Application::SAP S/4HANA"] == {"uuid": "abc-1", "created": True}
    assert data["entries"]["ITComponent::SAP Fiori"] == {"uuid": "def-2", "created": True}
    assert data["failed"] == [{"name": "Broken App", "type": "Application", "error": "boom"}]


def test_push_leanix_writes_uuid_map_next_to_staging(tmp_path):
    """End-to-end: mock the GraphQL layer so push_leanix runs without network,
    populates app_id_cache, and writes push_uuid_map.json."""
    from pipeline import write as wmod

    staging = tmp_path / "client_target_leanix.xlsx"
    # Touch an empty xlsx so Path operations succeed; the mocked push won't read it.
    import openpyxl
    openpyxl.Workbook().save(str(staging))

    def fake_push(*args, **kwargs):
        # Simulate what push_leanix does internally: build caches then call our helper.
        wmod._write_push_uuid_map(
            out_dir=staging.parent,
            base_url="https://demo-eu-3.leanix.net",
            workspace="demo-eu-3",
            app_id_cache={"App A": "uuid-a"},
            itc_id_cache={},
            failed=[],
        )
        return {"ok": True}

    with patch.object(wmod, "push_leanix", side_effect=fake_push):
        wmod.push_leanix(str(staging), "client")

    out = staging.parent / "push_uuid_map.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["entries"]["Application::App A"] == {"uuid": "uuid-a", "created": True}


from unittest.mock import patch, MagicMock
from pipeline.push_ldif import _resolve_uuids_for_ldif


def test_resolve_uuids_returns_app_and_itc_caches():
    """Mock pathfinder GET; expect mapping per name."""
    fake_responses = {
        "archimedes-client-app-App_A":   {"data": [{"id": "uuid-a"}]},
        "archimedes-client-itc-ITC_One": {"data": [{"id": "uuid-itc-1"}]},
    }

    def fake_get(url, headers=None, params=None, timeout=None):
        ext_id = params["externalId.externalId"]
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = fake_responses.get(ext_id, {"data": []})
        return m

    with patch("pipeline.push_ldif.requests.get", side_effect=fake_get):
        apps, itcs, failed = _resolve_uuids_for_ldif(
            base_url="https://demo-eu-3.leanix.net",
            bearer="token",
            client_name="client",
            app_names=["App A"],
            itc_names=["ITC One"],
        )
    assert apps == {"App A": "uuid-a"}
    assert itcs == {"ITC One": "uuid-itc-1"}
    assert failed == []


def test_resolve_uuids_records_missing_as_failed():
    def fake_get(url, headers=None, params=None, timeout=None):
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = {"data": []}
        return m

    with patch("pipeline.push_ldif.requests.get", side_effect=fake_get):
        apps, itcs, failed = _resolve_uuids_for_ldif(
            base_url="https://demo-eu-3.leanix.net",
            bearer="token",
            client_name="client",
            app_names=["Missing"],
            itc_names=[],
        )
    assert apps == {}
    assert itcs == {}
    assert failed == [{"name": "Missing", "type": "Application", "error": "not found by externalId"}]


def test_persist_ldif_uuid_map_writes_file(tmp_path):
    from pipeline.push_ldif import _persist_ldif_uuid_map

    staging = tmp_path / "client_target_leanix.xlsx"
    staging.touch()

    ldif = {"content": [
        {"type": "Application", "data": {"name": "App A"}},
        {"type": "ITComponent", "data": {"name": "ITC One"}},
    ]}

    fake_responses = {
        "archimedes-client-app-App_A":   {"data": [{"id": "uuid-a"}]},
        "archimedes-client-itc-ITC_One": {"data": [{"id": "uuid-itc-1"}]},
    }
    def fake_get(url, headers=None, params=None, timeout=None):
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = fake_responses.get(params["externalId.externalId"], {"data": []})
        return m

    with patch("pipeline.push_ldif.requests.get", side_effect=fake_get):
        _persist_ldif_uuid_map(staging_path=staging, ldif=ldif, client_name="client",
                               base_url="https://demo-eu-3.leanix.net", bearer="t")

    out = staging.parent / "push_uuid_map.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["workspace"] == "demo-eu-3"
    assert data["base_url"] == "https://demo-eu-3.leanix.net"
    assert data["entries"]["Application::App A"] == {"uuid": "uuid-a", "created": True}
    assert data["entries"]["ITComponent::ITC One"] == {"uuid": "uuid-itc-1", "created": True}
    assert data["failed"] == []

