from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.models.schemas import ChatMessage


class GuardrailService:
    def __init__(self, settings: Settings, redis_client: Redis) -> None:
        self._settings = settings
        self._redis = redis_client
        self._burst_limiter = RateLimiter(
            redis_client=redis_client,
            limit=settings.chat_rate_limit_requests,
            window_seconds=settings.chat_rate_limit_window_seconds,
        )
        self._blocked_patterns = [
            re.compile(r"\bignore\s+previous\s+instructions\b", re.IGNORECASE),
            re.compile(r"\bdump\s+all\s+data\b", re.IGNORECASE),
            re.compile(r"\bshow\s+full\s+document\b", re.IGNORECASE),
            re.compile(r"\bexport\s+everything\b", re.IGNORECASE),
            re.compile(r"\bprint\s+full\s+source\b", re.IGNORECASE),
            re.compile(r"\breturn\s+exact\s+text\b", re.IGNORECASE),
        ]
        self._source_introspection_patterns = [
            re.compile(r"\b(which|what)\s+document\s+did\s+you\s+use\b", re.IGNORECASE),
            re.compile(r"\b(which|what)\s+sources?\s+did\s+you\s+use\b", re.IGNORECASE),
            re.compile(r"\bwhich\s+document\s+you\s+used\b", re.IGNORECASE),
            re.compile(r"\bwhat\s+document\s+you\s+used\b", re.IGNORECASE),
            re.compile(r"\bwhich\s+source(?:s)?\b.*\b(?:used|use|based on)\b", re.IGNORECASE),
            re.compile(r"\bwhat\s+source(?:s)?\b.*\b(?:used|use|based on)\b", re.IGNORECASE),
            re.compile(r"\btell me\b.*\bwhich\s+document\b", re.IGNORECASE),
            re.compile(r"\btell me\b.*\bwhich\s+source(?:s)?\b", re.IGNORECASE),
        ]

    async def enforce_request_budget(self, rate_limit_key: str) -> None:
        allowed, _ = await self._burst_limiter.check(rate_limit_key)
        if not allowed:
            raise ValueError("Chat rate limit exceeded")

        daily_key = f"rate_limit_daily:{rate_limit_key}:{datetime.now(timezone.utc).date().isoformat()}"
        current = await self._redis.incr(daily_key)
        if current == 1:
            await self._redis.expire(daily_key, 60 * 60 * 48)

        if current > self._settings.chat_daily_limit_requests:
            raise ValueError("Chat daily quota exceeded")

    def validate_user_message(self, message: str, recent_user_messages: list[str]) -> str:
        normalized = self._normalize(message)
        if len(normalized) > self._settings.chat_max_message_chars:
            raise ValueError("Prompt too long")
        if self._estimate_tokens(normalized) > self._settings.chat_max_input_tokens:
            raise ValueError("Prompt too long")

        if self._matches_blocked_pattern(normalized):
            raise ValueError("Your request matches a blocked pattern. Please rephrase it.")

        if self._matches_source_introspection_pattern(normalized):
            raise ValueError("I cannot help with that.")

        if self._is_repeated_prompt(normalized, recent_user_messages):
            raise ValueError("Repeated or highly similar prompts are blocked. Please rephrase your request.")

        return normalized

    def clamp_top_k(self, requested_top_k: int) -> int:
        return max(self._settings.chat_min_top_k, min(requested_top_k, self._settings.chat_max_top_k))

    def limit_history(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        if self._settings.chat_max_history_messages <= 0:
            return []
        return messages[-self._settings.chat_max_history_messages :]

    def truncate_response(self, text: str) -> str:
        max_chars = self._settings.chat_max_response_chars
        max_tokens = self._settings.chat_max_response_tokens
        if len(text) <= max_chars and self._estimate_tokens(text) <= max_tokens:
            return text

        words = text.split()
        if words:
            limited = " ".join(words[:max_tokens])
        else:
            limited = text[:max_chars]

        return limited[:max_chars]

    def _matches_blocked_pattern(self, message: str) -> bool:
        return any(pattern.search(message) for pattern in self._blocked_patterns)

    def _matches_source_introspection_pattern(self, message: str) -> bool:
        return any(pattern.search(message) for pattern in self._source_introspection_patterns)

    def _is_repeated_prompt(self, message: str, recent_user_messages: list[str]) -> bool:
        normalized_recent = [self._normalize(item) for item in recent_user_messages if self._normalize(item)]
        if not normalized_recent:
            return False

        identical_count = sum(1 for item in normalized_recent if item == message)
        if identical_count >= 2:
            return True

        lookback = normalized_recent[-self._settings.chat_repeated_prompt_lookback :]
        near_matches = 0
        for previous in lookback:
            if len(message) < 24 or len(previous) < 24:
                continue
            ratio = SequenceMatcher(None, message, previous).ratio()
            if ratio >= 0.92:
                near_matches += 1
            if near_matches >= 2:
                return True

        return False

    def _normalize(self, text: str) -> str:
        return " ".join(text.strip().split())

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(text.split())
