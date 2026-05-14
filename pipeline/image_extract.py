"""
image_extract.py — Extract LeanIX fact sheets from architecture diagrams/images using Claude vision.

Sends images to Claude API with a prompt that identifies applications, domains,
relations, and infrastructure components visible in the diagram.

Public API:
    extract_image_factsheets(image_paths, client_name, anthropic_client) -> dict
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"

_SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

_MEDIA_TYPES = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
}

_SYSTEM_PROMPT = """
You are a senior SAP Enterprise Architect and LeanIX expert analyzing architecture diagrams.
Your task is to identify LeanIX fact sheets visible in the diagram(s).
Map SAP applications to their canonical RSA names and business capabilities to SAP RBA names.
Only include items clearly visible or strongly implied by the diagram.
Return ONLY valid JSON, no markdown, no explanation.
""".strip()

_USER_PROMPT_TEMPLATE = """
## SAP RBA CATALOG (short_name_index — BC short name → full path)
{rba_catalog}

## SAP RSA CATALOG (canonical SAP product names)
{rsa_catalog}

## CLIENT NAME
{client_name}

## TASK
Analyze the architecture diagram(s) above and extract all LeanIX fact sheets you can identify.

For each item assign a confidence score (0.0–1.0):
- 1.0 = explicitly labeled in the diagram
- 0.8 = clearly implied by context or standard SAP naming
- 0.7 = reasonably inferred from the diagram
- < 0.7 = uncertain — DO NOT include

Map every SAP application to its canonical RSA name.
Map every business capability/domain to its canonical RBA short name.
Note any relations (arrows, connections) between applications as relToParent or interface links.

Return a JSON object with this exact structure:
{{
  "applications": [
    {{
      "name": "<canonical RSA name or label from diagram>",
      "description": "<what the diagram shows about this app>",
      "lifecycle_phase": "<active|phaseIn|phaseOut|plan>",
      "lxHostingType": "<onPremise|saas|paas|iaas|hybrid — infer from diagram if possible>",
      "domain": "<domain/layer label from diagram if visible>",
      "relToParent": "<parent app name if hierarchy visible>",
      "tags": "Baseline;Diagram;{client_name}",
      "confidence": 0.9
    }}
  ],
  "business_capabilities": [
    {{
      "name": "<RBA short name or label>",
      "full_path": "<RBA full path if mappable, else empty>",
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
  "it_components": [
    {{
      "name": "<ITC name>",
      "description": "<description>",
      "lxHostingType": "<onPremise|saas|paas>",
      "confidence": 0.8
    }}
  ],
  "interfaces": [
    {{
      "from": "<source app name>",
      "to": "<target app name>",
      "description": "<interface description if labeled>",
      "confidence": 0.8
    }}
  ],
  "summary": "<1-2 sentence description of the architecture shown in the diagram>",
  "diagram_type": "<landscape|application_map|data_flow|infrastructure|other>"
}}

Rules:
- Read domain/layer labels carefully — they can appear at the TOP or BOTTOM of bounding boxes.
- Use EXACT canonical names from RBA/RSA catalogs when the diagram shows SAP products.
- Do NOT invent items not visible in the diagram.
- Omit any array that has zero items.
""".strip()


def _load_catalogs() -> tuple[str, str]:
    rba = json.loads((KNOWLEDGE_DIR / "sap_rba_catalog.json").read_text())
    rba_str = json.dumps(rba["short_name_index"], ensure_ascii=False, indent=2)

    rsa = json.loads((KNOWLEDGE_DIR / "sap_rsa_catalog.json").read_text())
    rsa_str = "\n".join(
        f'- "{a["name"]}": {a.get("use_when", "")}'
        for a in rsa["applications"]
    )
    return rba_str, rsa_str


def _image_to_content_block(path: Path) -> dict:
    ext = path.suffix.lower()
    media_type = _MEDIA_TYPES.get(ext, "image/png")
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def _call_claude(
    client: anthropic.Anthropic,
    image_paths: list[Path],
    rba_str: str,
    rsa_str: str,
    client_name: str,
    model: str,
) -> dict[str, Any]:
    content: list[dict] = []

    for path in image_paths:
        content.append(_image_to_content_block(path))
        content.append({"type": "text", "text": f"[Image: {path.name}]"})

    prompt = _USER_PROMPT_TEMPLATE.format(
        rba_catalog=rba_str[:8000],
        rsa_catalog=rsa_str[:4000],
        client_name=client_name,
    )
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
    filtered = {}
    for key, items in data.items():
        if key in ("summary", "diagram_type"):
            filtered[key] = items
            continue
        if isinstance(items, list):
            filtered[key] = [i for i in items if i.get("confidence", 0) >= min_confidence]
    return filtered


def extract_image_factsheets(
    image_paths: list[str | Path],
    client_name: str,
    anthropic_client: anthropic.Anthropic,
    model: str = "claude-sonnet-4-6",
    min_confidence: float = 0.7,
    max_images_per_call: int = 5,
) -> dict[str, Any]:
    """
    Extract LeanIX fact sheets from architecture diagram images using Claude vision.

    Args:
        image_paths:         List of image file paths (.png, .jpg, .jpeg, .gif, .webp).
        client_name:         Client name used as tag.
        anthropic_client:    Authenticated anthropic.Anthropic client.
        model:               Claude model to use.
        min_confidence:      Minimum confidence to include a fact sheet.
        max_images_per_call: Max images per API call (batched if more).

    Returns:
        Merged dict with keys: applications, business_capabilities, organizations,
                               it_components, interfaces, summary, source_files
    """
    valid_paths = []
    for p in image_paths:
        p = Path(p)
        if not p.exists():
            logger.warning("Image not found: %s", p)
            continue
        if p.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            logger.warning("Unsupported image format: %s", p.suffix)
            continue
        valid_paths.append(p)

    if not valid_paths:
        logger.warning("No valid images to process")
        return {"summary": "No valid images provided.", "source_files": []}

    rba_str, rsa_str = _load_catalogs()

    # Batch images into groups to stay within API limits
    merged: dict[str, Any] = {
        "applications": [], "business_capabilities": [], "organizations": [],
        "it_components": [], "interfaces": [], "summaries": [],
    }

    batches = [
        valid_paths[i:i + max_images_per_call]
        for i in range(0, len(valid_paths), max_images_per_call)
    ]

    for batch_idx, batch in enumerate(batches, start=1):
        logger.info("Image extract: batch %d/%d (%d images)", batch_idx, len(batches), len(batch))
        try:
            raw = _call_claude(anthropic_client, batch, rba_str, rsa_str, client_name, model)
            filtered = _filter_by_confidence(raw, min_confidence)

            for key in ("applications", "business_capabilities", "organizations",
                        "it_components", "interfaces"):
                merged[key].extend(filtered.get(key, []))

            if filtered.get("summary"):
                merged["summaries"].append(filtered["summary"])

        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Parse error on batch %d: %s", batch_idx, e)
        except anthropic.APIError as e:
            logger.error("API error on batch %d: %s", batch_idx, e)

    # Deduplicate by name within each fact sheet type
    for key in ("applications", "business_capabilities", "organizations", "it_components"):
        seen: set[str] = set()
        deduped = []
        for item in merged[key]:
            name = item.get("name", "")
            if name and name not in seen:
                seen.add(name)
                deduped.append(item)
        merged[key] = deduped

    merged["summary"] = " | ".join(merged.pop("summaries", []))
    merged["source_files"] = [str(p) for p in valid_paths]

    logger.info(
        "Image extract complete: %d apps, %d BCs, %d orgs, %d ITCs, %d interfaces",
        len(merged["applications"]), len(merged["business_capabilities"]),
        len(merged["organizations"]), len(merged["it_components"]),
        len(merged["interfaces"]),
    )

    return merged
