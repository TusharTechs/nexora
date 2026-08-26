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
