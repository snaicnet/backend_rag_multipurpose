from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.core.security import require_authenticated_user
from app.models.schemas import (
    AuthenticatedUser,
    IngestFilesResponse,
    IngestTextRequest,
    IngestTextResponse,
)
from app.services.ingest_service import IngestService

router = APIRouter()


def _build_ingest_service(request: Request) -> IngestService:
    return IngestService(
        settings=request.app.state.settings,
        redis_manager=request.app.state.redis,
        qdrant_manager=request.app.state.qdrant,
        postgres_pool=request.app.state.postgres.pool,
        provider_registry=request.app.state.providers,
        model_selection_service=request.app.state.model_selection_service,
    )


@router.post("/text", response_model=IngestTextResponse)
async def ingest_text(
    request: Request,
    payload: IngestTextRequest,
    current_user: AuthenticatedUser = Depends(require_authenticated_user),
) -> IngestTextResponse:
    service = _build_ingest_service(request)
    return await service.ingest_text_items(payload, current_user=current_user)


@router.post("/files", response_model=IngestFilesResponse)
async def ingest_files(
    request: Request,
    files: list[UploadFile] = File(...),
    current_user: AuthenticatedUser = Depends(require_authenticated_user),
) -> IngestFilesResponse:
    service = _build_ingest_service(request)
    return await service.ingest_uploaded_files(
        files=files,
        current_user=current_user,
    )
