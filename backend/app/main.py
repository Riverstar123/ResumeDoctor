"""SET-01 factory: only a process health endpoint, no business API or worker yet."""

from fastapi import FastAPI
from pydantic import BaseModel

from app.settings import Settings, load_settings


class HealthStatus(BaseModel):
    status: str


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="ResumeDoctor minimal backend", version="0.1.0")
    app.state.settings = settings if settings is not None else load_settings()

    @app.get("/healthz", response_model=HealthStatus, tags=["operations"])
    def health() -> HealthStatus:
        # Process liveness only: this is not a database/provider readiness check.
        return HealthStatus(status="ok")

    return app
