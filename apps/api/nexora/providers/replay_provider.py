"""Deterministic Replay provider (ADR-045). Zero external or mock mutation."""
import uuid
from collections import defaultdict, deque
from packages.core.models import Artifact, Mission


class ReplayProvider:
    def __init__(self, source: Mission):
        self._art = defaultdict(deque)
        self._out = {}
        cap_of = {n.node_id: n.capability_id for n in source.nodes}
        for a in source.artifacts:
            self._art[cap_of.get(a.node_id, "-")].append(a)
        for n in source.nodes:
            self._out[n.capability_id] = n.outputs

    def _pop(self, cap: str, mission_id: str, node_id: str, atype: str) -> Artifact:
        q = self._art.get(cap)
        if q:
            return q.popleft().model_copy(update={"mission_id": mission_id, "node_id": node_id})
        return Artifact(artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
                        type=atype, provider="replay", resource_id="replay",
                        uri=f"replay://{cap}")

    async def create_document(self, mission_id, node_id, title, content) -> Artifact:
        return self._pop("docs.create", mission_id, node_id, "DOC")

    async def send_email(self, to, subject, body) -> Artifact:
        return self._pop("gmail.send", mission_id="-", node_id="-", atype="EMAIL")

    async def draft_email(self, to, subject, body) -> Artifact:
        return self._pop("gmail.draft", mission_id="-", node_id="-", atype="DRAFT")

    async def create_sheet(self, mission_id, node_id, title, headers) -> Artifact:
        return self._pop("sheets.create", mission_id, node_id, "SHEET")

    async def create_event(self, mission_id, node_id, title, attendees) -> Artifact:
        return self._pop("calendar.create_event", mission_id, node_id, "EVENT")

    async def create_task(self, mission_id, node_id, title, notes) -> Artifact:
        return self._pop("tasks.create", mission_id, node_id, "TASK")

    async def search_emails(self, query, max_results):
        return self._out.get("gmail.search", {}).get("search_results", [])

    async def read_email(self, message_id):
        return {}

    async def search_files(self, query):
        return self._out.get("drive.search", {}).get("search_results", [])

    async def verify_artifact(self, artifact: Artifact) -> bool:
        return True