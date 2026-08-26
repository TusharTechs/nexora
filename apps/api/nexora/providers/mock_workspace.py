import asyncio
import uuid
from typing import Dict, List
from packages.core.models import Artifact

class MockWorkspaceProvider:
    """Deterministic, seeded, zero-external-call provider with concurrency tracking."""
    def __init__(self):
        self._docs, self._sheets, self._events, self._sent = {}, {}, {}, {}
        self._emails = {
            "msg_1": {"id": "msg_1", "subject": "URGENT: Checkout Down", "snippet": "Customers cannot pay.",
                      "body": "Checkout API returning 500. Severe impact."},
        }
        self._files = {
            "file_1": {"id": "file_1", "name": "SLA_Acme.pdf", "type": "pdf",
                       "content": "SLA requires 1h response."},
        }
        self._active = 0
        self.max_concurrency = 0

    async def _latency(self):
        self._active += 1
        self.max_concurrency = max(self.max_concurrency, self._active)
        await asyncio.sleep(0.05)
        self._active -= 1

    async def create_document(self, mission_id, node_id, title, content) -> Artifact:
        await self._latency()
        aid = str(uuid.uuid4())
        self._docs[aid] = {"title": title, "content": content}
        return Artifact(artifact_id=aid, mission_id=mission_id, node_id=node_id, type="DOC",
                        provider="mock", resource_id=aid, uri=f"mock://docs/{aid}")

    async def search_emails(self, query, max_results) -> List[Dict]:
        await self._latency()
        return [{"id": m["id"], "subject": m["subject"], "snippet": m["snippet"]} for m in list(self._emails.values())[:max_results]]

    async def read_email(self, message_id) -> Dict:
        await self._latency()
        return self._emails.get(message_id, {})

    async def send_email(self, to, subject, body) -> Artifact:
        await self._latency()
        aid = str(uuid.uuid4())
        self._sent[aid] = {"to": to, "subject": subject}
        return Artifact(artifact_id=aid, mission_id="-", node_id="-", type="EMAIL",
                        provider="mock", resource_id=aid, uri=f"mock://sent/{aid}")

    async def search_files(self, query) -> List[Dict]:
        await self._latency()
        return [{"id": f["id"], "name": f["name"], "type": f["type"]} for f in self._files.values()]

    async def create_sheet(self, mission_id, node_id, title, headers) -> Artifact:
        await self._latency()
        aid = str(uuid.uuid4())
        self._sheets[aid] = {"title": title, "headers": headers, "rows": []}
        return Artifact(artifact_id=aid, mission_id=mission_id, node_id=node_id, type="SHEET",
                        provider="mock", resource_id=aid, uri=f"mock://sheets/{aid}")

    async def create_event(self, mission_id, node_id, title, attendees) -> Artifact:
        await self._latency()
        aid = str(uuid.uuid4())
        self._events[aid] = {"title": title, "attendees": attendees, "meet_link": f"mock://meet/{aid}"}
        return Artifact(artifact_id=aid, mission_id=mission_id, node_id=node_id, type="EVENT",
                        provider="mock", resource_id=aid, uri=f"mock://calendar/{aid}")

    async def verify_artifact(self, artifact: Artifact) -> bool:
        store = {"DOC": self._docs, "SHEET": self._sheets, "EVENT": self._events, "EMAIL": self._sent}
        return artifact.resource_id in store.get(artifact.type, {})
