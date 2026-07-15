"""라우터 — api-spec #20~22 (레시피북). 핸들러는 Depends로 의존성 주입(전역 state 없음 → 테스트 가능).
쿼리 결과는 dict(row_factory=dict_row) → 컬럼명이 모델과 같으면 `BookOut(**row)`.

- user_id는 반드시 JWT에서(Depends(get_current_user)) — 바디/쿼리의 user_id 신뢰 금지(A01).
- 소유권: 목록/삭제 쿼리에 WHERE user_id 포함, 남의 행 접근 시 404(A01).
- psycopg 예외 → HTTPException 매핑(UniqueViolation→409, ForeignKeyViolation→404).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from psycopg.errors import ForeignKeyViolation, UniqueViolation

from app import queries
from app.context import get_conn, get_current_user
from app.models import BookCreateReq, BookListOut, BookOut

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
