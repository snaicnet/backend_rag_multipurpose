from __future__ import annotations

import asyncio

import pytest
import httpx


def test_live_api_flow(live_api_config: dict[str, str | None]) -> None:
    assert live_api_config["base_url"] is not None
    assert live_api_config["username"] is not None
    assert live_api_config["password"] is not None
    assert live_api_config["ingest_text"] is not None

    async def run_flow() -> None:
        base_url = live_api_config["base_url"]
        async with httpx.AsyncClient(base_url=base_url, timeout=120.0) as client:
            token_response = await client.post(
                "/auth/token",
                json={
                    "username": live_api_config["username"],
                    "password": live_api_config["password"],
                },
            )
            assert token_response.status_code == 200, token_response.text
            token = token_response.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            ingest_payload: dict[str, object] = {
                "items": [
                    {
                        "title": live_api_config["ingest_title"],
                        "content": live_api_config["ingest_text"],
                        "source_type": "text",
                    }
                ]
            }
            if live_api_config["embedding_profile"]:
                ingest_payload["embedding_profile"] = live_api_config["embedding_profile"]
            if live_api_config["embedding_provider"]:
                ingest_payload["embedding_provider"] = live_api_config["embedding_provider"]
            if live_api_config["embedding_model"]:
                ingest_payload["embedding_model"] = live_api_config["embedding_model"]

            ingest_response = await client.post(
                "/ingest/text",
                headers=headers,
                json=ingest_payload,
            )
            assert ingest_response.status_code == 200, ingest_response.text

            chat_payload: dict[str, object] = {
                "message": live_api_config["chat_message"],
                "debug": True,
            }
            if live_api_config["generation_provider"]:
                chat_payload["provider"] = live_api_config["generation_provider"]
            if live_api_config["generation_model"]:
                chat_payload["model"] = live_api_config["generation_model"]
            if live_api_config["embedding_profile"]:
                chat_payload["embedding_profile"] = live_api_config["embedding_profile"]
            if live_api_config["embedding_provider"]:
                chat_payload["embedding_provider"] = live_api_config["embedding_provider"]
            if live_api_config["embedding_model"]:
                chat_payload["embedding_model"] = live_api_config["embedding_model"]

            chat_response = await client.post("/chat", headers=headers, json=chat_payload)
            assert chat_response.status_code == 200, chat_response.text
            payload = chat_response.json()

            print("ANSWER:", payload["answer"])
            print("CITATIONS:", payload["citations"])
            print("RETRIEVED_CHUNKS:", payload["retrieved_chunks"])

            assert payload["answer"].strip()
            assert "SIT Centre for AI" in payload["answer"]
            assert "NVIDIA" in payload["answer"]
            assert payload["citations"]
            assert payload["retrieved_chunks"]
            assert any(
                citation.get("title") == live_api_config["ingest_title"]
                for citation in payload["citations"]
            )
            assert payload["used_fallback"] is False

    asyncio.run(run_flow())
