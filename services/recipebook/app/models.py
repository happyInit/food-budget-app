"""요청/응답 스키마. docs/design/api-spec.md #20~22 (레시피북=bookmark).

입력 검증(A05): recipe_id 는 양의 정수(bigint FK)로 제한 → Pydantic이 타입·범위 검증.
프론트 파생값(₩·D-day·% 등)은 저장/반환하지 않는다(CONVENTIONS §1).
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


# ── 요청 ──
class BookCreateReq(BaseModel):
    """#21 POST body. user_id는 바디로 받지 않는다 — JWT에서만 취득(A01)."""
    recipe_id: int = Field(ge=1)  # public.recipe.id (논리 FK 포인터)


# ── 응답 ──
class BookOut(BaseModel):
    """#20 목록 항목 — recipebook.bookmark JOIN public.recipe."""
    id: int                             # bookmark.id (삭제 키)
    recipe_id: int                      # public.recipe.id
    name: str                           # recipe.name
    image_url: str | None = None        # recipe.image_url (없을 수 있음)
    cooking_time: str | None = None     # recipe.cooking_time (텍스트, COOKRCP01 null)
    level_nm: str | None = None         # recipe.level_nm (EPIS 외 null)


class BookListOut(BaseModel):
    """#20 응답 봉투 {books:[...]}."""
    books: list[BookOut]


# ── user_recipe (#24 수동 등록 + 공유) — recipebook.user_recipe 소유 ──
# A05: 입력 길이·개수 상한을 Pydantic으로 강제. 프론트 파생값은 저장 안 함(CONVENTIONS §1).
_StepStr = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class IngredientItem(BaseModel):
    """재료 1건 — 표준품목(item_id) 매칭 없는 자유 텍스트(수동 작성이라 NER 대상 아님)."""
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    quantity: Annotated[str, StringConstraints(max_length=50)] | None = None


class UserRecipeCreate(BaseModel):
    """직접 작성 레시피 등록. user_id는 바디로 받지 않는다 — JWT에서만(A01). origin은 서버가 MANUAL 고정."""
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    ingredients: list[IngredientItem] = Field(default_factory=list, max_length=100)
    steps: list[_StepStr] = Field(default_factory=list, max_length=100)
    image_url: Annotated[str, StringConstraints(max_length=1000)] | None = None
    source_url: Annotated[str, StringConstraints(max_length=1000)] | None = None


class UserRecipeListItem(BaseModel):
    """내 레시피 목록 항목(최신순)."""
    id: int
    title: str
    image_url: str | None = None
    is_public: bool
    created_at: datetime


class UserRecipeListOut(BaseModel):
    recipes: list[UserRecipeListItem]


class UserRecipeOut(BaseModel):
    """내 레시피 상세(소유자만). ingredients·steps는 jsonb → 파싱된 리스트."""
    id: int
    title: str
    origin: str
    ingredients: list[IngredientItem] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    image_url: str | None = None
    source_url: str | None = None
    is_public: bool
    share_token: str | None = None
    created_at: datetime


class ShareOut(BaseModel):
    """공유 설정 결과 — 프론트가 share_token으로 공개 링크(/shared/<token>) 구성."""
    share_token: str
    is_public: bool


class SharedRecipeOut(BaseModel):
    """공개 공유 뷰(비인증). 작성자 식별정보(user_id 등)는 노출하지 않는다."""
    title: str
    ingredients: list[IngredientItem] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    image_url: str | None = None


# ── shared_recipe (공개 카탈로그 발행) ──
class PublishOut(BaseModel):
    """발행 결과 — 프론트가 share_token으로 공개 뷰(/shared/<token>) 링크 구성."""
    share_token: str
    is_public: bool = True


class SharedRecipeCard(BaseModel):
    """공개 발행 레시피 카드(비인증 목록). 작성자 식별정보는 노출하지 않는다."""
    id: int
    title: str
    image_url: str | None = None
    origin: str
    share_token: str                    # 클릭 시 /shared/<token> 공개 뷰로 이동
    published_at: datetime


class SharedRecipeListOut(BaseModel):
    recipes: list[SharedRecipeCard]
