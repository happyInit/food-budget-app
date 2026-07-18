"""요청/응답 스키마. api-spec #32~40 (Cart·Expense·Recommend).

입력 검증 = Pydantic 타입·길이·범위·enum(Literal) (OWASP A05). ₩·D-day 등 프론트 파생값은 저장/반환 X.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Category = Literal["GROCERY", "DINING", "DELIVERY", "ETC"]
Source = Literal["MANUAL", "OCR", "CART"]


# ── Cart #33~36 ──
class CartItemCreate(BaseModel):
    """#34 담기. user_id는 바디에 받지 않는다(JWT에서 — A01)."""
    name: str = Field(min_length=1, max_length=200)
    recipe_id: int | None = None
    item_id: int | None = None
    retail_product_id: int | None = None
    qty: int = Field(default=1, ge=1, le=999)
    quantity: str | None = Field(default=None, max_length=100)


class CartItemOut(BaseModel):
    id: int
    name: str
    qty: int
    quantity: str | None = None
    item_id: int | None = None
    lowest_krw_per_100g: int | None = None   # least(kurly_100g, oasis_100g)
    source: str | None = None                # 더 싼 소스('kurly'|'oasis'|None)


class CartOut(BaseModel):
    items: list[CartItemOut]
    subtotal: int
    budget: int | None = None                # budget seam (없으면 null)
    remaining: int | None = None             # budget - subtotal (없으면 null)


class CartItemCreated(BaseModel):
    id: int


class CheckoutOrder(BaseModel):
    expense_id: int
    amount: int


class CheckoutOut(BaseModel):
    order: CheckoutOrder


# ── Expense #38~40 ──
class ExpenseCreate(BaseModel):
    """#39 지출 기록."""
    amount: int = Field(ge=0)
    category: Category
    spent_on: date
    memo: str | None = Field(default=None, max_length=500)
    source: Source = "MANUAL"


class ExpenseCreated(BaseModel):
    id: int


class MonthQuery(BaseModel):
    """#38·#40 month 쿼리 — 형식(정규식) + 실월(01~12) 검증 후 date로 파라미터 바인딩(A05)."""
    month: str = Field(pattern=r"^\d{4}-\d{2}$")

    @field_validator("month")
    @classmethod
    def _real_month(cls, v: str) -> str:
        datetime.strptime(v + "-01", "%Y-%m-%d")  # 13월·00월이면 ValueError → 422
        return v

    @property
    def first_of_month(self) -> date:
        return datetime.strptime(self.month + "-01", "%Y-%m-%d").date()


class CalendarDay(BaseModel):
    date: date
    amount: int


class CalendarOut(BaseModel):
    days: list[CalendarDay]


class ExpenseSummary(BaseModel):
    spent: int                               # 실구현(SQL sum)
    budget: int | None = None                # budget seam
    remaining: int | None = None             # budget - spent (budget seam)
    saved_ingredients: int | None = None     # pantry seam(안 버린 재료)


class CategoryAmount(BaseModel):
    """카테고리 1건 지출 합 + 총지출 대비 비중(0~1). 성과보기 '식비 구성'."""
    category: Category
    amount: int
    ratio: float                             # amount / total (total=0 이면 0.0)


class ExpenseBreakdown(BaseModel):
    """이번 달 카테고리별 지출 구성(4종 항상 포함 — 지출 없으면 0). 성과보기 실데이터."""
    month: str
    total: int
    categories: list[CategoryAmount]


# ── Recommend #32 ──
class RecommendReq(BaseModel):
    budget: int | None = Field(default=None, ge=0)
    prefer: str | None = Field(default=None, max_length=100)
    # 클릭스트림 세션(프론트 발급 uuid) — 노출 로그↔이벤트 조인키. 없으면 서버가 uuid 발급(비링크).
    session_id: str | None = Field(default=None, max_length=64)


class Recommendation(BaseModel):
    recipe_id: int
    name: str
    score: float
    coverage: float                          # 보유재료 커버리지(0~1)
    matched: list[int]                       # 보유한 재료 item_id
    expiring_used: int                       # 임박재료 사용 수
    est_cost: int | None = None              # 재료 최저가 합(원) 추정
    image_url: str | None = None             # 레시피 썸네일(표시용)


class RecommendOut(BaseModel):
    recommendations: list[Recommendation]
    note: str | None = None                  # degrade 사유(재고 미가용 등)
