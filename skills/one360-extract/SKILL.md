---
name: one360-extract
description: Guided browser extraction of the 3 ONE360 landscape exports (Cloud Systems, OnPrem System Landscape, Purchased Solutions) for a given customer using the archimedes-browser Playwright MCP. Downloads land in the shared session directory and are then POSTed to the Archimedes wizard's /baseline/from-one360 endpoint. Use when the user says "extract from ONE360", "pull the landscape for <customer>", or clicks the ONE360 tab in Step 2 of the wizard.
---

# ONE360 Extractor

Drives the internal SAP ONE360 portal (https://one360.for.sap) via the `archimedes-browser` Playwright MCP to download the three Excel exports Archimedes needs for a customer's baseline:

- **Cloud Systems** — `Cloud-Systems-Table-*.xlsx`
- **OnPrem System Landscape** — `System-Landscape-Details-Table-*.xlsx`
- **Purchased Solutions (contracts)** — `Purchased-Solutions-Table*LPR-*.xlsx`

Then handshakes with the Archimedes wizard so the user does not have to upload the files manually.

---

## Inputs

The invoker MUST provide:

- `session_id` — Archimedes wizard session UUID (from Step 0 of the wizard).
- `customer` — customer name or ONE360 account ID. If a plain name, resolve it via the ONE360 search / landing page.

If either is missing, ask the user.

---

## Preconditions

1. `archimedes-browser` MCP is registered in `.mcp.json` (points to `bin/launch-browser.sh`). If tools with prefix `mcp__archimedes-browser__` are unavailable, tell the user to reload their MCP servers.
2. The wizard is running locally (default: `http://localhost:8767`). Confirm with `curl -sS http://localhost:8767/api/config` if unsure.
3. Downloads land in `$ARCHIMEDES_ONE360_DIR` (set by `bin/launch-browser.sh`, falls back to `<repo>/downloads/one360`). This same directory is what `GET /api/session/{id}/baseline/one360-status` polls.

---

## Steps

### 1. Open ONE360 and let the user authenticate

Use `mcp__archimedes-browser__browser_navigate` to go to `https://one360.for.sap/experiences/1csw/pages/landing-page`.

Take a snapshot (`browser_snapshot`) and inspect. If the page shows the SSO login screen, tell the user:

> "Log in with your SAP corporate credentials in the browser window. I'll wait — reply when you're on the ONE360 landing page."

Do NOT try to type credentials yourself. Wait for the user's go-ahead.

### 2. Resolve the account ID

If the user gave you the raw account ID, skip this step.

Otherwise, on the landing page, use the search widget to find the customer (`browser_type` into the search input, then `browser_click` the matching result). Once on the single-customer page, extract the `accountId` query parameter from the URL — `pipeline.one360_extractor.extract_account_id_from_url` has the exact regex.

Confirm with the user before proceeding: "I'm about to pull the landscape for `<Customer Name>` (accountId=`<ID>`). Proceed?"

### 3. Download the 3 exports — one per deep-link

For each of `cloud`, `onprem`, `contracts`:

a. Build the deep-link URL — call `pipeline.one360_extractor.build_download_urls(account_id)` conceptually (the URLs are stable, so you can construct them directly):
   - Cloud: `.../single-customer?accountId=<ID>&tab=system_landscape&nf-selected-section=system-landscape-cloud`
   - OnPrem: `.../single-customer?accountId=<ID>&tab=system_landscape&nf-selected-section=system-landscape-onpremise`
   - Contracts: `.../single-customer?accountId=<ID>&tab=contracts&nf-selected-section=purchased-solutions`

b. Take a snapshot of the current download directory BEFORE clicking export:
   ```bash
   ls "$ARCHIMEDES_ONE360_DIR" 2>/dev/null > /tmp/one360_before_<key>.txt || true
   ```

c. `browser_navigate` to the deep-link. Wait for the table to render (`browser_wait_for` with a short text unique to the section, or a 3s wait).

d. Click the "Export" / download-icon button. In ONE360 this is the ⬇ icon in the top-right of each table. Use `browser_snapshot` + `browser_click` on the export ref.

e. Poll the download dir until a NEW file appears whose name matches the expected pattern (see `pipeline.one360_extractor.FILENAME_PATTERNS`). If a file that does NOT match the pattern appears, stop and warn the user — you probably clicked the wrong export.

   You can also call the wizard's status endpoint to check:
   ```bash
   curl -sS http://localhost:8767/api/session/<session_id>/baseline/one360-status
   ```
   The `downloaded.<key>` field flips to `true` when the matching file lands.

f. Repeat for the other two exports.

### 4. Hand off to the wizard

Once all 3 (or at minimum `cloud` and/or `onprem` — contracts is optional) are on disk, POST the paths to the wizard:

```bash
curl -sS -X POST "http://localhost:8767/api/session/<session_id>/baseline/from-one360" \
  -H "Content-Type: application/json" \
  -d '{
    "onprem_path":    "<abs path from status endpoint>",
    "cloud_path":     "<abs path>",
    "contracts_path": "<abs path or omit>"
  }'
```

The response has the same shape as the manual `/baseline` endpoint (`n_onprem`, `n_cloud`, `n_total`, `download_url`). Report the counts to the user and tell them Step 2 is complete.

### 5. Cleanup (optional)

Do NOT delete the downloaded files — the wizard has already copied them into the session directory. The user may want the originals for audit. `bin/launch-browser.sh` already sets `--output-dir` to a dedicated location, so they won't pollute anywhere else.

---

## Failure modes

- **SSO expired mid-flow** → the page redirects to login. Ask the user to re-authenticate, then resume from the current step.
- **Export button not found** → the ONE360 UI changed. Fall back: ask the user to click Export manually while you keep polling the status endpoint.
- **Wrong file downloaded** → the pattern check in `pipeline.one360_extractor.detect_new_file` raises `ValueError`. Stop and report which file appeared; likely you clicked the wrong section.
- **Account not found** → the search widget shows no result. Ask the user to double-check the customer name or provide the accountId directly.

---

## What NOT to do

- Do NOT type SAP credentials — always defer to the user.
- Do NOT retry a failed navigation more than twice in a row. If it keeps failing, ask the user to check the browser window.
- Do NOT upload the downloaded files back via `POST /baseline` (that endpoint expects multipart file uploads). Always use `POST /baseline/from-one360` with filesystem paths.
- Do NOT delete files from `$ARCHIMEDES_ONE360_DIR` — the user may run the flow multiple times.

---

## References

- Utility module: `pipeline/one360_extractor.py` (URL builders, filename patterns, snapshot/diff helpers).
- Wizard endpoint: `archimedes_wizard.py` — `POST /baseline/from-one360`, `GET /baseline/one360-status`.
- Playwright MCP launcher: `bin/launch-browser.sh` (sets `ARCHIMEDES_ONE360_DIR`).
- Reference implementation this was adapted from: SAP internal `app-landscape-builder` repo on github.tools.sap.
