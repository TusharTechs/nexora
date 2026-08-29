# NEXORA — 4‑minute demo script

Goal of the video: **wow in the first 30 seconds**, then show — on screen, live,
unedited — every technology the rubric rewards, so no point can be deducted.
Human voice, not AI. English (or English subtitles).

## Before you record

Open these, each in its own browser tab, and sign in:

| Tab | URL | Why |
|---|---|---|
| **NEXORA** | your Cloud Run URL (the `*.run.app`) | the product |
| **Cloud Run** | console → Cloud Run → `nexora-api` | *proof the backend runs on Google Cloud* |
| **Agent Engine** | console → Vertex AI → Agent Engine → `nexora-agent-engine` | ADK on the agent platform |
| **Firestore** | console → Firestore → `missions` collection | durable state |
| **Cloud Tasks** | console → Cloud Tasks → `nexora-workers` | durable execution |
| **Cloud Scheduler** | console → Cloud Scheduler → `nexora-run-due` | standing goals |
| **Drive** | drive.google.com | where the deliverables land |

Set NEXORA to **LIVE** mode and confirm the Google connection.
Have a second goal pre‑typed for the schedule demo.

---

## 0:00 – 0:30 · The hook

> "Every AI tool gives you a draft. None of them give you finished, checked work.
> Watch." *(type, or paste, one sentence)*

**Goal:** *"I'm in Kyoto for 3 days next week. Prepare the trip: a travel guide
document, a day‑by‑day slide deck, an itemised budget spreadsheet in USD, one
inspiring hero photo, and a short spoken audio briefing of the plan."*

Hit **Launch**. While it starts, say the line and **point at the badge row**:

> "Everything you see here runs on Google — Gemini 3.5, the Agent Development
> Kit, an Agent Engine instance, Veo, Lyria, all live from the running config."

## 0:30 – 1:45 · The mission, live

Narrate the Command Center as it moves:

- **"First it writes a contract"** — the *Outcome Contract* panel appears: the
  five deliverables it now has to satisfy. "It defined success before doing any
  work."
- **"Then a Mission Architect agent plans it"** — phases tick
  Understand → Discover → Plan.
- **"Then a workforce of six Gemini agents on the ADK executes"** — the workforce
  cards light up: Research Analyst, Writer, Financial Analyst, Designer, Visual
  Designer. "The Research Analyst is doing grounded web search right now."
- **"Then a QA Auditor agent checks the actual files against the contract"** —
  the deliverables flip to ✓. "Not *did the steps run* — *is the work good*."

Land on **Mission Complete · 5 of 5 deliverables satisfied** and click **Open
Mission Workspace**.

## 1:45 – 2:45 · The real work

In the Drive folder, open each file for ~8 seconds:

- **Google Doc** — scroll it: real headings, a costed day‑by‑day itinerary,
  cited facts. "Gemini wrote this from grounded search, not a template."
- **Google Sheet** — the budget: frozen header, currency formatting, a TOTAL row.
- **Google Slides** — the themed day‑by‑day deck.
- **The hero image** — generated with a Gemini image model.
- **The audio file** — play 3 seconds. "That's Gemini TTS reading the plan."

*(If your Product‑Launch demo is running instead, this is where the **Veo** clip
and the **Lyria** jingle play.)*

## 2:45 – 3:30 · The receipts — why this is a system, not a demo

Rapid cuts, ~10 seconds each:

1. **Cloud Run tab** — the service, green, the `*.run.app` URL. "The backend is
   here, on Cloud Run."
2. **Agent Engine tab** — the `reasoningEngines/…` instance. "The agents run on
   Vertex AI Agent Engine — managed sessions and Memory Bank."
3. **Firestore tab** — refresh; the mission document that just appeared.
4. **Cloud Tasks tab** — the queue; tasks that fired for each plan node.
5. **The firewall** — run the *Email Summary* scenario; point at the audit line
   where a poisoned email is **quarantined** before any model sees it.
6. **A replan** — show a mission that reached `PARTIAL`, the *"replan"* arrow, and
   the follow‑up nodes that closed the gap.

## 3:30 – 4:00 · It runs when you're not there

- Click the **🗓 schedule** button, pick **every weekday · 07:00**, add the
  standing instruction. "This mission doesn't exist yet — Cloud Scheduler will
  create it Monday morning."
- **Cloud Scheduler tab** — the `nexora-run-due` job, `* * * * *`.
- Close: *"One sentence in. A folder of finished, verified work out — and it
  keeps working after you close the tab. That's NEXORA."*

---

## The one‑glance checklist you just showed

| Rubric item | Shown at |
|---|---|
| Gemini 3.5 | badge row + narration (0:20) |
| Google ADK | workforce narration (1:10) + Agent Engine tab (2:55) |
| Vertex AI Agent Engine | badge row + Agent Engine tab (2:55) |
| Cloud Run | Cloud Run tab (2:50) |
| Firestore | Firestore tab (3:05) |
| Cloud Tasks | Cloud Tasks tab (3:10) |
| Cloud Scheduler | Scheduler tab (3:45) |
| Google Search grounding | Research Analyst narration (1:15) + the doc's citations (1:55) |
| Gemini image | the hero photo (2:20) |
| Veo | Product‑Launch clip (2:30, alt path) |
| Lyria | Product‑Launch jingle (2:35, alt path) |
| Gemini TTS | the audio briefing (2:35) |
| Multimodal | voice input (optional 0:10) + image + video + audio + screenshot analysis |
| Autonomous multi‑step / Taskmaster | the whole 0:30–2:45 run |
| Failure‑tolerant architecture | the replan (3:20) + the firewall (3:15) |
| Production readiness | live URL + Cloud Console throughout |
