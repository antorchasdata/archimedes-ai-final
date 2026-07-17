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
from dataclasses import asdict
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


_BULK_CHUNK_SIZE = 50


def process_inbox(
    session_dir: Path,
    client: Client,
    catalog: dict,
    create_factsheet,
) -> dict:
    """Phase 2: pull inbox, decide, execute link/create/reject.

    Args:
        session_dir: session working directory.
        client: pipeline.sap_discovery.client.Client instance.
        catalog: {product_name: metadata} lookup for the matcher.
        create_factsheet: callable(payload_dict) -> {"id": str}. Injected so the
            orchestrator does not import pipeline.write directly (keeps tests
            hermetic and avoids circular imports).

    Returns execution_log dict and persists snapshot/decisions/log.
    """
    state = _read_json(session_dir / "integration.json")
    origin = state["origin"]

    items = client.list_inbox(origin=origin, status="action_needed,review_needed")
    _write_json(
        session_dir / "inbox_snapshot.json",
        [i.raw for i in items],
    )

    decisions: list[MatchDecision] = [decide(i, catalog) for i in items]
    _write_json(session_dir / "decisions.json", [asdict(d) for d in decisions])

    pending_review: list[str] = []
    to_link: list[dict] = []
    to_reject: list[str] = []

    for d in decisions:
        if d.action == "review":
            pending_review.append(d.item_id)
        elif d.action == "reject":
            # includes "already linked" skips — do NOT re-reject those
            if d.reason.lower().startswith("item already linked"):
                continue
            to_reject.append(d.item_id)
        elif d.action == "link":
            to_link.append({
                "itemId": d.item_id,
                "targetType": d.target_type,
                "targetId": d.target_id,
            })
        elif d.action == "create_and_link":
            created = create_factsheet(d.create_payload)
            to_link.append({
                "itemId": d.item_id,
                "targetType": d.target_type,
                "targetId": created["id"],
            })

    applied: list[str] = []
    failed: list[dict] = []

    for chunk_start in range(0, len(to_link), _BULK_CHUNK_SIZE):
        chunk = to_link[chunk_start:chunk_start + _BULK_CHUNK_SIZE]
        resp = client.bulk_link(origin=origin, decisions=chunk)
        applied.extend(resp.get("applied", []))
        failed.extend(resp.get("failed", []))

    if to_reject:
        resp = client.bulk_reject(origin=origin, item_ids=to_reject)
        applied.extend(resp.get("applied", []))
        failed.extend(resp.get("failed", []))

    log = {
        "applied": applied,
        "failed": failed,
        "pending_review": pending_review,
    }
    _write_json(session_dir / "execution_log.json", log)
    return log


def apply_review(session_dir: Path, client: Client, decisions: list[dict]) -> dict:
    """Phase 3: apply human-confirmed decisions from the review report.

    Each decision: {"item_id": str, "action": "link"|"reject", "target_type"?: str, "target_id"?: str}.
    """
    state = _read_json(session_dir / "integration.json")
    origin = state["origin"]

    to_link = [
        {"itemId": d["item_id"], "targetType": d["target_type"], "targetId": d["target_id"]}
        for d in decisions if d["action"] == "link"
    ]
    to_reject = [d["item_id"] for d in decisions if d["action"] == "reject"]

    applied: list[str] = []
    failed: list[dict] = []

    if to_link:
        resp = client.bulk_link(origin=origin, decisions=to_link)
        applied.extend(resp.get("applied", []))
        failed.extend(resp.get("failed", []))

    if to_reject:
        resp = client.bulk_reject(origin=origin, item_ids=to_reject)
        applied.extend(resp.get("applied", []))
        failed.extend(resp.get("failed", []))

    log_path = session_dir / "execution_log.json"
    existing = _read_json(log_path) if log_path.exists() else {"applied": [], "failed": [], "pending_review": []}
    existing["applied"] = list(set(existing.get("applied", [])) | set(applied))
    existing["failed"] = existing.get("failed", []) + failed
    processed_ids = {d["item_id"] for d in decisions}
    existing["pending_review"] = [
        i for i in existing.get("pending_review", []) if i not in processed_ids
    ]
    _write_json(log_path, existing)
    return existing
