#!/usr/bin/env python3
"""Probe every model id NEXORA is configured to use and report which resolve.

Run it once, authenticated, against the project you deploy to:

    cd apps/api && PYTHONPATH=../.. ./venv/Scripts/python ../../infrastructure/probe_models.py

It reads apps/api/.env (GEMINI_API_KEY / GCP_PROJECT_ID / GCP_LOCATION and the
NEXORA_*_MODEL overrides), makes one tiny real call per model, and prints a
table. Nothing is written anywhere. Exit code is non-zero if a required model
(reasoning / embedding) fails.
"""
from __future__ import annotations

import base64
import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "apps", "api", ".env"))
except Exception:
    pass

PROJECT = os.getenv("GCP_PROJECT_ID", "")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
GLOBAL_LOC = os.getenv("GCP_GENAI_LOCATION", "global")
KEY = os.getenv("GEMINI_API_KEY", "")

REASONING = os.getenv("NEXORA_MODEL_T2", "gemini-3.5-flash")
IMAGE = os.getenv("NEXORA_IMAGE_MODEL", "gemini-2.5-flash-image")
TTS = os.getenv("NEXORA_TTS_MODEL", "gemini-2.5-flash-tts")
MUSIC = os.getenv("NEXORA_AUDIO_MODEL", "lyria-002")
VIDEO = os.getenv("NEXORA_VIDEO_MODEL", "veo-3.1-fast-generate-001")
FIREWALL = os.getenv("NEXORA_FIREWALL_MODEL", "gemma-4-26b-a4b-it")
EMBED = os.getenv("NEXORA_EMBED_MODEL", "text-embedding-005")

rows: list[tuple[str, str, str, bool, str]] = []


def record(role, model, where, ok, note=""):
    rows.append((role, model, where, ok, note))
    mark = "OK " if ok else "FAIL"
    print(f"  [{mark}] {role:12} {model:34} via {where}  {note}")


def genai_vertex():
    from google import genai
    return genai.Client(vertexai=True, project=PROJECT, location=GLOBAL_LOC)


def genai_key():
    from google import genai
    return genai.Client(api_key=KEY)


def probe_text(role, model, vertex):
    try:
        c = genai_vertex() if vertex else genai_key()
        r = c.models.generate_content(model=model, contents="Reply with the single word: ok")
        record(role, model, "Vertex" if vertex else "Gemini API", bool(r.text), (r.text or "").strip()[:20])
        return bool(r.text)
    except Exception as e:
        record(role, model, "Vertex" if vertex else "Gemini API", False, str(e).splitlines()[0][:90])
        return False


def probe_tts(vertex):
    try:
        from google.genai import types
        c = genai_vertex() if vertex else genai_key()
        r = c.models.generate_content(
            model=TTS, contents="Say: hello",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=os.getenv("NEXORA_TTS_VOICE", "Kore"))))))
        got = any(getattr(p, "inline_data", None) for p in r.candidates[0].content.parts)
        record("tts", TTS, "Vertex" if vertex else "Gemini API", got,
               "returned audio" if got else "no audio part")
    except Exception as e:
        record("tts", TTS, "Vertex" if vertex else "Gemini API", False,
               str(e).splitlines()[0][:90])


def probe_image():
    try:
        c = genai_vertex() if PROJECT else genai_key()
        r = c.models.generate_content(model=IMAGE,
                                      contents="Generate a plain solid teal 16:9 image.")
        got = any(getattr(p, "inline_data", None) for p in r.candidates[0].content.parts)
        record("image", IMAGE, "Vertex" if PROJECT else "Gemini API", got,
               "returned image bytes" if got else "no image part")
    except Exception as e:
        record("image", IMAGE, "Vertex" if PROJECT else "Gemini API", False,
               str(e).splitlines()[0][:90])


def probe_embed():
    try:
        c = genai_vertex() if PROJECT else genai_key()
        r = c.models.embed_content(model=EMBED, contents="hello")
        n = len(r.embeddings[0].values)
        record("embedding", EMBED, "Vertex" if PROJECT else "Gemini API", n > 0, f"{n}-dim")
        return n > 0
    except Exception as e:
        record("embedding", EMBED, "Vertex" if PROJECT else "Gemini API", False,
               str(e).splitlines()[0][:90])
        return False


def probe_vertex_rest(role, model, loc, payload):
    """Veo / Lyria live on the raw predict endpoints."""
    import google.auth
    import google.auth.transport.requests
    import httpx
    try:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        host = ("aiplatform.googleapis.com" if loc == "global"
                else f"{loc}-aiplatform.googleapis.com")
        verb = ":predictLongRunning" if role == "video" else ":predict"
        url = (f"https://{host}/v1/projects/{PROJECT}/locations/{loc}"
               f"/publishers/google/models/{model}{verb}")
        with httpx.Client(timeout=60) as c:
            r = c.post(url, headers={"Authorization": f"Bearer {creds.token}"}, json=payload)
        ok = r.status_code < 400
        record(role, model, f"Vertex {loc}", ok,
               "accepted" if ok else f"HTTP {r.status_code}: {r.text[:70]}")
    except Exception as e:
        record(role, model, f"Vertex {loc}", False, str(e).splitlines()[0][:90])


def main() -> int:
    if not (PROJECT or KEY):
        print("Set GEMINI_API_KEY or GCP_PROJECT_ID in apps/api/.env first.", file=sys.stderr)
        return 2
    print(f"Project: {PROJECT or '(none)'}   Vertex loc: {LOCATION}/{GLOBAL_LOC}   "
          f"Gemini API key: {'set' if KEY else 'no'}\n")

    print("Reasoning / text:")
    ok_reason = probe_text("reasoning", REASONING, vertex=bool(PROJECT)) or (
        KEY and probe_text("reasoning", REASONING, vertex=False))
    probe_text("firewall", FIREWALL, vertex=False if KEY else bool(PROJECT))

    print("\nMultimodal:")
    probe_image()
    # NEXORA's TTS + Lyria always run on Vertex (genai_client is Vertex-first).
    probe_tts(vertex=bool(PROJECT))
    if PROJECT:
        probe_vertex_rest("music", MUSIC, os.getenv("NEXORA_MUSIC_LOCATION", "us-central1"),
                          {"instances": [{"prompt": "a warm, uplifting corporate acoustic guitar theme"}],
                           "parameters": {"sampleCount": 1}})
        probe_vertex_rest("video", VIDEO, os.getenv("NEXORA_VIDEO_LOCATION", "us-central1"),
                          {"instances": [{"prompt": "a calm lake at dawn"}],
                           "parameters": {"sampleCount": 1, "durationSeconds": 6}})

    print("\nEmbeddings:")
    ok_embed = probe_embed()

    print("\n--- Markdown table for the README ---\n")
    print("| Role | Model ID | Endpoint | Resolves |")
    print("|---|---|---|---|")
    for role, model, where, ok, _ in rows:
        print(f"| {role} | `{model}` | {where} | {'yes' if ok else 'NO'} |")

    required_ok = bool(ok_reason) and bool(ok_embed)
    print(f"\nRequired models (reasoning, embedding): {'OK' if required_ok else 'MISSING'}")
    return 0 if required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
