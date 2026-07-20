"""분량 텍스트 → 그램 변환 (레시피 영양합산·장보기 공용).

parse_qty: "1/2컵"→(0.5,'컵') · "2~3개"→(2.5,'개') · "반개"→(0.5,'개') · "약간"→(None,None).
to_grams: 무게 / 부피·계량(밀도) / 낱개(item_unit_weight) / 모호 → (grams, confidence).
참조: item_master.density_g_per_ml + item_unit_weight (migrate_quantity + seed/mine 로 적재).

데모/측정:  python pipelines/ingest/quantity.py
"""
import re
import sys
from pathlib import Path

MEASURE_ML = {"큰술": 15, "작은술": 5, "큰수저": 15, "작은수저": 5, "스푼": 15,
              "컵": 200, "종이컵": 180, "밥술": 10, "밥숟갈": 10, "숟가락": 10,
              "T": 15, "t": 5}   # 만개레시피 약어: T=큰술 15ml, t=작은술 5ml (대소문자 의미 구분 — IGNORECASE 금지)
WEIGHT_G = {"kg": 1000, "g": 1}
VOLUME_ML = {"ml": 1, "cc": 1, "l": 1000, "리터": 1000}
PIECE = ["개", "대", "모", "알", "쪽", "장", "줌", "톨", "송이", "봉", "줄",
         "마리", "캔", "팩", "판", "공기", "포기", "뿌리", "족", "꼬집", "줄기"]
KNUM = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6}
VAGUE = re.compile(r"약간|적당|조금|톡톡|취향|기호|살짝|넉넉|고명")

_U = "|".join(map(re.escape, sorted(
    list(MEASURE_ML) + list(WEIGHT_G) + list(VOLUME_ML) + PIECE, key=len, reverse=True)))
_FRAC = re.compile(rf"(\d+)\s*/\s*(\d+)\s*({_U})")
_RANGE = re.compile(rf"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*({_U})")
_HALF = re.compile(rf"반\s*({_U})")
_KNUM = re.compile(rf"(다섯|여섯|[한두세네])\s*({_U})")
_NUM = re.compile(rf"(\d+(?:\.\d+)?)\s*({_U})")


def parse_qty(text):
    """분량 텍스트 → (수량, 단위). 못 읽으면 (None, None)."""
    if not text:
        return None, None
    t = str(text).strip()
    if (m := _FRAC.search(t)):
        return int(m[1]) / int(m[2]), m[3]
    if (m := _RANGE.search(t)):
        return (float(m[1]) + float(m[2])) / 2, m[3]
    if (m := _HALF.search(t)):
        return 0.5, m[1]
    if (m := _KNUM.search(t)):
        return KNUM.get(m[1], 1), m[2]
    if (m := _NUM.search(t)):
        return float(m[1]), m[2]
    if (m := re.search(_U, t)):                       # 단위만 → 암묵 1 (모호어 있으면 수량 미상)
        return (None, m.group(0)) if VAGUE.search(t) else (1.0, m.group(0))
    return None, None


def to_grams(text, item_id, refs):
    """(grams, confidence). 변환 불가면 (None, 사유)."""
    num, unit = parse_qty(text)
    if unit and num is not None:
        if unit in WEIGHT_G:
            return num * WEIGHT_G[unit], "weight"
        density = refs["density"].get(item_id) or 1.0
        if unit in VOLUME_ML:
            return round(num * VOLUME_ML[unit] * density, 1), "volume"
        if unit in MEASURE_ML:
            return round(num * MEASURE_ML[unit] * density, 1), "measure"
        g = refs["uw"].get((item_id, unit))
        if g is not None:
            return round(num * g, 1), "piece"
        return None, "no_ref"                         # 단위는 알지만 무게참조 없음(미curation 낱개)
    if text and VAGUE.search(str(text)):
        return None, "vague"
    return None, "unknown"


def load_refs(cur):
    cur.execute("select item_id, density_g_per_ml from item_master where density_g_per_ml is not null")
    density = {i: float(d) for i, d in cur.fetchall()}
    cur.execute("select item_id, unit, grams from item_unit_weight")
    uw = {(i, u): float(g) for i, u, g in cur.fetchall()}
    return {"density": density, "uw": uw}


# 육수/물 = 집에서 끓이거나 사실상 무료 → 레시피 재료비에서 제외 (챗·상세 공용, 팀 결정 2026-07-20)
_LIQUID_EXCL = re.compile(r"육수|스톡|다시|사골|채수|맛국물|국물")
_WATER = {"물", "생수", "정수", "찬물", "얼음물", "끓인물", "미지근한물", "따뜻한물"}


def is_liquid_excl(name):
    """육수/물류 = 재료비 제외 대상."""
    n = (name or "").replace(" ", "")
    return bool(_LIQUID_EXCL.search(n)) or n in _WATER


def _demo():
    sys.path.insert(0, str(Path(__file__).parent))
    from _db import connect
    import collections
    with connect() as conn, conn.cursor() as cur:
        refs = load_refs(cur)
        # 전체 변환율
        cur.execute("select quantity, item_id from recipe_ingredient where quantity is not null and item_id is not null")
        conf = collections.Counter()
        for q, iid in cur.fetchall():
            _, c = to_grams(q, iid, refs)
            conf[c] += 1
        tot = sum(conf.values())
        ok = sum(v for k, v in conf.items() if k in ("weight", "volume", "measure", "piece"))
        print(f"분량→그램 변환율: {ok*100//tot}% ({ok:,}/{tot:,})")
        print("  confidence별:", dict(conf.most_common()))
        # 레시피 영양합산 데모
        cur.execute("""select ri.ingredient_name, ri.quantity, ri.item_id, fn.kcal, fn.sodium_mg
            from recipe_ingredient ri left join food_nutrition fn on fn.item_id=ri.item_id
            where ri.recipe_id=10159 order by ri.seq""")
        tk = tn = 0
        print("\n레시피 「돼지목살스테이크샐러드」 영양합산 (분량→그램→영양):")
        for nm, q, iid, kcal, na in cur.fetchall():
            g, c = to_grams(q, iid, refs) if iid else (None, "no_item")
            if g and kcal is not None:
                k = float(kcal) * g / 100
                tk += k
                tn += float(na or 0) * g / 100
                print(f"  {(nm or '')[:10]:11} {(q or ''):7} → {g:>6.0f}g  {k:>5.0f}kcal  [{c}]")
        print(f"  ─────────  합계 약 {tk:.0f}kcal · 나트륨 {tn:.0f}mg")


if __name__ == "__main__":
    _demo()
