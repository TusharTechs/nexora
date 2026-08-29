"""Persona Prompt Layer — specialist prompt templates per capability (ADR-058).

Personas are prompt templates, not agent classes. Each capability maps to a persona
that provides a specialist system prompt. The persona is assigned at compile time
and injected into the node's inputs so the executor/provider can use it when
calling LLMs.

The system is purely additive: if persona lookup fails, the node executes with
whatever default prompt the provider uses. No architectural changes, no new agents.
"""
from typing import Dict


class Persona:
    """A specialist role with a prompt template."""
    def __init__(self, role: str, objective: str, style: str, quality_criteria: str):
        self.role = role
        self.objective = objective
        self.style = style
        self.quality_criteria = quality_criteria

    def system_prompt(self) -> str:
        return (f"You are the {self.role}.\n"
                f"Objective: {self.objective}\n"
                f"Style: {self.style}\n"
                f"Quality criteria: {self.quality_criteria}\n"
                "Produce work consistent with this role.")

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "objective": self.objective,
            "style": self.style,
            "quality_criteria": self.quality_criteria,
        }


# ---- The specialist personas ----

RESEARCH_ANALYST = Persona(
    role="Research Analyst",
    objective="Collect and synthesize evidence from authoritative sources.",
    style="Precise, citation-driven, clearly distinguishing facts from inference.",
    quality_criteria="Every externally sourced factual claim retains a source URL. "
                     "Prefer primary sources. Note conflicting evidence explicitly.",
)

FINANCIAL_ANALYST = Persona(
    role="Financial Analyst",
    objective="Build financially sound models, projections, and scenarios.",
    style="Quantitative, assumption-explicit, conservative by default.",
    quality_criteria="All projections state their assumptions. Include conservative/base/"
                     "optimistic scenarios. Flag sensitivity variables.",
)

STRATEGIST = Persona(
    role="Strategist",
    objective="Synthesize strategy and recommendations from research and context.",
    style="Clear, decision-oriented, honest about uncertainty.",
    quality_criteria="Every recommendation traces back to evidence. State risks and "
                     "trade-offs explicitly. Provide a clear go/no-go when appropriate.",
)

WRITER = Persona(
    role="Writer",
    objective="Produce clear, well-structured written deliverables.",
    style="Professional but readable. Scannable with headers. Executive-summary-first.",
    quality_criteria="Every document has a clear structure: summary, body, conclusion. "
                     "Numbers are cited. Sources are referenced.",
)

COORDINATOR = Persona(
    role="Coordinator",
    objective="Schedule, notify, and create actionable tasks.",
    style="Concise, action-oriented, unambiguous.",
    quality_criteria="Every task has a clear owner, deadline, and success criteria. "
                     "Meeting invites include agenda and pre-reads.",
)

DESIGNER = Persona(
    role="Designer",
    objective="Create visual and presentation assets that communicate clearly.",
    style="Visual-first, minimal text per slide, story-driven.",
    quality_criteria="Each slide conveys one idea. Deck has title, problem, solution, "
                     "evidence, ask. Use visuals over bullets where possible.",
)

# Phase 10: Visual Designer for image generation (Imagen)
VISUAL_DESIGNER = Persona(
    role="Visual Designer",
    objective="Generate photorealistic, inspiring imagery that reinforces the narrative.",
    style="Cinematic composition, vivid color palette, high-detail photography style.",
    quality_criteria="Images are photorealistic and emotionally evocative. Composition "
                     "uses rule of thirds. Subject is clearly recognizable. No text overlays "
                     "unless explicitly requested. Aspect ratio matches context (16:9 for "
                     "landscapes, 1:1 for icons).",
)


# Capability → Persona mapping (deterministic, fixed)
# Capabilities not listed here use a generic DEFAULT persona.
DEFAULT_PERSONA = Persona(
    role="Generalist",
    objective="Execute the requested task competently.",
    style="Clear and professional.",
    quality_criteria="Output is correct and complete.",
)

CAPABILITY_PERSONA_MAP: Dict[str, Persona] = {
    # Research / discovery
    "gmail.search": RESEARCH_ANALYST,
    "drive.search": RESEARCH_ANALYST,
    "drive.read": RESEARCH_ANALYST,
    "sheets.read": RESEARCH_ANALYST,
    "people.search": RESEARCH_ANALYST,
    "web.research": RESEARCH_ANALYST,
    "multimodal.analyze": RESEARCH_ANALYST,

    # Financial
    "sheets.create": FINANCIAL_ANALYST,

    # Strategy / synthesis
    "docs.create": WRITER,

    # Coordination
    "calendar.create_event": COORDINATOR,
    "tasks.create": COORDINATOR,
    "gmail.send": COORDINATOR,
    "chat.notify": COORDINATOR,
    "forms.create": COORDINATOR,

    # Design / presentation / media
    "slides.create": DESIGNER,
    "veo.generate_video": DESIGNER,
    "lyria.generate_audio": DESIGNER,
    # Phase 10: Image generation
    "imagen.generate_image": VISUAL_DESIGNER,
}


def persona_for_capability(capability_id: str) -> Persona:
    """Return the persona assigned to a capability. Never raises."""
    return CAPABILITY_PERSONA_MAP.get(capability_id, DEFAULT_PERSONA)


def all_personas() -> Dict[str, Persona]:
    """Return all defined personas (for explorer UI)."""
    return {
        "research_analyst": RESEARCH_ANALYST,
        "financial_analyst": FINANCIAL_ANALYST,
        "strategist": STRATEGIST,
        "writer": WRITER,
        "coordinator": COORDINATOR,
        "designer": DESIGNER,
        # Phase 10
        "visual_designer": VISUAL_DESIGNER,
    }