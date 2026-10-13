"""Pure M4 scoring: importing this module has no model/database/network side effects."""

from .calculator import MATCHER_VERSION, RULE_VERSION, calculate_score
from .errors import ScoringError
from .matcher import PreparedJob, assess_requirements, prepare_job
from .service import ScoringService

__all__ = [
    "MATCHER_VERSION",
    "RULE_VERSION",
    "ScoringError",
    "calculate_score",
    "PreparedJob",
    "assess_requirements",
    "prepare_job",
    "ScoringService",
]
