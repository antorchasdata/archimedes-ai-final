"""
catalog_mxp.py — Actualiza sap_rba_catalog.json y sap_rsa_catalog.json
desde el MXP Value Experience Hub (worksphere SAP Reference Architecture).

Uso:
    python3 pipeline/catalog_mxp.py
    python3 pipeline/catalog_mxp.py --dry-run   # solo muestra stats, no escribe

Requiere:
    pip install requests python-dotenv
    MXP_TOKEN en .env  (Bearer token SAP / XSUAA)
    o bien: MXP_BASE_URL si se usa un proxy local con auth ya inyectada
"""

import json
import os
import re
import sys
import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Configuración ──────────────────────────────────────────────────────────────

MXP_BASE_URL = os.getenv("MXP_BASE_URL", "https://mxpresso.cfapps.eu10-004.hana.ondemand.com")
MXP_TOKEN    = os.getenv("MXP_TOKEN", "")

WORKSPHERE_ID = "dc676573-3c8c-493c-8e9a-cfdb22835c56"  # SAP Reference Architecture (RBA/RSA)

ENTITY_BC   = "38bb7648-0835-4ff3-b88b-5b44e17e7b73"  # business_capability
ENTITY_BA   = "2e8a8514-29c0-40bf-9bde-a2cb2f103779"  # business_area
ENTITY_BD   = "22fffeb9-49b9-48dd-8850-2af432be56a8"  # business_domain

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"
RBA_PATH = KNOWLEDGE_DIR / "sap_rba_catalog.json"
RSA_PATH = KNOWLEDGE_DIR / "sap_rsa_catalog.json"

PAGE_SIZE = 100

# Sufijos → nombre canónico de producto SAP
# Mapea solution_suffix de MXP a nombres legibles para el RSA
_SUFFIX_TO_PRODUCT = {
    "S/4 CLD Public":   "SAP S/4HANA Cloud",
    "S/4 CLD Private":  "SAP S/4HANA Cloud Private Edition",
    "S/4":              "SAP S/4HANA",
    "ERP":              "SAP ERP",
    "PaPM CLD":         "SAP Profitability and Performance Management Cloud",
    "PaPM OP":          "SAP Profitability and Performance Management",
    "PaPM OP, BW":      "SAP Profitability and Performance Management",
    "PaPM OP, BW/4HANA":"SAP Profitability and Performance Management",
    "BW/4HANA":         "SAP BW/4HANA",
    "BW":               "SAP Business Information Warehouse",
    "IBP":              "SAP Integrated Business Planning",
    "APO":              "SAP Advanced Planning and Optimization",
    "TM OP":            "SAP Transportation Management",
    "GTS":              "SAP Global Trade Services",
    "SRM":              "SAP Supplier Relationship Management",
    "SRM CLD":          "SAP Ariba Sourcing",
    "Ariba":            "SAP Ariba Sourcing",
    "Ariba CLD":        "SAP Ariba Sourcing",
    "Concur":           "SAP Concur",
    "Fieldglass":       "SAP Fieldglass",
    "SuccessFactors":   "SAP SuccessFactors",
    "SF":               "SAP SuccessFactors",
    "SAC":              "SAP Analytics Cloud",
    "Datasphere":       "SAP Datasphere",
    "CX":               "SAP Customer Experience",
    "C4C":              "SAP Customer Experience",
    "MDG":              "SAP Master Data Governance",
    "MDG CLD":          "SAP Master Data Governance, cloud edition",
    "WM":               "SAP Waste and Recycling",
    "EAM":              "SAP Asset Performance Management",
    "FSM":              "SAP Field Service Management",
    "IBN":              "SAP Intelligent Business Network",
    "LBN":              "SAP Logistics Business Network",
    "SBN":              "SAP Sustainability Business Network",
    "EDAM":             "SAP Enterprise Deployment Automation Management",
    "HXM":              "SAP SuccessFactors",
    "C/4HANA":          "SAP Customer Experience",
}

# ── HTTP helper ────────────────────────────────────────────────────────────────

def _headers():
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if MXP_TOKEN:
        h["Authorization"] = f"Bearer {MXP_TOKEN}"
    return h


def _query_all(entity_id: str, selected_fields: list[str], status: str = "published") -> list[dict]:
    """Descarga todas las entradas de una entidad paginando con top/skip."""
    url = f"{MXP_BASE_URL}/api/mxp/workspheres/{WORKSPHERE_ID}/entities/{entity_id}/entries"
    results = []
    skip = 0
    while True:
        params = {
            "top": PAGE_SIZE,
            "skip": skip,
            "status": status,
            "selectedFields": ",".join(selected_fields),
        }
        resp = requests.get(url, headers=_headers(), params=params, timeout=30)
        if resp.status_code == 401:
            print("ERROR 401 — Token MXP inválido o expirado. Configura MXP_TOKEN en .env")
            sys.exit(1)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        results.extend(batch)
        print(f"  [{entity_id[:8]}] {len(results)}/{skip+len(batch)} descargados...", end="\r")
        if len(batch) < PAGE_SIZE:
            break
        skip += PAGE_SIZE
    print()
    return results


# ── Construcción RBA catalog ───────────────────────────────────────────────────

def _extract_product_name(sc: dict) -> str:
    """Deriva nombre canónico de producto desde un solution_capability."""
    suffix = sc.get("solution_suffix", "")
    base   = sc.get("title_without_suffix", sc.get("title", ""))

    # Si el sufijo está en nuestro mapa → nombre canónico conocido
    if suffix in _SUFFIX_TO_PRODUCT:
        return _SUFFIX_TO_PRODUCT[suffix]

    # Si el título completo ya es un nombre de producto SAP sin sufijo útil
    if not suffix or suffix.strip() == base.strip():
        return base

    # Intento: "SAP X (Suffix)" → strip paréntesis
    clean = re.sub(r"\s*\([^)]*\)\s*$", "", sc.get("title", base)).strip()
    return clean if clean else base


def build_rba_catalog(bc_entries: list[dict]) -> dict:
    """
    Construye el dict con la misma estructura que sap_rba_catalog.json:
    {
      "version": ...,
      "catalog": { enterprise_domain: { business_domain: { business_area: [BCs] } } },
      "bc_index": { "BC123": { name, enterprise_domain, business_domain, business_area, full_path } },
      "short_name_index": { "BC name": "domain / area / name" }
    }
    El enterprise_domain no viene de MXP directamente — lo derivamos del uuid FD* → grupo.
    """
    # MXP no expone enterprise_domain directamente. Usamos el del JSON actual como fallback.
    existing_rba = json.loads(RBA_PATH.read_text()) if RBA_PATH.exists() else {}
    old_bc_index = existing_rba.get("bc_index", {})

    # Mapa uuid BC → enterprise_domain del catálogo anterior (para mantener coherencia)
    _old_ed = {v["name"]: v.get("enterprise_domain", "Corporate") for v in old_bc_index.values()}

    # Estructura jerárquica: enterprise_domain → business_domain → business_area → [BCs]
    tree: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    bc_index: dict = {}
    short_name_index: dict = {}

    enterprise_domains = set()
    business_domains   = set()
    business_areas     = set()

    for bc in bc_entries:
        bc_id   = bc.get("uuid", "")
        bc_name = bc.get("title", "")
        if not bc_id or not bc_name:
            continue

        ba_obj = bc.get("business_area") or {}
        bd_obj = ba_obj.get("business_domain") or {}

        ba_name = ba_obj.get("title", "Unknown Area")
        bd_name = bd_obj.get("title", "Unknown Domain")

        # Enterprise domain: intentamos conservar el del catálogo anterior
        ed_name = _old_ed.get(bc_name, "Corporate")

        enterprise_domains.add(ed_name)
        business_domains.add(bd_name)
        business_areas.add(ba_name)

        tree[ed_name][bd_name][ba_name].append({"id": bc_id, "name": bc_name})

        full_path = f"{bd_name} / {ba_name} / {bc_name}"
        bc_index[bc_id] = {
            "name": bc_name,
            "enterprise_domain": ed_name,
            "business_domain": bd_name,
            "business_area": ba_name,
            "full_path": full_path,
        }
        short_name_index[bc_name] = full_path

    # Convertir defaultdicts a dicts normales y ordenar BCs dentro de cada área
    catalog = {}
    for ed, domains in sorted(tree.items()):
        catalog[ed] = {}
        for bd, areas in sorted(domains.items()):
            catalog[ed][bd] = {}
            for ba, bcs in sorted(areas.items()):
                catalog[ed][bd][ba] = sorted(bcs, key=lambda x: x["name"])

    today = datetime.now().strftime("%Y-%m")
    return {
        "version": today,
        "source": f"SAP Value Experience Hub (MXP API) — auto-generated {datetime.now().strftime('%Y-%m-%d')}",
        "description": "SAP Reference Business Architecture (RBA) — complete Business Capability catalog. Hierarchy: Enterprise Domain > Business Domain > Business Area > BC. Names are canonical SAP RBA names.",
        "stats": {
            "enterprise_domains": len(enterprise_domains),
            "business_domains":   len(business_domains),
            "business_areas":     len(business_areas),
            "business_capabilities": len(bc_index),
        },
        "catalog": catalog,
        "bc_index": bc_index,
        "short_name_index": short_name_index,
    }


# ── Construcción RSA catalog ───────────────────────────────────────────────────

def build_rsa_catalog(bc_entries: list[dict]) -> dict:
    """
    Construye el dict con la misma estructura que sap_rsa_catalog.json:
    {
      "applications": [ { "name": ..., "domain": ... } ],
      "name_index": { "lowercase name": "Canonical Name" }
    }
    Extrae productos únicos de los solution_capabilities de cada BC.
    El dominio del producto se deriva del business_domain de la BC que lo referencia.
    """
    # product_name → set of domains que lo referencian
    product_domains: dict[str, set] = defaultdict(set)

    for bc in bc_entries:
        ba_obj = bc.get("business_area") or {}
        bd_obj = ba_obj.get("business_domain") or {}
        bd_name = bd_obj.get("title", "")

        for sc in bc.get("solution_capability") or []:
            if not sc.get("part_of_lastest_rba_release", False):
                # Solo los que son parte de la última release
                continue
            prod_name = _extract_product_name(sc)
            if prod_name:
                product_domains[prod_name].add(bd_name)

    # Para cada producto, elegir el dominio más frecuente
    applications = []
    for prod_name in sorted(product_domains.keys()):
        domains = product_domains[prod_name]
        # Si solo hay un dominio, usarlo; si hay varios, el primero alfabético
        domain = sorted(domains)[0] if domains else "General"
        applications.append({"name": prod_name, "domain": domain})

    # Ordenar por dominio luego por nombre
    applications.sort(key=lambda x: (x["domain"], x["name"]))

    # Construir name_index (lowercase → canonical)
    name_index = {app["name"].lower(): app["name"] for app in applications}

    today = datetime.now().strftime("%Y-%m")
    return {
        "version": today,
        "source": f"SAP Value Experience Hub (MXP API) — auto-generated {datetime.now().strftime('%Y-%m-%d')}",
        "description": "SAP Reference Solution Architecture (RSA) — canonical SAP product names extracted from RBA Solution Capabilities (part_of_lastest_rba_release=true). Use these verbatim in fact sheet names. Grouped by functional domain.",
        "stats": {
            "total_products": len(applications),
            "domains": len(set(a["domain"] for a in applications)),
        },
        "applications": applications,
        "name_index": name_index,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Actualiza catálogos RBA/RSA desde MXP API")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra stats, no escribe ficheros")
    args = parser.parse_args()

    print("=" * 60)
    print("Archimedes — Actualización catálogos RBA/RSA desde MXP")
    print("=" * 60)

    if not MXP_TOKEN:
        print("\nAVISO: MXP_TOKEN no configurado en .env")
        print("Si el servidor MXP requiere auth, las llamadas fallarán con 401.")
        print("Continuando de todas formas (puede funcionar con auth implícita)...\n")

    # 1. Descargar BCs con jerarquía completa
    print("\n[1/3] Descargando Business Capabilities...")
    bc_entries = _query_all(
        ENTITY_BC,
        selected_fields=["uuid", "title", "type", "cross_industry_relevant", "business_area", "solution_capability"],
    )
    print(f"      → {len(bc_entries)} BCs descargadas")

    if not bc_entries:
        print("ERROR: No se descargaron BCs. Verifica token y worksphereId.")
        sys.exit(1)

    # 2. Construir catálogos
    print("\n[2/3] Construyendo catálogos RBA y RSA...")
    rba = build_rba_catalog(bc_entries)
    rsa = build_rsa_catalog(bc_entries)

    print(f"      RBA: {rba['stats']['business_capabilities']} BCs | "
          f"{rba['stats']['business_domains']} dominios | "
          f"{rba['stats']['business_areas']} áreas")
    print(f"      RSA: {rsa['stats']['total_products']} productos | "
          f"{rsa['stats']['domains']} dominios")

    if args.dry_run:
        print("\n[DRY RUN] No se escriben ficheros.")
        print("\nSample BC index:")
        for k, v in list(rba["bc_index"].items())[:3]:
            print(f"  {k}: {v['full_path']}")
        print("\nSample RSA products:")
        for a in rsa["applications"][:5]:
            print(f"  {a['name']} ({a['domain']})")
        return

    # 3. Escribir ficheros
    print("\n[3/3] Escribiendo ficheros...")
    RBA_PATH.write_text(json.dumps(rba, ensure_ascii=False, indent=2))
    print(f"      ✓ {RBA_PATH}")
    RSA_PATH.write_text(json.dumps(rsa, ensure_ascii=False, indent=2))
    print(f"      ✓ {RSA_PATH}")

    print("\n✅ Catálogos actualizados correctamente.")
    print(f"   RBA: {rba['stats']['business_capabilities']} BCs ({rba['version']})")
    print(f"   RSA: {rsa['stats']['total_products']} productos ({rsa['version']})")


if __name__ == "__main__":
    main()
