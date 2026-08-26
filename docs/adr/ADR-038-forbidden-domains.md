# ADR-038: Forbidden Domains Enforcement
Status: Accepted.

Decision: MissionConstitution carries `forbidden_domains` and `forbidden_entities`. The
Policy Engine inspects capability inputs (e.g., email `to:` list) and deterministically
BLOCKs any action targeting a forbidden destination. No LLM output can override this.

Consequences: "Send a status email to competitor.com" is blocked even if an LLM
recommended it. The block appears in the Audit Trail.