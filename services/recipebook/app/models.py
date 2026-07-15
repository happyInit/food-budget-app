"""요청/응답 스키마. docs/design/api-spec.md #20~22 (레시피북=bookmark).

입력 검증(A05): recipe_id 는 양의 정수(bigint FK)로 제한 → Pydantic이 타입·범위 검증.
프론트 파생값(₩·D-day·% 등)은 저장/반환하지 않는다(CONVENTIONS §1).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


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
