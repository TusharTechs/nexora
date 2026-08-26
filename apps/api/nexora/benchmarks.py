"""Benchmark missions — non-scripted goals for evaluation (ADR-049).

Each benchmark is a goal + expected outcomes. Evaluation is deterministic:
artifact types, node statuses, evidence coverage.
"""
from typing import List, Dict
from packages.core.models import Mission


class BenchmarkMission:
    def __init__(self, name: str, goal: str, expected_artifacts: List[str],
                 expected_nodes: List[str], min_evidence: int):
        self.name = name
        self.goal = goal
        self.expected_artifacts = expected_artifacts
        self.expected_nodes = expected_nodes
        self.min_evidence = min_evidence


BENCHMARKS = [
    BenchmarkMission(
        name="Incident Response",
        goal="Investigate the production outage by searching emails, analyze customer complaints, and create an incident report.",
        expected_artifacts=["DOC"],
        expected_nodes=["gmail.search", "docs.create"],
        min_evidence=1,
    ),
    BenchmarkMission(
        name="Financial Analysis",
        goal="Analyze Q3 revenue, review the financial report in Drive, and create a summary deck.",
        expected_artifacts=["DOC", "SLIDES"],
        expected_nodes=["drive.search", "docs.create", "slides.create"],
        min_evidence=2,
    ),
    BenchmarkMission(
        name="Customer Escalation",
        goal="Handle the customer complaint, check the SLA, and schedule a follow-up meeting.",
        expected_artifacts=["DOC", "EVENT"],
        expected_nodes=["gmail.search", "drive.search", "calendar.create_event"],
        min_evidence=2,
    ),
    BenchmarkMission(
        name="Product Launch Prep",
        goal="Prepare for the Feature X launch: analyze the screenshot, create a launch video, and notify the team.",
        expected_artifacts=["ANALYSIS", "VIDEO", "CHAT"],
        expected_nodes=["gmail.search", "multimodal.analyze", "veo.generate_video", "chat.notify"],
        min_evidence=3,
    ),
    BenchmarkMission(
        name="Vendor Negotiation",
        goal="Review the CloudScale contract and prepare a negotiation brief.",
        expected_artifacts=["DOC"],
        expected_nodes=["drive.search", "docs.create"],
        min_evidence=1,
    ),
    BenchmarkMission(
        name="Team Onboarding",
        goal="Prepare onboarding materials for the new hire Alex Kim.",
        expected_artifacts=["DOC", "TASK"],
        expected_nodes=["people.search", "docs.create", "tasks.create"],
        min_evidence=2,
    ),
    BenchmarkMission(
        name="Security Review",
        goal="Review the security audit and create a remediation plan.",
        expected_artifacts=["DOC"],
        expected_nodes=["drive.search", "docs.create"],
        min_evidence=1,
    ),
    BenchmarkMission(
        name="Marketing Campaign",
        goal="Review the Q4 marketing campaign and approve the budget.",
        expected_artifacts=["DOC"],
        expected_nodes=["drive.search", "docs.create"],
        min_evidence=1,
    ),
]


def evaluate_mission(mission: Mission, benchmark: BenchmarkMission) -> Dict:
    """Deterministic evaluation of a benchmark mission."""
    artifact_types = {a.type for a in mission.artifacts}
    node_caps = {n.capability_id for n in mission.nodes if n.status == "SUCCESS"}
    evidence_count = len(mission.evidence)

    artifact_match = set(benchmark.expected_artifacts) <= artifact_types
    node_match = set(benchmark.expected_nodes) <= node_caps
    evidence_match = evidence_count >= benchmark.min_evidence

    score = sum([artifact_match, node_match, evidence_match]) / 3.0

    return {
        "benchmark_name": benchmark.name,
        "mission_id": mission.mission_id,
        "state": mission.state.value,
        "score": round(score, 2),
        "artifact_match": artifact_match,
        "expected_artifacts": benchmark.expected_artifacts,
        "actual_artifacts": sorted(artifact_types),
        "node_match": node_match,
        "expected_nodes": benchmark.expected_nodes,
        "actual_nodes": sorted(node_caps),
        "evidence_match": evidence_match,
        "expected_evidence": benchmark.min_evidence,
        "actual_evidence": evidence_count,
        "pass": score == 1.0,
    }