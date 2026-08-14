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
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402
from quantity import MEASURE_ML, PIECE, VOLUME_ML, WEIGHT_G  # noqa: E402  정본 단위 어휘

_REPO = Path(__file__).resolve().parents[2]

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

# CRF 가 색상 **수식어**를 별도 스팬으로 뽑는 경우가 있다 — 재료가 아니다.
# 실측(2026-07-30): 원문 `파프리카(빨간색, 노란색)` 에서 파프리카 뒤에 `빨간색`·`노란색` 이
# 각각 독립 재료 행으로 들어갔다. `item_id` 가 안 붙어 재료비 비용은 0이지만,
# **레시피 상세 API 가 `ingredient_name` 을 필터 없이 반환하므로 유저 화면에 재료로 보인다**
# (`services/recipe/app/queries.py:147` — item_id·ner_status 조건이 없다).
#
# 🔴 **완전일치만 거른다.** `색` 포함으로 거르면 실제 재료가 대량으로 날아간다 — 실측:
#    자색양파(6) · 갈색설탕(5) · 자색고구마(4) · 대파 녹색부분(2) · 적색 파프리카(2) ·
#    노란색 파프리카(2) · 삼색파프리카(1) 는 **전부 매칭에 성공한 정상 재료**다.
#    비매칭인 것은 `노란색`(4) · `빨간색`(3) 처럼 **색상어 단독**뿐이다.
#
# 색상 목록을 명시하는 이유: `^[가-힣]{1,3}색$` 로 두면 앞으로 뜻이 다른 낱말(예: 원색·염색)이
# 재료명에 등장할 때 조용히 걸린다. 무엇을 거르는지 코드가 스스로 말하게 한다.
#
# ⚠️ **버리기만 하고 앞 재료에 붙이지는 않는다.** `파프리카` 에 색을 되붙이는 편이 데이터로는
#    낫지만, 스팬 순서·괄호 구조를 추정해야 해서 잘못 붙으면 **멀쩡한 재료명을 오염시킨다.**
#    버리는 쪽은 최악이어도 정보가 줄 뿐이다(그 색은 원문 `ingredient_raw` 에 그대로 남는다).
_COLOR_WORDS = ("빨간", "노란", "파란", "초록", "검은", "하얀", "보라", "주황", "분홍",
                "갈", "자", "적", "청", "황", "녹", "백", "흑", "회", "남")
_COLOR_ONLY = re.compile(r"^(?:" + "|".join(_COLOR_WORDS) + r")색$")


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
            # 색상어 단독 스팬은 재료가 아니다 — 버린다(위 _COLOR_ONLY 주석 참조).
            # ⚠️ cursor 는 진행시키지 않는다. 이 스팬은 원문에서 소비되지 않은 셈이라
            #    다음 재료의 수량 탐색 구간이 좁아지면 안 된다.
            if _COLOR_ONLY.match(name.strip()):
                continue
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


def _model_path() -> Path:
    """서빙 아티팩트를 먼저 찾는다.

    🔴 `.crfsuite` 는 **CRFsuite 네이티브 포맷**이라 `python-crfsuite`(5MB) 만으로 열린다.
    `.pkl` 은 `sklearn_crfsuite.CRF` **객체**라 scikit-learn·scipy·numpy 195MB 를 끌고 온다 —
    추론에는 한 줄도 안 쓰이는데도 그렇다(`predict()` 가 `tagger_.tag()` 로 그대로 넘긴다).
    실측(2026-08-14): gold 50건 F1 **0.9238 동일** · 번들 **224MB→19MB** · import **18,986→243ms**.
    """
    env = os.environ.get("NER_MODEL_PATH")
    if env:
        return Path(env)
    for base in (Path(__file__).parent,                       # Lambda 번들 — 평평하다
                 _REPO / "ml" / "ingredient-ner" / "data" / "model"):
        for name in ("crf_ingredient.crfsuite", "crf_ingredient.pkl"):
            if (base / name).exists():
                return base / name
    return _REPO / "ml" / "ingredient-ner" / "data" / "model" / "crf_ingredient.crfsuite"


def _load_tools():
    """CRF 추출기 + gazetteer 매처. 챗·영상과 **같은 gazetteer** 를 쓴다(매칭 규칙 불일치 방지)."""
    # 🔴 번들에는 `services/chat/` 트리가 없다. build.sh 가 `ner.py` 를 **평평하게** 넣으므로
    #    그쪽을 먼저 시도하고, 레포에서 돌 때만 원래 경로로 떨어진다(G-05).
    try:
        from ner import CrfSpanExtractor  # noqa: PLC0415  — Lambda 번들
    except ImportError:
        sys.path.insert(0, str(_REPO / "services" / "chat"))
        from app.pipeline.span_extractor.ner import CrfSpanExtractor  # noqa: PLC0415

    from gazetteer import load_gazetteer, load_meat_canons, make_matcher  # noqa: PLC0415

    extractor = CrfSpanExtractor(str(_model_path()))
    with connect() as conn, conn.cursor() as cur:
        match = make_matcher(load_gazetteer(cur), load_meat_canons(cur))

    def resolve(name: str) -> int | None:
        item_id, _canon, _method = match(name or "")
        return item_id

    return extractor, resolve


def run(*, limit=None, apply=False, has_time=None, emit=print) -> dict:
    """백필 본체. **CLI 와 Lambda 가 같이 쓴다.**

    has_time — 레시피 사이마다 "시간이 남았나"를 묻는다. None 이면 안 본다(CLI).
    emit     — 한 줄 출력. CLI 는 print, Lambda 는 로거.

    🟢 이 배치는 **자연히 이어받는다** — `_ALREADY` 가 이미 백필된 레시피를 제외하므로,
    자진 중단 후 다시 부르면 **남은 것부터** 다시 고른다.
    """
    extractor, resolve = _load_tools()
    with connect() as conn:
        done_ids = {r[0] for r in conn.execute(_ALREADY).fetchall()}
        rows = conn.execute(_SELECT_RAW).fetchall()
    rows = [r for r in rows if r[1] not in done_ids]
    if limit:
        rows = rows[:limit]

    emit(f"대상 RAW 레시피 {len(rows)}개 (이미 백필된 {len(done_ids)}개 제외)")

    total_ing = total_matched = applied = seen = 0
    stopped_early = False
    conn = connect() if apply else None
    try:
        for _rid_row, recipe_id, raw in rows:
            # 시간 가드는 **레시피 사이**에 둔다 — 한 레시피의 재료를 반만 넣고 끊기지 않는다.
            if has_time is not None and not has_time():
                stopped_early = True
                emit(f"⏱ 시간 상한 임박 — {seen}/{len(rows)} 에서 자진 중단(남은 것은 다음 실행에서)")
                break
            seen += 1
            items = structure(raw, extractor, resolve)
            if not items:
                continue
            matched = sum(1 for x in items if x["item_id"])
            total_ing += len(items)
            total_matched += matched
            if apply:
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
                emit(f"  recipe={recipe_id} 재료 {len(items)}개 매칭 {matched} · {names}")
        if apply:
            conn.commit()   # 자진 중단이어도 여기까지는 커밋한다.
    finally:
        if conn is not None:
            conn.close()

    rate = (total_matched / total_ing * 100) if total_ing else 0.0
    emit(f"재료 {total_ing:,}개 추출 · item_id 매칭 {total_matched:,} ({rate:.1f}%)")
    if apply:
        emit(f"→ 레시피 {applied}개 적재 완료 (ner_status='NER_PARSED')")
    else:
        emit("→ 미리보기(무변경). 적용하려면 --apply / apply=true")
    return {"ingredients": total_ing, "matched": total_matched, "match_rate": round(rate, 1),
            "applied_recipes": applied, "processed": seen, "targets": len(rows),
            "remaining": len(rows) - seen, "applied": apply, "stopped_early": stopped_early}


def main() -> None:
    ap = argparse.ArgumentParser(description="RAW 재료 덩어리 CRF 구조화 백필")
    ap.add_argument("--limit", type=int, help="상위 N개 레시피만(미리보기·시범)")
    # 기본 dry-run — 운영 데이터를 늘리는 작업이라 명시적 --apply 를 요구한다.
    ap.add_argument("--apply", action="store_true", help="실제로 INSERT(기본: 미리보기만)")
    args = ap.parse_args()
    run(limit=args.limit, apply=args.apply)


if __name__ == "__main__":
    main()
