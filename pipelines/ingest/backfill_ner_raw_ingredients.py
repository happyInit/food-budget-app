"""RAW 재료 덩어리 → CRF NER 구조화 백필 (#5 재료 NER 서빙).

**무엇을 고치나.** 크롤러가 재료 섹션을 쪼개지 못한 레시피가 있다. 그 행은
`ner_status='RAW'` 로 남고 `ingredient_name` 이 비어 있어, 재료 전체가 통째로 한 칸에 들어간다:

    [주재료] 소고기(치맛살)(100g), 김(6g(3장)), 튀김가루(20g)<br>[양념] …
    •필수 재료 : 비름나물(70g), 양파(10g), 마늘(3g), 생강(1g)

`item_id` 가 하나도 안 붙으므로 이 레시피들은 **재료비·재고매칭·추천·랭킹 어디에도 안 잡힌다.**
실측(2026-07-29): RAW 1,143행 = 레시피 1,143개, 매칭 0건. 이 레시피들은 재료가 **없는 것과 같다.**

**왜 CRF 인가.** `ml/ingredient-ner` CRF 는 **바로 이 분포**(레시피 재료 목록)로 학습됐다
(gold F1 0.924). 섹션 헤더·괄호 수량·쉼표 나열이 학습 데이터 그 자체다.
⚠️ 같은 모델을 **채팅에 쓰면 안 된다** — 대화 문장에서는 조사·동사째 과다추출한다
(train/serve 불일치, `span_extractor/ner.py` 경고). 채팅은 rule 유지가 방침이고,
**이 배치가 CRF 의 정당한 용도**다(README §다음단계 "(a) 레시피 ingredient_raw 구조화").

**안전성.** RAW 레시피는 CRAWLER·LABELED 행을 **하나도 갖고 있지 않다**(실측 확인) → 순수 추가라
중복 위험이 없다. RAW 행(seq=1)은 출처로 남기고 추출분을 seq=2.. 로 넣는다.
기본은 dry-run — `--apply` 없이는 아무것도 쓰지 않는다.

사용:
  python pipelines/ingest/backfill_ner_raw_ingredients.py --limit 20      # 미리보기
  python pipelines/ingest/backfill_ner_raw_ingredients.py --apply         # 전량 적용
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402
from quantity import MEASURE_ML, PIECE, VOLUME_ML, WEIGHT_G  # noqa: E402  정본 단위 어휘

_REPO = Path(__file__).resolve().parents[2]
_MODEL = _REPO / "ml" / "ingredient-ner" / "data" / "model" / "crf_ingredient.pkl"

_SELECT_RAW = """
SELECT id, recipe_id, ingredient_raw
  FROM recipe_ingredient
 WHERE ner_status = 'RAW' AND ingredient_raw IS NOT NULL AND btrim(ingredient_raw) <> ''
 ORDER BY recipe_id
"""

# 이미 백필된 레시피는 건너뛴다(재실행 멱등).
_ALREADY = "SELECT DISTINCT recipe_id FROM recipe_ingredient WHERE ner_status = 'NER_PARSED'"

_INSERT = """
INSERT INTO recipe_ingredient (recipe_id, seq, ingredient_name, quantity, ingredient_raw,
                               ner_status, item_id)
VALUES (%(recipe_id)s, %(seq)s, %(name)s, %(qty)s, %(raw)s, 'NER_PARSED', %(item_id)s)
"""

# ── 분량 집기 ───────────────────────────────────────────────────────────────
# 재료명 **바로 뒤**에 오는 계량만 받는다. 스팬 사이 구간을 통째로 쓰면 레시피 제목·섹션
# 헤더가 딸려온다 — 실측에서 "방울토마토" 뒤 구간이 "소박이 : \n방울토마토 150g(5개)" 로
# 잡혔다. **틀린 분량은 재료비를 그대로 왜곡하므로 애매하면 비운다**(servings_known 과 같은 원칙).
_UNITS = sorted(
    set(list(WEIGHT_G) + list(VOLUME_ML) + list(MEASURE_ML) + list(PIECE)),
    key=len, reverse=True,
)
_QTY_LEAD = re.compile(
    r"^[\s,·•\-–:/(\[]*"                                  # 구분자·여는 괄호
    r"(\d+(?:\s*[½⅓¼¾])?(?:[./]\d+)?|[½⅓¼¾]|반)"            # 수량(정수·분수·유니코드 분수)
    r"\s*(" + "|".join(map(re.escape, _UNITS)) + r")"       # 단위
)


def _quantity_between(text: str, start: int, end: int) -> str | None:
    """재료명 직후 구간에서 **선두 계량**만 집는다. 없으면 None(추정하지 않는다)."""
    m = _QTY_LEAD.match(text[start:end])
    return f"{m.group(1)}{m.group(2)}" if m else None


# 헤더 줄 — 레시피 제목·섹션명("고명", "●양념장"). 숫자도 쉼표도 없는 짧은 줄이다.
# ⚠️ 스팬이 **줄바꿈을 넘지 못하게** 해야 한다. 실측(2026-07-29): 제목과 첫 재료가 붙어
#    '새우두부계란찜\n연두부' 가 한 스팬으로 나왔다(학습 때는 제목줄을 마스킹하지만
#    추론 경로엔 그 처리가 없었다). 줄 단위로 돌리면 구조적으로 막힌다.
def _is_header(line: str) -> bool:
    t = line.strip(" ●•[]()")
    return bool(t) and not any(c.isdigit() for c in t) and "," not in t and len(t) <= 12


def structure(raw: str, extractor, resolve) -> list[dict]:
    """덩어리 1건 → [{name, quantity, item_id}]. 순수 함수(DB 무관) — 테스트 가능."""
    import asyncio

    out = []
    for line in raw.replace("<br>", "\n").split("\n"):
        if not line.strip() or _is_header(line):
            continue
        spans = asyncio.run(extractor.extract_spans(line))
        cursor = 0
        for i, name in enumerate(spans):
            pos = line.find(name, cursor)
            if pos < 0:                  # 스팬이 원문에 없으면(정규화 차이) 분량 없이 담는다
                out.append({"name": name, "quantity": None, "item_id": resolve(name)})
                continue
            tail = pos + len(name)
            nxt = line.find(spans[i + 1], tail) if i + 1 < len(spans) else len(line)
            out.append({
                "name": name,
                "quantity": _quantity_between(line, tail, max(nxt, tail)),
                "item_id": resolve(name),
            })
            cursor = tail
    return out


def _load_tools():
    """CRF 추출기 + gazetteer 매처. 챗·영상과 **같은 gazetteer** 를 쓴다(매칭 규칙 불일치 방지)."""
    sys.path.insert(0, str(_REPO / "services" / "chat"))
    from app.pipeline.span_extractor.ner import CrfSpanExtractor  # noqa: PLC0415

    from gazetteer import load_gazetteer, load_meat_canons, make_matcher  # noqa: PLC0415

    extractor = CrfSpanExtractor(str(_MODEL))
    with connect() as conn, conn.cursor() as cur:
        match = make_matcher(load_gazetteer(cur), load_meat_canons(cur))

    def resolve(name: str) -> int | None:
        item_id, _canon, _method = match(name or "")
        return item_id

    return extractor, resolve


def main() -> None:
    ap = argparse.ArgumentParser(description="RAW 재료 덩어리 CRF 구조화 백필")
    ap.add_argument("--limit", type=int, help="상위 N개 레시피만(미리보기·시범)")
    # 기본 dry-run — 운영 데이터를 늘리는 작업이라 명시적 --apply 를 요구한다.
    ap.add_argument("--apply", action="store_true", help="실제로 INSERT(기본: 미리보기만)")
    args = ap.parse_args()

    extractor, resolve = _load_tools()
    with connect() as conn:
        done = {r[0] for r in conn.execute(_ALREADY).fetchall()}
        rows = conn.execute(_SELECT_RAW).fetchall()
    rows = [r for r in rows if r[1] not in done]
    if args.limit:
        rows = rows[: args.limit]

    print(f"대상 RAW 레시피 {len(rows)}개 (이미 백필된 {len(done)}개 제외)\n")

    total_ing = total_matched = applied = 0
    conn = connect() if args.apply else None
    try:
        for _rid_row, recipe_id, raw in rows:
            items = structure(raw, extractor, resolve)
            if not items:
                continue
            matched = sum(1 for x in items if x["item_id"])
            total_ing += len(items)
            total_matched += matched
            if args.apply:
                with conn.cursor() as cur:
                    for seq, x in enumerate(items, start=2):   # seq=1 은 RAW 원문 행
                        cur.execute(_INSERT, {
                            "recipe_id": recipe_id, "seq": seq, "name": x["name"],
                            "qty": x["quantity"], "raw": raw[:500],
                            "item_id": x["item_id"],
                        })
                applied += 1
            elif len(rows) <= 30:                              # 미리보기는 소량일 때만 상세 출력
                names = ", ".join(f"{x['name']}({x['quantity'] or '-'})" for x in items[:8])
                print(f"  recipe={recipe_id} 재료 {len(items)}개 매칭 {matched} · {names}")
        if args.apply:
            conn.commit()
    finally:
        if conn is not None:
            conn.close()

    rate = (total_matched / total_ing * 100) if total_ing else 0.0
    print(f"\n재료 {total_ing:,}개 추출 · item_id 매칭 {total_matched:,} ({rate:.1f}%)")
    if args.apply:
        print(f"→ 레시피 {applied}개 적재 완료 (ner_status='NER_PARSED')")
    else:
        print("→ 미리보기(무변경). 적용하려면 --apply")


if __name__ == "__main__":
    main()
