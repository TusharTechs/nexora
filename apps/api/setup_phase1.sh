#!/bin/bash
set -e

echo "🚀 Generating NEXORA Phase 1 Codebase..."

# Ensure directories exist
mkdir -p packages/core
mkdir -p apps/api/nexora/core
mkdir -p apps/api/nexora/agents
mkdir -p apps/api/nexora/providers

# Create __init__.py files
touch packages/__init__.py
touch packages/core/__init__.py
touch apps/api/nexora/__init__.py
touch apps/api/nexora/core/__init__.py
touch apps/api/nexora/agents/__init__.py
touch apps/api/nexora/providers/__init__.py

# 1. Core Models
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

class ActionReceipt(BaseModel):
    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mission_id: str
    node_id: str
    action: str
    reason: str
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
    receipts: List[ActionReceipt] = []
    verification: Optional[VerificationResult] = None
    health: Optional[MissionHealth] = None
    execution_mode: ExecutionMode = ExecutionMode.MOCK
    created_at: datetime = Field(default_factory=utcnow)
EOF

# 2. State Machine
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

# 3. Repository
cat << 'EOF' > apps/api/nexora/core/repository.py
from typing import Dict, Optional
from packages.core.models import Mission

class InMemoryMissionRepository:
    def __init__(self):
        self._store: Dict[str, Mission] = {}

    async def save(self, mission: Mission) -> None:
        self._store[mission.mission_id] = mission

    async def get(self, mission_id: str) -> Optional[Mission]:
        return self._store.get(mission_id)
EOF

# 4. Capability Network
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
            description="Creates a new Google Document.",
            provider="google",
            required_api="docs",
            risk_level=RiskLevel.LOW,
            estimated_cost_usd=0.001,
            estimated_latency_ms=1500,
            reversible=True,
            approval_requirement=ApprovalRequirement.NONE,
            execution_mode_support=[ExecutionMode.LIVE, ExecutionMode.MOCK]
        ))

    def register(self, capability: Capability):
        self._capabilities[capability.capability_id] = capability

    def get(self, capability_id: str) -> Optional[Capability]:
        return self._capabilities.get(capability_id)
EOF

# 5. Policy Engine
cat << 'EOF' > apps/api/nexora/core/policy_engine.py
from packages.core.models import MissionConstitution

class PolicyEngine:
    def evaluate(self, action: str, constitution: MissionConstitution) -> str:
        if action in constitution.forbidden_actions:
            return "BLOCK"
        return "ALLOW"
EOF

# 6. Interpreter
cat << 'EOF' > apps/api/nexora/agents/interpreter.py
from packages.core.models import MissionIntent

class MissionInterpreter:
    async def interpret(self, goal: str) -> MissionIntent:
        # Phase 1: Deterministic mock interpretation
        if "incident report" in goal.lower():
            return MissionIntent(
                objective="Create an incident report",
                entities=["incident"],
                success_criteria=["A Google Doc incident report exists"],
                ambiguity_score=0.1
            )
        return MissionIntent(objective=goal, ambiguity_score=0.5)
EOF

# 7. Constitution Builder
cat << 'EOF' > apps/api/nexora/core/constitution_builder.py
from packages.core.models import MissionConstitution, MissionIntent

class ConstitutionBuilder:
    def build(self, mission_id: str, intent: MissionIntent) -> MissionConstitution:
        return MissionConstitution(
            mission_id=mission_id,
            budget_usd=1.0,
            allowed_capabilities=["docs.create"]
        )
EOF

# 8. Compiler
cat << 'EOF' > apps/api/nexora/core/compiler.py
from typing import List
from packages.core.models import MissionNode, MissionIntent, MissionConstitution
from apps.api.nexora.core.capability_network import CapabilityNetwork

class WorkflowCompiler:
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    async def compile(self, intent: MissionIntent, constitution: MissionConstitution) -> List[MissionNode]:
        nodes = []
        cap = self.network.get("docs.create")
        if cap and cap.capability_id in constitution.allowed_capabilities:
            nodes.append(MissionNode(
                capability_id=cap.capability_id,
                inputs={"title": f"Incident Report - {intent.objective}", "content": "Initial details..."},
                rationale_summary="Selected docs.create to fulfill objective."
            ))
        return nodes
EOF

# 9. Critic
cat << 'EOF' > apps/api/nexora/agents/critic.py
from typing import List
from packages.core.models import MissionNode, MissionConstitution
from apps.api.nexora.core.capability_network import CapabilityNetwork

class PlanCritic:
    def __init__(self, network: CapabilityNetwork):
        self.network = network

    async def critique(self, nodes: List[MissionNode], constitution: MissionConstitution) -> dict:
        issues = []
        for node in nodes:
            cap = self.network.get(node.capability_id)
            if not cap:
                issues.append(f"Capability {node.capability_id} not found")
            elif cap.capability_id not in constitution.allowed_capabilities:
                issues.append(f"Capability {cap.capability_id} not allowed")
        return {"approved": len(issues) == 0, "issues": issues}
EOF

# 10. Mock Docs Provider
cat << 'EOF' > apps/api/nexora/providers/mock_docs.py
import uuid
from packages.core.models import Artifact

class MockDocsProvider:
    def __init__(self):
        self._store = {}

    async def create_document(self, mission_id: str, node_id: str, title: str, content: str) -> Artifact:
        artifact_id = str(uuid.uuid4())
        self._store[artifact_id] = {"title": title, "content": content}
        return Artifact(
            artifact_id=artifact_id,
            mission_id=mission_id,
            node_id=node_id,
            type="DOC",
            provider="mock",
            resource_id=artifact_id,
            uri=f"mock://docs/{artifact_id}"
        )

    async def verify_document(self, artifact: Artifact) -> bool:
        return artifact.artifact_id in self._store
EOF

# 11. Worker
cat << 'EOF' > apps/api/nexora/agents/worker.py
import uuid
from packages.core.models import MissionNode, MissionConstitution, Artifact, ActionReceipt, ExecutionMode
from apps.api.nexora.core.policy_engine import PolicyEngine
from apps.api.nexora.core.capability_network import CapabilityNetwork

class Worker:
    def __init__(self, policy_engine: PolicyEngine, network: CapabilityNetwork, provider):
        self.policy_engine = policy_engine
        self.network = network
        self.provider = provider

    async def execute_node(self, mission_id: str, node: MissionNode, constitution: MissionConstitution, mode: ExecutionMode) -> tuple[Artifact, ActionReceipt]:
        decision = self.policy_engine.evaluate(node.capability_id, constitution)
        if decision == "BLOCK":
            raise PermissionError(f"Policy blocked: {node.capability_id}")

        cap = self.network.get(node.capability_id)
        artifact = await self.provider.create_document(
            mission_id=mission_id,
            node_id=node.node_id,
            title=node.inputs.get("title", "Untitled"),
            content=node.inputs.get("content", "")
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
            execution_mode=mode
        )
        return artifact, receipt
EOF

# 12. Verifier
cat << 'EOF' > apps/api/nexora/agents/verifier.py
from packages.core.models import VerificationResult, Artifact, MissionIntent

class VerificationAgent:
    def __init__(self, provider):
        self.provider = provider

    async def verify(self, mission_id: str, intent: MissionIntent, artifacts: list[Artifact]) -> VerificationResult:
        artifact_exists = False
        for art in artifacts:
            if await self.provider.verify_document(art):
                artifact_exists = True
                break

        return VerificationResult(
            mission_id=mission_id,
            objective_completion=artifact_exists,
            artifact_existence=artifact_exists,
            evidence_coverage=1.0 if artifact_exists else 0.0,
            overall_status="PASS" if artifact_exists else "FAIL",
            failure_reasons=[] if artifact_exists else ["Artifact missing"]
        )
EOF

# 13. Evidence
cat << 'EOF' > apps/api/nexora/core/evidence.py
from packages.core.models import Evidence, Artifact

class EvidenceGraph:
    def generate_evidence(self, mission_id: str, claim: str, artifact: Artifact, node_id: str) -> Evidence:
        return Evidence(
            mission_id=mission_id,
            claim=claim,
            sources=[artifact.artifact_id],
            derivation_path=[node_id],
            confidence=1.0
        )
EOF

# 14. Health
cat << 'EOF' > apps/api/nexora/core/health.py
from packages.core.models import MissionHealth, MissionState, Mission

class HealthCalculator:
    def calculate(self, mission: Mission) -> MissionHealth:
        total = len(mission.nodes)
        completed = sum(1 for n in mission.nodes if n.status == "SUCCESS")
        pct = (completed / total * 100) if total > 0 else 0.0
        return MissionHealth(
            mission_id=mission.mission_id,
            completion_percentage=pct,
            evidence_coverage=1.0 if mission.verification and mission.verification.evidence_coverage > 0 else 0.0,
            current_execution_state=mission.state
        )
EOF

# 15. Main API
cat << 'EOF' > apps/api/nexora/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from packages.core.models import Mission, MissionState, ExecutionMode
from apps.api.nexora.core.repository import InMemoryMissionRepository
from apps.api.nexora.core.state_machine import MissionStateMachine, InvalidStateTransitionError
from apps.api.nexora.agents.interpreter import MissionInterpreter
from apps.api.nexora.core.constitution_builder import ConstitutionBuilder
from apps.api.nexora.core.compiler import WorkflowCompiler
from apps.api.nexora.agents.critic import PlanCritic
from apps.api.nexora.core.policy_engine import PolicyEngine
from apps.api.nexora.agents.worker import Worker
from apps.api.nexora.agents.verifier import VerificationAgent
from apps.api.nexora.core.evidence import EvidenceGraph
from apps.api.nexora.core.health import HealthCalculator
from apps.api.nexora.providers.mock_docs import MockDocsProvider
from apps.api.nexora.core.capability_network import CapabilityNetwork

app = FastAPI(title="NEXORA API")

# Dependency Injection
repo = InMemoryMissionRepository()
network = CapabilityNetwork()
provider = MockDocsProvider()
policy = PolicyEngine()

class GoalRequest(BaseModel):
    goal: str
    execution_mode: ExecutionMode = ExecutionMode.MOCK

@app.post("/api/v1/missions", response_model=Mission)
async def create_mission(req: GoalRequest):
    mission = Mission(goal=req.goal, execution_mode=req.execution_mode)
    await repo.save(mission)
    
    try:
        # 1. Interpreter
        mission.state = MissionStateMachine.transition(mission.state, MissionState.INTERPRETING)
        interpreter = MissionInterpreter()
        mission.intent = await interpreter.interpret(req.goal)
        
        # 2. Constitution
        mission.state = MissionStateMachine.transition(mission.state, MissionState.PLANNING)
        builder = ConstitutionBuilder()
        mission.constitution = builder.build(mission.mission_id, mission.intent)
        
        # 3. Compiler
        compiler = WorkflowCompiler(network)
        mission.nodes = await compiler.compile(mission.intent, mission.constitution)
        
        # 4. Critic
        mission.state = MissionStateMachine.transition(mission.state, MissionState.CRITICIZING)
        critic = PlanCritic(network)
        critique = await critic.critique(mission.nodes, mission.constitution)
        if not critique["approved"]:
            mission.state = MissionState.FAILED
            await repo.save(mission)
            raise HTTPException(status_code=400, detail=f"Plan rejected: {critique['issues']}")
            
        # 5. Execute
        mission.state = MissionStateMachine.transition(mission.state, MissionState.EXECUTING)
        worker = Worker(policy, network, provider)
        
        for node in mission.nodes:
            node.status = "RUNNING"
            artifact, receipt = await worker.execute_node(mission.mission_id, node, mission.constitution, mission.execution_mode)
            node.status = "SUCCESS"
            mission.artifacts.append(artifact)
            mission.receipts.append(receipt)
            
        # 6. Verify
        mission.state = MissionStateMachine.transition(mission.state, MissionState.VERIFYING)
        verifier = VerificationAgent(provider)
        mission.verification = await verifier.verify(mission.mission_id, mission.intent, mission.artifacts)
        
        # 7. Evidence
        eg = EvidenceGraph()
        for art in mission.artifacts:
            mission.evidence.append(eg.generate_evidence(mission.mission_id, "Document created", art, mission.nodes[0].node_id))
            
        # 8. Complete
        if mission.verification.overall_status == "PASS":
            mission.state = MissionStateMachine.transition(mission.state, MissionState.COMPLETED)
        else:
            mission.state = MissionState.FAILED
            
        # 9. Health
        mission.health = HealthCalculator().calculate(mission)
        
        await repo.save(mission)
        return mission
        
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/missions/{mission_id}", response_model=Mission)
async def get_mission(mission_id: str):
    mission = await repo.get(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission
EOF

echo "✅ Phase 1 codebase generated successfully!"
