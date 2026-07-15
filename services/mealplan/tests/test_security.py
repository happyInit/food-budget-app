"""Security 딥 모듈 — 인터페이스만으로 완전 검증(DB·전역·서버 불요). account 복제.
mealplan은 verify_access(account 발급 JWT 검증)만 쓰지만, 딥 모듈 계약을 그대로 검증한다."""
from __future__ import annotations

import pytest

from app.security import Security, TokenError


def test_token_roundtrip():
    s = Security("secret")
    access, refresh = s.issue(42)
    assert s.verify_access(access) == 42
    assert s.verify_refresh(refresh) == 42


def test_token_type_is_enforced():
    s = Security("secret")
    access, refresh = s.issue(1)
    with pytest.raises(TokenError):
        s.verify_refresh(access)           # access를 refresh로 통과시키면 안 됨
    with pytest.raises(TokenError):
        s.verify_access(refresh)


def test_tampered_token_rejected():
    s = Security("secret")
    access, _ = s.issue(1)
    with pytest.raises(TokenError):
        Security("other-secret").verify_access(access)   # 서명키 불일치 → 거부
