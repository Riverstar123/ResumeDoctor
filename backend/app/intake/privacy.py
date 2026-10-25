"""Local fake-context contact filtering; real gateways need an explicit policy.

These bounded patterns cover ordinary contact examples, not arbitrary-address
anonymization. GatewayIntake fails closed for non-fake gateways without a caller
provided filter reviewed for the actual provider and data policy.
"""

import re
from collections.abc import Mapping
from typing import Any

# Consume a whole non-email local-part run rather than retrying its every suffix.
# A lookbehind alone would miss adjacent contacts after a previous email match.
_EMAIL_OR_TEXT = re.compile(
    r"(?P<email>[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})|[A-Z0-9._%+-]+",
    re.IGNORECASE,
)
_MOBILE = re.compile(r"(?<!\d)(?:\+?86[ \t-]?)?1[3-9](?:[ \t-]?\d){9}(?!\d)")
_INTERNATIONAL_PHONE = re.compile(r"(?<!\w)\+\d(?:[ \t()-]*\d){6,14}(?!\d)")
_CONTACT_FIELD = re.compile(
    r"(?:电话|手机|联系方式|(?:家庭|居住|详细|联系|通讯|收件)?地址|e-?mail|phone|mobile|address)"
    r"[ \t]*[:：][^\r\n。；;]*",
    re.IGNORECASE,
)


def filter_fake_context(value: Any) -> Any:
    """Copy and filter all nested values; never modify saved facts/evidence."""
    if isinstance(value, str):
        value = _CONTACT_FIELD.sub("", value)
        value = _EMAIL_OR_TEXT.sub(
            lambda match: "" if match.lastgroup == "email" else match.group(0), value
        )
        for pattern in (_MOBILE, _INTERNATIONAL_PHONE):
            value = pattern.sub("", value)
        return value
    if isinstance(value, Mapping):
        return {key: filter_fake_context(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [filter_fake_context(item) for item in value]
    return value
