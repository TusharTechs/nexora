# ADR-070: Spoken briefings use Gemini TTS; Lyria is for music

Status: Accepted.

## Context

NEXORA's `lyria.generate_audio` capability was described as "audio briefing" and
the composer produces a **spoken narration script** for it. But Lyria is a
**music** model — it generates songs with instrumentation and sung vocals, not
spoken narration. Feeding a briefing script to Lyria produces a jingle, not a
briefing.

## Decision

`generate_audio(prompt, kind=...)`:

- `kind="speech"` (default) — **Gemini TTS** (`NEXORA_TTS_MODEL`, default
  `gemini-2.5-flash-tts`, voice `NEXORA_TTS_VOICE=Kore`). Returns 24 kHz PCM,
  wrapped to WAV, uploaded to the mission folder. This is what "audio briefing /
  narration / read aloud" means.
- `kind="music"` — **Vertex Lyria** (`NEXORA_AUDIO_MODEL`, default `lyria-002`).
  Used only when the goal explicitly asks for music / a jingle / a soundtrack /
  a theme.

The Node Executor picks `kind` from the goal wording.

## Model choices (cost-aware)

| Purpose | Model | Why |
| --- | --- | --- |
| Spoken audio | `gemini-2.5-flash-tts` | already enabled with Gemini; ~nothing per 45 s clip |
| Music / jingle | `lyria-002` (Lyria 2) | cheapest Lyria tier; Lyria 3 / 3 Pro are full-song, pricier |
| Video | `veo-3.1-fast-generate-001` (Veo 3.1 Fast) | current gen, Fast tier is materially cheaper than standard, native audio; Lite drops quality visibly for a demo |

Veo's estimated cost is raised to $0.20/clip and the default mission budget to
$2.00 so a video node doesn't trip the circuit breaker.

## Consequences

- "Give me an audio briefing" now returns an actual spoken briefing.
- Lyria stays wired for a genuine music use case (brand jingle, launch sting),
  which also keeps the multimodal-models bonus in play.
- Veo/Lyria still fall back to a mock artifact if the model isn't enabled in the
  project.
