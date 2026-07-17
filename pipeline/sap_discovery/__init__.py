"""pipeline.sap_discovery — Vía B for SAP Internal Discovery.

Package layout:
- client: REST calls to discovery-sap v1 + discovery-linking v2 (real API)
- matcher: pure heuristics that turn a DiscoveryItem into a MatchDecision
- orchestrator: discover_integration → process_inbox → apply_review
- report: HTML/JSON report renderer

Design: docs/superpowers/specs/2026-07-16-sap-internal-discovery-design.md
"""
from __future__ import annotations

from pipeline.sap_discovery.client import (
    Client,
    DiscoveryItem,
    IntegrationNotFoundError,
)
from pipeline.sap_discovery.matcher import (
    MatchDecision,
    decide,
)
from pipeline.sap_discovery.orchestrator import (
    apply_review,
    discover_integration,
    poll_status,
    process_inbox,
)
from pipeline.sap_discovery.report import build

__all__ = [
    "Client",
    "DiscoveryItem",
    "IntegrationNotFoundError",
    "MatchDecision",
    "apply_review",
    "build",
    "decide",
    "discover_integration",
    "poll_status",
    "process_inbox",
]


def make_create_factsheet_bridge():
    """Return a callable(payload_dict) -> {"id": str} that delegates to pipeline.write.

    Lazy factory so pipeline.write is not imported at package load time.

    Raises:
        AttributeError: if pipeline.write does not expose a public create_factsheet
            function. In that case, the orchestrator should be called with a
            different bridge (e.g. a stub in tests, or a wizard-side wrapper).
    """
    from pipeline import write as _write

    fn = getattr(_write, "create_factsheet", None)
    if fn is None:
        raise AttributeError(
            "pipeline.write.create_factsheet is not defined — "
            "provide a custom create_factsheet callable to orchestrator.process_inbox"
        )

    def _bridge(payload: dict) -> dict:
        fs = fn(
            type_=payload["type"],
            name=payload["name"],
            attributes={"product": payload.get("product")},
        )
        return {"id": fs["id"]}

    return _bridge


__all__ = __all__ + ["make_create_factsheet_bridge"]
