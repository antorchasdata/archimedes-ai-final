"""Tests for pipeline.leanix_auth — shared OAuth2 bearer cache."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from pipeline import leanix_auth


@pytest.fixture(autouse=True)
def _reset_token_cache():
    """Reset the module-level token cache before every test."""
    leanix_auth._token_cache["token"] = None
    leanix_auth._token_cache["expires_at"] = 0.0
    yield
    leanix_auth._token_cache["token"] = None
    leanix_auth._token_cache["expires_at"] = 0.0


def test_get_bearer_calls_token_endpoint_with_basic_auth():
    """First call POSTs to /services/mtm/v1/oauth2/token with Basic auth and returns access_token."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "JWT", "expires_in": 3600}
    mock_resp.raise_for_status.return_value = None

    with patch("pipeline.leanix_auth.requests.post", return_value=mock_resp) as post:
        token = leanix_auth.get_bearer("https://x.leanix.net", "tok")

    assert token == "JWT"
    post.assert_called_once()
    args, kwargs = post.call_args
    assert args[0] == "https://x.leanix.net/services/mtm/v1/oauth2/token"
    assert kwargs["data"] == {"grant_type": "client_credentials"}
    assert kwargs["auth"] == ("apitoken", "tok")
    assert kwargs["timeout"] == 30


def test_get_bearer_returns_cached_within_window():
    """Second call within (expires_at - 60s) must NOT re-POST."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "JWT1", "expires_in": 3600}
    mock_resp.raise_for_status.return_value = None

    with patch("pipeline.leanix_auth.requests.post", return_value=mock_resp) as post, \
         patch("pipeline.leanix_auth.time.time", return_value=1000.0):
        # First call populates the cache with expires_at = 1000 + 3600 = 4600
        first = leanix_auth.get_bearer("https://x", "tok")
        # Second call at t=2000 is well within (4600 - 60) — must reuse cache
        with patch("pipeline.leanix_auth.time.time", return_value=2000.0):
            second = leanix_auth.get_bearer("https://x", "tok")

    assert first == "JWT1"
    assert second == "JWT1"
    assert post.call_count == 1


def test_get_bearer_refreshes_when_near_expiry():
    """When time() is past (expires_at - 60s), get_bearer must re-POST."""
    first_resp = MagicMock()
    first_resp.json.return_value = {"access_token": "JWT_OLD", "expires_in": 120}
    first_resp.raise_for_status.return_value = None
    second_resp = MagicMock()
    second_resp.json.return_value = {"access_token": "JWT_NEW", "expires_in": 3600}
    second_resp.raise_for_status.return_value = None

    with patch("pipeline.leanix_auth.requests.post",
               side_effect=[first_resp, second_resp]) as post:
        # First call at t=1000 → expires_at = 1120, refresh window starts at 1060
        with patch("pipeline.leanix_auth.time.time", return_value=1000.0):
            first = leanix_auth.get_bearer("https://x", "tok")
        # Second call at t=1100 → inside the 60s safety margin, MUST refresh
        with patch("pipeline.leanix_auth.time.time", return_value=1100.0):
            second = leanix_auth.get_bearer("https://x", "tok")

    assert first == "JWT_OLD"
    assert second == "JWT_NEW"
    assert post.call_count == 2
