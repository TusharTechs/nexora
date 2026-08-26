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
