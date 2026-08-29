import os
from typing import Optional
from urllib.parse import urlencode

from dotenv import load_dotenv
load_dotenv()  # populate os.environ from apps/api/.env before anything reads it

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from packages.core.models import (Mission, MissionState, ExecutionMode, MissionIntent,
                                  MissionNode, MemoryEntry, MemoryType, MemoryScope)
from nexora.core.repository import build_repository
from nexora.core.state_machine import MissionStateMachine, InvalidStateTransitionError
from nexora.core.capability_network import     CapabilityNetwork
from nexora.core.constitution_builder import ConstitutionBuilder
from nexora.core.compiler import WorkflowCompiler
from nexora.core.llm_compiler import LLMWorkflowCompiler
from nexora.core.event_bus import LocalEventBus
from nexora.core.runtime import MissionRuntime
from nexora.core.security import ContentFirewall
from nexora.core.audit import AuditTrail, AuditEntry, AuditKind
from nexora.core.memory import InMemoryMemoryStore, TeachExtractor
from nexora.core.forge import WorkflowForge
from nexora.core.credential_store import LocalCredentialStore
from nexora.core.model_router import ModelRouter
from nexora.core.contract import ContractGenerator
from nexora.core.context_discovery import ContextDiscoveryService
from nexora.agents.interpreter import MissionInterpreter
from nexora.agents.critic import PlanCritic
from nexora.providers.mock_workspace import MockWorkspaceProvider
from nexora.providers.acme_labs import AcmeLabsProvider
from nexora.providers.replay_provider import ReplayProvider
from nexora.providers.protocols import ProviderRegistry
from nexora.benchmarks import BENCHMARKS, evaluate_mission

app = FastAPI(title="NEXORA API")

# Allowed browser origins: localhost for dev plus anything in CORS_ORIGINS
# (comma-separated) for the deployed frontend.
_cors = ["http://localhost:3000", "http://127.0.0.1:3000"]
_cors += [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_cors,
                   allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

repo = build_repository()
network = CapabilityNetwork()
router = ModelRouter()
bus = LocalEventBus()
firewall = ContentFirewall()
audit = AuditTrail()
memory = InMemoryMemoryStore()
forge = WorkflowForge(network)

def build_registry(mode: ExecutionMode) -> ProviderRegistry:
    if mode == ExecutionMode.LIVE:
        from nexora.providers.live_workspace import LiveWorkspaceProvider
        return ProviderRegistry(LiveWorkspaceProvider(LocalCredentialStore()))
    if mode == ExecutionMode.ACME_LABS:
        return ProviderRegistry(AcmeLabsProvider())
    return ProviderRegistry(MockWorkspaceProvider())

registry = build_registry(ExecutionMode(os.getenv("EXECUTION_MODE", "MOCK")))
runtime = MissionRuntime(repo, network, registry, bus, firewall, audit, memory)
llm_compiler = LLMWorkflowCompiler(network, router)


# ---------------- Request models ----------------

class GoalRequest(BaseModel):
    goal: str
    execution_mode: ExecutionMode = ExecutionMode.MOCK
    attachment: Optional[dict] = None

class NodeRef(BaseModel):
    mission_id: str
    node_id: str

class ApprovalRequest(BaseModel):
    approved: bool

class InterventionRequest(BaseModel):
    instruction: str

class TeachRequest(BaseModel):
    instruction: str


async def _get_or_404(mission_id: str) -> Mission:
    mission = await repo.get(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "execution_mode": os.getenv("EXECUTION_MODE", "MOCK"),
            "repo": os.getenv("NEXORA_REPO", "memory"),
            "dispatcher": os.getenv("NEXORA_DISPATCHER", "local")}


@app.on_event("startup")
async def _startup():
    audit.record(AuditEntry(kind=AuditKind.NODE_EXECUTED, severity="INFO",
                            title="api.started", detail="NEXORA API started."))


# ---------------- Missions ----------------

@app.post("/api/v1/missions", response_model=Mission)
async def create_mission(req: GoalRequest):
    mission = Mission(goal=req.goal, execution_mode=req.execution_mode)
    await repo.save(mission)
    try:
        mission.state = MissionStateMachine.transition(mission.state, MissionState.INTERPRETING)
        mission.intent = await MissionInterpreter(router).interpret(req.goal)
        # Set runtime registry matching execution mode if specialized
        if req.execution_mode == ExecutionMode.ACME_LABS and not isinstance(runtime.registry.provider, AcmeLabsProvider):
            runtime.registry = build_registry(ExecutionMode.ACME_LABS)
            runtime.executor.registry = runtime.registry
            runtime.supervisor.registry = runtime.registry
        elif req.execution_mode == ExecutionMode.LIVE:
            from nexora.providers.live_workspace import LiveWorkspaceProvider
            if not isinstance(runtime.registry.provider, LiveWorkspaceProvider):
                runtime.registry = build_registry(ExecutionMode.LIVE)
                runtime.executor.registry = runtime.registry
                runtime.supervisor.registry = runtime.registry
        # Outcome Contract (ADR-053) & Context Discovery (ADR-055)
        contract_gen = ContractGenerator()
        mission.outcome_contract = await contract_gen.generate(req.goal, mission.intent)
        ctx_svc = ContextDiscoveryService(runtime.registry.provider)
        mission.context_bundle = await ctx_svc.discover(req.goal, mission.outcome_contract)
        mission.state = MissionStateMachine.transition(mission.state, MissionState.PLANNING)
        mission.constitution = ConstitutionBuilder(network, memory).build(mission.mission_id, mission.intent)

        # LIVE requires a connected Google account (OAuth) before any work
        if mission.execution_mode == ExecutionMode.LIVE:
            creds = await LocalCredentialStore().get_google_credentials("default")
            if not creds:
                raise HTTPException(status_code=409,
                                    detail="Google not connected. Open /api/v1/auth/google first.")

        # Mission Workspace (ADR-050): one folder, everything filed inside
        ws = await runtime.registry.provider.ensure_workspace(req.goal)
        mission.workspace_folder_id = ws["folder_id"]
        mission.workspace_uri = ws["uri"]

        # LLM compiler (ADR-051) with deterministic keyword fallback (ADR-031)
        mission.nodes = await llm_compiler.compile(mission.goal, mission.intent,
                                                   mission.constitution, attachment=req.attachment,
                                                   context_bundle=mission.context_bundle,
                                                   outcome_contract=mission.outcome_contract)
        if not mission.nodes:
            mission.nodes = await WorkflowCompiler(network).compile(mission.goal, mission.intent,
                                                                    mission.constitution, attachment=req.attachment,
                                                                    context_bundle=mission.context_bundle,
                                                                    outcome_contract=mission.outcome_contract)

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


@app.post("/internal/reset")
async def reset_all_state():
    if hasattr(repo, "clear"): repo.clear()
    audit.clear(); memory.clear(); bus.clear(); forge.clear()
    if hasattr(registry.provider, "reset_seed"): registry.provider.reset_seed()
    return {"status": "reset"}


@app.post("/api/v1/missions/{mission_id}/approvals/{node_id}")
async def decide_approval(mission_id: str, node_id: str, body: ApprovalRequest):
    mission = await _get_or_404(mission_id)
    node = next((n for n in mission.nodes if n.node_id == node_id), None)
    if node is None or node.status != "WAITING_APPROVAL":
        raise HTTPException(status_code=409, detail="Node not awaiting approval")
    audit.record(AuditEntry(mission_id=mission_id, node_id=node_id,
                            kind=AuditKind.APPROVAL_DECIDED, severity="INFO",
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
        await memory.add(MemoryEntry(type=MemoryType.CORRECTION, scope=MemoryScope.ORG,
                                     content=f"User rejected {node.capability_id}",
                                     capability=node.capability_id, effect="correction",
                                     provenance="approval_rejected"))
        await runtime.handle_failure(mission_id, node_id, "approval_rejected")
    return {"node_id": node_id, "approved": body.approved}


@app.post("/api/v1/missions/{mission_id}/intervene")
async def intervene(mission_id: str, body: InterventionRequest):
    mission = await _get_or_404(mission_id)
    try:
        return await runtime.apply_intervention(mission, body.instruction)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


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


# ---------------- Memory / Teach / Forge / Replay ----------------

@app.post("/api/v1/memory/teach")
async def teach(body: TeachRequest):
    entry = TeachExtractor().extract(body.instruction)
    await memory.add(entry)
    return entry.model_dump(mode="json")

@app.get("/api/v1/memory")
async def list_memory():
    return [e.model_dump(mode="json") for e in await memory.all()]

@app.post("/api/v1/missions/{mission_id}/forge")
async def forge_workflow(mission_id: str):
    mission = await _get_or_404(mission_id)
    if mission.state not in (MissionState.COMPLETED, MissionState.PARTIAL_SUCCESS):
        raise HTTPException(status_code=409, detail="Only completed missions can be forged")
    template = forge.forge(mission)
    await memory.add(MemoryEntry(type=MemoryType.LEARNED_WORKFLOW, scope=MemoryScope.WORKFLOW,
                                 content=template.name, provenance="forge"))
    return template.model_dump(mode="json")

@app.get("/api/v1/workflows")
async def list_workflows():
    return [t.model_dump(mode="json") for t in forge.list()]

@app.post("/api/v1/workflows/{template_id}/run")
async def run_workflow(template_id: str):
    template = forge.get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    mission = Mission(goal=template.name, execution_mode=ExecutionMode.MOCK)
    mission.intent = MissionIntent(objective=template.name)
    mission.constitution = ConstitutionBuilder(network, memory).build(mission.mission_id, mission.intent)
    mission.nodes = forge.build_nodes(template)
    critique = await PlanCritic(network).critique(mission.nodes, mission.constitution)
    if not critique["approved"]:
        raise HTTPException(status_code=400, detail=f"Template rejected: {critique['issues']}")
    mission.state = MissionState.EXECUTING
    await repo.save(mission)
    await bus.publish("MISSION.CREATED", {"mission_id": mission.mission_id, "goal": template.name})
    for node in mission.nodes:
        if not node.depends_on:
            await runtime.dispatch(mission.mission_id, node.node_id)
    return mission.model_dump(mode="json")

@app.post("/api/v1/missions/{mission_id}/replay")
async def replay_mission(mission_id: str):
    src = await _get_or_404(mission_id)
    if src.state not in (MissionState.COMPLETED, MissionState.PARTIAL_SUCCESS, MissionState.FAILED):
        raise HTTPException(status_code=409, detail="Mission not terminal")
    replay_m = Mission(goal=src.goal, execution_mode=ExecutionMode.REPLAY)
    replay_m.intent = src.intent
    if src.constitution:
        replay_m.constitution = src.constitution.model_copy()
    else:
        replay_m.constitution = ConstitutionBuilder(network, memory).build(
            replay_m.mission_id, src.intent or MissionIntent(objective=src.goal))
    idmap = {}
    for n in src.nodes:
        if n.status != "SUCCESS":
            continue
        new = MissionNode(capability_id=n.capability_id, inputs=dict(n.inputs),
                          depends_on=[idmap[d] for d in n.depends_on if d in idmap],
                          rationale_summary=f"Replay of {n.node_id}.")
        idmap[n.node_id] = new.node_id
        replay_m.nodes.append(new)
    replay_m.state = MissionStateMachine.transition(replay_m.state, MissionState.INTERPRETING)
    replay_m.state = MissionStateMachine.transition(replay_m.state, MissionState.PLANNING)
    replay_m.state = MissionStateMachine.transition(replay_m.state, MissionState.CRITICIZING)
    replay_m.state = MissionStateMachine.transition(replay_m.state, MissionState.EXECUTING)
    await repo.save(replay_m)
    rt = MissionRuntime(repo, network, ProviderRegistry(ReplayProvider(src)),
                        bus, firewall, audit, memory)
    for node in replay_m.nodes:
        if not node.depends_on:
            await rt.dispatch(replay_m.mission_id, node.node_id)
    return replay_m.model_dump(mode="json")


# ---------------- Benchmarks (Phase 8) ----------------

@app.get("/api/v1/benchmarks")
async def list_benchmarks():
    return [{"name": b.name, "goal": b.goal, "expected_artifacts": b.expected_artifacts,
             "expected_nodes": b.expected_nodes, "min_evidence": b.min_evidence}
            for b in BENCHMARKS]

@app.post("/api/v1/benchmarks/{benchmark_name}/run")
async def run_benchmark(benchmark_name: str):
    bm = next((b for b in BENCHMARKS if b.name == benchmark_name), None)
    if bm is None:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    old_provider = runtime.registry.provider
    runtime.registry.provider = AcmeLabsProvider()
    try:
        return await create_mission(GoalRequest(goal=bm.goal, execution_mode=ExecutionMode.ACME_LABS))
    finally:
        runtime.registry.provider = old_provider

@app.get("/api/v1/missions/{mission_id}/benchmark")
async def get_benchmark_result(mission_id: str):
    mission = await _get_or_404(mission_id)
    bm = next((b for b in BENCHMARKS if b.goal == mission.goal), None)
    if bm is None:
        raise HTTPException(status_code=404, detail="Mission is not a benchmark")
    return evaluate_mission(mission, bm)


# ---------------- Google OAuth (Phase 9.3) ----------------

REDIRECT_URI = "http://localhost:8000/api/v1/auth/callback"
GOOGLE_SCOPES = [
    "openid", "email", "profile",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",   # <-- ADDED: Read Drive files
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",   # <-- ADDED: Read Gmail
]

@app.get("/api/v1/auth/google")
async def auth_google():
    cid = os.getenv("GOOGLE_CLIENT_ID", "")
    if not cid:
        raise HTTPException(status_code=409,
                            detail="Set GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET in apps/api/.env")
    q = urlencode({"client_id": cid, "redirect_uri": REDIRECT_URI, "response_type": "code",
                   "scope": " ".join(GOOGLE_SCOPES), "access_type": "offline", "prompt": "consent"})
    return RedirectResponse(url=f"https://accounts.google.com/o/oauth2/v2/auth?{q}")

@app.get("/api/v1/auth/callback", response_class=HTMLResponse)
async def auth_callback(code: str, state: str = ""):
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    insecure = os.getenv("NEXORA_INSECURE_TLS", "") == "1"
    
    async with httpx.AsyncClient(verify=not insecure) as c:
        r = await c.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code"})
            
    if r.status_code != 200:
        return HTMLResponse(f"<h2>❌ Token exchange failed</h2><pre>{r.text}</pre>", status_code=400)
        
    token_data = r.json()
    # Bake client ID/Secret into the stored creds so refresh doesn't depend on env vars
    token_data["client_id"] = client_id
    token_data["client_secret"] = client_secret
    
    await LocalCredentialStore().store_google_credentials("default", token_data)
    return HTMLResponse("<h2>✅ Google connected</h2><p>You can close this tab and launch a LIVE mission.</p>")

@app.get("/api/v1/auth/status")
async def auth_status():
    creds = await LocalCredentialStore().get_google_credentials("default")
    return {"connected": bool(creds)}


# ---------------- Read endpoints ----------------

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

@app.get("/api/v1/missions/{mission_id}/contract")
async def get_contract(mission_id: str):
    mission = await _get_or_404(mission_id)
    if mission.outcome_contract is None:
        raise HTTPException(status_code=404, detail="No contract generated")
    # Handle both OutcomeContract instance and plain dict
    if hasattr(mission.outcome_contract, "model_dump"):
        return mission.outcome_contract.model_dump(mode="json")
    return mission.outcome_contract

@app.get("/api/v1/missions/{mission_id}/verification/semantic")
async def get_semantic_verification(mission_id: str):
    mission = await _get_or_404(mission_id)
    if mission.semantic_verification is None:
        raise HTTPException(status_code=404, detail="No semantic verification yet")
    if hasattr(mission.semantic_verification, "model_dump"):
        return mission.semantic_verification.model_dump(mode="json")
    return mission.semantic_verification

@app.get("/api/v1/missions/{mission_id}/context")
async def get_context(mission_id: str):
    mission = await _get_or_404(mission_id)
    if mission.context_bundle is None:
        raise HTTPException(status_code=404, detail="No context discovered")
    if hasattr(mission.context_bundle, "model_dump"):
        return mission.context_bundle.model_dump(mode="json")
    return mission.context_bundle

@app.post("/api/v1/missions/{mission_id}/replan")
async def trigger_adaptive_replan(mission_id: str):
    """Manually trigger adaptive replanning (for demo/testing)."""
    mission = await _get_or_404(mission_id)
    if mission.state not in (MissionState.COMPLETED, MissionState.PARTIAL_SUCCESS):
        raise HTTPException(status_code=409,
                            detail="Adaptive replan only works on terminal missions")
    if not mission.semantic_verification:
        raise HTTPException(status_code=409, detail="No semantic verification yet")
    if mission.semantic_verification.complete:
        return {"status": "already_complete", "replan_triggered": False}
    if mission.replan_count >= 2:
        return {"status": "max_replans_reached", "replan_triggered": False}
    # Re-open the mission for execution
    mission.state = MissionState.EXECUTING
    mission.adaptive_replan_pending = False  # allow supervisor to re-trigger
    await repo.save(mission)
    await runtime.supervisor.check_completion(mission_id)
    return {"status": "replan_triggered", "replan_count": mission.replan_count}


# ---------------- Capability Network ----------------

@app.get("/api/v1/capabilities")
async def list_capabilities():
    return [network.get(cid).model_dump(mode="json") for cid in network.ids()]

@app.get("/api/v1/capabilities/{capability_id}")
async def get_capability(capability_id: str):
    cap = network.get(capability_id)
    if cap is None:
        raise HTTPException(status_code=404, detail="Capability not found")
    return cap.model_dump(mode="json")