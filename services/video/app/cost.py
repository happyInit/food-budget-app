"""영상 레시피 재료비 산출 (#11 · 프론트 파이프라인 4단계 "상품 매핑 · 가격 산출").

추출된 재료(name·quantity·item_id)에 현재 소매가를 곱해 **"이 영상 따라하면 얼마"**를 낸다.
`item_id` 정규화(3단계)가 여기서 값을 갖는다 — 정규화 없이는 가격을 붙일 수 없다.

**공식은 챗의 정본과 동일해야 한다**(`services/chat/app/pipeline/recipe_cost.py`):
  · 용량(g) ÷ 100 × `won_per_100g`, **1팩 상한**(min(usage, pack)) — 200g 쓰려고 500g 한 팩을
    사도 지출은 한 팩 값이므로 그 이상으로 잡지 않는다.
  · **육수/물 제외**(`is_liquid_excl`) · **상비 양념 제외**(_STAPLES) — 둘 다 팀 결정.
공식이 갈리면 "챗이 말한 재료비와 영상 화면의 재료비가 다른" 불일치가 생긴다.

**모르면 지어내지 않는다**(`servings_known` 과 같은 원칙):
"적당량"·무게참조 없는 낱개·가격 미수집 품목은 합산에서 빠지고 `unpriced` 로 드러난다.
그래서 총액은 항상 **과소추정**이며, 응답에 `priced_count/total_count` 를 함께 준다.
"""
from __future__ import annotations

import psycopg

from app.config import settings
from app.vendor.quantity import is_liquid_excl, to_grams   # 정본 컨버터 — 챗·상세와 단일 소스

# 상비 재료(양념·조미료) — 집에 보통 있는 것. 재료비 합산에서 제외(팀 결정).
# ⚠️ chat `generator/template.py::_STAPLES` 와 동일 목록이어야 한다.
_STAPLES = frozenset({
    "소금", "후추", "후춧가루", "흰후추", "통후추", "설탕", "백설탕", "황설탕", "흑설탕",
    "간장", "국간장", "진간장", "양조간장", "조선간장", "고추장", "된장", "쌈장", "춘장",
    "고춧가루", "식용유", "카놀라유", "올리브유", "포도씨유", "콩기름", "참기름", "들기름",
    "마늘", "다진마늘", "생강", "다진생강", "식초", "사과식초", "발사믹식초", "맛술", "미림", "미린", "청주",
    "올리고당", "물엿", "조청", "꿀", "깨", "통깨", "참깨", "깨소금", "케첩", "마요네즈",
    "굴소스", "액젓", "멸치액젓", "까나리액젓", "새우젓", "다시다", "미원", "치킨스톡", "물",
    "김치",   # 대부분 집에 상비(팀 결정) — 가격 매기기 애매
})

_DENSITY_QUERY = ("select item_id, density_g_per_ml from item_master "
                  "where item_id = any(%(ids)s) and density_g_per_ml is not null")
_WEIGHT_QUERY = "select item_id, unit, grams from item_unit_weight where item_id = any(%(ids)s)"
# 소스 무관 최저 단가 — "가장 싸게 사면 얼마"가 이 기능의 질문이다.
# `retail_unit_price.name` 은 **상품명**이라 품목 표준명은 item_master 에서 가져온다
# (유저에게 "삼겹살"로 매칭됐다고 보여줘야지 "1++ 한돈 삼겹살 500g"을 보여줄 일이 아니다).
_UNIT_QUERY = """
select r.item_id, min(r.won_per_100g), min(r.price), min(im.canonical_name)
  from retail_unit_price r
  join item_master im on im.item_id = r.item_id
 where r.item_id = any(%(ids)s) and r.won_per_100g is not null
 group by r.item_id
"""


def _is_staple(name: str | None) -> bool:
    return (name or "").replace(" ", "") in _STAPLES


def _conninfo() -> str:
    return (f"host={settings.pghost} port={settings.pgport} dbname={settings.pgdatabase} "
            f"user={settings.pguser} password={settings.pgpassword}")


def estimate(ingredients: list[dict], servings: int | None = None) -> dict:
    """재료 목록 → 재료비 내역. DB 실패·재료 없음이면 빈 결과(추출 자체는 계속 유효).

    ingredients: [{"name": str, "quantity": str|None, "item_id": int|None}, ...]
    반환: {"total_krw", "per_serving_krw", "priced_count", "total_count", "lines"[, "unpriced"]}
    """
    # 1차 필터는 **정규화 실패분(item_id 없음)** 과 원문만으로 명백한 상비/물만 거른다.
    # 상비 판정의 본판은 아래 표준명(canonical) 기준 — 그래야 챗과 같은 금액이 나온다.
    resolved = [g for g in ingredients if g.get("item_id")]
    excluded = sum(1 for g in ingredients
                   if not g.get("item_id")
                   and (_is_staple(g.get("name")) or is_liquid_excl(g.get("name"))))
    if not resolved:
        return {"total_krw": None, "per_serving_krw": None, "priced_count": 0,
                "total_count": len(ingredients), "excluded_count": excluded, "lines": []}

    ids = list({g["item_id"] for g in resolved})
    with psycopg.connect(_conninfo(), connect_timeout=8) as conn, conn.cursor() as cur:
        cur.execute(_DENSITY_QUERY, {"ids": ids})
        density = {i: float(d) for i, d in cur.fetchall()}
        cur.execute(_WEIGHT_QUERY, {"ids": ids})
        uw = {(i, u): float(g) for i, u, g in cur.fetchall()}
        cur.execute(_UNIT_QUERY, {"ids": ids})
        unit = {i: (float(w), float(p) if p is not None else None, nm)
                for i, w, p, nm in cur.fetchall()}

    refs = {"density": density, "uw": uw}
    lines, total = [], 0
    for g in resolved:
        iid = g["item_id"]
        # ⚠️ 상비·물 판정은 **표준명**으로 한다(챗 batch_costs 의 names_map 과 동일).
        #    원문("신 김치"·"간 마늘")으로 보면 상비 목록에 걸리지 않아 김치찌개의 김치가
        #    8,700원으로 잡힌다 — 실측 2026-07-29 에서 총액의 84%를 오염시켰다.
        canon_name = unit[iid][2] if iid in unit else g.get("name")
        if _is_staple(canon_name) or is_liquid_excl(canon_name):
            excluded += 1
            continue
        grams, conf = to_grams(g.get("quantity"), iid, refs)
        if iid not in unit:
            lines.append({"name": g.get("name"), "item_id": iid, "krw": None,
                          "reason": "가격 미수집"})
            continue
        w100, pack, canon = unit[iid]
        if not grams:
            # 용량을 못 읽으면 **추정하지 않는다** — 틀린 용량은 총액을 그대로 왜곡한다.
            lines.append({"name": g.get("name"), "item_id": iid, "krw": None,
                          "matched_name": canon,
                          "reason": {"vague": "분량 표현이 모호", "no_ref": "낱개 무게 미등록"}
                                    .get(conf, "분량 해석 불가")})
            continue
        usage = grams / 100 * w100
        krw = round(min(usage, pack) if pack is not None else usage)   # 1팩 상한
        total += krw
        lines.append({"name": g.get("name"), "item_id": iid, "krw": krw,
                      "matched_name": canon, "grams": round(grams, 1), "basis": conf})

    # 정규화 실패분도 "산출 못 한 재료"로 드러낸다 — 조용히 사라지면 총액이 왜 낮은지 알 수 없다.
    for g in ingredients:
        if not g.get("item_id") and not (_is_staple(g.get("name")) or is_liquid_excl(g.get("name"))):
            lines.append({"name": g.get("name"), "item_id": None, "krw": None,
                          "reason": "품목 매칭 실패"})

    priced = sum(1 for ln in lines if ln["krw"] is not None)
    # 인분이 불확실하면 1인분 단가를 내지 않는다 — servings_known=False 인 영상이 실측상 다수다.
    per_serving = round(total / servings) if (servings and servings > 0 and total) else None
    return {
        "total_krw": total if priced else None,
        "per_serving_krw": per_serving,
        "priced_count": priced,
        "total_count": len(ingredients),
        "excluded_count": excluded,          # 상비·물/육수 — 뺀 이유를 UI가 설명할 수 있게
        "lines": lines,
    }
