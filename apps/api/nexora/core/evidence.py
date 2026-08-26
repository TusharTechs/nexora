from packages.core.models import Evidence, Artifact

class EvidenceGraph:
    def generate_evidence(self, mission_id: str, claim: str, artifact: Artifact, node_id: str) -> Evidence:
        return Evidence(
            mission_id=mission_id,
            claim=claim,
            sources=[artifact.artifact_id],
            derivation_path=[node_id],
            confidence=1.0,
        )
