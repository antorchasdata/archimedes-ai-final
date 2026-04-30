"""
tests/test_validate.py — Unit tests for the validation step.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.validate import _validate_one

# Minimal short_name_index for tests
SHORT_NAME_INDEX = {
    "Operational Procurement":           "Sourcing and Procurement / Operational Procurement",
    "Procurement Contract Management":   "Sourcing and Procurement / Procurement Contract Management",
    "Accounting and Financial Close":    "Finance / Accounting and Financial Close",
    "Financial Planning and Analysis":   "Finance / Financial Planning and Analysis",
    "Inventory Management":              "Supply Chain Execution / Inventory Management",
    "Delivery Management":               "Supply Chain Execution / Delivery Management",
}

RSA_NAMES = {
    "SAP S/4HANA",
    "SAP Ariba, SAP S/4HANA",
    "SAP Analytics Cloud, SAP S/4HANA",
    "SAP Integration Suite, SAP S/4HANA",
}

VALID_COMMENT = (
    "El proceso de compras en S/4HANA gestiona el ciclo completo pedido-recepción-factura. "
    "La entrada de mercancías se registra con el movimiento 101 en MIGO (entrada de mercancías). "
    "Transacciones: ME21N (crear pedido), MIGO (entrada de mercancías), MIRO (verificar factura). "
    "Fiori app 'Manage Purchase Orders' (F2229). "
    "OSS Note 2537150 – Goods receipt and inbound delivery in S/4HANA. "
    "OSS Note 2789430 – Three-way match invoice verification in S/4HANA."
)


def _req(**overrides):
    base = {
        "id": "REQ_001",
        "module": "SAP S/4HANA – MM",
        "bcs": ["Operational Procurement", "Procurement Contract Management"],
        "rsa": "SAP S/4HANA",
        "coverage": "Total",
        "dev": "No",
        "dev_exp": "",
        "ext_apps": "",
        "licensing": "Básico",
        "comment": VALID_COMMENT,
    }
    base.update(overrides)
    return base


# ── Happy path ────────────────────────────────────────────────────────────────

def test_valid_requirement_passes():
    errors = _validate_one(_req(), SHORT_NAME_INDEX, RSA_NAMES)
    assert errors == []


# ── bcs ───────────────────────────────────────────────────────────────────────

def test_duplicate_bc_full_paths_fail():
    errors = _validate_one(
        _req(bcs=["Operational Procurement", "Operational Procurement"]),
        SHORT_NAME_INDEX, RSA_NAMES,
    )
    assert any("duplicate" in e for e in errors)


def test_bc_not_in_catalog_fails():
    errors = _validate_one(
        _req(bcs=["Operational Procurement", "NonExistent BC"]),
        SHORT_NAME_INDEX, RSA_NAMES,
    )
    assert any("not found in RBA catalog" in e for e in errors)


def test_bc_same_domain_different_subbc_passes():
    errors = _validate_one(
        _req(bcs=["Accounting and Financial Close", "Financial Planning and Analysis"]),
        SHORT_NAME_INDEX, RSA_NAMES,
    )
    assert errors == []


# ── rsa ───────────────────────────────────────────────────────────────────────

def test_invalid_rsa_fails():
    errors = _validate_one(_req(rsa="Ariba"), SHORT_NAME_INDEX, RSA_NAMES)
    assert any("not in RSA catalog" in e for e in errors)


def test_ariba_rsa_requires_adicional_licensing():
    errors = _validate_one(
        _req(rsa="SAP Ariba, SAP S/4HANA", licensing="Básico"),
        SHORT_NAME_INDEX, RSA_NAMES,
    )
    assert any("Adicional" in e for e in errors)


def test_ariba_rsa_with_adicional_passes():
    errors = _validate_one(
        _req(rsa="SAP Ariba, SAP S/4HANA", licensing="Adicional"),
        SHORT_NAME_INDEX, RSA_NAMES,
    )
    assert errors == []


# ── comment ───────────────────────────────────────────────────────────────────

def test_comment_with_url_fails():
    errors = _validate_one(
        _req(comment=VALID_COMMENT + " See https://help.sap.com/docs"),
        SHORT_NAME_INDEX, RSA_NAMES,
    )
    assert any("URL" in e for e in errors)


def test_comment_missing_fiori_fails():
    comment_no_fiori = VALID_COMMENT.replace("(F2229)", "")
    errors = _validate_one(_req(comment=comment_no_fiori), SHORT_NAME_INDEX, RSA_NAMES)
    assert any("Fiori" in e for e in errors)


def test_comment_with_only_one_oss_note_fails():
    comment_one_oss = (
        "Proceso estándar S/4HANA con movimiento 101. "
        "Transacciones: ME21N (crear pedido). "
        "Fiori app 'Manage Purchase Orders' (F2229). "
        "OSS Note 2537150 – Goods receipt in S/4HANA."
    )
    errors = _validate_one(_req(comment=comment_one_oss), SHORT_NAME_INDEX, RSA_NAMES)
    assert any("OSS Note" in e for e in errors)


# ── missing fields ────────────────────────────────────────────────────────────

def test_missing_module_fails():
    errors = _validate_one(_req(module=""), SHORT_NAME_INDEX, RSA_NAMES)
    assert any("module" in e for e in errors)


def test_invalid_coverage_fails():
    errors = _validate_one(_req(coverage="Fully Covered"), SHORT_NAME_INDEX, RSA_NAMES)
    assert any("coverage" in e for e in errors)
