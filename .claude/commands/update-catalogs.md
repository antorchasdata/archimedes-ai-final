# /update-catalogs — Actualiza catálogos RBA/RSA desde MXP

Actualiza `sap_rba_catalog.json` y `sap_rsa_catalog.json` directamente desde el
Value Experience Hub (MXP API) usando el MCP server `mxp-mcp` de esta sesión de Claude Code.

## Cuándo usar

Cuando el usuario quiera refrescar los catálogos de referencia SAP RBA/RSA en Archimedes.
El wizard muestra el botón "Actualizar desde MXP" — si falla con error de token, redirige aquí.

## Instrucciones

Ejecuta los pasos siguientes **en orden**. No te saltes ninguno.

### Paso 1 — Descargar Business Areas (con Business Domain anidado)

Llama a `mxp-mcp / query-entries` con:
- worksphereId: `dc676573-3c8c-493c-8e9a-cfdb22835c56`
- entityId: `2e8a8514-29c0-40bf-9bde-a2cb2f103779`  (business_area)
- selectedFields: `["uuid", "title", "business_domain"]`
- status: `published`
- top: 100, skip: 0

Repite con skip=100, skip=200... hasta que el batch esté vacío o tenga < 100 entradas.
Construye un dict `AR_MAP = { ba_uuid: { ba_title, bd_title } }`.

### Paso 2 — Descargar Business Capabilities (paginado, 12 páginas aprox.)

Llama a `mxp-mcp / query-entries` con:
- worksphereId: `dc676573-3c8c-493c-8e9a-cfdb22835c56`
- entityId: `38bb7648-0835-4ff3-b88b-5b44e17e7b73`  (business_capability)
- selectedFields: `["uuid", "title", "type", "cross_industry_relevant", "business_area", "solution_capability"]`
- status: `published`
- top: 100, skip: 0 → 100 → 200 → ... hasta batch vacío

Acumula todos los BCs en una lista.

### Paso 3 — Construir RBA catalog

Para cada BC:
- `bc_id` = uuid, `bc_name` = title
- `ba_uuid` = business_area.id o business_area[0].id (puede ser lista)
- `ba_title`, `bd_title` = AR_MAP.get(ba_uuid, {})
- `ed_name` = deriva del business_domain usando BD_TO_ED mapping:

```
BD_TO_ED = {
  "Finance":                    "Corporate",
  "Controlling":                "Corporate",
  "Human Resources":            "Corporate",
  "Real Estate":                "Corporate",
  "Research & Development":     "Corporate",
  "Compliance":                 "Corporate",
  "Strategy":                   "Corporate",
  "Sales":                      "Customer",
  "Marketing":                  "Customer",
  "Service":                    "Customer",
  "Commerce":                   "Customer",
  "Customer Engagement":        "Customer",
  "Manufacturing":              "Operations",
  "Supply Chain":               "Operations",
  "Procurement":                "Operations",
  "Asset Management":           "Operations",
  "Quality Management":         "Operations",
  "Project Management":         "Operations",
  "Logistics":                  "Operations",
  "Sustainability":             "Operations",
  "IT":                         "Technology",
  "Platform":                   "Technology",
  "Data & Analytics":           "Technology",
  "Integration":                "Technology",
}
# Default: "Corporate"
```

Genera estructura:
```json
{
  "version": "YYYY-MM",
  "source": "SAP Value Experience Hub (MXP API) — auto-generated YYYY-MM-DD",
  "description": "SAP Reference Business Architecture (RBA) ...",
  "stats": { "enterprise_domains": N, "business_domains": N, "business_areas": N, "business_capabilities": N },
  "catalog": { "<ed>": { "<bd>": { "<ba>": [ {"id": "...", "name": "..."} ] } } },
  "bc_index": { "<uuid>": { "name", "enterprise_domain", "business_domain", "business_area", "full_path" } },
  "short_name_index": { "<bc_name>": "<bd> / <ba> / <bc_name>" }
}
```

### Paso 4 — Construir RSA catalog

Para cada BC, itera `solution_capability`:
- Solo los que tienen `part_of_lastest_rba_release == true`
- Mapea `solution_suffix` a nombre canónico usando `_SUFFIX_TO_PRODUCT` de `pipeline/catalog_mxp.py`
- Si no está en el mapa, usa `title_without_suffix` o el título limpio (sin paréntesis)
- Acumula `product_name → set(bd_title)`

Genera estructura:
```json
{
  "version": "YYYY-MM",
  "source": "SAP Value Experience Hub (MXP API) — auto-generated YYYY-MM-DD",
  "description": "SAP Reference Solution Architecture (RSA) ...",
  "stats": { "total_products": N, "domains": N },
  "applications": [ { "name": "...", "domain": "..." } ],
  "name_index": { "<lowercase_name>": "<canonical_name>" }
}
```

### Paso 5 — Escribir ficheros

Escribe los JSON resultantes en:
- `/Users/I519409/dev/archimedes-ai/knowledge/sap_rba_catalog.json`
- `/Users/I519409/dev/archimedes-ai/knowledge/sap_rsa_catalog.json`

Usa `json.dumps(..., ensure_ascii=False, indent=2)`.

### Paso 6 — Confirmar

Muestra un resumen:
```
✅ Catálogos actualizados:
   RBA: <N> BCs | <N> dominios | <N> áreas  (versión YYYY-MM)
   RSA: <N> productos | <N> dominios         (versión YYYY-MM)
```

## Notas

- La autenticación MXP es automática vía sesión Claude Code (SSO SAP). No se necesita token.
- Si alguna llamada MXP falla, reintenta una vez. Si falla de nuevo, informa al usuario.
- El enterprise_domain NO viene de MXP — lo derivamos del business_domain con BD_TO_ED.
- El script `pipeline/catalog_mxp.py` requiere MXP_TOKEN en .env (no funciona en terminal).
  Este skill usa el MCP server directamente, que sí tiene auth.
