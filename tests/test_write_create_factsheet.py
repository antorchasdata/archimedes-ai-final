"""Test para pipeline.write.create_factsheet (public entrypoint).

Verifies the top-level wrapper that pipeline.sap_discovery.make_create_factsheet_bridge()
consumes: signature (type_, name, attributes) → {"id": str}.
"""
from unittest.mock import MagicMock, patch

from pipeline import write as _write


def test_create_factsheet_returns_id_from_graphql():
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "data": {"createFactSheet": {"factSheet": {"id": "fs-123", "displayName": "Foo"}}}
    }
    with patch.dict(
        "os.environ",
        {"LEANIX_BASE_URL": "https://x.leanix.net", "LEANIX_API_TOKEN": "t"},
    ), patch("pipeline.write.get_bearer", return_value="bearer-token"), patch(
        "requests.post", return_value=fake_response
    ) as post_mock:
        result = _write.create_factsheet(type_="Application", name="Foo")

    assert result == {"id": "fs-123"}
    call = post_mock.call_args
    assert call.kwargs["json"]["variables"] == {"type": "Application", "name": "Foo"}


def test_create_factsheet_patches_attributes_after_creation():
    fake_create = MagicMock(status_code=200)
    fake_create.json.return_value = {
        "data": {"createFactSheet": {"factSheet": {"id": "fs-42", "displayName": "Bar"}}}
    }
    fake_patch = MagicMock(status_code=200)
    fake_patch.json.return_value = {"data": {"updateFactSheet": {"factSheet": {"id": "fs-42"}}}}

    with patch.dict(
        "os.environ",
        {"LEANIX_BASE_URL": "https://x.leanix.net", "LEANIX_API_TOKEN": "t"},
    ), patch("pipeline.write.get_bearer", return_value="bearer-token"), patch(
        "requests.post", side_effect=[fake_create, fake_patch]
    ) as post_mock:
        result = _write.create_factsheet(
            type_="Application",
            name="Bar",
            attributes={"product": "SAP S/4HANA"},
        )

    assert result == {"id": "fs-42"}
    assert post_mock.call_count == 2


def test_create_factsheet_ignores_none_attribute_values():
    fake_create = MagicMock(status_code=200)
    fake_create.json.return_value = {
        "data": {"createFactSheet": {"factSheet": {"id": "fs-9", "displayName": "Z"}}}
    }

    with patch.dict(
        "os.environ",
        {"LEANIX_BASE_URL": "https://x.leanix.net", "LEANIX_API_TOKEN": "t"},
    ), patch("pipeline.write.get_bearer", return_value="bearer-token"), patch(
        "requests.post", return_value=fake_create
    ) as post_mock:
        result = _write.create_factsheet(
            type_="Application",
            name="Z",
            attributes={"product": None},
        )

    assert result == {"id": "fs-9"}
    assert post_mock.call_count == 1  # sólo la creación, no el patch
