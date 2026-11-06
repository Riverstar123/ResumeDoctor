"""Shared date semantics for extraction and persisted profile snapshots."""

from app.contracts import Fact


def invalid_future_end(fact: Fact, as_of_month: str) -> bool:
    if not fact.end_month or fact.end_month <= as_of_month:
        return False
    # A stated expected graduation is not completed education or earned tenure.
    return not (
        fact.kind == "education"
        and fact.completed is False
        and (fact.start_month is None or fact.start_month <= as_of_month)
    )
