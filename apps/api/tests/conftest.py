# apps/api/tests/conftest.py
import os

# Hermetic tests: blank every backend/integration env var BEFORE importing the
# app so module-level singletons (LLM client, memory store, repos) build in
# their in-process form and nothing ever touches the network. Set to "" rather
# than pop so main.py's load_dotenv(override=False) can't re-add them from .env.
for _k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GCP_PROJECT_ID", "NEXORA_LLM_BACKEND",
           "NEXORA_MEMORY", "NEXORA_AGENT_ENGINE", "NEXORA_REPO", "NEXORA_DISPATCHER",
           "NEXORA_INTERNAL_AUDIENCE", "GOOGLE_GENAI_USE_VERTEXAI"):
    os.environ[_k] = ""
os.environ["EXECUTION_MODE"] = "MOCK"
os.environ["NEXORA_ADK"] = "0"

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from nexora.main import app
from nexora.core.llm_client import reset_default_client

def _clean_env():
    os.environ["EXECUTION_MODE"] = "MOCK"
    for _k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GCP_PROJECT_ID", "NEXORA_LLM_BACKEND",
               "NEXORA_MEMORY", "NEXORA_AGENT_ENGINE", "NEXORA_INTERNAL_AUDIENCE"):
        os.environ.pop(_k, None)
    reset_default_client()

_clean_env()

@pytest.fixture(autouse=True)
def reset_state_between_tests():
    _clean_env()
    async def _reset():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/internal/reset")
            assert r.status_code == 200
    asyncio.run(_reset())
    yield
    _clean_env()