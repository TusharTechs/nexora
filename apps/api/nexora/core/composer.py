"""Artifact Composer — turns a plan node into real, content-rich deliverables (ADR-066).

NEXORA's earlier providers created *structurally* valid artifacts (a Doc exists, a
Sheet exists) but their content was boilerplate. The Composer closes that gap: it
uses Gemini (through the Unified LLM Client) plus the node's persona, the Outcome
Contract, and the evidence gathered by upstream research nodes to write the actual
document body, slide outline, or spreadsheet rows.

It is provider-agnostic — MOCK stores the composed content, LIVE writes it into the
real Google file. Both therefore produce the same substantive work.

Every method degrades gracefully: if no LLM backend is configured (or the call
fails / returns junk) it returns a sensible non-empty structure so the mission
never hard-fails at composition.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from nexora.core.personas import Persona, persona_for_capability


def _contract_text(contract) -> str:
    if contract is None:
        return ""
    if hasattr(contract, "to_human_summary"):
        return contract.to_human_summary()
    if isinstance(contract, dict):
        parts = [f"Objective: {contract.get('objective', '')}"]
        for k in ("success_criteria", "required_deliverables", "required_evidence", "constraints"):
            vals = contract.get(k) or []
            if vals:
                parts.append(f"{k}: " + "; ".join(str(v) for v in vals))
        return "\n".join(parts)
    return str(contract)


def _extract_json(text: str):
    """Pull the first JSON object/array out of an LLM response."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.S)
    raw = fenced.group(1) if fenced else None
    if raw is None:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        raw = m.group(1) if m else None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


class ArtifactComposer:
    def __init__(self, call_fn=None, model: Optional[str] = None):
        self.call_fn = call_fn  # test seam
        self.model = model or os.getenv("NEXORA_MODEL_T2", "gemini-3.5-flash")

    # ---------------- transport ----------------
    def _persona_parts(self, persona: Optional[Persona | str]) -> tuple[str, str]:
        """Return (role, instruction) for the persona."""
        if isinstance(persona, Persona):
            return persona.role, persona.system_prompt()
        if isinstance(persona, str) and persona:
            return persona, f"You are the {persona}. Produce work consistent with that role."
        return "Specialist", "You are a senior specialist. Produce correct, complete work."

    async def _call(self, task: str, persona: Optional[Persona | str] = None) -> Optional[str]:
        """Reason about `task` as `persona`. ADK agent first, then Unified LLM
        Client, then None (caller uses a deterministic fallback)."""
        role, instruction = self._persona_parts(persona)
        if self.call_fn:
            return self.call_fn(f"{instruction}\n\n{task}")

        from nexora.core.adk_runtime import try_run_agent
        adk_text = await try_run_agent(role=role, instruction=instruction, task=task)
        if adk_text and adk_text.strip():
            return adk_text

        from nexora.core.llm_client import llm_available, llm_generate
        if not llm_available():
            return None
        try:
            return await llm_generate(f"{instruction}\n\n{task}",
                                      temperature=0.4, model=self.model)
        except Exception:
            return None

    # ---------------- document ----------------
    async def compose_document(self, *, title: str, objective: str,
                               persona: Optional[Persona | str] = None,
                               contract=None, evidence_text: str = "") -> str:
        prompt = (
            f"Write the FULL body of ONE deliverable: \"{title}\".\n"
            f"User goal: {objective}\n\n"
            f"What success looks like:\n{_contract_text(contract)}\n\n"
            + ("MATERIAL RETRIEVED FROM THE USER'S OWN WORKSPACE (emails, files, "
               "calendar) AND FROM THE WEB — this is real, already-fetched data; "
               "treat it as ground truth and never claim you lack access to it:\n"
               f"{evidence_text}\n\n" if evidence_text else
               "No upstream data was needed — rely on well-established knowledge.\n\n")
            + "Requirements:\n"
            "- Return GitHub-flavored Markdown only. No code fences, no preamble.\n"
            "- The FIRST line is a single `# ` H1 title for this document.\n"
            "- Then a one-paragraph executive summary, then `## ` sections.\n"
            "- Short paragraphs and `- ` bullet lists. Use `**bold**` for key terms.\n"
            "- NO image syntax, NO markdown links — write URLs/sources as plain text.\n"
            "- Write ONLY this document. Do NOT describe or restate the other "
            "deliverables (the slide deck, the spreadsheet) — they are produced separately.\n"
            "- Be concrete: real names, numbers, steps, trade-offs. If the goal implies "
            "an itinerary/schedule/plan, include a day-by-day or step-by-step section.\n"
            "- Ground every specific claim in the material above or well-established "
            "knowledge; do not fabricate numbers or quotes, and do not add disclaimers "
            "about data access or tool limitations.\n"
            "- 450-900 words."
        )
        text = await self._call(prompt, persona)
        if text and len(text.strip()) > 120:
            return text.strip()
        return self._fallback_document(title, objective, contract, evidence_text)

    def _fallback_document(self, title, objective, contract, evidence_text) -> str:
        lines = [f"# {title}", "",
                 f"**Goal:** {objective}", "",
                 "## Executive summary", "",
                 "This document was assembled from the evidence collected during the mission. "
                 "A language model was not available to expand it further.", ""]
        ct = _contract_text(contract)
        if ct:
            lines += ["## Success criteria", "", ct, ""]
        if evidence_text:
            lines += ["## Findings", "", evidence_text, ""]
        return "\n".join(lines)

    # ---------------- slides ----------------
    async def compose_slides(self, *, title: str, objective: str,
                             persona: Optional[Persona | str] = None,
                             contract=None, evidence_text: str = "") -> List[Dict[str, Any]]:
        prompt = (
            f"Design a concise slide deck titled \"{title}\".\n"
            f"User goal: {objective}\n\n"
            f"What success looks like:\n{_contract_text(contract)}\n\n"
            f"Evidence gathered so far:\n{evidence_text or '(rely on well-established knowledge)'}\n\n"
            "Return ONLY JSON: a list of 5-9 slides, each "
            '{"title": "...", "bullets": ["...", "..."]}.\n'
            "Rules: first slide is a title/agenda slide; one idea per slide; "
            "3-5 short bullets per slide; concrete details, not filler; "
            "last slide is 'Next steps' with actionable items."
        )
        data = _extract_json(await self._call(prompt, persona) or "")
        slides: List[Dict[str, Any]] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("title"):
                    bullets = item.get("bullets") or []
                    slides.append({"title": str(item["title"]),
                                   "bullets": [str(b) for b in bullets][:6]})
        if slides:
            return slides
        return self._fallback_slides(title, objective, evidence_text)

    def _fallback_slides(self, title, objective, evidence_text) -> List[Dict[str, Any]]:
        deck = [{"title": title, "bullets": [objective]}]
        if evidence_text:
            chunks = [c.strip("• ").strip() for c in evidence_text.split("\n") if c.strip()][:5]
            deck.append({"title": "Key findings", "bullets": chunks or ["See mission evidence"]})
        deck.append({"title": "Next steps", "bullets": ["Review the accompanying document",
                                                        "Confirm the budget", "Schedule follow-up"]})
        return deck

    # ---------------- sheet ----------------
    async def compose_sheet(self, *, title: str, objective: str,
                            persona: Optional[Persona | str] = None,
                            contract=None, evidence_text: str = "",
                            headers: Optional[List[str]] = None) -> Dict[str, Any]:
        prompt = (
            f"Build the data for a spreadsheet titled \"{title}\".\n"
            f"User goal: {objective}\n\n"
            f"What success looks like:\n{_contract_text(contract)}\n\n"
            f"Evidence gathered so far:\n{evidence_text or '(use realistic, clearly-labelled estimates)'}\n\n"
            "Return ONLY JSON: {\"headers\": [...], \"rows\": [[...], ...], \"notes\": \"...\"}.\n"
            "Rules: pick columns that fit the goal (for a budget: Category, Item, "
            "Estimated Cost (USD), Notes). 6-20 rows of real, specific line items. "
            "Include a final TOTAL row where it makes sense. Numbers must be plausible "
            "and internally consistent."
        )
        data = _extract_json(await self._call(prompt, persona) or "")
        if isinstance(data, dict) and data.get("headers") and isinstance(data.get("rows"), list):
            hdrs = [str(h) for h in data["headers"]]
            rows = [[("" if c is None else str(c)) for c in r]
                    for r in data["rows"] if isinstance(r, list)]
            if rows:
                return {"headers": hdrs, "rows": rows, "notes": str(data.get("notes", ""))}
        return self._fallback_sheet(title, objective, headers, evidence_text)

    def _fallback_sheet(self, title, objective, headers, evidence_text) -> Dict[str, Any]:
        hdrs = headers or ["Category", "Item", "Estimated Cost (USD)", "Notes"]
        rows = [
            ["Accommodation", "Hotel (1 night)", "220", "Mid-range, central location"],
            ["Food", "Meals (1 day)", "80", "3 meals, casual dining"],
            ["Transport", "Local transit / rideshare", "40", "Day pass + short trips"],
            ["Activities", "Attractions & admissions", "90", "2-3 paid attractions"],
            ["Misc", "Contingency", "50", "Buffer for extras"],
            ["TOTAL", "", "480", "Per person, single day"],
        ]
        return {"headers": hdrs, "rows": rows, "notes": "Fallback estimate — LLM unavailable."}

    # ---------------- email ----------------
    async def compose_email(self, *, objective: str, purpose: str = "",
                            persona: Optional[Persona | str] = None,
                            contract=None, evidence_text: str = "") -> Dict[str, str]:
        prompt = (
            f"Draft a professional email that advances this goal:\n{objective}\n"
            + (f"Specific purpose of this email: {purpose}\n" if purpose else "")
            + f"\nContext / findings:\n{evidence_text or '(rely on the goal)'}\n\n"
            "Return ONLY JSON: {\"subject\": \"...\", \"body_markdown\": \"...\"}.\n"
            "Rules: subject under 80 chars; body is tight Markdown with a greeting, "
            "2-4 short paragraphs or a short bullet list, and a clear ask or next step; "
            "no placeholders like [Name] unless truly unknown; sign off as 'NEXORA'."
        )
        data = _extract_json(await self._call(prompt, persona or "Coordinator") or "")
        if isinstance(data, dict) and data.get("body_markdown"):
            return {"subject": str(data.get("subject") or objective)[:120],
                    "body_markdown": str(data["body_markdown"])}
        return {"subject": (purpose or objective)[:120],
                "body_markdown": (f"Hi,\n\n{evidence_text or objective}\n\n"
                                  "Best,\nNEXORA")}

    # ---------------- media prompts ----------------
    async def compose_media_prompt(self, *, kind: str, objective: str,
                                   evidence_text: str = "") -> str:
        """kind: 'image' | 'video' | 'audio' — returns a rich generation prompt."""
        instructions = {
            "image": "a single photorealistic, editorial-quality still image (16:9)",
            "video": "a short 6-8 second cinematic establishing video clip",
            "audio": "a 30-45 second spoken narration script for an audio briefing",
        }.get(kind, "a visual asset")
        prompt = (
            f"Write a production-ready generation prompt for {instructions} that supports this goal:\n"
            f"{objective}\n\n"
            f"Context / findings:\n{evidence_text[:1500]}\n\n"
            "Return ONLY the prompt text itself — vivid, specific, one paragraph, no preamble."
        )
        text = await self._call(prompt, "Visual Designer")
        if text and text.strip():
            return text.strip().strip('"')
        if kind == "audio":
            return f"A concise, warm spoken briefing summarizing the key points for: {objective}"
        return f"Photorealistic, vibrant, editorial photograph representing: {objective}"


def evidence_from_mission(mission, node) -> str:
    """Reuse the executor's upstream-summary logic (static, no circular state)."""
    from nexora.agents.node_executor import NodeExecutor
    try:
        return NodeExecutor._summarize_upstream(mission, node)
    except Exception:
        return ""
