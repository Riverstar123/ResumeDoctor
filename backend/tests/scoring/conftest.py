"""Small, wholly synthetic DTO factories shared by the M4 boundary tests."""

import pytest

from app.contracts import Evidence, Fact, JobContent, ProfileContent, Requirement


@pytest.fixture
def fact():
    def make(id="f1", label="Python", kind="skill", **changes):
        values = dict(
            id=id,
            label=label,
            kind=kind,
            value=None,
            polarity="positive",
            application="claimed",
            start_month=None,
            end_month=None,
            completed=None,
            evidence_ids=[f"e-{id}"],
        )
        values.update(changes)
        return Fact.model_validate(values)

    return make


@pytest.fixture
def profile():
    def make(facts=(), as_of="2026-01"):
        ids = sorted({id for f in facts for id in f.evidence_ids})
        return ProfileContent(
            overview="完全虚构的 M4 边界测试档案。",
            as_of_month=as_of,
            facts=list(facts),
            evidence=[
                Evidence(
                    id=id,
                    source_type="manual",
                    source_id="synthetic-revision",
                    quote=f"合成事实引用 {id}，不代表真实简历。",
                    locator=None,
                )
                for id in ids
            ],
        )

    return make


@pytest.fixture
def requirement():
    def make(id="r1", target="Python", operator="has_skill", **changes):
        values = dict(
            id=id,
            target=target,
            operator=operator,
            quote="合成 JD 要求。",
            category="skill",
            importance="must",
            subject=None,
            ignored=False,
            ignore_reason=None,
        )
        values.update(changes)
        return Requirement.model_validate(values)

    return make


@pytest.fixture
def job():
    def make(requirements):
        return JobContent(
            title="虚构测试岗位",
            company_name=None,
            company_context="只用于合成测试。",
            requirements=list(requirements),
        )

    return make
