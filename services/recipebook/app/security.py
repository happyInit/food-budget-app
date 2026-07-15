"""Security — JWT **검증** 딥 모듈 (account가 발급한 access 토큰을 recipebook이 로컬 검증).

recipebook은 토큰 **소비자**다 — 발급(issue)·비밀번호 해시 없음 → bcrypt 불요(A03 의존성 최소화).
검증 규약은 account/security.py._verify 와 **동일**(HS256 · typ=='access' · sub=user_id) 해야
account 발급 토큰과 호환된다. 순수(DB·전역·시계 무관) → 인터페이스만으로 검증 가능.

★ A07: 서명(secret 불일치)·만료(exp)·타입(typ) 을 서버에서 검증 → 위조/탈취/타입혼용 토큰 거부.
"""
from __future__ import annotations

import jwt  # PyJWT (design.md §6.1 스택)


class TokenError(Exception):
    """JWT 검증 실패 (만료·서명불일치·타입불일치)."""


class Security:
    def __init__(self, secret: str, alg: str = "HS256") -> None:
        self._secret = secret
        self._alg = alg

    def verify_access(self, token: str) -> int:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._alg])
        except jwt.PyJWTError as e:
            raise TokenError(str(e))  # 만료·서명불일치 등 (exp 는 PyJWT가 자동 검사)
        if payload.get("typ") != "access":
            raise TokenError("expected access token")  # refresh 토큰을 access로 못 쓰게
        return int(payload["sub"])
