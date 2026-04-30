"""
run.py — Orchestrator for the Archimedes AI pipeline.

Usage:
  python run.py <input_file> [--no-validate] [--push-leanix] [--output-dir OUTPUT]

Steps:
  1. extract  → output/reqs_raw.json
  2. enrich   → output/reqs_enriched.json
  3. validate → output/validation_report.json  (skipped with --no-validate)
  4. write    → output/<name>_enriched.xlsx  + optional LeanIX push

Environment variables (see .env.example):
  ANTHROPIC_API_KEY, LEANIX_API_TOKEN, LEANIX_WORKSPACE_ID, LEANIX_BASE_URL
  ENRICH_MODEL, ENRICH_BATCH_SIZE, LEANIX_PUSH, LOG_LEVEL
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add pipeline dir to path so modules can import each other
sys.path.insert(0, str(Path(__file__).parent / "pipeline"))

from pipeline.extract  import extract   # noqa: E402
from pipeline.enrich   import enrich    # noqa: E402
from pipeline.validate import validate  # noqa: E402
from pipeline.write    import write     # noqa: E402


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Archimedes AI — SAP requirements enrichment pipeline"
    )
    parser.add_argument("input_file", help="Path to .xlsx, .xls, or .pdf input file")
    parser.add_argument("--no-validate", action="store_true", help="Skip validation step")
    parser.add_argument("--push-leanix", action="store_true", help="Push results to LeanIX API")
    parser.add_argument("--output-dir", default="output", help="Directory for output files")
    args = parser.parse_args()

    _setup_logging(os.getenv("LOG_LEVEL", "INFO"))
    logger = logging.getLogger("archimedes")

    input_path = Path(args.input_file)
    output_dir = Path(args.output_dir)

    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        sys.exit(1)

    logger.info("═" * 60)
    logger.info("Archimedes AI — starting pipeline")
    logger.info("Input:  %s", input_path)
    logger.info("Output: %s", output_dir)
    logger.info("═" * 60)

    # Step 1 — Extract
    logger.info("Step 1/4 — Extract")
    raw_path = extract(input_path, output_dir)

    # Step 2 — Enrich
    logger.info("Step 2/4 — Enrich")
    enriched_path = enrich(raw_path, output_dir)

    # Step 3 — Validate
    if not args.no_validate:
        logger.info("Step 3/4 — Validate")
        ok = validate(enriched_path, output_dir)
        if not ok:
            logger.error(
                "Validation failed. Fix errors in %s/validation_report.json "
                "or re-run with --no-validate to skip.",
                output_dir,
            )
            sys.exit(1)
    else:
        logger.info("Step 3/4 — Validate (SKIPPED)")

    # Step 4 — Write
    logger.info("Step 4/4 — Write")
    out_excel = write(
        enriched_path,
        input_path,
        output_dir,
        push_leanix=args.push_leanix,
    )

    logger.info("═" * 60)
    logger.info("Pipeline complete.")
    logger.info("  Excel output : %s", out_excel)
    logger.info("  Enriched JSON: %s", enriched_path)
    if not args.no_validate:
        logger.info("  Validation   : %s/validation_report.json", output_dir)
    logger.info("═" * 60)


if __name__ == "__main__":
    main()
