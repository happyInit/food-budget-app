"""라우터 — api-spec #11~15 (냉장고 재고 CRUD + 소비기한 임박).
핸들러는 Depends로 의존성 주입(전역 state 없음 → 테스트 가능). 쿼리 결과는 dict(row_factory=dict_row)
→ `PantryItemOut(**row)`.

★ A01: 모든 재고 접근은 get_current_user(JWT) 의 user_id 로 소유자 스코프. 요청 바디의 user_id 안 믿음.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app import queries
from app.context import get_conn, get_current_user
from app.estimate import estimate_expire_date
from app.models import PantryItemIn, PantryItemOut, PantryItemPatch

pantry = APIRouter(prefix="/api/pantry", tags=["pantry"])


@pantry.get("/items", response_model=list[PantryItemOut])  # #11
async def list_items(uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    rows = await queries.list_items(conn, uid)
    return [PantryItemOut(**r) for r in rows]


@pantry.get("/expiring", response_model=list[PantryItemOut])  # #15
async def list_expiring(
    within_days: int = Query(3, ge=0, le=30),      # 기본 3일·상한 30(A05 범위 검증)
    uid: int = Depends(get_current_user),
    conn=Depends(get_conn),
):
    rows = await queries.list_expiring(conn, uid, within_days)
    return [PantryItemOut(**r) for r in rows]


@pantry.post("/items", status_code=status.HTTP_201_CREATED, response_model=PantryItemOut)  # #12
async def add_item(body: PantryItemIn, uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    expire_at = body.expire_at
    # expire_at 미입력 + 표준품목(item_id) 있으면 shelf_life_ref 로 추정(없으면 null 유지 = 유저입력 대기).
    if expire_at is None and body.item_id is not None:
        ref = await queries.lookup_shelf_life(conn, body.item_id, body.storage.value)
        if ref is not None:
            expire_at = estimate_expire_date(date.today(), ref["days_min"], ref["days_max"])
    row = await queries.create_item(
        conn, uid, body.name, body.storage.value, body.quantity, body.item_id, expire_at
    )
    return PantryItemOut(**row)


@pantry.patch("/items/{item_id}", response_model=PantryItemOut)  # #13
async def patch_item(item_id: int, body: PantryItemPatch,
                     uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    fields = body.model_dump(exclude_unset=True)          # 제공된 필드만
    if not fields:
        raise HTTPException(422, "no fields to update")   # 수정할 필드 없음(Unprocessable)
    for k in ("storage", "status"):                       # enum → 문자열 값(psycopg 바인딩 안전)
        if fields.get(k) is not None:
            fields[k] = fields[k].value
    row = await queries.update_item(conn, uid, item_id, fields)
    if row is None:                                        # 다른 유저/없음 → 존재 노출 없이 404 (A01)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    return PantryItemOut(**row)


@pantry.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)  # #14
async def delete_item(item_id: int, uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    deleted = await queries.delete_item(conn, uid, item_id)
    if deleted is None:                                    # 다른 유저/없음 → 404 (A01)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    return None
