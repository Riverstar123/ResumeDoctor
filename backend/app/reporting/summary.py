"""Keep generated analysis separate from the program-owned diagnosis score."""

import re

_SCORE_CLAIM = re.compile(
    r"(?:总分|覆盖分|匹配分|匹配度|(?:当前|本次|简历|岗位|综合|自动|规则)(?:的)?(?:评分|得分|分数)"
    r"|^(?:你的|您的)?(?:评分|得分|分数))\s*(?:为|是|达(?:到)?|[：:])?\s*"
    r"(?:[0-9]+(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百]+(?:点[零〇一二两三四五六七八九]+)?)"
    r"(?=\s*(?:分|[%％/／]|[（(]|$))"
)
_SEPARATOR = re.compile(r"([，,；;。！？!?\n]+|\.(?=\s|$))")


def without_score_claims(summary: str) -> str:
    parts = _SEPARATOR.split(summary)
    result = "".join(
        part + (parts[index + 1] if index + 1 < len(parts) else "")
        for index, part in enumerate(parts)
        if index % 2 == 0 and not _SCORE_CLAIM.search(part.strip())
    )
    return summary if result == summary else re.sub(r"[，,；;]+$", "。", result.strip())
