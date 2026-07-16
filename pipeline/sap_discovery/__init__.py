"""pipeline.sap_discovery — Vía B for SAP Internal Discovery.

Package layout:
- client: REST calls to discovery-sap-extension + discovery-linking v2
- matcher: pure heuristics that turn a DiscoveryItem into a MatchDecision
- orchestrator: two-phase flow (start_integration, process_inbox, apply_review)
- report: HTML/JSON report renderer

Design: docs/superpowers/specs/2026-07-16-sap-internal-discovery-design.md
"""
from __future__ import annotations

from pipeline.sap_discovery.client import (
    Client,
    DiscoveryItem,
)

# TODO: Import additional modules as they are implemented
# from pipeline.sap_discovery.matcher import (
#     MatchDecision,
#     decide,
# )
# from pipeline.sap_discovery.orchestrator import (
#     apply_review,
#     poll_status,
#     process_inbox,
#     start_integration,
# )
# from pipeline.sap_discovery.report import build

__all__ = [
    "Client",
    "DiscoveryItem",
    # "MatchDecision",
    # "apply_review",
    # "build",
    # "decide",
    # "poll_status",
    # "process_inbox",
    # "start_integration",
]
