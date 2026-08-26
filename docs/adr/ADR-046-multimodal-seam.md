# ADR-046: Multimodal Analysis as a Capability
Status: Accepted. multimodal.analyze is a Capability Network entry routed to the T2 tier.
MOCK returns a deterministic extraction from the seeded screenshot; the real Gemini call
lives behind MultimodalAnalyzer so LIVE swap never touches the runtime. The extraction
is stored on node.outputs["analysis"] and an ANALYSIS artifact feeds the Evidence Graph.