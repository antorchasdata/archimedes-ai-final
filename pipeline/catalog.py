"""
catalog.py — Catalog version check and optional update.

Reads version/source metadata from sap_rba_catalog.json and sap_rsa_catalog.json,
displays it to the user, and offers an update option.

Update strategy: re-downloads from the Value Experience Hub export file if provided,
or prompts the user to supply an updated export. Since the hub requires manual export,
the update path accepts a path to a freshly downloaded Hierarchical Exploration View
Excel and regenerates the catalog JSONs using the existing build scripts (if present),
or marks the catalog as needing manual update.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"
RBA_PATH = KNOWLEDGE_DIR / "sap_rba_catalog.json"
RSA_PATH = KNOWLEDGE_DIR / "sap_rsa_catalog.json"


def _catalog_info(path: Path) -> dict:
    """Return version/source/stats from a catalog JSON."""
    data = json.loads(path.read_text())
    return {
        "version": data.get("version", "unknown"),
        "source":  data.get("source",  "unknown"),
        "stats":   data.get("stats",   {}),
    }


def check_catalogs(interactive: bool = True) -> bool:
    """
    Display catalog version info and optionally prompt the user to update.

    Args:
        interactive: If True, prompt the user via stdin. If False, just log and return.

    Returns:
        True if the pipeline should continue, False if the user chose to abort.
    """
    print("\n" + "═" * 60)
    print("  PASO 0 — Catálogos SAP RBA / RSA")
    print("═" * 60)

    for label, path in [("RBA", RBA_PATH), ("RSA", RSA_PATH)]:
        if not path.exists():
            print(f"  [{label}] ⚠  No encontrado: {path}")
            continue
        info = _catalog_info(path)
        stats = info["stats"]
        stats_str = "  |  ".join(f"{k}: {v}" for k, v in stats.items())
        print(f"  [{label}] versión: {info['version']}")
        print(f"         fuente:  {info['source']}")
        print(f"         stats:   {stats_str}")

    print("─" * 60)

    if not interactive:
        return True

    answer = input("  ¿Actualizar catálogos antes de continuar? [s/N]: ").strip().lower()
    if answer in ("s", "si", "sí", "y", "yes"):
        return _prompt_update()

    print("  → Catálogos actuales. Continuando.\n")
    return True


def _prompt_update() -> bool:
    """
    Guide the user through supplying a new catalog export and regenerating JSONs.

    Returns True to continue, False to abort.
    """
    print()
    print("  Para actualizar los catálogos necesitas un export del Value Experience Hub:")
    print("  1. Accede a https://valueexperiencehub.sap.com")
    print("  2. Capability Model → Export → Hierarchical Exploration View (.xlsx)")
    print("  3. Proporciona la ruta al fichero descargado aquí.")
    print()

    xlsx_input = input("  Ruta al fichero Excel del Value Experience Hub (Enter para cancelar): ").strip()
    if not xlsx_input:
        print("  → Actualización cancelada. Continuando con catálogos actuales.\n")
        return True

    xlsx_path = Path(xlsx_input).expanduser()
    if not xlsx_path.exists():
        print(f"  ⚠  Fichero no encontrado: {xlsx_path}")
        print("  → Continuando con catálogos actuales.\n")
        return True

    # Check if build scripts exist
    build_rba = KNOWLEDGE_DIR.parent / "scripts" / "build_rba_catalog.py"
    build_rsa = KNOWLEDGE_DIR.parent / "scripts" / "build_rsa_catalog.py"

    if build_rba.exists() and build_rsa.exists():
        import subprocess
        print(f"  → Regenerando RBA desde {xlsx_path.name} …")
        subprocess.run(["python3", str(build_rba), str(xlsx_path)], check=True)
        print(f"  → Regenerando RSA desde {xlsx_path.name} …")
        subprocess.run(["python3", str(build_rsa), str(xlsx_path)], check=True)
        print("  ✓ Catálogos actualizados.\n")
    else:
        # No build scripts available — copy file and log for manual update
        import shutil
        dest = KNOWLEDGE_DIR / xlsx_path.name
        shutil.copy2(xlsx_path, dest)
        logger.warning(
            "Build scripts not found. Copied %s to %s. "
            "Run build scripts manually to regenerate catalog JSONs.",
            xlsx_path.name, dest,
        )
        print(f"  ⚠  Scripts de build no encontrados en {KNOWLEDGE_DIR.parent / 'scripts'}/")
        print(f"     Fichero copiado a: {dest}")
        print("     Actualiza los JSONs manualmente y vuelve a ejecutar el pipeline.\n")
        answer = input("  ¿Continuar con catálogos actuales? [S/n]: ").strip().lower()
        if answer in ("n", "no"):
            return False

    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    check_catalogs()
