# ADR-076: One node → one deliverable, plus a real design pass

Status: Accepted.

## Context

Two things undermined the artifacts NEXORA hands back:

1. **Scope bleed.** Every composer (`compose_document`, `compose_slides`,
   `compose_sheet`, `compose_email`) received the *whole* mission objective as
   its brief. For a goal like "a guide document, a slide deck, a budget
   spreadsheet, and a summary email", the document composer dutifully wrote all
   four — a single Doc with sections titled "Slide 1", "Slide 2", "Draft Summary
   Email", "Hero Image", the email body pasted inline, and `[Your Name]`
   placeholders in the sign-off.
2. **Dull rendering.** `formatting.py` set one accent colour and left everything
   else at Google's defaults — Arial, single line spacing, no title treatment,
   plain white slides.

The planner also only ever assigned placeholder inputs to outward actions
(`customer@acme.dev`, "tomorrow at 10am"), so a LIVE `calendar.create_event` or
`gmail.send` ignored the address and time the user actually named.

## Decision

**Scoped deliverables.** `NodeExecutor._deliverable_brief(mission, node)` matches
the node's capability to one entry in the contract's `required_deliverables` and
passes just that as `deliverable=` to the composer. Each composer prompt now
opens with «this exact deliverable» and is told explicitly that the deck / sheet
/ email / image are produced separately and must not appear here.

**Placeholder scrub.** `composer._clean_output()` removes bracketed template
tokens (`[Your Name]`, `[Date]`, `[Company]`, …) from every composed doc, slide,
and email, and rewrites a stranded "Best,\n" into "— NEXORA".

**Entity extraction** (`nexora/core/extractors.py`). `emails(text)` and
`event_datetime(text)` pull real recipients and "at 11am tomorrow" style times
out of the goal. The Node Executor uses them to override the planner's
placeholders for `gmail.send/draft` and `calendar.create_event`.
`create_event(..., start=, description=, duration_min=)` now honours the
requested time, real attendees, the primary calendar's own timezone, a Meet
link, and `sendUpdates='all'` — added across the live, mock, and replay
providers and the provider protocol.

**Design pass** in `formatting.py`:
- *Docs* — Poppins headings, Lora body, a 26pt accent title with a hairline
  rule under it, a real heading-size scale, 1.18 line spacing.
- *Slides* — a deep-accent full-bleed title slide with white display type; a
  slim accent bar down the left of every content slide; Poppins titles, Lora
  bodies, comfortable bullet spacing.
- *Email* — gradient header, an accent keyline, a tighter type scale, and a
  footer that says what NEXORA actually did.

## Consequences

- The document is now the document. QA verification stops seeing "the guide only
  covers 2 of 5 things" because the guide is no longer diluted by four other
  deliverables crammed into it.
- LIVE calendar and email actions land where and when the user asked.
- Fonts (`Poppins`, `Lora`) are standard Google Fonts in the Docs/Slides menu;
  if a viewer lacks them the app falls back to a system face and the document is
  unharmed.
