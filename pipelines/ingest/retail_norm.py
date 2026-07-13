"""소매 상품명 정규화 — 컬리/오아시스 상품명 → 기반명 → gazetteer 매칭.

소매 상품명은 마케팅/등급/원산지/용도 노이즈가 큼(레시피 재료와 다름):
  [KF365] 백다다기오이 3입 · [농할20%]감자 | 유기농 (800g) · 국내산 1+등급 채끝 스테이크
전략: 브래킷·스펙·묶음(N종/택1)·용도(구이용)·등급/원산지 스트립 + 노이즈토큰 제거 →
      한국어 머리명사(끝)를 gazetteer 접미/prefix 매치. 정규화명은 retail_product.name_norm에 보존.
"""
import re

UNIT = (r"kg|g|ml|mL|L|입|단|과|미|수|봉지|봉|포|매|장|병|캔|구|알|송이|모|마리|줄|편|쪽|통|"
        r"박스|세트|팩|인분|인|용|호|자루|판|줄기|ea|EA")
SPEC   = re.compile(rf"\d[\d.]*\s*(?:{UNIT})\b", re.I)
BUNDLE = re.compile(r"\d+\s*종|택\s*\d+|택일|골라\s*담기|모둠|모음|혼합|반반팩|샘플러|세트|선물|믹스|모듬")
USAGE  = re.compile(r"(?:구이|국거리|찌개|수육|장조림|육전|볶음|조림|탕|회|무침|쌈|샤브|불고기|편육|다짐)\s*용")
MOD = ["동물복지", "자유방목", "무항생제", "무농약", "유기농", "친환경", "저탄소", "국내산", "국내", "국산",
       "호주산", "미국산", "캐나다산", "뉴질랜드산", "한우", "한돈", "1++", "1+등급", "1+", "2+", "특등급", "등급",
       "프리미엄", "산지직송", "당일", "냉장", "냉동", "손질", "세척", "자연산", "활", "생물", "급냉", "순살", "뼈없는",
       "햇", "깐", "흙", "미니", "왕", "한입", "한끼", "알뜰", "실속형", "실속", "특大", "특", "대", "중", "소",
       "곰곰", "KF365", "바로", "데워먹는", "포슬포슬", "싱그러운", "고소", "아삭한", "든든하게", "한통", "보들",
       "촉촉", "프레시", "신선"]
REGION = ["영암", "서산", "당진", "밀양", "천안", "아우내", "예산", "경기", "안동", "제주", "해남", "고흥", "성주",
          "나주", "횡성", "완도", "기장", "통영", "봉화", "의성", "청양", "괴산", "영광", "법성포", "포항", "무안",
          "진도", "고성", "강원", "충주", "이천", "여주", "김포", "논산", "부여"]
NOISE_TOK = {"고기", "절단", "진공", "채", "순", "팩", "선물", "혼합", "묶음", "꾸러미", "한정", "증정", "사은품",
             "골라", "담기", "냉장", "냉동", "선물세트", "실속", "정성", "담은", "한정판", "기획"}


def normalize(name):
    s = re.sub(r"\[[^\]]*\]", " ", name or "")   # [브랜드/프로모]
    s = re.sub(r"\([^)]*\)", " ", s)             # (스펙/설명)
    s = s.split("|")[0]                           # | 이후 옵션 버림
    s = re.sub(r"[*/~,]", " ", s)                # 구분기호
    s = SPEC.sub(" ", s); s = BUNDLE.sub(" ", s); s = USAGE.sub(" ", s)
    for m in MOD + REGION:                         # 등급·원산지·재배 수식어
        s = s.replace(m, " ")
    toks = [t for t in s.split() if t not in NOISE_TOK]   # 노이즈 토큰(고기 등, 돼지고기는 보존)
    return " ".join(toks)


def make_retail_matcher(gaz_match):
    """gazetteer 매처를 감싸 상품명 정규화+후보시도. 반환 (item_id, canonical, method, name_norm)."""
    def match(name):
        nm = normalize(name)
        if not nm:
            return (None, None, None, nm)
        toks = nm.split()
        cands = [nm]
        if toks:
            cands.append(toks[-1])                # 머리명사(끝)
        if len(toks) > 1:
            cands.append(" ".join(toks[-2:]))
        for cand in cands:
            iid, canon, meth = gaz_match(cand)
            if iid is not None:
                return (iid, canon, meth, nm)
        return (None, None, None, nm)
    return match
