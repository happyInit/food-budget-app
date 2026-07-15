"""Security 딥 모듈 — 인터페이스만으로 검증(DB·전역·서버 불요). account에서 복사.
recipebook은 verify_access 만 실사용하지만, 파일이 account와 동일하므로 계약을 그대로 검증한다."""
from __future__ import annotations

import pytest

from app.security import Security, TokenError


def test_token_roundtrip():
    s = Security("secret")
    access, refresh = s.issue(42)
    assert s.verify_access(access) == 42     # recipebook의 get_current_user가 쓰는 경로
    assert s.verify_refresh(refresh) == 42


def test_token_type_is_enforced():
    s = Security("secret")
    access, refresh = s.issue(1)
    with pytest.raises(TokenError):
        s.verify_access(refresh)             # refresh를 access로 통과시키면 안 됨


def test_tampered_token_rejected():
    s = Security("secret")
    access, _ = s.issue(1)
    with pytest.raises(TokenError):
        Security("other-secret").verify_access(access)   # 서명키 불일치 → 거부
