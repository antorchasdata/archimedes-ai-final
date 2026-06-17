# Workspace Selector — Design Spec

**Date:** 2026-06-16
**Status:** Approved

---

## Overview

Add a LeanIX workspace selector to Step 0 (Client name) of the Archimedes AI wizard. The user picks (or creates) a workspace in the same step where they enter the client name. From that point on, every API call in the session uses the credentials of the selected workspace instead of the `.env` defaults.

---

## User Flow

1. User opens the wizard — lands on Step 0 (Client & Workspace).
2. **Client name** input (existing, unchanged).
3. **LeanIX Workspace** dropdown — populated from `workspaces.json`.
   - Options: saved workspaces + `"+ Create new workspace…"` at the bottom.
4. User selects a saved workspace → clicks **Validate** → green badge appears (`✓ Connected · <name> · N applications`).
5. **OR** user selects "Create new workspace…" → inline form expands below the dropdown with:
   - **Name** (free text label, e.g. "BBVA Production")
   - **Base URL** (e.g. `https://yourcompany.leanix.net`)
   - **Technical User API Token** (password field)
   - **Save & Validate** button → validates against LeanIX API, saves to `workspaces.json`, collapses form, selects new entry in dropdown, shows green badge.
   - **Cancel** button → collapses form, resets dropdown.
6. Continue button is enabled only when both client name and a validated workspace are present.
7. The validated workspace (`base_url` + `api_token`) is stored in the session object and used by all subsequent steps (baseline push, target push, industry reference, KPI easter egg).

---

## Data Model

### `workspaces.json` (project root)

```json
{
  "workspaces": [
    {
      "name": "SAP Internal",
      "base_url": "https://app.leanix.net",
      "api_token": "eyJ..."
    },
    {
      "name": "Customer Demo",
      "base_url": "https://acme.leanix.net",
      "api_token": "eyJ..."
    }
  ]
}
```

- Stored at `<project_root>/workspaces.json`.
- Tokens stored in plaintext (same security model as the existing `.env`).
- File created automatically on first save if it doesn't exist.

### Session object additions

```python
_sessions[session_id] = {
    ...existing fields...,
    "leanix_base_url": str,   # from selected workspace
    "leanix_api_token": str,  # from selected workspace
}
```

---

## Backend — New Endpoints

### `GET /api/workspaces`
Returns the list of saved workspaces (names + URLs, **no tokens** in response).

```json
{
  "ok": true,
  "workspaces": [
    {"name": "SAP Internal", "base_url": "https://app.leanix.net"},
    {"name": "Customer Demo", "base_url": "https://acme.leanix.net"}
  ]
}
```

### `POST /api/workspaces/validate`
Validates credentials against the LeanIX API (calls `/services/mtm/v1/workspaces/currentUserWorkspaces`).

Request body:
```json
{"name": "SAP Internal", "base_url": "https://app.leanix.net", "api_token": "eyJ..."}
```

Response (success):
```json
{"ok": true, "workspace_name": "SAP Internal", "n_applications": 142}
```

Response (failure):
```json
{"ok": false, "detail": "Invalid token or unreachable host"}
```

Does **not** save to `workspaces.json` — saving is done by `/api/workspaces` POST.

### `POST /api/workspaces`
Saves a new workspace to `workspaces.json`. Called after a successful validate.

Request body:
```json
{"name": "BBVA Production", "base_url": "https://bbva.leanix.net", "api_token": "eyJ..."}
```

Upserts by name (replaces if name already exists).

### `POST /api/session` (modified)
Accepts two additional fields alongside `client_name`:

```json
{
  "client_name": "BBVA",
  "leanix_base_url": "https://bbva.leanix.net",
  "leanix_api_token": "eyJ..."
}
```

Stores both in `_sessions[session_id]`. If omitted, falls back to `os.environ` values (backwards-compatible).

---

## Backend — Modified Endpoints

All endpoints that currently read `os.environ.get("LEANIX_API_TOKEN")` / `os.environ.get("LEANIX_BASE_URL")` are updated to read from the session object first, falling back to env vars:

```python
def _leanix_creds(sess: dict) -> tuple[str, str]:
    base_url  = sess.get("leanix_base_url")  or os.environ.get("LEANIX_BASE_URL", "")
    api_token = sess.get("leanix_api_token") or os.environ.get("LEANIX_API_TOKEN", "")
    return base_url, api_token
```

Affected endpoints (7 locations in `archimedes_wizard.py`):
- `POST /api/session/{id}/push` (lines 845–846, 857, 865)
- `POST /api/session/{id}/push-ldif` (lines 887–888, 899)
- `POST /api/session/{id}/generate` (lines 924–925, 1011–1012, 1132–1133)
- `POST /api/session/{id}/push-kpi` (lines 1186–1187, 1215)
- Industry reference step (line 623)

---

## Frontend — Changes to `archimedes_wizard.html`

### Step 0 card additions

Below the existing client name `<input>`, add:

1. `<hr>` separator.
2. "LeanIX Workspace" label + dropdown (`<select>`) populated via `GET /api/workspaces` on step render.
3. **Validate** button → calls `POST /api/workspaces/validate` with stored token for selected workspace name.
4. Green badge `<div>` (hidden until validated).
5. Inline "New workspace" form (hidden until "Create new…" selected):
   - Name, Base URL, API Token fields.
   - Save & Validate → calls `POST /api/workspaces` then `POST /api/workspaces/validate`.
   - Cancel → collapses form.

### Continue button guard

`nextStep()` for Step 0 checks that:
- `clientName.trim()` is non-empty, AND
- a workspace has been validated in this session (`sessionWorkspaceValidated === true`).

### Workspace badge in header

After validation, show a small workspace indicator in the header (next to the existing step label):
`🏢 SAP Internal` — so the user always knows which workspace they're working against.

### Translations

Add workspace-related strings to all 5 language blocks (`en`, `es`, `fr`, `it`, `fi`).

---

## `workspaces.json` — Security Note

Tokens are stored in plaintext, consistent with the existing `.env` approach. The file should be added to `.gitignore`.

---

## Backwards Compatibility

- If `workspaces.json` doesn't exist, the dropdown shows only "Create new workspace…".
- If the user skips workspace selection (no entry selected), the session falls back to `.env` credentials — existing behavior preserved.
- All existing API consumers unaffected.
