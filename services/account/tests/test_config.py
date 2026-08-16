"""JWT_SECRET fail-fast (AWS 이관 체크리스트 0-12) — 조용한 폴백이 돌아오면 여기서 깨진다.

`_env_file=None` 을 넘기는 이유: 개발자 로컬에 `services/account/.env` 가 있으면 그 값이 먹혀
"미주입" 상황을 재현할 수 없다. 이 테스트는 **env 만** 본다.
"""
from __future__ import annotations

import pytest

from app.config import JWT_SECRET_MIN_LEN, RELEASE_UNSET, ConfigError, Settings, release


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


# ── MP_RELEASE (Blue-Green 신원) ────────────────────────────────────────────
# 🔴 여기서 지키는 성질은 "값이 맞다" 가 아니라 **"모르면 모른다고 답한다"** 이다.
#    주입이 빠졌을 때 마지막으로 알던 값을 계속 답하면, 승격 시연에서 *전환이 안 됐는데 됐다고*
#    읽히거나 그 반대가 된다 — 판정 근거로 쓸 수 없는 값이 된다.
def test_release_reads_env(monkeypatch):
    monkeypatch.setenv("MP_RELEASE", "7d9f4c2")
    assert release() == "7d9f4c2"


def test_release_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("MP_RELEASE", raising=False)
    assert release() == RELEASE_UNSET


def test_release_treats_blank_as_unset(monkeypatch):
    # downward API 가 라벨을 못 찾으면 빈 문자열이 들어온다 — 빈 값을 그대로 노출하면
    # 응답이 `"release": ""` 가 되어 "주입이 빠진 것"과 "버전이 빈 것"이 구분되지 않는다.
    monkeypatch.setenv("MP_RELEASE", "   ")
    assert release() == RELEASE_UNSET
