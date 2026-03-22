# Architecture

## Overview

The project is a backend-only RAG chatbot service with these runtime dependencies:

- FastAPI application layer
- PostgreSQL as the primary data store
- Qdrant for embedding storage and similarity search
- Redis for rate limiting, caching, and optional session state
- Provider adapters for OpenAI, Gemini, and Ollama
- JWT bearer authentication and hashed API keys

## High-level flow

1. Documents are ingested through `POST /ingest/text` or `POST /ingest/files`.
2. Protected routes require a bearer token or `X-API-Key`.
3. Inputs are normalized into a shared internal document model.
4. Text is chunked.
5. Chunks are embedded using the active embedding profile.
6. Documents are stored in PostgreSQL and chunk vectors are stored in Qdrant.
7. A chat request is rate-limited and quota-checked per authenticated user.
8. The input is filtered for blocked phrases, unusually long prompts, and repeated prompt abuse.
9. The user query is embedded with the same active profile or an explicitly requested profile.
10. Qdrant retrieves top matching chunks from the collection for that embedding dimension.
11. Retrieval `top_k` is clamped to a safe range before any search happens.
12. A grounded prompt is built from retrieved context with caps on history size, context size, and per-chunk size.
13. The selected generation provider produces either a full answer or a streaming answer.
14. The response is truncated to the configured output budget before being returned to the client.

## Code layout

```text
backend/app/
|- api/         # FastAPI routes
|- core/        # config, logging, rate limiting, security
|- db/          # connection managers, schema, repositories
|- models/      # Pydantic schemas
|- parsers/     # file parsing and normalization
|- providers/   # provider abstraction and implementations
`- services/    # auth, chunking, embeddings, retrieval, prompting, chat, ingest
```

## Separation of concerns

- Route handlers stay thin and delegate to services.
- Provider-specific logic is isolated under `backend/app/providers/`.
- PostgreSQL access is isolated under `backend/app/db/repositories/`.
- File-type-specific parsing stays under `backend/app/parsers/`.
- RAG orchestration lives in `backend/app/services/`.
- Auth token issuance and API key verification live in `backend/app/services/auth_service.py`.

## Data model

Primary tables:

- `app_users`
- `api_keys`
- `documents`

Primary vector store:

- Qdrant collections keyed by embedding dimension

Important fields:

- `app_users.username`
- `app_users.password_hash`
- `api_keys.key_prefix`
- `api_keys.key_hash`
- `documents.title`
- `documents.url`
- `documents.source_type`
- `documents.metadata`
- `documents.original_filename`
- `documents.mime_type`
- Qdrant point payloads store chunk content, metadata, and embedding profile details
- Retrieval queries are additionally constrained by `top_k` and the configured similarity threshold

## Authentication model

Implemented authentication is:

- local bootstrap admin user stored in PostgreSQL
- password hashing with `hashlib.scrypt`
- JWT access tokens signed with `AUTH_JWT_SECRET`
- optional `X-API-Key` auth for service clients
- API keys stored as SHA-256 hashes, never in plaintext

Protected routes:

- `GET /auth/me`
- `POST /auth/api-keys`
- `POST /ingest/text`
- `POST /ingest/files`
- `POST /chat`
- `POST /chat/stream`
- `DELETE /admin/reset`

Unprotected routes:

- `GET /health`
- `POST /auth/token`

## Transport security

The application signs tokens and hashes credentials, but HTTP encryption itself must still be provided by TLS at the deployment layer. If `AUTH_REQUIRE_HTTPS=true`, authenticated requests are rejected unless the request scheme is `https` or the proxy sends `X-Forwarded-Proto: https`.

## Current architectural limitations

- Embedding profiles are configured in `.env` and can be switched without code changes.
- Each embedding dimension maps to its own Qdrant collection, created automatically on first use.
- Request payloads expose `embedding_profile`, `embedding_provider`, and `embedding_model` for explicit selection.
- Provider streaming is implemented, but integration tests against live providers are not included.
- TLS termination is not implemented in the app itself.
- Chat guardrails are implemented in the service layer, not only in the prompt.

Current repository default embedding profile:

- profile: `ollama_1536`
- provider: `ollama`
- model: `rjmalagon/gte-qwen2-1.5b-instruct-embed-f16`
- dimension: `1536`
