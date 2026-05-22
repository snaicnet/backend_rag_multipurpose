from fastapi import APIRouter, Request

from app.models.schemas import HealthCheckResponse

router = APIRouter()


@router.get("/health", response_model=HealthCheckResponse)
async def health_check(request: Request) -> HealthCheckResponse:
    postgres_status = await request.app.state.postgres.healthcheck()
    redis_status = await request.app.state.redis.healthcheck()
    qdrant_status = await request.app.state.qdrant.healthcheck()
    provider_status = await request.app.state.providers.healthcheck_all()

    overall_ok = postgres_status.ok and redis_status.ok and qdrant_status.ok and all(
        status.ok for status in provider_status.values()
    )

    return HealthCheckResponse(
        status="ok" if overall_ok else "degraded",
        app=request.app.state.settings.app_name,
        postgres=postgres_status,
        redis=redis_status,
        qdrant=qdrant_status,
        providers=provider_status,
    )
