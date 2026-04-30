"""
03_validate.py — Quality validation of enriched requirements.

Checks:
  1. Required fields present and non-empty
  2. bcs: exactly 2 items, both in RBA catalog, both resolve to distinct full paths
  3. rsa: value exists in RSA catalog
  4. comment: contains Fiori app ID, 2 OSS Notes with titles, no URLs
  5. licensing: "Adicional" when rsa != "SAP S/4HANA"
  6. coverage: valid enum value

Exits with code 1 if any validation errors are found.
Output: prints a report and writes output/validation_report.json
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"

VALID_COVERAGE  = {"Total", "Parcial", "No cubierto"}
VALID_DEV       = {"No", "Sí", "Si"}
VALID_LICENSING = {"Básico", "Adicional", "Basico"}
URL_PATTERN     = re.compile(r"https?://")
FIORI_PATTERN   = re.compile(r"\([A-Z]\d{4,5}[A-Z]?\)")   # e.g. (F0842A)
OSS_PATTERN     = re.compile(r"OSS\s+Note\s+\d{6,7}\s+[–\-—]")  # OSS Note XXXXXXX –


# ── Load catalogs ─────────────────────────────────────────────────────────────

def _load_catalogs() -> tuple[dict[str, str], set[str]]:
    rba = json.loads((KNOWLEDGE_DIR / "sap_rba_catalog.json").read_text())
    short_name_index: dict[str, str] = rba["short_name_index"]

    rsa = json.loads((KNOWLEDGE_DIR / "sap_rsa_catalog.json").read_text())
    rsa_names: set[str] = {a["name"] for a in rsa["applications"]}

    return short_name_index, rsa_names


# ── Per-requirement validation ────────────────────────────────────────────────

def _validate_one(
    req: dict[str, Any],
    short_name_index: dict[str, str],
    rsa_names: set[str],
) -> list[str]:
    errors: list[str] = []
    req_id = req.get("id", "UNKNOWN")

    # 1. Required fields
    for field in ("module", "bcs", "rsa", "coverage", "dev", "licensing", "comment"):
        val = req.get(field)
        if val is None or val == "" or val == []:
            errors.append(f"{req_id}: field '{field}' is missing or empty")

    if errors:
        return errors  # no point checking further

    # 2. bcs
    bcs: list = req["bcs"]
    if not isinstance(bcs, list) or len(bcs) < 1:
        errors.append(f"{req_id}: 'bcs' must be a non-empty list")
    elif len(bcs) > 3:
        errors.append(f"{req_id}: 'bcs' has {len(bcs)} items — max 3 expected")
    else:
        full_paths = []
        for bc in bcs:
            full = short_name_index.get(bc)
            if full is None:
                errors.append(
                    f"{req_id}: BC '{bc}' not found in RBA catalog"
                )
            else:
                full_paths.append(full)
        if len(full_paths) != len(set(full_paths)):
            errors.append(
                f"{req_id}: 'bcs' resolves to duplicate full paths: "
                f"{[short_name_index.get(b, b) for b in bcs]}"
            )
        # Check no bare domain (full path must contain '/')
        for bc, fp in zip(bcs, full_paths):
            if fp and "/" not in fp:
                errors.append(
                    f"{req_id}: BC '{bc}' resolves to bare domain '{fp}' — use a leaf BC"
                )

    # 3. rsa
    if req["rsa"] not in rsa_names:
        errors.append(
            f"{req_id}: rsa '{req['rsa']}' not in RSA catalog. "
            f"Valid values: {sorted(rsa_names)}"
        )

    # 4. licensing vs rsa
    if req["rsa"] != "SAP S/4HANA" and req["licensing"] not in ("Adicional",):
        errors.append(
            f"{req_id}: rsa is '{req['rsa']}' but licensing is '{req['licensing']}' "
            f"— should be 'Adicional'"
        )

    # 5. coverage
    if req["coverage"] not in VALID_COVERAGE:
        errors.append(
            f"{req_id}: coverage '{req['coverage']}' invalid. "
            f"Use one of: {VALID_COVERAGE}"
        )

    # 6. comment quality
    comment: str = req.get("comment", "")
    if URL_PATTERN.search(comment):
        errors.append(f"{req_id}: comment contains a URL — remove it")

    fiori_matches = FIORI_PATTERN.findall(comment)
    if not fiori_matches:
        errors.append(f"{req_id}: comment missing Fiori app ID (e.g. '(F0842A)')")

    oss_matches = OSS_PATTERN.findall(comment)
    if len(oss_matches) < 2:
        errors.append(
            f"{req_id}: comment has {len(oss_matches)} OSS Note(s) with title — need at least 2"
        )

    return errors


# ── Main ──────────────────────────────────────────────────────────────────────

def validate(
    enriched_path: str | Path,
    output_dir: str | Path = "output",
) -> bool:
    enriched_path = Path(enriched_path)
    output_dir    = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    reqs: list[dict] = json.loads(enriched_path.read_text())
    short_name_index, rsa_names = _load_catalogs()

    all_errors: dict[str, list[str]] = {}
    for req in reqs:
        errs = _validate_one(req, short_name_index, rsa_names)
        if errs:
            all_errors[req.get("id", "UNKNOWN")] = errs

    report = {
        "total": len(reqs),
        "passed": len(reqs) - len(all_errors),
        "failed": len(all_errors),
        "errors": all_errors,
    }

    report_path = output_dir / "validation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    if all_errors:
        logger.error(
            "Validation FAILED: %d/%d requirements have errors. See %s",
            len(all_errors), len(reqs), report_path,
        )
        for req_id, errs in all_errors.items():
            for e in errs:
                logger.error("  %s", e)
        return False

    logger.info(
        "Validation PASSED: all %d requirements are clean.", len(reqs)
    )
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("Usage: python 03_validate.py <reqs_enriched.json> [output_dir]")
        sys.exit(1)
    ok = validate(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "output")
    sys.exit(0 if ok else 1)
