import asyncio

import httpx
from fastapi import FastAPI

from app.api.health import router as health_router
from app.models.schemas import DependencyHealth, ProviderHealth


class StubPostgres:
    async def healthcheck(self) -> DependencyHealth:
        return DependencyHealth(ok=True, detail="connected")


class StubRedis:
    async def healthcheck(self) -> DependencyHealth:
        return DependencyHealth(ok=True, detail="connected")


class StubQdrant:
    async def healthcheck(self) -> DependencyHealth:
        return DependencyHealth(ok=True, detail="connected")


class StubProviders:
    async def healthcheck_all(self) -> dict[str, ProviderHealth]:
        return {
            "openai": ProviderHealth(
                ok=True,
                detail="configuration_present",
                enabled=True,
                provider="openai",
                capabilities=["chat", "embeddings"],
                configuration_present=True,
            ),
            "gemini": ProviderHealth(
                ok=True,
                detail="configuration_present",
                enabled=True,
                provider="gemini",
                capabilities=["chat"],
                configuration_present=True,
            ),
            "ollama": ProviderHealth(
                ok=True,
                detail="reachable",
                enabled=True,
                provider="ollama",
                capabilities=["chat", "embeddings"],
                configuration_present=True,
            ),
        }


class StubSettings:
    app_name = "backend-rag-multipurpose"


def build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(health_router)
    app.state.postgres = StubPostgres()
    app.state.redis = StubRedis()
    app.state.qdrant = StubQdrant()
    app.state.providers = StubProviders()
    app.state.settings = StubSettings()
    return app


def test_health_endpoint_returns_ok() -> None:
    async def run_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=build_test_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/health")

    response = asyncio.run(run_request())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["postgres"]["ok"] is True
    assert payload["redis"]["ok"] is True
    assert payload["qdrant"]["ok"] is True
    assert payload["providers"]["ollama"]["detail"] == "reachable"
