"""라우터 — api-spec #2~10. 핸들러는 Depends로 의존성 주입(전역 state 없음 → 테스트 가능).
쿼리 결과는 dict(row_factory=dict_row) → `row["email"]`, 컬럼명이 모델과 같으면 `UserOut(**row)`.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.errors import ForeignKeyViolation, UniqueViolation

from app import queries
from app.context import get_conn, get_current_user, get_oauth, get_security
from app.models import (
    AccessToken, BudgetOut, BudgetReq, ExcludedItemOut, ExcludedItemReq, GoogleReq,
    KakaoReq, LoginReq, RefreshReq, SignupReq, TokenPair, UpdateUserReq, UserOut,
)
from app.oauth import OAuthClients, OAuthError, OAuthProvider
from app.security import Security, TokenError

logger = logging.getLogger("account")

auth = APIRouter(prefix="/api/auth", tags=["auth"])
users = APIRouter(prefix="/api/users", tags=["users"])


# ── Auth ─────────────────────────────────────────────────────────────────
@auth.post("/signup", status_code=status.HTTP_201_CREATED)  # #2
async def signup(body: SignupReq, conn=Depends(get_conn), sec: Security = Depends(get_security)):
    # bcrypt(CPU 집약·수십 ms)는 동기라 이벤트 루프를 막는다 → 스레드로 오프로드(고동시성 블로킹 방지).
    pw_hash = await asyncio.to_thread(sec.hash_password, body.password)
    try:
        uid = await queries.create_local_user(
            conn, body.email, pw_hash, body.nickname
        )
    except UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    return {"userId": uid}


@auth.post("/login", response_model=TokenPair)  # #3
async def login(body: LoginReq, conn=Depends(get_conn), sec: Security = Depends(get_security)):
    row = await queries.get_login_user(conn, body.email)
    # bcrypt 검증도 스레드로 오프로드(이벤트 루프 블로킹 방지). row/해시 없으면 단락되어 실행 안 됨.
    if row is None or row["password_hash"] is None \
            or not await asyncio.to_thread(sec.verify_password, body.password, row["password_hash"]):
        logger.warning("login failed", extra={"event": "authentication_failed"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    access, refresh = sec.issue(row["id"])
    return TokenPair(access_token=access, refresh_token=refresh)


async def _oauth_login(provider_name: str, provider: OAuthProvider, code: str,
                       redirect_uri: str | None, conn, sec: Security) -> TokenPair:
    """소셜 로그인 공통 — code 교환 → (provider,provider_uid) upsert → 우리 JWT 발급.
    redirect_uri = 프론트가 authorize 때 쓴 값(교환도 동일해야 함). provider 교환 실패는 401.
    신규·재로그인 모두 upsert_oauth_user 가 흡수."""
    try:
        profile = await provider.exchange(code, redirect_uri)
    except OAuthError:
        logger.warning("oauth exchange failed",
                       extra={"event": "authentication_failed", "provider": provider_name})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"{provider_name} oauth failed")
    uid = await queries.upsert_oauth_user(conn, provider_name, profile.provider_uid, profile.nickname)
    access, refresh = sec.issue(uid)
    return TokenPair(access_token=access, refresh_token=refresh)


@auth.post("/kakao", response_model=TokenPair)  # #4
async def kakao(body: KakaoReq, conn=Depends(get_conn),
                sec: Security = Depends(get_security), oauth: OAuthClients = Depends(get_oauth)):
    return await _oauth_login("kakao", oauth.kakao, body.code, body.redirect_uri, conn, sec)


@auth.post("/google", response_model=TokenPair)  # #4b 소셜 로그인 — 구글
async def google(body: GoogleReq, conn=Depends(get_conn),
                 sec: Security = Depends(get_security), oauth: OAuthClients = Depends(get_oauth)):
    return await _oauth_login("google", oauth.google, body.code, body.redirect_uri, conn, sec)


@auth.post("/refresh", response_model=AccessToken)  # #5
async def refresh(body: RefreshReq, sec: Security = Depends(get_security)):
    try:
        uid = sec.verify_refresh(body.refresh_token)
    except TokenError:
        logger.warning("refresh token verification failed", extra={"event": "token_invalid"})
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


@users.delete("/me", status_code=status.HTTP_204_NO_CONTENT)  # 회원 탈퇴
async def delete_me(uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    row = await queries.delete_user(conn, uid)
    if row is None:                                   # 이미 없음 → 404
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return None


@users.get("/budget", response_model=BudgetOut | None)  # #9
async def get_budget(uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    row = await queries.get_current_budget(conn, uid)
    return None if row is None else BudgetOut(month=row["month"], amount=int(row["amount"]))


@users.put("/budget", response_model=BudgetOut)  # #10
async def put_budget(body: BudgetReq, uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    row = await queries.upsert_current_budget(conn, uid, body.amount)
    return BudgetOut(month=row["month"], amount=int(row["amount"]))


# ── 제외 재료 (회피 재료 — 추천에서 걸러낼 표준품목. A01: JWT 소유자 스코프) ──
@users.get("/excluded-items", response_model=list[ExcludedItemOut])
async def list_excluded(uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    rows = await queries.list_excluded_items(conn, uid)
    return [ExcludedItemOut(**r) for r in rows]


@users.post("/excluded-items", status_code=status.HTTP_201_CREATED, response_model=ExcludedItemOut)
async def add_excluded(body: ExcludedItemReq, uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    try:
        row = await queries.add_excluded_item(conn, uid, body.item_id, body.name)
    except ForeignKeyViolation:                       # 없는 표준품목 → 404
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown item_id")
    return ExcludedItemOut(**row)


@users.delete("/excluded-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_excluded(item_id: int, uid: int = Depends(get_current_user), conn=Depends(get_conn)):
    row = await queries.remove_excluded_item(conn, uid, item_id)
    if row is None:                                   # 남의 것/없음 → 404 (A01)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "excluded item not found")
    return None
