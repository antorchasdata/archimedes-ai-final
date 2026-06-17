"""
pdf_extract.py — Extract LeanIX fact sheets from a PDF using Claude API.

Sends the full PDF text (and page images if available) to Claude with a prompt
that extracts Applications, Business Capabilities, Organizations, Initiatives,
and IT Components, mapped against the SAP RBA/RSA catalogs.

Only fact sheets derivable with high confidence are returned.

Public API:
    extract_pdf_factsheets(pdf_path, client, anthropic_client) -> dict
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import anthropic
import pdfplumber

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"

# Confidence threshold — Claude must rate each item >= this to be included
_MIN_CONFIDENCE = 0.7

_SYSTEM_PROMPT = """
You are a senior SAP Enterprise Architect and LeanIX expert.
Your task is to extract structured LeanIX fact sheet data from a client document.
Always map Applications and Business Capabilities against the provided SAP RBA/RSA catalogs.
Only include items you can derive with HIGH confidence from the document.
Return ONLY valid JSON, no markdown, no explanation.
""".strip()

_USER_PROMPT_TEMPLATE = """
## DOCUMENT TEXT
{text}

## SAP RBA CATALOG (short_name_index — BC short name → full path)
{rba_catalog}

## SAP RSA CATALOG (canonical SAP product names)
{rsa_catalog}

## CLIENT NAME
{client_name}

## TASK
Extract all LeanIX fact sheets you can identify from the document above.
For each fact sheet, assign a confidence score (0.0–1.0) indicating how certain you are
it can be derived from the document. Only include items with confidence >= 0.7.

Map every Application to its canonical RSA name if it is an SAP product.
Map every Business Capability to its canonical RBA short name.

Return a JSON object with this exact structure:
{{
  "applications": [
    {{
      "name": "<canonical RSA name or custom name>",
      "description": "<description from document>",
      "lifecycle_phase": "<active|phaseIn|phaseOut|plan|endOfLife>",
      "lxHostingType": "<onPremise|saas|paas|iaas|hybrid>",
      "businessCriticality": "<missionCritical|businessCritical|businessOperational|administrativeService>",
      "relApplicationToBusinessCapability": "<BC short name 1>;<BC short name 2>",
      "relApplicationToITComponent": "<ITC name if known>",
      "tags": "Target;{client_name}",
      "confidence": 0.9
    }}
  ],
  "business_capabilities": [
    {{
      "name": "<RBA short name>",
      "full_path": "<RBA full path>",
      "confidence": 0.85
    }}
  ],
  "organizations": [
    {{
      "name": "<org unit name>",
      "description": "<description>",
      "confidence": 0.8
    }}
  ],
  "initiatives": [
    {{
      "name": "<initiative name>",
      "description": "<description>",
      "lifecycle_phase": "<plan|active|phaseIn>",
      "confidence": 0.75
    }}
  ],
  "it_components": [
    {{
      "name": "<ITC name>",
      "description": "<description>",
      "lxHostingType": "<onPremise|saas|paas>",
      "confidence": 0.8
    }}
  ],
  "summary": "<1-2 sentence summary of what was found in the document>"
}}

Rules:
- Use EXACT canonical names from the RBA/RSA catalogs when available.
- If an application is not in the RSA catalog, use the name as it appears in the document.
- If a BC is not in the RBA catalog, use the name as it appears but set confidence <= 0.6.
- Omit any array that has zero items.
- Do NOT invent items that are not in the document.
""".strip()


def _load_catalogs() -> tuple[str, str]:
    """Return (rba_short_name_index_str, rsa_catalog_str)."""
    rba = json.loads((KNOWLEDGE_DIR / "sap_rba_catalog.json").read_text())
    rba_str = json.dumps(rba["short_name_index"], ensure_ascii=False, indent=2)

    rsa = json.loads((KNOWLEDGE_DIR / "sap_rsa_catalog.json").read_text())
    rsa_str = "\n".join(
        f'- "{a["name"]}": {a.get("use_when", a.get("domain", ""))}'
        for a in rsa["applications"]
    )
    return rba_str, rsa_str


def _extract_text(pdf_path: Path) -> str:
    """Extract all text from a PDF, page by page."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"[Page {i}]\n{text}")
    return "\n\n".join(pages)


def _extract_page_images(pdf_path: Path, max_pages: int = 10) -> list[str]:
    """
    Convert up to max_pages pages to base64 PNG for Claude vision.
    Returns list of base64-encoded PNG strings.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.debug("PyMuPDF not installed — skipping image extraction from PDF")
        return []

    images = []
    doc = fitz.open(str(pdf_path))
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(dpi=100)
        images.append(base64.standard_b64encode(pix.tobytes("png")).decode())
    return images


def _call_claude(
    client: anthropic.Anthropic,
    text: str,
    page_images: list[str],
    rba_str: str,
    rsa_str: str,
    client_name: str,
    model: str,
) -> dict[str, Any]:
    """Call Claude API with text + optional page images."""
    prompt = _USER_PROMPT_TEMPLATE.format(
        text=text[:40000],  # cap to avoid token limits
        rba_catalog=rba_str[:8000],
        rsa_catalog=rsa_str[:4000],
        client_name=client_name,
    )

    content: list[dict] = []

    # Add up to 3 page images for visual context
    for img_b64 in page_images[:3]:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
        })

    content.append({"type": "text", "text": prompt})

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


def _filter_by_confidence(data: dict, min_confidence: float) -> dict:
    """Remove items below confidence threshold."""
    filtered = {}
    for key, items in data.items():
        if key == "summary":
            filtered[key] = items
            continue
        if isinstance(items, list):
            filtered[key] = [i for i in items if i.get("confidence", 0) >= min_confidence]
    return filtered


def extract_pdf_factsheets(
    pdf_path: str | Path,
    client_name: str,
    anthropic_client: anthropic.Anthropic,
    model: str = "claude-sonnet-4-6",
    min_confidence: float = _MIN_CONFIDENCE,
) -> dict[str, Any]:
    """
    Extract LeanIX fact sheets from a PDF using Claude API.

    Args:
        pdf_path:          Path to the PDF file.
        client_name:       Client name used as tag.
        anthropic_client:  Authenticated anthropic.Anthropic client.
        model:             Claude model to use.
        min_confidence:    Minimum confidence score (0–1) to include a fact sheet.

    Returns:
        dict with keys: applications, business_capabilities, organizations,
                        initiatives, it_components, summary, source_file
    """
    pdf_path = Path(pdf_path)
    logger.info("PDF extract: %s", pdf_path.name)

    text = _extract_text(pdf_path)
    if not text.strip():
        logger.warning("No text extracted from %s", pdf_path.name)
        return {"summary": "No text could be extracted from the PDF.", "source_file": str(pdf_path)}

    page_images = _extract_page_images(pdf_path)
    logger.info("PDF: %d chars of text, %d page images", len(text), len(page_images))

    rba_str, rsa_str = _load_catalogs()

    try:
        raw = _call_claude(anthropic_client, text, page_images, rba_str, rsa_str, client_name, model)
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Claude response parse error: %s", e)
        return {"summary": f"Extraction failed: {e}", "source_file": str(pdf_path)}
    except anthropic.APIError as e:
        logger.error("Claude API error: %s", e)
        return {"summary": f"API error: {e}", "source_file": str(pdf_path)}

    result = _filter_by_confidence(raw, min_confidence)
    result["source_file"] = str(pdf_path)

    n_apps  = len(result.get("applications", []))
    n_bcs   = len(result.get("business_capabilities", []))
    n_orgs  = len(result.get("organizations", []))
    n_inits = len(result.get("initiatives", []))
    n_itcs  = len(result.get("it_components", []))

    logger.info(
        "PDF extract complete: %d apps, %d BCs, %d orgs, %d initiatives, %d ITCs",
        n_apps, n_bcs, n_orgs, n_inits, n_itcs,
    )

    return result
