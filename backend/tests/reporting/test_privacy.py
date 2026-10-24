"""QA25-01: report contact filtering preserves text and has bounded CPU cost."""

import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from app.reporting.privacy import filter_report_context


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("技能 Python；邮箱 candidate@example.invalid。", "技能 Python；邮箱 。"),
        ("a@b.co+z@domain.invalid", ""),
        ("a@b.cox-y@z.com", ""),
        ("中文Ka@example.invalid中文", "中文中文"),
        ("README.md / C++ / A_B-C%+ / 成果 2026", "README.md / C++ / A_B-C%+ / 成果 2026"),
        ("local-part@domain-without-a-dot", "local-part@domain-without-a-dot"),
    ],
)
def test_email_filter_keeps_text_and_removes_adjacent_contacts(raw, expected):
    original = {"evidence": [{"quote": raw}], "history": (raw,)}
    frozen = deepcopy(original)

    filtered = filter_report_context(original)

    assert filtered == {"evidence": [{"quote": expected}], "history": [expected]}
    assert original == frozen


def test_long_non_email_input_finishes_within_an_isolated_process_budget():
    # A confirmed profile can hold values above the report gateway's input budget,
    # and filtering runs before that budget. The watchdog bounds this regression;
    # it is not a production throughput benchmark.
    program = """
from app.reporting.privacy import filter_report_context
for value in ('a' * 100_000, 'a' * 50_000 + '@' + 'b' * 50_000):
    payload = {'previous_profile': {'evidence': [{'quote': value}]}}
    assert filter_report_context(payload) == payload
print('report-filter-completed')
"""
    try:
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", program],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=6,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Report contact filtering exceeded its six-second subprocess watchdog")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "report-filter-completed"
