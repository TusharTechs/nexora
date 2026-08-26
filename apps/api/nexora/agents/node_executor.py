import uuid
from packages.core.models import MissionNode, MissionConstitution, ExecutionMode
from nexora.core.policy_engine import PolicyEngine
from nexora.core.capability_network import CapabilityNetwork
from nexora.core.security import ContentFirewall
from nexora.core.audit import AuditTrail, AuditEntry, AuditKind
from nexora.providers.protocols import ProviderRegistry


class ApprovalRequiredError(Exception):
    def __init__(self, capability_id: str):
        self.capability_id = capability_id
        super().__init__(f"Approval required for {capability_id}")


class NodeExecutor:
    def __init__(self, policy: PolicyEngine, network: CapabilityNetwork,
                 registry: ProviderRegistry, firewall: ContentFirewall, audit: AuditTrail):
        self.policy = policy
        self.network = network
        self.registry = registry
        self.firewall = firewall
        self.audit = audit

    async def execute(self, mission_id: str, node: MissionNode,
                      constitution: MissionConstitution, mode: ExecutionMode):
        cap = self.network.get(node.capability_id)
        if cap is None:
            raise ValueError(f"Unknown capability {node.capability_id}")

        # Policy decision — deterministic, authoritative
        decision = self.policy.evaluate(node.capability_id, constitution, cap,
                                        extra_params=node.inputs)
        self.audit.record(AuditEntry(
            mission_id=mission_id, node_id=node.node_id, kind=AuditKind.POLICY_DECISION,
            severity="INFO" if decision == "ALLOW" else "WARN",
            title=f"policy:{decision}",
            detail=f"{node.capability_id} → {decision}",
            metadata={"capability": node.capability_id, "decision": decision}))

        if decision == "BLOCK":
            raise PermissionError(f"Policy blocked action: {node.capability_id}")
        if decision == "REQUIRE_APPROVAL" and not node.approved:
            self.audit.record(AuditEntry(
                mission_id=mission_id, node_id=node.node_id,
                kind=AuditKind.APPROVAL_REQUEST, severity="WARN",
                title="approval_required",
                detail=f"{node.capability_id} requires human approval before execution.",
                metadata={"capability": node.capability_id}))
            raise ApprovalRequiredError(node.capability_id)

        provider = self.registry.for_api(cap.required_api)
        artifact = None
        action = node.capability_id

        if node.capability_id == "docs.create":
            artifact = await provider.create_document(mission_id, node.node_id,
                node.inputs.get("title", "Doc"), node.inputs.get("content", ""))
        elif node.capability_id == "gmail.search":
            results = await provider.search_emails(node.inputs.get("query", ""),
                                                   node.inputs.get("max_results", 5))
            # Scan EACH email body for injection payloads (ADR-037)
            scan_results = []
            for msg in results:
                body = msg.get("body") or msg.get("snippet") or ""
                r = self.firewall.scan(body)
                scan_results.append({"id": msg.get("id"), "verdict": r.verdict.value,
                                     "quarantined": r.quarantined,
                                     "matches": [{"pattern_id": m.pattern_id,
                                                  "category": m.category}
                                                 for m in r.matches]})
                if r.quarantined:
                    self.audit.record(AuditEntry(
                        mission_id=mission_id, node_id=node.node_id,
                        kind=AuditKind.FIREWALL_DETECT, severity="ALERT",
                        title="quarantined_payload",
                        detail=r.rationale,
                        metadata={"source_email": msg.get("id"),
                                  "verdict": r.verdict.value,
                                  "quarantined": r.quarantined,
                                  "categories": [m.category for m in r.matches]}))
            node.outputs["search_results"] = results
            node.outputs["search_results_firewall"] = {
                "verdict": max((s["verdict"] for s in scan_results),
                               key=lambda v: {"CLEAN": 0, "SUSPICIOUS": 1, "MALICIOUS": 2}[v]),
                "scanned_count": len(scan_results),
                "quarantined_count": sum(1 for s in scan_results if s["quarantined"]),
                "per_message": scan_results,
            }
            node.firewall_summary = (f"Scanned {len(scan_results)} message(s); "
                                     f"{node.outputs['search_results_firewall']['quarantined_count']} quarantined.")
        elif node.capability_id == "gmail.read":
            msg = await provider.read_email(node.inputs.get("message_id", ""))
            r = self.firewall.scan(msg.get("body", ""))
            node.outputs["email"] = msg
            node.outputs["email_firewall"] = {"verdict": r.verdict.value,
                                              "quarantined": r.quarantined}
            node.firewall_summary = r.safe_summary
        elif node.capability_id == "gmail.send":
            artifact = await provider.send_email(node.inputs.get("to", []),
                                                 node.inputs.get("subject", ""),
                                                 node.inputs.get("body", ""))
        elif node.capability_id == "drive.search":
            files = await provider.search_files(node.inputs.get("query", ""))
            node.outputs["search_results"] = files
        elif node.capability_id == "sheets.create":
            artifact = await provider.create_sheet(mission_id, node.node_id,
                node.inputs.get("title", "Sheet"), node.inputs.get("headers", []))
        elif node.capability_id == "calendar.create_event":
            artifact = await provider.create_event(mission_id, node.node_id,
                node.inputs.get("title", "Meeting"), node.inputs.get("attendees", []))
        else:
            raise ValueError(f"No executor route for {node.capability_id}")

        from packages.core.models import ActionReceipt
        receipt = ActionReceipt(
            mission_id=mission_id, node_id=node.node_id, action=action,
            reason=node.rationale_summary, agent_id="worker", capability_id=node.capability_id,
            policy_decision=decision, model_tier="T1", cost_usd=cap.estimated_cost_usd,
            output_artifact_id=artifact.artifact_id if artifact else None, execution_mode=mode,
        )

        self.audit.record(AuditEntry(
            mission_id=mission_id, node_id=node.node_id, kind=AuditKind.NODE_EXECUTED,
            severity="INFO", title=f"executed:{node.capability_id}",
            detail=f"{node.capability_id} executed with policy={decision}",
            metadata={"capability": node.capability_id, "decision": decision,
                      "artifact_id": artifact.artifact_id if artifact else None}))

        return artifact, receipt