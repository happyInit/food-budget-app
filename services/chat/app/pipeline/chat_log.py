"""chat_message 영속 — 동의(인증) 유저 대화 로그. 대화분석(ml/chat-insights) 입력 (#127).

게이팅: `CHAT_PERSIST_ENABLED` + 인증(JWT→user_id) 있을 때만 기록. 회원가입 일괄 동의라
**인증 = 동의**로 간주(미인증/익명은 저장 안 함). best-effort — 실패해도 응답을 막지 않는다.
user·bot 두 턴을 같은 session_id 로 묶어 저장(멀티턴 분석용).
"""
from __future__ import annotations

import json

from app.config import settings


async def persist_turns(pool, user_id, session_id, user_text, query, response) -> None:
    """유저 발화 + 봇 응답을 chat.chat_message 에 2행 insert. 컬럼=_data.COLUMNS 계약."""
    if not (settings.chat_persist_enabled and pool is not None and user_id is not None and session_id):
        return
    try:
        item_ids = list(query.item_ids) if getattr(query, "item_ids", None) else None
        basis = (json.dumps([b.model_dump() for b in response.basis], ensure_ascii=False)
                 if response.basis else None)
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "insert into chat.chat_message (user_id, session_id, role, text, intent, item_ids) "
                "values (%s, %s, 'user', %s, %s, %s)",
                (user_id, session_id, user_text, query.intent, item_ids))
            await cur.execute(
                "insert into chat.chat_message (user_id, session_id, role, text, intent, unanswered, basis) "
                "values (%s, %s, 'bot', %s, %s, %s, %s)",
                (user_id, session_id, response.reply, query.intent, response.unanswered, basis))
            await conn.commit()
    except Exception:   # noqa: BLE001 — 로그 영속 실패는 비치명(응답 무영향)
        return
