"""JWT 검증 + 인증 경로 테스트 (A07). account 발급 토큰을 pantry가 로컬 검증하는 경계를 지킨다.
- 순수: Security.verify_access — 서명(secret)·만료(exp)·타입(typ='access') 검증.
- 통합: get_current_user 실검증 경로 — 실제 Bearer 헤더로 라우트 통과/거부(override 없이).
conftest 가 JWT_SECRET 을 아래 SECRET 과 동일 값으로 고정 → 발급/검증 키 일치.
"""
from __future__ import annotations

import datetime as dt

import jwt
import pytest

import app.main as main_mod
from app.context import get_conn
from app.security import Security, TokenError
from tests.fakes import FakeConn

SECRET = "test-secret-0123456789abcdef0123456789"   # = conftest.TEST_JWT_SECRET (앱과 동일 키, ≥32B)
OV = main_mod.app.dependency_overrides


def _token(sub=7, typ="access", secret=SECRET, ttl_min=30):
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {"sub": str(sub), "typ": typ, "iat": now, "exp": now + dt.timedelta(minutes=ttl_min)},
        secret, "HS256",
    )


# ── 순수 verify_access ─────────────────────────────────────────────────────
def test_verify_access_returns_uid():
    assert Security(SECRET).verify_access(_token(sub=42)) == 42


def test_verify_rejects_wrong_secret():
    with pytest.raises(TokenError):
        Security(SECRET).verify_access(_token(secret="other-secret-0123456789abcdef0123"))  # 서명 위조


def test_verify_rejects_refresh_typ():
    with pytest.raises(TokenError):
        Security(SECRET).verify_access(_token(typ="refresh"))           # refresh 를 access 로 못 씀


def test_verify_rejects_expired():
    with pytest.raises(TokenError):
        Security(SECRET).verify_access(_token(ttl_min=-1))              # 이미 만료(exp 과거)


# ── 통합: 실제 Bearer 헤더로 get_current_user 검증 경로(override 없이) ──────────
def test_valid_bearer_reaches_handler(client):
    OV[get_conn] = lambda: FakeConn(responses=[])
    r = client.get("/api/pantry/items", headers={"Authorization": f"Bearer {_token(sub=7)}"})
    assert r.status_code == 200                                         # 유효 토큰 → 핸들러 도달


def test_wrong_secret_bearer_401(client):
    forged = _token(secret="evil-secret-0123456789abcdef0123456789")
    r = client.get("/api/pantry/items", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401                                         # 위조 서명 거부


def test_refresh_token_as_access_401(client):
    r = client.get("/api/pantry/items", headers={"Authorization": f"Bearer {_token(typ='refresh')}"})
    assert r.status_code == 401                                         # 타입 혼용 거부
