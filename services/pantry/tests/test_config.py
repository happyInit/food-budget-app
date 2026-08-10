"""JWT_SECRET fail-fast (AWS 이관 체크리스트 0-12) — 조용한 폴백이 돌아오면 여기서 깨진다.

`_env_file=None` 을 넘기는 이유: 개발자 로컬에 `services/pantry/.env` 가 있으면 그 값이 먹혀
"미주입" 상황을 재현할 수 없다. 이 테스트는 **env 만** 본다.
"""
from __future__ import annotations

import pytest

from app.config import JWT_SECRET_MIN_LEN, ConfigError, Settings


def _settings(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("JWT_SECRET", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET", value)
    return Settings(_env_file=None)


def test_missing_jwt_secret_blocks_startup(monkeypatch):
    with pytest.raises(ConfigError):
        _settings(monkeypatch, None)


def test_placeholder_jwt_secret_blocks_startup(monkeypatch):
    with pytest.raises(ConfigError):
        _settings(monkeypatch, "dev-insecure-change-me")


def test_short_jwt_secret_blocks_startup(monkeypatch):
    with pytest.raises(ConfigError):
        _settings(monkeypatch, "x" * (JWT_SECRET_MIN_LEN - 1))


def test_real_jwt_secret_boots(monkeypatch):
    value = "y" * JWT_SECRET_MIN_LEN
    assert _settings(monkeypatch, value).jwt_secret == value


def test_error_message_never_leaks_the_value(monkeypatch):
    """🔴 크래시 로그로 비밀이 새면 안 된다 — ValueError 로 던지면 pydantic 이 입력 dict 를 찍는다."""
    secret = "leaky-but-too-short"
    with pytest.raises(ConfigError) as excinfo:
        _settings(monkeypatch, secret)
    assert secret not in str(excinfo.value)
