# ADR-066: Artifact Composer — real deliverable content

Status: Accepted.

## Context

Through Phase 20 the providers produced *structurally* valid artifacts (a Doc
exists, a Sheet exists, a Slides deck exists) but their **content** was
templated: `docs.create` concatenated upstream snippets, `sheets.create` only
wrote headers, `slides.create` wrote `["Summary", "Impact", "Next steps"]`.
Semantic verification could be satisfied by the *existence* of an artifact whose
body was empty. A judge opening the Drive folder would see placeholders.

## Decision

Introduce `nexora/core/composer.py` — an `ArtifactComposer` that sits in the
Node Executor, between "gather evidence" and "call the provider". For
`docs.create` / `docs.update`, `sheets.create` / `sheets.write`,
`slides.create`, and the media capabilities it calls Gemini (through the Unified
LLM Client / GenAI SDK) with:

- the node's **persona** system prompt,
- the **Outcome Contract** (so content targets the definition of done),
- the **evidence** collected by upstream research/search nodes.

It returns real content: a full Markdown document body, a `{headers, rows}`
spreadsheet (budgets get costed line items and a TOTAL row), a list of
`{title, bullets}` slides, or a production-ready media generation prompt.

Provider signatures stay backward compatible: `create_sheet` gains an optional
`rows=` argument; `create_slides` accepts either `list[str]` (legacy) or
`list[{title, bullets}]`.

## Consequences

- MOCK and LIVE now produce the **same substance** — MOCK stores the composed
  content, LIVE writes it into the real Google file. The demo is compelling in
  either mode.
- Every composer method degrades to a sensible non-empty structure when no LLM
  backend is configured, so the 127 hermetic tests keep passing and missions
  never hard-fail at composition.
- The compiler gains a `_ensure_contract_coverage` pass: any required
  deliverable with no matching capability in the plan gets one appended, so
  semantic verification is not doomed to `PARTIAL` by a thin plan.
- Prompt rule added: the composer must not invent counts/statistics/quotes that
  are not in the evidence.
