from __future__ import annotations

import asyncio

import httpx

# Edit these values before running the script.
BASE_URL = "http://localhost:9010"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "change-me-immediately"
QUERY = """
How LLMs help manufacturing company?
"""

# Optional chat settings.
DEBUG = True
TOP_K = 5
GENERATION_PROVIDER: str | None = None
GENERATION_MODEL: str | None = None
EMBEDDING_PROFILE: str | None = None
EMBEDDING_PROVIDER: str | None = None
EMBEDDING_MODEL: str | None = None
SESSION_ID: str | None = None


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        token_response = await client.post(
            "/auth/token",
            json={
                "username": ADMIN_USERNAME,
                "password": ADMIN_PASSWORD,
            },
        )
        token_response.raise_for_status()

        token = token_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        chat_payload: dict[str, object] = {
            "message": QUERY,
            "debug": DEBUG,
            "top_k": TOP_K,
        }
        if SESSION_ID is not None:
            chat_payload["session_id"] = SESSION_ID
        if GENERATION_PROVIDER is not None:
            chat_payload["provider"] = GENERATION_PROVIDER
        if GENERATION_MODEL is not None:
            chat_payload["model"] = GENERATION_MODEL
        if EMBEDDING_PROFILE is not None:
            chat_payload["embedding_profile"] = EMBEDDING_PROFILE
        if EMBEDDING_PROVIDER is not None:
            chat_payload["embedding_provider"] = EMBEDDING_PROVIDER
        if EMBEDDING_MODEL is not None:
            chat_payload["embedding_model"] = EMBEDDING_MODEL

        chat_response = await client.post("/chat", headers=headers, json=chat_payload)
        chat_response.raise_for_status()
        payload = chat_response.json()
        
        # chatgethealth = await client.get("/health")
        # chatgethealth.raise_for_status()
        # health_info = chatgethealth.json()

    # print("Health Info:", health_info)
    print("Prompt Messages:")
    for message in payload.get("prompt_messages", []):
        print(f"- role={message.get('role')}")
        print(message.get("content", ""))
        print("---")
    # print("Citations:", payload.get("citations", []))
    print("Retrieved Chunks:", payload.get("retrieved_chunks", []))
    print("Answer:", payload.get("answer", ""))
    


if __name__ == "__main__":
    asyncio.run(main())
