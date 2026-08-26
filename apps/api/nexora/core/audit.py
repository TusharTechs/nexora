"""Append-only Audit Trail (ADR-039).

Records every security-relevant event: firewall detections, policy decisions,
approval gates, and node executions. Never stores raw chain-of-thought.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import uuid

from packages.core.models import utcnow


class AuditKind(str, Enum):
    FIREWALL_DETECT   = "FIREWALL_DETECT"
    POLICY_DECISION   = "POLICY_DECISION"
    APPROVAL_REQUEST  = "APPROVAL_REQUEST"
    APPROVAL_DECIDED  = "APPROVAL_DECIDED"
    NODE_EXECUTED     = "NODE_EXECUTED"
    NODE_FAILED       = "NODE_FAILED"
    NODE_SKIPPED      = "NODE_SKIPPED"
    BUDGET_BREAKER    = "BUDGET_BREAKER"
    ENVIRONMENT_CHANGE = "ENVIRONMENT_CHANGE"
    REPLAN             = "REPLAN"
    INTERVENTION       = "INTERVENTION"
    UNTRUSTED_INPUT   = "UNTRUSTED_INPUT"


@dataclass
class AuditEntry:
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    mission_id: str = ""
    node_id: Optional[str] = None
    kind: AuditKind = AuditKind.NODE_EXECUTED
    severity: str = "INFO"          # INFO | WARN | ALERT
    title: str = ""
    detail: str = ""                # safe, structured summary — never raw CoT
    metadata: Dict[str, Any] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=utcnow)


class AuditTrail:
    """In-memory in Phase 4; swap for Firestore in Phase 9."""

    def __init__(self):
        self._entries: Dict[str, List[AuditEntry]] = {}

    def record(self, entry: AuditEntry) -> AuditEntry:
        self._entries.setdefault(entry.mission_id or "-", []).append(entry)
        return entry

    def history(self, mission_id: str, limit: int = 100) -> List[AuditEntry]:
        entries = self._entries.get(mission_id, [])
        return list(reversed(entries[-limit:]))

    def counts(self, mission_id: str) -> Dict[str, int]:
        from collections import Counter
        c = Counter(e.kind.value for e in self._entries.get(mission_id, []))
        return dict(c)

    def clear(self):
        self._entries.clear()