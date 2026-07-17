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


async def set_recipes(redis, session_id: str, recipes: list[dict]) -> None:
    """직전 추천 레시피 저장(recipe_cost 계산 대상). recipes=[{name, ingredient_item_ids}]."""
    if not session_id or not recipes:
        return
    try:
        await redis.set(f"{_key(session_id)}:recipes",
                        json.dumps(recipes, ensure_ascii=False), ex=settings.multiturn_ttl_s)
    except Exception:
        return


async def get_recipes(redis, session_id: str) -> list[dict]:
    """세션의 직전 추천 레시피 목록. 없으면 빈 리스트."""
    if not session_id:
        return []
    try:
        raw = await redis.get(f"{_key(session_id)}:recipes")
        return json.loads(raw) if raw else []
    except Exception:
        return []


async def add_dislikes(redis, session_id: str, item_ids: list[int]) -> None:
    """비선호 재료 누적(세션 개인화). Redis set에 append + TTL 갱신."""
    if not session_id or not item_ids:
        return
    try:
        key = f"{_key(session_id)}:dislikes"
        await redis.sadd(key, *[str(i) for i in item_ids])
        await redis.expire(key, settings.multiturn_ttl_s)
    except Exception:
        return


async def get_dislikes(redis, session_id: str) -> list[int]:
    """세션의 비선호 재료 item_id 목록."""
    if not session_id:
        return []
    try:
        raw = await redis.smembers(f"{_key(session_id)}:dislikes")
        return [int(x) for x in raw]
    except Exception:
        return []


async def add_shown_recipes(redis, session_id: str, recipe_ids: list[int]) -> None:
    """이미 추천한 레시피 id 누적(중복 방지). Redis set + TTL."""
    if not session_id or not recipe_ids:
        return
    try:
        key = f"{_key(session_id)}:shown"
        await redis.sadd(key, *[str(i) for i in recipe_ids])
        await redis.expire(key, settings.multiturn_ttl_s)
    except Exception:
        return


async def get_shown_recipes(redis, session_id: str) -> list[int]:
    """세션에서 이미 보여준 레시피 id 목록."""
    if not session_id:
        return []
    try:
        raw = await redis.smembers(f"{_key(session_id)}:shown")
        return [int(x) for x in raw]
    except Exception:
        return []
