"""소비기한 참조표 초안 생성 (ai-spec §6 — A안 "검수 테이블 하이브리드"의 ① 초안 생성).

**무엇을 메우나.** `shelf_life_ref` 에 item_id 앵커가 붙은 품목은 **CURATED 153건뿐**이라
`item_master` 461개 중 **121개(26%)만 커버**된다. 나머지는 `lookup_shelf_life` 가 None 을 돌려
`pantry_item.expire_at` 이 NULL 로 남고 → **임박 알림(F8)이 아예 동작하지 않는다.**

미커버 품목은 곰취·머위·다슬기·라이스페이퍼처럼 **한식 롱테일**이다. FoodKeeper(US, 1,111건)는
item_id 앵커가 0건이라 이들을 못 잡는다 — ai-spec §6이 *"FoodKeeper는 US 기준이라 한식 매칭률
낮음 → AI 초안 생성의 역할이 오히려 확대됨"* 이라고 예측한 그대로다.

**왜 Bedrock nova-micro 인가.** ai-spec §6은 초안 생성을 Gemini 로 적었고 그래서 "유료예외 재승인"이
블로커였다. 그 사유는 **개인 유료 SaaS 확대**였는데, AGENTS.md §3 갱신(2026-07-28)으로 비용 주체가
**팀 AWS Bedrock 크레딧**으로 바뀌며 "학생 예산" 제약을 벗어났다 → 블로커 소멸.
태스크 유형도 **텍스트→구조화 JSON**이라 실측상 nova-micro 가 채택 모델이다
(`ai-model-selection-final.md` 횡단 결정표).

**⚠️ 식품안전 원칙.**
- 생성분은 `source='AI_DRAFT'` 로 표시한다. 조회는 **CURATED 우선**이라 검수본을 덮지 못한다.
- 모델에 **보수적 추정**(짧은 쪽)을 요구한다 — 소비기한을 길게 잡으면 유저가 상한 음식을 먹는다.
- 상한 캡(`_MAX_DAYS`)을 코드로 건다. 모델이 과대 추정해도 그 이상은 저장하지 않는다.
- 사람 검수 후 `source` 를 `CURATED` 로 승격하는 것이 최종 형태다(이 배치는 초안까지만).

사용:
  python pipelines/ingest/draft_shelf_life.py --limit 5      # 미리보기
  python pipelines/ingest/draft_shelf_life.py --apply        # 전량 적재
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

MODEL_ID = "apac.amazon.nova-micro-v1:0"   # 서울 — 데이터 레지던시
REGION = "ap-northeast-2"

# 보관방법별 상한(일). 모델이 과대 추정해도 이 이상은 저장하지 않는다 — 식품안전 방어선.
_MAX_DAYS = {"ROOM": 180, "FRIDGE": 60, "FREEZER": 365}
# ⚠️ **FREEZER 는 AI 초안 대상에서 뺀다.** 실측에서 삼치·황태·멜론·호두·아몬드에 일괄
#    "6~12일" 을 반환했다 — 냉동 보관은 수개월~1년인데 모델이 구분하지 못하는 퇴화 출력이다.
#    냉동품에 12일을 붙이면 멀쩡한 식재료가 임박 알림으로 떠서 유저가 버린다(식비 절약과 역행).
#    빼면 그 보관은 추정 없음(expire_at NULL) = 현행과 동일 → **회귀 없이 오탐만 제거**된다.
_STORAGES = ("ROOM", "FRIDGE")

# 대상은 **신선식품에 한정**한다. 실측(2026-07-29)으로 좁힌 근거:
#  · 상비 양념 35종 → 수작업 큐레이션이 더 정확(2026-07-29c 시드). AI 는 여기서 크게 틀린다
#    (후추 FREEZER 6~12일 · 된장 냉동 1~6일 — 상온 보관품에 짧은 냉장창을 붙인다).
#  · 가공식품(스팸·소시지·만두·단무지) → **포장에 소비기한이 표기**돼 있다. 추정할 이유가 없고,
#    추정치가 포장 표기와 어긋나면 유저를 혼란시킨다.
#  · 곡류·견과·건조허브 → 상온 장기 보관품이다. 실측에서 모델이 호두·아몬드·현미·찹쌀가루에
#    **일괄 "FREEZER 6~12일"** 을 반환했다(견과는 냉동 1년 이상) — 모르는 품목에 같은 값을
#    반복하는 퇴화 출력이라 신뢰할 수 없다. 이들도 큐레이션 대상으로 넘긴다.
#  → 남는 것이 **실제로 부패하는** 채소·과일·수산물·육류·버섯·유제품이다.
_FRESH_CATEGORIES = ("채소", "과일", "수산물", "육류", "버섯", "유제품", "난류", "발효식품")

# 분류가 신선이어도 **건조품**은 제외한다 — 황태·북어는 '수산물'이지만 상온 장기 보관이다.
# 실측: 황태에 FRIDGE 1~3일이 붙었다(실제로는 수개월).
#
# ── 건조 해조류 4종을 **앵커로** 추가 (2026-07-30) ──────────────────────────────
# 이름에 '건조·마른' 표기가 없는 건조품이 또 있었다. 실측: 김·다시마·미역·톳에
# **FRIDGE 1~3일**이 붙었다(전부 건조 유통이 통상이라 실제로는 수개월).
# 마른김을 3일 뒤 임박 알림으로 띄우면 유저가 멀쩡한 김을 버린다 — **식비 절약과 역행**하고,
# 오래 두는 상비품이라 알림이 **반복**되어 알림 신뢰도까지 깎는다.
# 데이터는 `2026-07-30j` 로 교정했으나 **이 패턴을 고치지 않으면 재생성 때 같은 값이 다시 나온다.**
#
# 🔴 **반드시 앵커(`^...$`)를 쓴다.** 부분일치로 두면 `김` 이 **김치**(발효식품 — 냉장 기한이
#    실제로 필요하다)를 걸어 초안 대상에서 빼버린다. 실측: `canonical_name LIKE '%김%'` =
#    김 · **김치** · 튀김가루. 튀김가루는 곡류라 애초에 대상이 아니지만 김치는 대상이다.
#
# ⚠️ **청각·매생이는 넣지 않았다.** 넷과 달리 `CURATED ROOM` 행이 없다 —
#    "장기보관"이라는 근거가 데이터에 없다는 뜻이다. 매생이는 냉동·생 유통이 주류라 FRIDGE
#    1~2일이 **실제로 맞다**. 청각은 건조 유통이 흔하나 근거가 없어 **추측하지 않고 남겼다**
#    (`ai-verification-backlog.md` §1.2). 여기서 뭉뚱그리면 매생이가 틀어진다.
_DRIED_PATTERN = (r'건조|말린|황태|북어|건포도|건새우|말랭이|가루|분말|차$'
                  r'|^(?:김|미역|다시마|톳)$')

# ⚠️ 커버 판정은 **(item_id, storage) 조합**이다 — `lookup_shelf_life` 가 그 조합으로 찾는다.
#    item_id 만 보면 "ROOM 만 있는 감자"가 커버됨으로 잡혀 **FRIDGE 가 영영 안 채워진다**
#    (실측 2026-07-29: 감자·바나나가 ROOM+FREEZER 만 있어 유저의 FRIDGE 재고가 계속 미커버였다).
_UNCOVERED = """
SELECT im.item_id, im.canonical_name, im.category
  FROM item_master im
 WHERE im.category = ANY(%(cats)s)
   AND im.canonical_name !~ %(dried)s
   AND EXISTS (
     SELECT 1 FROM unnest(%(storages)s::text[]) st
      WHERE NOT EXISTS (SELECT 1 FROM public.shelf_life_ref s
                         WHERE s.item_id = im.item_id AND s.storage = st)
   )
 ORDER BY im.item_id
"""

# 이미 그 (품목, 보관) 이 있으면 넣지 않는다 — CURATED 를 덮지 않기 위한 마지막 방어선.
_INSERT = """
INSERT INTO public.shelf_life_ref (source, food_category, item_name, storage,
                                   days_min, days_max, note, item_id)
SELECT 'AI_DRAFT', %(category)s, %(name)s, %(storage)s, %(dmin)s, %(dmax)s, %(note)s, %(item_id)s
 WHERE NOT EXISTS (SELECT 1 FROM public.shelf_life_ref x
                    WHERE x.item_id = %(item_id)s AND x.storage = %(storage)s)
"""

_PROMPT = (
    "한국에서 유통되는 식재료의 **소비기한**을 보관방법별로 추정해 JSON으로만 답해라.\n"
    "형식: {\"ROOM\":{\"min\":정수|null,\"max\":정수|null},"
    "\"FRIDGE\":{...},\"FREEZER\":{...},\"note\":\"짧은 근거|빈문자열\"}\n"
    "규칙:\n"
    "- 단위는 **일수**. 해당 보관이 부적절하면 그 항목은 null (예: 생선의 ROOM).\n"
    "- **보수적으로(짧게) 추정한다.** 소비기한을 길게 잡으면 유저가 상한 음식을 먹는다.\n"
    "- 개봉/손질 후 기준이면 note에 적는다. 확신이 없으면 그 보관은 null.\n"
    "- JSON 외 텍스트 금지.\n"
    "품목: "
)


def _client():
    import boto3

    return boto3.client("bedrock-runtime", region_name=REGION)


def draft_one(client, name: str, category: str | None) -> dict | None:
    """품목 1건 → 보관별 초안. 파싱 실패는 None(건너뛴다 — 억지로 채우지 않는다)."""
    q = f"{name}" + (f" (분류: {category})" if category else "")
    r = client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": _PROMPT + q}]}],
        inferenceConfig={"maxTokens": 200, "temperature": 0.0},
    )
    text = r["output"]["message"]["content"][0]["text"].strip()
    if "{" not in text:
        return None
    try:
        return json.loads(text[text.index("{"): text.rindex("}") + 1])
    except (ValueError, KeyError):
        return None


def rows_from_draft(item_id: int, name: str, category: str | None, draft: dict) -> list[dict]:
    """초안 → 적재 행. 상한 캡·유효성 검사를 여기서 건다(순수 함수 — 테스트 가능)."""
    note = (draft.get("note") or "")[:200]
    out = []
    for st in _STORAGES:
        d = draft.get(st) or {}
        dmin, dmax = d.get("min"), d.get("max")
        if not isinstance(dmax, int) or dmax <= 0:      # 상한이 없으면 그 보관은 저장하지 않는다
            continue
        if not isinstance(dmin, int) or dmin <= 0 or dmin > dmax:
            dmin = None
        cap = _MAX_DAYS[st]
        dmax = min(dmax, cap)                            # 과대 추정 방어
        if dmin is not None:
            dmin = min(dmin, dmax)
        out.append({"item_id": item_id, "name": name, "category": category,
                    "storage": st, "dmin": dmin, "dmax": dmax, "note": note})
    return out


def run(*, limit=None, apply=False, has_time=None, emit=print) -> dict:
    """초안 생성 본체. **CLI 와 Lambda 가 같이 쓴다.**

    has_time — 매 품목 전에 불러 "아직 시간이 남았나"를 bool 로 답하는 함수.
               None 이면 시간을 보지 않는다(프로세스는 상한이 없다).
               Lambda 는 15분 상한이 있어 이걸 넘긴다 — 잘리는 대신 **스스로 멈춘다.**
    emit     — 한 줄 출력. CLI 는 print, Lambda 는 로거를 넘긴다.

    반환 = 처리 요약. Lambda 는 이걸 그대로 돌려주고 CLI 는 사람이 읽게 찍는다.
    """
    with connect() as conn:
        targets = conn.execute(_UNCOVERED, {"cats": list(_FRESH_CATEGORIES),
                                            "dried": _DRIED_PATTERN,
                                            "storages": list(_STORAGES)}).fetchall()
    if limit:
        targets = targets[:limit]
    emit(f"미커버 **신선식품** {len(targets)}개 "
         f"(상비양념=수작업 큐레이션 · 가공식품=포장표기 → 대상 제외) · "
         f"source='AI_DRAFT' 로 적재 — CURATED 를 덮지 않는다")

    client = _client()
    made = skipped = done = 0
    stopped_early = False
    conn = connect() if apply else None
    try:
        for item_id, name, category in targets:
            # 시간 가드는 **품목 사이**에 둔다 — 한 품목을 반쯤 처리하고 끊기지 않는다.
            if has_time is not None and not has_time():
                stopped_early = True
                emit(f"⏱ 시간 상한 임박 — {done}/{len(targets)} 에서 자진 중단(남은 것은 다음 실행에서)")
                break
            done += 1
            draft = draft_one(client, name, category)
            if not draft:
                skipped += 1
                continue
            rows = rows_from_draft(item_id, name, category, draft)
            if not rows:
                skipped += 1
                continue
            made += len(rows)
            if apply:
                with conn.cursor() as cur:
                    for r in rows:
                        cur.execute(_INSERT, r)
            else:
                shown = " · ".join(f"{r['storage']} {r['dmin'] or '-'}~{r['dmax']}일" for r in rows)
                emit(f"  {name:12} {shown}")
        if apply:
            conn.commit()   # 자진 중단이어도 여기까지 한 것은 커밋한다(멱등이라 재실행이 안전).
    finally:
        if conn is not None:
            conn.close()

    emit(f"초안 {made}행 생성 · 건너뜀 {skipped}품목(파싱 실패·유효값 없음)")
    emit("→ 적재 완료" if apply else "→ 미리보기(무변경). 적용하려면 --apply / apply=true")
    emit("⚠️ AI_DRAFT 는 **검수 전** 값이다. 사람이 확인 후 source 를 CURATED 로 승격할 것.")
    return {"made": made, "skipped": skipped, "processed": done,
            "targets": len(targets), "remaining": len(targets) - done,
            "applied": apply, "stopped_early": stopped_early}


def main() -> None:
    ap = argparse.ArgumentParser(description="소비기한 참조표 AI 초안 생성(ai-spec §6 ①)")
    ap.add_argument("--limit", type=int, help="상위 N개 품목만(미리보기·시범)")
    # 기본 dry-run — 식품안전 항목이라 명시적 --apply 를 요구한다.
    ap.add_argument("--apply", action="store_true", help="실제로 INSERT(기본: 미리보기만)")
    args = ap.parse_args()
    run(limit=args.limit, apply=args.apply)


if __name__ == "__main__":
    main()
