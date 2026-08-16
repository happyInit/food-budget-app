from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

import numpy as np


class RunbookEmbeddingError(RuntimeError):
    """Raised when a Bedrock embedding call fails or returns an unusable response."""


@dataclass(frozen=True)
class RunbookChunk:
    chunk_id: str
    source_path: str
    chunk_index: int
    title: str | None
    content: str
    embedding: list[float] | None = None
    embedding_model: str | None = None


_HEADER_RE = re.compile(r"^(#{2,3})\s+(.*)$", re.MULTILINE)


def chunk_markdown(
    text: str, *, source_path: str, max_chars: int = 1500
) -> list[RunbookChunk]:
    """Split a markdown runbook into retrieval-sized chunks.

    Splits on ## / ### headers first (keeps each section's own heading as
    context), then further splits any section still over max_chars on
    paragraph boundaries. A whole-document embedding would blur unrelated
    sections together and dilute cosine similarity, so sections stay
    separate rather than being embedded as one blob.
    """
    sections: list[tuple[str | None, str]] = []
    matches = list(_HEADER_RE.finditer(text))
    if not matches:
        sections.append((None, text))
    else:
        if matches[0].start() > 0:
            preamble = text[: matches[0].start()].strip()
            if preamble:
                sections.append((None, preamble))
        for i, match in enumerate(matches):
            title = match.group(2).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            sections.append((title, body))

    chunks: list[RunbookChunk] = []
    index = 0
    for title, body in sections:
        if not body:
            continue
        for piece in _split_to_max_chars(body, max_chars):
            chunks.append(
                RunbookChunk(
                    chunk_id=f"{source_path}#{index}",
                    source_path=source_path,
                    chunk_index=index,
                    title=title,
                    content=piece,
                )
            )
            index += 1
    return chunks


def _split_to_max_chars(body: str, max_chars: int) -> list[str]:
    if len(body) <= max_chars:
        return [body]
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > max_chars and current:
            pieces.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        pieces.append(current)
    # A single paragraph longer than max_chars falls through untouched above —
    # hard-cut it so no chunk is unbounded.
    return [p if len(p) <= max_chars else p[:max_chars] for p in pieces] or [
        body[:max_chars]
    ]


def embed_text(
    text: str, *, region_name: str, model_id: str, client=None
) -> list[float]:
    """Call Bedrock titan-embed and return the embedding vector.

    ``client`` is injectable so unit tests do not require AWS credentials or
    network access, matching app.rca_contract.build_bedrock_rca's pattern.
    """
    if client is None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - packaging safeguard
            raise RunbookEmbeddingError("boto3 is not installed") from exc
        client = boto3.client("bedrock-runtime", region_name=region_name)

    try:
        response = client.invoke_model(
            modelId=model_id,
            body=json.dumps({"inputText": text}),
            contentType="application/json",
            accept="application/json",
        )
    except Exception as exc:
        raise RunbookEmbeddingError(f"Bedrock embedding request failed: {exc}") from exc

    try:
        payload = json.loads(response["body"].read())
    except Exception as exc:
        raise RunbookEmbeddingError("Bedrock embedding response was not valid JSON") from exc

    embedding = payload.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise RunbookEmbeddingError(
            "Bedrock embedding response did not contain an embedding vector"
        )
    return embedding


def embed_chunk(
    chunk: RunbookChunk, *, region_name: str, model_id: str, client=None
) -> RunbookChunk:
    """Return a copy of chunk with its embedding populated."""
    embedding = embed_text(
        chunk.content, region_name=region_name, model_id=model_id, client=client
    )
    return replace(chunk, embedding=embedding, embedding_model=model_id)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    vec_a = np.asarray(a, dtype=float)
    vec_b = np.asarray(b, dtype=float)
    denom = float(np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)


def search_similar_chunks(
    query_embedding: list[float],
    candidates: list[tuple[str, list[float]]],
    *,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """Rank candidate chunks by cosine similarity to the query embedding.

    ``candidates`` = [(chunk_id, embedding), ...]. Returns the top_k
    (chunk_id, score) pairs sorted by descending similarity. Pure function —
    no DB/network — so the ranking logic is testable without a live corpus.
    """
    scored = [
        (chunk_id, cosine_similarity(query_embedding, embedding))
        for chunk_id, embedding in candidates
        if embedding
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]
