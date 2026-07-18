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
from app.models import (
    PantryItemIn, PantryItemOut, PantryItemPatch, PantryStats,
    ReceiptConfirmIn, ReceiptConfirmOut,
)

pantry = APIRouter(prefix="/api/pantry", tags=["pantry"])

# 식비 라우팅 키(§3.5) — OCR 분류 category 값. 비식품=total에서 차감, 조정=이미 반영(차감 X).
_NONFOOD, _ADJUST = "비식품", "조정"


def _won(x) -> int:
    """금액 → 원(정수). None=0. 식비 합산·비교용."""
    return int(round(x)) if x is not None else 0


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


@pantry.post("/receipts", status_code=status.HTTP_201_CREATED, response_model=ReceiptConfirmOut)  # OCR 확정
async def confirm_receipt(body: ReceiptConfirmIn,
                         uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    """OCR 결과 HITL 확정 → 저장·재고반영. 한 트랜잭션(전부 성공 or 롤백; get_conn이 커밋/롤백).

    1) ocr_receipt(헤더) + ocr_receipt_item(전줄, 감사 추적) 저장
    2) 식품 + storage 있음 + keep=true → pantry_item(source=OCR). item_id 검증→미매칭 시 이름 재해결,
       expire_at 미입력이면 shelf_life 추정(#12 add_item과 동일 규칙)
    3) 식비 = 냉장고에 담은(선택·keep) 식품의 가격 합만. (선택 안 한 줄·비식품·조정 제외 — 유저가 넣은 재료값만 차감)
    ★ 식비는 반환만 — 기록은 프론트가 mealplan /api/expenses 로(pantry→mealplan 순환의존 회피).
    """
    receipt_id = await queries.create_ocr_receipt(
        conn, uid, body.store, body.purchased_at, body.total_amount
    )
    added = 0
    kept_expense = 0            # 식비 = 냉장고에 담은(선택) 식품 가격 합
    kept_missing_price = False  # 담은 재료 중 가격 미인식 존재 → 검토 권장(과소차감 가능)
    for it in body.items:
        item_id = await queries.valid_item_id(conn, it.item_id)     # FK 안전(삽입 전 검증)
        # 전줄 저장(감사) — 확정 시점이므로 confirmed=true
        await queries.add_ocr_receipt_item(
            conn, receipt_id, it.raw_text, it.name, item_id,
            it.quantity, _won(it.price) if it.price is not None else None, it.is_food, True,
        )
        # 냉장고 반영: 식품(비식품·조정 제외) + storage 있음 + keep
        if it.keep and it.storage is not None and it.category not in (_NONFOOD, _ADJUST):
            if item_id is None:                                     # 앵커 없으면 이름으로 재해결(추천 반영용)
                item_id = await queries.resolve_item_id(conn, it.name)
            expire_at = it.expire_at
            if expire_at is None and item_id is not None:           # 미입력+앵커 → shelf_life 추정
                ref = await queries.lookup_shelf_life(conn, item_id, it.storage.value)
                if ref is not None:
                    expire_at = estimate_expire_date(date.today(), ref["days_min"], ref["days_max"])
            await queries.create_item(
                conn, uid, it.name, it.storage.value, it.quantity, item_id, expire_at, source="OCR"
            )
            added += 1
            p = _won(it.price)                     # 담은 재료 가격만 식비로 합산
            if p > 0:
                kept_expense += p
            else:
                kept_missing_price = True          # 가격 미인식 → 식비 과소 가능(검토)

    # 식비 = 냉장고에 담은(선택) 식품의 가격 합만. (총액 앵커 아님 — 유저가 넣은 재료값만 차감)
    #   선택 안 한 줄·비식품·조정은 제외. 담은 재료 중 가격 미인식이 있으면 검토 권장.
    expense = kept_expense
    basis = "selected_items"
    needs_review = kept_missing_price
    return ReceiptConfirmOut(
        receipt_id=receipt_id, added_count=added,
        expense_amount=max(expense, 0), expense_basis=basis, needs_expense_review=needs_review,
    )


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
    # 보관이동 시 소비기한 재계산(#3) — storage 만 바뀌고 expire_at 을 직접 지정하지 않은 경우.
    # 새 보관구역의 shelf_life 로 소비기한을 다시 계산(냉장→냉동이면 냉동 기준으로 길어짐).
    # 표준품목 앵커(item_id)/레퍼런스 없으면 냉동 이동은 무기한(null=동결), 그 외 구역은 기존값 유지.
    if "storage" in fields and "expire_at" not in fields:
        new_storage = fields["storage"]
        new_expire, recompute = None, False
        if row["item_id"] is not None:
            ref = await queries.lookup_shelf_life(conn, row["item_id"], new_storage)
            if ref is not None:
                new_expire = estimate_expire_date(date.today(), ref["days_min"], ref["days_max"])
                recompute = True
        if not recompute and new_storage == "FREEZER":
            new_expire, recompute = None, True             # 앵커/레퍼런스 없음 + 냉동 → 무기한 동결
        if recompute and new_expire != row["expire_at"]:
            row = await queries.update_item(conn, uid, item_id, {"expire_at": new_expire})
    return PantryItemOut(**row)


@pantry.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)  # #14
async def delete_item(item_id: int, uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    deleted = await queries.delete_item(conn, uid, item_id)
    if deleted is None:                                    # 다른 유저/없음 → 404 (A01)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    return None
