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


def load_gazetteer(cur):
    """item_alias(공백제거) → (item_id, canonical) 사전."""
    cur.execute("""select a.alias, a.item_id, m.canonical_name
                   from item_alias a join item_master m on m.item_id = a.item_id""")
    return {alias.replace(" ", ""): (iid, canon) for alias, iid, canon in cur.fetchall()}


def make_matcher(gaz):
    aliases = sorted(gaz.keys(), key=len, reverse=True)   # 최장 우선

    def match(name):
        """name → (item_id, canonical, method) 또는 (None, None, None)."""
        nc = (name or "").replace(" ", "")
        if not nc:
            return (None, None, None)
        if nc in gaz:
            return gaz[nc] + ("exact",)
        for a in aliases:                                  # 최장 접미
            if len(a) >= 2 and nc.endswith(a):
                return gaz[a] + ("suffix",)
        for tok in sorted(name.split(), key=len, reverse=True):  # 최장 토큰
            if tok in gaz:
                return gaz[tok] + ("token",)
        for a in aliases:                                  # 파생식품 최장 prefix
            if len(a) >= 2 and nc.startswith(a):
                return gaz[a] + ("prefix",)
        return (None, None, None)

    return match
