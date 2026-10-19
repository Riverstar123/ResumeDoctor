"""INT-01 fake-only composition root; imports perform no I/O or settings load."""

from app.intake import SyntheticIntake
from app.llm import FakeModelDirectory, FakeModelGateway
from app.main import create_app as create_platform_app
from app.platform.integration import GatewayCatalog, GatewayReporting
from app.scoring import ScoringService


def create_app(settings=None, *, directory=None, gateway=None, executor=None, repository=None):
    directory = directory if directory is not None else FakeModelDirectory()
    gateway = gateway if gateway is not None else FakeModelGateway(directory)
    app = create_platform_app(
        settings,
        repository=repository,
        executor=executor,
        catalog=GatewayCatalog(directory),
        intake=SyntheticIntake(),
        scoring=ScoringService(),
        reporting=GatewayReporting(gateway),
    )
    app.state.gateway = gateway
    app.title = "ResumeDoctor INT-01 / synthetic intake, real scoring, fake report"
    return app


def create_report_failure_app():
    """Server-selected demo failure; no request content can activate this control."""
    directory = FakeModelDirectory()
    gateway = FakeModelGateway(directory, failures={"diagnosis_report": "invalid_json"})
    return create_app(directory=directory, gateway=gateway)
