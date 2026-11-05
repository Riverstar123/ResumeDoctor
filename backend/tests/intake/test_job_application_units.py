"""A tool applied to a task contributes one requirement, with independent skills retained."""

import asyncio
from time import perf_counter
from unittest.mock import Mock

import pytest

from app.contracts import JobContent, Requirement
from app.intake import GatewayIntake, IntakeError, validate_job_content, validation
from tests.intake.test_gateway_intake import CONTEXT, StubGateway


def job(quote, targets):
    return JobContent(
        title="合成岗位",
        company_name=None,
        company_context="",
        requirements=[
            Requirement(
                id=f"r{index}",
                quote=quote,
                category="skill",
                importance="must",
                operator="has_skill",
                target=target,
                subject=None,
                ignored=False,
                ignore_reason=None,
            )
            for index, target in enumerate(targets, 1)
        ],
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_extract_job_coalesces_tool_and_its_same_application(reverse):
    quote = "能用 Python 清洗和分析金融数据"
    content = job(quote, ["Python", "金融数据清洗与分析"])
    if reverse:
        content.requirements.reverse()
    original = content.model_dump(mode="json")
    gateway = StubGateway({"job_extract": original})
    result = asyncio.run(GatewayIntake(gateway).extract_job(quote, "", context=CONTEXT))
    assert len(result.requirements) == 1
    assert result.requirements[0].target == "Python"
    assert result.requirements[0].quote == quote
    assert content.model_dump(mode="json") == original


@pytest.mark.parametrize(
    "quote, targets",
    [
        ("具备 Python 和 SQL 应用能力", ["Python", "SQL"]),
        ("能独立撰写行业报告，也能独立搭建估值模型", ["行业报告撰写", "估值建模"]),
        ("用 Python 清洗数据，同时熟悉 SQL", ["Python", "SQL"]),
        ("不用 Python 分析金融数据", ["Python", "金融数据分析"]),
        ("用 Python 分析金融数据，但还需金融数据清洗能力", ["Python", "金融数据清洗"]),
        ("用 Python 分析金融数据", ["Python", "信用风险模型开发"]),
    ],
)
def test_independent_or_uncertain_requirements_are_preserved(quote, targets):
    content = job(quote, targets)
    result = validate_job_content(content, quote)
    assert result.content == content


@pytest.mark.parametrize("targets", [["Excel", "制作财务图表"], ["Excel", "财务图表制作"]])
def test_explicit_same_action_forms_merge_without_hardcoding_python(targets):
    quote = "使用 Excel 制作财务图表。"
    result = validate_job_content(job(quote, targets), quote)
    assert [r.target for r in result.content.requirements] == ["Excel"]
    assert result.warnings


def test_ignored_conflict_is_not_silently_merged():
    quote = "用 Python 清洗数据"
    content = job(quote, ["Python", "数据清洗"])
    content.requirements[1].ignored = True
    content.requirements[1].ignore_reason = "用户排除"
    with pytest.raises(IntakeError) as error:
        validate_job_content(content, quote)
    assert error.value.code == "REQUIREMENT_CONFLICT"


def test_other_operator_and_different_quote_are_not_removed():
    quote = "用 Python 分析金融数据"
    content = job(quote, ["Python", "金融数据分析"])
    content.requirements[1].operator = "has_evidence"
    assert len(validate_job_content(content, quote).content.requirements) == 2
    content.requirements[1].operator = "has_skill"
    content.requirements[1].quote = "还需金融数据分析能力"
    assert (
        len(validate_job_content(content, quote + "，还需金融数据分析能力").content.requirements)
        == 2
    )


@pytest.mark.parametrize(
    "quote",
    [
        "用 Python" + " " * 10000 + "，分析数据",
        "用 Python" + " " * 10000 + "分析数据，",
        "用 Python 分析" + "和分析" * 6000 + "数据，",
        "用 " + "Long Tool " * 1800 + "，分析数据",
    ],
    ids=["reviewer-spaces", "trailing-punctuation", "repeated-actions", "long-tool"],
)
def test_long_nonmatching_clauses_do_not_block_validation(quote):
    # Inputs fit the public JD limit. A one-second budget leaves ample machine
    # headroom while catching the multi-second backtracking regression.
    assert len(quote) <= 20000
    content = job(quote, ["Python", "Python"])
    original = content.model_dump()
    start = perf_counter()
    result = validate_job_content(content, quote)
    elapsed = perf_counter() - start
    assert elapsed < 1.0, f"JD validation took {elapsed:.3f}s"
    assert [r.target for r in result.content.requirements] == ["Python"]
    assert result.content.requirements[0].quote == quote
    assert content.model_dump() == original


@pytest.mark.parametrize(
    "tool", ["Power BI", "Visual Studio Code", "C++", "C#", "Node.js", "scikit-learn"]
)
@pytest.mark.parametrize("separator", ["", " " * 10000, "\t\n\u3000"])
def test_tool_names_and_spacing_keep_source_and_application(tool, separator):
    quote = f"能用 {tool}{separator}分析金融数据。"
    content = job(quote, ["金融数据分析", tool])
    original = content.model_dump()
    result = validate_job_content(content, quote)
    assert [r.target for r in result.content.requirements] == [tool]
    assert result.content.requirements[0].quote == quote
    assert content.model_dump() == original


@pytest.mark.parametrize("quote", ["用 Python 分析数据", "用 Python，分析数据"])
def test_each_clause_is_parsed_once_and_cache_does_not_survive_a_call(monkeypatch, quote):
    parser = Mock(wraps=validation._TOOL_TASK)
    monkeypatch.setattr(validation, "_TOOL_TASK", parser)
    # The tool arrives last: a task seen first must not hide a later tool.
    content = job(quote, ["数据分析"] * 30 + ["Python"])
    first = validate_job_content(content, quote)
    assert parser.fullmatch.call_count == 1
    expected = ["Python"] if "，" not in quote else ["数据分析", "Python"]
    assert [r.target for r in first.content.requirements] == expected
    validate_job_content(content, quote)
    assert parser.fullmatch.call_count == 2


def test_similar_but_different_quotes_do_not_share_tool_bindings():
    quote = "用 Python 分析数据"
    content = job(quote, ["Python", "数据分析"])
    content.requirements[1].quote = "用 Python   分析数据"
    raw = quote + "\n" + content.requirements[1].quote
    assert validate_job_content(content, raw).content == content


def test_ambiguous_action_suffix_retains_previous_nonempty_object_behavior():
    quote = "用 Python 分析和分析"
    result = validate_job_content(job(quote, ["Python", "和分析分析"]), quote)
    assert [r.target for r in result.content.requirements] == ["Python"]
