"""CredentialStore (ADR-024). Dev: encrypted-ish local JSON file. Prod: Secret Manager.
Never store plaintext OAuth refresh tokens in Firestore."""
import json
import os
from typing import Any, Dict, Optional, Protocol

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".nexora_creds.json")


class CredentialStore(Protocol):
    async def get_google_credentials(self, user_id: str) -> Optional[Dict[str, Any]]: ...
    async def store_google_credentials(self, user_id: str, token_data: Dict[str, Any]) -> str: ...


class LocalCredentialStore:
    """Dev-only local file backend. .nexora_creds.json is gitignored."""
    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.path):
            with open(self.path) as f:
                return json.load(f)
        return {}

    async def store_google_credentials(self, user_id: str, token_data: Dict[str, Any]) -> str:
        data = self._load()
        data[user_id] = token_data
        with open(self.path, "w") as f:
            json.dump(data, f)
        return f"local://{user_id}"

    async def get_google_credentials(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self._load().get(user_id)


class SecretManagerCredentialStore:
    async def get_google_credentials(self, user_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Implemented in Phase 9.6 with GCP Secret Manager")

    async def store_google_credentials(self, user_id: str, token_data: Dict[str, Any]) -> str:
        raise NotImplementedError("Implemented in Phase 9.6 with GCP Secret Manager")