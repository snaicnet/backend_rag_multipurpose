from app.models.schemas import ChatMessage, RetrievedChunk
from app.services.prompt_builder import PromptBuilder


def test_prompt_builder_includes_grounding_and_citations() -> None:
    builder = PromptBuilder()
    chunks = [
        RetrievedChunk(
            chunk_id="11111111-1111-1111-1111-111111111111",
            document_id="22222222-2222-2222-2222-222222222222",
            title="Service Catalog",
            url="https://example.com/catalog",
            source_type="md",
            content="We offer AI chatbot implementation for SME customers.",
            metadata={"section_title": "Services"},
            similarity_score=0.92,
        )
    ]

    prompt = builder.build(
        user_message="What services do we offer?",
        chat_history=[ChatMessage(role="user", content="Hi")],
        retrieved_chunks=chunks,
        max_history_messages=8,
        max_context_chars=4000,
        max_context_tokens=1000,
        max_chunk_chars=2000,
    )

    assert "friendly, cheerful grounded RAG assistant" in prompt.system_prompt
    assert "Answer only from the provided context" in prompt.system_prompt
    assert "Do not name, list, or explain which internal documents or sources were used" in prompt.system_prompt
    assert "Question: What services do we offer?" in prompt.messages[-1].content
    assert "Do not mention which internal documents, sources, or chunks were used." in prompt.messages[-1].content
    assert prompt.citations[0].title == "Service Catalog"


def test_prompt_builder_caps_context_budget() -> None:
    builder = PromptBuilder()
    chunks = [
        RetrievedChunk(
            chunk_id="11111111-1111-1111-1111-111111111111",
            document_id="22222222-2222-2222-2222-222222222222",
            title="Chunk A",
            url=None,
            source_type="text",
            content="A" * 5000,
            metadata={},
            similarity_score=0.9,
        ),
        RetrievedChunk(
            chunk_id="33333333-3333-3333-3333-333333333333",
            document_id="44444444-4444-4444-4444-444444444444",
            title="Chunk B",
            url=None,
            source_type="text",
            content="B" * 5000,
            metadata={},
            similarity_score=0.8,
        ),
    ]

    prompt = builder.build(
        user_message="Summarize the sources",
        chat_history=[],
        retrieved_chunks=chunks,
        max_history_messages=8,
        max_context_chars=800,
        max_context_tokens=200,
        max_chunk_chars=300,
    )

    assert len(prompt.messages[-1].content) < 2000
    assert "A" * 301 not in prompt.messages[-1].content
    assert "B" * 301 not in prompt.messages[-1].content
