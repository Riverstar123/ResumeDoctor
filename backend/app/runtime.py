"""INT-02 business composition shared by the HTTP process and durable worker.

Only the model is simulated. Intake validation/file parsing, scoring, reporting
and persistence remain their owners' delivered implementations. No import I/O.
"""

from dataclasses import dataclass

from app.contracts.ports import ModelGateway
from app.intake import GatewayIntake
from app.llm import FakeModelDirectory
from app.platform.demo_gateway import IntegrationFakeGateway
from app.platform.integration import GatewayCatalog
from app.reporting import ReportService
from app.scoring import ScoringService


@dataclass(frozen=True)
class Modules:
    gateway: ModelGateway
    catalog: GatewayCatalog
    reporting: ReportService
    scoring: ScoringService

    def intake_for(self, source_id: str) -> GatewayIntake:
        # A fresh adapter binds a persisted source to one task. Never mutate a
        # process-wide source ID while different sessions are running.
        return GatewayIntake(self.gateway, source_id=source_id)


def business_modules(settings, *, directory=None, gateway=None) -> Modules:
    if settings.llm_mode != "fake":
        raise ValueError("INT-02 requires LLM_MODE=fake; real AI acceptance belongs to AI-03")
    directory = directory if directory is not None else FakeModelDirectory()
    gateway = gateway if gateway is not None else IntegrationFakeGateway(directory)
    return Modules(gateway, GatewayCatalog(directory), ReportService(gateway), ScoringService())
