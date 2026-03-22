from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from uuid import UUID

import pytest

redis_module = types.ModuleType("redis")
redis_asyncio_module = types.ModuleType("redis.asyncio")
redis_asyncio_module.Redis = object
redis_module.asyncio = redis_asyncio_module
sys.modules.setdefault("redis", redis_module)
sys.modules.setdefault("redis.asyncio", redis_asyncio_module)

psycopg_pool_module = types.ModuleType("psycopg_pool")
psycopg_pool_module.AsyncConnectionPool = object
sys.modules.setdefault("psycopg_pool", psycopg_pool_module)

psycopg_module = types.ModuleType("psycopg")
psycopg_rows_module = types.ModuleType("psycopg.rows")
psycopg_rows_module.dict_row = object
psycopg_types_module = types.ModuleType("psycopg.types")
psycopg_types_json_module = types.ModuleType("psycopg.types.json")
psycopg_types_json_module.Jsonb = object
psycopg_module.rows = psycopg_rows_module
psycopg_module.types = psycopg_types_module
sys.modules.setdefault("psycopg", psycopg_module)
sys.modules.setdefault("psycopg.rows", psycopg_rows_module)
sys.modules.setdefault("psycopg.types", psycopg_types_module)
sys.modules.setdefault("psycopg.types.json", psycopg_types_json_module)

docx_module = types.ModuleType("docx")
docx_module.Document = object
sys.modules.setdefault("docx", docx_module)

openpyxl_module = types.ModuleType("openpyxl")
openpyxl_module.load_workbook = lambda *args, **kwargs: None
sys.modules.setdefault("openpyxl", openpyxl_module)

multipart_module = types.ModuleType("multipart")
multipart_module.__version__ = "0.0.0"
multipart_submodule = types.ModuleType("multipart.multipart")
multipart_submodule.parse_options_header = lambda *args, **kwargs: (b"", {})
multipart_module.multipart = multipart_submodule
sys.modules.setdefault("multipart", multipart_module)
sys.modules.setdefault("multipart.multipart", multipart_submodule)

from app.models.schemas import NormalizedDocument, ParsedFile
from app.services.ingest_service import IngestService


class FakeDocumentRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.record = SimpleNamespace(id=UUID("11111111-1111-1111-1111-111111111111"))

    async def create_or_get_by_content_hash(
        self,
        document: NormalizedDocument,
        embedding_provider: str,
        embedding_model: str,
        content_hash: str,
    ) -> tuple[SimpleNamespace, bool]:
        self.calls.append(content_hash)
        return self.record, False


class FakeChunkingService:
    def build_chunks(self, document: NormalizedDocument) -> list[dict]:
        raise AssertionError("chunking should not run for duplicate documents")


class FakeEmbeddingService:
    async def embed_texts(self, *args, **kwargs):
        raise AssertionError("embedding should not run for duplicate documents")


class FakeChunkRepository:
    async def bulk_create(self, *args, **kwargs):
        raise AssertionError("chunk storage should not run for duplicate documents")


def build_service() -> IngestService:
    service = object.__new__(IngestService)
    service._document_repository = FakeDocumentRepository()
    service._chunking_service = FakeChunkingService()
    service._embedding_service = FakeEmbeddingService()
    service._chunk_repository = FakeChunkRepository()
    return service


def test_duplicate_document_upload_is_skipped() -> None:
    service = build_service()
    parsed_file = ParsedFile(
        filename="kb.txt",
        detected_type="txt",
        documents=[
            NormalizedDocument(
                title="KB",
                source_type="text",
                content="Same knowledge base content",
                metadata={},
            )
        ],
    )

    result = asyncio.run(
        service._persist_documents(
            parsed_file=parsed_file,
            embedding_provider="ollama",
            embedding_model="test-model",
            embedding_profile="ollama_1536",
            embedding_dimension=1536,
        )
    )

    assert result["documents_inserted"] == 0
    assert result["chunks_inserted"] == 0
    assert result["results"][0].deduplicated is True
    assert result["results"][0].success is True
