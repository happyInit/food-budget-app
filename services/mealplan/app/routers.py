"""라우터 — api-spec #32~40. 핸들러는 Depends로 의존성 주입(전역 state 없음 → 테스트 가능).
쿼리 결과는 dict(row_factory=dict_row) → `row["name"]`. numeric(Decimal)은 명시적으로 int().

라우터 3개(account가 auth·users 2개 include 하듯 여러 개 include):
  cart(/api/mealplan/cart) · expense(/api/expenses) · recommend(/api/mealplan).
self-contained(#34·35·36·38·39·cart조회·월합계)는 완전 실구현.
seam 붙은 부분(#33 예산 · #40 예산·안버린재료 · #32 재고)만 주입 어댑터(없으면 null/degrade).
"""
from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg.errors import ForeignKeyViolation

from app import events, queries, ranking_client
from app.context import (
    AppCtx, BudgetProvider, ConnOpener, ExclusionProvider, PantryProvider, ProviderUnavailable,
    get_budget_provider, get_conn, get_conn_opener, get_ctx, get_current_user,
    get_exclusion_provider, get_pantry_provider,
)
from app.models import (
    CalendarDay, CalendarOut, CartItemCreate, CartItemCreated, CartItemOut,
    CartOut, CategoryAmount, CheckoutOrder, CheckoutOut, ExpenseBreakdown,
    ExpenseCreate, ExpenseCreated, ExpenseSummary, MonthQuery, Recommendation,
    RecommendOut, RecommendReq,
)
from app.ranking import group_recipe_rows, rank_recipes

# 지출 카테고리 정본(4종) — breakdown 이 지출 없는 카테고리도 0 으로 채워 항상 4행 반환.
_CATEGORIES = ("GROCERY", "DINING", "DELIVERY", "ETC")

cart = APIRouter(prefix="/api/mealplan/cart", tags=["cart"])
expense = APIRouter(prefix="/api/expenses", tags=["expense"])
recommend = APIRouter(prefix="/api/mealplan", tags=["recommend"])


def _cart_subtotal(rows: list[dict]) -> int:
    """장바구니 합계 — 품목별 더 싼 100g 단가 × 수량(단가 미상 품목은 제외).
    #33 subtotal 과 #36 checkout amount 가 같은 정의를 공유(정본은 여기 하나)."""
    return sum(int(r["lowest_krw_per_100g"]) * r["qty"]
               for r in rows if r["lowest_krw_per_100g"] is not None)


async def _try_budget(budget: BudgetProvider, uid: int) -> int | None:
    """budget seam — 미가용(미배선·네트워크)이면 None 으로 degrade."""
    try:
        return await budget.get_budget(uid)
    except ProviderUnavailable:
        return None


async def _try_saved(pantry: PantryProvider, uid: int) -> int | None:
    """pantry 성과지표 seam — 미가용이면 None 으로 degrade."""
    try:
        return await pantry.saved_ingredients(uid)
    except ProviderUnavailable:
        return None


# ── Cart ─────────────────────────────────────────────────────────────────
@cart.get("", response_model=CartOut)  # #33
async def get_cart(uid: int = Depends(get_current_user),
                   open_conn: ConnOpener = Depends(get_conn_opener),
                   budget: BudgetProvider = Depends(get_budget_provider)):
    # budget HTTP 는 conn 없이 동시 진행 → conn 은 DB 조회 구간에만 좁게 쥐고 즉시 반납한다
    # (병렬성 유지 + 다운스트림 대기 중 풀 미점유 → cascade 방지).
    budget_task = asyncio.create_task(_try_budget(budget, uid))
    try:
        async with open_conn() as conn:
            rows = await queries.get_cart(conn, uid)
    finally:
        budget_amt = await budget_task           # DB 성공·실패 무관 항상 완료까지(태스크 누수 방지;
        #                                          _try_budget 은 예외를 삼켜 여기서 안전)
    items = [
        CartItemOut(
            id=r["id"], name=r["name"], qty=r["qty"], quantity=r["quantity"],
            item_id=r["item_id"],
            lowest_krw_per_100g=(None if r["lowest_krw_per_100g"] is None
                                 else int(r["lowest_krw_per_100g"])),
            source=r["source"],
        )
        for r in rows
    ]
    subtotal = _cart_subtotal(rows)
    remaining = None if budget_amt is None else budget_amt - subtotal
    return CartOut(items=items, subtotal=subtotal, budget=budget_amt, remaining=remaining)


@cart.post("/items", status_code=status.HTTP_201_CREATED, response_model=CartItemCreated)  # #34
async def add_cart_item(body: CartItemCreate, uid: int = Depends(get_current_user),
                        conn=Depends(get_conn), ctx: AppCtx = Depends(get_ctx)):
    try:
        new_id = await queries.insert_cart_item(
            conn, uid, body.name, body.recipe_id, body.item_id,
            body.retail_product_id, body.qty, body.quantity,
        )
    except ForeignKeyViolation:  # 없는 recipe/item/product 참조 → 500 대신 400 (psycopg→HTTPException 매핑)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid recipe/item/product reference")
    # 클릭스트림 ADD_CART 적재(P1 랭킹 주 라벨). flag OFF/발행 실패면 무동작(담기 무손상).
    # conn 을 넘기는 이유 = EVENT_SINK=pg 일 때 **같은 트랜잭션에 savepoint 로** 쓴다(C-88).
    # 새 커넥션을 열지 않으므로 풀 사용량이 늘지 않는다.
    await events.emit_add_cart(ctx.settings, uid, body.recipe_id, body.session_id, conn)
    return CartItemCreated(id=new_id)


@cart.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)  # #35
async def delete_cart_item(item_id: int, uid: int = Depends(get_current_user),
                           conn=Depends(get_conn)):
    row = await queries.delete_cart_item(conn, uid, item_id)
    if row is None:                         # 남의 행이거나 없음 → 404 (A01 소유권)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cart item not found")
    return None


@cart.post("/checkout", response_model=CheckoutOut)  # #36
async def checkout(uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    rows = await queries.get_cart(conn, uid)
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cart is empty")
    amount = _cart_subtotal(rows)
    # 같은 conn(=같은 트랜잭션): 지출 기록 → 장바구니 비우기.
    expense_id = await queries.insert_cart_expense(conn, uid, amount)
    await queries.clear_cart(conn, uid)
    return CheckoutOut(order=CheckoutOrder(expense_id=expense_id, amount=amount))


# ── Expense ──────────────────────────────────────────────────────────────
@expense.post("", status_code=status.HTTP_201_CREATED, response_model=ExpenseCreated)  # #39
async def add_expense(body: ExpenseCreate, uid: int = Depends(get_current_user),
                      conn=Depends(get_conn)):
    new_id = await queries.insert_expense(
        conn, uid, body.amount, body.category, body.spent_on, body.memo, body.source,
    )
    return ExpenseCreated(id=new_id)


@expense.get("/calendar", response_model=CalendarOut)  # #38
async def calendar(q: Annotated[MonthQuery, Query()], uid: int = Depends(get_current_user),
                   conn=Depends(get_conn)):
    rows = await queries.calendar_by_day(conn, uid, q.first_of_month)
    days = [CalendarDay(date=r["spent_on"], amount=int(r["amount"])) for r in rows]
    return CalendarOut(days=days)


@expense.get("/summary", response_model=ExpenseSummary)  # #40
async def summary(q: Annotated[MonthQuery, Query()], uid: int = Depends(get_current_user),
                  open_conn: ConnOpener = Depends(get_conn_opener),
                  budget: BudgetProvider = Depends(get_budget_provider),
                  pantry: PantryProvider = Depends(get_pantry_provider)):
    # 예산·안버린재료(HTTP)는 conn 없이 동시 진행 → conn 은 월 지출(DB) 구간에만 좁게 쥔다.
    budget_task = asyncio.create_task(_try_budget(budget, uid))   # budget seam
    saved_task = asyncio.create_task(_try_saved(pantry, uid))     # pantry seam
    try:
        async with open_conn() as conn:
            spent = await queries.month_spent(conn, uid, q.first_of_month)   # 실구현
    finally:
        budget_amt = await budget_task   # DB 성패 무관 항상 완료까지(누수 방지; _try_* 는 예외를 삼킴)
        saved = await saved_task
    remaining = None if budget_amt is None else budget_amt - spent
    return ExpenseSummary(spent=spent, budget=budget_amt, remaining=remaining,
                          saved_ingredients=saved)


@expense.get("/breakdown", response_model=ExpenseBreakdown)  # 성과보기 '식비 구성'
async def breakdown(q: Annotated[MonthQuery, Query()], uid: int = Depends(get_current_user),
                    conn=Depends(get_conn)):
    rows = await queries.category_breakdown(conn, uid, q.first_of_month)
    amounts = {r["category"]: int(r["amount"]) for r in rows}
    total = sum(amounts.values())
    categories = [
        CategoryAmount(category=c, amount=amounts.get(c, 0),
                       ratio=(round(amounts.get(c, 0) / total, 4) if total else 0.0))
        for c in _CATEGORIES
    ]
    return ExpenseBreakdown(month=q.month, total=total, categories=categories)


# ── Recommend ────────────────────────────────────────────────────────────
@recommend.post("/recommend", response_model=RecommendOut)  # #32
async def recommend_recipes(body: RecommendReq, uid: int = Depends(get_current_user),
                            open_conn: ConnOpener = Depends(get_conn_opener),
                            pantry: PantryProvider = Depends(get_pantry_provider),
                            exclusion: ExclusionProvider = Depends(get_exclusion_provider),
                            ctx: AppCtx = Depends(get_ctx)):
    # ★ pantry·exclusion·ranking 은 전부 크로스서비스 HTTP → conn 없이 돈다. conn 은 후보조회·노출로깅
    #   DB 구간에만 open_conn() 으로 좁게 연다(이 핸들러가 3번 왕복을 도는 동안 풀을 점유하지 않게).
    try:
        stock = await pantry.get_pantry(uid)
    except ProviderUnavailable:
        # 크로스서비스(pantry) 미가용 → degrade(빈 목록 + 사유).
        return RecommendOut(recommendations=[], note="pantry service unavailable")
    owned = [s.item_id for s in stock]
    if not owned:
        return RecommendOut(recommendations=[], note="no pantry items to base recommendation on")
    expiring = [s.item_id for s in stock if s.expiring]
    try:                                             # 제외(회피) 재료 seam — 미가용이면 제외 없이 진행.
        excluded = await exclusion.get_excluded_item_ids(uid)
    except ProviderUnavailable:
        excluded = []
    async with open_conn() as conn:                  # 후보 조회 — DB 구간만 좁게(랭킹 HTTP 전에 반납)
        rows = await queries.get_candidate_recipes(conn, owned, excluded, limit=50)
    candidates = group_recipe_rows(rows)
    ranked = rank_recipes(candidates, owned, expiring, budget=body.budget)
    # P1 2단계 블렌딩 — ML 서빙으로 개인화 재랭킹(flag ON·데이터有일 때만). 미가용/콜드스타트 → 규칙순.
    order = await ranking_client.personalize(ctx.settings, uid, ranked, body.budget)
    if order:
        ranked = ranking_client.reorder(ranked, order)
    top = ranked[:20]
    recs = [
        Recommendation(recipe_id=r.id, name=r.name, score=r.score, coverage=r.coverage,
                       matched=list(r.matched_item_ids), expiring_used=r.expiring_used,
                       est_cost=r.est_cost, image_url=r.image_url)
        for r in top
    ]
    # P1 랭킹 학습데이터 — 노출 로깅(설계 §3ⓐ). flag OFF/테이블 부재면 무동작(best-effort).
    if ctx.settings.impression_log_enabled:
        async with open_conn() as conn:              # 별도 DB 구간(후보 조회와 무관·독립 커밋)
            await queries.insert_impressions(conn, uid, body.session_id, top, body.budget, body.prefer)
    return RecommendOut(recommendations=recs, note=None)
