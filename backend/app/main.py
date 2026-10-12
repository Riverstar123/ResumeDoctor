"""Injectable API-01 factory. Default adapters are process-local test doubles."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from app.api.errors import install_http
from app.api.routes import router
from app.contracts.ports import IntakePort, ReportingPort, ScoringPort
from app.platform.catalog import FakeModelCatalog, ModelCatalog
from app.platform.fakes import FakeIntake, FakeReporting, FakeScoring, FakeTaskExecutor
from app.platform.repositories import InMemoryRepository
from app.platform.service import Platform
from app.settings import Settings, load_settings


class HealthStatus(BaseModel):
    status: str


def create_app(
    settings: Settings | None = None,
    *,
    repository: InMemoryRepository | None = None,
    executor: FakeTaskExecutor | None = None,
    catalog: ModelCatalog | None = None,
    intake: IntakePort | None = None,
    scoring: ScoringPort | None = None,
    reporting: ReportingPort | None = None,
) -> FastAPI:
    platform = Platform(
        repository if repository is not None else InMemoryRepository(),
        executor if executor is not None else FakeTaskExecutor(),
        catalog if catalog is not None else FakeModelCatalog(),
        intake if intake is not None else FakeIntake(),
        scoring if scoring is not None else FakeScoring(),
        reporting if reporting is not None else FakeReporting(),
    )

    @asynccontextmanager
    async def lifespan(app):
        async def sweep():
            while True:
                await asyncio.sleep(60)
                platform.prune()

        sweeper = asyncio.create_task(sweep())
        try:
            yield
        finally:
            sweeper.cancel()
            await asyncio.gather(sweeper, return_exceptions=True)
            await platform.close()

    app = FastAPI(title="ResumeDoctor API / fake development", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings if settings is not None else load_settings()
    if app.state.settings.llm_mode != "fake":
        raise ValueError(
            "API-01 default assembly requires LLM_MODE=fake; real integration is not delivered"
        )
    app.state.platform = platform
    install_http(app)
    app.include_router(router)

    @app.get("/healthz", response_model=HealthStatus, tags=["operations"])
    def health() -> HealthStatus:
        # Process liveness only: this is not a database/provider readiness check.
        return HealthStatus(status="ok")

    return app
