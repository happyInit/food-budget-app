"""리뷰 감정분류 배치 (#10 — ai-features-roadmap §10 "감정 분류").

**모델은 실측으로 확정돼 있다** — `apac.amazon.nova-micro-v1:0`(Bedrock 서울).
근거(`ai-model-migration-benchmark.md`): 감정 **24/25** vs Gemini 25/25(동급) · **351ms(2.2× 빠름)** ·
**0.0095원/건**. 리뷰는 건수가 많아(레시피당 중앙값 4 · 최대 739) 분류 단가·지연이 지배적이라
Bedrock 최저가로 돌리는 이득이 크다.

**규모.** 실측 2026-07-29 기준 `recipe_review` **141,298건**. 건당 0.0095원이면 전량 약 **1,342원**.
1건씩 호출하면 141,298회 왕복이라 지연이 지배한다 → **배치 프롬프트**(기본 20건/호출)로 묶는다.

**설계 판단**
- `model` 컬럼이 재실행 대상을 특정한다 — 모델 교체 시
  `select review_id from recipe_review_sentiment where model <> '<신규>'` 한 줄이면 된다(핸드오프 §4.1).
- **미분류만 처리**한다(`LEFT JOIN ... IS NULL`). 중단 후 재개가 기본 동작이라 긴 배치가 안전하다.
- 파싱 실패·라벨 이상은 **건너뛴다.** 억지로 neutral 을 넣으면 긍정 비율이 조용히 왜곡된다.
- 라벨은 스키마 CHECK(`positive|negative|neutral`)와 같은 어휘만 허용한다.

**요약(2~3문장)은 이 배치의 범위 밖이다** — 모델 미확정이고(자유 요약은 refine 과 성격이 달라
실험 G 결과를 전용할 수 없다) 사람 확인이 필요하다. 여기서는 **긍정 비율**까지만 만든다.

사용:
  python pipelines/ingest/score_review_sentiment.py --limit 200     # 시범
  python pipelines/ingest/score_review_sentiment.py --apply         # 전량
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

MODEL_ID = "apac.amazon.nova-micro-v1:0"   # 서울 — 데이터 레지던시(리뷰는 유저 생성 텍스트)
REGION = "ap-northeast-2"
BATCH = 20                                  # 1회 호출당 리뷰 수 — 141k건을 1건씩 돌리면 지연이 지배한다
_LABELS = ("positive", "negative", "neutral")

_PENDING = """
SELECT r.id, r.body
  FROM recipe_review r
  LEFT JOIN recipe_review_sentiment s ON s.review_id = r.id
 WHERE s.review_id IS NULL
 ORDER BY r.id
"""

_INSERT = """
INSERT INTO recipe_review_sentiment (review_id, label, model)
VALUES (%(review_id)s, %(label)s, %(model)s)
ON CONFLICT (review_id) DO NOTHING
"""

# 레시피별 집계 — 분류가 끝난 리뷰만으로 긍정 비율을 낸다.
# ⚠️ neutral 을 분모에서 빼지 않는다. "긍정 비율"은 전체 대비 긍정이라야 레시피 간 비교가 된다.
_SUMMARY = """
INSERT INTO recipe_review_summary (recipe_id, review_count, positive_rate, model)
SELECT r.recipe_id,
       count(*),
       round(100.0 * count(*) FILTER (WHERE s.label = 'positive') / count(*), 1),
       %(model)s
  FROM recipe_review r
  JOIN recipe_review_sentiment s ON s.review_id = r.id
 GROUP BY r.recipe_id
ON CONFLICT (recipe_id) DO UPDATE
   SET review_count = EXCLUDED.review_count,
       positive_rate = EXCLUDED.positive_rate,
       model = EXCLUDED.model,
       generated_at = now()
"""

_PROMPT_HEAD = (
    "다음은 요리 레시피에 달린 후기들이다. 각각의 감정을 분류해라.\n"
    "출력: JSON 배열만. 형식 [{\"i\":번호,\"label\":\"positive|negative|neutral\"}, ...]\n"
    "규칙:\n"
    "- positive=만족/칭찬, negative=불만/실패, neutral=사실 서술·질문·인사만.\n"
    "- 번호(i)는 입력과 **정확히 같은 수**만큼, 같은 순서로 낸다.\n"
    "- JSON 외 텍스트 금지.\n\n"
)


def build_prompt(items: list[tuple[int, str]]) -> str:
    """(id, body) 목록 → 배치 프롬프트. 모델에는 **순번만** 주고 DB id 는 노출하지 않는다."""
    lines = [f"{i}. {body[:200]}" for i, (_rid, body) in enumerate(items, start=1)]
    return _PROMPT_HEAD + "\n".join(lines)


def parse_labels(text: str, n: int) -> dict[int, str]:
    """모델 응답 → {순번: 라벨}. 형식 이탈·이상 라벨은 버린다(억지로 채우지 않는다)."""
    if "[" not in text:
        return {}
    try:
        arr = json.loads(text[text.index("["): text.rindex("]") + 1])
    except (ValueError, KeyError):
        return {}
    out = {}
    for e in arr if isinstance(arr, list) else []:
        if not isinstance(e, dict):
            continue
        i, label = e.get("i"), e.get("label")
        if isinstance(i, str) and i.isdigit():
            i = int(i)
        if isinstance(i, int) and 1 <= i <= n and label in _LABELS:
            out[i] = label
    return out


def score_batch(client, items: list[tuple[int, str]]) -> list[dict]:
    """리뷰 묶음 1개 → [{review_id, label, model}]. 실패분은 결과에 없다(다음 실행이 재시도)."""
    r = client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": build_prompt(items)}]}],
        inferenceConfig={"maxTokens": 20 * len(items) + 100, "temperature": 0.0},
    )
    got = parse_labels(r["output"]["message"]["content"][0]["text"], len(items))
    return [{"review_id": items[i - 1][0], "label": lb, "model": MODEL_ID}
            for i, lb in got.items()]


def main() -> None:
    ap = argparse.ArgumentParser(description="리뷰 감정분류(#10) — Bedrock nova-micro")
    ap.add_argument("--limit", type=int, help="상위 N건만(시범)")
    ap.add_argument("--batch", type=int, default=BATCH, help="1회 호출당 리뷰 수")
    ap.add_argument("--apply", action="store_true", help="실제로 적재(기본: 미리보기)")
    ap.add_argument("--summary-only", action="store_true", help="분류는 건너뛰고 집계만 갱신")
    args = ap.parse_args()

    import boto3
    client = boto3.client("bedrock-runtime", region_name=REGION)

    if not args.summary_only:
        with connect() as conn:
            pending = conn.execute(_PENDING).fetchall()
        if args.limit:
            pending = pending[: args.limit]
        print(f"미분류 리뷰 {len(pending):,}건 · 배치 {args.batch}건/호출 "
              f"→ 예상 호출 {(len(pending) + args.batch - 1) // args.batch:,}회 "
              f"· 예상 비용 약 {len(pending) * 0.0095:,.0f}원\n")

        done = failed = 0
        t0 = time.perf_counter()
        conn = connect() if args.apply else None
        try:
            for k in range(0, len(pending), args.batch):
                chunk = [(rid, body) for rid, body in pending[k: k + args.batch]]
                try:
                    rows = score_batch(client, chunk)
                except Exception as exc:      # noqa: BLE001 — 한 배치 실패가 전체를 죽이면 안 된다
                    failed += len(chunk)
                    print(f"  ⚠️ 배치 실패({type(exc).__name__}) — 다음 실행이 재시도한다")
                    continue
                failed += len(chunk) - len(rows)
                done += len(rows)
                if args.apply:
                    with conn.cursor() as cur:
                        for r in rows:
                            cur.execute(_INSERT, r)
                    conn.commit()             # 배치마다 커밋 — 중단해도 진행분이 남는다
                if done and done % 1000 < args.batch:
                    el = time.perf_counter() - t0
                    print(f"  {done:,}건 분류 ({el:.0f}s · {done / max(el, 1):.0f}건/s)")
        finally:
            if conn is not None:
                conn.close()
        el = time.perf_counter() - t0
        print(f"\n분류 {done:,}건 · 누락 {failed:,}건 · {el:.0f}s")
        if not args.apply:
            print("→ 미리보기(무변경). 적용하려면 --apply")
            return

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_SUMMARY, {"model": MODEL_ID})
            n = cur.rowcount
        conn.commit()
    print(f"→ recipe_review_summary {n:,}개 레시피 집계 갱신")


if __name__ == "__main__":
    main()
