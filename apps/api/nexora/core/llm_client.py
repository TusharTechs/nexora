"""Unified LLM Client (ADR-060).

One client, two Google backends:
- "gemini": Gemini API / AI Studio (key-based, free tier)
- "vertex": Vertex AI (GCP project + ADC; also the future Veo/Lyria path)

Selection: NEXORA_LLM_BACKEND=gemini|vertex|auto (default auto).
auto prefers Vertex when GCP_PROJECT_ID is configured, else Gemini, and falls
back to the other backend on any failure. All LLM call sites (compiler,
contract, verifier, replanner, research synthesis) delegate here, so the
backend choice is env-only and never touches business logic.

Test seams: call_fn (short-circuit), http_fn (fake transport), token_fn (fake ADC).
"""
import asyncio
import os
import time
from typing import Callable, Optional

import httpx


class LLMUnavailableError(RuntimeError):
    pass


def _insecure() -> bool:
    return os.getenv("NEXORA_INSECURE_TLS", "") == "1"


def gemini_api_key() -> str:
    """The Gemini API key. NEXORA_GEMINI_API_KEY is the private stash the ADK
    setup uses when it has to hide GEMINI_API_KEY from google-genai on the
    Vertex path (see adk_runtime._configure_genai_env)."""
    return os.getenv("GEMINI_API_KEY", "") or os.getenv("NEXORA_GEMINI_API_KEY", "")


def llm_available() -> bool:
    """Env-level check: at least one backend configured."""
    return bool(gemini_api_key()) or bool(os.getenv("GCP_PROJECT_ID", ""))


class LLMClient:
    """Unified client for Gemini API and Vertex AI."""

    def __init__(self, backend: Optional[str] = None,
                 gemini_key: Optional[str] = None,
                 project: Optional[str] = None,
                 location: Optional[str] = None,
                 model: Optional[str] = None,
                 call_fn: Optional[Callable[[str], str]] = None,
                 http_fn=None,
                 token_fn=None):
        """Initialize the LLM client.

        Args:
            backend: "gemini" | "vertex" | "auto". None = read from env.
            gemini_key: Gemini API key. None = read from env; "" = explicitly unset.
            project: GCP project ID for Vertex. None = read from env; "" = explicitly unset.
            location: GCP location for Vertex. None = read from env; "" = explicitly unset.
            model: Model id. None = read from env.
            call_fn: Test seam — short-circuit with canned output.
            http_fn: Test seam — fake HTTP transport.
            token_fn: Test seam — fake ADC token.
        """
        self.backend = backend if backend is not None else os.getenv("NEXORA_LLM_BACKEND", "auto")
        self.gemini_key = gemini_key if gemini_key is not None else gemini_api_key()
        self.project = project if project is not None else os.getenv("GCP_PROJECT_ID", "")
        # Gemini text models on Vertex are served from the "global" endpoint;
        # regional media endpoints (Imagen/Veo/Lyria) use GCP_LOCATION separately.
        self.location = location if location is not None else \
            os.getenv("GCP_GENAI_LOCATION", "global")
        self.model = model or os.getenv("NEXORA_MODEL_T2", "gemini-3.5-flash")
        self.call_fn = call_fn
        self.http_fn = http_fn
        self.token_fn = token_fn
        self._token_cache = {"token": None, "expires": 0.0}

    # ---------------- public ----------------
    async def generate(self, prompt: str, temperature: float = 0.2,
                       model: Optional[str] = None) -> str:
        if self.call_fn:
            return self.call_fn(prompt)
        order = self._order()
        if not order:
            raise LLMUnavailableError(
                "No LLM backend configured (set GEMINI_API_KEY or GCP_PROJECT_ID).")
        last_err: Optional[Exception] = None
        for backend in order:
            try:
                if backend == "vertex":
                    return await self._vertex(prompt, temperature, model)
                return await self._gemini(prompt, temperature, model)
            except Exception as e:
                last_err = e          # try the next backend
        raise LLMUnavailableError(f"All LLM backends failed: {last_err}")

    # ---------------- backend selection ----------------
    def _order(self):
        configured = []
        if self.project:
            configured.append("vertex")
        if self.gemini_key:
            configured.append("gemini")
        if self.backend == "vertex":
            return ["vertex"] if self.project else []
        if self.backend == "gemini":
            return ["gemini"] if self.gemini_key else []
        return configured             # auto: vertex-first when available

    # ---------------- transports ----------------
    # Real runs go through the Google GenAI SDK (`google-genai`) — this is the
    # "Google Agent Framework / GenAI SDK" the hackathon requires. The raw-REST
    # path below is kept only for the http_fn test seam and as a last-resort
    # fallback if the SDK is unavailable.
    async def _gemini(self, prompt, temperature, model):
        m = model or self.model
        if self.http_fn is None:
            try:
                return await self._genai_sdk(prompt, temperature, m, vertex=False)
            except ImportError:
                pass
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
        headers = {"x-goog-api-key": self.gemini_key}
        payload = {"contents": [{"parts": [{"text": prompt}]}],
                   "generationConfig": {"temperature": temperature}}
        return await self._http("gemini", url, headers, payload)

    async def _vertex(self, prompt, temperature, model):
        m = model or self.model
        if self.http_fn is None and self.token_fn is None:
            try:
                return await self._genai_sdk(prompt, temperature, m, vertex=True)
            except ImportError:
                pass
        token = await self._vertex_token()
        host = ("aiplatform.googleapis.com" if self.location == "global"
                else f"{self.location}-aiplatform.googleapis.com")
        url = (f"https://{host}/v1/"
               f"projects/{self.project}/locations/{self.location}/"
               f"publishers/google/models/{m}:generateContent")
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"contents": [{"parts": [{"text": prompt}]}],
                   "generationConfig": {"temperature": temperature}}
        return await self._http("vertex", url, headers, payload)

    async def _genai_sdk(self, prompt: str, temperature: float, model: str,
                         vertex: bool) -> str:
        """Primary transport — Google GenAI SDK (google-genai)."""
        from google import genai
        from google.genai import types
        if vertex:
            client = genai.Client(vertexai=True, project=self.project,
                                  location=self.location)
        else:
            client = genai.Client(api_key=self.gemini_key)
        resp = await client.aio.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(temperature=temperature),
        )
        return resp.text or ""

    async def _http(self, backend, url, headers, payload) -> str:
        if self.http_fn:
            return self.http_fn(backend, url, headers, payload)
        async with httpx.AsyncClient(timeout=30, verify=not _insecure()) as c:
            r = await c.post(url, headers=headers, json=payload)
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    # ---------------- Vertex auth (ADC) ----------------
    async def _vertex_token(self) -> str:
        if self.token_fn:
            return self.token_fn()
        now = time.time()
        if self._token_cache["token"] and now < self._token_cache["expires"]:
            return self._token_cache["token"]
        token = await asyncio.to_thread(self._default_vertex_token)
        self._token_cache = {"token": token, "expires": now + 3000}
        return token

    @staticmethod
    def _default_vertex_token() -> str:
        import google.auth
        import google.auth.transport.requests
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not creds.valid:
            request = None
            if _insecure():
                try:
                    import requests as _requests
                    s = _requests.Session()
                    s.verify = False
                    request = google.auth.transport.requests.Request(session=s)
                except Exception:
                    request = None
            creds.refresh(request or google.auth.transport.requests.Request())
        return creds.token


_default_client: Optional[LLMClient] = None


def get_default_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client


def reset_default_client():
    global _default_client
    _default_client = None


async def llm_generate(prompt: str, temperature: float = 0.2,
                       model: Optional[str] = None) -> str:
    return await get_default_client().generate(prompt, temperature, model)


def genai_client():
    """A configured google-genai Client, Vertex-first when a project is set.

    Used by call sites that need SDK features beyond plain text generation
    (Google Search grounding, image generation, multimodal parts).
    """
    from google import genai
    backend = os.getenv("NEXORA_LLM_BACKEND", "auto")
    project = os.getenv("GCP_PROJECT_ID", "")
    key = gemini_api_key()
    use_vertex = backend == "vertex" or (backend == "auto" and project and not key)
    if use_vertex and project:
        return genai.Client(vertexai=True, project=project,
                            location=os.getenv("GCP_GENAI_LOCATION", "global"))
    if key:
        return genai.Client(api_key=key)
    if project:
        return genai.Client(vertexai=True, project=project,
                            location=os.getenv("GCP_GENAI_LOCATION", "global"))
    raise LLMUnavailableError("No LLM backend configured.")