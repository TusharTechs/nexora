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
