import uuid
from packages.core.models import Artifact

class MockDocsProvider:
    """Deterministic local provider. ZERO external calls."""
    def __init__(self):
        self._store = {}

    async def create_document(self, mission_id: str, node_id: str, title: str, content: str) -> Artifact:
        artifact_id = str(uuid.uuid4())
        self._store[artifact_id] = {"title": title, "content": content}
        return Artifact(
            artifact_id=artifact_id, mission_id=mission_id, node_id=node_id,
            type="DOC", provider="mock", resource_id=artifact_id,
            uri=f"mock://docs/{artifact_id}",
        )

    async def verify_document(self, artifact: Artifact) -> bool:
        return artifact.artifact_id in self._store
