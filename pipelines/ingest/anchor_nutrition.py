"""food_nutrition ↔ item_master 앵커링 — 품목별 대표 food_cd 1개에 item_id 부여 (#5).

레시피/재고 재료(item_master로 매칭됨)에 영양을 붙이는 조인 키를 만든다.
품목당 대표행 1개만 item_id를 세팅(1:N 방지 → 서비스 조인 결정적).
선택: 이름완전일치 > 원재료(R) > 생것 > 대표/평균 > 짧은이름(generic).

기본 = DRY(픽·커버리지만 출력). 실제 반영은 --commit.
사용:  python pipelines/ingest/anchor_nutrition.py [--commit]
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

# 동의어: item_master canonical → 식약처 식품명에서 찾을 대체 검색어(들)
SYN = {
    "계란": ["달걀"], "통깨": ["참깨"], "식용유": ["콩기름", "대두유"],
    "참치": ["다랑어"], "새송이버섯": ["새송이"], "깻잎": ["들깨"],
    "청양고추": ["풋고추", "고추"], "홍고추": ["홍고추", "풋고추"], "쪽파": ["실파", "파"],
    "실파": ["실파", "파"], "닭가슴살": ["닭고기", "가슴살"], "꽈리고추": ["꽈리고추", "풋고추"],
    "맛술": ["미림", "미향", "청주"], "액젓": ["멸치액젓", "까나리액젓"],
}
BAD = {"싹", "순", "씨", "꽃", "눈"}   # 원재료 오매칭 유발 부위(청양고추→고추_싹 등)

# 수동 override: canonical → 강제할 식품명(부분일치, R 우선). 자동픽이 대표성 부족할 때.
OVERRIDE = {
    "밥": "멥쌀밥_백미", "설탕": "설탕_백설탕", "현미밥": "멥쌀밥_현미",
    "쌀": "멥쌀_백미", "닭가슴살": "닭고기_가슴", "통깨": "참깨_흰깨_볶은것",
    # ⚠️ 버터·치즈: 가공 50k 슬라이스에 콘버터/콘치즈뿐(값 부정확) → 전량 가공데이터 확보 시 교체 TODO
}


def norm(s):
    return (s or "").replace(" ", "")


def segs(name):  # 언더바+괄호 분해: 파프리카(착색단고추)_빨간색_생것 → 파프리카·착색단고추·빨간색·생것
    return [s for s in re.split(r"[_,\s()]+", name) if s]


def matches(canon, name, is_R):
    terms = [norm(canon)] + [norm(x) for x in SYN.get(canon, [])]
    for t in terms:
        if is_R:
            if t in segs(name):          # 원재료는 '정확 세그먼트'만(버터헤드≠버터)
                return True
        elif t in norm(name):            # 가공품은 부분일치(짧은이름 우선으로 완화)
            return True
    return False


def score(canon, name, is_R, kcal):
    s, n, ss = 0, norm(name), segs(name)
    if n == norm(canon):
        s += 150                         # 완전일치 = 가벼운 우선(생것에 안 밀리게)
    if is_R:
        s += 400                         # 원재료(국가표준) 우선
        if "생것" in ss:
            s += 500                     # 생것 강력 우선 → 건조/가루/브랜드 exact 이김
        elif "대표" in name or "평균" in name:
            s += 60                      # 생것 없으면 대표/평균
        s -= 12 * len(ss)                # 세그먼트 적은(generic) 선호
        s -= 80 * sum(1 for b in BAD if b in ss)   # 싹/순/씨/꽃 부위 페널티
    elif n.startswith(norm(canon)) or n.endswith(norm(canon)):
        s += 60                          # 가공품: 앞/뒤가 품목명이면 generic 가능성↑
    if kcal is None:
        s -= 500                         # 열량 없는 행 회피
    return s - len(name)                 # 짧을수록 generic


def main():
    commit = "--commit" in sys.argv
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select item_id, canonical_name, category from item_master")
        items = cur.fetchall()
        cur.execute("select food_cd, food_name, kcal from food_nutrition")
        foods = [(fc, fn, kc, fc[:1] == "R") for fc, fn, kc in cur.fetchall()]

        picks = {}       # item_id → (food_cd, food_name)
        for item_id, canon, _cat in items:
            ov = OVERRIDE.get(canon)
            if ov:       # 수동 지정: 해당 이름 포함행 중 R·짧은이름 우선
                cands = sorted(((fc, fn) for fc, fn, kc, isR in foods if norm(ov) in norm(fn)),
                               key=lambda x: (x[0][:1] != "R", len(x[1])))
                if cands:
                    picks[item_id] = cands[0]
                    continue
            best, best_s = None, None
            for fc, fn, kc, is_R in foods:
                if matches(canon, fn, is_R):
                    sc = score(canon, fn, is_R, kc)
                    if best_s is None or sc > best_s:
                        best, best_s = (fc, fn), sc
            if best:
                picks[item_id] = best

        hit = len(picks)
        print(f"앵커 매칭: {hit}/{len(items)} 품목 ({hit * 100 // len(items)}%)")

        # 레시피 빈도가중 커버리지(실제 서빙 관점)
        cur.execute("""select im.item_id, count(*) c from recipe_ingredient ri
            join item_master im on im.item_id = ri.item_id
            where ri.recipe_id in (select id from recipe where source='10K')
            group by im.item_id""")
        freq = cur.fetchall()
        tot = sum(c for _, c in freq)
        cov = sum(c for iid, c in freq if iid in picks)
        print(f"레시피 빈도가중 커버리지: {cov * 100 // tot}% ({cov:,}/{tot:,} occ)")

        # 상위 품목 픽 품질 확인
        cur.execute("""select im.canonical_name, im.item_id, count(*) c from recipe_ingredient ri
            join item_master im on im.item_id = ri.item_id
            where ri.recipe_id in (select id from recipe where source='10K')
            group by im.canonical_name, im.item_id order by c desc limit 22""")
        print("\n상위 재료 앵커 픽 (→ 서비스에 붙을 대표 영양):")
        for canon, iid, c in cur.fetchall():
            p = picks.get(iid)
            print(f"  {'✓' if p else '✗'} {canon:8}({c:>5,}) → {p[1] if p else '— 미매칭'}")

        if commit:
            cur.execute("update food_nutrition set item_id=NULL where item_id is not null")
            for item_id, (fc, _fn) in picks.items():
                cur.execute("update food_nutrition set item_id=%s where food_cd=%s", (item_id, fc))
            conn.commit()
            print(f"\n[COMMIT] {len(picks)}개 food_nutrition 행에 item_id 세팅")
        else:
            print("\n[DRY] 반영 안 함. 확정하려면 --commit")


if __name__ == "__main__":
    main()
