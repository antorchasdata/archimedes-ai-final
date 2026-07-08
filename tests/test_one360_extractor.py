"""Tests for pipeline.one360_extractor."""

from __future__ import annotations

import fnmatch
import time
from pathlib import Path

import pytest

from pipeline.one360_extractor import (
    FILENAME_PATTERNS,
    build_download_urls,
    detect_new_file,
    extract_account_id_from_url,
    find_new_matching_file,
    snapshot_dir,
)


# ── build_download_urls ────────────────────────────────────────────────────────

def test_build_download_urls_returns_all_three_keys():
    urls = build_download_urls("ACC123")
    assert set(urls.keys()) == {"cloud", "onprem", "contracts"}
    for url in urls.values():
        assert "ACC123" in url


def test_build_download_urls_uses_correct_sections():
    urls = build_download_urls("ACC123")
    assert "system-landscape-cloud" in urls["cloud"]
    assert "system-landscape-onpremise" in urls["onprem"]
    assert "purchased-solutions" in urls["contracts"]


def test_build_download_urls_rejects_empty_account_id():
    with pytest.raises(ValueError):
        build_download_urls("")
    with pytest.raises(ValueError):
        build_download_urls("   ")


# ── extract_account_id_from_url ────────────────────────────────────────────────

def test_extract_account_id_from_url_present():
    url = (
        "https://one360.for.sap/experiences/1csw/pages/single-customer"
        "?accountId=ABC-999&tab=system_landscape"
    )
    assert extract_account_id_from_url(url) == "ABC-999"


def test_extract_account_id_from_url_absent():
    url = "https://one360.for.sap/experiences/1csw/pages/landing-page"
    assert extract_account_id_from_url(url) is None


# ── FILENAME_PATTERNS ──────────────────────────────────────────────────────────

def test_filename_patterns_match_real_examples():
    assert fnmatch.fnmatch("Cloud-Systems-Table-2024-01-15.xlsx", FILENAME_PATTERNS["cloud"])
    assert fnmatch.fnmatch(
        "System-Landscape-Details-Table-2024-01-15.xlsx", FILENAME_PATTERNS["onprem"]
    )
    assert fnmatch.fnmatch(
        "Purchased-Solutions-Table-LPR-2024-01-15.xlsx", FILENAME_PATTERNS["contracts"]
    )
    assert fnmatch.fnmatch(
        "Purchased-Solutions-Table---LPR-2024-01-15.xlsx", FILENAME_PATTERNS["contracts"]
    )


def test_filename_patterns_reject_wrong_files():
    for pattern in FILENAME_PATTERNS.values():
        assert not fnmatch.fnmatch("Something-Else.xlsx", pattern)


# ── snapshot_dir ───────────────────────────────────────────────────────────────

def test_snapshot_dir_empty(tmp_path):
    assert snapshot_dir(tmp_path) == set()


def test_snapshot_dir_missing(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert snapshot_dir(missing) == set()


def test_snapshot_dir_returns_basenames_only(tmp_path):
    (tmp_path / "a.xlsx").write_bytes(b"")
    (tmp_path / "b.xlsx").write_bytes(b"")
    (tmp_path / "c.txt").write_bytes(b"")
    result = snapshot_dir(tmp_path)
    assert result == {"a.xlsx", "b.xlsx"}


# ── find_new_matching_file ─────────────────────────────────────────────────────

def test_find_new_matching_file(tmp_path):
    old = tmp_path / "Cloud-Systems-Table-2024-01-01.xlsx"
    old.write_bytes(b"")
    before = snapshot_dir(tmp_path)
    time.sleep(0.01)
    new = tmp_path / "Cloud-Systems-Table-2024-01-15.xlsx"
    new.write_bytes(b"")
    result = find_new_matching_file(tmp_path, before, FILENAME_PATTERNS["cloud"])
    assert result == new


def test_find_new_matching_file_ignores_non_matching(tmp_path):
    before = snapshot_dir(tmp_path)
    (tmp_path / "Unrelated.xlsx").write_bytes(b"")
    result = find_new_matching_file(tmp_path, before, FILENAME_PATTERNS["cloud"])
    assert result is None


# ── detect_new_file ────────────────────────────────────────────────────────────

def test_detect_new_file_success(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    before: set[str] = set()
    target = tmp_path / "Cloud-Systems-Table-2024-01-15.xlsx"
    target.write_bytes(b"")
    result = detect_new_file(tmp_path, before, FILENAME_PATTERNS["cloud"], timeout=1)
    assert result == target


def test_detect_new_file_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    before: set[str] = set()
    with pytest.raises(TimeoutError):
        detect_new_file(
            tmp_path, before, FILENAME_PATTERNS["cloud"], timeout=0.1, poll_interval=0.05
        )


def test_detect_new_file_wrong_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    before: set[str] = set()
    wrong = tmp_path / "Wrong-File.xlsx"
    wrong.write_bytes(b"")
    with pytest.raises(ValueError) as exc_info:
        detect_new_file(tmp_path, before, FILENAME_PATTERNS["cloud"], timeout=1)
    assert "Wrong-File.xlsx" in str(exc_info.value)
