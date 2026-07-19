"""합성 chat_message — 실 대화 로그(#127 쓰기경로) 대기 중 파이프라인을 검증하기 위한 것.

실제 대화 분포를 모사: 의도 분포(recommend가 다수), 일부 미응답(unanswered),
유저별 재료 선호(개인화 신호), 커버리지 갭 품목(예: '마라탕' 반복 미응답). numpy 불필요.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

_INTENTS = ["recommend", "recommend", "recommend", "price_lookup", "nutrition", "recipe_cost", "unknown"]
# 유저 페르소나별 자주 언급하는 재료(개인화 신호) — item_id
_PERSONA_ITEMS = {0: [10, 11], 1: [20, 21], 2: [30]}   # 돼지고기류 / 닭류 / 두부
_UNANSWERED_TERMS = ["마라탕", "분모자", "탕후루"]        # 데이터에 없어 반복 미응답(커버리지 갭)
_TERMS = {"recommend": "뭐 해먹지", "price_lookup": "얼마야", "nutrition": "칼로리",
          "recipe_cost": "재료비", "unknown": "음"}


def make_messages(n_users: int = 30, sessions_per_user: int = 3, seed: int = 3) -> list[dict]:
    """유저 n_users명의 대화 메시지(user·bot 페어) 리스트 — chat_message 컬럼 계약."""
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    mid = 1
    for u in range(n_users):
        persona = u % 3
        for s in range(sessions_per_user):
            sess = str(uuid.uuid4())
            for _turn in range(rng.randint(1, 4)):
                # 20% 미응답(커버리지 갭 용어) / 80% 정상 의도
                if rng.random() < 0.2:
                    intent, items, unanswered = "unknown", [], True
                    text = f"{rng.choice(_UNANSWERED_TERMS)} {rng.choice(['레시피', '어떻게 만들어'])}"
                else:
                    intent = rng.choice(_INTENTS)
                    items = _PERSONA_ITEMS.get(persona, []) if rng.random() < 0.6 else []
                    unanswered = False
                    text = f"{'·'.join(str(i) for i in items) or '뭔가'} {_TERMS[intent]}"
                created = now - timedelta(days=rng.uniform(0, 7), minutes=mid)
                rows.append({"id": mid, "user_id": u + 1, "session_id": sess, "role": "user",
                             "text": text, "intent": intent, "item_ids": items,
                             "unanswered": unanswered, "basis": None, "created_at": created})
                mid += 1
                rows.append({"id": mid, "user_id": u + 1, "session_id": sess, "role": "bot",
                             "text": "..." if unanswered else "여기 있어요",
                             "intent": intent, "item_ids": items, "unanswered": unanswered,
                             "basis": None if unanswered else [{"type": "recipe_match"}],
                             "created_at": created + timedelta(seconds=1)})
                mid += 1
    return rows
