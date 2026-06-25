"""Unit tests for pipeline.reference_catalog."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.reference_catalog import ResolvedMatch, ReferenceCatalogResolver, _normalize_name, _source_for_type, _external_id_prefix
import pytest


def test_resolved_match_defaults():
    m = ResolvedMatch(name="SAP S/4HANA")
    assert m.name == "SAP S/4HANA"
    assert m.external_id is None
    assert m.catalog_uuid is None
    assert m.display_name is None
    assert m.confidence == "NONE"
    assert m.status == "CUSTOM"
    assert m.fields == {}


def test_resolver_construct():
    r = ReferenceCatalogResolver(base_url="https://example.com", api_token="tok")
    assert r.base_url == "https://example.com"
    assert r.api_token == "tok"
    assert r.interactive is True


def test_normalize_lowercases_and_collapses_whitespace():
    assert _normalize_name("SAP S/4HANA") == "sap s/4hana"
    assert _normalize_name("  SAP   S/4HANA  ") == "sap s/4hana"
    assert _normalize_name("SAP\tS/4HANA\n") == "sap s/4hana"


def test_normalize_idempotent():
    once = _normalize_name("SAP S/4HANA")
    twice = _normalize_name(once)
    assert once == twice


def test_source_for_type_application():
    assert _source_for_type("Application") == "saas"


def test_source_for_type_itcomponent():
    assert _source_for_type("ITComponent") == "ltls"


def test_source_for_type_invalid():
    with pytest.raises(ValueError):
        _source_for_type("BusinessCapability")


def test_external_id_prefix():
    assert _external_id_prefix("Application") == "lx_APP_"
    assert _external_id_prefix("ITComponent") == "lx_ITC_"


from unittest.mock import patch, MagicMock


def _mk_response(json_body, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return r


def test_search_by_name_returns_candidates():
    r = ReferenceCatalogResolver("https://x", "tok")
    payload = [
        {
            "alreadyLinked": False,
            "factSheet": {
                "id": "uuid-1",
                "externalId": "lx_APP_000123",
                "displayName": "SAP S/4HANA",
                "type": "Application",
            },
        }
    ]
    with patch("pipeline.reference_catalog.requests.get",
               return_value=_mk_response(payload)) as get:
        candidates = r._search_by_name("Application", "SAP S/4HANA")
    assert len(candidates) == 1
    assert candidates[0]["factSheet"]["externalId"] == "lx_APP_000123"
    called_url = get.call_args[0][0]
    assert "/services/reference-data/v1/source/saas/fact-sheets" in called_url


def test_search_by_name_http_error_returns_empty():
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch("pipeline.reference_catalog.requests.get",
               return_value=_mk_response({}, status=500)):
        candidates = r._search_by_name("Application", "Anything")
    assert candidates == []


def test_search_by_name_short_query_skipped():
    """API requires min 2 chars — a 1-char name must be skipped, not sent."""
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch("pipeline.reference_catalog.requests.get") as get:
        candidates = r._search_by_name("Application", "X")
    assert candidates == []
    get.assert_not_called()


def test_fetch_detail_returns_fields():
    r = ReferenceCatalogResolver("https://x", "tok")
    payload = {
        "id": "uuid-1",
        "externalId": "lx_APP_000123",
        "displayName": "SAP S/4HANA",
        "description": "ERP",
        "fields": [
            {"name": "lxHostingType", "value": "saas"},
            {"name": "productCategory", "value": "ERP"},
        ],
        "relations": [
            {"name": "relApplicationToProvider",
             "targetFactSheet": {"displayName": "SAP"}},
        ],
    }
    with patch("pipeline.reference_catalog.requests.get",
               return_value=_mk_response(payload)):
        detail = r._fetch_detail("Application", "lx_APP_000123")
    assert detail["description"] == "ERP"
    assert detail["fields"]["lxHostingType"] == "saas"
    assert detail["fields"]["productCategory"] == "ERP"
    assert detail["fields"]["provider"] == "SAP"


def test_fetch_detail_http_error_returns_empty():
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch("pipeline.reference_catalog.requests.get",
               return_value=_mk_response({}, status=500)):
        detail = r._fetch_detail("Application", "lx_APP_000123")
    assert detail == {}


def test_probe_create_returns_uuid():
    r = ReferenceCatalogResolver("https://x", "tok")
    gql_resp = {"data": {"createFactSheet": {"factSheet": {"id": "probe-uuid-1"}}}}
    with patch("pipeline.reference_catalog.requests.post",
               return_value=_mk_response(gql_resp)) as post:
        fs_id = r._probe_create("Application", "Probe Name")
    assert fs_id == "probe-uuid-1"
    body = post.call_args.kwargs["json"]
    assert "createFactSheet" in body["query"]


def test_probe_create_failure_returns_none():
    r = ReferenceCatalogResolver("https://x", "tok")
    with patch("pipeline.reference_catalog.requests.post",
               return_value=_mk_response({"errors": [{"message": "boom"}]})):
        assert r._probe_create("Application", "X") is None


def test_probe_rename_returns_true():
    r = ReferenceCatalogResolver("https://x", "tok")
    gql_resp = {"data": {"updateFactSheet": {"factSheet": {"id": "probe-uuid-1"}}}}
    with patch("pipeline.reference_catalog.requests.post",
               return_value=_mk_response(gql_resp)):
        assert r._probe_rename("probe-uuid-1", "New Name") is True


def test_probe_archive_returns_true():
    r = ReferenceCatalogResolver("https://x", "tok")
    gql_resp = {"data": {"updateFactSheet": {"factSheet": {"id": "probe-uuid-1"}}}}
    with patch("pipeline.reference_catalog.requests.post",
               return_value=_mk_response(gql_resp)):
        assert r._probe_archive("probe-uuid-1") is True
