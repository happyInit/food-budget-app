"""질문 문장에서 '내용어'만 추출 — search.py(①검색어 축소)·generator/template.py(③관련성 검증) 공용.

ES 검색은 관련성 임계값 없이 느슨하게 매칭하므로(known limitation), 조사·흔한
동사·잡담성 부사를 뺀 내용어만 검색어/근거검증에 써서 "만들 수 있는" 같은 잡음
문구가 실제 신호(재료명·요리명)를 덮어버리는 걸 막는다.
"""
from __future__ import annotations

# startswith 매칭이라 "만들"이 "만들어"/"만드는"/"만들고" 등 활용형을 함께 잡는다.
# 안녕/기분/요즘: 100문항 검증에서 레시피 제목("~안녕", "기분좋아지는~", "요즘 핫한~")과
#   우연히 겹쳐 오프토픽 질문이 새는 게 확인되어 추가.
# 방법/궁금/어떻게/알려/정보: 순수 질문 scaffolding — food term이 아닌데 레시피 제목의
#   "만드는 방법"/"비법이 궁금해?" 등에 걸려 오탐 유발(iter2 검증). 도메인명사가 아니라
#   질문 뼈대라 상시 제거해도 안전.
# "있": "있는/있어/있을/있고" 활용형을 1개 스템으로 포괄(iter3, 보르시 오탐 원인).
_QUESTION_STEMS = (
    "어때", "만들", "만드", "있", "싶", "알고", "직접", "뭐",
    "해먹", "추천", "레시피", "요리", "좀", "그냥", "진짜", "오늘",
    "안녕", "기분", "요즘",
    "방법", "궁금", "어떻게", "알려", "정보",
)
# 오프토픽 도메인 명사 — ⚠️ 잠정(iter3). 실제로 이 단어가 든 장식성 레시피 제목
# (날씨에/상황별/영화속요리)에 토큰 매칭돼 오프토픽 질문이 새는 걸 막는 차단목록.
# 근본적으론 whack-a-mole — 원칙적 대안(질문에 food term이 있어야 응답하는 positive
# 게이트)은 향후 iteration 과제. "영화 리틀포레스트 레시피"처럼 도메인명사가 든 정당한
# food 질문은 함께 거절되는 trade-off 감수.
_OFFTOPIC_NOUNS = (
    "날씨", "상황", "영화", "교통", "노래", "환율", "내일", "주식", "시장",
    "운동", "코딩", "시험", "사랑", "누구",
)
CONTENT_STOP_STEMS = _QUESTION_STEMS + _OFFTOPIC_NOUNS
_PARTICLES = (
    "으로", "에서", "부터", "까지", "이랑", "하고",
    "을", "를", "이", "가", "은", "는", "과", "와", "랑", "도", "만", "의", "에", "로",
)


def strip_particle(word: str) -> str:
    for p in sorted(_PARTICLES, key=len, reverse=True):
        if word.endswith(p) and len(word) > len(p):
            return word[: -len(p)]
    return word


def meaningful_words(text: str) -> list[str]:
    """불용어·조사를 뺀 내용어만 추출."""
    words = []
    for raw in text.split():
        w = strip_particle(raw)
        if len(w) >= 2 and not any(w.startswith(stem) for stem in CONTENT_STOP_STEMS):
            words.append(w)
    return words
