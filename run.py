"""
run.py — Orchestrator for the Archimedes AI pipeline.

Two commands:

  1. Enrich — extract → enrich → validate → write (both Excel outputs)
     python run.py enrich <input_file> --client <name> [options]

     Outputs:
       output/<stem>_enriched.xlsx        ← client deliverable (cols H–P)
       output/<client>_leanix_import.xlsx ← staging file for LeanIX (review before push)

  2. Push — read staging Excel → push to LeanIX
     python run.py push <leanix_import.xlsx> --client <name>

     Run after reviewing / editing the staging file.

Options for enrich:
  --no-validate         Skip validation step
  --client NAME         Client name used as tag in LeanIX (default: unknown)
  --output-dir OUTPUT   Directory for output files (default: output)

Environment variables (see .env.example):
  ANTHROPIC_API_KEY, LEANIX_API_TOKEN, LEANIX_BASE_URL
  ENRICH_MODEL, ENRICH_BATCH_SIZE, LOG_LEVEL
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent / "pipeline"))

from pipeline.extract  import extract     # noqa: E402
from pipeline.enrich   import enrich      # noqa: E402
from pipeline.validate import validate    # noqa: E402
from pipeline.write    import write, push_leanix  # noqa: E402


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_enrich(args: argparse.Namespace) -> None:
    logger = logging.getLogger("archimedes")

    input_path = Path(args.input_file)
    output_dir = Path(args.output_dir)

    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        sys.exit(1)

    logger.info("═" * 60)
    logger.info("Archimedes AI — enrich")
    logger.info("Input:  %s", input_path)
    logger.info("Client: %s", args.client)
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
    out_excel, out_staging = write(
        enriched_path,
        input_path,
        output_dir,
        client_name=args.client,
    )

    logger.info("═" * 60)
    logger.info("Done.")
    logger.info("  Client Excel  : %s", out_excel)
    logger.info("  LeanIX import : %s", out_staging)
    logger.info("  Enriched JSON : %s", enriched_path)
    if not args.no_validate:
        logger.info("  Validation    : %s/validation_report.json", output_dir)
    logger.info("─" * 60)
    logger.info("Review %s, then run:", out_staging)
    logger.info("  python run.py push %s --client %s", out_staging, args.client)
    logger.info("═" * 60)


def cmd_push(args: argparse.Namespace) -> None:
    logger = logging.getLogger("archimedes")
    staging = Path(args.staging_file)

    if not staging.exists():
        logger.error("Staging file not found: %s", staging)
        sys.exit(1)

    logger.info("═" * 60)
    logger.info("Archimedes AI — push to LeanIX")
    logger.info("Staging: %s", staging)
    logger.info("Client:  %s", args.client)
    logger.info("═" * 60)

    push_leanix(staging, client_name=args.client)

    logger.info("═" * 60)
    logger.info("LeanIX push complete.")
    logger.info("═" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Archimedes AI — SAP requirements enrichment pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # enrich sub-command
    p_enrich = sub.add_parser("enrich", help="Extract → enrich → validate → write")
    p_enrich.add_argument("input_file", help="Path to .xlsx, .xls, or .pdf")
    p_enrich.add_argument("--no-validate", action="store_true", help="Skip validation")
    p_enrich.add_argument("--client", default="unknown", help="Client name (used as LeanIX tag)")
    p_enrich.add_argument("--output-dir", default="output", help="Output directory")

    # push sub-command
    p_push = sub.add_parser("push", help="Push staging Excel to LeanIX")
    p_push.add_argument("staging_file", help="Path to <client>_leanix_import.xlsx")
    p_push.add_argument("--client", default="unknown", help="Client name (used as LeanIX tag)")

    args = parser.parse_args()
    _setup_logging(os.getenv("LOG_LEVEL", "INFO"))

    if args.command == "enrich":
        cmd_enrich(args)
    else:
        cmd_push(args)


if __name__ == "__main__":
    main()
