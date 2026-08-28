# apps/api/tests/conftest.py
import os
os.environ["EXECUTION_MODE"] = "MOCK"

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from nexora.main import app
from nexora.core.llm_client import reset_default_client

def _clean_env():
    os.environ["EXECUTION_MODE"] = "MOCK"
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("GCP_PROJECT_ID", None)
    os.environ.pop("NEXORA_LLM_BACKEND", None)
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