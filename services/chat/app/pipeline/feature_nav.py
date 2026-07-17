"""기능 안내 — 앱 기능 요청("레시피 등록")을 인앱 라우트 딥링크로 안내.

그라운디드: 실재 라우트만(하드코딩 맵). 챗봇은 route만 반환, 실제 이동은 프론트가 처리.
LLM 미사용 — 네비게이션 타깃은 정확해야 해 생성형 부적합(오라우팅 위험). 순수 추가라
기존 RAG 경로(추천·가격·영양)에 무영향 — 등록 키워드에만 반응한다.
"""
from __future__ import annotations

from app.models import ActionButton

# 실재 프론트 라우트 대응(frontend/src/App.tsx · Recipebook.tsx). 라우트 변경 시 여기만 갱신.
_FEATURES = [
    {
        "keys": ("레시피 등록", "레시피 작성", "레시피 직접", "직접 작성",
                 "레시피 올리", "레시피 추가", "레시피북에 추가", "내 레시피 등록"),
        "reply": ("레시피는 '레시피북'에서 직접 작성하거나 YouTube 링크로 등록할 수 있어요. "
                  "직접 작성 화면으로 안내해 드릴게요."),
        "actions": [
            ("레시피 직접 작성하러 가기", "/recipebook?compose=write"),
            ("YouTube 링크로 추가", "/recipebook?compose=youtube"),
        ],
    },
]


def match(text: str) -> dict | None:
    """등록/작성 등 기능 요청이면 해당 기능 dict, 아니면 None."""
    for feature in _FEATURES:
        if any(k in text for k in feature["keys"]):
            return feature
    return None


def build_actions(feature: dict) -> list[ActionButton]:
    """기능 dict → navigate 액션 버튼 목록(route = 인앱 라우트)."""
    return [ActionButton(label=lbl, action="navigate", route=route)
            for lbl, route in feature["actions"]]
