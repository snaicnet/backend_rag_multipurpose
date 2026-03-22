# Redis and Caching

## Redis usage in the implementation

Redis is used for:

- chat rate limiting
- daily chat quota tracking
- retrieval result caching
- embedding caching
- optional session history storage

Redis is not used as the vector store.

## Rate limiting

Implemented in:

- `backend/app/core/rate_limit.py`

Applied in:

- `backend/app/services/chat_service.py`

Config:

- `CHAT_RATE_LIMIT_REQUESTS`
- `CHAT_RATE_LIMIT_WINDOW_SECONDS`
- `CHAT_DAILY_LIMIT_REQUESTS`

Behavior:

- a Redis counter key is created per time bucket
- a separate Redis counter tracks the per-user daily quota
- requests beyond the limit return HTTP `429`
- rate limiting is keyed to the authenticated user for `/chat` and `/chat/stream`

## Embedding cache

Implemented in:

- `backend/app/services/cache_service.py`
- `backend/app/services/embeddings.py`

Config:

- `EMBEDDING_CACHE_TTL_SECONDS`

Cache key includes:

- provider
- model
- input texts

## Retrieval cache

Implemented in:

- `backend/app/services/retrieval.py`

Config:

- `RETRIEVAL_CACHE_TTL_SECONDS`

Cache key includes:

- canonical embedding provider
- canonical embedding model
- query embedding
- `top_k`
- `SIMILARITY_THRESHOLD`

## Chat guardrails

Implemented in:

- `backend/app/services/guardrails.py`

Config:

- `CHAT_MAX_MESSAGE_CHARS`
- `CHAT_MAX_INPUT_TOKENS`
- `CHAT_MAX_HISTORY_MESSAGES`
- `CHAT_MAX_CONTEXT_CHARS`
- `CHAT_MAX_CONTEXT_TOKENS`
- `CHAT_MAX_CONTEXT_CHUNK_CHARS`
- `CHAT_MIN_TOP_K`
- `CHAT_MAX_TOP_K`
- `CHAT_MAX_RESPONSE_CHARS`
- `CHAT_MAX_RESPONSE_TOKENS`

Behavior:

- blocked phrases such as `ignore previous instructions` and `dump all data` are rejected before embedding
- repeated or highly similar prompts are rejected
- `top_k` is clamped to a safe range before retrieval
- chat history and retrieved context are trimmed before the prompt is built
- generated responses are truncated before the client receives them

## Session storage

Implemented in:

- `backend/app/services/session_service.py`

Config:

- `SESSION_STORAGE_ENABLED`
- `SESSION_TTL_SECONDS`
- `MAX_SESSION_MESSAGES`

Behavior:

- disabled by default
- when enabled, user and assistant messages are stored in Redis by `session_id`
- stored history is trimmed to the most recent configured message count

## Operational notes

- Redis must be reachable for chat rate limiting to work
- the daily quota is enforced in Redis as well
- cache misses do not break functionality
- Redis data is non-authoritative and safe to clear
