from nexora.core.personas import (
    persona_for_capability, RESEARCH_ANALYST, FINANCIAL_ANALYST, WRITER,
    COORDINATOR, DESIGNER, DEFAULT_PERSONA, all_personas,
)


def test_capability_maps_to_research_analyst():
    p = persona_for_capability("web.research")
    assert p is RESEARCH_ANALYST
    assert "Research Analyst" in p.system_prompt()


def test_capability_maps_to_financial_analyst():
    p = persona_for_capability("sheets.create")
    assert p is FINANCIAL_ANALYST


def test_capability_maps_to_writer():
    p = persona_for_capability("docs.create")
    assert p is WRITER


def test_capability_maps_to_coordinator():
    p = persona_for_capability("calendar.create_event")
    assert p is COORDINATOR


def test_capability_maps_to_designer():
    p = persona_for_capability("slides.create")
    assert p is DESIGNER


def test_unknown_capability_gets_default():
    p = persona_for_capability("unknown.thing")
    assert p is DEFAULT_PERSONA


def test_persona_system_prompt_contains_role():
    p = persona_for_capability("web.research")
    prompt = p.system_prompt()
    assert "Research Analyst" in prompt
    assert "Objective" in prompt
    assert "citation" in prompt.lower()


def test_all_personas_have_nonempty_prompts():
    for name, p in all_personas().items():
        assert p.system_prompt(), f"Persona {name} has empty prompt"
        assert p.role
        assert p.objective


def test_persona_to_dict_roundtrip():
    p = persona_for_capability("docs.create")
    d = p.to_dict()
    assert d["role"] == "Writer"
    assert "structure" in d["quality_criteria"].lower()