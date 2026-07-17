"""멀티턴 세션 — Redis 단기 저장(영속 X). 최근 N턴을 유지해 팔로우업 승계.

키 `chat:sess:{session_id}` = 턴 JSON 리스트. LTRIM으로 최근 N턴만, EXPIRE로 단기 TTL.
opt-in(`config.multiturn_enabled`) — OFF면 main.py가 호출 자체를 안 함(기존 단일턴 무손상).
Redis 장애는 전부 조용히 삼켜 **무맥락으로 degrade**(응답 실패 아님).
"""
from __future__ import annotations

import json

from app.config import settings


def _key(session_id: str) -> str:
    return f"chat:sess:{session_id}"


async def load_history(redis, session_id: str) -> list[dict]:
    """최근 턴 리스트(오래된→최신). 세션 없거나 장애면 빈 리스트."""
    if not session_id:
        return []
    try:
        raw = await redis.lrange(_key(session_id), 0, -1)
    except Exception:
        return []
    out: list[dict] = []
    for s in raw:
        try:
            out.append(json.loads(s))
        except Exception:
            continue
    return out


async def append_turn(
    redis,
    session_id: str,
    role: str,
    text: str,
    item_ids: list[int] | None = None,
    item_names: list[str] | None = None,
    intent: str | None = None,
) -> None:
    """한 턴 추가 → 최근 N턴으로 트림 → TTL 갱신. 실패는 무시(저장 실패가 응답을 막지 않음)."""
    if not session_id:
        return
    turn = {
        "role": role,
        "text": text,
        "item_ids": item_ids or [],
        "item_names": item_names or [],
        "intent": intent,
    }
    try:
        key = _key(session_id)
        await redis.rpush(key, json.dumps(turn, ensure_ascii=False))
        await redis.ltrim(key, -settings.multiturn_max_turns, -1)
        await redis.expire(key, settings.multiturn_ttl_s)
    except Exception:
        return
