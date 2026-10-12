"""Uniform JSON errors and safe HTTP middleware, including FastAPI validation."""

import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware

from app.contracts import Error, ErrorInfo
from app.platform.errors import PlatformError

logger = logging.getLogger(__name__)


def error_response(request: Request, status: int, info: ErrorInfo, retry_after=None):
    request_id = getattr(request.state, "request_id", str(uuid4()))
    response = JSONResponse(
        status_code=status, content=Error(error=info, request_id=request_id).model_dump(mode="json")
    )
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    if info.code == "SESSION_EXPIRED":
        response.delete_cookie(
            "rd_session",
            path="/",
            httponly=True,
            samesite="lax",
            secure=request.app.state.settings.session_cookie_secure,
        )
    return response


def install_http(app: FastAPI) -> None:
    settings = app.state.settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key"],
        expose_headers=["Retry-After", "X-Request-ID"],
    )

    @app.exception_handler(PlatformError)
    async def platform_error(request, exc):
        return error_response(request, exc.status, exc.info, exc.retry_after)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not serialize input/ctx/loc: even an extra-field name can contain PII.
        return error_response(
            request, 422, ErrorInfo(code="VALIDATION_ERROR", message="请求字段或格式不合法")
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        codes = {
            400: "VALIDATION_ERROR",
            401: "SESSION_EXPIRED",
            403: "ORIGIN_FORBIDDEN",
            404: "RESOURCE_NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            413: "FILE_TOO_LARGE",
        }
        return error_response(
            request,
            exc.status_code,
            ErrorInfo(code=codes.get(exc.status_code, "INTERNAL_ERROR"), message="请求无法处理"),
        )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        request.state.request_id = str(uuid4())
        api = request.url.path.startswith("/api/v1/")
        try:
            if api:
                platform = app.state.platform
                platform.prune()
                creation = request.url.path == "/api/v1/session" and request.method == "POST"
                session = None
                if not creation and request.method != "OPTIONS":
                    session = platform.repo.authenticate(request.cookies.get("rd_session"))
                if request.method in {"POST", "PUT", "DELETE", "OPTIONS"}:
                    if request.headers.get("origin") not in settings.allowed_origins:
                        raise PlatformError(403, "ORIGIN_FORBIDDEN", "请求来源不允许")
                    if session:
                        platform.write_limit(session)
                if request.url.path == "/api/v1/documents" and request.method == "POST":
                    # Bound the whole multipart request before the parser spools it.
                    data = bytearray()
                    async for chunk in request.stream():
                        data.extend(chunk)
                        if len(data) > 10 * 1024 * 1024 + 65536:
                            raise PlatformError(413, "FILE_TOO_LARGE", "上传请求过大")
                    request._body = bytes(data)
            response = await call_next(request)
        except PlatformError as exc:
            response = error_response(request, exc.status, exc.info, exc.retry_after)
        except Exception:
            logger.error(
                "request_failed request_id=%s code=INTERNAL_ERROR", request.state.request_id
            )
            response = error_response(
                request, 500, ErrorInfo(code="INTERNAL_ERROR", message="服务处理失败")
            )
        if api:
            response.headers["Cache-Control"] = "no-store"
            # Guard-generated errors must also be readable from the allowed origin.
            origin = request.headers.get("origin")
            if origin in settings.allowed_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Access-Control-Expose-Headers"] = "Retry-After, X-Request-ID"
                response.headers["Vary"] = "Origin"
        response.headers["X-Request-ID"] = request.state.request_id
        return response
