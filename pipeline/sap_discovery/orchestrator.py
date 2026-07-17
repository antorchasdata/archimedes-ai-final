"""pipeline.sap_discovery.orchestrator — flow for real LeanIX Internal SAP Landscape Data.

Uses:
- Client (injected) for all REST I/O
- pipeline.sap_discovery.matcher.decide for pure decision logic
- create_factsheet callable (usually built via make_create_factsheet_bridge)

All state persisted under session_dir/ as JSON.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from pipeline.sap_discovery.client import Client, DiscoveryItem, IntegrationNotFoundError
from pipeline.sap_discovery.matcher import MatchDecision, decide


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def discover_integration(client: Client, session_dir: Path) -> dict:
    """Detect the pre-existing SLIS integration; persist metadata; return it.

    The integration is configured by the workspace admin in the LeanIX UI —
    Archimedes only *reads* it. Raises IntegrationNotFoundError with a
    user-facing message if none is active.
    """
    integ = client.find_active_slis_integration()
    _write_json(session_dir / "integration.json", integ)
    return integ


def poll_status(client: Client, session_dir: Path) -> dict:
    """Report inbox readiness. Uses persisted integration.json only for metadata."""
    items = client.list_inbox()
    return {
        "inbox_count": len(items),
        "action_needed": sum(1 for i in items if i.review_status == "action_needed"),
        "linked": sum(1 for i in items if i.linking_status == "linked"),
        "not_linked": sum(1 for i in items if i.linking_status == "not_linked"),
    }


def process_inbox(
    client: Client,
    session_dir: Path,
    *,
    create_factsheet: Callable[[dict], dict] | None = None,
    dry_run: bool = False,
) -> dict:
    """Pull inbox, decide, and (unless dry_run) apply the plan.

    Flow:
      1. list_inbox -> persist raw snapshot
      2. decide for each item -> persist decisions.json
      3. For each "link" decision: set_link_selection with links_per_node.
         For each "create_and_link": create fact sheets first (create_factsheet
         callable), substitute the new IDs into links_per_node, then
         set_link_selection.
      4. bulk_link on all "link" + "create_and_link" item ids.
      5. bulk_reject on all "reject" item ids (skip HIGH "already linked" —
         those don't need a re-reject).
      6. Persist execution_log.json.

    Args:
        client: sap_discovery.Client instance.
        session_dir: where to persist snapshots and logs.
        create_factsheet: callable(payload) -> {"id": str}. Required when any
            decision.action == "create_and_link". Payload keys:
            {"type": str, "name": str, "attributes": {...}}.
        dry_run: if True, skip HTTP writes (no set_link_selection / bulk_*),
            still persist snapshot + decisions.
    """
    items = client.list_inbox()
    _write_json(session_dir / "inbox_snapshot.json", [i.raw for i in items])

    decisions: list[MatchDecision] = [decide(i) for i in items]
    _write_json(session_dir / "decisions.json", [asdict(d) for d in decisions])

    pending_review: list[str] = [d.item_id for d in decisions if d.action == "review"]

    if dry_run:
        log = {
            "applied": [],
            "failed": [],
            "pending_review": pending_review,
            "dry_run": True,
        }
        _write_json(session_dir / "execution_log.json", log)
        return log

    applied: list[str] = []
    failed: list[dict] = []

    link_ids: list[str] = []
    reject_ids: list[str] = []

    for d in decisions:
        if d.action == "review":
            continue
        if d.action == "reject":
            if d.reason.lower().startswith("item already linked"):
                # Nothing to do: LeanIX already has the link, and re-reject would 4xx.
                continue
            reject_ids.append(d.item_id)
            continue

        # link or create_and_link
        try:
            links_per_node = dict(d.links_per_node)
            if d.action == "create_and_link":
                if create_factsheet is None:
                    raise RuntimeError(
                        f"decision {d.item_id} needs create_and_link but no "
                        "create_factsheet callable was provided"
                    )
                for create in d.creates:
                    node_id = create["nodeId"]
                    fs = create_factsheet({
                        "type": create["factSheetType"],
                        "name": create["factSheetName"],
                        "attributes": {},
                    })
                    links_per_node[node_id] = {"factSheetId": fs["id"]}
            client.set_link_selection(d.item_id, links_per_node=links_per_node)
            link_ids.append(d.item_id)
        except Exception as exc:  # noqa: BLE001
            failed.append({"itemId": d.item_id, "reason": str(exc)})

    if link_ids:
        try:
            resp = client.bulk_link(link_ids)
            applied.extend(resp.get("applied", link_ids))
            failed.extend(resp.get("failed", []))
        except Exception as exc:  # noqa: BLE001
            failed.append({"itemIds": link_ids, "reason": f"bulk_link: {exc}"})

    if reject_ids:
        try:
            resp = client.bulk_reject(reject_ids)
            applied.extend(resp.get("applied", reject_ids))
            failed.extend(resp.get("failed", []))
        except Exception as exc:  # noqa: BLE001
            failed.append({"itemIds": reject_ids, "reason": f"bulk_reject: {exc}"})

    log = {
        "applied": applied,
        "failed": failed,
        "pending_review": pending_review,
    }
    _write_json(session_dir / "execution_log.json", log)
    return log


def apply_review(
    client: Client,
    session_dir: Path,
    decisions: list[dict],
) -> dict:
    """Apply user-confirmed decisions from the review report.

    Each decision: {
        "item_id": str,
        "action": "link"|"reject",
        "links_per_node"?: {nodeId: {"factSheetId": str}}  # required for link
    }
    """
    link_ids: list[str] = []
    reject_ids: list[str] = []
    applied: list[str] = []
    failed: list[dict] = []

    for d in decisions:
        if d["action"] == "link":
            try:
                client.set_link_selection(
                    d["item_id"], links_per_node=d.get("links_per_node", {})
                )
                link_ids.append(d["item_id"])
            except Exception as exc:  # noqa: BLE001
                failed.append({"itemId": d["item_id"], "reason": str(exc)})
        elif d["action"] == "reject":
            reject_ids.append(d["item_id"])

    if link_ids:
        try:
            resp = client.bulk_link(link_ids)
            applied.extend(resp.get("applied", link_ids))
            failed.extend(resp.get("failed", []))
        except Exception as exc:  # noqa: BLE001
            failed.append({"itemIds": link_ids, "reason": f"bulk_link: {exc}"})

    if reject_ids:
        try:
            resp = client.bulk_reject(reject_ids)
            applied.extend(resp.get("applied", reject_ids))
            failed.extend(resp.get("failed", []))
        except Exception as exc:  # noqa: BLE001
            failed.append({"itemIds": reject_ids, "reason": f"bulk_reject: {exc}"})

    log_path = session_dir / "execution_log.json"
    existing = _read_json(log_path) if log_path.exists() else {
        "applied": [], "failed": [], "pending_review": []
    }
    existing["applied"] = sorted(set(existing.get("applied", [])) | set(applied))
    existing["failed"] = existing.get("failed", []) + failed
    processed_ids = {d["item_id"] for d in decisions}
    existing["pending_review"] = [
        i for i in existing.get("pending_review", []) if i not in processed_ids
    ]
    _write_json(log_path, existing)
    return existing
