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

def _load_knowledge() -> tuple[str, str, str]:
    """Return (prompt_template, rba_catalog_str, rsa_catalog_str)."""
    template = (KNOWLEDGE_DIR / "prompt_template.txt").read_text()

    rba = json.loads((KNOWLEDGE_DIR / "sap_rba_catalog.json").read_text())
    rba_str = json.dumps(rba["short_name_index"], ensure_ascii=False, indent=2)

    rsa = json.loads((KNOWLEDGE_DIR / "sap_rsa_catalog.json").read_text())
    rsa_str = "\n".join(
        f"- \"{a['name']}\": {a['use_when']}"
        for a in rsa["applications"]
    )

    return template, rba_str, rsa_str


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
    template, rba_str, rsa_str = _load_knowledge()

    enriched: list[dict] = []
    errors: list[str] = []

    for i, req in enumerate(reqs, start=1):
        logger.info("[%d/%d] %s", i, len(reqs), req["id"])
        result = _enrich_one(client, req, template, rba_str, rsa_str)
        enriched.append(result)
        if "_error" in result:
            errors.append(req["id"])

        # Brief pause every batch to respect rate limits
        if i % BATCH_SIZE == 0:
            time.sleep(1)

    out_path = output_dir / "reqs_enriched.json"
    out_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2))
    logger.info(
        "Saved %d enriched requirements to %s (%d errors)",
        len(enriched), out_path, len(errors),
    )
    if errors:
        logger.warning("Failed IDs: %s", errors)

    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("Usage: python 02_enrich.py <reqs_raw.json> [output_dir]")
        sys.exit(1)
    out = enrich(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "output")
    print(f"Enriched → {out}")
