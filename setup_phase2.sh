#!/bin/bash
set -e
echo "🚀 NEXORA Phase 2 — Workspace Core + Parallel Runtime..."
[ -d "apps" ] || { echo "❌ Run from ROOT"; exit 1; }

rm -f apps/api/nexora/agents/worker.py   # superseded by NodeExecutor

# ================= MODELS (v2) =================
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
    forbidden_actions: List[str] = []
    allowed_capabilities: List[str] = []
    created_at: datetime = Field(default_factory=utcnow)

class MissionNode(BaseModel):
    node_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    capability_id: str
    inputs: Dict[str, Any] = {}
    outputs: Dict[str, Any] = {}
    depends_on: List[str] = []
    status: Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "WAITING_APPROVAL"] = "PENDING"
    approved: bool = False
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
    current_execution_state: MissionState

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

# ================= STATE MACHINE (v2) =================
cat << 'EOF' > apps/api/nexora/core/state_machine.py
from packages.core.models import MissionState

VALID_TRANSITIONS = {
    MissionState.CREATED: [MissionState.INTERPRETING],
    MissionState.INTERPRETING: [MissionState.PLANNING, MissionState.FAILED],
    MissionState.PLANNING: [MissionState.CRITICIZING, MissionState.FAILED],
    MissionState.CRITICIZING: [MissionState.EXECUTING, MissionState.FAILED],
    MissionState.EXECUTING: [MissionState.VERIFYING, MissionState.BLOCKED, MissionState.FAILED],
    MissionState.BLOCKED: [MissionState.EXECUTING, MissionState.VERIFYING, MissionState.FAILED],
    MissionState.VERIFYING: [MissionState.COMPLETED, MissionState.PARTIAL_SUCCESS, MissionState.FAILED],
}

class InvalidStateTransitionError(Exception):
    pass

class MissionStateMachine:
    @staticmethod
    def transition(current: MissionState, next_state: MissionState) -> MissionState:
        if next_state not in VALID_TRANSITIONS.get(current, []):
            raise InvalidStateTransitionError(f"Invalid transition {current} -> {next_state}")
        return next_state
EOF

# ================= CAPABILITY NETWORK (v2) =================
cat << 'EOF' > apps/api/nexora/core/capability_network.py
from typing import Dict, List, Optional
from packages.core.models import Capability, RiskLevel, ApprovalRequirement, ExecutionMode

ALL_MODES = [ExecutionMode.LIVE, ExecutionMode.MOCK, ExecutionMode.REPLAY, ExecutionMode.SIMULATION]

class CapabilityNetwork:
    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._register_defaults()

    def _add(self, cid, name, api, risk, approval, cost, latency, reversible, desc):
        self.register(Capability(
            capability_id=cid, name=name, description=desc, provider="google",
            required_api=api, risk_level=risk, estimated_cost_usd=cost,
            estimated_latency_ms=latency, reversible=reversible,
            approval_requirement=approval, execution_mode_support=ALL_MODES,
        ))

    def _register_defaults(self):
        self._add("gmail.search", "Search Emails", "gmail", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0005, 800, False, "Search Gmail messages.")
        self._add("gmail.read", "Read Email", "gmail", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0002, 300, False, "Read a single Gmail message.")
        self._add("gmail.draft", "Draft Email", "gmail", RiskLevel.MEDIUM, ApprovalRequirement.NONE, 0.0005, 600, True, "Create a Gmail draft.")
        self._add("gmail.send", "Send Email", "gmail", RiskLevel.HIGH, ApprovalRequirement.ALWAYS, 0.0005, 900, False, "Send an email. Always requires human approval.")
        self._add("drive.search", "Search Drive", "drive", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0005, 800, False, "Search Drive files.")
        self._add("drive.read", "Read Drive File", "drive", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0002, 400, False, "Read file content.")
        self._add("drive.create_folder", "Create Folder", "drive", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0005, 600, True, "Create a Drive folder.")
        self._add("docs.create", "Create Google Doc", "docs", RiskLevel.LOW, ApprovalRequirement.NONE, 0.001, 1500, True, "Create a Google Document.")
        self._add("docs.read", "Read Doc", "docs", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0002, 400, False, "Read document text.")
        self._add("docs.update", "Update Doc", "docs", RiskLevel.MEDIUM, ApprovalRequirement.NONE, 0.0008, 900, True, "Append/update document.")
        self._add("sheets.create", "Create Spreadsheet", "sheets", RiskLevel.LOW, ApprovalRequirement.NONE, 0.001, 1200, True, "Create a Google Sheet.")
        self._add("sheets.read", "Read Sheet", "sheets", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0002, 400, False, "Read sheet values.")
        self._add("sheets.write", "Write Sheet", "sheets", RiskLevel.MEDIUM, ApprovalRequirement.NONE, 0.0008, 800, True, "Write sheet values.")
        self._add("calendar.search", "Search Events", "calendar", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0005, 600, False, "Search calendar events.")
        self._add("calendar.availability", "Check Availability", "calendar", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0005, 700, False, "Check attendee availability.")
        self._add("calendar.create_event", "Schedule Meeting", "calendar", RiskLevel.MEDIUM, ApprovalRequirement.NONE, 0.001, 1500, True, "Create event with Meet link.")

    def register(self, capability: Capability):
        self._capabilities[capability.capability_id] = capability

    def get(self, capability_id: str) -> Optional[Capability]:
        return self._capabilities.get(capability_id)

    def ids(self) -> List[str]:
        return list(self._capabilities.keys())
EOF

# ================= POLICY ENGINE (v2) =================
cat << 'EOF' > apps/api/nexora/core/policy_engine.py
from typing import Optional
from packages.core.models import MissionConstitution, Capability, RiskLevel, ApprovalRequirement

class PolicyEngine:
    """Deterministic and authoritative. LLMs can never override this."""
    def evaluate(self, action: str, constitution: MissionConstitution, capability: Optional[Capability] = None) -> str:
        if action in constitution.forbidden_actions:
            return "BLOCK"
        if capability is not None:
            if capability.approval_requirement == ApprovalRequirement.ALWAYS:
                return "REQUIRE_APPROVAL"
            if capability.risk_level == RiskLevel.HIGH:
                return "REQUIRE_APPROVAL"
        return "ALLOW"
EOF

# ================= CONSTITUTION BUILDER (v2) =================
cat << 'EOF' > apps/api/nexora/core/constitution_builder.py
from packages.core.models import MissionConstitution, MissionIntent
from nexora.core.capability_network import CapabilityNetwork

class ConstitutionBuilder:
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    def build(self, mission_id: str, intent: MissionIntent) -> MissionConstitution:
        return MissionConstitution(
            mission_id=mission_id,
            budget_usd=1.0,
            forbidden_actions=intent.constraints,
            allowed_capabilities=self.network.ids(),
        )
EOF

# ================= COMPILER (v2 — deterministic matcher, LLM seam) =================
cat << 'EOF' > apps/api/nexora/core/compiler.py
from typing import List, Tuple
from packages.core.models import MissionNode, MissionIntent, MissionConstitution
from nexora.core.capability_network import CapabilityNetwork

# ADR-031: deterministic capability discovery seam. Replaced by LLM compiler later.
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
    """Reasons over the Capability Network — never over raw Google APIs."""
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    async def compile(self, goal: str, intent: MissionIntent, constitution: MissionConstitution) -> List[MissionNode]:
        text = goal.lower()
        selected: List[Tuple[str, str]] = []   # (capability_id, matched_term)
        for terms, cap_id in KEYWORD_RULES:
            hit = next((t for t in terms if t in text), None)
            if hit and cap_id in constitution.allowed_capabilities:
                if cap_id not in [c for c, _ in selected]:
                    selected.append((cap_id, hit))

        if not selected:   # safe fallback: knowledge artifact
            selected.append(("docs.create", "fallback"))

        research_ids = [c for c, _ in selected if c in RESEARCH_CAPS]
        nodes: List[MissionNode] = []
        for cap_id, term in selected:
            deps = research_ids if (cap_id in SYNTHESIS_CAPS and cap_id not in RESEARCH_CAPS) else []
            cap = self.network.get(cap_id)
            nodes.append(MissionNode(
                capability_id=cap_id,
                depends_on=[rid for rid in deps if rid != cap_id],
                inputs=self._default_inputs(cap_id, intent),
                rationale_summary=f"Matched term '{term}' → capability {cap_id} ({cap.name}).",
            ))
        return nodes

    @staticmethod
    def _default_inputs(cap_id: str, intent: MissionIntent) -> dict:
        if cap_id == "gmail.search":
            return {"query": intent.objective, "max_results": 5}
        if cap_id == "drive.search":
            return {"query": intent.objective}
        if cap_id == "sheets.create":
            return {"title": f"Tracker - {intent.objective}", "headers": ["Item", "Owner", "Status"]}
        if cap_id == "calendar.create_event":
            return {"title": f"Sync - {intent.objective}", "attendees": ["team@acme.dev"]}
        if cap_id == "gmail.send":
            return {"to": ["customer@acme.dev"], "subject": f"Update: {intent.objective}", "body": "Status update..."}
        return {"title": f"Report - {intent.objective}", "content": "Initial details..."}
EOF

# ================= EVENT BUS =================
cat << 'EOF' > apps/api/nexora/core/event_bus.py
import logging
from collections import defaultdict
from typing import Dict, List, Protocol
from packages.core.models import utcnow

logger = logging.getLogger("nexora.events")

class EventBus(Protocol):
    async def publish(self, event_type: str, payload: Dict) -> None: ...

class LocalEventBus:
    """In-memory Pub/Sub stand-in. Zero GCP cost."""
    def __init__(self):
        self._events: Dict[str, List[Dict]] = defaultdict(list)

    async def publish(self, event_type: str, payload: Dict) -> None:
        record = {"event_type": event_type, "payload": payload, "timestamp": utcnow().isoformat()}
        self._events[payload.get("mission_id", "-")].append(record)
        logger.info("[EVENT] %s %s", event_type, payload)

    def history(self, mission_id: str) -> List[Dict]:
        return self._events.get(mission_id, [])

class PubSubEventBus:
    """Production scaffold. Lazy-imports GCP libs only when used."""
    def __init__(self, project_id: str, topic: str):
        self.project_id = project_id
        self.topic = topic

    async def publish(self, event_type: str, payload: Dict) -> None:
        import json  # noqa
        from google.cloud import pubsub_v1  # lazy: installed only in cloud image
        publisher = pubsub_v1.PublisherClient()
        path = publisher.topic_path(self.project_id, self.topic)
        publisher.publish(path, json.dumps({"event_type": event_type, "payload": payload}).encode())
EOF

# ================= TASK DISPATCHER =================
cat << 'EOF' > apps/api/nexora/core/task_dispatcher.py
import asyncio
import json
from typing import Awaitable, Callable, Protocol

NodeHandler = Callable[[str, str], Awaitable[None]]

class TaskDispatcher(Protocol):
    async def dispatch_node(self, mission_id: str, node_id: str) -> None: ...

class LocalTaskDispatcher:
    """Durable-execution stand-in for local dev. Tracks tasks to avoid GC."""
    def __init__(self, handler: NodeHandler):
        self.handler = handler
        self._tasks = set()

    async def dispatch_node(self, mission_id: str, node_id: str) -> None:
        task = asyncio.create_task(self.handler(mission_id, node_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

class CloudTasksDispatcher:
    """Production: each node becomes a Cloud Tasks HTTP hit on the worker endpoint."""
    def __init__(self, project_id: str, location: str, queue: str, worker_url: str):
        self.project_id = project_id
        self.location = location
        self.queue = queue
        self.worker_url = worker_url

    async def dispatch_node(self, mission_id: str, node_id: str) -> None:
        from google.cloud import tasks_v2  # lazy: installed only in cloud image
        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(self.project_id, self.location, self.queue)
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{self.worker_url}/internal/execute_node",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"mission_id": mission_id, "node_id": node_id}).encode(),
            }
        }
        client.create_task(request={"parent": parent, "task": task})
EOF

# ================= PROVIDER PROTOCOLS + REGISTRY =================
cat << 'EOF' > apps/api/nexora/providers/protocols.py
from typing import List, Dict, Optional, Protocol
from packages.core.models import Artifact

class WorkspaceProvider(Protocol):
    """One object implements every Workspace protocol per execution mode."""
    async def create_document(self, mission_id: str, node_id: str, title: str, content: str) -> Artifact: ...
    async def verify_artifact(self, artifact: Artifact) -> bool: ...
    async def search_emails(self, query: str, max_results: int) -> List[Dict]: ...
    async def read_email(self, message_id: str) -> Dict: ...
    async def send_email(self, to: List[str], subject: str, body: str) -> Artifact: ...
    async def search_files(self, query: str) -> List[Dict]: ...
    async def create_sheet(self, mission_id: str, node_id: str, title: str, headers: List[str]) -> Artifact: ...
    async def create_event(self, mission_id: str, node_id: str, title: str, attendees: List[str]) -> Artifact: ...

class ProviderRegistry:
    def __init__(self, provider):
        self.provider = provider

    def for_api(self, required_api: str):
        return self.provider
EOF

cat << 'EOF' > apps/api/nexora/providers/mock_workspace.py
import asyncio
import uuid
from typing import Dict, List
from packages.core.models import Artifact

class MockWorkspaceProvider:
    """Deterministic, seeded, zero-external-call provider with concurrency tracking."""
    def __init__(self):
        self._docs, self._sheets, self._events, self._sent = {}, {}, {}, {}
        self._emails = {
            "msg_1": {"id": "msg_1", "subject": "URGENT: Checkout Down", "snippet": "Customers cannot pay.",
                      "body": "Checkout API returning 500. Severe impact."},
        }
        self._files = {
            "file_1": {"id": "file_1", "name": "SLA_Acme.pdf", "type": "pdf",
                       "content": "SLA requires 1h response."},
        }
        self._active = 0
        self.max_concurrency = 0

    async def _latency(self):
        self._active += 1
        self.max_concurrency = max(self.max_concurrency, self._active)
        await asyncio.sleep(0.05)
        self._active -= 1

    async def create_document(self, mission_id, node_id, title, content) -> Artifact:
        await self._latency()
        aid = str(uuid.uuid4())
        self._docs[aid] = {"title": title, "content": content}
        return Artifact(artifact_id=aid, mission_id=mission_id, node_id=node_id, type="DOC",
                        provider="mock", resource_id=aid, uri=f"mock://docs/{aid}")

    async def search_emails(self, query, max_results) -> List[Dict]:
        await self._latency()
        return [{"id": m["id"], "subject": m["subject"], "snippet": m["snippet"]} for m in list(self._emails.values())[:max_results]]

    async def read_email(self, message_id) -> Dict:
        await self._latency()
        return self._emails.get(message_id, {})

    async def send_email(self, to, subject, body) -> Artifact:
        await self._latency()
        aid = str(uuid.uuid4())
        self._sent[aid] = {"to": to, "subject": subject}
        return Artifact(artifact_id=aid, mission_id="-", node_id="-", type="EMAIL",
                        provider="mock", resource_id=aid, uri=f"mock://sent/{aid}")

    async def search_files(self, query) -> List[Dict]:
        await self._latency()
        return [{"id": f["id"], "name": f["name"], "type": f["type"]} for f in self._files.values()]

    async def create_sheet(self, mission_id, node_id, title, headers) -> Artifact:
        await self._latency()
        aid = str(uuid.uuid4())
        self._sheets[aid] = {"title": title, "headers": headers, "rows": []}
        return Artifact(artifact_id=aid, mission_id=mission_id, node_id=node_id, type="SHEET",
                        provider="mock", resource_id=aid, uri=f"mock://sheets/{aid}")

    async def create_event(self, mission_id, node_id, title, attendees) -> Artifact:
        await self._latency()
        aid = str(uuid.uuid4())
        self._events[aid] = {"title": title, "attendees": attendees, "meet_link": f"mock://meet/{aid}"}
        return Artifact(artifact_id=aid, mission_id=mission_id, node_id=node_id, type="EVENT",
                        provider="mock", resource_id=aid, uri=f"mock://calendar/{aid}")

    async def verify_artifact(self, artifact: Artifact) -> bool:
        store = {"DOC": self._docs, "SHEET": self._sheets, "EVENT": self._events, "EMAIL": self._sent}
        return artifact.resource_id in store.get(artifact.type, {})
EOF

cat << 'EOF' > apps/api/nexora/providers/live_workspace.py
import uuid
from typing import Dict, List
from packages.core.models import Artifact
from nexora.core.credential_store import CredentialStore

class LiveWorkspaceProvider:
    """Isolated Google-specific code. Core engine never imports googleapiclient."""
    def __init__(self, credential_store: CredentialStore):
        self.credential_store = credential_store

    def _service(self, api: str, version: str):
        from googleapiclient.discovery import build  # lazy
        # creds = await self.credential_store.get_google_credentials("default")
        return build(api, version)  # real impl attaches creds

    async def create_document(self, mission_id, node_id, title, content) -> Artifact:
        svc = self._service("docs", "v1")
        doc = svc.documents().create(body={"title": title}).execute()
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="DOC", provider="google", resource_id=doc["documentId"],
                        uri=f"https://docs.google.com/document/d/{doc['documentId']}/edit")

    async def search_emails(self, query, max_results) -> List[Dict]:
        svc = self._service("gmail", "v1")
        res = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        return [{"id": m["id"]} for m in res.get("messages", [])]

    async def read_email(self, message_id) -> Dict:
        svc = self._service("gmail", "v1")
        return svc.users().messages().get(userId="me", id=message_id, format="metadata").execute()

    async def send_email(self, to, subject, body) -> Artifact:
        import base64  # noqa - real impl builds RFC822 message
        svc = self._service("gmail", "v1")
        raw = base64.urlsafe_b64encode(f"To: {', '.join(to)}\nSubject: {subject}\n\n{body}".encode()).decode()
        msg = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id="-", node_id="-", type="EMAIL",
                        provider="google", resource_id=msg["id"], uri=f"https://mail.google.com/mail/u/0/#sent/{msg['id']}")

    async def search_files(self, query) -> List[Dict]:
        svc = self._service("drive", "v3")
        res = svc.files().list(q=f"name contains '{query}'", pageSize=10).execute()
        return res.get("files", [])

    async def create_sheet(self, mission_id, node_id, title, headers) -> Artifact:
        svc = self._service("sheets", "v4")
        sheet = svc.spreadsheets().create(body={"properties": {"title": title}}).execute()
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="SHEET", provider="google", resource_id=sheet["spreadsheetId"],
                        uri=f"https://docs.google.com/spreadsheets/d/{sheet['spreadsheetId']}")

    async def create_event(self, mission_id, node_id, title, attendees) -> Artifact:
        svc = self._service("calendar", "v3")
        event = svc.events().insert(
            calendarId="primary",
            body={"summary": title, "attendees": [{"email": e} for e in attendees],
                  "start": {"dateTime": "2026-08-26T15:00:00Z"}, "end": {"dateTime": "2026-08-26T16:00:00Z"},
                  "conferenceData": {"createRequest": {"requestId": str(uuid.uuid4())}}},
            conferenceDataVersion=1,
        ).execute()
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type="EVENT", provider="google", resource_id=event["id"],
                        uri=event.get("htmlLink", ""))

    async def verify_artifact(self, artifact: Artifact) -> bool:
        return artifact.provider == "google" and bool(artifact.resource_id)
EOF

# ================= NODE EXECUTOR =================
cat << 'EOF' > apps/api/nexora/agents/node_executor.py
import uuid
from packages.core.models import MissionNode, MissionConstitution, ExecutionMode
from nexora.core.policy_engine import PolicyEngine
from nexora.core.capability_network import CapabilityNetwork
from nexora.providers.protocols import ProviderRegistry

class ApprovalRequiredError(Exception):
    def __init__(self, capability_id: str):
        self.capability_id = capability_id
        super().__init__(f"Approval required for {capability_id}")

class NodeExecutor:
    def __init__(self, policy: PolicyEngine, network: CapabilityNetwork, registry: ProviderRegistry):
        self.policy = policy
        self.network = network
        self.registry = registry

    async def execute(self, mission_id: str, node: MissionNode, constitution: MissionConstitution, mode: ExecutionMode):
        cap = self.network.get(node.capability_id)
        if cap is None:
            raise ValueError(f"Unknown capability {node.capability_id}")

        decision = self.policy.evaluate(node.capability_id, constitution, cap)
        if decision == "BLOCK":
            raise PermissionError(f"Policy blocked action: {node.capability_id}")
        if decision == "REQUIRE_APPROVAL" and not node.approved:
            raise ApprovalRequiredError(node.capability_id)

        provider = self.registry.for_api(cap.required_api)
        artifact = None
        action = node.capability_id

        if node.capability_id == "docs.create":
            artifact = await provider.create_document(mission_id, node.node_id, node.inputs.get("title", "Doc"), node.inputs.get("content", ""))
        elif node.capability_id == "gmail.search":
            node.outputs["search_results"] = await provider.search_emails(node.inputs.get("query", ""), node.inputs.get("max_results", 5))
        elif node.capability_id == "gmail.read":
            node.outputs["email"] = await provider.read_email(node.inputs.get("message_id", ""))
        elif node.capability_id == "gmail.send":
            artifact = await provider.send_email(node.inputs.get("to", []), node.inputs.get("subject", ""), node.inputs.get("body", ""))
        elif node.capability_id == "drive.search":
            node.outputs["search_results"] = await provider.search_files(node.inputs.get("query", ""))
        elif node.capability_id == "sheets.create":
            artifact = await provider.create_sheet(mission_id, node.node_id, node.inputs.get("title", "Sheet"), node.inputs.get("headers", []))
        elif node.capability_id == "calendar.create_event":
            artifact = await provider.create_event(mission_id, node.node_id, node.inputs.get("title", "Meeting"), node.inputs.get("attendees", []))
        else:
            raise ValueError(f"No executor route for {node.capability_id}")

        from packages.core.models import ActionReceipt
        receipt = ActionReceipt(
            mission_id=mission_id, node_id=node.node_id, action=action,
            reason=node.rationale_summary, agent_id="worker", capability_id=node.capability_id,
            policy_decision="ALLOW", model_tier="T1", cost_usd=cap.estimated_cost_usd,
            output_artifact_id=artifact.artifact_id if artifact else None, execution_mode=mode,
        )
        return artifact, receipt
EOF

# ================= SUPERVISOR =================
cat << 'EOF' > apps/api/nexora/agents/supervisor.py
from packages.core.models import MissionState, utcnow
from nexora.core.state_machine import MissionStateMachine
from nexora.core.health import HealthCalculator
from nexora.core.evidence import EvidenceGraph
from nexora.agents.verifier import VerificationAgent

TERMINAL = {"SUCCESS", "FAILED"}

class MissionSupervisor:
    def __init__(self, repo, bus, registry):
        self.repo = repo
        self.bus = bus
        self.registry = registry
        self.health = HealthCalculator()

    async def check_completion(self, mission_id: str):
        mission = await self.repo.get(mission_id)
        if not mission or mission.state not in (MissionState.EXECUTING, MissionState.BLOCKED):
            return

        statuses = [n.status for n in mission.nodes]

        if any(s == "WAITING_APPROVAL" for s in statuses):
            if mission.state == MissionState.EXECUTING:
                mission.state = MissionStateMachine.transition(mission.state, MissionState.BLOCKED)
                await self.bus.publish("MISSION.BLOCKED", {"mission_id": mission_id, "reason": "awaiting_approval"})
        elif all(s in TERMINAL for s in statuses):
            mission.state = MissionStateMachine.transition(mission.state, MissionState.VERIFYING)
            verifier = VerificationAgent(self.registry)
            mission.verification = await verifier.verify(mission_id, mission.intent, mission.artifacts)

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

# ================= VERIFIER (v2) =================
cat << 'EOF' > apps/api/nexora/agents/verifier.py
from packages.core.models import VerificationResult

class VerificationAgent:
    """A mission cannot reach COMPLETED unless verification passes."""
    def __init__(self, registry):
        self.registry = registry

    async def verify(self, mission_id, intent, artifacts) -> VerificationResult:
        if not artifacts:
            return VerificationResult(mission_id=mission_id, objective_completion=False,
                                      artifact_existence=False, evidence_coverage=0.0,
                                      overall_status="FAIL", failure_reasons=["No artifacts produced"])
        results = [await self.registry.provider.verify_artifact(a) for a in artifacts]
        verified = sum(results)
        all_ok = verified == len(artifacts)
        return VerificationResult(
            mission_id=mission_id,
            objective_completion=all_ok,
            artifact_existence=all_ok,
            evidence_coverage=verified / len(artifacts),
            overall_status="PASS" if all_ok else "FAIL",
            failure_reasons=[] if all_ok else [f"{len(artifacts) - verified} artifact(s) unverifiable"],
        )
EOF

# ================= RUNTIME =================
cat << 'EOF' > apps/api/nexora/core/runtime.py
import os
from packages.core.models import MissionState, utcnow
from nexora.core.state_machine import MissionStateMachine
from nexora.core.policy_engine import PolicyEngine
from nexora.core.task_dispatcher import LocalTaskDispatcher, CloudTasksDispatcher
from nexora.core.event_bus import LocalEventBus
from nexora.agents.node_executor import NodeExecutor, ApprovalRequiredError
from nexora.agents.supervisor import MissionSupervisor
from packages.core.models import ActionReceipt

class MissionRuntime:
    """Owns node execution, dependency dispatch, and supervisor notification."""
    def __init__(self, repo, network, registry, bus):
        self.repo = repo
        self.network = network
        self.registry = registry
        self.bus = bus
        self.executor = NodeExecutor(PolicyEngine(), network, registry)
        self.supervisor = MissionSupervisor(repo, bus, registry)
        if os.getenv("NEXORA_DISPATCHER") == "cloud":
            self.dispatcher = CloudTasksDispatcher(
                os.getenv("GCP_PROJECT_ID", ""), os.getenv("GCP_REGION", "us-central1"),
                "nexora-workers", os.getenv("NEXORA_WORKER_URL", "http://localhost:8000"))
        else:
            self.dispatcher = LocalTaskDispatcher(self.process_node)

    async def dispatch(self, mission_id: str, node_id: str):
        await self.dispatcher.dispatch_node(mission_id, node_id)

    async def process_node(self, mission_id: str, node_id: str):
        mission = await self.repo.get(mission_id)
        if not mission:
            return
        node = next((n for n in mission.nodes if n.node_id == node_id), None)
        if node is None or node.status != "PENDING":   # idempotency vs duplicate events
            return

        node.status = "RUNNING"
        node.started_at = utcnow()
        await self.repo.save(mission)
        await self.bus.publish("MISSION.NODE.STARTED", {"mission_id": mission_id, "node_id": node_id})

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
        except Exception as e:
            node.status = "FAILED"
            node.completed_at = utcnow()
            await self.bus.publish("MISSION.NODE.FAILED", {"mission_id": mission_id, "node_id": node_id, "error": str(e)})

        await self.repo.save(mission)

        if node.status == "SUCCESS":
            for dep in mission.nodes:
                if node_id in dep.depends_on and dep.status == "PENDING":
                    if all(self._status(mission, d) == "SUCCESS" for d in dep.depends_on):
                        await self.dispatch(mission_id, dep.node_id)

        await self.supervisor.check_completion(mission_id)

    @staticmethod
    def _status(mission, node_id: str) -> str:
        n = next((x for x in mission.nodes if x.node_id == node_id), None)
        return n.status if n else "FAILED"
EOF

# ================= MAIN (v2) =================
cat << 'EOF' > apps/api/nexora/main.py
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from packages.core.models import Mission, MissionState, ExecutionMode
from nexora.core.repository import InMemoryMissionRepository
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

repo = InMemoryMissionRepository()
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
    """Cloud Tasks worker target (also used by LocalTaskDispatcher)."""
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

# ================= TESTS (Phase 1 updated + Phase 2) =================
cat << 'EOF' > apps/api/tests/test_phase1.py
import asyncio
import time
from httpx import ASGITransport, AsyncClient
from nexora.main import app
from nexora.core.state_machine import MissionStateMachine, InvalidStateTransitionError
from nexora.core.policy_engine import PolicyEngine
from nexora.core.capability_network import CapabilityNetwork
from nexora.agents.verifier import VerificationAgent
from nexora.providers.mock_workspace import MockWorkspaceProvider
from nexora.providers.protocols import ProviderRegistry
from packages.core.models import MissionState, MissionConstitution, MissionIntent

def run(c): return asyncio.run(c)

async def post_and_wait(ac, goal, timeout=10.0):
    r = await ac.post("/api/v1/missions", json={"goal": goal, "execution_mode": "MOCK"})
    assert r.status_code == 200
    mid = r.json()["mission_id"]
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if d["state"] in ("COMPLETED", "FAILED"):
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError("mission did not finish")

def test_vertical_slice_mock():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac, "Create an incident report for this issue.")
            assert d["state"] == "COMPLETED"
            assert d["intent"]["objective"] == "Create an incident report"
            assert d["nodes"][0]["capability_id"] == "docs.create"
            assert d["nodes"][0]["status"] == "SUCCESS"
            assert d["artifacts"][0]["provider"] == "mock"
            assert d["receipts"][0]["policy_decision"] == "ALLOW"
            assert d["verification"]["overall_status"] == "PASS"
            assert d["health"]["completion_percentage"] == 100.0
            assert len(d["evidence"]) == 1
    run(inner())

def test_state_machine_rejects_invalid_transition():
    try:
        MissionStateMachine.transition(MissionState.CREATED, MissionState.COMPLETED)
        assert False
    except InvalidStateTransitionError:
        pass

def test_policy_engine_blocks_forbidden():
    constitution = MissionConstitution(mission_id="m1", forbidden_actions=["docs.create"])
    assert PolicyEngine().evaluate("docs.create", constitution) == "BLOCK"

def test_capability_network_lookup():
    net = CapabilityNetwork()
    assert net.get("docs.create") is not None
    assert net.get("gmail.search") is not None
    assert net.get("vault.search") is None   # enterprise caps arrive later

def test_verifier_fails_when_artifact_missing():
    async def inner():
        v = await VerificationAgent(ProviderRegistry(MockWorkspaceProvider())).verify("m1", MissionIntent(objective="x"), [])
        assert v.overall_status == "FAIL"
    run(inner())
EOF

cat << 'EOF' > apps/api/tests/test_phase2.py
import asyncio
import time
from httpx import ASGITransport, AsyncClient
from nexora.main import app, runtime, repo
from packages.core.models import Mission, MissionConstitution, MissionNode, MissionState, ExecutionMode

def run(c): return asyncio.run(c)

GOAL = ("Investigate the incident: search emails and drive files, create a tracker sheet, "
        "schedule a sync meeting, then write the incident report.")

async def post_and_wait(ac, goal, timeout=10.0):
    r = await ac.post("/api/v1/missions", json={"goal": goal, "execution_mode": "MOCK"})
    assert r.status_code == 200
    mid = r.json()["mission_id"]
    start = time.time()
    while time.time() - start < timeout:
        d = (await ac.get(f"/api/v1/missions/{mid}")).json()
        if d["state"] in ("COMPLETED", "FAILED"):
            return d
        await asyncio.sleep(0.2)
    raise TimeoutError("mission did not finish")

def test_parallel_dag_and_dependencies():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac, GOAL)
            assert d["state"] == "COMPLETED"
            caps = {n["capability_id"]: n for n in d["nodes"]}
            assert {"gmail.search", "drive.search", "sheets.create", "calendar.create_event", "docs.create"} <= set(caps)
            for synth in ("docs.create", "calendar.create_event"):
                for research in ("gmail.search", "drive.search"):
                    assert caps[research]["completed_at"] <= caps[synth]["started_at"]
            assert sorted(a["type"] for a in d["artifacts"]) == ["DOC", "EVENT", "SHEET"]
            assert len(d["evidence"]) == 3
    run(inner())

def test_parallelism_observed():
    assert runtime.registry.provider.max_concurrency >= 2

def test_events_published():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            d = await post_and_wait(ac, "Write the incident report.")
            ev = (await ac.get(f"/api/v1/missions/{d['mission_id']}/events")).json()
            types = [e["event_type"] for e in ev]
            assert "MISSION.NODE.COMPLETED" in types
            assert "MISSION.COMPLETED" in types
    run(inner())

def test_gmail_send_requires_approval_then_approve():
    async def inner():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/missions", json={
                "goal": "Search emails then send a status email to the customer.", "execution_mode": "MOCK"})
            mid = r.json()["mission_id"]
            d = None
            for _ in range(50):
                d = (await ac.get(f"/api/v1/missions/{mid}")).json()
                if any(n["status"] == "WAITING_APPROVAL" for n in d["nodes"]):
                    break
                await asyncio.sleep(0.2)
            assert d["state"] == "BLOCKED"
            node = next(n for n in d["nodes"] if n["capability_id"] == "gmail.send")
            a = await ac.post(f"/api/v1/missions/{mid}/approvals/{node['node_id']}", json={"approved": True})
            assert a.status_code == 200
            start = time.time()
            while time.time() - start < 10:
                d2 = (await ac.get(f"/api/v1/missions/{mid}")).json()
                if d2["state"] in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.2)
            assert d2["state"] == "COMPLETED"
            send = next(n for n in d2["nodes"] if n["capability_id"] == "gmail.send")
            assert send["status"] == "SUCCESS" and send["approved"] is True
    run(inner())

def test_worker_endpoint_executes_node():
    async def inner():
        m = Mission(goal="x", execution_mode=ExecutionMode.MOCK)
        m.constitution = MissionConstitution(mission_id=m.mission_id, allowed_capabilities=["docs.create"])
        node = MissionNode(capability_id="docs.create", inputs={"title": "t", "content": "c"})
        m.nodes.append(node)
        m.state = MissionState.EXECUTING
        await repo.save(m)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/internal/execute_node", json={"mission_id": m.mission_id, "node_id": node.node_id})
            assert r.status_code == 200
        stored = await repo.get(m.mission_id)
        assert stored.nodes[0].status == "SUCCESS"
    run(inner())
EOF

# ================= FRONTEND (v2: approvals + events) =================
cat << 'EOF' > apps/web/src/app/page.tsx
"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

const API = "http://localhost:8000";

export default function Home() {
  const [goal, setGoal] = useState(
    "Investigate the incident: search emails and drive files, create a tracker sheet, schedule a sync meeting, then write the incident report."
  );
  const [mission, setMission] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!mission || mission.state === "COMPLETED" || mission.state === "FAILED") return;
    const t = setInterval(async () => {
      const r = await fetch(`${API}/api/v1/missions/${mission.mission_id}`);
      if (r.ok) setMission(await r.json());
    }, 1000);
    return () => clearInterval(t);
  }, [mission]);

  useEffect(() => {
    if (!mission || (mission.state !== "COMPLETED" && mission.state !== "FAILED")) return;
    fetch(`${API}/api/v1/missions/${mission.mission_id}/events`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setEvents);
  }, [mission?.state]);

  const launch = async () => {
    setLoading(true); setError(null); setMission(null); setEvents([]);
    try {
      const r = await fetch(`${API}/api/v1/missions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal, execution_mode: "MOCK" }),
      });
      if (!r.ok) throw new Error(`API error ${r.status}`);
      setMission(await r.json());
    } catch (e) { setError(String(e)); } finally { setLoading(false); }
  };

  const decide = async (nodeId: string, approved: boolean) => {
    await fetch(`${API}/api/v1/missions/${mission.mission_id}/approvals/${nodeId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    });
    const r = await fetch(`${API}/api/v1/missions/${mission.mission_id}`);
    if (r.ok) setMission(await r.json());
  };

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

          <Panel title="PLAN (DAG) — parallel execution">
            {mission.nodes.map((n: any) => (
              <div key={n.node_id} className="mb-2 text-xs">
                <span className="text-emerald-400">{n.capability_id}</span>{" "}
                <span className={n.status === "SUCCESS" ? "text-zinc-400" : n.status === "WAITING_APPROVAL" ? "text-amber-400" : "text-sky-400"}>
                  [{n.status}]
                </span>
                {n.depends_on?.length > 0 && <span className="text-zinc-600"> after: {n.depends_on.length} dep(s)</span>}
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

          <Panel title="HEALTH & VERIFICATION">
            <KV k="Completion" v={`${mission.health?.completion_percentage ?? 0}%`} />
            <KV k="Evidence" v={String(mission.health?.evidence_coverage ?? 0)} />
            <KV k="Verified" v={mission.verification?.overall_status ?? "—"} highlight />
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

          <Panel title="EVENT BUS">
            {events.slice(-8).map((e, i) => (
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
cat << 'EOF' > docs/adr/ADR-031-deterministic-compiler-seam.md
# ADR-031: Deterministic Capability Matching (Phase 2 seam)
Status: Accepted. Keyword→capability matching discovers capabilities; DAG shape emerges from research/synthesis dependency rules. Replaced by the LLM compiler later without touching the runtime.
EOF
cat << 'EOF' > docs/adr/ADR-032-dispatcher-eventbus-abstractions.md
# ADR-032: Dispatcher & EventBus Protocols
Status: Accepted. LocalTaskDispatcher/LocalEventBus for zero-cost dev; CloudTasksDispatcher/PubSubEventBus for production, selected via env. Worker endpoint /internal/execute_node is the Cloud Tasks target.
EOF
cat << 'EOF' > docs/adr/ADR-033-runtime-approval-gate.md
# ADR-033: Approval Gate for ALWAYS/HIGH capabilities
Status: Accepted. NodeExecutor raises ApprovalRequired; node parks in WAITING_APPROVAL, mission BLOCKED; approval endpoint resumes. Deterministic, LLM never consulted.
EOF

echo "✅ Phase 2 generated. Restart: npm run dev:api  |  Test: npm run test:api"
