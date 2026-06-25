# tests/test_catalog_report.py
from pipeline.catalog_report import build_rows

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
