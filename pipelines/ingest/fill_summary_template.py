"""리뷰가 적은 레시피의 요약 칸 채우기 — LLM 없이 집계로 (#10 보완).

**무엇을 메우나.** LLM 요약은 후기 10건 이상 레시피(2,195개)만 대상이다. 나머지
**4,678개(1~9건)** 는 요약이 비어 화면에 빈칸이 생긴다 — 유저는 "왜 이 레시피만 요약이 없지?"
라고 느끼고, 요약 유무가 레시피마다 갈리면 일관성이 깨진다.

**왜 LLM 을 안 쓰나.** 후기 3건을 2문장으로 압축하면 **정보가 줄어든다**(원문을 읽는 편이 낫다).
게다가 4,678건에 유료 호출을 더하면 비용이 배로 뛴다. 대신 이미 가진 **전수 감정 라벨**로
사실만 서술한다 — 창작이 없어 검증이 필요 없고 **비용 0**이다.

문구는 후기 수에 따라 달라진다. 1건에 "1건 중 1건이 긍정" 은 통계처럼 보여 어색하므로
건수가 적을 땐 그대로 말한다.

사용:
  python pipelines/ingest/fill_summary_template.py            # 미리보기
  python pipelines/ingest/fill_summary_template.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

# LLM 요약이 없는 레시피 + 전수 감정 분포.
# ⚠️ **LLM 요약 대상(리뷰 MIN_REVIEWS 이상)은 건드리지 않는다.**
#    두 배치가 같은 칸을 쓰므로 경계를 SQL 로 못박지 않으면 서로를 덮는다
#    (실측 2026-07-29: 경계가 없어 템플릿이 LLM 대상 2,192건까지 채워 버렸다).
_TARGETS = """
SELECT s.recipe_id, s.review_count,
       count(*) FILTER (WHERE t.label = 'positive') AS pos,
       count(*) FILTER (WHERE t.label = 'negative') AS neg
  FROM recipe_review_summary s
  JOIN recipe_review r ON r.recipe_id = s.recipe_id
  JOIN recipe_review_sentiment t ON t.review_id = r.id
 WHERE s.summary IS NULL
   AND s.review_count < %(min_llm)s
 GROUP BY s.recipe_id, s.review_count
 ORDER BY s.recipe_id
"""

_UPDATE = """
UPDATE recipe_review_summary
   SET summary = %(summary)s, summary_kind = 'template', generated_at = now()
 WHERE recipe_id = %(rid)s AND summary IS NULL
"""

# LLM 요약 임계 — summarize_reviews 와 **같은 값이어야 경계가 맞는다**.
from summarize_reviews import MIN_REVIEWS as _MIN_LLM  # noqa: E402


def build_text(n: int, pos: int, neg: int) -> str | None:
    """건수·긍정수 → 사실 문장. 창작 없음."""
    if n <= 0:
        return None
    if n == 1:
        return "후기가 1건 있습니다." if pos == 0 else "후기 1건이 긍정적입니다."
    if n <= 4:
        base = f"후기 {n}건 중 {pos}건이 긍정적입니다."
    else:
        base = f"후기 {n}건 중 {pos}건({pos * 100 // n}%)이 긍정적입니다."
    if neg:
        base += f" 아쉬웠다는 의견도 {neg}건 있습니다."
    return base


def main() -> None:
    ap = argparse.ArgumentParser(description="리뷰 적은 레시피 요약 템플릿 채우기")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with connect() as conn:
        rows = conn.execute(_TARGETS, {"min_llm": _MIN_LLM}).fetchall()
    if args.limit:
        rows = rows[: args.limit]
    print(f"대상 {len(rows):,}개 레시피 (LLM 요약 없음 · 집계로 채움 · 비용 0)\n")

    made = 0
    conn = connect() if args.apply else None
    try:
        for rid, n, pos, neg in rows:
            text = build_text(n, pos, neg)
            if not text:
                continue
            if args.apply:
                with conn.cursor() as cur:
                    cur.execute(_UPDATE, {"rid": rid, "summary": text})
                    made += cur.rowcount
            else:
                if made < 8:
                    print(f"  recipe={rid} ({n}건) {text}")
                made += 1
        if args.apply:
            conn.commit()
    finally:
        if conn is not None:
            conn.close()
    print(f"\n{'적재' if args.apply else '생성 예정'} {made:,}건")
    if not args.apply:
        print("→ 미리보기(무변경). 적용하려면 --apply")


if __name__ == "__main__":
    main()
