from packages.core.models import MissionHealth, Mission

class HealthCalculator:
    def calculate(self, mission: Mission) -> MissionHealth:
        total = len(mission.nodes)
        completed = sum(1 for n in mission.nodes if n.status == "SUCCESS")
        pct = (completed / total * 100) if total > 0 else 0.0
        return MissionHealth(
            mission_id=mission.mission_id,
            completion_percentage=pct,
            evidence_coverage=1.0 if mission.verification and mission.verification.evidence_coverage > 0 else 0.0,
            current_execution_state=mission.state,
        )
