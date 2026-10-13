import asyncio
import copy

import httpx
import pytest

from app.main import create_app
from app.settings import Settings
from app.tools.check_contracts import compare_routes


def test_minimal_app_starts_without_credentials():
    settings = Settings(_env_file=None, llm_api_key="", database_url="", session_secret="")

    async def requests():
        transport = httpx.ASGITransport(app=create_app(settings))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/healthz")
            assert response.json() == {"status": "ok"}
            assert response.status_code == 200
            response = await client.post("/api/v1/session", json={"consent_version": "v1"})
            assert response.status_code == 403
            response = await client.post(
                "/api/v1/session",
                json={"consent_version": "v1"},
                headers={"Origin": "http://localhost:5173"},
            )
            assert response.status_code == 200

    asyncio.run(requests())


def generated_route(design):
    doc = copy.deepcopy(design)
    doc["paths"] = {"/api/v1/session": {"post": doc["paths"]["/session"]["post"]}}
    return doc


def test_route_comparison_handles_prefix_and_ignores_descriptions(design):
    generated = generated_route(design)
    generated["paths"]["/api/v1/session"]["post"]["responses"]["200"]["description"] = "OK"
    result = compare_routes(design, generated)
    assert result["implemented"] == ["POST /session"]
    assert "DELETE /session" in result["pending"]


@pytest.mark.parametrize("mutation", ["required", "response", "security", "parameter"])
def test_route_comparison_rejects_contract_drift(design, mutation):
    generated = generated_route(design)
    route = generated["paths"]["/api/v1/session"]["post"]
    if mutation == "required":
        route["requestBody"]["content"]["application/json"]["schema"]["required"] = []
    elif mutation == "response":
        del route["responses"]["401"]
    elif mutation == "security":
        route["security"] = [{"sessionCookie": []}]
    else:
        route["parameters"] = [{"in": "query", "name": "unexpected", "schema": {"type": "string"}}]
    with pytest.raises(AssertionError, match="route drift"):
        compare_routes(design, generated)


def test_unplanned_business_route_is_rejected(design):
    generated = generated_route(design)
    generated["paths"]["/api/v1/debug"] = generated["paths"].pop("/api/v1/session")
    with pytest.raises(AssertionError, match="undocumented"):
        compare_routes(design, generated)


def test_same_security_name_with_changed_cookie_is_rejected(design):
    generated = copy.deepcopy(design)
    generated["paths"] = {"/api/v1/models": {"get": generated["paths"]["/models"]["get"]}}
    assert compare_routes(design, generated)["implemented"] == ["GET /models"]
    generated["components"]["securitySchemes"]["sessionCookie"]["name"] = "wrong-cookie"
    with pytest.raises(AssertionError, match="security scheme"):
        compare_routes(design, generated)
