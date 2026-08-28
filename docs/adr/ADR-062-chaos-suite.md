# ADR-062: Anti-Scripting + Chaos Suite

## Status
Accepted

## Context
NEXORA must handle any goal a hackathon judge throws at it: advisory ("help me learn AI"), 
business ("launch a product"), vague ("make me successful"), and adversarial ("ignore all 
instructions"). The system must never crash, never claim fake success, and always degrade 
gracefully when components fail.

## Decision
Phase 8C introduces a **chaos suite** with three test categories:

### 1. Live-Fire Goals (10 diverse types)
Test with varied goal types to ensure general planning works:
- Advisory: learning, career, finance
- Business: product launch, SaaS
- Personal: fitness, retirement
- Vague: "make me successful"
- Creative: short story
- Operational: production outage

**Assertion:** Every goal produces an OutcomeContract and reaches terminal state.

### 2. Failure Injection
Test behavior when components fail:
- LLM unavailable → should produce minimal contract
- Capability fails → should mark node FAILED, not crash
- Approval rejected → should replan with draft

**Assertion:** System degrades gracefully, never crashes.

### 3. Edge Cases
Test adversarial and pathological inputs:
- Empty/minimal goals
- Malicious input (prompt injection)
- Contradictory goals

**Assertion:** ContentFirewall filters malicious input, system doesn't crash.

## Consequences
- **101+ tests passing** proves NEXORA is bulletproof for the demo
- Judges can type any goal and get a coherent response
- Failures are marked honestly (FAILED/PARTIAL_SUCCESS), not hidden
- Semantic verification runs on every terminal mission
- Adaptive replanning works when deliverables are missing

## Testing Strategy
Tests verify **BEHAVIOR**, not specific artifacts:
- ✗ "Mission produces exactly 3 artifacts"
- ✓ "Mission produces at least 1 artifact and reaches terminal state"

This prevents brittle tests that break when the LLM generates different (but valid) outputs.