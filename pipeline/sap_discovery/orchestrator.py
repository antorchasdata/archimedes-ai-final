"""pipeline.sap_discovery.orchestrator — two-phase flow (start + poll + process + apply).

Uses:
- Client (injected) for all REST I/O
- pipeline.write.create_factsheet for fact sheet creation
- pipeline.sap_discovery.matcher.decide for pure decision logic

All state persisted under session_dir/ as JSON.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.sap_discovery.client import Client, DiscoveryItem
from pipeline.sap_discovery.matcher import MatchDecision, decide


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def start_integration(
    session_dir: Path,
    client: Client,
    crm_id: str,
    enable_autolinking: bool = True,
) -> dict:
    """Phase 1: create the integration, discover origin, optionally enable autolinking.

    Persists integration.json and returns the state dict.
    """
    integration = client.create_integration(crm_id=crm_id)
    origin = client.discover_origin()

    if enable_autolinking:
        client.set_autolinking(origin=origin, enabled=True)

    state = {
        "integration_id": integration.get("id"),
        "crm_id": crm_id,
        "origin": origin,
        "autolinking_enabled": bool(enable_autolinking),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    _write_json(session_dir / "integration.json", state)
    return state


def poll_status(session_dir: Path, client: Client) -> dict:
    """Phase 1b: check whether inbox has items yet."""
    state = _read_json(session_dir / "integration.json")
    origin = state["origin"]
    items = client.list_inbox(origin=origin)
    action_needed = sum(1 for i in items if i.status == "action_needed")
    review_needed = sum(1 for i in items if i.status == "review_needed")
    ready = len(items) > 0
    return {
        "status": "ready" if ready else "pending",
        "inbox_count": len(items),
        "action_needed": action_needed,
        "review_needed": review_needed,
    }
