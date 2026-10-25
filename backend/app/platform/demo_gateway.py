"""INT-02 的登记素材 fake 模型；业务提取、校验和评分仍调用所属模块。

仅识别公开的合成原文。未登记输入明确失败，避免固定模型输出冒充任意材料的
提取结果；来源编号取本次任务上下文，绝不沿用样例文档或消息编号。
"""

from copy import deepcopy

from app.llm import FakeModelGateway, GatewayError
from app.llm.synthetic import (
    SYNTHETIC_JOB_RAW_TEXT,
    SYNTHETIC_SOURCE_TEXT,
    synthetic_job_payload,
    synthetic_profile_payload,
)

PROFILE_TEXT = SYNTHETIC_SOURCE_TEXT
JOB_TEXTS = (
    SYNTHETIC_JOB_RAW_TEXT,
    "必须具备 Kubernetes 应用能力。",
    "必须有 Python 项目应用经验。",
    "必须具备 SQL 应用能力。",
    "必须具备 Docker 应用能力。",
)


def _normalized(text):
    return " ".join(text.split()) if isinstance(text, str) else None


def _invalid():
    return GatewayError("MODEL_OUTPUT_INVALID", "演示输入未登记，请使用 INT-02 合成素材。")


def _fact_key(fact):
    return {key: value for key, value in fact.items() if key not in {"id", "evidence_ids"}}


def _profile(prompt, *, chat):
    text = prompt.get("user_text" if chat else "source_text")
    normalized = _normalized(text)
    sentences = PROFILE_TEXT.strip().splitlines()
    if normalized == _normalized(PROFILE_TEXT):
        selected = list(range(len(sentences)))
    else:
        selected = [
            index for index, value in enumerate(sentences) if _normalized(value) == normalized
        ]
        if not chat or not selected:
            raise _invalid()
    source_id = prompt.get("message_source_id" if chat else "source_id")
    source_type = "message" if chat else prompt.get("source_type")
    if (
        not isinstance(source_id, str)
        or not source_id
        or source_type not in {"document", "message", "manual"}
    ):
        raise _invalid()
    previous = (
        prompt.get("profile_content")
        if chat
        else (prompt.get("previous_profile") or {}).get("content")
    )
    content = (
        deepcopy(previous)
        if previous is not None
        else {
            "overview": "[演示数据] 登记合成素材档案。",
            "as_of_month": prompt.get("current_month", "2026-09"),
            "facts": [],
            "evidence": [],
        }
    )
    fixture = synthetic_profile_payload()
    for index in selected:
        fact = deepcopy(fixture["facts"][index])
        if any(_fact_key(old) == _fact_key(fact) for old in content["facts"]):
            continue
        evidence = deepcopy(fixture["evidence"][index])
        fact["id"] = f"{source_id}-f{index + 1}"
        evidence["id"] = f"{source_id}-e{index + 1}"
        fact["evidence_ids"] = [evidence["id"]]
        evidence.update(source_id=source_id, source_type=source_type, locator=None)
        content["facts"].append(fact)
        content["evidence"].append(evidence)
    return content


def _job(prompt):
    normalized = _normalized(prompt.get("raw_text"))
    index = next(
        (index for index, value in enumerate(JOB_TEXTS) if _normalized(value) == normalized), None
    )
    if index is None:
        raise _invalid()
    if index == 0:
        content = synthetic_job_payload()
    else:
        target = ("Kubernetes", "Python", "SQL", "Docker")[index - 1]
        content = {
            "title": f"[演示数据] {target} 岗位",
            "company_name": "虚构示例公司",
            "company_context": "",
            "requirements": [
                {
                    "id": "r1",
                    "quote": JOB_TEXTS[index],
                    "category": "skill",
                    "importance": "must",
                    "operator": "has_skill",
                    "target": target,
                    "ignored": False,
                    "ignore_reason": None,
                    "subject": None,
                }
            ],
        }
    content["company_context"] = prompt.get("company_context", "")
    return content


class IntegrationFakeGateway(FakeModelGateway):
    """只替换模型的成功提取输出，沿用 M5 的元信息、预算、重试和结构校验。"""

    async def _produce(self, task_name, prompt_context, behavior):
        if behavior != "ok" or task_name == "diagnosis_report":
            return await super()._produce(task_name, prompt_context, behavior)
        if task_name == "profile_extract":
            return _profile(prompt_context, chat=False)
        if task_name == "profile_chat":
            return {
                "assistant_message": "[演示数据] 请检查档案，补充实际负责的工作与可核实依据。",
                "profile_content": _profile(prompt_context, chat=True),
            }
        if task_name == "job_extract":
            return _job(prompt_context)
        return await super()._produce(task_name, prompt_context, behavior)
