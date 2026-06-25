# tests/test_catalog_report.py
from pipeline.catalog_report import build_rows, sort_rows, count_rows

def test_build_rows_empty_inputs():
    rows = build_rows(
        resolution={"entries": []},
        uuid_map={"workspace": "demo-eu-3", "base_url": "https://demo-eu-3.leanix.net", "entries": {}, "failed": []},
    )
    assert rows == []


_UUID_MAP_EMPTY = {"workspace": "demo-eu-3", "base_url": "https://demo-eu-3.leanix.net", "entries": {}, "failed": []}

def test_linked_when_status_linked():
    res = {"entries": [{"name": "X", "type": "Application", "status": "LINKED", "confidence": "VERYHIGH", "external_id": "lx_APP_1"}]}
    rows = build_rows(res, _UUID_MAP_EMPTY)
    assert rows[0].status == "LINKED"

def test_review_when_high_confidence_custom():
    res = {"entries": [{"name": "X", "type": "Application", "status": "CUSTOM", "confidence": "HIGH"}]}
    rows = build_rows(res, _UUID_MAP_EMPTY)
    assert rows[0].status == "REVIEW"

def test_review_when_medium_confidence_custom():
    res = {"entries": [{"name": "X", "type": "Application", "status": "CUSTOM", "confidence": "MEDIUM"}]}
    rows = build_rows(res, _UUID_MAP_EMPTY)
    assert rows[0].status == "REVIEW"

def test_custom_when_low_confidence():
    res = {"entries": [{"name": "X", "type": "Application", "status": "CUSTOM", "confidence": "LOW"}]}
    rows = build_rows(res, _UUID_MAP_EMPTY)
    assert rows[0].status == "CUSTOM"

def test_custom_when_no_confidence():
    res = {"entries": [{"name": "X", "type": "Application", "status": "CUSTOM", "confidence": "NONE"}]}
    rows = build_rows(res, _UUID_MAP_EMPTY)
    assert rows[0].status == "CUSTOM"

def test_uuid_attached_when_present_in_map():
    res = {"entries": [{"name": "SAP S/4HANA", "type": "Application", "status": "LINKED", "confidence": "VERYHIGH"}]}
    umap = {"workspace": "demo-eu-3", "base_url": "https://demo-eu-3.leanix.net",
            "entries": {"Application::SAP S/4HANA": {"uuid": "abc123", "created": True}}, "failed": []}
    rows = build_rows(res, umap)
    assert rows[0].fs_uuid == "abc123"
    assert rows[0].push_failed is False

def test_uuid_missing_when_not_in_map():
    res = {"entries": [{"name": "Custom App", "type": "Application", "status": "CUSTOM", "confidence": "NONE"}]}
    umap = {"workspace": "demo-eu-3", "base_url": "https://demo-eu-3.leanix.net", "entries": {}, "failed": []}
    rows = build_rows(res, umap)
    assert rows[0].fs_uuid is None
    assert rows[0].push_failed is False

def test_push_failed_marked():
    res = {"entries": [{"name": "Broken App", "type": "Application", "status": "CUSTOM", "confidence": "NONE"}]}
    umap = {"workspace": "demo-eu-3", "base_url": "https://demo-eu-3.leanix.net",
            "entries": {}, "failed": [{"name": "Broken App", "type": "Application", "error": "boom"}]}
    rows = build_rows(res, umap)
    assert rows[0].fs_uuid is None
    assert rows[0].push_failed is True

def test_rows_sorted_linked_review_custom():
    res = {"entries": [
        {"name": "C", "type": "Application", "status": "CUSTOM",  "confidence": "NONE"},
        {"name": "L", "type": "Application", "status": "LINKED",  "confidence": "VERYHIGH"},
        {"name": "R", "type": "Application", "status": "CUSTOM",  "confidence": "HIGH"},
    ]}
    rows = sort_rows(build_rows(res, _UUID_MAP_EMPTY))
    assert [r.name for r in rows] == ["L", "R", "C"]

def test_counters():
    res = {"entries": [
        {"name": "L1", "type": "Application", "status": "LINKED",  "confidence": "VERYHIGH"},
        {"name": "L2", "type": "Application", "status": "LINKED",  "confidence": "VERYHIGH"},
        {"name": "R1", "type": "Application", "status": "CUSTOM",  "confidence": "HIGH"},
        {"name": "C1", "type": "Application", "status": "CUSTOM",  "confidence": "NONE"},
    ]}
    counts = count_rows(build_rows(res, _UUID_MAP_EMPTY))
    assert counts == {"LINKED": 2, "REVIEW": 1, "CUSTOM": 1}
