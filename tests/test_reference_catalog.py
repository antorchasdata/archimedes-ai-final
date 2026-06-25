"""Unit tests for pipeline.reference_catalog."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.reference_catalog import ResolvedMatch, ReferenceCatalogResolver, _normalize_name


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
