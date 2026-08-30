# NEXORA — demo video script (≤ 4:00)

**Shape:** a viral hook you pre-recorded (0:00–0:35), then ONE task run live —
narrated while it works — then the payoff and the close. Human voice, English
(or subtitles). Every rubric technology appears **on screen, live**.

The `▸ SAY` lines are the voiceover. `▸ SHOW` is what's on screen.

---

## Before you record

**Assets from the pre-run launch-kit mission** (already generated — links in
`docs/DEMO-assets.md`): the Drive folder, the Doc, the Sheet, the Slides, the
outreach email, the hero image, the Veo teaser `.mp4`, the Lyria jingle `.wav`.
Have them open in tabs / a video editor for the montage.

**Tabs, each signed in:**

| Tab | Where | Proves |
|---|---|---|
| **NEXORA** | `https://nexora-nexus.vercel.app` | the product |
| **Cloud Run** | console → Cloud Run → `nexora-api` | backend on Google Cloud |
| **Agent Engine** | console → Vertex AI → Agent Engine → `nexora-agent-engine` | ADK on the agent platform |
| **Cloud Build** | console → Cloud Build → History | reproducible deploy |
| **Google Calendar** | calendar.google.com | the live task's real output |
| **Drive** | drive.google.com | where deliverables land |

Set NEXORA to **LIVE**, confirm the Google connection (top-right). Pre-type the
live goal (below) so you only have to hit **Launch**.

---

## 0:00 – 0:35 · The hook (pre-recorded montage)

▸ SHOW  You, typing one sentence into NEXORA and hitting Launch. Hard cut to a
fast montage — 3–4 seconds each, Ken-Burns push on each:

1. the **Google Doc** scrolling — a real go-to-market strategy, headings, named accounts
2. the **Google Sheet** — the 12-month financial model, margins, a bottom-line row
3. the **Google Slides** deck flipping through — dark title slide, accent bars
4. the **outreach email** — the branded HTML render
5. the **hero image**, then the **Veo teaser** playing with the **Lyria jingle** under it

▸ SAY  *"I gave NEXORA one sentence — 'launch my oat-milk brand, prepare the
kit.' No follow-ups. This is what came back: a go-to-market strategy, a full
financial model, an investor deck, a wholesale outreach email, a brand film, and
a jingle — every file sitting in one Drive folder, already checked."*

▸ SHOW  Text card: **One sentence in. A verified workspace out.**

---

## 0:35 – 0:55 · What it is

▸ SHOW  The NEXORA Command Center, idle. Pan slowly across the **live stack badge
row** in the header.

▸ SAY  *"NEXORA is an autonomous goal compiler. A workforce of Gemini 3.5 agents,
running on Google's Agent Development Kit and Vertex AI Agent Engine, plans the
work, does it, and checks it against a contract it wrote first. Everything in
this row is read live from the running service — Gemini 3.5, ADK, Agent Engine
with managed Sessions and Memory Bank, Vertex AI, and the media models: Veo,
Lyria, Gemini image, Gemini TTS."*

---

## 0:55 – 2:45 · One task, live

▸ SHOW  Type the goal (or reveal it pre-typed) and hit **Launch**:

> **"Plan our founder offsite in Lisbon, March 3–5, for 6 people: an agenda
> document and a shared budget spreadsheet in USD — and hold 11am tomorrow for
> the kickoff call with a Google Meet link."**

▸ SAY  *"Real research, real writing, real file-building takes a couple of
minutes — so I'll fast-forward the clock, not skip anything. While it works,
here's what's actually happening."*

**Now narrate the panels as they appear (fast-forward the dead air between):**

- **Outcome Contract card** —
  ▸ SAY *"First it wrote a contract: the checkable definition of done — the
  deliverables, the evidence it needs, the constraints. It decides what success
  means before it does any work. That's the whole idea — success is a contract,
  not a status code."*

- **5-phase strip: Understand → Discover → Plan → Execute → Verify** —
  ▸ SAY *"A Mission Interpreter agent restated the goal as structured intent. A
  Discovery pass scanned the connected workspace so it doesn't rebuild what's
  already there. Then the Mission Architect agent compiled the goal into a
  dependency graph of capabilities — never raw API calls."*

- **The 6-agent workforce grid lighting up** —
  ▸ SAY *"Six specialist agents on the ADK run the graph in parallel — a Research
  Analyst doing grounded Google Search, a Writer, a Financial Analyst, a
  Designer. Gemini writes the actual document body and the costed spreadsheet
  rows from the evidence they gather."*

- **Switch to the Cloud Console tabs for ~15 seconds total:**
  ▸ SHOW  Cloud Run `nexora-api` (green, the URL) → Agent Engine
  `reasoningEngines/…` instance → Cloud Build history.
  ▸ SAY *"The service is on Cloud Run. The agents run on a real Vertex AI Agent
  Engine instance — managed Sessions and a Memory Bank that remembers your
  preferences across missions. Deployed reproducibly from one script."*

- **Back to NEXORA — the "Technical details" drawer** (open it) —
  ▸ SHOW  the DAG, the audit trail, the evidence list.
  ▸ SAY *"Every action writes a receipt to an audit trail. Every external string
  — an email body, a web result — is scanned for prompt injection, twice: a
  deterministic firewall, then a Gemma model as a second opinion, before any
  reasoning model sees it."*

- **The Standing Instructions panel** —
  ▸ SAY *"And a goal can be scheduled — daily, weekly, weekdays. The mission for
  next Monday doesn't exist until Monday; Cloud Scheduler creates it."*

▸ SHOW  The mission lands on **Mission Complete · OUTCOME VERIFIED · 3 of 3
deliverables satisfied**.

▸ SAY *"And here's the part no other agent does — a QA Auditor agent opened the
files it just made and ruled on each one against the contract: satisfied,
partial, or missing. Not 'did the steps run' — 'is the work actually good.' If
something's short, it repairs itself and re-runs."*

---

## 2:45 – 3:25 · The payoff — it's real

▸ SHOW  Click **Open Mission Workspace**. In the Drive folder, open each file for
~6 seconds:

- **Doc** — scroll the agenda: real sessions, times, a Lisbon logistics section.
- **Sheet** — the budget: frozen header, currency formatting, a TOTAL row.

▸ SHOW  Switch to the **Google Calendar** tab. There's the event — **tomorrow,
11:00**, a **Google Meet link**, the invite sent.

▸ SAY *"That's a real hold on a real calendar with a real Meet link — not a
mock-up. NEXORA didn't describe the work. It did the work."*

---

## 3:25 – 4:00 · Close

▸ SHOW  The architecture diagram (`docs/architecture.svg`), then a clean title
card.

▸ SAY *"Gemini 3.5. Google ADK. Vertex AI Agent Engine. Cloud Run, Firestore,
Cloud Tasks, Cloud Scheduler, Secret Manager. Veo, Lyria, Gemini image, Gemini
TTS, Gemma. A hundred and fifty-four tests, fifty-six architecture decisions on
record. One sentence in — a folder of finished, verified work out, and it keeps
working after you close the tab."*

▸ SHOW  **NEXORA** · `nexora-nexus.vercel.app`

---

## Rubric coverage — where each item lands

| Rubric item | On screen at |
|---|---|
| Gemini 3.5 | badge row (0:40) + workforce narration (1:40) |
| Google ADK (agent framework) | badge row + workforce (1:40) + Agent Engine tab (2:05) |
| Vertex AI Agent Engine (agent platform) | badge row + Agent Engine tab (2:05) |
| Cloud Run | Cloud Run tab (2:00) |
| Cloud Build / reproducible deploy | Cloud Build tab (2:10) |
| Firestore / Cloud Tasks / Cloud Scheduler | narration (2:30) — scale profile; demo runs in-process |
| Model on Vertex AI | badge row "Transport: Vertex AI" (0:40) |
| Google Search grounding | Research Analyst narration (1:40) + the doc's cited facts (2:50) |
| Gemini image | hero image in the montage (0:20) |
| Veo 3.1 | teaser in the montage (0:25) |
| Lyria 2 | jingle under the montage (0:25) |
| Gemini TTS | (optional) add "a spoken briefing" to the hook goal |
| Multimodal | doc + sheet + slides + email + image + video + audio in the montage |
| Autonomous multi-step / Taskmaster | the whole 0:55–2:45 run |
| Verification / failure-tolerance | QA Auditor verdict (2:40) + firewall narration (2:25) |
| Long-running / standing goals | Standing Instructions panel (2:35) |
| Production readiness | live URL + Cloud Console throughout |

## If you want a second live task (only if under 3:30 so far)

15 seconds, right before the close: open the **🗓 schedule** control, add
*"Every weekday 07:00 — brief me on overnight news for our top 3 competitors"*,
hit save. ▸ SAY *"That mission will run itself every morning."*
