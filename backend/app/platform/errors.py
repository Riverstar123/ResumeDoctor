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
