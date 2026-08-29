from typing import List, Dict, Protocol
from packages.core.models import Artifact

class WorkspaceProvider(Protocol):
    """One object implements every Workspace protocol per execution mode.

    CONTRACT (Phase 4 hardening): search/read results MUST include the full
    message/file body under the "body" key when available — the Content
    Firewall scans it before any agent consumes the content.
    Live Gmail implementation: fetch messages with format="full" (or parse
    the payload from format="metadata"); never return snippet-only dicts.
    """
    async def create_document(self, mission_id: str, node_id: str, title: str, content: str) -> Artifact: ...
    async def verify_artifact(self, artifact: Artifact) -> bool: ...
    async def search_emails(self, query: str, max_results: int) -> List[Dict]: ...
    async def read_email(self, message_id: str) -> Dict: ...
    async def send_email(self, to: List[str], subject: str, body: str) -> Artifact: ...
    async def search_files(self, query: str) -> List[Dict]: ...
    async def create_sheet(self, mission_id: str, node_id: str, title: str, headers: List[str]) -> Artifact: ...
    async def create_event(self, mission_id: str, node_id: str, title: str, attendees: List[str]) -> Artifact: ...

class ProviderRegistry:
    def __init__(self, provider):
        self.provider = provider

    def for_api(self, required_api: str):
        return self.provider
