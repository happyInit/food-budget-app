from __future__ import annotations

import json

import pytest

from app.runbook_embeddings import (
    RunbookEmbeddingError,
    chunk_markdown,
    cosine_similarity,
    embed_chunk,
    embed_text,
    search_similar_chunks,
)


class FakeBedrockEmbedClient:
    def __init__(self, vector: list[float] | None = None, error: Exception | None = None) -> None:
        self.vector = vector if vector is not None else [0.1, 0.2, 0.3]
        self.error = error
        self.kwargs: dict | None = None

    def invoke_model(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error

        class _Body:
            def __init__(self, payload: dict) -> None:
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode()

        return {"body": _Body({"embedding": self.vector})}


def test_chunk_markdown_splits_on_headers():
    text = "intro text\n\n## First\nfirst body\n\n### Nested\nnested body\n\n## Second\nsecond body\n"
    chunks = chunk_markdown(text, source_path="doc.md")
    titles = [c.title for c in chunks]
    assert titles == [None, "First", "Nested", "Second"]
    assert chunks[0].content == "intro text"
    assert chunks[0].chunk_id == "doc.md#0"
    assert all(c.source_path == "doc.md" for c in chunks)


def test_chunk_markdown_splits_long_section_on_paragraphs():
    long_body = "\n\n".join(f"paragraph {i} " + "x" * 100 for i in range(20))
    text = f"## Big\n{long_body}\n"
    chunks = chunk_markdown(text, source_path="doc.md", max_chars=300)
    assert len(chunks) > 1
    assert all(len(c.content) <= 300 for c in chunks)
    # chunk_index is contiguous and matches position in chunk_id
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunk_markdown_no_headers_returns_single_chunk():
    chunks = chunk_markdown("just plain text, no headers here", source_path="doc.md")
    assert len(chunks) == 1
    assert chunks[0].title is None


def test_embed_text_returns_vector_from_injected_client():
    client = FakeBedrockEmbedClient(vector=[0.5, 0.5])
    result = embed_text("hello", region_name="ap-northeast-2", model_id="amazon.titan-embed-text-v2:0", client=client)
    assert result == [0.5, 0.5]
    assert client.kwargs["modelId"] == "amazon.titan-embed-text-v2:0"
    assert json.loads(client.kwargs["body"]) == {"inputText": "hello"}


def test_embed_text_raises_on_client_error():
    client = FakeBedrockEmbedClient(error=RuntimeError("boom"))
    with pytest.raises(RunbookEmbeddingError):
        embed_text("hello", region_name="ap-northeast-2", model_id="m", client=client)


def test_embed_text_raises_on_missing_embedding_field():
    class _NoEmbeddingClient(FakeBedrockEmbedClient):
        def invoke_model(self, **kwargs):
            class _Body:
                def read(self):
                    return json.dumps({"unexpected": "shape"}).encode()

            return {"body": _Body()}

    with pytest.raises(RunbookEmbeddingError):
        embed_text("hello", region_name="ap-northeast-2", model_id="m", client=_NoEmbeddingClient())


def test_embed_chunk_populates_embedding_and_model():
    chunks = chunk_markdown("## Only\nbody text", source_path="doc.md")
    client = FakeBedrockEmbedClient(vector=[1.0, 0.0])
    embedded = embed_chunk(chunks[0], region_name="ap-northeast-2", model_id="titan-x", client=client)
    assert embedded.embedding == [1.0, 0.0]
    assert embedded.embedding_model == "titan-x"
    # original chunk is untouched (frozen dataclass, embed_chunk returns a copy)
    assert chunks[0].embedding is None


def test_cosine_similarity_identical_vectors_is_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector_is_zero_not_nan():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_search_similar_chunks_ranks_by_similarity_desc():
    query = [1.0, 0.0]
    candidates = [
        ("far", [0.0, 1.0]),
        ("close", [0.9, 0.1]),
        ("exact", [1.0, 0.0]),
    ]
    ranked = search_similar_chunks(query, candidates, top_k=2)
    assert [chunk_id for chunk_id, _ in ranked] == ["exact", "close"]


def test_search_similar_chunks_skips_empty_embeddings():
    ranked = search_similar_chunks([1.0, 0.0], [("empty", []), ("ok", [1.0, 0.0])])
    assert [chunk_id for chunk_id, _ in ranked] == ["ok"]
