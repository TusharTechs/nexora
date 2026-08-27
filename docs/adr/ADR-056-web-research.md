# ADR-056: Web Research Capability
Status: Accepted.

Context: Some Outcome Contracts require external evidence (market data, competitor
analysis, industry facts) that cannot come from the user's workspace. Without a
controlled research capability, NEXORA cannot satisfy these contracts.

Decision: web.research is a controlled capability that searches the web via
Tavily API (or deterministic mock when no key), scans every fetched page through
the Content Firewall BEFORE it enters any LLM prompt, synthesizes findings with
mandatory source citations, and produces RESEARCH artifacts. The LLM cannot
execute arbitrary URLs; web.research is a scoped tool triggered only when the
Outcome Contract sets needs_external_research=True.

Consequences: NEXORA can gather external evidence for market research, competitor
analysis, and fact-finding missions. Every finding is cited. Malicious web content
is quarantined by the firewall before it can poison downstream artifacts.