"""
02_enrich.py — LLM-based enrichment of raw requirements.

For each requirement in reqs_raw.json, calls Claude API with the prompt template
and the SAP RBA/RSA catalogs, returning structured enrichment data.

Output: output/reqs_enriched.json
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"
MODEL         = os.getenv("ENRICH_MODEL", "claude-sonnet-4-6")
BATCH_SIZE    = int(os.getenv("ENRICH_BATCH_SIZE", "10"))
MAX_RETRIES   = int(os.getenv("ENRICH_MAX_RETRIES", "3"))
RETRY_DELAY   = 5  # seconds between retries


# ── Load knowledge base ───────────────────────────────────────────────────────

def _load_knowledge() -> tuple[str, dict, str, str]:
    """Return (prompt_template, rba_full_index, rba_catalog_str, rsa_catalog_str).

    rba_full_index: the complete short_name_index dict (used for domain pre-scan).
    rba_catalog_str: full catalog serialized as JSON string (fallback).
    """
    template = (KNOWLEDGE_DIR / "prompt_template.txt").read_text()

    rba = json.loads((KNOWLEDGE_DIR / "sap_rba_catalog.json").read_text())
    rba_full_index: dict[str, str] = rba["short_name_index"]
    rba_str = json.dumps(rba_full_index, ensure_ascii=False, indent=2)

    rsa = json.loads((KNOWLEDGE_DIR / "sap_rsa_catalog.json").read_text())
    rsa_str = "\n".join(
        f"- \"{a['name']}\": {a['use_when']}"
        for a in rsa["applications"]
    )

    return template, rba_full_index, rba_str, rsa_str


def _subset_rba(
    reqs: list[dict],
    rba_full_index: dict[str, str],
    client: anthropic.Anthropic,
) -> str:
    """Pre-scan all requirements with one Claude call to identify relevant RBA L1 domains,
    then return a filtered catalog string containing only BCs from those domains.

    Falls back to the full catalog if the pre-scan fails.
    """
    all_domains = sorted({v.split(" / ")[0] for v in rba_full_index.values()})

    # Build a compact summary of all requirements for the pre-scan prompt
    req_summary = "\n".join(
        f"- [{r['id']}] {r.get('area', '')} | {r['description'][:120]}"
        for r in reqs
    )

    prescan_prompt = f"""You are an SAP Enterprise Architect.
Below is a list of {len(reqs)} client requirements. Identify which SAP RBA L1 domains are relevant.

Available L1 domains:
{chr(10).join(f'- {d}' for d in all_domains)}

Requirements:
{req_summary}

Respond with a JSON array of relevant domain names (exact spelling), e.g.:
["Finance", "Supply Chain Planning", "Human Resources"]
Include a domain if ANY requirement could map to a BC within it. When in doubt, include it.
Return ONLY the JSON array, no explanation."""

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prescan_prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        relevant_domains: list[str] = json.loads(raw)
        # Validate against known domains
        relevant_domains = [d for d in relevant_domains if d in all_domains]
        if not relevant_domains:
            raise ValueError("No valid domains returned")
        logger.info(
            "Catalog pre-scan: %d/%d domains selected — %s",
            len(relevant_domains), len(all_domains), relevant_domains,
        )
    except Exception as exc:
        logger.warning("Catalog pre-scan failed (%s) — using full RBA catalog", exc)
        return json.dumps(rba_full_index, ensure_ascii=False, indent=2)

    # Filter index to only BCs whose L1 domain is in the relevant set
    filtered = {
        short: full_path
        for short, full_path in rba_full_index.items()
        if full_path.split(" / ")[0] in relevant_domains
    }
    logger.info(
        "RBA catalog subset: %d → %d BCs (%.0f%% reduction)",
        len(rba_full_index), len(filtered),
        100 * (1 - len(filtered) / len(rba_full_index)),
    )
    return json.dumps(filtered, ensure_ascii=False, indent=2)


# ── Prompt building ───────────────────────────────────────────────────────────

def _build_prompt(req: dict, template: str, rba_str: str, rsa_str: str) -> str:
    return (
        template
        .replace("{req_id}", req["id"])
        .replace("{description}", req["description"])
        .replace("{area}", req.get("area", ""))
        .replace("{rba_catalog}", rba_str)
        .replace("{rsa_catalog}", rsa_str)
    )


# ── Claude API call ───────────────────────────────────────────────────────────

def _call_claude(client: anthropic.Anthropic, prompt: str) -> dict[str, Any]:
    """Call Claude and parse the JSON response. Raises on failure."""
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


def _enrich_one(
    client: anthropic.Anthropic,
    req: dict,
    template: str,
    rba_str: str,
    rsa_str: str,
) -> dict[str, Any]:
    prompt = _build_prompt(req, template, rba_str, rsa_str)
    last_err: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = _call_claude(client, prompt)
            result["_source_id"] = req["id"]
            logger.debug("Enriched %s (attempt %d)", req["id"], attempt)
            return result
        except (json.JSONDecodeError, KeyError, anthropic.APIError) as e:
            last_err = e
            logger.warning(
                "Attempt %d/%d failed for %s: %s",
                attempt, MAX_RETRIES, req["id"], e,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

    logger.error("All retries failed for %s — writing error placeholder", req["id"])
    return {
        "_source_id": req["id"],
        "_error": str(last_err),
        "id": req["id"],
        "module": "",
        "bcs": [],
        "rsa": "",
        "coverage": "",
        "dev": "",
        "dev_exp": "",
        "ext_apps": "",
        "licensing": "",
        "comment": f"[ENRICHMENT ERROR: {last_err}]",
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def enrich(
    raw_path: str | Path,
    output_dir: str | Path = "output",
) -> Path:
    raw_path   = Path(raw_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    reqs: list[dict] = json.loads(raw_path.read_text())
    logger.info("Enriching %d requirements with model %s …", len(reqs), MODEL)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    template, rba_full_index, rba_str_full, rsa_str = _load_knowledge()

    # Pre-scan: select relevant RBA domains to reduce prompt tokens
    rba_str = _subset_rba(reqs, rba_full_index, client) if len(reqs) >= 5 else rba_str_full

    # ── Resume from checkpoint if available ───────────────────────────────────
    checkpoint_path = output_dir / f"{raw_path.stem}_checkpoint.json"
    already_done: dict[str, dict] = {}
    if checkpoint_path.exists():
        try:
            saved = json.loads(checkpoint_path.read_text())
            already_done = {r["_source_id"]: r for r in saved if "_source_id" in r}
            logger.info("Resuming from checkpoint: %d/%d already enriched", len(already_done), len(reqs))
        except Exception as exc:
            logger.warning("Could not read checkpoint (%s) — starting fresh", exc)

    enriched: list[dict] = []
    errors: list[str] = []

    for i, req in enumerate(reqs, start=1):
        # Skip requirements already in checkpoint
        if req["id"] in already_done:
            enriched.append(already_done[req["id"]])
            logger.debug("[%d/%d] %s — from checkpoint", i, len(reqs), req["id"])
            continue

        logger.info("[%d/%d] %s", i, len(reqs), req["id"])
        result = _enrich_one(client, req, template, rba_str, rsa_str)
        enriched.append(result)
        if "_error" in result:
            errors.append(req["id"])

        # Write checkpoint after every batch
        if i % BATCH_SIZE == 0:
            checkpoint_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2))
            logger.debug("Checkpoint saved (%d/%d)", i, len(reqs))
            time.sleep(1)

    out_path = output_dir / "reqs_enriched.json"
    out_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2))
    logger.info(
        "Saved %d enriched requirements to %s (%d errors)",
        len(enriched), out_path, len(errors),
    )
    if errors:
        logger.warning("Failed IDs: %s", errors)

    # Remove checkpoint on successful completion
    if checkpoint_path.exists():
        checkpoint_path.unlink()
        logger.debug("Checkpoint removed")

    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("Usage: python 02_enrich.py <reqs_raw.json> [output_dir]")
        sys.exit(1)
    out = enrich(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "output")
    print(f"Enriched → {out}")
