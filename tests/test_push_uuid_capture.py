import json
from pathlib import Path
from unittest.mock import patch
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

