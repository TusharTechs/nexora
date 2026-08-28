import uuid
from packages.core.models import MissionNode, MissionConstitution, ExecutionMode, ActionReceipt, Artifact
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
    def __init__(self, policy, network, registry, firewall, audit):
        self.policy = policy
        self.network = network
        self.registry = registry
        self.firewall = firewall
        self.audit = audit

    def _summarize_upstream(self, mission, node) -> str:
        """Build doc content from upstream search/research outputs (Phase 9)."""
        if mission is None:
            return node.inputs.get("content") or ""

        # Use declared deps; if none, scan all other nodes for data
        deps = node.depends_on or []
        sources = [n for n in mission.nodes if n.node_id in deps]
        if not sources:
            sources = [n for n in mission.nodes if n.node_id != node.node_id]

        lines = []
        for dep in sources:
            outs = dep.outputs or {}

            # Gmail / Drive search results
            for item in outs.get("search_results", []) or []:
                subj = item.get("subject") or item.get("title") or item.get("name") or "Result"
                snip = item.get("snippet") or item.get("body") or ""
                lines.append(f"• {subj}\n  {str(snip)[:300]}")

            # Web research findings
            research = outs.get("research")
            if isinstance(research, dict):
                for f in research.get("findings", []) or []:
                    title = f.get("title") or f.get("url") or "Finding"
                    snip = f.get("snippet") or f.get("summary") or ""
                    lines.append(f"• {title}\n  {str(snip)[:300]}")

            # Single email read
            email = outs.get("email") or {}
            if email and email.get("body"):
                lines.append(f"• Email: {email.get('subject', 'No subject')}\n  {str(email.get('body'))[:300]}")

            # Drive file read
            file_data = outs.get("file") or {}
            if file_data and file_data.get("content"):
                lines.append(f"• File: {file_data.get('title', 'Untitled')}\n  {str(file_data.get('content'))[:300]}")

        if lines:
            title = node.inputs.get("title") or "Summary"
            return f"{title}\n\n" + "\n\n".join(lines)
        return node.inputs.get("content") or "No upstream data was available to summarize."

    async def execute(self, mission_id, node, constitution, mode, mission=None):
        cap = self.network.get(node.capability_id)
        if cap is None:
            raise ValueError(f"Unknown capability {node.capability_id}")

        decision = self.policy.evaluate(node.capability_id, constitution, cap, extra_params=node.inputs)
        self.audit.record(AuditEntry(mission_id=mission_id, node_id=node.node_id,
                                     kind=AuditKind.POLICY_DECISION,
                                     severity="INFO" if decision == "ALLOW" else "WARN",
                                     title=f"policy:{decision}",
                                     detail=f"{node.capability_id} → {decision}",
                                     metadata={"capability": node.capability_id, "decision": decision}))
        if decision == "BLOCK":
            raise PermissionError(f"Policy blocked action: {node.capability_id}")
        if decision == "REQUIRE_APPROVAL" and not node.approved:
            self.audit.record(AuditEntry(mission_id=mission_id, node_id=node.node_id,
                                         kind=AuditKind.APPROVAL_REQUEST, severity="WARN",
                                         title="approval_required",
                                         detail=f"{node.capability_id} requires human approval.",
                                         metadata={"capability": node.capability_id}))
            raise ApprovalRequiredError(node.capability_id)

        provider = self.registry.for_api(cap.required_api)
        artifact = None
        action = node.capability_id

        if node.capability_id == "docs.create":
            # Phase 9: enrich doc content from upstream search/research outputs
            content = self._summarize_upstream(mission, node)
            artifact = await provider.create_document(mission_id, node.node_id,
                node.inputs.get("title", "Doc"), content)

        elif node.capability_id == "gmail.search":
            results = await provider.search_emails(node.inputs.get("query", ""), node.inputs.get("max_results", 5))
            scans = []
            for msg in results:
                body = msg.get("body") or msg.get("snippet") or ""
                r = self.firewall.scan(body)
                scans.append({"id": msg.get("id"), "verdict": r.verdict.value, "quarantined": r.quarantined,
                              "matches": [{"pattern_id": m.pattern_id, "category": m.category} for m in r.matches]})
                if r.quarantined:
                    self.audit.record(AuditEntry(mission_id=mission_id, node_id=node.node_id,
                        kind=AuditKind.FIREWALL_DETECT, severity="ALERT", title="quarantined_payload",
                        detail=r.rationale,
                        metadata={"source_email": msg.get("id"), "verdict": r.verdict.value,
                                  "quarantined": r.quarantined,
                                  "categories": [m.category for m in r.matches]}))
            node.outputs["search_results"] = results

            # Phase 9: handle empty results gracefully (fixes max() on empty)
            if scans:
                verdict_scores = {"CLEAN": 0, "SUSPICIOUS": 1, "MALICIOUS": 2}
                worst_verdict = max((s["verdict"] for s in scans), key=lambda v: verdict_scores.get(v, 0))
            else:
                worst_verdict = "CLEAN"

            node.outputs["search_results_firewall"] = {
                "verdict": worst_verdict,
                "scanned_count": len(scans),
                "quarantined_count": sum(1 for s in scans if s["quarantined"]),
                "per_message": scans}
            node.firewall_summary = (f"Scanned {len(scans)} message(s); "
                                     f"{node.outputs['search_results_firewall']['quarantined_count']} quarantined.")

        elif node.capability_id == "gmail.read":
            # Phase 9: graceful handling when message_id missing — pass-through
            msg_id = node.inputs.get("message_id", "")
            if not msg_id:
                node.outputs["email"] = {"body": "(No specific message ID — using upstream search results)"}
                node.outputs["email_firewall"] = {"verdict": "CLEAN", "quarantined": False}
                node.firewall_summary = "Pass-through: no message_id provided."
            else:
                try:
                    msg = await provider.read_email(msg_id)
                    r = self.firewall.scan(msg.get("body", ""))
                    node.outputs["email"] = msg
                    node.outputs["email_firewall"] = {"verdict": r.verdict.value, "quarantined": r.quarantined}
                    node.firewall_summary = r.safe_summary
                except Exception as e:
                    node.outputs["email"] = {"body": f"(Read failed: {e})"}
                    node.outputs["email_firewall"] = {"verdict": "CLEAN", "quarantined": False}
                    node.firewall_summary = f"Read failed gracefully: {e}"

        elif node.capability_id == "gmail.send":
            artifact = await provider.send_email(node.inputs.get("to", []), node.inputs.get("subject", ""), node.inputs.get("body", ""))
        elif node.capability_id == "gmail.draft":
            artifact = await provider.draft_email(node.inputs.get("to", []), node.inputs.get("subject", ""), node.inputs.get("body", ""))
        elif node.capability_id == "drive.search":
            node.outputs["search_results"] = await provider.search_files(node.inputs.get("query", ""))
        elif node.capability_id == "drive.read":
            node.outputs["file"] = await provider.read_file(node.inputs.get("file_id", ""))
        elif node.capability_id == "sheets.create":
            artifact = await provider.create_sheet(mission_id, node.node_id, node.inputs.get("title", "Sheet"), node.inputs.get("headers", []))
        elif node.capability_id == "sheets.read":
            node.outputs["rows"] = await provider.read_sheet(node.inputs.get("sheet_id", ""), node.inputs.get("range", ""))
        elif node.capability_id == "calendar.create_event":
            artifact = await provider.create_event(mission_id, node.node_id, node.inputs.get("title", "Meeting"), node.inputs.get("attendees", []))
        elif node.capability_id == "tasks.create":
            artifact = await provider.create_task(mission_id, node.node_id, node.inputs.get("title", "Task"), node.inputs.get("notes", ""))
        elif node.capability_id == "slides.create":
            artifact = await provider.create_slides(mission_id, node.node_id, node.inputs.get("title", "Deck"), node.inputs.get("slides", []))
        elif node.capability_id == "chat.notify":
            artifact = await provider.send_chat(node.inputs.get("space", "general"), node.inputs.get("text", ""))
        elif node.capability_id == "people.search":
            node.outputs["people"] = await provider.search_people(node.inputs.get("query", ""))
        elif node.capability_id == "forms.create":
            artifact = await provider.create_form(mission_id, node.node_id, node.inputs.get("title", "Form"), node.inputs.get("questions", []))
        elif node.capability_id == "multimodal.analyze":
            result = await provider.analyze_attachment(mission_id, node.node_id, node.inputs.get("attachment"))
            node.outputs["analysis"] = {k: v for k, v in result.items() if k != "artifact"}
            artifact = result["artifact"]
            node.rationale_summary += f" [extracted error_code={result['error_code']}]"
        elif node.capability_id == "veo.generate_video":
            artifact = await provider.generate_video(mission_id, node.node_id, node.inputs.get("prompt", ""))
        elif node.capability_id == "lyria.generate_audio":
            artifact = await provider.generate_audio(mission_id, node.node_id, node.inputs.get("prompt", ""))
        elif node.capability_id == "web.research":
            result_dict = await provider.web_research(
                node.inputs.get("objective", node.inputs.get("query", "")),
                node.inputs.get("max_results", 5))
            node.outputs["research"] = result_dict
            artifact = Artifact(
                artifact_id=str(uuid.uuid4()),
                mission_id=mission_id,
                node_id=node.node_id,
                type="RESEARCH",
                provider="web",
                resource_id=f"research_{node.node_id}",
                uri=f"research://findings/{node.node_id}",
            )
            node.rationale_summary += f" [found {result_dict.get('sources_cited', 0)} cited findings]"
        elif node.capability_id == "imagen.generate_image":
            artifact = await provider.generate_image(mission_id, node.node_id, node.inputs.get("prompt", ""))
            node.rationale_summary += " [image generated]"
        else:
            raise ValueError(f"No executor route for {node.capability_id}")

        receipt = ActionReceipt(
            mission_id=mission_id, node_id=node.node_id, action=action,
            reason=node.rationale_summary, agent_id="worker", capability_id=node.capability_id,
            policy_decision=decision, model_tier="T2" if node.capability_id == "multimodal.analyze" else "T1",
            cost_usd=cap.estimated_cost_usd,
            output_artifact_id=artifact.artifact_id if artifact else None, execution_mode=mode)

        self.audit.record(AuditEntry(mission_id=mission_id, node_id=node.node_id,
                                     kind=AuditKind.NODE_EXECUTED, severity="INFO",
                                     title=f"executed:{node.capability_id}",
                                     detail=f"{node.capability_id} executed with policy={decision}",
                                     metadata={"capability": node.capability_id, "decision": decision,
                                               "artifact_id": artifact.artifact_id if artifact else None}))
        return artifact, receipt