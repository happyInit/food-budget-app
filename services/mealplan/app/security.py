"""Security — JWT 발급/검증 딥 모듈. account/app/security.py 를 그대로 복제.

mealplan은 로그인/회원가입이 없어 hash/verify_password 는 쓰지 않지만(account가 발급한
JWT를 verify_access 로 검증만), 템플릿 통일을 위해 원본을 그대로 둔다(bcrypt 미사용 무방).
순수(DB·전역·시계 목킹 무관) → 인터페이스만으로 완전 테스트됨(tests/test_security.py).
"""
from __future__ import annotations

import datetime as dt

import bcrypt
import jwt  # PyJWT (design.md §6.1 스택)


class TokenError(Exception):
    """JWT 검증 실패 (만료·서명불일치·타입불일치)."""


class Security:
    def __init__(self, secret: str, alg: str = "HS256",
                 access_ttl_min: int = 30, refresh_ttl_days: int = 14) -> None:
        self._secret = secret
        self._alg = alg
        self._access_ttl = dt.timedelta(minutes=access_ttl_min)
        self._refresh_ttl = dt.timedelta(days=refresh_ttl_days)

    # ── 비밀번호 (mealplan 미사용, 템플릿 통일용) ──
    def hash_password(self, raw: str) -> str:
        return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()

    def verify_password(self, raw: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(raw.encode(), hashed.encode())
        except ValueError:
            return False  # 손상된 해시

    # ── JWT ──
    def _encode(self, user_id: int, typ: str, ttl: dt.timedelta) -> str:
        now = dt.datetime.now(dt.timezone.utc)
        payload = {"sub": str(user_id), "typ": typ, "iat": now, "exp": now + ttl}
        return jwt.encode(payload, self._secret, algorithm=self._alg)

    def issue(self, user_id: int) -> tuple[str, str]:
        """(access, refresh) 토큰 쌍."""
        return (self._encode(user_id, "access", self._access_ttl),
                self._encode(user_id, "refresh", self._refresh_ttl))

    def _verify(self, token: str, expect_typ: str) -> int:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._alg])
        except jwt.PyJWTError as e:
            raise TokenError(str(e))
        if payload.get("typ") != expect_typ:
            raise TokenError(f"expected {expect_typ} token")
        return int(payload["sub"])

    def verify_access(self, token: str) -> int:
        return self._verify(token, "access")

    def verify_refresh(self, token: str) -> int:
        return self._verify(token, "refresh")
