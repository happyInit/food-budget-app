"""OAuth 재시도 헬퍼 단위 테스트 — 실 네트워크 없이 httpx MockTransport 로
connect/read 트랜지언트를 주입해 재시도 정책을 검증한다(DB·async 러너 불필요, asyncio.run).

핵심 계약: authorization code 는 단일 사용이라 token 교환은 'connect 단계' 실패만
재시도하고 4xx·ReadTimeout 은 재시도하지 않는다. userinfo(GET)는 idempotent 라
read 트랜지언트도 재시도한다.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app import oauth

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    # 테스트가 실제 sleep 하지 않도록 백오프 제거
    monkeypatch.setattr(oauth, "_RETRY_BACKOFF", 0.0)


def _run(handler, call):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await call(http)
    return asyncio.run(go())


def test_post_token_retries_once_on_connect_error():
    """콜드 DNS 등 connect 실패 → 코드 미소비라 1회 재시도 후 성공."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("cold dns", request=request)
        return httpx.Response(200, json={"access_token": "tok"})

    r = _run(handler, lambda http: oauth._post_token(http, _TOKEN_URL, data={"code": "x"}))
    assert calls["n"] == 2
    assert r.json()["access_token"] == "tok"


def test_post_token_does_not_retry_on_4xx():
    """4xx(invalid_grant 등)는 코드가 이미 소비됐을 수 있어 재시도 금지 — 1회로 끝."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, json={"error": "invalid_grant"})

    with pytest.raises(httpx.HTTPStatusError):
        _run(handler, lambda http: oauth._post_token(http, _TOKEN_URL, data={"code": "x"}))
    assert calls["n"] == 1


def test_post_token_does_not_retry_on_read_timeout():
    """요청이 나간 뒤(ReadTimeout)는 코드 소비 가능 → token 교환은 재시도 금지."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(httpx.ReadTimeout):
        _run(handler, lambda http: oauth._post_token(http, _TOKEN_URL, data={"code": "x"}))
    assert calls["n"] == 1


def test_userinfo_retries_on_read_timeout():
    """userinfo 는 GET(idempotent) → read 트랜지언트도 재시도해 성공."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={"sub": "123"})

    r = _run(handler, lambda http: oauth._get_userinfo(http, _USERINFO_URL, headers={}))
    assert calls["n"] == 2
    assert r.json()["sub"] == "123"
