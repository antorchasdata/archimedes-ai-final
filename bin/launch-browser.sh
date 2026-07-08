#!/bin/sh
# Playwright MCP launcher for Archimedes ONE360 extractor skill.
# Downloads land in $ARCHIMEDES_ONE360_DIR if set, else in a plugin-local fallback.
DOWNLOAD_DIR="${ARCHIMEDES_ONE360_DIR:-${CLAUDE_PLUGIN_ROOT:-/Users/I519409/dev/archimedes-ai}/downloads/one360}"
mkdir -p "$DOWNLOAD_DIR"
exec npx -y @playwright/mcp@0.0.75 --output-dir "$DOWNLOAD_DIR"
