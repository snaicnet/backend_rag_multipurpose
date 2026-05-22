import json
from typing import AsyncIterator

import httpx

from app.core.config import (
    CHAT_FREQUENCY_PENALTY,
    CHAT_MAX_RESPONSE_TOKENS,
    CHAT_PRESENCE_PENALTY,
    OPENAI_REASONING_EFFORT,
    CHAT_TOP_P,
    Settings,
)
from app.models.schemas import ChatCompletionResult, ChatMessage, ProviderHealth
from app.providers.base import ProviderAdapter


OPENAI_API_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(ProviderAdapter):
    provider_name = "openai"
    capabilities = ["chat", "embeddings"]

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def healthcheck(self) -> ProviderHealth:
        configured = bool(self._settings.openai_api_key)

        if not configured:
            return ProviderHealth(
                ok=False,
                detail="missing OPENAI_API_KEY",
                enabled=True,
                provider=self.provider_name,
                capabilities=self.capabilities,
                configuration_present=False,
            )

        return ProviderHealth(
            ok=True,
            detail="configuration_present",
            enabled=True,
            provider=self.provider_name,
            capabilities=self.capabilities,
            configuration_present=True,
        )

    async def complete_chat(
        self,
        messages: list[ChatMessage],
        model: str,
    ) -> ChatCompletionResult:
        if not self._settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI chat")

        headers = {"Content-Type": "application/json"}
        if self._settings.openai_api_key:
            headers["Authorization"] = f"Bearer {self._settings.openai_api_key}"
        thinking_enabled = self._thinking_enabled()
        data = await self._post_chat_completion(
            headers=headers,
            payload=self._build_chat_payload(messages, model, thinking_enabled=thinking_enabled),
        )
        if data is None and thinking_enabled:
            data = await self._post_chat_completion(
                headers=headers,
                payload=self._build_chat_payload(messages, model, thinking_enabled=False),
            )
        if data is None:
            raise ValueError("OpenAI chat request failed")

        text = data["choices"][0]["message"]["content"]
        return ChatCompletionResult(text=text, thinking=None, provider=self.provider_name, model=model)

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        model: str,
    ) -> AsyncIterator[str]:
        if not self._settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI chat")

        headers = {"Content-Type": "application/json"}
        if self._settings.openai_api_key:
            headers["Authorization"] = f"Bearer {self._settings.openai_api_key}"
        thinking_enabled = self._thinking_enabled()
        payload = self._build_chat_payload(messages, model, thinking_enabled=thinking_enabled, stream=True)
        try:
            async for delta in self._stream_chat_completion(headers=headers, payload=payload):
                yield delta
            return
        except httpx.HTTPStatusError as exc:
            if not self._should_retry_without_thinking(exc):
                raise

        fallback_payload = self._build_chat_payload(messages, model, thinking_enabled=False, stream=True)
        async for delta in self._stream_chat_completion(headers=headers, payload=fallback_payload):
            yield delta

    def _thinking_enabled(self) -> bool:
        return bool(getattr(self._settings, "chat_thinking_enabled", False))

    def _build_chat_payload(
        self,
        messages: list[ChatMessage],
        model: str,
        *,
        thinking_enabled: bool,
        stream: bool = False,
    ) -> dict:
        payload = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "temperature": self._settings.chat_temperature,
            "top_p": CHAT_TOP_P,
            "frequency_penalty": CHAT_FREQUENCY_PENALTY,
            "presence_penalty": CHAT_PRESENCE_PENALTY,
        }
        if stream:
            payload["stream"] = True
        if thinking_enabled:
            payload["reasoning_effort"] = OPENAI_REASONING_EFFORT
            payload["max_completion_tokens"] = CHAT_MAX_RESPONSE_TOKENS
        else:
            payload["max_tokens"] = CHAT_MAX_RESPONSE_TOKENS
        return payload

    async def _post_chat_completion(self, headers: dict, payload: dict) -> dict | None:
        try:
            async with httpx.AsyncClient(base_url=OPENAI_API_BASE_URL, timeout=60.0) as client:
                response = await client.post(
                    "/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            if self._should_retry_without_thinking(exc):
                return None
            raise

    async def _stream_chat_completion(self, headers: dict, payload: dict) -> AsyncIterator[str]:
        async with httpx.AsyncClient(base_url=OPENAI_API_BASE_URL, timeout=60.0) as client:
            async with client.stream(
                "POST",
                "/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    data = line[6:].strip()
                    if data == "[DONE]":
                        break

                    parsed = json.loads(data)
                    delta = parsed["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta

    def _should_retry_without_thinking(self, exc: httpx.HTTPStatusError) -> bool:
        if not self._thinking_enabled():
            return False
        status_code = getattr(exc.response, "status_code", None)
        if status_code not in {400, 404, 422}:
            return False
        detail = " ".join(
            part
            for part in [
                str(exc),
                getattr(exc.response, "text", ""),
                getattr(exc.response, "reason_phrase", ""),
            ]
            if part
        ).lower()
        return any(
            token in detail
            for token in ("reasoning_effort", "reasoning", "thinking", "thought", "think")
        )
