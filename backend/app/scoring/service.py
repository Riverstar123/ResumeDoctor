"""Stateless adapter satisfying the shared synchronous ScoringPort."""

from typing import Sequence

from app.contracts import JobContent, ProfileContent, RequirementAssessment, ScoreResult

from .calculator import calculate_score
from .matcher import assess_requirements


class ScoringService:
    def assess_requirements(
        self, profile_content: ProfileContent, job_content: JobContent, matcher_version: str
    ) -> list[RequirementAssessment]:
        return assess_requirements(profile_content, job_content, matcher_version)

    def calculate_score(
        self, assessments: Sequence[RequirementAssessment], rule_version: str
    ) -> ScoreResult:
        return calculate_score(assessments, rule_version)
