"""Deterministic natural-language intervention parser (ADR-042).

Phase 5 supports a sealed verb set. Unknown instructions are ignored safely
(no-op) rather than guessed at. LLM interpretation is a later seam.
"""
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class InterventionPlan:
    forbid_actions: List[str] = field(default_factory=list)
    remove_entities: List[str] = field(default_factory=list)
    fallbacks: List[str] = field(default_factory=list)      # capabilities to invalidate+replace
    add_capabilities: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.forbid_actions or self.remove_entities
                    or self.fallbacks or self.add_capabilities)


class InterventionHandler:
    def parse(self, instruction: str) -> InterventionPlan:
        text = instruction.lower().strip()
        plan = InterventionPlan()

        if "stop all external" in text or "no external" in text or "stop external" in text:
            plan.forbid_actions.append("gmail.send")
            plan.fallbacks.append("gmail.send")

        m = re.search(r"don'?t involve (\S+)", text) or re.search(r"\bremove (\S+)", text)
        if m:
            plan.remove_entities.append(m.group(1).rstrip(".,;"))

        if "add a tracker sheet" in text or "add a sheet" in text or "add a spreadsheet" in text:
            plan.add_capabilities.append("sheets.create")
        if "add a task" in text or "create a task" in text:
            plan.add_capabilities.append("tasks.create")

        return plan