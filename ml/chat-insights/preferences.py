"""장기 개인화 — 영속 대화 로그에서 유저 선호 신호 추출(chat-conversation-data-plan §1.2).

유저별로: 선호 재료(자주 언급) · 비선호 재료(제외 마커) · 예산 민감도 · 활동량.
출력 = reports/chat/preference-signals/YYYY-MM-DD.jsonl (기계 소비용) — 랭킹 재학습이
user_ing_affinity 등 피처로 환류하고, 챗봇 응답 개인화(비선호 회피)에도 쓴다.

⚠️ 민감정보(선호·비선호·예산) — 동의 유저만, 익명화는 user_id 논리값 유지(재조인용).
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

_DISLIKE_MARKERS = ("빼고", "빼줘", "제외", "싫어", "안 먹", "안먹", "못 먹", "못먹", "알레르기")
SIGNALS_DIR = os.environ.get("CHAT_REPORTS_DIR", "reports/chat")


def extract_signals(messages: list[dict]) -> dict[int, dict]:
    """user_id → 선호 신호. 규칙 기반(LLM 불필요) — 언급 빈도·제외 마커·예산 언급."""
    liked = defaultdict(Counter)      # user → item_id 빈도(선호)
    disliked = defaultdict(set)       # user → item_id(비선호 맥락에서 언급)
    budget_mentions = Counter()       # user → 예산 언급 횟수(가격 민감도 프록시)
    activity = Counter()              # user → 메시지 수
    for m in messages:
        if m.get("role") != "user":
            continue
        uid = m.get("user_id")
        if uid is None:
            continue
        activity[uid] += 1
        text = m.get("text") or ""
        items = m.get("item_ids") or []
        if any(k in text for k in _DISLIKE_MARKERS):
            disliked[uid].update(items)                 # 제외 맥락 → 비선호
        else:
            for i in items:
                liked[uid][i] += 1                       # 일반 언급 → 선호 후보
        if m.get("intent") in ("price_lookup", "recipe_cost") or "원" in text:
            budget_mentions[uid] += 1

    out: dict[int, dict] = {}
    for uid in set(activity):
        n = activity[uid]
        liked_items = [i for i, _ in liked[uid].most_common(10) if i not in disliked[uid]]
        out[uid] = {
            "user_id": uid,
            "liked_item_ids": liked_items,
            "disliked_item_ids": sorted(disliked[uid]),
            "budget_sensitivity": round(budget_mentions[uid] / n, 3) if n else 0.0,
            "activity": n,
        }
    return out


def write_signals(signals: dict[int, dict]) -> str:
    """user별 선호 신호를 jsonl로 저장(기계 소비). 경로 반환."""
    now = datetime.now(timezone.utc)
    path = os.path.join(SIGNALS_DIR, "preference-signals", f"{now:%Y-%m-%d}.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for sig in signals.values():
            f.write(json.dumps(sig, ensure_ascii=False) + "\n")
    return path


def upsert_to_pg(signals: dict[int, dict]) -> int:
    """선호 신호를 activity.user_chat_pref에 upsert → 랭킹이 user_ing_affinity 보강에 사용.
    테이블 없으면(미마이그레이션) skip(0). best-effort — 실패해도 jsonl은 남음."""
    if not signals:
        return 0
    try:
        from _data import connect
        with connect() as c, c.cursor() as cur:
            cur.execute("select to_regclass('activity.user_chat_pref')")
            if cur.fetchone()[0] is None:
                return 0
            for s in signals.values():
                cur.execute(
                    """insert into activity.user_chat_pref
                         (user_id, liked_item_ids, disliked_item_ids, budget_sensitivity, updated_at)
                       values (%s,%s,%s,%s, now())
                       on conflict (user_id) do update set
                         liked_item_ids=excluded.liked_item_ids,
                         disliked_item_ids=excluded.disliked_item_ids,
                         budget_sensitivity=excluded.budget_sensitivity,
                         updated_at=now()""",
                    (s["user_id"], s["liked_item_ids"], s["disliked_item_ids"], s["budget_sensitivity"]))
            c.commit()
        return len(signals)
    except Exception:  # noqa: BLE001 — DB 부재/장애 → jsonl만(무해)
        return 0


def generate(messages: list[dict]) -> tuple[str, dict[int, dict]]:
    signals = extract_signals(messages)
    path = write_signals(signals)
    upsert_to_pg(signals)   # 랭킹 환류용(테이블 있으면). 없으면 jsonl만.
    return path, signals
