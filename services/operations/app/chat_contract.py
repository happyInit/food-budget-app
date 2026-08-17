"""Chat request/response contract and provider implementations.

Same provider split as ``rca_contract.py`` (mock/bedrock) and for the same
reason: the dashboard must never mistake a canned mock reply for a real
Bedrock answer, so the response always says which provider produced it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    snapshot: dict = Field(default_factory=dict)


class ChatResponse(BaseModel):
    answer: str
    provider: str
    guardrail_intervened: bool = False


class ChatProviderError(RuntimeError):
    """Raised when a non-mock chat provider fails to produce an answer."""


def build_mock_chat_response(request: ChatRequest) -> ChatResponse:
    """Deterministic placeholder so the UI can be built before Bedrock is wired.

    Not an attempt at real intent matching — it exists only to prove the
    request/response plumbing end to end. See ``feedback_no_confirmation_loops``-
    adjacent project convention: mock never pretends to be a real answer.
    """
    return ChatResponse(
        answer=(
            "Mock 응답입니다 — 실제 Bedrock 호출은 아직 연결되지 않았습니다. "
            f"질문: {request.question!r}"
        ),
        provider="mock",
    )


def build_bedrock_chat_response(
    request: ChatRequest,
    *,
    region_name: str,
    model_id: str,
    guardrail_id: str | None = None,
    guardrail_version: str | None = None,
    client=None,
) -> ChatResponse:
    """Call Bedrock Converse with the snapshot as context and return plain text.

    Unlike RCA, this does not force tool use — the answer is meant to be a
    short natural-language sentence, not a structured draft. ``client`` is
    injectable so unit tests do not require AWS credentials or network access.
    Credentials are resolved by boto3's standard provider chain (local
    profile, then EC2 Instance Profile once deployed).

    ``guardrail_id``/``guardrail_version`` are both-or-neither — pass both to
    apply the Contextual Grounding Check to this call, or leave both unset to
    call Bedrock without a guardrail (matches every other opt-in feature flag
    in this service: no guardrail configured means no guardrail applied,
    never a silent partial-config error).
    """
    from app.chat_prompt import SYSTEM_PROMPT, format_chat_context_for_prompt

    if client is None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - packaging safeguard
            raise ChatProviderError("boto3 is not installed") from exc
        client = boto3.client("bedrock-runtime", region_name=region_name)

    user_text = (
        f"{format_chat_context_for_prompt(request.snapshot)}\n\n"
        f"질문: {request.question}"
    )
    converse_kwargs: dict = {
        "modelId": model_id,
        "system": [{"text": SYSTEM_PROMPT}],
        "messages": [{"role": "user", "content": [{"text": user_text}]}],
    }
    if guardrail_id and guardrail_version:
        converse_kwargs["guardrailConfig"] = {
            "guardrailIdentifier": guardrail_id,
            "guardrailVersion": guardrail_version,
            "trace": "enabled",
        }
    try:
        response = client.converse(**converse_kwargs)
    except Exception as exc:
        raise ChatProviderError(f"Bedrock chat request failed: {exc}") from exc

    content = response.get("output", {}).get("message", {}).get("content", [])
    if not isinstance(content, list):
        raise ChatProviderError("Bedrock chat response content was malformed")
    text_blocks = [
        block["text"]
        for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ]
    if not text_blocks:
        raise ChatProviderError("Bedrock chat response did not contain any text")

    return ChatResponse(
        answer="\n".join(text_blocks),
        provider="bedrock",
        guardrail_intervened=response.get("stopReason") == "guardrail_intervened",
    )
