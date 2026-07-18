# [챗봇+프론트] 레시피 등록 기능 안내 + 딥링크 이동

> **작성:** 건우(AI) · **수신:** 프론트 담당(④~⑥) · **챗봇(①~③)=AI 직접**
> **배경:** 챗봇에 "레시피 직접 등록 안내"를 요청하면 "그런 기능 없다 → 유튜브"로 **잘못 안내**됨.
> 실제로는 `/recipebook`에 **「직접 작성」**(RecipeWriteForm)·**「YouTube 추가」** 모달이 **이미 존재**.
> 원인: 챗봇에 기능 안내/이동 핸들러 부재 → 유튜브 검색 폴백/생성문에 오분류.

## 목표
1. 챗봇이 레시피 등록 요청을 **정확히 안내**(잘못된 "없다" 제거).
2. 안내에 **딥링크 액션 버튼** → `/recipebook`의 해당 모달로 **원탭 이동**.

## 파트 경계
| # | 변경 | 파트 |
|---|------|------|
| ① | `ActionButton`에 `navigate` 액션 + `route` 필드 | AI |
| ② | `feature_nav.py` — 등록 키워드 → 라우트 안내(하드코딩 맵, LLM 미사용) | AI |
| ③ | `main.py` 기능 안내 early-return | AI |
| ④ | `ChatAction` 타입에 `navigate`/`route` | **프론트** |
| ⑤ | `ChatWidget.doAction` navigate 분기 | **프론트** |
| ⑥ | `Recipebook` 쿼리파라미터로 모달 자동 오픈 | **프론트** |

> ④만으로 `/recipebook` **페이지 이동**(직접작성 버튼 보임). ⑥까지면 **모달 자동 오픈**(원탭 완성).
> 네비 타깃은 정확한 라우트라 **하드코딩 맵**이 맞음(생성형 = 오라우팅 위험, 부적합).

---

## 챗봇 측 (AI, `services/chat/`)

### ① `app/models.py` — ActionButton
```diff
 class ActionButton(BaseModel):
     label: str
-    action: Literal["add_to_cart", "open_recipe", "open_youtube"]
+    action: Literal["add_to_cart", "open_recipe", "open_youtube", "navigate"]
     recipe_id: int | None = None
     item_id: int | None = None
     url: str | None = None   # open_youtube 전용
+    route: str | None = None # navigate 전용 — 인앱 라우트(예 /recipebook?compose=write)
     image_url: str | None = None
     meta: str | None = None
```

### ② `app/pipeline/feature_nav.py` (신규)
```python
"""기능 안내 — 앱 기능 요청("레시피 등록")을 인앱 라우트 딥링크로 안내.
그라운디드: 실재 라우트만(하드코딩 맵). 챗봇은 route만 반환, 이동은 프론트가 처리.
LLM 미사용 — 네비 타깃은 정확해야 해 생성형 부적합."""
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
    for f in _FEATURES:
        if any(k in text for k in f["keys"]):
            return f
    return None


def build_actions(feature: dict) -> list[ActionButton]:
    return [ActionButton(label=lbl, action="navigate", route=route)
            for lbl, route in feature["actions"]]
```

### ③ `app/main.py` — 소셜 응답 블록(현 244~246줄) 바로 뒤
```diff
         social = _social_reply(req.message)
         if social:
             request_span.set_attribute("chat.result", "social")
             return ChatResponse(reply=social)
+
+        # 기능 안내 — "레시피 등록" 등 앱 기능 요청 → 인앱 라우트 딥링크(검색 없이 즉답).
+        feature = feature_nav.match(req.message)
+        if feature:
+            request_span.set_attribute("chat.result", "feature_nav")
+            return ChatResponse(reply=feature["reply"],
+                                actions=feature_nav.build_actions(feature),
+                                session_id=req.session_id)
```
+ 상단 import: `from app.pipeline import feature_nav` (기존 import 스타일에 맞춤)

### 테스트(초안) `tests/test_pipeline.py`
```python
def test_feature_nav_recipe_register():
    from app.pipeline import feature_nav
    f = feature_nav.match("레시피 직접 등록하는 기능 안내해줘")
    assert f is not None
    acts = feature_nav.build_actions(f)
    assert acts[0].action == "navigate"
    assert acts[0].route == "/recipebook?compose=write"

def test_feature_nav_none_for_recommend():
    from app.pipeline import feature_nav
    assert feature_nav.match("두부로 뭐 해먹지") is None
```

---

## 프론트 측 (프론트 담당, `frontend/`) — 초안 diff

### ④ `src/lib/api.ts` — ChatAction
```diff
 export type ChatAction = {
   label: string
-  action: 'add_to_cart' | 'open_recipe' | 'open_youtube'
+  action: 'add_to_cart' | 'open_recipe' | 'open_youtube' | 'navigate'
   recipe_id?: number | null
   url?: string | null // open_youtube 전용
+  route?: string | null // navigate 전용 — 인앱 라우트(예 /recipebook?compose=write)
 }
```

### ⑤ `src/components/ChatWidget.tsx` — doAction
```diff
   const doAction = (a: ChatAction) => {
     if (a.action === 'open_recipe' && a.recipe_id != null) goTo(`/recipes/${a.recipe_id}`)
     else if (a.action === 'add_to_cart') goTo('/cart')
     else if (a.action === 'open_youtube' && a.url) window.open(a.url, '_blank', 'noopener,noreferrer')
+    else if (a.action === 'navigate' && a.route) goTo(a.route)
   }
```
> ※ 답변 액션 필터(`res.actions?.filter((a) => a.action !== 'open_recipe' || ...)`)는 navigate를 통과시킴(조건 무관). feature_nav 응답은 `unanswered=false`라 버튼 정상 노출 — 추가 변경 불필요.

### ⑥ `src/pages/Recipebook.tsx` — 쿼리파라미터로 모달 자동 오픈
```diff
-import { useState } from 'react'
-import { useNavigate } from 'react-router-dom'
+import { useState, useEffect } from 'react'
+import { useNavigate, useSearchParams } from 'react-router-dom'
 ...
 export default function Recipebook() {
   const nav = useNavigate()
+  const [params, setParams] = useSearchParams()
   const [modal, setModal] = useState<null | 'write' | 'youtube'>(null)
   ...
+  // 챗봇 딥링크(/recipebook?compose=write|youtube) → 해당 모달 자동 오픈 후 쿼리 정리
+  useEffect(() => {
+    const c = params.get('compose')
+    if (c === 'write' || c === 'youtube') {
+      setModal(c)
+      params.delete('compose')
+      setParams(params, { replace: true })
+    }
+    // eslint-disable-next-line react-hooks/exhaustive-deps
+  }, [])
```

## 완료 기준
- 챗봇: "레시피 직접 등록 안내해줘" → 정확 안내문 + 「직접 작성하러 가기」·「YouTube 링크로 추가」 버튼.
- ④⑤ 적용: 버튼 탭 → `/recipebook` 이동. ⑥ 추가: 해당 모달 자동 오픈.
- 회귀: 기존 추천/가격/영양/유튜브 폴백 무변경(navigate는 신규 분기).

## 리스크·비고
- 챗봇 변경은 **순수 추가**(네비 의도 구절에만 반응) → 기존 경로 무영향, 플래그 불필요.
- 라우트가 프론트 리팩터로 바뀌면 `feature_nav._FEATURES`만 갱신(단일 지점).

## 업데이트 — 전체 기능 안내 맵으로 확장 완료
`feature_nav._FEATURES`가 레시피 등록뿐 아니라 **앱 전 기능**을 커버(각 라우트는 실재):
레시피북 · 냉장고/재고(`/pantry`,`/pantry/add`) · 밀플랜(`/mealplan`) · 장바구니(`/cart`) ·
식비/지출(`/expense`,`/expense/add`) · 성과(`/performance`) · 핫딜(`/hotdeal`) ·
알림(`/notifications`) · 마이페이지(`/my`) · 레시피 둘러보기(`/recipes`).

**프론트 작업은 동일** — ④⑤(navigate 분기)면 모든 라우트 이동 동작. ⑥(쿼리 모달)은
`/recipebook?compose=` 전용(나머지는 `/pantry/add`·`/expense/add`처럼 실재 라우트라 불필요).
