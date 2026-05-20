"""
pipeline/lift_shift.py — Lift & Shift conversion via SAP Material Mapping Tool

Flow:
  1. resolve_app_to_skus()     — app names → Material Numbers (API exact match + Claude fallback)
  2. get_deployment_modes()    — union of ProdDeployment values for a set of SKUs
  3. convert_to_rise()         — SKU + deployment mode → target materials + prerequisites
"""

import re
import json
import os
import urllib.parse
import logging
from typing import Optional

import requests
import anthropic

try:
    import browser_cookie3
    _BROWSER_COOKIE3_AVAILABLE = True
except ImportError:
    _BROWSER_COOKIE3_AVAILABLE = False

logger = logging.getLogger(__name__)

MODEL   = os.getenv("ENRICH_MODEL", "claude-sonnet-4-6")
_BASE_URL = (
    "https://sapit-dataandintegration-prod-otter.launchpad.cfapps.eu10.hana.ondemand.com"
    "/2c184f43-fb02-4ab8-a478-b823776e0b5c.comsapplamaterialrelationship"
    ".comsapplamaterialrelationship/sap/opu/odata/sap/ZPRODUMRM_SRV"
)
_DOMAIN = "sapit-dataandintegration-prod-otter.launchpad.cfapps.eu10.hana.ondemand.com"


# ── Session ────────────────────────────────────────────────────────────────────

def get_material_session() -> requests.Session:
    """Return a requests.Session with SAP BTP cookies from Chrome/Edge."""
    session = requests.Session()
    if not _BROWSER_COOKIE3_AVAILABLE:
        logger.warning("browser_cookie3 not installed — session will have no cookies")
        session.headers.update({"Accept": "application/json"})
        return session
    for loader in [browser_cookie3.chrome, browser_cookie3.edge]:
        try:
            cookies = loader(domain_name=_DOMAIN)
            session.cookies.update(cookies)
            logger.info("Cookies loaded from %s", loader.__name__)
            break
        except Exception:
            continue
    session.headers.update({"Accept": "application/json"})
    return session


def check_session(session: requests.Session) -> bool:
    """Quick auth check — returns True if session is valid."""
    url = f"{_BASE_URL}/MaterialsetSet?$top=1&$format=json"
    try:
        r = session.get(url, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


# ── Helpers ────────────────────────────────────────────────────────────────────

def _strip_sid(name: str) -> str:
    """'SAP ERP (ECP)' → 'SAP ERP'"""
    return re.sub(r'\s*\([A-Z0-9]{2,6}\)\s*$', '', name).strip()


def _search_by_name(name: str, session: requests.Session, top: int = 10) -> list[dict]:
    """Exact match on Maktx — returns list of {matnr, maktx}."""
    encoded = urllib.parse.quote(f"Maktx eq '{name}'")
    url = f"{_BASE_URL}/MaterialsetSet?$filter={encoded}&$top={top}&$format=json"
    try:
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return []
        results = r.json().get("d", {}).get("results", [])
        return [{"matnr": i.get("Matnr", ""), "maktx": i.get("Maktx", "")} for i in results]
    except Exception as e:
        logger.warning("Search failed for '%s': %s", name, e)
        return []


def _claude_pick_best(app_name: str, candidates: list[dict]) -> Optional[str]:
    """Ask Claude to pick the most representative Material Number for an app name."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    client = anthropic.Anthropic(api_key=api_key)
    candidates_str = "\n".join(f"  {c['matnr']} — {c['maktx']}" for c in candidates)
    prompt = (
        f"You are an SAP licensing expert helping map customer applications to SAP Material Numbers.\n"
        f"A customer has the SAP application '{app_name}' in their landscape.\n"
        f"Below are Material Numbers from the SAP Material Relationship tool that match this name.\n"
        f"Pick the ONE Material Number that is most likely to be the main PRODUCT SKU for this application "
        f"(prefer Professional User or the edition that encompasses the full product, "
        f"avoid Developer User, upgrade SKUs, SMB/AIO variants, or add-ons).\n"
        f"Reply with ONLY the Material Number, nothing else.\n\n"
        f"Candidates:\n{candidates_str}"
    )
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=32,
            messages=[{"role": "user", "content": prompt}],
        )
        matnr = message.content[0].text.strip().split()[0]
        # Validate it's one of the candidates
        valid = {c["matnr"] for c in candidates}
        return matnr if matnr in valid else candidates[0]["matnr"]
    except Exception as e:
        logger.warning("Claude pick failed for '%s': %s", app_name, e)
        return candidates[0]["matnr"]


# ── Public API ─────────────────────────────────────────────────────────────────

def resolve_app_to_skus(app_names: list[str], session: requests.Session) -> list[dict]:
    """
    Resolve a list of application names to Material Numbers.

    Returns list of:
      {
        "app_name":    str,   # original name from baseline
        "clean_name":  str,   # after SID strip
        "candidates":  [{matnr, maktx}, ...],
        "selected":    str,   # best candidate chosen by Claude (or first if only one)
        "selected_maktx": str,
        "resolved_by": "exact" | "claude" | "manual" | "not_found"
      }
    """
    results = []
    for app_name in app_names:
        clean = _strip_sid(app_name)
        candidates = _search_by_name(clean, session)

        if not candidates:
            results.append({
                "app_name":       app_name,
                "clean_name":     clean,
                "candidates":     [],
                "selected":       "",
                "selected_maktx": "",
                "resolved_by":    "not_found",
            })
            continue

        if len(candidates) == 1:
            selected = candidates[0]["matnr"]
            resolved_by = "exact"
        else:
            selected = _claude_pick_best(clean, candidates)
            resolved_by = "claude"

        selected_maktx = next((c["maktx"] for c in candidates if c["matnr"] == selected), "")
        results.append({
            "app_name":       app_name,
            "clean_name":     clean,
            "candidates":     candidates,
            "selected":       selected,
            "selected_maktx": selected_maktx,
            "resolved_by":    resolved_by,
        })

    return results


def get_deployment_modes(skus: list[str], session: requests.Session) -> list[str]:
    """
    Return sorted unique ProdDeployment values across all given SKUs.
    Used to populate the deployment mode dropdown.
    """
    modes: set[str] = set()
    for sku in skus:
        if not sku:
            continue
        url = f"{_BASE_URL}/MaterialDeploymentSet?$filter=Matnr%20eq%20'{sku}'&$format=json"
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                continue
            for item in r.json().get("d", {}).get("results", []):
                mode = item.get("ProdDeployment", "").strip()
                if mode:
                    modes.add(mode)
        except Exception as e:
            logger.warning("Deployment modes fetch failed for %s: %s", sku, e)
    return sorted(modes)


def convert_to_rise(
    skus_map: list[dict],
    deployment_mode: str,
    session: requests.Session,
) -> list[dict]:
    """
    Convert a list of SKUs to their RISE equivalents for a given deployment mode.

    skus_map: [{app_name, selected (matnr)}]

    Returns list of:
      {
        "source_app":    str,   # original app name
        "source_matnr":  str,   # source SKU
        "target_matnr":  str,   # converted Material ID
        "target_desc":   str,   # description
        "status":        str,   # Mstav
        "status_desc":   str,   # Vmstb
        "deployment":    str,   # ProdDeployment
        "price_model":   str,
        "prerequisites": str,   # raw prereq string e.g. "8001 OR 8002"
        "prereq_list":   [str], # parsed list of individual SKUs
      }
    """
    results = []
    for item in skus_map:
        source_app   = item.get("app_name", "")
        source_matnr = item.get("selected", "")
        if not source_matnr:
            continue

        url = f"{_BASE_URL}/MaterialDeploymentSet?$filter=Matnr%20eq%20'{source_matnr}'&$format=json"
        try:
            r = session.get(url, timeout=15)
            if r.status_code != 200:
                continue
            deployments = r.json().get("d", {}).get("results", [])
        except Exception as e:
            logger.warning("Conversion failed for %s: %s", source_matnr, e)
            continue

        # Filter by deployment mode (case-insensitive partial match)
        mode_lower = deployment_mode.lower()
        matches = [
            d for d in deployments
            if mode_lower in d.get("ProdDeployment", "").lower()
        ]

        for d in matches:
            prereq_raw = d.get("Prerequisite", "").strip()
            # Parse "( 8001 OR 8002 OR 8003 )" → ["8001", "8002", "8003"]
            prereq_clean = re.sub(r'[()]', '', prereq_raw).strip()
            prereq_list = [p.strip() for p in re.split(r'\s+OR\s+', prereq_clean) if p.strip()] if prereq_clean else []

            results.append({
                "source_app":    source_app,
                "source_matnr":  source_matnr,
                "target_matnr":  d.get("Matnr", ""),
                "target_desc":   d.get("Descr", ""),
                "status":        d.get("Mstav", ""),
                "status_desc":   d.get("Vmstb", ""),
                "deployment":    d.get("ProdDeployment", ""),
                "price_model":   d.get("PriceModel", ""),
                "prerequisites": prereq_raw,
                "prereq_list":   prereq_list,
            })

    return results


def resolve_prerequisites(
    prereq_skus: list[str],
    session: requests.Session,
) -> list[dict]:
    """
    Resolve a list of prerequisite SKUs to their names via MaterialsetSet.
    Returns [{matnr, maktx}]
    """
    results = []
    seen = set()
    for sku in prereq_skus:
        if not sku or sku in seen:
            continue
        seen.add(sku)
        url = f"{_BASE_URL}/MaterialsetSet('{sku}')?$format=json"
        try:
            r = session.get(url, timeout=10)
            if r.status_code == 200:
                d = r.json().get("d", {})
                results.append({"matnr": sku, "maktx": d.get("Maktx", sku)})
            else:
                results.append({"matnr": sku, "maktx": sku})
        except Exception:
            results.append({"matnr": sku, "maktx": sku})
    return results
