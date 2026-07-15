"""라우터 — api-spec #32~40. 핸들러는 Depends로 의존성 주입(전역 state 없음 → 테스트 가능).
쿼리 결과는 dict(row_factory=dict_row) → `row["name"]`. numeric(Decimal)은 명시적으로 int().

라우터 3개(account가 auth·users 2개 include 하듯 여러 개 include):
  cart(/api/mealplan/cart) · expense(/api/expenses) · recommend(/api/mealplan).
self-contained(#34·35·36·38·39·cart조회·월합계)는 완전 실구현.
seam 붙은 부분(#33 예산 · #40 예산·안버린재료 · #32 재고)만 주입 어댑터(없으면 null/degrade).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg.errors import ForeignKeyViolation

from app import queries
from app.context import (
    BudgetProvider, PantryProvider, ProviderUnavailable,
    get_budget_provider, get_conn, get_current_user, get_pantry_provider,
)
from app.models import (
    CalendarDay, CalendarOut, CartItemCreate, CartItemCreated, CartItemOut,
    CartOut, CheckoutOrder, CheckoutOut, ExpenseCreate, ExpenseCreated,
    ExpenseSummary, MonthQuery, Recommendation, RecommendOut, RecommendReq,
)
from app.ranking import group_recipe_rows, rank_recipes

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


# ── Cart ─────────────────────────────────────────────────────────────────
@cart.get("", response_model=CartOut)  # #33
async def get_cart(uid: int = Depends(get_current_user), conn=Depends(get_conn),
                   budget: BudgetProvider = Depends(get_budget_provider)):
    rows = await queries.get_cart(conn, uid)
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
    budget_amt = await _try_budget(budget, uid)
    remaining = None if budget_amt is None else budget_amt - subtotal
    return CartOut(items=items, subtotal=subtotal, budget=budget_amt, remaining=remaining)


@cart.post("/items", status_code=status.HTTP_201_CREATED, response_model=CartItemCreated)  # #34
async def add_cart_item(body: CartItemCreate, uid: int = Depends(get_current_user),
                        conn=Depends(get_conn)):
    try:
        new_id = await queries.insert_cart_item(
            conn, uid, body.name, body.recipe_id, body.item_id,
            body.retail_product_id, body.qty, body.quantity,
        )
    except ForeignKeyViolation:  # 없는 recipe/item/product 참조 → 500 대신 400 (psycopg→HTTPException 매핑)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid recipe/item/product reference")
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
                  conn=Depends(get_conn),
                  budget: BudgetProvider = Depends(get_budget_provider),
                  pantry: PantryProvider = Depends(get_pantry_provider)):
    spent = await queries.month_spent(conn, uid, q.first_of_month)   # 실구현
    budget_amt = await _try_budget(budget, uid)                       # budget seam
    remain = None if budget_amt is None else budget_amt - spent
    try:                                                             # pantry seam
        saved = await pantry.saved_ingredients(uid)
    except ProviderUnavailable:
        saved = None
    return ExpenseSummary(spent=spent, budget=budget_amt, remain=remain,
                          saved_ingredients=saved)


# ── Recommend ────────────────────────────────────────────────────────────
@recommend.post("/recommend", response_model=RecommendOut)  # #32
async def recommend_recipes(body: RecommendReq, uid: int = Depends(get_current_user),
                            conn=Depends(get_conn),
                            pantry: PantryProvider = Depends(get_pantry_provider)):
    try:
        stock = await pantry.get_pantry(uid)
    except ProviderUnavailable:
        # 크로스서비스(pantry) 미가용 → degrade(빈 목록 + 사유).
        return RecommendOut(recommendations=[], note="pantry service unavailable")
    owned = [s.item_id for s in stock]
    if not owned:
        return RecommendOut(recommendations=[], note="no pantry items to base recommendation on")
    expiring = [s.item_id for s in stock if s.expiring]
    rows = await queries.get_candidate_recipes(conn, owned, limit=50)
    candidates = group_recipe_rows(rows)
    ranked = rank_recipes(candidates, owned, expiring, budget=body.budget)
    recs = [
        Recommendation(recipe_id=r.id, name=r.name, score=r.score, coverage=r.coverage,
                       matched=list(r.matched_item_ids), expiring_used=r.expiring_used,
                       est_cost=r.est_cost)
        for r in ranked[:20]
    ]
    return RecommendOut(recommendations=recs, note=None)
