"""KakaoProvider·GoogleProvider 의 code 교환 경로 — 실 네트워크 없이 httpx MockTransport 로 검증.

기존 테스트는 재시도 헬퍼(_post_token·_get_userinfo)와 라우터(FakeOAuthProvider)만 덮고 있어서
**provider 의 exchange 본체는 무방비**였다. 공통 골격(_CodeExchangeProvider)으로 합치는
리팩터의 안전망이자, provider 응답 파싱 계약(닉네임 폴백 순서·필수 필드)의 회귀 방지다.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.oauth import GoogleProvider, KakaoProvider, OAuthError

_KAKAO_TOKEN = "https://kauth.kakao.com/oauth/token"
_KAKAO_USER = "https://kapi.kakao.com/v2/user/me"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_USER = "https://openidconnect.googleapis.com/v1/userinfo"


def _client(routes: dict[str, httpx.Response]) -> httpx.AsyncClient:
    """URL → 응답 매핑으로 도는 가짜 전송계층. 등록 안 된 URL 은 500 으로 떨군다."""
    def handler(request):
        return routes.get(str(request.url), httpx.Response(500))
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _exchange(provider_cls, token_url, user_url, user_body, *, token_body=None):
    async def go():
        async with _client({
            token_url: httpx.Response(200, json=token_body or {"access_token": "tok"}),
            user_url: httpx.Response(200, json=user_body),
        }) as http:
            p = provider_cls("cid", "csecret", "https://app/callback", http)
            return await p.exchange("the-code")
    return asyncio.run(go())


# ── 카카오 ────────────────────────────────────────────────────────────────
def test_kakao_exchange_returns_profile():
    prof = _exchange(KakaoProvider, _KAKAO_TOKEN, _KAKAO_USER,
                     {"id": 12345, "kakao_account": {"profile": {"nickname": "봉수"}}})
    assert prof.provider_uid == "12345"      # 회원번호는 정수로 오지만 문자열로 정규화
    assert prof.nickname == "봉수"
    assert prof.email is None                # 계정연동 결정 전이라 카카오는 email 을 안 담는다


def test_kakao_nickname_falls_back_to_legacy_properties():
    """동의항목에 따라 kakao_account.profile 이 비고 레거시 properties 만 오는 경우."""
    prof = _exchange(KakaoProvider, _KAKAO_TOKEN, _KAKAO_USER,
                     {"id": 7, "properties": {"nickname": "레거시"}})
    assert prof.nickname == "레거시"


def test_kakao_nickname_defaults_when_absent():
    prof = _exchange(KakaoProvider, _KAKAO_TOKEN, _KAKAO_USER, {"id": 7})
    assert prof.nickname == "카카오사용자"


def test_kakao_missing_id_raises():
    with pytest.raises(OAuthError, match="missing member id"):
        _exchange(KakaoProvider, _KAKAO_TOKEN, _KAKAO_USER, {"kakao_account": {}})


# ── 구글 ──────────────────────────────────────────────────────────────────
def test_google_exchange_returns_profile():
    prof = _exchange(GoogleProvider, _GOOGLE_TOKEN, _GOOGLE_USER,
                     {"sub": "10987", "name": "Kevin", "email": "kevin@example.com"})
    assert (prof.provider_uid, prof.nickname, prof.email) == ("10987", "Kevin", "kevin@example.com")


def test_google_nickname_falls_back_to_email_local_part():
    prof = _exchange(GoogleProvider, _GOOGLE_TOKEN, _GOOGLE_USER,
                     {"sub": "1", "email": "someone@example.com"})
    assert prof.nickname == "someone"


def test_google_nickname_defaults_when_absent():
    prof = _exchange(GoogleProvider, _GOOGLE_TOKEN, _GOOGLE_USER, {"sub": "1"})
    assert prof.nickname == "구글사용자"


def test_google_missing_sub_raises():
    with pytest.raises(OAuthError, match="missing sub"):
        _exchange(GoogleProvider, _GOOGLE_TOKEN, _GOOGLE_USER, {"name": "no sub"})


# ── 공통 실패 봉인 ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("provider_cls,token_url,name", [
    (KakaoProvider, _KAKAO_TOKEN, "kakao"),
    (GoogleProvider, _GOOGLE_TOKEN, "google"),
])
def test_token_endpoint_error_is_wrapped_as_oauth_error(provider_cls, token_url, name):
    """4xx 는 httpx 예외로 새어나가면 안 된다 — 라우터가 OAuthError 만 401 로 매핑한다."""
    async def go():
        async with _client({token_url: httpx.Response(400, json={"error": "invalid_grant"})}) as http:
            p = provider_cls("cid", "csecret", "https://app/callback", http)
            await p.exchange("used-code")

    with pytest.raises(OAuthError, match=f"{name} exchange failed"):
        asyncio.run(go())


@pytest.mark.parametrize("provider_cls,token_url,user_url", [
    (KakaoProvider, _KAKAO_TOKEN, _KAKAO_USER),
    (GoogleProvider, _GOOGLE_TOKEN, _GOOGLE_USER),
])
def test_missing_access_token_is_wrapped_as_oauth_error(provider_cls, token_url, user_url):
    """토큰 응답에 access_token 이 없으면 KeyError 가 아니라 OAuthError 여야 한다."""
    async def go():
        async with _client({
            token_url: httpx.Response(200, json={"no": "token"}),
            user_url: httpx.Response(200, json={}),
        }) as http:
            p = provider_cls("cid", "csecret", "https://app/callback", http)
            await p.exchange("the-code")

    with pytest.raises(OAuthError, match="exchange failed"):
        asyncio.run(go())
