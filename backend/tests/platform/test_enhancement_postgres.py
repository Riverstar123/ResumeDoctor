"""Run durable advice scenarios on a real migrated PostgreSQL database."""

# ruff: noqa: F811 -- imported PostgreSQL fixtures are injected by pytest.

import pytest

from . import test_enhancement_sql as cases
from .test_postgres import engine, repo, upload_dir  # noqa: F401


@pytest.mark.parametrize(
    "scenario",
    [
        cases.test_sql_base_and_advice_survive_restart_rejection_and_duplicate_requests,
        cases.test_expired_enhancement_lease_is_not_reissued_or_allowed_to_fail_base,
        cases.test_legacy_report_cannot_start_paid_enhancement,
        cases.test_queued_enhancement_from_old_policy_fails_before_provider_call,
    ],
    ids=["concurrent_dedup_restart_rejection", "expired_lease", "legacy_gate", "frozen_policy"],
)
def test_postgres_optional_advice(repo, engine, tmp_path, scenario):
    scenario(repo, engine.url.render_as_string(hide_password=False), tmp_path)
