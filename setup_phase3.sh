#!/bin/bash
set -e
echo "🚀 NEXORA Phase 3 — Dynamic Autonomous Runtime..."
[ -d "apps" ] || { echo "❌ Run from ROOT"; exit 1; }

# ================= MODELS (v3) =================
cat << 'EOF' > packages/core/models.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal
from enum import Enum
from datetime import datetime, timezone
import uuid

def utcnow():
    return datetime.now(timezone.utc)

class ExecutionMode(str, Enum):
    LIVE = "LIVE"
    MOCK = "MOCK"
    REPLAY = "REPLAY"
    SIMULATION = "SIMULATION"

class MissionState(str, Enum):
    CREATED = "CREATED"
    INTERPRETING = "INTERPRETING"
    PLANNING = "PLANNING"
    CRITICIZING = "CRITICIZING"
    EXECUTING = "EXECUTING"
    BLOCKED = "BLOCKED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"

class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

class ApprovalRequirement(str, Enum):
    NONE = "NONE"
    ALWAYS = "ALWAYS"

class Capability(BaseModel):
    capability_id: str
    name: str
    description: str
    provider: str
    required_api: str
    risk_level: RiskLevel
    estimated_cost_usd: float
    estimated_latency_ms: int
    reversible: bool
    approval_requirement: ApprovalRequirement
    execution_mode_support: List[ExecutionMode] = [ExecutionMode.LIVE, ExecutionMode.MOCK]

class MissionIntent(BaseModel):
    objective: str
    entities: List[str] = []
    constraints: List[str] = []
    success_criteria: List[str] = []
    ambiguity_score: float = 0.0
    confidence: float = 1.0

class MissionConstitution(BaseModel):
    mission_id: str
    budget_usd: float = 1.0
    deadline: Optional[datetime] = None
    forbidden_actions: List[str] = []
    allowed_capabilities: List[str] = []
    created_at: datetime = Field(default_factory=utcnow)

class NodeCondition(BaseModel):
    """Declarative, deterministic branch condition (ADR-034)."""
    source_capability: str
    path: str = "search_results"
    op: Literal["min_count", "any_contains"]
    field: Optional[str] = None
    value: Any = None

class MissionNode(BaseModel):
    node_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    capability_id: str
    inputs: Dict[str, Any] = {}
    outputs: Dict[str, Any] = {}
    depends_on: List[str] = []
    condition: Optional[NodeCondition] = None
    status: Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "SKIPPED", "WAITING_APPROVAL"] = "PENDING"
    approved: bool = False
    retries: int = 0
    rationale_summary: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class Artifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mission_id: str
    node_id: str
    type: str
    provider: str
    resource_id: str
    uri: str
    created_at: datetime = Field(default_factory=utcnow)

class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mission_id: str
    claim: str
    sources: List[str] = []
    derivation_path: List[str] = []
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=utcnow)

class ActionReceipt(BaseModel):
    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mission_id: str
    node_id: str
    action: str
    reason: str                      # safe rationale summary — NEVER raw CoT
    agent_id: str
    capability_id: str
    policy_decision: Literal["ALLOW", "BLOCK", "REQUIRE_APPROVAL"]
    model_tier: str
    cost_usd: float = 0.0
    output_artifact_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=utcnow)
    execution_mode: ExecutionMode

class VerificationResult(BaseModel):
    mission_id: str
    objective_completion: bool
    artifact_existence: bool
    evidence_coverage: float
    overall_status: Literal["PASS", "FAIL"]
    failure_reasons: List[str] = []

class MissionHealth(BaseModel):
    mission_id: str
    completion_percentage: float = 0.0
    evidence_coverage: float = 0.0
    policy_risk_score: float = 0.0
    budget_consumed_usd: float = 0.0
    budget_remaining_usd: float = 0.0
    blocked_objectives: List[str] = []
    failed_nodes: List[str] = []
    retry_count: int = 0
    current_execution_state: MissionState = MissionState.CREATED
    replan_count: int = 0

class Mission(BaseModel):
    mission_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str
    intent: Optional[MissionIntent] = None
    constitution: Optional[MissionConstitution] = None
    state: MissionState = MissionState.CREATED
    nodes: List[MissionNode] = []
    artifacts: List[Artifact] = []
    evidence: List[Evidence] = []
    receipts: List[ActionReceipt] = []
    verification: Optional[VerificationResult] = None
    health: Optional[MissionHealth] = None
    execution_mode: ExecutionMode = ExecutionMode.MOCK
    created_at: datetime = Field(default_factory=utcnow)
EOF

# ================= REPOSITORY (v3: Firestore behind Protocol) =================
cat << 'EOF' > apps/api/nexora/core/repository.py
import os
from typing import Dict, Optional, Protocol
from packages.core.models import Mission

class MissionRepository(Protocol):
    async def save(self, mission: Mission) -> None: ...
    async def get(self, mission_id: str) -> Optional[Mission]: ...

class InMemoryMissionRepository:
    def __init__(self):
        self._store: Dict[str, Mission] = {}

    async def save(self, mission: Mission) -> None:
        self._store[mission.mission_id] = mission

    async def get(self, mission_id: str) -> Optional[Mission]:
        return self._store.get(mission_id)

class FirestoreMissionRepository:
    """Durable state. Honors FIRESTORE_EMULATOR_HOST for zero-cost local runs (ADR-035)."""
    def __init__(self, project_id: str):
        self.project_id = project_id
        self._client = None

    def client(self):
        if self._client is None:
            from google.cloud.firestore import AsyncClient  # lazy
            self._client = AsyncClient(project=self.project_id)
        return self._client

    async def save(self, mission: Mission) -> None:
        await self.client().collection("missions").document(mission.mission_id).set(
            mission.model_dump(mode="json"))

    async def get(self, mission_id: str) -> Optional[Mission]:
        snap = await self.client().collection("missions").document(mission_id).get()
        if not snap.exists:
            return None
        return Mission.model_validate(snap.to_dict())

def build_repository() -> MissionRepository:
    if os.getenv("NEXORA_REPO") == "firestore":
        return FirestoreMissionRepository(os.getenv("GCP_PROJECT_ID", "nexora-dev"))
    return InMemoryMissionRepository()
EOF

# ================= EVENT BUS (v3: WS fan-out) =================
cat << 'EOF' > apps/api/nexora/core/event_bus.py
import asyncio
import logging
from collections import defaultdict
from typing import Dict, List, Protocol
from packages.core.models import utcnow

logger = logging.getLogger("nexora.events")

class EventBus(Protocol):
    async def publish(self, event_type: str, payload: Dict) -> None: ...

class LocalEventBus:
    def __init__(self):
        self._events: Dict[str, List[Dict]] = defaultdict(list)
        self._subscribers: List[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    async def publish(self, event_type: str, payload: Dict) -> None:
        record = {"event_type": event_type, "payload": payload, "timestamp": utcnow().isoformat()}
        self._events[payload.get("mission_id", "-")].append(record)
        for q in list(self._subscribers):
            q.put_nowait(record)
        logger.info("[EVENT] %s %s", event_type, payload)

    def history(self, mission_id: str) -> List[Dict]:
        return self._events.get(mission_id, [])

class PubSubEventBus:
    def __init__(self, project_id: str, topic: str):
        self.project_id = project_id
        self.topic = topic

    async def publish(self, event_type: str, payload: Dict) -> None:
        import json
        from google.cloud import pubsub_v1  # lazy: cloud image only
        publisher = pubsub_v1.PublisherClient()
        publisher.publish(publisher.topic_path(self.project_id, self.topic),
                          json.dumps({"event_type": event_type, "payload": payload}).encode())
EOF

# ================= MOCK PROVIDER (v3: failure injection) =================
cat << 'EOF' > apps/api/nexora/providers/mock_workspace.py
import asyncio
import uuid
from typing import Dict, List
from packages.core.models import Artifact

class MockWorkspaceProvider:
    """Deterministic, seeded, zero-external-call provider. Supports failure injection."""
    def __init__(self):
        self._docs, self._sheets, self._events, self._sent = {}, {}, {}, {}
        self._emails = {
            "msg_1": {"id": "msg_1", "subject": "URGENT: Checkout Down", "snippet": "Customers cannot pay.",
                      "body": "Checkout API returning 500. Severe impact."},
        }
        self._files = {"file_1": {"id": "file_1", "name": "SLA_Acme.pdf", "type": "pdf",
                                  "content": "SLA requires 1h response."}}
        self._active = 0
        self.max_concurrency = 0
        self.fail_caps: Dict[str, int] = {}   # capability -> remaining injected failures

    async def _enter(self, cap: str):
        if self.fail_caps.get(cap, 0) > 0:
            self.fail_caps[cap] -= 1
            raise RuntimeError(f"injected failure for {cap}")
        self._active += 1
        self.max_concurrency = max(self.max_concurrency, self._active)
        await asyncio.sleep(0.05)
        self._active -= 1

    async def create_document(self, mission_id, node_id, title, content) -> Artifact:
        await self._enter("docs.create")
        aid = str(uuid.uuid4())
        self._docs[aid] = {"title": title, "content": content}
        return Artifact(artifact_id=aid, mission_id=mission_id, node_id=node_id, type="DOC",
                        provider="mock", resource_id=aid, uri=f"mock://docs/{aid}")

    async def search_emails(self, query, max_results) -> List[Dict]:
        await self._enter("gmail.search")
        return [{"id": m["id"], "subject": m["subject"], "snippet": m["snippet"]}
                for m in list(self._emails.values())[:max_results]]

    async def read_email(self, message_id) -> Dict:
        await self._enter("gmail.read")
        return self._emails.get(message_id, {})

    async def send_email(self, to, subject, body) -> Artifact:
        await self._enter("gmail.send")
        aid = str(uuid.uuid4())
        self._sent[aid] = {"to": to, "subject": subject}
        return Artifact(artifact_id=aid, mission_id="-", node_id="-", type="EMAIL",
                        provider="mock", resource_id=aid, uri=f"mock://sent/{aid}")

    async def search_files(self, query) -> List[Dict]:
        await self._enter("drive.search")
        return [{"id": f["id"], "name": f["name"], "type": f["type"]} for f in self._files.values()]

    async def create_sheet(self, mission_id, node_id, title, headers) -> Artifact:
        await self._enter("sheets.create")
        aid = str(uuid.uuid4())
        self._sheets[aid] = {"title": title, "headers": headers, "rows": []}
        return Artifact(artifact_id=aid, mission_id=mission_id, node_id=node_id, type="SHEET",
                        provider="mock", resource_id=aid, uri=f"mock://sheets/{aid}")

    async def create_event(self, mission_id, node_id, title, attendees) -> Artifact:
        await self._enter("calendar.create_event")
        aid = str(uuid.uuid4())
        self._events[aid] = {"title": title, "attendees": attendees, "meet_link": f"mock://meet/{aid}"}
        return Artifact(artifact_id=aid, mission_id=mission_id, node_id=node_id, type="EVENT",
                        provider="mock", resource_id=aid, uri=f"mock://calendar/{aid}")

    async def verify_artifact(self, artifact: Artifact) -> bool:
        store = {"DOC": self._docs, "SHEET": self._sheets, "EVENT": self._events, "EMAIL": self._sent}
        return artifact.resource_id in store.get(artifact.type, {})
EOF

# ================= COMPILER (v3: conditional branches) =================
cat << 'EOF' > apps/api/nexora/core/compiler.py
from typing import List, Optional, Tuple
from packages.core.models import MissionNode, MissionIntent, MissionConstitution, NodeCondition
from nexora.core.capability_network import CapabilityNetwork

KEYWORD_RULES: List[Tuple[Tuple[str, ...], str]] = [
    (("email", "gmail", "inbox"), "gmail.search"),
    (("drive", "file", "contract"), "drive.search"),
    (("sheet", "spreadsheet", "tracker", "budget"), "sheets.create"),
    (("meeting", "schedule", "sync", "calendar"), "calendar.create_event"),
    (("send",), "gmail.send"),
    (("report", "doc", "write", "brief"), "docs.create"),
]
RESEARCH_CAPS = {"gmail.search", "drive.search"}
SYNTHESIS_CAPS = {"docs.create", "calendar.create_event", "gmail.send"}

class WorkflowCompiler:
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    async def compile(self, goal: str, intent: MissionIntent, constitution: MissionConstitution) -> List[MissionNode]:
        text = goal.lower()
        selected: List[Tuple[str, str]] = []
        for terms, cap_id in KEYWORD_RULES:
            hit = next((t for t in terms if t in text), None)
            if hit and cap_id in constitution.allowed_capabilities and cap_id not in [c for c, _ in selected]:
                selected.append((cap_id, hit))

        # Conditional branches: research outcomes decide extra work (ADR-034)
        conditions: List[Tuple[str, NodeCondition, str]] = []
        if "war room" in text or "escalation" in text:
            if ("gmail.search", ) and "gmail.search" not in [c for c, _ in selected]:
                selected.append(("gmail.search", "escalation"))
            conditions.append(("calendar.create_event",
                               NodeCondition(source_capability="gmail.search", op="any_contains",
                                             field="subject", value="urgent"),
                               "War Room"))
        if "refund" in text:
            if "gmail.search" not in [c for c, _ in selected]:
                selected.append(("gmail.search", "refund"))
            conditions.append(("docs.create",
                               NodeCondition(source_capability="gmail.search", op="any_contains",
                                             field="subject", value="refund"),
                               "Refund Brief"))

        if not selected:
            selected.append(("docs.create", "fallback"))

        research_ids = [c for c, _ in selected if c in RESEARCH_CAPS]
        nodes: List[MissionNode] = []
        by_cap = {}
        for cap_id, term in selected:
            deps = research_ids if cap_id in SYNTHESIS_CAPS and cap_id not in RESEARCH_CAPS else []
            cap = self.network.get(cap_id)
            n = MissionNode(
                capability_id=cap_id,
                depends_on=[r for r in deps if r != cap_id],
                inputs=self._default_inputs(cap_id, intent, None),
                rationale_summary=f"Matched term '{term}' → capability {cap_id} ({cap.name}).",
            )
            by_cap.setdefault(cap_id, n)
            nodes.append(n)

        for cap_id, cond, title in conditions:
            cap = self.network.get(cap_id)
            src = by_cap.get(cond.source_capability)
            nodes.append(MissionNode(
                capability_id=cap_id,
                depends_on=[src.node_id] if src else [],
                condition=cond,
                inputs=self._default_inputs(cap_id, intent, title),
                rationale_summary=f"Conditional branch: {title} runs only if {cond.source_capability} output matches '{cond.value}'.",
            ))
        return nodes

    @staticmethod
    def _default_inputs(cap_id: str, intent: MissionIntent, title: Optional[str]) -> dict:
        if cap_id == "gmail.search":
            return {"query": intent.objective, "max_results": 5}
        if cap_id == "drive.search":
            return {"query": intent.objective}
        if cap_id == "sheets.create":
            return {"title": title or f"Tracker - {intent.objective}", "headers": ["Item", "Owner", "Status"]}
        if cap_id == "calendar.create_event":
            return {"title": title or f"Sync - {intent.objective}", "attendees": ["team@acme.dev"]}
        if cap_id == "gmail.send":
            return {"to": ["customer@acme.dev"], "subject": f"Update: {intent.objective}", "body": "Status update..."}
        return {"title": title or f"Report - {intent.objective}", "content": "Initial details..."}
EOF

# ================= HEALTH (v3: full 9 metrics) =================
cat << 'EOF' > apps/api/nexora/core/health.py
from packages.core.models import MissionHealth, Mission, RiskLevel
from nexora.core.capability_network import CapabilityNetwork

RISK_SCORE = {RiskLevel.LOW: 0.0, RiskLevel.MEDIUM: 0.3, RiskLevel.HIGH: 0.7}

class HealthCalculator:
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    def calculate(self, mission: Mission) -> MissionHealth:
        total = len(mission.nodes)
        done = sum(1 for n in mission.nodes if n.status in ("SUCCESS", "SKIPPED"))
        consumed = sum(r.cost_usd for r in mission.receipts)
        budget = mission.constitution.budget_usd if mission.constitution else 0.0
        risk = max([RISK_SCORE.get(self.network.get(r.capability_id).risk_level, 0.0)
                    for r in mission.receipts
                    if self.network.get(r.capability_id)], default=0.0)
        return MissionHealth(
            mission_id=mission.mission_id,
            completion_percentage=(done / total * 100) if total else 0.0,
            evidence_coverage=mission.verification.evidence_coverage if mission.verification else 0.0,
            policy_risk_score=min(1.0, risk),
            budget_consumed_usd=round(consumed, 6),
            budget_remaining_usd=round(budget - consumed, 6),
            blocked_objectives=[n.capability_id for n in mission.nodes if n.status in ("FAILED", "SKIPPED")],
            failed_nodes=[n.node_id for n in mission.nodes if n.status == "FAILED"],
            retry_count=sum(n.retries for n in mission.nodes),
            current_execution_state=mission.state,
            replan_count=0,
        )
EOF

# ================= SUPERVISOR (v3) =================
cat << 'EOF' > apps/api/nexora/agents/supervisor.py
from packages.core.models import MissionState, utcnow
from nexora.core.state_machine import MissionStateMachine
from nexora.core.health import HealthCalculator
from nexora.core.evidence import EvidenceGraph
from nexora.agents.verifier import VerificationAgent

TERMINAL = {"SUCCESS", "FAILED", "SKIPPED"}

class MissionSupervisor:
    def __init__(self, repo, bus, registry, network):
        self.repo = repo
        self.bus = bus
        self.registry = registry
        self.network = network
        self.health = HealthCalculator(network)

    def can_spend(self, mission, capability) -> bool:
        consumed = sum(r.cost_usd for r in mission.receipts)
        budget = mission.constitution.budget_usd if mission.constitution else 0.0
        return consumed + capability.estimated_cost_usd <= budget + 1e-9

    async def check_completion(self, mission_id: str):
        mission = await self.repo.get(mission_id)
        if not mission or mission.state not in (MissionState.EXECUTING, MissionState.BLOCKED):
            return

        if mission.constitution and mission.constitution.deadline and utcnow() > mission.constitution.deadline:
            mission.state = MissionStateMachine.transition(mission.state, MissionState.FAILED)
            mission.health = self.health.calculate(mission)
            await self.repo.save(mission)
            await self.bus.publish("MISSION.FAILED", {"mission_id": mission_id, "reason": "deadline_exceeded"})
            return

        statuses = [n.status for n in mission.nodes]

        if any(s == "WAITING_APPROVAL" for s in statuses):
            if mission.state == MissionState.EXECUTING:
                mission.state = MissionStateMachine.transition(mission.state, MissionState.BLOCKED)
                await self.bus.publish("MISSION.BLOCKED", {"mission_id": mission_id, "reason": "awaiting_approval"})
        elif all(s in TERMINAL for s in statuses):
            mission.state = MissionStateMachine.transition(mission.state, MissionState.VERIFYING)
            mission.verification = await VerificationAgent(self.registry).verify(
                mission_id, mission.intent, mission.artifacts)

            eg = EvidenceGraph()
            for art in mission.artifacts:
                node = next((n for n in mission.nodes if n.node_id == art.node_id), None)
                mission.evidence.append(eg.generate_evidence(
                    mission_id, f"{art.type} artifact created and verified.", art, node.node_id if node else "-"))

            passed = mission.verification.overall_status == "PASS"
            final = MissionState.COMPLETED if passed else (
                MissionState.PARTIAL_SUCCESS if mission.artifacts else MissionState.FAILED)
            mission.state = MissionStateMachine.transition(mission.state, final)
            mission.health = self.health.calculate(mission)
            await self.bus.publish("MISSION.COMPLETED" if passed else "MISSION.FAILED",
                                   {"mission_id": mission_id, "status": final.value})
        else:
            mission.health = self.health.calculate(mission)

        await self.repo.save(mission)
EOF

# ================= RUNTIME (v3: conditions, retries, cascade, budget) =================
cat << 'EOF' > apps/api/nexora/core/runtime.py
import os
from packages.core.models import MissionState, utcnow, ActionReceipt, Mission
from nexora.core.state_machine import MissionStateMachine
from nexora.core.policy_engine import PolicyEngine
from nexora.core.task_dispatcher import LocalTaskDispatcher, CloudTasksDispatcher
from nexora.agents.node_executor import NodeExecutor, ApprovalRequiredError
from nexora.agents.supervisor import MissionSupervisor

MAX_RETRIES = 2
SATISFIED = {"SUCCESS", "SKIPPED"}

class MissionRuntime:
    def __init__(self, repo, network, registry, bus):
        self.repo = repo
        self.network = network
        self.registry = registry
        self.bus = bus
        self.executor = NodeExecutor(PolicyEngine(), network, registry)
        self.supervisor = MissionSupervisor(repo, bus, registry, network)
        if os.getenv("NEXORA_DISPATCHER") == "cloud":
            self.dispatcher = CloudTasksDispatcher(
                os.getenv("GCP_PROJECT_ID", ""), os.getenv("GCP_REGION", "us-central1"),
                "nexora-workers", os.getenv("NEXORA_WORKER_URL", "http://localhost:8000"))
        else:
            self.dispatcher = LocalTaskDispatcher(self.process_node)

    async def dispatch(self, mission_id: str, node_id: str):
        await self.dispatcher.dispatch_node(mission_id, node_id)

    # ---- conditional branching (ADR-034) ----
    def _eval_condition(self, mission: Mission, node) -> bool:
        cond = node.condition
        src = next((n for n in mission.nodes if n.capability_id == cond.source_capability), None)
        if not src:
            return False
        data = src.outputs.get(cond.path, [])
        if cond.op == "min_count":
            return len(data) >= cond.value
        if cond.op == "any_contains":
            return any(str(cond.value).lower() in str(item.get(cond.field, "")).lower()
                       for item in data if isinstance(item, dict))
        return False

    def _cascade_skip(self, mission: Mission, failed_id: str):
        changed = True
        while changed:
            changed = False
            for n in mission.nodes:
                if n.status == "PENDING" and any(d == failed_id or
                        (self._node(mission, d) and self._node(mission, d).status == "FAILED")
                        for d in n.depends_on):
                    n.status = "SKIPPED"
                    n.completed_at = utcnow()
                    n.rationale_summary += " [skipped: dependency failed]"
                    changed = True

    @staticmethod
    def _node(mission, node_id):
        return next((n for n in mission.nodes if n.node_id == node_id), None)

    async def process_node(self, mission_id: str, node_id: str):
        mission = await self.repo.get(mission_id)
        if not mission:
            return
        node = self._node(mission, node_id)
        if node is None or node.status != "PENDING":
            return

        # Conditional branch gate
        if node.condition and not self._eval_condition(mission, node):
            node.status = "SKIPPED"
            node.completed_at = utcnow()
            node.rationale_summary += " [condition not met]"
            await self.repo.save(mission)
            await self.bus.publish("MISSION.NODE.SKIPPED", {"mission_id": mission_id, "node_id": node_id})
            for dep in mission.nodes:
                if node_id in dep.depends_on and dep.status == "PENDING" and \
                   all(self._node(mission, d).status in SATISFIED for d in dep.depends_on):
                    await self.dispatch(mission_id, dep.node_id)
            await self.supervisor.check_completion(mission_id)
            return

        node.status = "RUNNING"
        node.started_at = utcnow()
        await self.repo.save(mission)
        await self.bus.publish("MISSION.NODE.STARTED", {"mission_id": mission_id, "node_id": node_id})

        cap = self.network.get(node.capability_id)
        if cap and not self.supervisor.can_spend(mission, cap):
            node.status = "FAILED"
            node.completed_at = utcnow()
            node.rationale_summary += " [budget exceeded — circuit breaker]"
            await self.repo.save(mission)
            await self.bus.publish("MISSION.NODE.FAILED", {"mission_id": mission_id, "node_id": node_id, "error": "budget"})
            self._cascade_skip(mission, node_id)
            await self.repo.save(mission)
            await self.supervisor.check_completion(mission_id)
            return

        try:
            artifact, receipt = await self.executor.execute(mission_id, node, mission.constitution, mission.execution_mode)
            node.status = "SUCCESS"
            node.completed_at = utcnow()
            if artifact:
                artifact.mission_id = mission_id
                artifact.node_id = node_id
                mission.artifacts.append(artifact)
            mission.receipts.append(receipt)
            await self.bus.publish("MISSION.NODE.COMPLETED", {"mission_id": mission_id, "node_id": node_id, "capability": node.capability_id})
        except ApprovalRequiredError:
            node.status = "WAITING_APPROVAL"
            mission.receipts.append(ActionReceipt(
                mission_id=mission_id, node_id=node_id, action=node.capability_id,
                reason=node.rationale_summary, agent_id="worker", capability_id=node.capability_id,
                policy_decision="REQUIRE_APPROVAL", model_tier="T1", cost_usd=0.0,
                execution_mode=mission.execution_mode))
            await self.bus.publish("MISSION.APPROVAL_REQUESTED", {"mission_id": mission_id, "node_id": node_id})
        except PermissionError as e:
            node.status = "FAILED"
            node.completed_at = utcnow()
            await self.bus.publish("MISSION.NODE.FAILED", {"mission_id": mission_id, "node_id": node_id, "error": str(e)})
            self._cascade_skip(mission, node_id)
        except Exception as e:
            if node.retries < MAX_RETRIES:
                node.retries += 1
                node.status = "PENDING"
                await self.repo.save(mission)
                await self.bus.publish("MISSION.NODE.RETRY", {"mission_id": mission_id, "node_id": node_id, "retry": node.retries})
                await self.dispatch(mission_id, node_id)
                return
            node.status = "FAILED"
            node.completed_at = utcnow()
            await self.bus.publish("MISSION.NODE.FAILED", {"mission_id": mission_id, "node_id": node_id, "error": str(e)})
            self._cascade_skip(mission, node_id)

        await self.repo.save(mission)

        if node.status in SATISFIED:
            for dep in mission.nodes:
                if node_id in dep.depends_on and dep.status == "PENDING":
                    if all(self._node(mission, d).status in SATISFIED for d in dep.depends_on):
                        await self.dispatch(mission_id, dep.node_id)

        await self.supervisor.check_completion(mission_id)
EOF

# ================= MAIN (v3: repo factory + WebSocket) =================
cat << 'EOF' > apps/api/nexora/main.py
import os
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from packages.core.models import Mission, MissionState, ExecutionMode
from nexora.core.repository import build_repository
from nexora.core.state_machine import MissionStateMachine, InvalidStateTransitionError
from nexora.core.capability_network import CapabilityNetwork
from nexora.core.constitution_builder import ConstitutionBuilder
from nexora.core.compiler import WorkflowCompiler
from nexora.core.event_bus import LocalEventBus
from nexora.core.runtime import MissionRuntime
from nexora.core.credential_store import LocalCredentialStore
from nexora.agents.interpreter import MissionInterpreter
from nexora.agents.critic import PlanCritic
from nexora.core.model_router import ModelRouter
from nexora.providers.mock_workspace import MockWorkspaceProvider
from nexora.providers.protocols import ProviderRegistry

app = FastAPI(title="NEXORA API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

repo = build_repository()
network = CapabilityNetwork()
router = ModelRouter()
bus = LocalEventBus()

def build_registry(mode: ExecutionMode) -> ProviderRegistry:
    if mode == ExecutionMode.LIVE:
        from nexora.providers.live_workspace import LiveWorkspaceProvider
        return ProviderRegistry(LiveWorkspaceProvider(LocalCredentialStore()))
    return ProviderRegistry(MockWorkspaceProvider())

registry = build_registry(ExecutionMode(os.getenv("EXECUTION_MODE", "MOCK")))
runtime = MissionRuntime(repo, network, registry, bus)

class GoalRequest(BaseModel):
    goal: str
    execution_mode: ExecutionMode = ExecutionMode.MOCK

class NodeRef(BaseModel):
    mission_id: str
    node_id: str

class ApprovalRequest(BaseModel):
    approved: bool

async def _get_or_404(mission_id: str) -> Mission:
    mission = await repo.get(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission

@app.post("/api/v1/missions", response_model=Mission)
async def create_mission(req: GoalRequest):
    mission = Mission(goal=req.goal, execution_mode=req.execution_mode)
    await repo.save(mission)
    try:
        mission.state = MissionStateMachine.transition(mission.state, MissionState.INTERPRETING)
        mission.intent = await MissionInterpreter(router).interpret(req.goal)

        mission.state = MissionStateMachine.transition(mission.state, MissionState.PLANNING)
        mission.constitution = ConstitutionBuilder(network).build(mission.mission_id, mission.intent)
        mission.nodes = await WorkflowCompiler(network).compile(mission.goal, mission.intent, mission.constitution)

        mission.state = MissionStateMachine.transition(mission.state, MissionState.CRITICIZING)
        critique = await PlanCritic(network).critique(mission.nodes, mission.constitution)
        if not critique["approved"]:
            mission.state = MissionState.FAILED
            await repo.save(mission)
            raise HTTPException(status_code=400, detail=f"Plan rejected: {critique['issues']}")

        mission.state = MissionStateMachine.transition(mission.state, MissionState.EXECUTING)
        await repo.save(mission)
        await bus.publish("MISSION.CREATED", {"mission_id": mission.mission_id, "goal": req.goal})

        for node in mission.nodes:
            if not node.depends_on:
                await runtime.dispatch(mission.mission_id, node.node_id)
        return mission
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/internal/execute_node")
async def execute_node_internal(ref: NodeRef):
    await runtime.process_node(ref.mission_id, ref.node_id)
    return {"status": "dispatched"}

@app.post("/api/v1/missions/{mission_id}/approvals/{node_id}")
async def decide_approval(mission_id: str, node_id: str, body: ApprovalRequest):
    mission = await _get_or_404(mission_id)
    node = next((n for n in mission.nodes if n.node_id == node_id), None)
    if node is None or node.status != "WAITING_APPROVAL":
        raise HTTPException(status_code=409, detail="Node not awaiting approval")
    if body.approved:
        node.approved = True
        node.status = "PENDING"
        if mission.state == MissionState.BLOCKED:
            mission.state = MissionStateMachine.transition(mission.state, MissionState.EXECUTING)
        await repo.save(mission)
        await runtime.dispatch(mission_id, node_id)
    else:
        node.status = "FAILED"
        await repo.save(mission)
        await runtime.supervisor.check_completion(mission_id)
    return {"node_id": node_id, "approved": body.approved}

@app.websocket("/api/v1/missions/{mission_id}/ws")
async def mission_ws(websocket: WebSocket, mission_id: str):
    await websocket.accept()
    q = bus.subscribe()
    try:
        mission = await repo.get(mission_id)
        if mission:
            await websocket.send_json({"type": "snapshot", "mission": mission.model_dump(mode="json")})
        while True:
            rec = await q.get()
            if rec["payload"].get("mission_id") == mission_id:
                await websocket.send_json({"type": "event", **rec})
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)

@app.get("/api/v1/missions/{mission_id}", response_model=Mission)
async def get_mission(mission_id: str):
    return await _get_or_404(mission_id)

@app.get("/api/v1/missions/{mission_id}/events")
async def get_events(mission_id: str):
    await _get_or_404(mission_id)
    return bus.history(mission_id)

@app.get("/api/v1/missions/{mission_id}/health")
async def get_health(mission_id: str):
    return (await _get_or_404(mission_id)).health

@app.get("/api/v1/missions/{mission_id}/evidence")
async def get_evidence(mission_id: str):
    return (await _get_or_404(mission_id)).evidence

@app.get("/api/v1/missions/{mission_id}/receipts")
async def get_receipts(mission_id: str):
    return (await _get_or_404(mission_id)).receipts

@app.get("/api/v1/missions/{mission_id}/verification")
async def get_verification(mission_id: str):
    return (await _get_or_404(mission_id)).verification

@app.get("/api/v1/missions/{mission_id}/constitution")
async def get_constitution(mission_id: str):
    return (await _get_or_404(mission_id)).constitution

@app.get("/api/v1/capabilities")
async def list_capabilities():
    return [network.get(cid) for cid in network.ids()]
EOF

cat << 'EOF' > apps/api/requirements.txt
fastapi
uvicorn[standard]
pydantic
pytest
httpx
python-dotenv
google-api-python-client
google-cloud-firestore
EOF

# ================= TESTS (Phase 3) =================
cat << 'EOF' > apps/api/tests/test_phase3.py
import asyncio
import time
from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient
from nexora.main import app, runtime, repo, bus
from packages.core.models import Mission, MissionConstitution, MissionNode, MissionState, ExecutionMode

def run(c): return asyncio.run(c)

async def post_and_wait(ac, goal, timeout=10.0):
    r = await ac.post("/api/v1/missions", json={"goal": goal, "execution_mode": "MOCK"})
    assert r.status_code == 200
    mid = r.json()["mission_id"]
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if d["state"] in ("COMPLETED", "FAILED", "PARTIAL_SUCCESS"):
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError("mission did not finish")

def test_conditional_branch_true_and_false():
    async def inner():
        runtime.registry.provider.fail_caps = {}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac,
                "Investigate: search emails and drive files, write the incident report, "
                "schedule a war room if urgent emails exist, and prepare a refund brief if refund requests exist.")
            caps = {n["capability_id"]: n for n in d["nodes"]}
            war_rooms = [n for n in d["nodes"] if n["capability_id"] == "calendar.create_event" and n.get("condition")]
            refunds = [n for n in d["nodes"] if n["capability_id"] == "docs.create" and n.get("condition")]
            assert war_rooms and war_rooms[0]["status"] == "SUCCESS"     # 'URGENT' matches seed
            assert refunds and refunds[0]["status"] == "SKIPPED"         # no 'refund' in seed
            assert d["state"] == "COMPLETED"
            assert any(n.get("condition") for n in d["nodes"])
    run(inner())

def test_failure_cascades_to_dependents():
    async def inner():
        runtime.registry.provider.fail_caps = {"gmail.search": 99}
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                d = await post_and_wait(ac, "Search emails and drive files then write the incident report.")
                docs = [n for n in d["nodes"] if n["capability_id"] == "docs.create"]
                assert docs[0]["status"] == "SKIPPED"   # dependency failed -> skipped
                assert d["state"] in ("FAILED", "PARTIAL_SUCCESS")
                assert d["health"]["failed_nodes"], "health must list failed nodes"
        finally:
            runtime.registry.provider.fail_caps = {}
    run(inner())

def test_retry_then_success():
    async def inner():
        runtime.registry.provider.fail_caps = {"sheets.create": 1}
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                d = await post_and_wait(ac, "Create a tracker sheet.")
                node = next(n for n in d["nodes"] if n["capability_id"] == "sheets.create")
                assert node["status"] == "SUCCESS"
                assert node["retries"] == 1
                assert d["health"]["retry_count"] >= 1
        finally:
            runtime.registry.provider.fail_caps = {}
    run(inner())

def test_budget_circuit_breaker():
    async def inner():
        m = Mission(goal="x", execution_mode=ExecutionMode.MOCK)
        m.constitution = MissionConstitution(mission_id=m.mission_id, budget_usd=0.0,
                                             allowed_capabilities=["docs.create"])
        node = MissionNode(capability_id="docs.create", inputs={"title": "t", "content": "c"})
        m.nodes.append(node)
        m.state = MissionState.EXECUTING
        await repo.save(m)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/internal/execute_node", json={"mission_id": m.mission_id, "node_id": node.node_id})
        stored = await repo.get(m.mission_id)
        assert stored.nodes[0].status == "FAILED"
        assert stored.state == MissionState.FAILED
        assert stored.health.budget_remaining_usd <= 0.0
    run(inner())

def test_event_bus_fanout():
    async def inner():
        q = bus.subscribe()
        await bus.publish("TEST.EVENT", {"mission_id": "mX"})
        rec = q.get_nowait()
        assert rec["event_type"] == "TEST.EVENT"
        bus.unsubscribe(q)
    run(inner())

def test_websocket_snapshot():
    with TestClient(app) as client:
        r = client.post("/api/v1/missions", json={"goal": "Write the incident report.", "execution_mode": "MOCK"})
        mid = r.json()["mission_id"]
        with client.websocket_connect(f"/api/v1/missions/{mid}/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            assert msg["mission"]["mission_id"] == mid
EOF

# ================= FRONTEND (v3: WS live updates + full health) =================
cat << 'EOF' > apps/web/src/app/page.tsx
"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

const API = "http://localhost:8000";

export default function Home() {
  const [goal, setGoal] = useState(
    "Investigate: search emails and drive files, write the incident report, schedule a war room if urgent emails exist, and prepare a refund brief if refund requests exist."
  );
  const [mission, setMission] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsOk = useRef(false);

  const refresh = async (mid: string) => {
    const r = await fetch(`${API}/api/v1/missions/${mid}`);
    if (r.ok) setMission(await r.json());
  };

  // WebSocket live updates, polling fallback (ADR-036)
  useEffect(() => {
    if (!mission) return;
    const mid = mission.mission_id;
    let poll: any = null;
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`ws://localhost:8000/api/v1/missions/${mid}/ws`);
      ws.onmessage = () => refresh(mid);
      ws.onopen = () => { wsOk.current = true; };
      ws.onerror = () => { poll = setInterval(() => refresh(mid), 1500); };
    } catch {
      poll = setInterval(() => refresh(mid), 1500);
    }
    return () => { ws?.close(); if (poll) clearInterval(poll); };
  }, [mission?.mission_id]);

  useEffect(() => {
    if (!mission || (mission.state !== "COMPLETED" && mission.state !== "FAILED" && mission.state !== "PARTIAL_SUCCESS")) return;
    fetch(`${API}/api/v1/missions/${mission.mission_id}/events`).then((r) => (r.ok ? r.json() : [])).then(setEvents);
  }, [mission?.state]);

  const launch = async () => {
    setLoading(true); setError(null); setMission(null); setEvents([]);
    try {
      const r = await fetch(`${API}/api/v1/missions`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal, execution_mode: "MOCK" }),
      });
      if (!r.ok) throw new Error(`API error ${r.status}`);
      setMission(await r.json());
    } catch (e) { setError(String(e)); } finally { setLoading(false); }
  };

  const decide = async (nodeId: string, approved: boolean) => {
    await fetch(`${API}/api/v1/missions/${mission.mission_id}/approvals/${nodeId}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    });
    refresh(mission.mission_id);
  };

  const h = mission?.health;

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-8 font-mono">
      <header className="mb-6">
        <h1 className="text-2xl font-bold tracking-widest text-emerald-400">NEXORA</h1>
        <p className="text-sm text-zinc-400">Autonomous execution layer for the Google ecosystem</p>
      </header>

      <section className="mb-6 flex gap-2">
        <input value={goal} onChange={(e) => setGoal(e.target.value)}
          className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm" />
        <button onClick={launch} disabled={loading}
          className="rounded bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 disabled:opacity-50">
          {loading ? "Launching…" : "Launch Mission"}
        </button>
      </section>

      {error && <p className="mb-4 text-red-400">Error: {error}</p>}

      {mission && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <Panel title="MISSION">
            <KV k="State" v={mission.state} highlight />
            <KV k="Mode" v={mission.execution_mode} />
            <KV k="Objective" v={mission.intent?.objective ?? "—"} />
          </Panel>

          <Panel title="PLAN (DAG)">
            {mission.nodes.map((n: any) => (
              <div key={n.node_id} className="mb-2 text-xs">
                <span className="text-emerald-400">{n.capability_id}</span>{" "}
                <span className={
                  n.status === "SUCCESS" ? "text-zinc-400"
                  : n.status === "WAITING_APPROVAL" ? "text-amber-400"
                  : n.status === "SKIPPED" ? "text-zinc-600 line-through"
                  : n.status === "FAILED" ? "text-red-400" : "text-sky-400"}>
                  [{n.status}{n.retries ? ` retry×${n.retries}` : ""}]
                </span>
                {n.condition && <span className="text-violet-400">  conditional</span>}
              </div>
            ))}
            {mission.nodes.filter((n: any) => n.status === "WAITING_APPROVAL").map((n: any) => (
              <div key={`ap-${n.node_id}`} className="mt-2 flex items-center gap-2 text-xs">
                <span className="text-amber-400">{n.capability_id} requires approval</span>
                <button onClick={() => decide(n.node_id, true)} className="rounded bg-emerald-600 px-2 py-1">Approve</button>
                <button onClick={() => decide(n.node_id, false)} className="rounded bg-red-700 px-2 py-1">Reject</button>
              </div>
            ))}
          </Panel>

          <Panel title="MISSION HEALTH (9 metrics)">
            <KV k="Completion" v={`${h?.completion_percentage ?? 0}%`} />
            <KV k="Evidence coverage" v={`${h?.evidence_coverage ?? 0} (${mission.evidence?.length ?? 0} claims)`} />
            <KV k="Policy risk" v={String(h?.policy_risk_score ?? 0)} />
            <KV k="Budget" v={`$${h?.budget_consumed_usd ?? 0} / $${((h?.budget_consumed_usd ?? 0) + (h?.budget_remaining_usd ?? 0)).toFixed(4)}`} />
            <KV k="Remaining" v={`$${h?.budget_remaining_usd ?? 0}`} />
            <KV k="Blocked" v={(h?.blocked_objectives ?? []).join(", ") || "none"} />
            <KV k="Failed nodes" v={String((h?.failed_nodes ?? []).length)} />
            <KV k="Retries" v={String(h?.retry_count ?? 0)} />
            <KV k="Replans" v={String(h?.replan_count ?? 0)} />
          </Panel>

          <Panel title="ARTIFACTS">
            {mission.artifacts.map((a: any) => (
              <p key={a.artifact_id} className="mb-1 text-xs text-zinc-300">
                {a.type} · {a.provider} · <span className="text-zinc-500">{a.uri}</span>
              </p>
            ))}
          </Panel>

          <Panel title="ACTION RECEIPTS">
            {mission.receipts.map((r: any) => (
              <p key={r.receipt_id} className="mb-1 text-xs text-zinc-300">
                {r.capability_id} · {r.policy_decision} · {r.cost_usd} USD
              </p>
            ))}
          </Panel>

          <Panel title="EVENT BUS (live)">
            {events.slice(-10).map((e, i) => (
              <p key={i} className="mb-1 text-xs text-zinc-400">{e.event_type}</p>
            ))}
          </Panel>
        </div>
      )}
    </main>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded border border-zinc-800 bg-zinc-900/60 p-4">
      <h2 className="mb-3 text-xs font-bold tracking-widest text-zinc-400">{title}</h2>
      {children}
    </section>
  );
}

function KV({ k, v, highlight }: { k: string; v: string; highlight?: boolean }) {
  return (
    <p className="mb-1 text-xs">
      <span className="text-zinc-500">{k}: </span>
      <span className={highlight ? "text-emerald-400" : "text-zinc-200"}>{v}</span>
    </p>
  );
}
EOF

# ================= ADRs =================
cat << 'EOF' > docs/adr/ADR-034-declarative-conditions.md
# ADR-034: Declarative Conditional Branches
Status: Accepted. NodeCondition data is evaluated deterministically by the runtime; unmet conditions SKIPPED the node; failed dependencies cascade SKIPPED transitively.
EOF
cat << 'EOF' > docs/adr/ADR-035-durable-repository.md
# ADR-035: Durable Mission State
Status: Accepted. Repository Protocol with FirestoreMissionRepository honoring FIRESTORE_EMULATOR_HOST; NEXORA_REPO selects backend; browser closure never destroys state.
EOF
cat << 'EOF' > docs/adr/ADR-036-websocket-fanout.md
# ADR-036: Live UI via EventBus subscribers
Status: Accepted. WebSocket endpoint streams events from LocalEventBus; UI uses push with polling fallback.
EOF

echo "✅ Phase 3 generated. Install new dep + restart:"
echo "   apps/api/venv/bin/pip install -q google-cloud-firestore"
echo "   npm run dev:api   |   npm run test:api"
