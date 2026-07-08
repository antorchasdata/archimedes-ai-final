"""Utility helpers for the ONE360 extractor skill.

This module does NOT drive Playwright. It provides pure helpers used by the
Claude Code skill that orchestrates a Playwright MCP browser:

- deep-link URL builders for ONE360 pages
- filename glob patterns for the 3 exports (cloud, onprem, contracts)
- download-dir snapshot / new-file detection helpers
"""

from __future__ import annotations

import fnmatch
import os
import re
import time
from pathlib import Path

ONE360_BASE_URL = "https://one360.for.sap"
ONE360_LANDING_URL = f"{ONE360_BASE_URL}/experiences/1csw/pages/landing-page"

_SINGLE_CUSTOMER = f"{ONE360_BASE_URL}/experiences/1csw/pages/single-customer"

FILENAME_PATTERNS: dict[str, str] = {
    "cloud": "Cloud-Systems-Table-*.xlsx",
    "onprem": "System-Landscape-Details-Table-*.xlsx",
    "contracts": "Purchased-Solutions-Table*LPR-*.xlsx",
}

_ACCOUNT_ID_RE = re.compile(r"accountId=([^&]+)")


def build_download_urls(account_id: str) -> dict[str, str]:
    if not account_id or not account_id.strip():
        raise ValueError("account_id must not be empty")
    base = f"{_SINGLE_CUSTOMER}?accountId={account_id}"
    return {
        "cloud": f"{base}&tab=system_landscape&nf-selected-section=system-landscape-cloud",
        "onprem": f"{base}&tab=system_landscape&nf-selected-section=system-landscape-onpremise",
        "contracts": f"{base}&tab=contracts&nf-selected-section=purchased-solutions",
    }


def extract_account_id_from_url(url: str) -> str | None:
    m = _ACCOUNT_ID_RE.search(url)
    return m.group(1) if m else None


def snapshot_dir(download_dir: Path) -> set[str]:
    if not download_dir.exists():
        return set()
    return {p.name for p in download_dir.iterdir() if p.is_file() and p.suffix == ".xlsx"}


def find_new_matching_file(
    download_dir: Path, before: set[str], pattern: str
) -> Path | None:
    if not download_dir.exists():
        return None
    candidates = [
        p
        for p in download_dir.iterdir()
        if p.is_file()
        and p.suffix == ".xlsx"
        and p.name not in before
        and fnmatch.fnmatch(p.name, pattern)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def detect_new_file(
    download_dir: Path,
    before: set[str],
    pattern: str,
    timeout: float = 110,
    poll_interval: float = 1.0,
) -> Path:
    deadline = time.monotonic() + timeout
    while True:
        match = find_new_matching_file(download_dir, before, pattern)
        if match is not None:
            return match
        # Detect unexpected new .xlsx files (wrong file downloaded)
        if download_dir.exists():
            new_files = [
                p.name
                for p in download_dir.iterdir()
                if p.is_file() and p.suffix == ".xlsx" and p.name not in before
            ]
            wrong = [name for name in new_files if not fnmatch.fnmatch(name, pattern)]
            if wrong:
                raise ValueError(
                    f"Unexpected download {wrong[0]!r} does not match pattern {pattern!r}"
                )
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"No file matching {pattern!r} appeared in {download_dir} within {timeout}s"
            )
        time.sleep(poll_interval)
