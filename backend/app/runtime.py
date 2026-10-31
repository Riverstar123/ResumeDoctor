"""Business composition shared by the HTTP process and durable worker.

`LLM_MODE=fake` keeps the simulated model used in development and QA-03:
intake validation/file parsing, scoring, reporting and persistence are the
owners' delivered implementations. `LLM_MODE=real` (AI-03) wires the
OpenAI-compatible gateway from `build_llm` and explicitly supplies the
QA-02-reviewed contact filters to both M3 intake and M5 reporting; neither
accepts a non-fake gateway without an explicit privacy policy. No import I/O.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.contracts.ports import ModelGateway
from app.intake import GatewayIntake
from app.intake.privacy import filter_fake_context
from app.llm import FakeModelDirectory, build_llm
from app.platform.demo_gateway import IntegrationFakeGateway
from app.platform.integration import GatewayCatalog
from app.reporting import ReportService
from app.reporting.privacy import filter_report_context
from app.scoring import ScoringService

PrivacyFilter = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class Modules:
    gateway: ModelGateway
    catalog: GatewayCatalog
    reporting: ReportService
    scoring: ScoringService
    intake_privacy_filter: PrivacyFilter | None = None

    def intake_for(self, source_id: str) -> GatewayIntake:
        # A fresh adapter binds a persisted source to one task. Never mutate a
        # process-wide source ID while different sessions are running.
        return GatewayIntake(
            self.gateway,
            source_id=source_id,
            privacy_filter=self.intake_privacy_filter,
        )


def business_modules(settings, *, directory=None, gateway=None) -> Modules:
    if settings.llm_mode == "fake":
        directory = directory if directory is not None else FakeModelDirectory()
        gateway = gateway if gateway is not None else IntegrationFakeGateway(directory)
        return Modules(gateway, GatewayCatalog(directory), ReportService(gateway), ScoringService())

    # AI-03 real acceptance: the controlled catalog and OpenAI-compatible
    # gateway come from build_llm, which fails at assembly when configuration
    # is missing. Tests may inject their own directory/gateway pair.
    if directory is None or gateway is None:
        components = build_llm(settings)
        directory = directory if directory is not None else components.directory
        gateway = gateway if gateway is not None else components.gateway
    return Modules(
        gateway,
        GatewayCatalog(directory),
        ReportService(gateway, privacy_filter=filter_report_context),
        ScoringService(),
        intake_privacy_filter=filter_fake_context,
    )
