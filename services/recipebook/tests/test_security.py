"""Security 검증 딥 모듈 — verify_access 계약(A07)만 인터페이스로 검증(DB·서버·시계 무관).
recipebook은 토큰 소비자 — issue/hash 없음(pantry 트림 선례). account 발급 access 토큰을 로컬 검증한다."""
from __future__ import annotations

import datetime as dt

import jwt
import pytest

from app.security import Security, TokenError

SECRET = "secret"


def _token(sub=7, typ="access", secret=SECRET, ttl_min=30):
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {"sub": str(sub), "typ": typ, "iat": now, "exp": now + dt.timedelta(minutes=ttl_min)},
        secret, "HS256",
    )


def test_verify_access_returns_uid():
    assert Security(SECRET).verify_access(_token(sub=42)) == 42


def test_verify_rejects_wrong_secret():
    with pytest.raises(TokenError):
        Security(SECRET).verify_access(_token(secret="other-secret"))   # 서명 위조 → 거부


def test_verify_rejects_refresh_typ():
    with pytest.raises(TokenError):
        Security(SECRET).verify_access(_token(typ="refresh"))           # refresh 를 access 로 못 씀


def test_verify_rejects_expired():
    with pytest.raises(TokenError):
        Security(SECRET).verify_access(_token(ttl_min=-1))              # 이미 만료(exp 과거)
