"""固定合成输出的 IntakePort 测试替身。

用途：让 M2/B/D 在没有真实模型和真实文件的情况下跑通链路（见 02-architecture.md
「Mock 与集成」）。它不读文件、不连数据库、不调用模型，按**已知的固定原文**返回
与 docs/examples/profile.json、docs/examples/job.json 一致的虚构数据。

岗位侧保存**多份 fixture**：集成需要验证「两份不同 JD 各自独立提取」，单份固定输出
会让第二份原文拿到第一份的要求，被 M2 的校验拒绝（#13 集成发现）。因此 `extract_job`
在忽略首尾空白后匹配已知原文；**匹配不到时明确失败**，绝不返回另一份岗位的数据。

档案侧仍按固定输出返回（`build_profile`、`advance_conversation`）：对话是逐轮提交的，
每一轮只是整段素材中的一句，无法用整段匹配。它仍使用固定来源表校验，
不会对传入的任意原文做提取或真实性核验；只能作为明确标记的合成演示使用。
需要验证用户实际输入时应使用 GatewayIntake，不能把该固定档案当成用户事实。

返回前会走一遍本模块的语义校验，因此端口输出始终满足
「引用来自原文、编号唯一、语义完整」这几条约束。
"""

from collections.abc import Callable
from typing import BinaryIO, Sequence

from app.contracts import Evidence, Fact, JobContent, ProfileContent, Requirement
from app.contracts.ports import (
    ConversationResult,
    ExtractedDocument,
    Message,
    TaskContext,
    TextSegment,
)

from .errors import IntakeError
from .validation import validate_job_content, validate_profile_content

SYNTHETIC_SOURCE_ID = "manual-revision-1"
SYNTHETIC_SOURCE_TEXT = (
    "使用 Python 完成课程数据清洗项目。\n了解 SQL 基本语法。\n已获得计算机相关专业本科学位。\n"
)
SYNTHETIC_JOB_RAW_TEXT = "必须有 Python 项目应用经验。\n必须具备 SQL 应用能力。\n熟悉 Docker 优先。\n本科及以上学历优先。"
# 第二份规范合成原文：集成用「两个不同 JD」的验收输入。
KUBERNETES_JOB_RAW_TEXT = "平台运维合成岗位：必须具备 Kubernetes 应用能力。"

SYNTHETIC_SOURCES = {SYNTHETIC_SOURCE_ID: SYNTHETIC_SOURCE_TEXT}


def synthetic_profile_content() -> ProfileContent:
    """与 docs/examples/profile.json 一致的全虚构档案。"""
    return ProfileContent(
        overview="完全虚构的课程演示档案。",
        as_of_month="2026-09",
        facts=[
            Fact(
                id="f1",
                kind="project",
                label="Python",
                value=None,
                polarity="positive",
                application="applied",
                start_month=None,
                end_month=None,
                completed=None,
                evidence_ids=["e1"],
            ),
            Fact(
                id="f2",
                kind="skill",
                label="SQL",
                value=None,
                polarity="positive",
                application="claimed",
                start_month=None,
                end_month=None,
                completed=None,
                evidence_ids=["e2"],
            ),
            Fact(
                id="f3",
                kind="education",
                label="计算机相关专业",
                value="bachelor",
                polarity="positive",
                application="claimed",
                start_month=None,
                end_month=None,
                completed=True,
                evidence_ids=["e3"],
            ),
        ],
        evidence=[
            Evidence(
                id="e1",
                source_type="manual",
                source_id=SYNTHETIC_SOURCE_ID,
                quote="使用 Python 完成课程数据清洗项目。",
                locator=None,
            ),
            Evidence(
                id="e2",
                source_type="manual",
                source_id=SYNTHETIC_SOURCE_ID,
                quote="了解 SQL 基本语法。",
                locator=None,
            ),
            Evidence(
                id="e3",
                source_type="manual",
                source_id=SYNTHETIC_SOURCE_ID,
                quote="已获得计算机相关专业本科学位。",
                locator=None,
            ),
        ],
    )


def synthetic_job_content() -> JobContent:
    """与 docs/examples/job.json 一致的全虚构岗位。"""
    return JobContent(
        title="数据开发课程演示岗位",
        company_name="虚构示例公司",
        company_context="仅用于测试，无真实招聘信息。",
        requirements=[
            Requirement(
                id="r1",
                quote="必须有 Python 项目应用经验。",
                category="skill",
                importance="must",
                operator="has_skill",
                target="Python",
                ignored=False,
                ignore_reason=None,
                subject=None,
            ),
            Requirement(
                id="r2",
                quote="必须具备 SQL 应用能力。",
                category="skill",
                importance="must",
                operator="has_skill",
                target="SQL",
                ignored=False,
                ignore_reason=None,
                subject=None,
            ),
            Requirement(
                id="r3",
                quote="熟悉 Docker 优先。",
                category="skill",
                importance="preferred",
                operator="has_skill",
                target="Docker",
                ignored=False,
                ignore_reason=None,
                subject=None,
            ),
            Requirement(
                id="r4",
                quote="本科及以上学历优先。",
                category="education",
                importance="preferred",
                operator="degree_at_least",
                target="bachelor",
                ignored=False,
                ignore_reason=None,
                subject=None,
            ),
        ],
    )


def kubernetes_job_content() -> JobContent:
    """第二份合成岗位：供集成验证两份不同 JD 的独立提取。"""
    return JobContent(
        title="平台运维合成岗位",
        company_name=None,
        company_context="仅用于合成的平台运维演示岗位。",
        requirements=[
            Requirement(
                id="r1",
                quote="必须具备 Kubernetes 应用能力。",
                category="skill",
                importance="must",
                operator="has_skill",
                target="Kubernetes",
                ignored=False,
                ignore_reason=None,
                subject=None,
            ),
        ],
    )


# 已知规范原文 → fixture。按原文精确匹配，未知输入不予处理。
SYNTHETIC_JOB_FIXTURES: dict[str, Callable[[], JobContent]] = {
    SYNTHETIC_JOB_RAW_TEXT: synthetic_job_content,
    KUBERNETES_JOB_RAW_TEXT: kubernetes_job_content,
}


class SyntheticIntake:
    """固定输出的 IntakePort 实现；按已知的规范原文返回对应 fixture。"""

    def __init__(self, assistant_message: str | None = None):
        self.assistant_message = assistant_message or (
            "这是合成数据的示例追问：这个项目里你具体负责哪一部分？"
        )

    async def extract_document(self, handle: BinaryIO, media_type: str) -> ExtractedDocument:
        return ExtractedDocument(
            text=SYNTHETIC_SOURCE_TEXT,
            segments=(TextSegment(text=SYNTHETIC_SOURCE_TEXT, locator="page:1"),),
            warnings=(),
        )

    async def build_profile(
        self,
        text: str,
        source_type: str,
        previous_profile=None,
        *,
        context: TaskContext,
    ) -> ProfileContent:
        return validate_profile_content(synthetic_profile_content(), SYNTHETIC_SOURCES).content

    async def advance_conversation(
        self,
        user_text: str,
        profile_content: ProfileContent,
        history_user_messages: Sequence[Message],
        *,
        context: TaskContext,
    ) -> ConversationResult:
        return ConversationResult(
            assistant_message=self.assistant_message,
            profile_content=validate_profile_content(
                synthetic_profile_content(), SYNTHETIC_SOURCES
            ).content,
        )

    async def extract_job(
        self,
        raw_text: str,
        company_context: str,
        *,
        context: TaskContext,
    ) -> JobContent:
        fixture = SYNTHETIC_JOB_FIXTURES.get(raw_text.strip())
        if fixture is None:
            raise IntakeError(
                "UNKNOWN_SYNTHETIC_INPUT",
                "合成端口只识别已知的演示原文，没有这份输入对应的合成岗位；"
                "集成请改用 IN-02 的 GatewayIntake，或为该原文补充 fixture。",
            )
        content = fixture()
        if company_context:
            # 公司背景是用户输入而非模型提取，原样带进结果。
            content = content.model_copy(update={"company_context": company_context})
        return validate_job_content(content, raw_text).content
