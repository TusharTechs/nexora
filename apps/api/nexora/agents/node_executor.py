import uuid
from packages.core.models import ActionReceipt, Artifact
from nexora.core.audit import AuditEntry, AuditKind
from nexora.core.composer import ArtifactComposer
from nexora.core.personas import persona_for_capability


class ApprovalRequiredError(Exception):
    def __init__(self, capability_id: str):
        self.capability_id = capability_id
        super().__init__(f"Approval required for {capability_id}")


class NodeExecutor:
    def __init__(self, policy, network, registry, firewall, audit, composer=None):
        self.policy = policy
        self.network = network
        self.registry = registry
        self.firewall = firewall
        self.audit = audit
        self.composer = composer or ArtifactComposer()

    @staticmethod
    def _clean_title(raw: str, mission, node) -> str:
        """Turn auto-generated titles ('Report - <goal>', 'Summary - <goal>') into
        a clean deliverable name using the contract's one-line objective."""
        raw = (raw or "").strip()
        junky = (not raw or raw in ("Document", "Doc", "Report", "Summary")
                 or raw.startswith(("Report - ", "Summary - ", "Doc - ", "Tracker - ")))
        if not junky and len(raw) <= 90:
            return raw
        obj = ""
        oc = getattr(mission, "outcome_contract", None) if mission else None
        if oc is not None:
            obj = getattr(oc, "objective", "") or (oc.get("objective", "") if isinstance(oc, dict) else "")
        obj = obj or (mission.intent.objective if mission and mission.intent else "") or raw
        obj = obj.strip().rstrip(".")
        # Prefer a noun phrase: drop leading intent/verb scaffolding.
        for lead in ("i want to ", "i am going to ", "i'm ", "help me ", "please ",
                     "can you ", "create ", "build ", "prepare ", "produce ",
                     "develop ", "generate ", "make ", "a ", "an ", "the "):
            if obj.lower().startswith(lead):
                obj = obj[len(lead):]
        # Cut at the first list separator so we don't title with the whole brief.
        for sep in (" consisting of", " including", " with a", ": ", " — ", " - "):
            i = obj.lower().find(sep)
            if i > 12:
                obj = obj[:i]
        return (obj[:1].upper() + obj[1:]).strip()[:90] or "Deliverable"

    @staticmethod
    def _objective(mission, node) -> str:
        if mission and getattr(mission, "intent", None) and mission.intent.objective:
            return mission.intent.objective
        if mission and getattr(mission, "goal", None):
            return mission.goal
        return node.inputs.get("title") or node.inputs.get("objective") or ""

    # Which contract deliverable does this node produce? Match by capability so the
    # composer writes ONE thing and never restates the deck / sheet / email.
    _CAP_DELIVERABLE_HINTS = {
        "docs.create": ("document", "guide", "doc", "report", "plan", "brief", "write-up", "summary", "itinerary", "roadmap"),
        "docs.update": ("document", "guide", "doc", "report", "plan", "brief"),
        "slides.create": ("slide", "deck", "presentation", "pitch"),
        "sheets.create": ("spreadsheet", "sheet", "budget", "tracker", "table", "breakdown", "model"),
        "sheets.write": ("spreadsheet", "sheet", "budget", "tracker", "table"),
        "gmail.send": ("email", "message", "note", "mail"),
        "gmail.draft": ("email", "draft", "message", "mail"),
        "imagen.generate_image": ("image", "photo", "visual", "picture", "illustration"),
    }

    @classmethod
    def _deliverable_brief(cls, mission, node) -> str:
        """The single contract deliverable this node is responsible for, phrased
        so the composer produces exactly that and nothing else."""
        oc = getattr(mission, "outcome_contract", None) if mission else None
        items = []
        if oc is not None:
            items = getattr(oc, "required_deliverables", None) or (
                oc.get("required_deliverables", []) if isinstance(oc, dict) else [])
        hints = cls._CAP_DELIVERABLE_HINTS.get(node.capability_id, ())
        for d in items:
            if any(h in str(d).lower() for h in hints):
                return str(d)
        # No contract match — fall back to a capability-shaped noun phrase.
        kind = {"docs.create": "document", "docs.update": "document",
                "slides.create": "slide deck", "sheets.create": "spreadsheet",
                "sheets.write": "spreadsheet", "gmail.send": "email",
                "gmail.draft": "email"}.get(node.capability_id, "deliverable")
        obj = cls._objective(mission, node)
        return f"the {kind} for: {obj}" if obj else f"the {kind}"

    @staticmethod
    def _summarize_upstream(mission, node) -> str:
        """Build doc content from upstream search/research outputs (Phase 9)."""
        if mission is None:
            return node.inputs.get("content") or ""

        # Prefer declared deps, but ALWAYS fold in every search/research/analysis
        # output anywhere in the mission — synthesis nodes must never miss evidence
        # just because the planner wired a narrow dependency.
        deps = set(node.depends_on or [])
        dep_nodes = [n for n in mission.nodes if n.node_id in deps]
        evidence_nodes = [n for n in mission.nodes
                          if n.node_id != node.node_id and (
                              n.node_id in deps or
                              n.capability_id in {"gmail.search", "drive.search", "web.research",
                                                  "multimodal.analyze", "sheets.read", "people.search"})]
        sources = dep_nodes + [n for n in evidence_nodes if n not in dep_nodes]
        if not sources:
            sources = [n for n in mission.nodes if n.node_id != node.node_id]

        # Which emails did the firewall quarantine? Never feed those to synthesis.
        quarantined = set()
        for n in mission.nodes:
            fw = (n.outputs or {}).get("search_results_firewall", {})
            for pm in fw.get("per_message", []) or []:
                if pm.get("quarantined"):
                    quarantined.add(pm.get("id"))

        lines = []
        for dep in sources:
            outs = dep.outputs or {}

            # Gmail / Drive search results
            for item in outs.get("search_results", []) or []:
                if item.get("id") in quarantined:
                    continue
                subj = item.get("subject") or item.get("title") or item.get("name") or "Result"
                snip = item.get("snippet") or item.get("body") or ""
                lines.append(f"• {subj}\n  {str(snip)[:300]}")

            # Web research findings
            research = outs.get("research")
            if isinstance(research, dict):
                if research.get("summary"):
                    lines.append(f"• Research summary: {str(research['summary'])[:400]}")
                for f in research.get("findings", []) or []:
                    claim = f.get("claim") or f.get("title") or f.get("url") or "Finding"
                    src = f.get("source_url") or f.get("url") or ""
                    snip = f.get("snippet") or f.get("summary") or ""
                    lines.append(f"• {claim}\n  {str(snip)[:250]}\n  Source: {src}")

            # Vision / screenshot analysis
            analysis = outs.get("analysis")
            if isinstance(analysis, dict) and analysis:
                lines.append(f"• Screenshot analysis: error_code={analysis.get('error_code')} "
                             f"{str(analysis.get('summary') or analysis.get('visual_evidence') or '')[:200]}")

            # Directory lookups
            for p in outs.get("people", []) or []:
                lines.append(f"• Contact: {p.get('name')} <{p.get('email')}> — {p.get('role')}")

            # Spreadsheet reads
            rows = outs.get("rows")
            if isinstance(rows, list) and rows:
                lines.append("• Sheet data: " + "; ".join(str(r) for r in rows[:8]))

            # Single email read
            email = outs.get("email") or {}
            if email and email.get("body"):
                lines.append(f"• Email: {email.get('subject', 'No subject')}\n  {str(email.get('body'))[:300]}")

            # Drive file read
            file_data = outs.get("file") or {}
            if file_data and file_data.get("content"):
                lines.append(f"• File: {file_data.get('title', 'Untitled')}\n  {str(file_data.get('content'))[:300]}")

        # ADR-072: fold in the org-memory entries the ConstitutionBuilder
        # retrieved as relevant to this mission (preferences, policies, past
        # corrections) so every deliverable respects them.
        mem = getattr(getattr(mission, "constitution", None), "relevant_memories", None) or []
        mem_block = ""
        if mem:
            mem_block = ("KNOWN PREFERENCES & FACTS FROM ORGANIZATIONAL MEMORY "
                         "(honour these):\n" + "\n".join(f"• {m}" for m in mem[:6]) + "\n\n")

        if lines:
            title = node.inputs.get("title") or "Summary"
            return mem_block + f"{title}\n\n" + "\n\n".join(lines)
        return mem_block + (node.inputs.get("content")
                            or "No upstream data was available to summarize.")

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
            # ADR-066: Gemini writes the real document body from the persona,
            # the Outcome Contract, and upstream research evidence.
            evidence_text = self._summarize_upstream(mission, node)
            title = self._clean_title(node.inputs.get("title", "Document"), mission, node)
            content = await self.composer.compose_document(
                title=title, objective=self._objective(mission, node),
                deliverable=self._deliverable_brief(mission, node),
                persona=persona_for_capability("docs.create"),
                contract=getattr(mission, "outcome_contract", None) if mission else None,
                evidence_text=evidence_text)
            from nexora.providers.formatting import first_h1
            title = first_h1(content) or title
            node.outputs["content_preview"] = content[:600]
            node.outputs["content_chars"] = len(content)
            artifact = await provider.create_document(mission_id, node.node_id, title, content)

        elif node.capability_id == "gmail.search":
            results = await provider.search_emails(node.inputs.get("query", ""), node.inputs.get("max_results", 5))
            scans = []
            for msg in results:
                body = msg.get("body") or msg.get("snippet") or ""
                r = self.firewall.scan(body)
                gemma = None
                if r.verdict.value == "CLEAN":
                    # ADR-074: Gemma second opinion on what the patterns let through
                    gemma = await self.firewall.classify_gemma(body)
                quarantined = r.quarantined or gemma == "INJECTION"
                scans.append({"id": msg.get("id"), "verdict": ("MALICIOUS" if quarantined else r.verdict.value),
                              "quarantined": quarantined, "gemma": gemma,
                              "matches": [{"pattern_id": m.pattern_id, "category": m.category} for m in r.matches]})
                if quarantined and not r.quarantined:
                    self.audit.record(AuditEntry(mission_id=mission_id, node_id=node.node_id,
                        kind=AuditKind.FIREWALL_DETECT, severity="ALERT", title="quarantined_payload_gemma",
                        detail="Gemma flagged an injection the deterministic patterns missed.",
                        metadata={"source_email": msg.get("id"), "classifier": "gemma"}))
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

        elif node.capability_id in ("gmail.send", "gmail.draft"):
            body = node.inputs.get("body", "")
            subject = node.inputs.get("subject", "")
            _weak_subj = (not subject or subject.startswith(("Update:", "Update -", "Re:", "Status")))
            if not body or body in ("Status update...", "") or _weak_subj:
                composed = await self.composer.compose_email(
                    objective=self._objective(mission, node),
                    deliverable=self._deliverable_brief(mission, node),
                    purpose=node.inputs.get("purpose", "" if _weak_subj else subject),
                    persona=persona_for_capability("gmail.send"),
                    contract=getattr(mission, "outcome_contract", None) if mission else None,
                    evidence_text=self._summarize_upstream(mission, node))
                if not body or body in ("Status update...", ""):
                    body = composed["body_markdown"]
                if _weak_subj:
                    subject = composed["subject"]
                node.inputs["body"], node.inputs["subject"] = body, subject
            to = node.inputs.get("to", [])
            # The goal may name the real recipient(s); the planner only had a placeholder.
            from nexora.core.extractors import emails as _emails
            named = _emails(self._objective(mission, node))
            placeholder = (not to) or any("acme.dev" in str(t) or "example.com" in str(t) for t in to)
            if named and placeholder:
                to = named
            node.inputs["to"] = to
            if node.capability_id == "gmail.send":
                artifact = await provider.send_email(to, subject, body)
            else:
                artifact = await provider.draft_email(to, subject, body)
        elif node.capability_id == "drive.search":
            node.outputs["search_results"] = await provider.search_files(node.inputs.get("query", ""))
        elif node.capability_id == "drive.read":
            node.outputs["file"] = await provider.read_file(node.inputs.get("file_id", ""))
        elif node.capability_id == "drive.create_folder":
            if hasattr(provider, "ensure_workspace"):
                ws = await provider.ensure_workspace(node.inputs.get("title", "NEXORA Folder"))
                node.outputs["folder"] = ws
        elif node.capability_id == "docs.read":
            fid = node.inputs.get("file_id") or node.inputs.get("doc_id") or ""
            try:
                node.outputs["file"] = await provider.read_file(fid) if fid else {"content": ""}
            except Exception:
                node.outputs["file"] = {"content": ""}
        elif node.capability_id == "docs.update":
            # Append composed content to an upstream doc; if none, behaves like docs.create.
            evidence_text = self._summarize_upstream(mission, node)
            title = node.inputs.get("title", "Document")
            content = await self.composer.compose_document(
                title=title, objective=self._objective(mission, node),
                deliverable=self._deliverable_brief(mission, node),
                persona=persona_for_capability("docs.create"),
                contract=getattr(mission, "outcome_contract", None) if mission else None,
                evidence_text=evidence_text)
            node.outputs["content_preview"] = content[:600]
            artifact = await provider.create_document(mission_id, node.node_id, title, content)
        elif node.capability_id == "sheets.write":
            composed = await self.composer.compose_sheet(
                title=node.inputs.get("title", "Spreadsheet"),
                objective=self._objective(mission, node),
                deliverable=self._deliverable_brief(mission, node),
                persona=persona_for_capability("sheets.create"),
                contract=getattr(mission, "outcome_contract", None) if mission else None,
                evidence_text=self._summarize_upstream(mission, node),
                headers=node.inputs.get("headers") or None)
            node.outputs["sheet_rows"] = composed["rows"]
            artifact = await provider.create_sheet(
                mission_id, node.node_id, node.inputs.get("title", "Spreadsheet"),
                composed["headers"], rows=composed["rows"])
        elif node.capability_id in ("calendar.search", "calendar.availability"):
            node.outputs["events"] = []
            node.outputs["available"] = True
        elif node.capability_id == "sheets.create":
            title = self._clean_title(node.inputs.get("title", "Spreadsheet"), mission, node)
            composed = await self.composer.compose_sheet(
                title=title, objective=self._objective(mission, node),
                deliverable=self._deliverable_brief(mission, node),
                persona=persona_for_capability("sheets.create"),
                contract=getattr(mission, "outcome_contract", None) if mission else None,
                evidence_text=self._summarize_upstream(mission, node),
                headers=node.inputs.get("headers") or None)
            node.outputs["sheet_rows"] = composed["rows"]
            artifact = await provider.create_sheet(
                mission_id, node.node_id, title, composed["headers"], rows=composed["rows"])
        elif node.capability_id == "sheets.read":
            node.outputs["rows"] = await provider.read_sheet(node.inputs.get("sheet_id", ""), node.inputs.get("range", ""))
        elif node.capability_id == "calendar.create_event":
            from nexora.core.extractors import emails as _emails, event_datetime as _when
            goal = self._objective(mission, node)
            attendees = [a for a in node.inputs.get("attendees", [])
                         if "acme.dev" not in str(a) and "example.com" not in str(a)]
            attendees = list(dict.fromkeys(attendees + _emails(goal)))
            when = _when(goal)
            title = self._clean_title(node.inputs.get("title", ""), mission, node)
            for junk in ("Sync - ", "Meeting - ", "Call - ", "Sync-", "Meeting:"):
                if title.startswith(junk):
                    title = title[len(junk):]
            title = (title or "Project kickoff sync").strip()[:80]
            desc = (self._summarize_upstream(mission, node) or goal)[:1500]
            artifact = await provider.create_event(
                mission_id, node.node_id, title, attendees,
                start=when.isoformat() if when else None, description=desc)
            node.outputs["event"] = {"title": title, "attendees": attendees,
                                     "start": when.isoformat() if when else "tomorrow 10:00"}
        elif node.capability_id == "tasks.create":
            artifact = await provider.create_task(mission_id, node.node_id, node.inputs.get("title", "Task"), node.inputs.get("notes", ""))
        elif node.capability_id == "slides.create":
            title = self._clean_title(node.inputs.get("title", "Presentation"), mission, node)
            deck = await self.composer.compose_slides(
                title=title, objective=self._objective(mission, node),
                deliverable=self._deliverable_brief(mission, node),
                persona=persona_for_capability("slides.create"),
                contract=getattr(mission, "outcome_contract", None) if mission else None,
                evidence_text=self._summarize_upstream(mission, node))
            node.outputs["slide_count"] = len(deck)
            artifact = await provider.create_slides(mission_id, node.node_id, title, deck)
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
            vp = node.inputs.get("prompt") or await self.composer.compose_media_prompt(
                kind="video", objective=self._objective(mission, node),
                evidence_text=self._summarize_upstream(mission, node))
            node.inputs["prompt"] = vp
            artifact = await provider.generate_video(mission_id, node.node_id, vp)
        elif node.capability_id == "lyria.generate_audio":
            obj = self._objective(mission, node)
            wants_music = any(w in obj.lower() for w in
                              ("music", "jingle", "song", "soundtrack", "theme tune",
                               "background track", "score"))
            kind = "music" if wants_music else "speech"
            ap = node.inputs.get("prompt") or await self.composer.compose_media_prompt(
                kind=("music" if wants_music else "audio"), objective=obj,
                evidence_text=self._summarize_upstream(mission, node))
            node.inputs["prompt"] = ap
            node.inputs["audio_kind"] = kind
            artifact = await provider.generate_audio(mission_id, node.node_id, ap, kind=kind)
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
            ip = node.inputs.get("prompt") or await self.composer.compose_media_prompt(
                kind="image", objective=self._objective(mission, node),
                evidence_text=self._summarize_upstream(mission, node))
            node.inputs["prompt"] = ip
            artifact = await provider.generate_image(mission_id, node.node_id, ip)
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