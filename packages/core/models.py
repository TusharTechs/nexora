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
    ACME_LABS = "ACME_LABS"

class MissionState(str, Enum):
    CREATED = "CREATED"
    INTERPRETING = "INTERPRETING"
    PLANNING = "PLANNING"
    CRITICIZING = "CRITICIZING"
    EXECUTING = "EXECUTING"
    BLOCKED = "BLOCKED"
    REPLANNING = "REPLANNING"
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
    forbidden_domains: List[str] = []      # ADR-038
    forbidden_entities: List[str] = []     # ADR-038
    allowed_capabilities: List[str] = []
    relevant_memories: List[str] = []      # ADR-072 — semantically retrieved
    created_at: datetime = Field(default_factory=utcnow)

class NodeCondition(BaseModel):
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
    replaced_by: Optional[str] = None
    rationale_summary: str = ""
    persona: Optional[str] = None   # role name from Persona system
    firewall_summary: str = ""    # ADR-037 — safe scan summary
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
    reason: str
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

class AuditEntryModel(BaseModel):
    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mission_id: str = ""
    node_id: Optional[str] = None
    kind: str = "NODE_EXECUTED"
    severity: str = "INFO"
    title: str = ""
    detail: str = ""
    metadata: Dict[str, Any] = {}
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=utcnow)

class MemoryScope(str, Enum):
    USER = "USER"
    TEAM = "TEAM"
    ORG = "ORG"
    MISSION = "MISSION"
    WORKFLOW = "WORKFLOW"

class MemoryType(str, Enum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    POLICY = "POLICY"
    LEARNED_WORKFLOW = "LEARNED_WORKFLOW"
    CORRECTION = "CORRECTION"

class MemoryEntry(BaseModel):
    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scope: MemoryScope = MemoryScope.ORG
    type: MemoryType = MemoryType.FACT
    content: str
    capability: Optional[str] = None
    effect: Optional[str] = None          # "forbid" | "require_approval" | "correction"
    provenance: str = "taught"
    confidence: float = 1.0
    author: str = "user"
    created_at: datetime = Field(default_factory=utcnow)

class WorkflowTemplate(BaseModel):
    template_id: str
    name: str
    source_mission_id: str
    blueprint: List[Dict[str, Any]] = []
    expected_cost_usd: float = 0.0
    expected_runtime_ms: int = 0
    trigger: str = "manual"
    created_at: datetime = Field(default_factory=utcnow)

class MissionSchedule(BaseModel):
    """A standing instruction that spawns missions over time (ADR-069).

    `cadence` is one of: 'once' (at `next_run`), 'daily', 'weekdays', 'weekly',
    'monthly'. The scheduler advances `next_run` after each fire.
    """
    schedule_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str
    cadence: Literal["once", "daily", "weekdays", "weekly", "monthly"] = "once"
    hour_utc: int = 8
    minute_utc: int = 0
    execution_mode: ExecutionMode = ExecutionMode.MOCK
    next_run: datetime = Field(default_factory=utcnow)
    active: bool = True
    last_run: Optional[datetime] = None
    run_count: int = 0
    spawned_mission_ids: List[str] = []
    created_at: datetime = Field(default_factory=utcnow)


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
    outcome_contract: Optional[Any] = None
    semantic_verification: Optional[Any] = None
    adaptive_replan_pending: bool = False
    context_bundle: Optional[Any] = None
    workspace_folder_id: Optional[str] = None
    workspace_uri: Optional[str] = None
    replan_count: int = 0
    created_at: datetime = Field(default_factory=utcnow)