"""item_master 큐레이션 배치 (룰: 철자·수식어 변형만 alias 병합, 종 다르면 유지).

상위 빈도 재료 head-noun을 canonical(+category)로 승격하고, 표면형 변형은 item_alias로 흡수.
노이즈(물·파싱부산물)는 제외. 기존 CURATED 38개는 보존(ON CONFLICT DO NOTHING).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect  # noqa: E402

CATS = {
 "채소": ["양파","당근","대파","오이","무","애호박","미나리","시금치","부추","깻잎","콩나물","파프리카",
          "청양고추","홍고추","청고추","풋고추","고추","피망","가지","단호박","브로콜리","양배추","양상추",
          "배추","숙주","아스파라거스","연근","비트","청경채","쑥갓","우엉","참나물","무순","어린잎","셀러리",
          "완두콩","마늘","생강"],
 "과일": ["사과","배","바나나","토마토","방울토마토","레몬","오렌지","파인애플","아보카도","대추","감귤","참외","딸기","포도"],
 "육류": ["소고기","돼지고기","닭고기","닭가슴살","베이컨"],
 "수산물": ["새우","오징어","멸치","주꾸미","바지락","연어","전복","건새우","다시마","김"],
 "난류": ["계란"],
 "유제품": ["우유","버터","생크림","치즈","요거트","파마산치즈"],
 "가공식품": ["두부","어묵","김치","빵가루","두유"],
 "양념": ["소금","설탕","후추","식초","간장","고춧가루","올리고당","꿀","고추장","된장","마요네즈","맛술",
          "물엿","매실청","유자청","카레가루","청주","통후추","흰후추","생강즙","생강청","국간장","발사믹식초",
          "굴소스","케첩","머스터드","화이트와인","깨소금","함초소금","매실","전분","참기름","들기름","통깨","흑임자"],
 "유지": ["식용유","올리브유"],
 "곡류": ["밀가루","쌀","찹쌀","현미","밥","찹쌀가루"],
 "버섯": ["표고버섯","새송이버섯","느타리버섯","양송이버섯","팽이버섯"],
 "견과": ["호두","잣","땅콩","아몬드"],
 "허브": ["로즈마리","바질","월계수잎","파슬리"],
}
ALIAS = {  # 표면형(수식어·철자·동의어) → canonical
 "달걀":"계란","달걀흰자":"계란",
 "저염간장":"간장","맛간장":"간장","국간장":"간장",
 "올리브오일":"올리브유","튀김기름":"식용유",
 "다진마늘":"마늘","마늘다진것":"마늘",
 "다진양파":"양파","양파다진것":"양파",
 "다진대파":"대파","파":"대파",
 "쇠고기":"소고기","브로컬리":"브로콜리","양송이":"양송이버섯",
 "후춧가루":"후추","참깨":"통깨","녹말가루":"전분","정종":"청주",
 "파슬리가루":"파슬리","청피망":"피망","홍피망":"피망","강력분":"밀가루",
 "매실액":"매실청","샐러리":"셀러리",
}


def main():
    cat_of = {name: cat for cat, names in CATS.items() for name in names}
    canon = set(cat_of)
    # 모든 canonical은 자기 자신 alias, 변형은 canonical로 매핑(단 canonical이 실재해야)
    aliases = {c: c for c in canon}
    for surf, c in ALIAS.items():
        assert c in canon, f"alias target not in canon: {c}"
        aliases[surf] = c
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            "insert into item_master(canonical_name, category) values (%s,%s) "
            "on conflict (canonical_name) do nothing",
            [(c, cat_of[c]) for c in canon])
        # canonical → item_id
        cur.execute("select canonical_name, item_id from item_master")
        idof = dict(cur.fetchall())
        cur.executemany(
            "insert into item_alias(alias, item_id, source) values (%s,%s,'RECIPE_CURATED') "
            "on conflict (alias) do nothing",
            [(surf, idof[c]) for surf, c in aliases.items()])
        conn.commit()
    print(f"큐레이션: canonical {len(canon)}개, alias {len(aliases)}개 반영")


if __name__ == "__main__":
    main()
