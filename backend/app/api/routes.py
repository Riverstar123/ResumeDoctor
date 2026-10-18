"""Thin HTTP boundary; ownership, versions and task work live in the platform."""

import io
import zipfile
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.security import APIKeyCookie

from app.contracts import (
    Confirmation,
    Diagnosis,
    DiagnosisAccepted,
    DiagnosisCreate,
    Error,
    Job,
    JobCreate,
    JobUpdate,
    MessageCreate,
    MessageList,
    ModelList,
    Profile,
    ProfileCreate,
    ProfileUpdate,
    Session,
    SessionCreate,
    Task,
    TaskAccepted,
)
from app.contracts.models import UUIDValue
from app.platform.errors import PlatformError
from app.platform.repositories import SessionRecord
from app.platform.service import Platform

MAX_FILE = 10 * 1024 * 1024
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class WireUploadFile(UploadFile):
    """Keep the checked-in OpenAPI binary form schema on newer FastAPI versions."""

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        return {"type": "string", "format": "binary"}


cookie = APIKeyCookie(name="rd_session", scheme_name="sessionCookie", auto_error=False)
ERROR_RESPONSES = {
    status: {"model": Error} for status in (401, 403, 404, 409, 413, 415, 422, 429, 500)
}
ERROR_RESPONSES[429]["headers"] = {"Retry-After": {"schema": {"type": "integer", "minimum": 1}}}


def get_platform(request: Request) -> Platform:
    return request.app.state.platform


def session_dependency(
    platform: Annotated[Platform, Depends(get_platform)],
    token: Annotated[str | None, Depends(cookie)],
) -> SessionRecord:
    return platform.repo.authenticate(token)


Service = Annotated[Platform, Depends(get_platform)]
SessionDep = Annotated[SessionRecord, Depends(session_dependency)]
ResourceID = Annotated[UUIDValue, Path(json_schema_extra={"format": "uuid"})]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)]
router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)


def set_session_cookie(
    response: Response, platform: Platform, session: SessionRecord, token: str, secure: bool
):
    response.set_cookie(
        "rd_session",
        token,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
        max_age=max(1, int((session.expires_at - platform.repo.clock()).total_seconds())),
        expires=session.expires_at,
    )


@router.post(
    "/session",
    response_model=Session,
    tags=["platform"],
    operation_id="createSession",
    responses={200: {"headers": {"Set-Cookie": {"schema": {"type": "string"}}}}},
    openapi_extra={"security": []},
)
async def create_session(
    body: SessionCreate, request: Request, response: Response, platform: Service
):
    token = request.cookies.get("rd_session")
    if token:
        session = platform.repo.authenticate(token)
    else:
        session, token = platform.repo.create_session()
    platform.write_limit(session)
    set_session_cookie(
        response, platform, session, token, request.app.state.settings.session_cookie_secure
    )
    return session.public


@router.delete(
    "/session",
    status_code=204,
    response_class=Response,
    tags=["platform"],
    operation_id="deleteSession",
)
async def delete_session(request: Request, platform: Service, session: SessionDep):
    platform.revoke(session.public.id)
    response = Response(status_code=204)
    response.delete_cookie(
        "rd_session",
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.session_cookie_secure,
    )
    return response


@router.get("/models", response_model=ModelList, tags=["models"], operation_id="listModels")
async def models(platform: Service, session: SessionDep):
    return platform.catalog.list_models()


@router.post(
    "/profiles",
    status_code=201,
    response_model=Profile,
    tags=["profiles"],
    operation_id="createProfile",
)
async def create_profile(
    body: ProfileCreate, platform: Service, session: SessionDep, key: IdempotencyKey
):
    return platform.profile_create(session.public.id, body, key)


@router.get("/profiles/{id}", response_model=Profile, tags=["profiles"], operation_id="getProfile")
async def get_profile(
    id: ResourceID, platform: Service, session: SessionDep, version: int = Query(default=None, ge=1)
):
    return platform.repo.version(platform.repo.profiles, id, session.public.id, version)


@router.put(
    "/profiles/{id}", response_model=Profile, tags=["profiles"], operation_id="updateProfile"
)
async def update_profile(
    id: ResourceID, body: ProfileUpdate, platform: Service, session: SessionDep
):
    return platform.profile_update(session.public.id, id, body)


@router.post(
    "/profiles/{id}/confirm",
    response_model=Profile,
    tags=["profiles"],
    operation_id="confirmProfile",
)
async def confirm_profile(
    id: ResourceID, body: Confirmation, platform: Service, session: SessionDep
):
    return platform.repo.confirm(platform.repo.profiles, id, session.public.id, body.version)


@router.get(
    "/profiles/{id}/messages",
    response_model=MessageList,
    tags=["intake"],
    operation_id="listMessages",
)
async def get_messages(id: ResourceID, platform: Service, session: SessionDep):
    record = platform.repo.owned(platform.repo.profiles, id, session.public.id)
    return MessageList(items=[m.model_copy(deep=True) for m in record.messages])


@router.post(
    "/profiles/{id}/messages",
    status_code=202,
    response_model=TaskAccepted,
    tags=["intake"],
    operation_id="createMessage",
)
async def create_message(
    id: ResourceID, body: MessageCreate, platform: Service, session: SessionDep, key: IdempotencyKey
):
    return platform.chat(session.public.id, id, body, key)


@router.post(
    "/documents",
    status_code=202,
    response_model=TaskAccepted,
    tags=["intake"],
    operation_id="uploadDocument",
    openapi_extra={
        "requestBody": {
            "content": {"multipart/form-data": {"schema": {"additionalProperties": False}}}
        }
    },
)
async def document(
    request: Request,
    platform: Service,
    session: SessionDep,
    key: IdempotencyKey,
    file: Annotated[WireUploadFile, File()],
    model_id: Annotated[str, Form(min_length=1, max_length=100)],
):
    form = await request.form()
    if sorted(k for k, _ in form.multi_items()) != ["file", "model_id"]:
        raise PlatformError(422, "VALIDATION_ERROR", "上传字段不合法")
    data = await file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise PlatformError(413, "FILE_TOO_LARGE", "文件超过 10 MiB")
    media_type = file.content_type
    valid = media_type == "application/pdf" and data.startswith(b"%PDF-")
    if media_type == DOCX:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
                valid = "[Content_Types].xml" in names and "word/document.xml" in names
                if sum(info.file_size for info in archive.infolist()) > MAX_FILE:
                    raise PlatformError(413, "FILE_TOO_LARGE", "DOCX 展开大小超过演示限制")
        except (zipfile.BadZipFile, ValueError):
            valid = False
    if not valid:
        raise PlatformError(
            415, "UNSUPPORTED_FILE_TYPE", "仅接受文字 PDF/DOCX；真实解析由后续模块交付"
        )
    return platform.document(
        session.public.id, data, media_type, model_id, key, original_name=file.filename or "upload"
    )


@router.post(
    "/jobs", status_code=202, response_model=TaskAccepted, tags=["jobs"], operation_id="createJob"
)
async def create_job(body: JobCreate, platform: Service, session: SessionDep, key: IdempotencyKey):
    return platform.job_create(session.public.id, body, key)


@router.get("/jobs/{id}", response_model=Job, tags=["jobs"], operation_id="getJob")
async def get_job(
    id: ResourceID, platform: Service, session: SessionDep, version: int = Query(default=None, ge=1)
):
    return platform.repo.version(platform.repo.jobs, id, session.public.id, version)


@router.put("/jobs/{id}", response_model=Job, tags=["jobs"], operation_id="updateJob")
async def update_job(id: ResourceID, body: JobUpdate, platform: Service, session: SessionDep):
    return platform.job_update(session.public.id, id, body)


@router.post("/jobs/{id}/confirm", response_model=Job, tags=["jobs"], operation_id="confirmJob")
async def confirm_job(id: ResourceID, body: Confirmation, platform: Service, session: SessionDep):
    return platform.repo.confirm(platform.repo.jobs, id, session.public.id, body.version)


@router.post(
    "/diagnoses",
    status_code=202,
    response_model=DiagnosisAccepted,
    tags=["diagnoses"],
    operation_id="createDiagnosis",
)
async def create_diagnosis(
    body: DiagnosisCreate, platform: Service, session: SessionDep, key: IdempotencyKey
):
    return platform.diagnosis_create(session.public.id, body, key)


@router.get("/tasks/{id}", response_model=Task, tags=["platform"], operation_id="getTask")
async def get_task(id: ResourceID, platform: Service, session: SessionDep):
    return platform.repo.owned(platform.repo.tasks, id, session.public.id).value.model_copy(
        deep=True
    )


@router.get(
    "/diagnoses/{id}", response_model=Diagnosis, tags=["diagnoses"], operation_id="getDiagnosis"
)
async def get_diagnosis(id: ResourceID, platform: Service, session: SessionDep):
    return platform.repo.owned(platform.repo.diagnoses, id, session.public.id).value.model_copy(
        deep=True
    )


@router.get(
    "/diagnoses/{id}/export",
    response_class=Response,
    tags=["diagnoses"],
    operation_id="exportDiagnosis",
    responses={
        200: {
            "content": {"text/markdown": {"schema": {"type": "string"}}},
            "headers": {"Content-Disposition": {"schema": {"type": "string"}}},
        }
    },
)
async def export_diagnosis(id: ResourceID, platform: Service, session: SessionDep):
    return Response(
        platform.export(session.public.id, id),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="diagnosis.md"'},
    )
