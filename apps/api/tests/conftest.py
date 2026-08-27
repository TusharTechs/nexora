import os
# Force a deterministic test environment BEFORE importing the app, so the suite
# never inherits a developer's local .env (e.g. EXECUTION_MODE=LIVE).
os.environ["EXECUTION_MODE"] = "MOCK"
os.environ.pop("GEMINI_API_KEY", None)

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from nexora.main import app


@pytest.fixture(autouse=True)
def reset_state_between_tests():
    async def _reset():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/internal/reset")
            assert r.status_code == 200
    asyncio.run(_reset())
    yield