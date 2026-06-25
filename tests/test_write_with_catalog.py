"""Tests for ReferenceCatalogResolver integration into write_leanix_excel.

Uses the ARCHIMEDES_USE_CATALOG_RESOLVER feature flag to gate resolver activation.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from pipeline.reference_catalog import ResolvedMatch
from pipeline import write as write_mod


def _minimal_enriched():
    """Two requirements → two distinct RSA apps."""
    return [
        {
            "id": "R1", "description": "x", "area": "",
            "module": "FIN", "bcs": ["Finance"], "rsa": "SAP S/4HANA",
            "coverage": "Total", "dev": "", "dev_exp": "",
            "ext_apps": "", "licensing": "", "comment": "",
        },
        {
            "id": "R2", "description": "y", "area": "",
            "module": "HR", "bcs": ["HR"], "rsa": "SAP SuccessFactors",
            "coverage": "Total", "dev": "", "dev_exp": "",
            "ext_apps": "", "licensing": "", "comment": "",
        },
    ]


def test_flag_off_resolver_not_called(tmp_path, monkeypatch):
    monkeypatch.delenv("ARCHIMEDES_USE_CATALOG_RESOLVER", raising=False)
    out = tmp_path / "x.xlsx"
    with patch.object(write_mod, "ReferenceCatalogResolver") as Resolver:
        write_mod.write_leanix_excel(
            enriched=_minimal_enriched(),
            bcs_index={},
            output_path=out,
            client_name="ACME",
        )
    Resolver.assert_not_called()
    assert out.exists()


def test_flag_on_resolver_called_and_externalid_written(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "true")

    fake_resolver = MagicMock()
    fake_resolver.resolve.side_effect = lambda fs_type, names: {
        n: ResolvedMatch(
            name=n,
            external_id=f"lx_APP_{i:03d}" if fs_type == "Application" else f"lx_ITC_{i:03d}",
            status="LINKED",
            confidence="VERYHIGH",
            display_name=n,
            fields={},
        )
        for i, n in enumerate(names, start=1)
    }
    out = tmp_path / "x.xlsx"
    with patch.object(write_mod, "ReferenceCatalogResolver", return_value=fake_resolver), \
         patch.object(write_mod, "_resolver_credentials", return_value=("https://x", "tok")):
        write_mod.write_leanix_excel(
            enriched=_minimal_enriched(),
            bcs_index={},
            output_path=out,
            client_name="ACME",
        )

    # resolver.resolve called for both types
    assert fake_resolver.resolve.call_count == 2
    types_called = [c.args[0] for c in fake_resolver.resolve.call_args_list]
    assert "Application" in types_called
    assert "ITComponent" in types_called

    # Verify externalId landed in the Application sheet
    import openpyxl
    wb = openpyxl.load_workbook(out)
    ws = wb["Application"]
    # Row 1 = technical keys
    headers = [c.value for c in ws[1]]
    ext_col = headers.index("externalId") + 1
    data_rows = [ws.cell(row=r, column=ext_col).value
                 for r in range(3, ws.max_row + 1)]
    assert any(v and v.startswith("lx_APP_") for v in data_rows)


def test_flag_on_cleanup_invoked(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "1")
    fake_resolver = MagicMock()
    fake_resolver.resolve.return_value = {}
    out = tmp_path / "x.xlsx"
    with patch.object(write_mod, "ReferenceCatalogResolver", return_value=fake_resolver), \
         patch.object(write_mod, "_resolver_credentials", return_value=("https://x", "tok")):
        write_mod.write_leanix_excel(
            enriched=_minimal_enriched(),
            bcs_index={},
            output_path=out,
            client_name="ACME",
        )
    fake_resolver.cleanup.assert_called_once()


def test_flag_on_resolver_failure_is_non_fatal(tmp_path, monkeypatch):
    """If resolver construction explodes, the Excel must still be written."""
    monkeypatch.setenv("ARCHIMEDES_USE_CATALOG_RESOLVER", "true")
    out = tmp_path / "x.xlsx"
    with patch.object(write_mod, "ReferenceCatalogResolver", side_effect=RuntimeError("boom")), \
         patch.object(write_mod, "_resolver_credentials", return_value=("https://x", "tok")):
        write_mod.write_leanix_excel(
            enriched=_minimal_enriched(),
            bcs_index={},
            output_path=out,
            client_name="ACME",
        )
    assert out.exists()
