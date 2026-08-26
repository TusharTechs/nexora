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
from nexora.core.security import ContentFirewall
from nexora.core.audit import AuditTrail, AuditEntry, AuditKind
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
firewall = ContentFirewall()
audit = AuditTrail()

def build_registry(mode: ExecutionMode) -> ProviderRegistry:
    if mode == ExecutionMode.LIVE:
        from nexora.providers.live_workspace import LiveWorkspaceProvider
        return ProviderRegistry(LiveWorkspaceProvider(LocalCredentialStore()))
    return ProviderRegistry(MockWorkspaceProvider())

registry = build_registry(ExecutionMode(os.getenv("EXECUTION_MODE", "MOCK")))
runtime = MissionRuntime(repo, network, registry, bus, firewall, audit)

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

@app.on_event("startup")
async def _startup():
    audit.record(AuditEntry(kind=AuditKind.NODE_EXECUTED, severity="INFO",
                            title="api.started", detail="NEXORA API started."))

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
        audit.record(AuditEntry(mission_id=mission.mission_id, kind=AuditKind.NODE_EXECUTED,
                                severity="INFO", title="mission_created",
                                detail=f"Mission created: {req.goal[:80]}"))
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
    audit.record(AuditEntry(mission_id=mission_id, node_id=node_id,
                            kind=AuditKind.APPROVAL_DECIDED,
                            severity="INFO",
                            title="approval_decided",
                            detail=f"Approval {'GRANTED' if body.approved else 'REJECTED'} for {node.capability_id}",
                            metadata={"approved": body.approved}))
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

@app.get("/api/v1/missions/{mission_id}/audit")
async def get_audit(mission_id: str):
    await _get_or_404(mission_id)
    return [e.__dict__ for e in audit.history(mission_id)]

@app.get("/api/v1/missions/{mission_id}/audit/counts")
async def get_audit_counts(mission_id: str):
    await _get_or_404(mission_id)
    return audit.counts(mission_id)

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
    return [network.get(cid).model_dump(mode="json") for cid in network.ids()]

@app.get("/api/v1/capabilities/{capability_id}")
async def get_capability(capability_id: str):
    cap = network.get(capability_id)
    if cap is None:
        raise HTTPException(status_code=404, detail="Capability not found")
    return cap.model_dump(mode="json")