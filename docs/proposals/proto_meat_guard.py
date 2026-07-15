"""재현 스크립트 (READ-ONLY) — 육류 종/부위 수식어 가드 실측.

gazetteer-meat-granularity.md §5.5 의 수치를 재현한다. DB 변경 없음(SELECT만).
실행: `.venv/bin/python docs/proposals/proto_meat_guard.py`  (PG 접속은 .env 사용)

가드 규칙: suffix 매칭이 '종 수식어 + 육류 alias' 이고 그 alias canonical의 종이
수식어 종과 다르거나(충돌) 없으면(generic 부위) 붕괴 차단.
  · remap = 종 item으로 재매핑(커버리지 유지)  · block = None(정직한 미매칭)
  · bare 단자 '양' 제외(양념/양파 오인 방지) + EXCLUDE 어  · LA/la/엘에이 → 소(beef)
  · exact alias(돼지갈비→10 등 기존 큐레이션)는 존중, 육류 canonical 에만 발동.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines" / "ingest"))
from _db import connect  # noqa: E402
from gazetteer import load_gazetteer, make_matcher, STOP  # noqa: E402

EXCLUDE = ("양념", "양파", "양배추", "양상추", "소금", "소스", "소면")
QUAL_SPECIES = [  # 긴 것 먼저. bare '양' 없음. LA 추가.
    ("돼지고기", "돼지"), ("소고기", "소"), ("닭고기", "닭"), ("오리고기", "오리"), ("양고기", "양"),
    ("엘에이", "소"), ("한우", "소"),
    ("돼지", "돼지"), ("오리", "오리"), ("소", "소"), ("닭", "닭"), ("LA", "소"), ("la", "소"),
]
CANON_SPECIES = {"소고기": "소", "돼지고기": "돼지", "닭고기": "닭", "오리고기": "오리", "양고기": "양"}


def leading_qual(prefix):
    for ex in EXCLUDE:
        if prefix.startswith(ex):
            return None
    for q, sp in QUAL_SPECIES:
        if prefix.startswith(q):
            return sp
    return None


def make_guarded(gaz, meat_canons, species_item, mode):
    aliases = sorted(gaz.keys(), key=len, reverse=True)

    def match(name):
        nc = (name or "").replace(" ", "")
        if not nc:
            return (None, None, None)
        if nc in gaz:
            return gaz[nc] + ("exact",)
        for a in aliases:
            if len(a) >= 2 and nc.endswith(a):
                canon_a = gaz[a][1]
                if canon_a in meat_canons:
                    prefix = nc[: -len(a)]
                    qsp = leading_qual(prefix)
                    if qsp is not None:
                        csp = CANON_SPECIES.get(canon_a)
                        if csp is None or csp != qsp:
                            if mode == "remap" and qsp in species_item:
                                return species_item[qsp] + ("guard-remap",)
                            return (None, None, "guard-block")
                return gaz[a] + ("suffix",)
        for tok in sorted(name.split(), key=len, reverse=True):
            if tok in gaz:
                return gaz[tok] + ("token",)
        for a in aliases:
            if len(a) >= 2 and nc.startswith(a):
                return gaz[a] + ("prefix",)
        return (None, None, None)

    return match


def iid(match, name):
    if name in STOP or name.replace(" ", "") in STOP:
        return None
    return match(name)[0]


def servable(recipes, match):
    return {rid for rid, ings in recipes.items()
            if ings and all(iid(match, n) is not None for n in ings)}


def main():
    with connect() as conn, conn.cursor() as cur:
        gaz = load_gazetteer(cur)
        cur.execute("select item_id, canonical_name from item_master where category='육류'")
        meat = cur.fetchall()
        meat_canons = {c for _, c in meat}
        canon_to_id = {c: i for i, c in meat}
        id_canon = {i: c for c, i in canon_to_id.items()}
        species_item = {sp: (canon_to_id[c], c) for c, sp in CANON_SPECIES.items() if c in canon_to_id}

        cur.execute("""select r.src_recipe_id, ri.ingredient_name
                       from recipe r join recipe_ingredient ri on ri.recipe_id=r.id
                       where r.source='10K'""")
        recipes = {}
        for rid, nm in cur.fetchall():
            recipes.setdefault(rid, []).append(nm)

    cur_m = make_matcher(gaz)
    remap = make_guarded(gaz, meat_canons, species_item, "remap")
    block = make_guarded(gaz, meat_canons, species_item, "block")
    cn = lambda i: id_canon.get(i, "?") if i is not None else "—"

    print("=== 오발·LA 검증: 현행 → remap ===")
    for t in ["양념갈비", "양념불고기", "양념돼지갈비", "양파", "양배추", "양고기 등심",
              "LA갈비", "la갈비", "엘에이갈비", "소갈비", "닭갈비", "돼지갈비", "훈제오리고기"]:
        c, r = cur_m(t), remap(t)
        print(f"  {t:10} | 현행 {str(c[0]):>5}({c[1]}) → remap {str(r[0]):>5}({r[1] or '—'})")

    names = {n for ings in recipes.values() for n in ings if n}
    changed = [(n, iid(cur_m, n), iid(remap, n)) for n in names if iid(remap, n) != iid(cur_m, n)]
    misfire = [(n, a, b) for n, a, b in changed
               if b is not None and cn(b) == "양고기" and "양념" in n]
    print(f"\n=== 실코퍼스 변경 {len(changed)}종 · 양념→양고기 오발 {len(misfire)}종 ===")
    for n, a, b in sorted(changed):
        print(f"  {n:22} {cn(a)}({a}) → {cn(b)}({b})")

    base, sr, sb = servable(recipes, cur_m), servable(recipes, remap), servable(recipes, block)
    print(f"\n=== 게이트 servable: 현행 {len(base)} · remap {len(sr)} (Δ{len(sr)-len(base)}) "
          f"· block {len(sb)} (Δ{len(sb)-len(base)}) ===")

    print("\n=== 잔여 판단(팀) — 순수 부위어의 종 vs 부위 트레이드오프 ===")
    for t in ["소갈비", "LA갈비", "소고기갈비살"]:
        c, r = cur_m(t), remap(t)
        print(f"  {t}: 현행 {cn(c[0])}({c[0]},부위보존) ↔ remap {cn(r[0])}({r[0]},종보존)")


if __name__ == "__main__":
    main()
