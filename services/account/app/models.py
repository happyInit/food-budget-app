"""요청/응답 스키마. docs/design/api-spec.md #2~10."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, EmailStr, Field


# ── Auth #2~6 ──
class SignupReq(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    nickname: str = Field(min_length=1, max_length=30)


class LoginReq(BaseModel):
    email: EmailStr
    password: str


class KakaoReq(BaseModel):
    code: str


class RefreshReq(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── User #7~10 ──
class UserOut(BaseModel):
    id: int
    email: str | None = None          # 카카오 유저는 null
    nickname: str
    provider: str


class UpdateUserReq(BaseModel):
    nickname: str = Field(min_length=1, max_length=30)


class BudgetReq(BaseModel):
    amount: int = Field(ge=0)         # KRW 정수(₩ 포맷은 프론트가 파생)


class BudgetOut(BaseModel):
    month: date                       # 매월 1일 정규화
    amount: int
