from packages.core.models import VerificationResult

class VerificationAgent:
    """A mission cannot reach COMPLETED unless verification passes."""
    def __init__(self, registry):
        self.registry = registry

    async def verify(self, mission_id, intent, artifacts) -> VerificationResult:
        if not artifacts:
            return VerificationResult(mission_id=mission_id, objective_completion=False,
                                      artifact_existence=False, evidence_coverage=0.0,
                                      overall_status="FAIL", failure_reasons=["No artifacts produced"])
        results = [await self.registry.provider.verify_artifact(a) for a in artifacts]
        verified = sum(results)
        all_ok = verified == len(artifacts)
        return VerificationResult(
            mission_id=mission_id,
            objective_completion=all_ok,
            artifact_existence=all_ok,
            evidence_coverage=verified / len(artifacts),
            overall_status="PASS" if all_ok else "FAIL",
            failure_reasons=[] if all_ok else [f"{len(artifacts) - verified} artifact(s) unverifiable"],
        )
