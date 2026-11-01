"""Replay synthetic real-extraction snapshots without network or wall-clock scoring."""

import json
from pathlib import Path

import pytest

from app.contracts import JobContent, ProfileContent
from app.scoring import ScoringService

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/exploratory_scoring.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["case"])
def test_synthetic_real_extraction_retains_expected_coverage(case):
    profile = ProfileContent.model_validate(FIXTURE["profile_content"])
    job = JobContent.model_validate(case["job_content"])
    service = ScoringService()
    assessments = service.assess_requirements(profile, job, "matcher-v1")
    score = service.calculate_score(assessments, "coverage-v1")
    assert score.score == case["expected_score"]
    if case["case"] == "mixed":
        by_target = {r.target: a.status for r, a in zip(job.requirements, assessments)}
        assert by_target == {"Excel": "partial", "Docker": "unmet", "Kubernetes": "unknown"}
