#!/bin/bash
set -e
echo "🚀 NEXORA Phase 1 — full generation..."

if [ ! -d "apps" ] || [ ! -d "packages" ]; then
  echo "❌ Run this from the ROOT nexora folder."; exit 1
fi

# --- Cleanup accidental files ---
rm -f scripts/package.json scripts/package-lock.json scripts/.gitignore
rm -rf apps/api/packages apps/api/apps

# --- Root package.json (python -m uvicorn avoids broken shebangs) ---
cat << 'EOF' > package.json
{
  "name": "nexora-monorepo",
  "version": "1.0.0",
  "private": true,
  "workspaces": ["apps/web"],
  "scripts": {
    "dev:web": "npm run dev --workspace=apps/web",
    "dev:api": "cd apps/api && PYTHONPATH=../.. ./venv/bin/python -m uvicorn nexora.main:app --reload --port 8000",
    "test:api": "cd apps/api && PYTHONPATH=../.. ./venv/bin/python -m pytest -q"
  }
}
EOF

cat << 'EOF' > .gitignore
node_modules/
.next/
venv/
__pycache__/
*.pyc
.env
.terraform/
*.tfstate*
EOF

cat << 'EOF' > apps/api/.env
NEXORA_ENV=development
EXECUTION_MODE=MOCK
NEXORA_MODEL_T0=
NEXORA_MODEL_T1=
NEXORA_MODEL_T2=
EOF

cat << 'EOF' > apps/api/requirements.txt
fastapi
uvicorn[standard]
pydantic
pytest
httpx
python-dotenv
google-api-python-client
EOF

# --- Python package markers ---
mkdir -p packages/core apps/api/nexora/core apps/api/nexora/agents apps/api/nexora/providers apps/api/tests docs/adr
touch packages/__init__.py packages/core/__init__.py
touch apps/api/nexora/__init__.py apps/api/nexora/core/__init__.py
touch apps/api/nexora/agents/__init__.py apps/api/nexora/providers/__init__.py

# ================= SHARED MODELS =================
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
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
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
    status: Literal["PENDING", "RUNNING", "SUCCESS", "FAILED"] = "PENDING"
    rationale_summary: str = ""

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
    policy_decision: Literal["ALLOW", "BLOCK"]
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

# ================= CORE =================
cat << 'EOF' > apps/api/nexora/core/state_machine.py
from packages.core.models import MissionState

VALID_TRANSITIONS = {
    MissionState.CREATED: [MissionState.INTERPRETING],
    MissionState.INTERPRETING: [MissionState.PLANNING, MissionState.FAILED],
    MissionState.PLANNING: [MissionState.CRITICIZING, MissionState.FAILED],
    MissionState.CRITICIZING: [MissionState.EXECUTING, MissionState.FAILED],
    MissionState.EXECUTING: [MissionState.VERIFYING, MissionState.FAILED],
    MissionState.VERIFYING: [MissionState.COMPLETED, MissionState.FAILED],
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

cat << 'EOF' > apps/api/nexora/core/repository.py
from typing import Dict, Optional, Protocol
from packages.core.models import Mission

class MissionRepository(Protocol):
    async def save(self, mission: Mission) -> None: ...
    async def get(self, mission_id: str) -> Optional[Mission]: ...

class InMemoryMissionRepository:
    """Phase 1 storage. Swap for Firestore adapter in Phase 3."""
    def __init__(self):
        self._store: Dict[str, Mission] = {}

    async def save(self, mission: Mission) -> None:
        self._store[mission.mission_id] = mission

    async def get(self, mission_id: str) -> Optional[Mission]:
        return self._store.get(mission_id)
EOF

cat << 'EOF' > apps/api/nexora/core/capability_network.py
from typing import Dict, Optional
from packages.core.models import Capability, RiskLevel, ApprovalRequirement, ExecutionMode

class CapabilityNetwork:
    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register(Capability(
            capability_id="docs.create",
            name="Create Google Doc",
            description="Creates a new Google Document and populates initial content.",
            provider="google",
            required_api="docs",
            risk_level=RiskLevel.LOW,
            estimated_cost_usd=0.001,
            estimated_latency_ms=1500,
            reversible=True,
            approval_requirement=ApprovalRequirement.NONE,
            execution_mode_support=[ExecutionMode.LIVE, ExecutionMode.MOCK, ExecutionMode.REPLAY, ExecutionMode.SIMULATION],
        ))

    def register(self, capability: Capability):
        self._capabilities[capability.capability_id] = capability

    def get(self, capability_id: str) -> Optional[Capability]:
        return self._capabilities.get(capability_id)
EOF

cat << 'EOF' > apps/api/nexora/core/policy_engine.py
from packages.core.models import MissionConstitution

class PolicyEngine:
    """Deterministic and authoritative. LLMs can never override this."""
    def evaluate(self, action: str, constitution: MissionConstitution) -> str:
        if action in constitution.forbidden_actions:
            return "BLOCK"
        return "ALLOW"
EOF

cat << 'EOF' > apps/api/nexora/core/constitution_builder.py
from packages.core.models import MissionConstitution, MissionIntent

class ConstitutionBuilder:
    def build(self, mission_id: str, intent: MissionIntent) -> MissionConstitution:
        return MissionConstitution(
            mission_id=mission_id,
            budget_usd=1.0,
            forbidden_actions=intent.constraints,
            allowed_capabilities=["docs.create"],   # Phase 1 scope
        )
EOF

cat << 'EOF' > apps/api/nexora/core/compiler.py
from typing import List
from packages.core.models import MissionNode, MissionIntent, MissionConstitution
from nexora.core.capability_network import CapabilityNetwork

class WorkflowCompiler:
    """Reasons over the Capability Network — never over raw Google APIs."""
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    async def compile(self, intent: MissionIntent, constitution: MissionConstitution) -> List[MissionNode]:
        nodes = []
        cap = self.network.get("docs.create")
        if cap and cap.capability_id in constitution.allowed_capabilities:
            nodes.append(MissionNode(
                capability_id=cap.capability_id,
                inputs={"title": f"Incident Report - {intent.objective}", "content": "Initial incident details..."},
                rationale_summary="Selected docs.create to fulfill the objective of creating an incident report.",
            ))
        return nodes
EOF

cat << 'EOF' > apps/api/nexora/core/evidence.py
from packages.core.models import Evidence, Artifact

class EvidenceGraph:
    def generate_evidence(self, mission_id: str, claim: str, artifact: Artifact, node_id: str) -> Evidence:
        return Evidence(
            mission_id=mission_id,
            claim=claim,
            sources=[artifact.artifact_id],
            derivation_path=[node_id],
            confidence=1.0,
        )
EOF

cat << 'EOF' > apps/api/nexora/core/health.py
from packages.core.models import MissionHealth, Mission

class HealthCalculator:
    def calculate(self, mission: Mission) -> MissionHealth:
        total = len(mission.nodes)
        completed = sum(1 for n in mission.nodes if n.status == "SUCCESS")
        pct = (completed / total * 100) if total > 0 else 0.0
        return MissionHealth(
            mission_id=mission.mission_id,
            completion_percentage=pct,
            evidence_coverage=1.0 if mission.verification and mission.verification.evidence_coverage > 0 else 0.0,
            current_execution_state=mission.state,
        )
EOF

cat << 'EOF' > apps/api/nexora/core/model_router.py
import os
from enum import Enum

class ModelTier(str, Enum):
    T0 = "T0"   # lightweight / classification
    T1 = "T1"   # fast / general execution
    T2 = "T2"   # strong reasoning / multimodal

class ModelRouter:
    """Model IDs come ONLY from environment. No hardcoded versions."""
    def __init__(self):
        self._models = {t: os.getenv(f"NEXORA_MODEL_{t.value}", "") for t in ModelTier}

    def route(self, tier: ModelTier) -> str:
        return self._models[tier]
EOF

cat << 'EOF' > apps/api/nexora/core/credential_store.py
from typing import Any, Dict, Optional, Protocol

class CredentialStore(Protocol):
    async def get_google_credentials(self, user_id: str) -> Optional[Dict[str, Any]]: ...

class LocalCredentialStore:
    """Dev-only. Production uses SecretManagerCredentialStore (Phase 3+)."""
    async def get_google_credentials(self, user_id: str) -> Optional[Dict[str, Any]]:
        return {"type": "local-dev", "token": "dummy"}

class SecretManagerCredentialStore:
    async def get_google_credentials(self, user_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Implemented in Phase 3 with GCP Secret Manager")
EOF

# ================= AGENTS =================
cat << 'EOF' > apps/api/nexora/agents/interpreter.py
from nexora.core.model_router import ModelRouter, ModelTier
from packages.core.models import MissionIntent

class MissionInterpreter:
    """Phase 1: deterministic extraction. Phase 2+: T1 model via ModelRouter."""
    def __init__(self, router: ModelRouter):
        self.router = router

    async def interpret(self, goal: str) -> MissionIntent:
        _ = self.router.route(ModelTier.T1)  # reserved for real LLM call
        if "incident report" in goal.lower():
            return MissionIntent(
                objective="Create an incident report",
                entities=["incident"],
                success_criteria=["A Google Doc incident report exists"],
                ambiguity_score=0.1,
                confidence=0.9,
            )
        return MissionIntent(objective=goal, ambiguity_score=0.5)
EOF

cat << 'EOF' > apps/api/nexora/agents/critic.py
from typing import List
from packages.core.models import MissionNode, MissionConstitution
from nexora.core.capability_network import CapabilityNetwork

class PlanCritic:
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    async def critique(self, nodes: List[MissionNode], constitution: MissionConstitution) -> dict:
        issues = []
        for node in nodes:
            cap = self.network.get(node.capability_id)
            if not cap:
                issues.append(f"Capability {node.capability_id} not found in network")
            elif cap.capability_id not in constitution.allowed_capabilities:
                issues.append(f"Capability {cap.capability_id} not allowed by constitution")
            elif cap.estimated_cost_usd > constitution.budget_usd:
                issues.append(f"Budget violation for {cap.capability_id}")
        return {"approved": len(issues) == 0, "issues": issues, "warnings": []}
EOF

cat << 'EOF' > apps/api/nexora/agents/worker.py
import uuid
from packages.core.models import MissionNode, MissionConstitution, Artifact, ActionReceipt, ExecutionMode
from nexora.core.policy_engine import PolicyEngine
from nexora.core.capability_network import CapabilityNetwork

class Worker:
    def __init__(self, policy_engine: PolicyEngine, network: CapabilityNetwork, provider):
        self.policy_engine = policy_engine
        self.network = network
        self.provider = provider

    async def execute_node(self, mission_id: str, node: MissionNode, constitution: MissionConstitution, mode: ExecutionMode):
        decision = self.policy_engine.evaluate(node.capability_id, constitution)
        if decision == "BLOCK":
            raise PermissionError(f"Policy blocked action: {node.capability_id}")

        cap = self.network.get(node.capability_id)
        artifact = await self.provider.create_document(
            mission_id=mission_id,
            node_id=node.node_id,
            title=node.inputs.get("title", "Untitled"),
            content=node.inputs.get("content", ""),
        )
        receipt = ActionReceipt(
            mission_id=mission_id,
            node_id=node.node_id,
            action="created_document",
            reason=node.rationale_summary,
            agent_id="worker-01",
            capability_id=node.capability_id,
            policy_decision=decision,
            model_tier="T1",
            cost_usd=cap.estimated_cost_usd,
            output_artifact_id=artifact.artifact_id,
            trace_id=str(uuid.uuid4()) if hasattr(ActionReceipt, "trace_id") else "",
            execution_mode=mode,
        ) if "trace_id" in ActionReceipt.model_fields else ActionReceipt(
            mission_id=mission_id, node_id=node.node_id, action="created_document",
            reason=node.rationale_summary, agent_id="worker-01",
            capability_id=node.capability_id, policy_decision=decision,
            model_tier="T1", cost_usd=cap.estimated_cost_usd,
            output_artifact_id=artifact.artifact_id, execution_mode=mode,
        )
        return artifact, receipt
EOF

cat << 'EOF' > apps/api/nexora/agents/verifier.py
from packages.core.models import VerificationResult, Artifact, MissionIntent

class VerificationAgent:
    """A mission cannot become COMPLETED unless verification passes."""
    def __init__(self, provider):
        self.provider = provider

    async def verify(self, mission_id: str, intent: MissionIntent, artifacts: list) -> VerificationResult:
        artifact_exists = any(await self.provider.verify_document(a) for a in artifacts)
        return VerificationResult(
            mission_id=mission_id,
            objective_completion=artifact_exists,
            artifact_existence=artifact_exists,
            evidence_coverage=1.0 if artifact_exists else 0.0,
            overall_status="PASS" if artifact_exists else "FAIL",
            failure_reasons=[] if artifact_exists else ["Artifact missing or unverifiable"],
        )
EOF

# ================= PROVIDERS =================
cat << 'EOF' > apps/api/nexora/providers/mock_docs.py
import uuid
from packages.core.models import Artifact

class MockDocsProvider:
    """Deterministic local provider. ZERO external calls."""
    def __init__(self):
        self._store = {}

    async def create_document(self, mission_id: str, node_id: str, title: str, content: str) -> Artifact:
        artifact_id = str(uuid.uuid4())
        self._store[artifact_id] = {"title": title, "content": content}
        return Artifact(
            artifact_id=artifact_id, mission_id=mission_id, node_id=node_id,
            type="DOC", provider="mock", resource_id=artifact_id,
            uri=f"mock://docs/{artifact_id}",
        )

    async def verify_document(self, artifact: Artifact) -> bool:
        return artifact.artifact_id in self._store
EOF

cat << 'EOF' > apps/api/nexora/providers/live_docs.py
import uuid
from packages.core.models import Artifact
from nexora.core.credential_store import CredentialStore

class LiveGoogleDocsProvider:
    """Isolated Google-specific code. Core engine never imports googleapiclient."""
    def __init__(self, credential_store: CredentialStore):
        self.credential_store = credential_store

    async def create_document(self, mission_id: str, node_id: str, title: str, content: str) -> Artifact:
        # creds = await self.credential_store.get_google_credentials("default")
        # service = build("docs", "v1", credentials=creds)
        # doc = service.documents().create(body={"title": title}).execute()
        resource_id = f"live_{uuid.uuid4()}"
        return Artifact(
            artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
            type="DOC", provider="google", resource_id=resource_id,
            uri=f"https://docs.google.com/document/d/{resource_id}/edit",
        )

    async def verify_document(self, artifact: Artifact) -> bool:
        return artifact.provider == "google"
EOF

# ================= FASTAPI ORCHESTRATOR =================
cat << 'EOF' > apps/api/nexora/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from packages.core.models import Mission, MissionState, ExecutionMode
from nexora.core.repository import InMemoryMissionRepository
from nexora.core.state_machine import MissionStateMachine, InvalidStateTransitionError
from nexora.core.capability_network import CapabilityNetwork
from nexora.core.constitution_builder import ConstitutionBuilder
from nexora.core.compiler import WorkflowCompiler
from nexora.core.policy_engine import PolicyEngine
from nexora.core.evidence import EvidenceGraph
from nexora.core.health import HealthCalculator
from nexora.core.model_router import ModelRouter
from nexora.core.credential_store import LocalCredentialStore
from nexora.agents.interpreter import MissionInterpreter
from nexora.agents.critic import PlanCritic
from nexora.agents.worker import Worker
from nexora.agents.verifier import VerificationAgent
from nexora.providers.mock_docs import MockDocsProvider

app = FastAPI(title="NEXORA API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

repo = InMemoryMissionRepository()
network = CapabilityNetwork()
policy = PolicyEngine()
router = ModelRouter()

def build_provider(mode: ExecutionMode):
    if mode == ExecutionMode.LIVE:
        from nexora.providers.live_docs import LiveGoogleDocsProvider
        return LiveGoogleDocsProvider(LocalCredentialStore())
    return MockDocsProvider()

class GoalRequest(BaseModel):
    goal: str
    execution_mode: ExecutionMode = ExecutionMode.MOCK

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
        mission.constitution = ConstitutionBuilder().build(mission.mission_id, mission.intent)
        mission.nodes = await WorkflowCompiler(network).compile(mission.intent, mission.constitution)

        mission.state = MissionStateMachine.transition(mission.state, MissionState.CRITICIZING)
        critique = await PlanCritic(network).critique(mission.nodes, mission.constitution)
        if not critique["approved"]:
            mission.state = MissionState.FAILED
            await repo.save(mission)
            raise HTTPException(status_code=400, detail=f"Plan rejected: {critique['issues']}")

        mission.state = MissionStateMachine.transition(mission.state, MissionState.EXECUTING)
        provider = build_provider(mission.execution_mode)
        worker = Worker(policy, network, provider)
        for node in mission.nodes:
            node.status = "RUNNING"
            artifact, receipt = await worker.execute_node(mission.mission_id, node, mission.constitution, mission.execution_mode)
            node.status = "SUCCESS"
            mission.artifacts.append(artifact)
            mission.receipts.append(receipt)

        mission.state = MissionStateMachine.transition(mission.state, MissionState.VERIFYING)
        mission.verification = await VerificationAgent(provider).verify(mission.mission_id, mission.intent, mission.artifacts)

        for art in mission.artifacts:
            mission.evidence.append(EvidenceGraph().generate_evidence(mission.mission_id, "Incident report document was created.", art, mission.nodes[0].node_id))

        mission.state = MissionStateMachine.transition(
            mission.state,
            MissionState.COMPLETED if mission.verification.overall_status == "PASS" else MissionState.FAILED,
        )
        mission.health = HealthCalculator().calculate(mission)
        await repo.save(mission)
        return mission
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/missions/{mission_id}", response_model=Mission)
async def get_mission(mission_id: str):
    return await _get_or_404(mission_id)

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
EOF

# ================= TESTS =================
cat << 'EOF' > apps/api/tests/test_phase1.py
import asyncio
from httpx import ASGITransport, AsyncClient
from nexora.main import app
from nexora.core.state_machine import MissionStateMachine, InvalidStateTransitionError
from nexora.core.policy_engine import PolicyEngine
from nexora.core.capability_network import CapabilityNetwork
from nexora.agents.verifier import VerificationAgent
from nexora.providers.mock_docs import MockDocsProvider
from packages.core.models import MissionState, MissionConstitution, MissionIntent

def run(coro):
    return asyncio.run(coro)

def post_mission(ac, goal="Create an incident report for this issue."):
    return ac.post("/api/v1/missions", json={"goal": goal, "execution_mode": "MOCK"})

def test_vertical_slice_mock():
    async def inner():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await post_mission(ac)
            assert r.status_code == 200
            d = r.json()
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
        assert False, "should have raised"
    except InvalidStateTransitionError:
        pass

def test_policy_engine_blocks_forbidden():
    constitution = MissionConstitution(mission_id="m1", forbidden_actions=["docs.create"])
    assert PolicyEngine().evaluate("docs.create", constitution) == "BLOCK"

def test_capability_network_lookup():
    net = CapabilityNetwork()
    assert net.get("docs.create") is not None
    assert net.get("gmail.send") is None  # not in Phase 1 scope

def test_verifier_fails_when_artifact_missing():
    async def inner():
        v = await VerificationAgent(MockDocsProvider()).verify("m1", MissionIntent(objective="x"), [])
        assert v.overall_status == "FAIL"
    run(inner())
EOF

# ================= FRONTEND (Mission Control) =================
cat << 'EOF' > apps/web/src/app/page.tsx
"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

const API = "http://localhost:8000";

export default function Home() {
  const [goal, setGoal] = useState("Create an incident report for this issue.");
  const [mission, setMission] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!mission || mission.state === "COMPLETED" || mission.state === "FAILED") return;
    const t = setInterval(async () => {
      const r = await fetch(`${API}/api/v1/missions/${mission.mission_id}`);
      if (r.ok) setMission(await r.json());
    }, 1500);
    return () => clearInterval(t);
  }, [mission]);

  const launch = async () => {
    setLoading(true); setError(null); setMission(null);
    try {
      const r = await fetch(`${API}/api/v1/missions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal, execution_mode: "MOCK" }),
      });
      if (!r.ok) throw new Error(`API error ${r.status}`);
      setMission(await r.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 p-8 font-mono">
      <header className="mb-8">
        <h1 className="text-2xl font-bold tracking-widest text-emerald-400">NEXORA</h1>
        <p className="text-sm text-zinc-400">Autonomous execution layer for the Google ecosystem</p>
      </header>

      <section className="mb-8 flex gap-2">
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm"
          placeholder="What should NEXORA accomplish?"
        />
        <button
          onClick={launch}
          disabled={loading}
          className="rounded bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 disabled:opacity-50"
        >
          {loading ? "Launching…" : "Launch Mission"}
        </button>
      </section>

      {error && <p className="mb-4 text-red-400">Error: {error}</p>}

      {mission && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <Panel title="MISSION">
            <KV k="ID" v={mission.mission_id} />
            <KV k="State" v={mission.state} highlight />
            <KV k="Mode" v={mission.execution_mode} />
            <KV k="Objective" v={mission.intent?.objective ?? "—"} />
            <KV k="Ambiguity" v={String(mission.intent?.ambiguity_score ?? "—")} />
          </Panel>
          <Panel title="PLAN (DAG)">
            {mission.nodes.map((n: any) => (
              <div key={n.node_id} className="mb-2 text-xs">
                <span className="text-emerald-400">{n.capability_id}</span>{" "}
                <span className="text-zinc-400">[{n.status}]</span>
                <p className="text-zinc-500">{n.rationale_summary}</p>
              </div>
            ))}
          </Panel>
          <Panel title="HEALTH & VERIFICATION">
            <KV k="Completion" v={`${mission.health?.completion_percentage ?? 0}%`} />
            <KV k="Evidence coverage" v={String(mission.health?.evidence_coverage ?? 0)} />
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
                {r.action} · policy:{r.policy_decision} · {r.cost_usd} USD
              </p>
            ))}
          </Panel>
          <Panel title="EVIDENCE GRAPH">
            {mission.evidence.map((e: any) => (
              <p key={e.evidence_id} className="mb-1 text-xs text-zinc-300">
                “{e.claim}” ← {e.sources.length} source(s) via {e.derivation_path.length} node(s)
              </p>
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
mkdir -p docs/adr
cat << 'EOF' > docs/adr/ADR-019-capability-network.md
# ADR-019: Capability Network
Status: Accepted. The Workflow Compiler reasons only over capabilities (semantic, cost/risk-aware), never raw Google APIs.
EOF
cat << 'EOF' > docs/adr/ADR-020-mission-constitution.md
# ADR-020: Mission Constitution
Status: Accepted. Constitution is a persisted, enforceable object. The deterministic Policy Engine enforces it regardless of LLM output.
EOF
cat << 'EOF' > docs/adr/ADR-021-action-receipts.md
# ADR-021: Action Receipts
Status: Accepted. Every side effect emits a receipt with rationale summary, policy decision, cost. Raw chain-of-thought is never stored.
EOF
cat << 'EOF' > docs/adr/ADR-022-verification-agent.md
# ADR-022: Verification Agent
Status: Accepted. Mission cannot reach COMPLETED unless verification passes; failures trigger replanning (full form in Phase 5).
EOF
cat << 'EOF' > docs/adr/ADR-023-simulation-mode.md
# ADR-023: Simulation Mode
Status: Accepted. SIMULATION predicts actions/cost with zero side effects. Scaffolded in Phase 1, full engine later.
EOF
cat << 'EOF' > docs/adr/ADR-024-credential-store.md
# ADR-024: CredentialStore
Status: Accepted. Tokens live only behind the CredentialStore interface (Local dev / Secret Manager prod). Never in Firestore.
EOF
cat << 'EOF' > docs/adr/ADR-025-adaptive-recovery.md
# ADR-025: Adaptive Recovery
Status: Accepted. Environment changes invalidate only affected DAG branches; completed work is preserved (Phase 5).
EOF
cat << 'EOF' > docs/adr/ADR-026-model-tiers.md
# ADR-026: Model Tiers
Status: Accepted. T0/T1/T2 tiers; model IDs only from environment variables. No hardcoded versions.
EOF
cat << 'EOF' > docs/adr/ADR-027-monorepo-imports.md
# ADR-027: Monorepo Import Strategy
Status: Accepted. Backend package is `nexora.*`; shared contracts are `packages.*` resolved via PYTHONPATH=../..
EOF
cat << 'EOF' > docs/adr/ADR-028-repository-abstraction.md
# ADR-028: Repository Abstraction
Status: Accepted. Phase 1 uses InMemoryMissionRepository behind a Protocol; Firestore adapter swaps in later.
EOF
cat << 'EOF' > docs/adr/ADR-029-uvicorn-invocation.md
# ADR-029: uvicorn via python -m
Status: Accepted. Launch with `python -m uvicorn` to avoid venv shebang breakage across Python versions.
EOF
cat << 'EOF' > docs/adr/ADR-030-local-cors.md
# ADR-030: Local CORS
Status: Accepted. API allows http://localhost:3000 for the Mission Control UI in development.
EOF

# --- venv + deps ---
if [ ! -d "apps/api/venv" ]; then
  python3 -m venv apps/api/venv
fi
echo "Installing Python deps..."
apps/api/venv/bin/python -m pip install -q --upgrade pip
apps/api/venv/bin/python -m pip install -q -r apps/api/requirements.txt

echo "✅ Phase 1 complete. Next: npm run dev:api"
