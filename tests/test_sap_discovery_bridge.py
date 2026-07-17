"""Tests for pipeline.sap_discovery.make_create_factsheet_bridge."""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

import pipeline
from pipeline.sap_discovery import make_create_factsheet_bridge


def test_bridge_delegates_to_pipeline_write_create_factsheet():
    fake_write = type("W", (), {})()
    fake_write.create_factsheet = lambda type_, name, attributes: {
        "id": "fs-new-1",
        "displayName": name,
    }

    with patch.object(pipeline, "write", fake_write, create=True), patch.dict(
        "sys.modules", {"pipeline.write": fake_write}
    ):
        bridge = make_create_factsheet_bridge()
        result = bridge({
            "type": "Application",
            "name": "SAP Ariba",
            "product": "SAP Ariba",
            "classification": "SaaS_Product",
        })

    assert result == {"id": "fs-new-1"}


def test_bridge_raises_when_pipeline_write_lacks_create_factsheet():
    fake_write = type("W", (), {})()  # no create_factsheet attribute

    with patch.object(pipeline, "write", fake_write, create=True), patch.dict(
        "sys.modules", {"pipeline.write": fake_write}
    ):
        with pytest.raises(AttributeError, match="create_factsheet"):
            make_create_factsheet_bridge()
