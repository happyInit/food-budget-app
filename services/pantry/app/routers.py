"""라우터 — api-spec #11~15 (냉장고 재고 CRUD + 소비기한 임박).
핸들러는 Depends로 의존성 주입(전역 state 없음 → 테스트 가능). 쿼리 결과는 dict(row_factory=dict_row)
→ `PantryItemOut(**row)`.

★ A01: 모든 재고 접근은 get_current_user(JWT) 의 user_id 로 소유자 스코프. 요청 바디의 user_id 안 믿음.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg.errors import ForeignKeyViolation

from app import queries
from app.context import get_conn, get_current_user
from app.estimate import estimate_expire_date
from app.models import PantryItemIn, PantryItemOut, PantryItemPatch, PantryStats

pantry = APIRouter(prefix="/api/pantry", tags=["pantry"])


def _parse_month(month: str | None) -> date | None:
    """'YYYY-MM' → 해당 월 1일 date(파라미터 바인딩용). None 은 그대로(전체 기간).
    Query(pattern) 이 형식을 거른 뒤 여기서 실월(13월·00월)까지 검증 → 422 (A05)."""
    if month is None:
        return None
    try:
        return datetime.strptime(month + "-01", "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(422, "invalid month (YYYY-MM)")  # 실월 위반(13월 등)


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


@pantry.get("/stats", response_model=PantryStats)  # 성과지표(안 버린 재료·폐기) — mealplan seam 소비
async def stats(
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),  # 형식검증(A05); 미지정=전체 기간
    uid: int = Depends(get_current_user),
    conn=Depends(get_conn),
):
    row = await queries.pantry_stats(conn, uid, _parse_month(month))
    consumed, discarded = int(row["consumed"]), int(row["discarded"])
    closed = consumed + discarded
    return PantryStats(
        active=int(row["active"]), consumed=consumed, discarded=discarded,
        saved_rate=(round(consumed / closed, 4) if closed else None),  # 종료 0건이면 null
    )


@pantry.post("/items", status_code=status.HTTP_201_CREATED, response_model=PantryItemOut)  # #12
async def add_item(body: PantryItemIn, uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    # 표준품목 앵커(item_id) 미지정 → 이름으로 자동 매칭. '뭐 해먹지' 추천이 item_id 매칭 기반이라,
    # 앵커가 있어야 추가 즉시 추천에 반영됨. 매칭 실패면 None(표시엔 지장 없음).
    item_id = body.item_id
    if item_id is None:
        item_id = await queries.resolve_item_id(conn, body.name)
    expire_at = body.expire_at
    # expire_at 미입력 + 표준품목(item_id) 있으면 shelf_life_ref 로 추정(없으면 null 유지 = 유저입력 대기).
    if expire_at is None and item_id is not None:
        ref = await queries.lookup_shelf_life(conn, item_id, body.storage.value)
        if ref is not None:
            expire_at = estimate_expire_date(date.today(), ref["days_min"], ref["days_max"])
    try:
        row = await queries.create_item(
            conn, uid, body.name, body.storage.value, body.quantity, item_id, expire_at
        )
    except ForeignKeyViolation:                    # 없는 item_id(item_master FK) → 404 (recipebook 매핑 역이식)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown item_id")
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
