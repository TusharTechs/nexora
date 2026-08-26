"""Reset every in-memory singleton between tests so memory/forge/audit state
from one test cannot contaminate another. Required because main.py holds
singletons at module scope."""
import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from nexora.main import app


@pytest.fixture(autouse=True)
def reset_state_between_tests():
    """Runs BEFORE every test. Clears all shared state.

    Plain (sync) fixture using asyncio.run() internally, matching the rest of
    this suite's style — the project deliberately avoids pytest-asyncio.
    An `async def` autouse fixture only ever silently no-oped under older
    pytest (no plugin executes it) and hard-errors under pytest >= 9.
    """
    async def _reset():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/internal/reset")
            assert r.status_code == 200
    asyncio.run(_reset())
    yield