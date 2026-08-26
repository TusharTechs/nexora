# ADR-040: Firewall Pattern Hardening + Provider Body Contract
Status: Accepted.

Context: Phase 4 test run (4 failed / 18 passed) exposed: (1) the authority-override
regex missed multi-modifier and noun-less injection phrasings; (2) MockWorkspaceProvider
omitted "body" from search results, so the firewall scanned snippets instead of payloads;
(3) FIREWALL_DETECT audit metadata lacked the "quarantined" key.

Decision: Two-tier authority-override patterns (strict 0.95 / loose 0.65); providers
MUST return "body" in search/read results (contract documented on WorkspaceProvider);
FIREWALL_DETECT metadata always includes "quarantined".

Consequences: Known-vector detection has zero false negatives for the seeded corpus;
loose tier yields advisory SUSPICIOUS verdicts rather than silent CLEAN.