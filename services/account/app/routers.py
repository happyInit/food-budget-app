"""라우터 — api-spec #2~10. 핸들러는 Depends로 의존성 주입(전역 state 없음 → 테스트 가능).
쿼리 결과는 dict(row_factory=dict_row) → `row["email"]`, 컬럼명이 모델과 같으면 `UserOut(**row)`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.errors import UniqueViolation

from app import queries
from app.context import get_conn, get_current_user, get_security
from app.models import (
    AccessToken, BudgetOut, BudgetReq, KakaoReq, LoginReq, RefreshReq,
    SignupReq, TokenPair, UpdateUserReq, UserOut,
)
from app.security import Security, TokenError

auth = APIRouter(prefix="/api/auth", tags=["auth"])
users = APIRouter(prefix="/api/users", tags=["users"])


# ── Auth ─────────────────────────────────────────────────────────────────
@auth.post("/signup", status_code=status.HTTP_201_CREATED)  # #2
async def signup(body: SignupReq, conn=Depends(get_conn), sec: Security = Depends(get_security)):
    try:
        uid = await queries.create_local_user(
            conn, body.email, sec.hash_password(body.password), body.nickname
        )
    except UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    return {"userId": uid}


@auth.post("/login", response_model=TokenPair)  # #3
async def login(body: LoginReq, conn=Depends(get_conn), sec: Security = Depends(get_security)):
    row = await queries.get_login_user(conn, body.email)
    if row is None or row["password_hash"] is None \
            or not sec.verify_password(body.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    access, refresh = sec.issue(row["id"])
    return TokenPair(access_token=access, refresh_token=refresh)


@auth.post("/kakao", response_model=TokenPair)  # #4
async def kakao(body: KakaoReq, conn=Depends(get_conn), sec: Security = Depends(get_security)):
    # TODO(seam): Kakao OAuth 토큰 교환 — code → 카카오 회원번호(provider_uid)+닉네임.
    #   외부 HTTP 호출이라 별도 어댑터로 분리(테스트 시 fake 주입). queries.upsert_kakao_user 는 준비됨.
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "kakao oauth not wired yet")


@auth.post("/refresh", response_model=AccessToken)  # #5
async def refresh(body: RefreshReq, sec: Security = Depends(get_security)):
    try:
        uid = sec.verify_refresh(body.refresh_token)
    except TokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")
    access, _ = sec.issue(uid)
    return AccessToken(access_token=access)


@auth.post("/logout", status_code=status.HTTP_204_NO_CONTENT)  # #6
async def logout(_uid: int = Depends(get_current_user)):
    # 스테이트리스 JWT → 클라이언트가 토큰 폐기. 서버측 denylist(Redis)는 후속 과제.
    return None


# ── User ─────────────────────────────────────────────────────────────────
@users.get("/me", response_model=UserOut)  # #7
async def me(uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    row = await queries.get_user(conn, uid)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return UserOut(**row)  # 컬럼명 = 모델 필드 → 그대로 매핑


@users.patch("/me", response_model=UserOut)  # #8
async def update_me(body: UpdateUserReq, uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    row = await queries.update_nickname(conn, uid, body.nickname)
    return UserOut(**row)


@users.get("/budget", response_model=BudgetOut | None)  # #9
async def get_budget(uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    row = await queries.get_current_budget(conn, uid)
    return None if row is None else BudgetOut(month=row["month"], amount=int(row["amount"]))


@users.put("/budget", response_model=BudgetOut)  # #10
async def put_budget(body: BudgetReq, uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    row = await queries.upsert_current_budget(conn, uid, body.amount)
    return BudgetOut(month=row["month"], amount=int(row["amount"]))
