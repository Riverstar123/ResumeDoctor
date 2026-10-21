"""报告上下文的最小联系方式过滤。

模型只能看到完成报告所需的数据。这里在调用任何网关之前过滤电话、邮箱和
联系方式字段，且只作用于发送副本，绝不修改冻结快照。它与 M3 的 fake 过滤规则
一致，但本模块不复用 M3 的实现，避免 M5 反向依赖 M3。

这是一份有限的模式匹配，不是完整的匿名化：非 fake 网关必须由调用方显式提供
已评审的 `privacy_filter`，否则报告服务 fail closed。
"""

import re
from collections.abc import Mapping
from typing import Any

_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_MOBILE = re.compile(r"(?<!\d)(?:\+?86[ \t-]?)?1[3-9](?:[ \t-]?\d){9}(?!\d)")
_INTERNATIONAL_PHONE = re.compile(r"(?<!\w)\+\d(?:[ \t()-]*\d){6,14}(?!\d)")
_CONTACT_FIELD = re.compile(
    r"(?:电话|手机|联系方式|(?:家庭|居住|详细|联系|通讯|收件)?地址|e-?mail|phone|mobile|address)"
    r"[ \t]*[:：][^\r\n。；;]*",
    re.IGNORECASE,
)

# 过滤后为空的引用仍要维持 Evidence.quote 非空；这不是新的用户证据。
REDACTED_QUOTE = "[联系方式已过滤]"


def filter_report_context(value: Any) -> Any:
    """复制并过滤嵌套值；冻结的快照对象保持不变。"""
    if isinstance(value, str):
        for pattern in (_CONTACT_FIELD, _EMAIL, _MOBILE, _INTERNATIONAL_PHONE):
            value = pattern.sub("", value)
        return value
    if isinstance(value, Mapping):
        return {key: filter_report_context(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [filter_report_context(item) for item in value]
    return value
