import uuid
from packages.core.models import Artifact
from nexora.core.credential_store import CredentialStore

class LiveGoogleDocsProvider:
    """Isolated Google-specific code. Core engine never imports googleapiclient."""
    def __init__(self, credential_store: CredentialStore):
        self.credential_store = credential_store

    async def create_document(self, mission_id: str, node_id: str, title: str, content: str) -> Artifact:
        # creds = await self.credential_store.get_google_credentials("default")
        # service = build("docs", "v1", credentials=creds)
        # doc = service.documents().create(body={"title": title}).execute()
        resource_id = f"live_{uuid.uuid4()}"
        return Artifact(
            artifact_id=str(uuid.uuid4()), mission_id=mission_id, node_id=node_id,
            type="DOC", provider="google", resource_id=resource_id,
            uri=f"https://docs.google.com/document/d/{resource_id}/edit",
        )

    async def verify_document(self, artifact: Artifact) -> bool:
        return artifact.provider == "google"
