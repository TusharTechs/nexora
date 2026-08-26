# ADR-045: Replay Mode via ReplayProvider
Status: Accepted. Replay missions execute against a provider seeded from the source
mission's artifacts/outputs, returning identical URIs. No live or mock state is touched;
receipts carry execution_mode=REPLAY for audit clarity.