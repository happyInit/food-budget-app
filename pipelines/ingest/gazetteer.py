"""품목 gazetteer 매칭 — 재료명/상품명 → item_master.item_id.
전략: 공백제거 exact → 최장 접미(suffix) → 최장 토큰 → 최장 prefix(파생식품).
소스 무관(레시피 재료·소매 상품 공통). item_master/item_alias 정본(curate_item_master.py) 기반.

- 접미 우선: 한국어 '수식어+머리명사' 순 → 국물용 멸치→멸치, 백다다기오이→오이.
- 최장 우선: 파프리카가 파보다 먼저(오매치 방지). len>=2 제한으로 단자 오매치 회피.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402  (외부 호출자 편의)

# 비재료/파싱노이즈 — 매칭 대상 아님(커버리지 분모서 제외)
STOP = {"물", "각", "얼음", "약간", "적당량", "기타", "고명", "위생장갑", "꼬치", "이쑤시개", "면포", "키친타월",
        "식용꽃", "식용 꽃", "저나트륨", "쌀뜨물", "장식", "곁들이", "곁들임", "미니",
        "구매", "생수", "기름", "오일", "술", "면수", "다시물", "찬물", "따뜻한 물", "뜨거운 물", "미지근한 물"}

# ── 종세분화 가드 (정책2 동물, #54 채택) ──────────────────────────────────────
# 종 수식어를 벗겨 육류 head로 뭉개는 것 방지. meat_canons가 주어질 때만 발동(없으면 현행 동작).
SPECIES_QUALIFIERS = [  # (수식어, 종) 긴 것 먼저. bare '양' 없음(양념/양파 오인 방지). LA=소.
    ("돼지고기", "돼지"), ("소고기", "소"), ("닭고기", "닭"), ("오리고기", "오리"), ("양고기", "양"),
    ("엘에이", "소"), ("한우", "소"),
    ("돼지", "돼지"), ("오리", "오리"), ("소", "소"), ("닭", "닭"), ("LA", "소"), ("la", "소"),
]
CANON_SPECIES = {"소고기": "소", "돼지고기": "돼지", "닭고기": "닭", "오리고기": "오리", "양고기": "양"}
SPECIES_EXCLUDE = ("양념", "양파", "양배추", "양상추", "소금", "소스", "소면")  # 종글자로 시작하나 종 아님


def _leading_species(prefix):
    """벗겨진 앞부분(prefix)이 종 수식어면 종, 아니면 None. EXCLUDE(양념·소금…) 먼저."""
    for ex in SPECIES_EXCLUDE:
        if ex in prefix:                # 양념·소스 등은 prefix 어디에 있어도 제외(LA 양념 갈비 등)
            return None
    for q, sp in SPECIES_QUALIFIERS:
        if prefix.startswith(q):
            return sp
    return None


def load_meat_canons(cur):
    """category='육류' canonical 집합 — 종세분화 가드 대상 head. make_matcher(gaz, meat_canons)로 주입."""
    cur.execute("select canonical_name from item_master where category = '육류'")
    return frozenset(r[0] for r in cur.fetchall())


def load_gazetteer(cur):
    """item_alias(공백제거) → (item_id, canonical) 사전."""
    cur.execute("""select a.alias, a.item_id, m.canonical_name
                   from item_alias a join item_master m on m.item_id = a.item_id""")
    return {alias.replace(" ", ""): (iid, canon) for alias, iid, canon in cur.fetchall()}


def make_matcher(gaz, meat_canons=frozenset()):
    aliases = sorted(gaz.keys(), key=len, reverse=True)   # 최장 우선
    species_item = {sp: gaz[c] for c, sp in CANON_SPECIES.items() if c in gaz}  # 종→종고기 item(remap)

    def match(name):
        """name → (item_id, canonical, method) 또는 (None, None, None)."""
        nc = (name or "").replace(" ", "")
        if not nc:
            return (None, None, None)
        if nc in gaz:
            return gaz[nc] + ("exact",)
        for a in aliases:                                  # 최장 접미
            if len(a) >= 2 and nc.endswith(a):
                canon_a = gaz[a][1]
                if meat_canons and canon_a in meat_canons:      # 종세분화 가드(정책2, #54)
                    qsp = _leading_species(nc[: -len(a)])
                    if qsp is not None:
                        csp = CANON_SPECIES.get(canon_a)
                        if csp is None or csp != qsp:            # generic 부위 or 종 충돌
                            if qsp in species_item:
                                return species_item[qsp] + ("guard-remap",)
                            return (None, None, "guard-block")
                return gaz[a] + ("suffix",)
        for tok in sorted(name.split(), key=len, reverse=True):  # 최장 토큰
            if tok in gaz:
                return gaz[tok] + ("token",)
        for a in aliases:                                  # 파생식품 최장 prefix
            if len(a) >= 2 and nc.startswith(a):
                return gaz[a] + ("prefix",)
        return (None, None, None)

    return match
