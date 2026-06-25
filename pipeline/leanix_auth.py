"""Shared LeanIX OAuth2 client_credentials bearer cache.

All LeanIX REST callers (Reference Catalog resolver, write pipeline,
LDIF push) authenticate by exchanging the workspace API token for an
OAuth access token at /services/mtm/v1/oauth2/token. Keeping the
handshake in one place avoids the three-way duplication that existed
previously and prevents auth drift between callers.
"""
from __future__ import annotations

import time

import requests

_token_cache: dict = {"token": None, "expires_at": 0.0}


def get_bearer(base_url: str, api_token: str) -> str:
    """Return a valid Bearer JWT for LeanIX REST calls.

    Caches the token at module level and refreshes when within 60s of
    expiry. Raises requests.HTTPError on token-endpoint failure —
    callers decide what to do (most wrap in try/except and degrade
    gracefully).
    """
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    resp = requests.post(
        f"{base_url}/services/mtm/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=("apitoken", api_token),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    return _token_cache["token"]
