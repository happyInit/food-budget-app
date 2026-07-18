"""기능 안내 — 앱 기능 요청("레시피 등록", "냉장고 열어줘")을 인앱 라우트 딥링크로 안내.

그라운디드: 실재 라우트만(하드코딩 맵, frontend/src/App.tsx 대응). 챗봇은 route만 반환,
실제 이동은 프론트가 처리(ChatWidget navigate 분기). LLM 미사용 — 네비 타깃은 정확해야 해
생성형 부적합(오라우팅 위험). RAG(추천·가격·영양) **앞단**에서 검사하므로, 키워드는
일상 질문("냉장고 재료로 추천")을 가로채지 않게 **네비 의도가 분명한 구절**로 좁힌다.
라우트가 프론트 리팩터로 바뀌면 이 파일 _FEATURES만 갱신.
"""
from __future__ import annotations

from app.models import ActionButton

# 각 기능: keys(부분일치) → reply(안내문) + actions[(라벨, 인앱 라우트)].
# 순서 = 우선순위(첫 매칭 승). 키는 RAG 발화와 겹치지 않는 구체 구절로.
_FEATURES: list[dict] = [
    {   # 레시피북 — 직접 작성 / YouTube 추출
        # 동시출현(cooccur): '레시피/레시피북' + 등록성 동사 → 조사·어순 변형도 포섭
        #   ("레시피를 등록", "내가 만든 레시피 올릴게", "레시피 작성하고 싶어"…).
        "cooccur": [("레시피", "레시피북"),
                    ("등록", "작성", "올리", "올려", "올릴")],
        "keys": ("직접 작성", "레시피북", "레시피 추가", "레시피북에 추가", "내 레시피"),
        "reply": ("레시피는 '레시피북'에서 직접 작성하거나 YouTube 링크로 등록할 수 있어요. "
                  "직접 작성 화면으로 안내해 드릴게요."),
        "actions": [("레시피 직접 작성하러 가기", "/recipebook?compose=write"),
                    ("YouTube 링크로 추가", "/recipebook?compose=youtube")],
    },
    {   # 냉장고/재고 — 영수증 OCR · 재료 직접 등록
        "keys": ("냉장고 열", "냉장고 보여", "냉장고 확인", "내 재고", "재고 확인", "재고 등록",
                 "재고 관리", "재료 등록", "재료 추가", "유통기한", "소비기한",
                 "영수증 스캔", "영수증으로", "바코드"),
        "reply": ("냉장고에서 재료를 확인하고, 영수증 스캔이나 직접 입력으로 재고를 등록할 수 있어요."),
        "actions": [("내 냉장고 열기", "/pantry"), ("재료 직접 등록", "/pantry/add")],
    },
    {   # 밀플랜 — 예산·임박재료 기반 식단
        "keys": ("밀플랜", "식단표", "식단 짜", "식단 추천", "주간 식단", "일주일 식단", "식단 계획"),
        "reply": ("밀플랜에서 예산과 임박 재료를 반영한 식단 추천을 볼 수 있어요."),
        "actions": [("밀플랜 보기", "/mealplan")],
    },
    {   # 장바구니
        "keys": ("장바구니", "카트에", "담은 재료 보", "장바구니 열"),
        "reply": ("장바구니에서 담은 재료와 예상 금액을 확인할 수 있어요."),
        "actions": [("장바구니 열기", "/cart")],
    },
    {   # 식비/지출 — 캘린더 · 직접 기록
        "keys": ("식비 관리", "식비 확인", "식비 얼마", "지출 기록", "지출 확인", "지출 관리",
                 "가계부", "얼마 썼", "예산 관리"),
        "reply": ("식비관리에서 지출을 캘린더로 확인하고 직접 기록할 수 있어요."),
        "actions": [("식비 관리 열기", "/expense"), ("지출 기록하기", "/expense/add")],
    },
    {   # 성과/리포트
        "keys": ("성과", "절약 리포트", "얼마나 아꼈", "얼마나 아낀", "리포트 보", "성과 지표", "절약 성과"),
        "reply": ("성과지표에서 절약 성과와 예산 대비 지출을 확인할 수 있어요."),
        "actions": [("성과 지표 보기", "/performance")],
    },
    {   # 핫딜 — 마감특가(매일 17시~자정)
        "keys": ("핫딜", "특가", "마감특가", "떨이", "세일 상품", "할인 상품", "할인 특가"),
        "reply": ("핫딜에서 컬리·오아시스 마감특가 상품을 모아 볼 수 있어요(매일 17시~자정)."),
        "actions": [("마감특가 보기", "/hotdeal")],
    },
    {   # 알림센터
        "keys": ("알림센터", "알림 설정", "알림 확인", "알림 받", "임박 알림"),
        "reply": ("알림센터에서 소비기한 임박·특가 등 알림을 확인할 수 있어요."),
        "actions": [("알림센터 열기", "/notifications")],
    },
    {   # 마이페이지 — 프로필·제외재료·설정
        "keys": ("마이페이지", "마이 페이지", "내 정보", "프로필", "제외 재료 설정", "비선호 설정",
                 "환경설정", "계정 설정", "로그아웃"),
        "reply": ("마이페이지에서 프로필·예산·제외 재료 등 설정을 관리할 수 있어요."),
        "actions": [("마이페이지 열기", "/my")],
    },
    {   # 레시피 검색 페이지(둘러보기) — 특정 레시피 질의는 RAG가 처리하므로 키를 좁게
        "keys": ("레시피 둘러보", "레시피 검색 페이지", "레시피 목록 보", "레시피 검색 기능"),
        "reply": ("레시피 검색에서 조리시간·난이도로 레시피를 둘러볼 수 있어요."),
        "actions": [("레시피 둘러보기", "/recipes")],
    },
]


def _matches(text: str, feature: dict) -> bool:
    """cooccur(모든 그룹에서 하나씩 동시출현) 또는 keys(단독 부분일치) 중 하나면 매칭."""
    cooccur = feature.get("cooccur")
    if cooccur and all(any(k in text for k in group) for group in cooccur):
        return True
    return any(k in text for k in feature.get("keys", ()))


def match(text: str) -> dict | None:
    """기능 안내 요청이면 해당 기능 dict, 아니면 None."""
    for feature in _FEATURES:
        if _matches(text, feature):
            return feature
    return None


def build_actions(feature: dict) -> list[ActionButton]:
    """기능 dict → navigate 액션 버튼 목록(route = 인앱 라우트)."""
    return [ActionButton(label=lbl, action="navigate", route=route)
            for lbl, route in feature["actions"]]
