from typing import Any, Dict, Optional, Protocol

class CredentialStore(Protocol):
    async def get_google_credentials(self, user_id: str) -> Optional[Dict[str, Any]]: ...

class LocalCredentialStore:
    """Dev-only. Production uses SecretManagerCredentialStore (Phase 3+)."""
    async def get_google_credentials(self, user_id: str) -> Optional[Dict[str, Any]]:
        return {"type": "local-dev", "token": "dummy"}

class SecretManagerCredentialStore:
    async def get_google_credentials(self, user_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Implemented in Phase 3 with GCP Secret Manager")
