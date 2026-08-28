import asyncio
import os
import pytest
from nexora.core.llm_client import LLMClient, LLMUnavailableError, llm_available

def run(c): return asyncio.run(c)


def test_call_fn_short_circuit():
    async def inner():
        c = LLMClient(call_fn=lambda p: "canned")
        assert await c.generate("x") == "canned"
    run(inner())


def test_no_backend_raises():
    async def inner():
        c = LLMClient(gemini_key="", project="")
        with pytest.raises(LLMUnavailableError):
            await c.generate("x")
    run(inner())


def test_gemini_backend_url_and_key():
    seen = {}
    def http_fn(backend, url, headers, payload):
        seen.update(backend=backend, url=url, headers=headers)
        return "gemini-says-hi"
    async def inner():
        c = LLMClient(backend="gemini", gemini_key="k", http_fn=http_fn)
        assert await c.generate("hello") == "gemini-says-hi"
        assert seen["backend"] == "gemini"
        assert "generativelanguage.googleapis.com" in seen["url"]
        assert seen["headers"]["x-goog-api-key"] == "k"
    run(inner())


def test_vertex_backend_url_and_token():
    seen = {}
    def http_fn(backend, url, headers, payload):
        seen.update(backend=backend, url=url, headers=headers)
        return "vertex-says-hi"
    async def inner():
        c = LLMClient(backend="vertex", project="proj-1", location="us-central1",
                      http_fn=http_fn, token_fn=lambda: "tok-123")
        out = await c.generate("hello", model="gemini-2.5-flash")
        assert out == "vertex-says-hi"
        assert seen["backend"] == "vertex"
        assert "us-central1-aiplatform.googleapis.com" in seen["url"]
        assert "/projects/proj-1/" in seen["url"]
        assert "gemini-2.5-flash" in seen["url"]
        assert seen["headers"]["Authorization"] == "Bearer tok-123"
    run(inner())


def test_auto_prefers_vertex_and_falls_back():
    calls = []
    def http_fn(backend, url, headers, payload):
        calls.append(backend)
        if backend == "vertex":
            raise RuntimeError("vertex down")
        return "gemini-fallback"
    async def inner():
        c = LLMClient(backend="auto", gemini_key="k", project="p",
                      http_fn=http_fn, token_fn=lambda: "t")
        assert await c.generate("x") == "gemini-fallback"
        assert calls == ["vertex", "gemini"]
    run(inner())


def test_auto_gemini_only():
    calls = []
    def http_fn(backend, url, headers, payload):
        calls.append(backend)
        return "ok"
    async def inner():
        c = LLMClient(backend="auto", gemini_key="k", project="", http_fn=http_fn)
        assert await c.generate("x") == "ok"
        assert calls == ["gemini"]
    run(inner())


def test_llm_available_env():
    old = (os.environ.get("GEMINI_API_KEY"), os.environ.get("GCP_PROJECT_ID"))
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("GCP_PROJECT_ID", None)
    try:
        assert llm_available() is False
        os.environ["GCP_PROJECT_ID"] = "p"
        assert llm_available() is True
    finally:
        for key, val in zip(("GEMINI_API_KEY", "GCP_PROJECT_ID"), old):
            if val is not None:
                os.environ[key] = val
            else:
                os.environ.pop(key, None)