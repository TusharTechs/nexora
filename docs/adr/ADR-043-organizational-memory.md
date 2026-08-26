# ADR-043: Organizational Memory & Taught Policies
Status: Accepted. Memory entries carry scope/type/provenance and an optional deterministic
effect (forbid | require_approval). Taught policies flow into ConstitutionBuilder
(forbidden_actions) and PolicyEngine (approval overrides). Extraction is a sealed
deterministic verb set; unknown sentences store as FACTs. Rejections and interventions
record CORRECTION entries.