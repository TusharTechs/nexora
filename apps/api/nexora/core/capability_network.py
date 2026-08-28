from typing import Dict, List, Optional
from packages.core.models import Capability, RiskLevel, ApprovalRequirement, ExecutionMode

ALL_MODES = [ExecutionMode.LIVE, ExecutionMode.MOCK, ExecutionMode.REPLAY, ExecutionMode.SIMULATION]

class CapabilityNetwork:
    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._register_defaults()

    def _add(self, cid, name, api, risk, approval, cost, latency, reversible, desc):
        self.register(Capability(
            capability_id=cid, name=name, description=desc, provider="google",
            required_api=api, risk_level=risk, estimated_cost_usd=cost,
            estimated_latency_ms=latency, reversible=reversible,
            approval_requirement=approval, execution_mode_support=ALL_MODES,
        ))

    def _register_defaults(self):
        self._add("gmail.search", "Search Emails", "gmail", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0005, 800, False, "Search Gmail messages.")
        self._add("gmail.read", "Read Email", "gmail", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0002, 300, False, "Read a single Gmail message.")
        self._add("gmail.draft", "Draft Email", "gmail", RiskLevel.MEDIUM, ApprovalRequirement.NONE, 0.0005, 600, True, "Create a Gmail draft.")
        self._add("gmail.send", "Send Email", "gmail", RiskLevel.HIGH, ApprovalRequirement.ALWAYS, 0.0005, 900, False, "Send an email. Always requires human approval.")
        self._add("drive.search", "Search Drive", "drive", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0005, 800, False, "Search Drive files.")
        self._add("drive.read", "Read Drive File", "drive", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0002, 400, False, "Read file content.")
        self._add("drive.create_folder", "Create Folder", "drive", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0005, 600, True, "Create a Drive folder.")
        self._add("docs.create", "Create Google Doc", "docs", RiskLevel.LOW, ApprovalRequirement.NONE, 0.001, 1500, True, "Create a Google Document.")
        self._add("docs.read", "Read Doc", "docs", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0002, 400, False, "Read document text.")
        self._add("docs.update", "Update Doc", "docs", RiskLevel.MEDIUM, ApprovalRequirement.NONE, 0.0008, 900, True, "Append/update document.")
        self._add("sheets.create", "Create Spreadsheet", "sheets", RiskLevel.LOW, ApprovalRequirement.NONE, 0.001, 1200, True, "Create a Google Sheet.")
        self._add("sheets.read", "Read Sheet", "sheets", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0002, 400, False, "Read sheet values.")
        self._add("sheets.write", "Write Sheet", "sheets", RiskLevel.MEDIUM, ApprovalRequirement.NONE, 0.0008, 800, True, "Write sheet values.")
        self._add("calendar.search", "Search Events", "calendar", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0005, 600, False, "Search calendar events.")
        self._add("calendar.availability", "Check Availability", "calendar", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0005, 700, False, "Check attendee availability.")
        self._add("calendar.create_event", "Schedule Meeting", "calendar", RiskLevel.MEDIUM, ApprovalRequirement.NONE, 0.001, 1500, True, "Create event with Meet link.")
        self._add("tasks.create", "Create Task", "tasks", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0005, 600, True, "Create a follow-up task.")
        self._add("slides.create", "Create Presentation", "slides", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0015, 2000, True, "Create a Slides deck.")
        self._add("chat.notify", "Notify Team", "chat", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0003, 400, False, "Post a Chat message.")
        self._add("people.search", "Search People", "people", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0004, 500, False, "Search the directory.")
        self._add("forms.create", "Create Form", "forms", RiskLevel.LOW, ApprovalRequirement.NONE, 0.0008, 900, True, "Create a Google Form.")
        self._add("multimodal.analyze", "Analyze Screenshot", "gemini", RiskLevel.LOW, ApprovalRequirement.NONE, 0.002, 1200, False, "Gemini multimodal extraction from an image.")
        self._add("veo.generate_video", "Generate Video", "veo", RiskLevel.MEDIUM, ApprovalRequirement.NONE, 0.05, 8000, True, "Veo launch video.")
        self._add("lyria.generate_audio", "Generate Audio", "lyria", RiskLevel.MEDIUM, ApprovalRequirement.NONE, 0.02, 5000, True, "Lyria audio briefing.")
        self._add("imagen.generate_image", "Generate Image", "imagen", RiskLevel.LOW, ApprovalRequirement.NONE, 0.04, 2500, True, "Generate a photorealistic image from a text prompt using Vertex Imagen.")
        self._add("web.research", "Web Research", "web", RiskLevel.LOW,
                  ApprovalRequirement.NONE, 0.001, 2000, False,
                  "Search the web for external evidence (market data, competitors, facts).")

    def register(self, capability: Capability):
        self._capabilities[capability.capability_id] = capability

    def get(self, capability_id: str) -> Optional[Capability]:
        return self._capabilities.get(capability_id)

    def ids(self) -> List[str]:
        return list(self._capabilities.keys())