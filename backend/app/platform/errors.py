"""Public, intentionally sanitized errors shared by routes and orchestration."""

from app.contracts import ErrorInfo


class PlatformError(Exception):
    def __init__(self, status: int, code: str, message: str, *, retry_after: int | None = None):
        super().__init__(code)
        self.status = status
        self.info = ErrorInfo(code=code, message=message)
        self.retry_after = retry_after


def missing() -> PlatformError:
    return PlatformError(404, "RESOURCE_NOT_FOUND", "资源不存在")


def expired() -> PlatformError:
    return PlatformError(401, "SESSION_EXPIRED", "会话已失效，请重新进入")


def conflict() -> PlatformError:
    return PlatformError(409, "VERSION_CONFLICT", "资料已更新，请刷新后重试")


# A public code is a label, never permission to expose exception text/details.
_TASK_MESSAGES = {
    "FILE_TOO_LARGE": "文件超过大小限制，请缩减后重试",
    "UNSUPPORTED_FILE_TYPE": "文件内容与支持的格式不符，请更换文件或使用对话输入",
    "NO_TEXT_LAYER": "文件没有可提取的文字，请更换文件或使用对话输入",
    "DOCUMENT_PARSE_FAILED": "文件解析失败，请更换文件或使用对话输入",
    "MODEL_TIMEOUT": "模型响应超时，请稍后重试",
    "MODEL_OUTPUT_INVALID": "模型输出不符合要求，请重试",
    "PROVIDER_UNAVAILABLE": "模型服务暂时不可用，请稍后重试",
    "INPUT_TOO_LONG": "输入内容过长，请缩减后重试",
    "TASK_TIMEOUT": "任务已超时",
    "MODEL_UNAVAILABLE": "所选模型不可用或配置已变化，请重新选择后创建任务",
    "VERSION_CONFLICT": "资料已更新，请刷新后重试",
    "VALIDATION_ERROR": "输入内容或格式不符合要求，请检查后重试",
    "NO_SCORABLE_REQUIREMENTS": "岗位没有可评分的要求，请检查岗位内容",
    "INTERNAL_ERROR": "任务处理失败，请稍后重试",
}


def task_error(exc: Exception | ErrorInfo | None) -> ErrorInfo:
    """Sanitize code/message ports and stored errors at every M2 task boundary."""
    if isinstance(exc, TimeoutError):
        code = "TASK_TIMEOUT"
    elif isinstance(exc, PlatformError):
        code = exc.info.code
    elif isinstance(exc, ErrorInfo):
        code = exc.code
    else:
        code = getattr(exc, "code", None)
    if not isinstance(code, str) or code not in _TASK_MESSAGES:
        code = "INTERNAL_ERROR"
    return ErrorInfo(code=code, message=_TASK_MESSAGES[code])
