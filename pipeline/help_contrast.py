"""
help_contrast.py — SAP Help Portal contrast for enriched requirements.

For each enriched requirement, searches help.sap.com to validate and
enrich the RSA product mapping with official SAP documentation.

Uses WebFetch-style HTTP requests (no auth required).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SAP_HELP_SEARCH = "https://help.sap.com/docs/search?q={query}&locale=en-US"
SAP_HELP_BASE   = "https://help.sap.com"


def _search_help_portal(query: str, timeout: int = 10) -> str:
    """Fetch SAP Help Portal search results page as text."""
    url = SAP_HELP_SEARCH.format(query=urllib.parse.quote(query))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.warning("SAP Help Portal fetch failed for '%s': %s", query, exc)
        return ""


def _extract_titles_from_html(html: str, max_results: int = 3) -> list[str]:
    """Extract result titles from SAP Help Portal search HTML."""
    import re
    # SAP Help search returns titles in <a> tags with class containing 'result'
    pattern = re.compile(r'<a[^>]+class="[^"]*result[^"]*"[^>]*>(.*?)</a>', re.I | re.S)
    matches = pattern.findall(html)
    # Also try generic <h3> or <h4> title patterns
    if not matches:
        pattern = re.compile(r'<(?:h3|h4)[^>]*>(.*?)</(?:h3|h4)>', re.I | re.S)
        matches = pattern.findall(html)
    # Strip HTML tags from matches
    tag_re = re.compile(r'<[^>]+>')
    titles = [tag_re.sub('', m).strip() for m in matches if m.strip()]
    return [t for t in titles if len(t) > 5][:max_results]


def contrast_requirement(req_id: str, rsa_product: str, description: str) -> dict[str, Any]:
    """
    Contrast a single requirement against SAP Help Portal.

    Returns:
        {
            "req_id": str,
            "rsa_product": str,
            "help_results": [str, ...],   # titles found on help.sap.com
            "validated": bool,             # True if help.sap.com confirms the product
            "note": str                    # human-readable note
        }
    """
    query = f"{rsa_product} {description[:80]}"
    html  = _search_help_portal(query)
    titles = _extract_titles_from_html(html)

    validated = any(
        rsa_product.lower().split()[-1] in t.lower() or
        any(word in t.lower() for word in rsa_product.lower().split() if len(word) > 4)
        for t in titles
    ) if titles else False

    note = (
        f"SAP Help confirms '{rsa_product}'" if validated
        else f"No direct confirmation found for '{rsa_product}' on SAP Help Portal"
    )

    return {
        "req_id":      req_id,
        "rsa_product": rsa_product,
        "help_results": titles,
        "validated":   validated,
        "note":        note,
    }


def run_contrast(
    enriched_path: str | Path,
    output_dir: str | Path = "output",
    delay: float = 0.5,
) -> Path:
    """
    Run SAP Help Portal contrast for all enriched requirements.

    Args:
        enriched_path: Path to reqs_enriched.json
        output_dir:    Output directory
        delay:         Seconds between requests (be polite to help.sap.com)

    Returns:
        Path to <output_dir>/help_contrast_report.json
    """
    enriched_path = Path(enriched_path)
    output_dir    = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    reqs: list[dict] = json.loads(enriched_path.read_text())
    results = []

    logger.info("Contrasting %d requirements with SAP Help Portal …", len(reqs))

    for i, req in enumerate(reqs, start=1):
        req_id  = req.get("_source_id") or req.get("id", f"REQ_{i:03d}")
        rsa     = req.get("rsa", "")
        desc    = req.get("description", "")

        if not rsa:
            results.append({
                "req_id":      req_id,
                "rsa_product": "",
                "help_results": [],
                "validated":   False,
                "note":        "No RSA product assigned — skipped",
            })
            continue

        logger.info("[%d/%d] %s — contrasting '%s'", i, len(reqs), req_id, rsa)
        result = contrast_requirement(req_id, rsa, desc)
        results.append(result)

        if delay:
            time.sleep(delay)

    out_path = output_dir / "help_contrast_report.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))

    validated_count = sum(1 for r in results if r["validated"])
    logger.info(
        "SAP Help contrast complete: %d/%d validated → %s",
        validated_count, len(results), out_path,
    )

    return out_path


def print_contrast_summary(report_path: str | Path) -> None:
    """Print a human-readable summary of the contrast report."""
    report_path = Path(report_path)
    results: list[dict] = json.loads(report_path.read_text())

    validated   = [r for r in results if r["validated"]]
    unvalidated = [r for r in results if not r["validated"] and r["rsa_product"]]
    skipped     = [r for r in results if not r["rsa_product"]]

    print(f"\n  {'─'*50}")
    print(f"  SAP Help Portal Contrast Report")
    print(f"  {'─'*50}")
    print(f"  Total:      {len(results)}")
    print(f"  Validated:  {len(validated)}  ✓")
    print(f"  No confirm: {len(unvalidated)}  ⚠")
    print(f"  No RSA:     {len(skipped)}  —")

    if unvalidated:
        print(f"\n  Requirements to review:")
        for r in unvalidated[:10]:
            print(f"    {r['req_id']:12s}  {r['rsa_product']}")
            if r['help_results']:
                print(f"               Help found: {r['help_results'][0][:60]}")
    print(f"  {'─'*50}")
    print(f"  Full report: {report_path}\n")
