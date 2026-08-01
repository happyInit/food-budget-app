"""리뷰 종합 요약 배치 (#10 후반 — roadmap §10 "종합 요약 2~3문장").

감정분류(`score_review_sentiment.py`)가 **건당 라벨**을 만든다면, 이 배치는 **레시피당 1회**
후기를 읽고 2~3문장으로 요약한다. 주기가 다르므로 배치도 분리한다(원문이 DB에 있어 각각
독립 재실행이 가능하다 — 핸드오프 §3의 "원문 보관" 근거가 이것이다).

**모델은 실측으로 정한다.** roadmap §10 은 후보만 두고 *"자유 요약은 근거 재작성과 성격이 달라
실험 G 결과를 전용할 수 없다 — 구현 후 실측으로 확정"* 이라고 못 박았다.
`--model` 로 바꿔 끼울 수 있게 두고, `--compare` 로 같은 레시피에 여러 모델을 돌려 비교한다.

**대상**: 리뷰 **5건 이상**인 레시피(실측 3,086개). 5건 미만(3,787개)은 후기를 그대로 보여주는
편이 낫고, 요약이 오히려 정보를 줄인다.

**⚠️ 창작 금지가 핵심이다.** 요약은 근거 대조가 어려운 자유 서술이라(selection-final §5) 모델이
후기에 없는 내용을 지어내기 쉽다. 프롬프트로 막고, `--audit` 으로 표본을 원문과 함께 출력해
사람이 대조할 수 있게 한다.

사용:
  python pipelines/ingest/summarize_reviews.py --limit 5 --audit    # 품질 육안 확인
  python pipelines/ingest/summarize_reviews.py --compare --limit 3  # 모델 비교
  python pipelines/ingest/summarize_reviews.py --apply              # 전량
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

REGION = "ap-northeast-2"
# ── 모델 확정 (실측 2026-07-29, 표본 8레시피 · 후보 5종) ────────────────────
#  모델                  문장수  존댓말   길이    지연
#  nova-micro              2.4   1/8 ❌   119자    851ms
#  claude-3-haiku          3.2   8/8 ✅   168자  2,156ms   ← 빠르나 장황
#  claude-haiku-4.5        2.0   0/8 ❌   147자  2,260ms
#  claude-3-5-sonnet-v2    2.0   8/8 ✅   117자  3,566ms   ← 채택
#  claude-sonnet-4.5       2.5   7/8      177자  5,317ms
#
# **존댓말을 지키는 건 3-haiku 와 3.5-sonnet 둘뿐이다.** nova-micro·haiku-4.5 는 "~언급된다",
# "~필요하다" 평서체를 쓴다(실제 출력 확인). 요약문은 유저에게 그대로 보이므로 탈락.
#   · roadmap §10 이 "자유 요약은 refine 결과를 전용할 수 없다"고 경고한 지점이 정확히 이것이다 —
#     nova-micro 는 근거 재작성(refine)에서는 Gemini 동률이었으나 자유 요약에서는 지시를 어긴다.
#   · 신형이 항상 낫지 않다: haiku-4.5(0/8) < haiku-3(8/8).
# 3-haiku 는 1.65배 빠르지만 **3.2문장으로 "2~3문장"을 넘고** "이 후기들을 종합해보면" 같은
# 군더더기 서두가 붙는다. 3.5-sonnet 은 정확히 2문장·최단(117자)이라 채택.
# ⚠️ 배치 시간이 문제가 되면 3-haiku 가 유일한 대안이다(품질 대신 속도).
DEFAULT_MODEL = "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"
COMPARE_MODELS = [                                  # --compare 시 나란히 돌린다
    "apac.amazon.nova-micro-v1:0",
    "apac.anthropic.claude-3-haiku-20240307-v1:0",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",   # 2026-07-29 액세스 열림
]
# ── 대상·입력량 (비용 실측 2026-07-29) ──────────────────────────────────────
# 요약은 유료 호출이라 "얼마나 많이"가 아니라 **"어디에 값이 있나"**로 정한다.
#
#  입력 후기수별 건당 비용(sonnet, 실측):  30건 11.76원 · 20건 8.46원 · **15건 7.44원** · 10건 5.52원
#  임계별 대상:  ≥5 → 3,086개(리뷰 95.6% 커버) · **≥10 → 2,195개(91.4%)** · ≥30 → 1,051개(77.6%)
#
#  현재 조합(≥10 · 15건) = 약 16,331원.  ≥5 · 30건이면 36,291원 — **55% 절감에 품질 손실 없음.**
#
# ⚠️ 15건으로 줄여도 되는 결정적 이유: **긍정 비율은 전수 분류(141,282건)에서 나온다.**
#    요약이 통계를 짊어질 필요가 없고 **테마·팁만 건지면 되므로** 표본 15건이면 충분하다
#    (실측 비교에서 30건과 품질 차이가 보이지 않았다 — 둘 다 구체 팁을 동일하게 짚었다).
# ⚠️ 임계 10건: 5~9건 레시피(891개·평균 6.7건)는 후기를 **그대로 보여주는 편이 낫다** —
#    6건을 2문장으로 압축하면 정보가 줄어든다. 필요하면 `--min-reviews 5` 로 되돌릴 수 있다.
MIN_REVIEWS = 10

# ② **적응형 표본** — 고정 15건이면 대표성이 레시피마다 극단적으로 갈린다(실측):
#      10~29건 → 97% 커버 · 30~99건 → 31% · 100~299건 → 10% · **300건+ → 3.7%**
#    같은 "15건"인데 신뢰도가 다른데 화면에서는 똑같아 보인다. 리뷰가 많을수록 표본을 늘린다.
#    추가 비용 약 2,700원(큰 레시피가 330개뿐이라 총량 영향이 작다).
def sample_size(n: int) -> int:
    if n <= 20:
        return n          # 전수 — 20건 이하는 다 읽어도 싸다
    if n <= 100:
        return 20
    return 30

# 요약 대상: 리뷰 N건 이상 + (재요약 아니면) 아직 요약이 없는 레시피.
# 템플릿으로 임시로 채워진 것도 대상이다 — LLM 요약이 템플릿을 **승격**한다.
_TARGETS = """
SELECT r.recipe_id, count(*) AS n
  FROM recipe_review r
  LEFT JOIN recipe_review_summary s ON s.recipe_id = r.recipe_id
 WHERE (%(redo)s OR s.summary IS NULL OR s.summary_kind = 'template')
 GROUP BY r.recipe_id
HAVING count(*) >= %(min_n)s
 ORDER BY count(*) DESC
"""

# ③ 부정 라벨 후기만 — 주의사항 생성 입력. 표본에 섞지 않는다(비율 왜곡 방지).
_NEGATIVES = """
SELECT r.body FROM recipe_review r
  JOIN recipe_review_sentiment s ON s.review_id = r.id
 WHERE r.recipe_id = %(rid)s AND s.label = 'negative'
 ORDER BY r.seq LIMIT 10
"""

_CAUTION_PROMPT = (
    "다음은 한 레시피에 달린 후기 중 **부정적인 것만** 모은 것이다. "
    "여기서 **다음 사람이 알면 도움이 되는 주의사항**을 **1문장**으로 뽑아라.\n"
    "규칙:\n"
    "- 구체적인 실패 원인·조치만 쓴다(물 양·불세기·시간·대체재료). 단순 취향 불만은 제외.\n"
    "- 쓸 만한 주의사항이 없으면 정확히 `없음` 만 출력한다.\n"
    "- 존댓말 1문장. 서두·머리말 금지.\n\n"
    "부정 후기:\n"
)

# 전수 감정 라벨 분포 — 표본이 아니라 **전체** 기준이다(141,282건 분류 완료).
_DIST = """
SELECT count(*) AS total,
       count(*) FILTER (WHERE s.label = 'positive') AS pos,
       count(*) FILTER (WHERE s.label = 'neutral')  AS neu,
       count(*) FILTER (WHERE s.label = 'negative') AS neg
  FROM recipe_review r
  JOIN recipe_review_sentiment s ON s.review_id = r.id
 WHERE r.recipe_id = %(rid)s
"""

# ⚠️ 앞에서 N건만 자르면 **위치 편향**이 생긴다 — 후기 739건짜리에서 앞 30건(4%)만 보고
#    전체 논조를 요약하게 된다. seq 가 최신순인지 오래된순인지 DB 로는 판정할 수 없어
#    (리뷰 작성일 컬럼이 없다) 어느 쪽이든 한쪽 끝에 쏠린다.
#    → **전 구간 균등 추출**. random() 이 아니라 seq 기반이라 **재실행 시 같은 표본**이 나온다.
_REVIEWS = """
SELECT body FROM (
  SELECT body,
         row_number() OVER (ORDER BY seq) AS rn,
         count(*)     OVER ()             AS total
    FROM recipe_review
   WHERE recipe_id = %(rid)s AND body IS NOT NULL
) t
 WHERE (rn - 1) %% GREATEST(1, total / %(lim)s) = 0
 ORDER BY rn
 LIMIT %(lim)s
"""

# 요약은 집계행에 얹는다. 집계행이 없으면(감정분류 미완) 만들지 않는다 — 긍정비율 없이
# 요약만 있는 반쪽 행을 만들지 않기 위해서다.
# ⚠️ `model` 컬럼은 **감정분류 모델**이 이미 쓰고 있다(핸드오프 §4.1 "재실행 대상 특정").
#    요약이 덮어쓰면 "긍정비율을 어느 모델로 냈나"를 알 수 없게 된다 — 산출물이 둘인데
#    컬럼이 하나인 충돌이라 **요약 전용 컬럼**(`summary_model`)에 쓴다.
_UPDATE = """
UPDATE recipe_review_summary
   SET summary = %(summary)s, caution = %(caution)s, summary_model = %(model)s,
       summary_kind = 'llm', generated_at = now()
 WHERE recipe_id = %(rid)s
"""

_PROMPT = (
    "다음은 한 요리 레시피에 달린 후기들이다. 전체 논조를 **2~3문장**으로 요약해라.\n"
    "규칙:\n"
    "- **후기에 실제로 나온 내용만** 쓴다. 없는 내용을 지어내지 마라.\n"
    "- 좋은 점과 아쉬운 점이 함께 있으면 **둘 다** 담는다. 한쪽만 쓰면 왜곡이다.\n"
    "- 자주 반복되는 팁·주의점(물양·불세기·대체재료)이 있으면 우선 담는다.\n"
    "- 존댓말 평서문. 이모지·머리말·번호 금지. 요약문만 출력한다.\n\n"
    "후기:\n"
)


def build_prompt(bodies: list[str], dist: dict | None = None) -> str:
    """후기 표본 → 프롬프트. `dist` 가 있으면 **전수 분포**를 함께 알려준다.

    ⚠️ 왜 분포를 주입하나 — 표본은 15건이지만 감정 라벨은 **전수 141,282건**을 갖고 있다.
    부정 후기를 표본에 강제로 끼워 넣으면 **비율이 왜곡된다**(300건 중 2건=0.7% 인데
    15건 중 3건=20% 로 30배 과대대표). 대신 모델에게 **실제 비율을 알려주면**
    표본의 대표성을 해치지 않으면서 논조를 정확히 쓸 수 있다.
    덤으로 `positive_rate`(전수)와 요약(표본)이 어긋나 보이는 문제도 사라진다.
    """
    head = _PROMPT
    if dist and dist.get("total"):
        t = dist["total"]
        head += (f"[전체 분포] 이 레시피 후기 {t}건 중 "
                 f"긍정 {dist['pos'] * 100 // t}% · 중립 {dist['neu'] * 100 // t}% · "
                 f"부정 {dist['neg'] * 100 // t}%.\n"
                 f"아래는 그중 {len(bodies)}건 표본이다. **논조는 표본이 아니라 위 비율에 맞춰** 쓴다.\n\n")
    return head + "\n".join(f"- {b[:150]}" for b in bodies)


def caution_from(client, model_id: str, negatives: list[str], temperature: float = 0.0) -> str | None:
    """부정 후기 → 주의사항 1문장. 없으면 None.

    ⚠️ **요약 표본에 섞지 않는 이유** — 후기 300건 중 부정 2건(0.7%)을 15건 표본에 3건(20%)
    넣으면 30배 과대대표가 되어 좋은 레시피가 부당하게 나쁘게 보인다. 칸을 나누면
    "일부 후기" 프레이밍이 내장돼 비율을 왜곡하지 않고도 경고를 보존할 수 있다.
    """
    if not negatives:
        return None
    r = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [
            {"text": _CAUTION_PROMPT + "\n".join(f"- {b[:150]}" for b in negatives)}]}],
        inferenceConfig={"maxTokens": 120, "temperature": temperature},
    )
    t = (r["output"]["message"]["content"][0]["text"] or "").strip()
    if not t or t.startswith("없음") or len(t) < 8 or len(t) > 200:
        return None
    return t


def summarize(client, model_id: str, bodies: list[str], dist: dict | None = None,
              temperature: float = 0.0) -> str | None:
    """후기 묶음 → 요약 2~3문장. 빈 응답·과길이는 None(건너뛴다 — 억지로 채우지 않는다)."""
    r = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": build_prompt(bodies, dist)}]}],
        inferenceConfig={"maxTokens": 300, "temperature": temperature},
    )
    t = (r["output"]["message"]["content"][0]["text"] or "").strip()
    # 모델이 머리말("요약:")을 붙이는 경우가 있어 걷어낸다.
    for pre in ("요약:", "요약 :", "**요약**"):
        if t.startswith(pre):
            t = t[len(pre):].strip()
    if not t or len(t) < 10 or len(t) > 600:
        return None
    return t


def main() -> None:
    ap = argparse.ArgumentParser(description="리뷰 종합 요약(#10 후반)")
    ap.add_argument("--limit", type=int, help="상위 N개 레시피만")
    ap.add_argument("--min-reviews", type=int, default=MIN_REVIEWS)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    # temperature 0 이 완전 결정적이진 않지만(실측: 3회 중 2회 동일) 변동 폭은 줄어든다.
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--redo", action="store_true", help="이미 요약된 레시피도 다시 생성")
    ap.add_argument("--apply", action="store_true", help="실제로 저장(기본: 미리보기)")
    ap.add_argument("--audit", action="store_true", help="원문 표본과 요약을 함께 출력(창작 대조용)")
    ap.add_argument("--compare", action="store_true", help="후보 모델들을 같은 레시피에 나란히 실행")
    args = ap.parse_args()

    import boto3
    client = boto3.client("bedrock-runtime", region_name=REGION)

    with connect() as conn:
        targets = conn.execute(_TARGETS, {"redo": args.redo, "min_n": args.min_reviews}).fetchall()
    if args.limit:
        targets = targets[: args.limit]
    print(f"요약 대상 {len(targets):,}개 레시피 (리뷰 {args.min_reviews}건 이상)\n")

    models = COMPARE_MODELS if args.compare else [args.model]
    done = skipped = 0
    t0 = time.perf_counter()
    wconn = connect() if args.apply else None
    try:
        for rid, n in targets:
            with connect() as c:
                bodies = [b for (b,) in c.execute(_REVIEWS, {"rid": rid, "lim": sample_size(n)}).fetchall()]
                d = c.execute(_DIST, {"rid": rid}).fetchone()
                negs = [b for (b,) in c.execute(_NEGATIVES, {"rid": rid}).fetchall()]
            dist = {"total": d[0], "pos": d[1], "neu": d[2], "neg": d[3]} if d and d[0] else None
            if not bodies:
                skipped += 1
                continue

            for m in models:
                try:
                    text = summarize(client, m, bodies, dist, args.temperature)
                except Exception as exc:  # noqa: BLE001 — 한 건 실패가 배치를 죽이면 안 된다
                    print(f"  ⚠️ recipe={rid} {m.split('.')[-1][:24]} 실패({type(exc).__name__})")
                    text = None
                if text is None:
                    skipped += 1
                    continue

                if args.compare:
                    print(f"  [{m.split('.')[-1][:26]:26}] {text}")
                elif args.audit:
                    print(f"\n── recipe={rid} (후기 {n}건 · 표본 {len(bodies)} · 부정 {len(negs)}) ──")
                    for b in bodies[:4]:
                        print(f"   · {b[:70]}")
                    print(f"   → 요약: {text}")
                    try:
                        cau = caution_from(client, m, negs, args.temperature)
                    except Exception:
                        cau = None
                    print(f"   → 주의: {cau or '(없음)'}")
                elif not args.apply:
                    print(f"  recipe={rid} ({n}건) {text[:90]}")

                if args.apply and not args.compare:
                    # 주의사항은 부정 후기가 있을 때만 — 별도 호출이라 없으면 비용 0.
                    try:
                        caution = caution_from(client, m, negs, args.temperature)
                    except Exception:  # noqa: BLE001 — 주의사항 실패가 요약을 막으면 안 된다
                        caution = None
                    with wconn.cursor() as cur:
                        cur.execute(_UPDATE, {"rid": rid, "summary": text,
                                              "caution": caution, "model": m})
                        hit = cur.rowcount
                    wconn.commit()
                    if hit:
                        done += 1
                    else:
                        # 집계행이 없으면 저장되지 않는다 — 성공으로 세면 조용한 유실이 된다.
                        skipped += 1
                        print(f"  ⚠️ recipe={rid} 집계행 없음(감정분류 미완) — 요약 미저장")
            if args.compare:
                print(f"  ↑ recipe={rid} (후기 {n}건)\n")
        if args.apply and wconn is not None:
            wconn.commit()
    finally:
        if wconn is not None:
            wconn.close()

    el = time.perf_counter() - t0
    print(f"\n요약 {done:,}건 · 건너뜀 {skipped:,} · {el:.0f}s")
    if not args.apply:
        print("→ 미리보기(무변경). 적용하려면 --apply")


if __name__ == "__main__":
    main()
