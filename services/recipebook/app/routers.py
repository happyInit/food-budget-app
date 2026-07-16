"""라우터 — api-spec #20~22 (레시피북). 핸들러는 Depends로 의존성 주입(전역 state 없음 → 테스트 가능).
쿼리 결과는 dict(row_factory=dict_row) → 컬럼명이 모델과 같으면 `BookOut(**row)`.

- user_id는 반드시 JWT에서(Depends(get_current_user)) — 바디/쿼리의 user_id 신뢰 금지(A01).
- 소유권: 목록/삭제 쿼리에 WHERE user_id 포함, 남의 행 접근 시 404(A01).
- psycopg 예외 → HTTPException 매핑(UniqueViolation→409, ForeignKeyViolation→404).
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Response, status
from psycopg.errors import ForeignKeyViolation, UniqueViolation

from app import queries
from app.context import get_conn, get_current_user
from app.models import (
    BookCreateReq, BookListOut, BookOut, ShareOut, SharedRecipeOut,
    UserRecipeCreate, UserRecipeListItem, UserRecipeListOut, UserRecipeOut,
)

book = APIRouter(prefix="/api/recipes/book", tags=["recipebook"])


@book.get("", response_model=BookListOut)  # #20
async def list_books(uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    rows = await queries.list_bookmarks(conn, uid)
    return BookListOut(books=[BookOut(**row) for row in rows])  # 컬럼명 = 모델 필드


@book.post("", status_code=status.HTTP_201_CREATED)  # #21
async def add_book(body: BookCreateReq,
                   uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    try:
        bid = await queries.create_bookmark(conn, uid, body.recipe_id)  # user_id=JWT, not body
    except UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "recipe already bookmarked")
    except ForeignKeyViolation:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
    return {"id": bid}


@book.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)  # #22
async def remove_book(bookmark_id: int,
                      uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    row = await queries.delete_bookmark(conn, uid, bookmark_id)
    if row is None:                       # 내 소유가 아니거나 존재하지 않음(소유권)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "bookmark not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── user_recipe (#24 수동 등록 + 공유) ────────────────────────────────────────
# 전부 인증 필요(get_current_user) · 소유권 스코프. 공개 뷰(shared)만 비인증.
mine = APIRouter(prefix="/api/recipes/mine", tags=["user_recipe"])
shared = APIRouter(prefix="/api/recipes/shared", tags=["user_recipe"])


@mine.get("", response_model=UserRecipeListOut)
async def list_mine(uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    rows = await queries.list_user_recipes(conn, uid)
    return UserRecipeListOut(recipes=[UserRecipeListItem(**row) for row in rows])


@mine.post("", status_code=status.HTTP_201_CREATED)
async def create_mine(body: UserRecipeCreate,
                      uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    rid = await queries.create_user_recipe(
        conn, uid, body.title,
        [i.model_dump() for i in body.ingredients],   # Pydantic → jsonb 직렬화용 dict
        list(body.steps), body.image_url, body.source_url,
    )
    return {"id": rid}


@mine.get("/{recipe_id}", response_model=UserRecipeOut)
async def get_mine(recipe_id: int,
                   uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    row = await queries.get_user_recipe(conn, uid, recipe_id)
    if row is None:                       # 남의 것/없음 → 존재 노출 없이 404 (A01)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
    return UserRecipeOut(**row)


@mine.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mine(recipe_id: int,
                      uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    row = await queries.delete_user_recipe(conn, uid, recipe_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@mine.post("/{recipe_id}/share", response_model=ShareOut)
async def share_mine(recipe_id: int,
                     uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    # 예측 불가한 공유 토큰(secrets) — 링크를 아는 사람만 열람. 소유자만 공유 설정 가능.
    row = await queries.set_share(conn, uid, recipe_id, secrets.token_urlsafe(12))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
    return ShareOut(**row)


@mine.delete("/{recipe_id}/share", status_code=status.HTTP_204_NO_CONTENT)
async def unshare_mine(recipe_id: int,
                       uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    row = await queries.unshare_user_recipe(conn, uid, recipe_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@shared.get("/{share_token}", response_model=SharedRecipeOut)
async def get_shared(share_token: str, conn=Depends(get_conn)):
    """공개 공유 뷰 — 인증 불요. is_public=true 인 레시피만(비공개/없음 → 404)."""
    row = await queries.get_shared_recipe(conn, share_token)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "shared recipe not found")
    return SharedRecipeOut(**row)
