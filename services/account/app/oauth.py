"""OAuth 소셜 로그인 어댑터 — 외부 provider(카카오·구글) 토큰 교환을 격리한 seam.

★ 외부 HTTP 호출이라 별도 어댑터로 분리(routers.py 의 TODO 회수 지점). 테스트는
   FakeOAuthProvider(tests/fakes.py)를 get_oauth 로 주입 → 실 네트워크 없이 라우터를 통째 검증.
   security 처럼 AppCtx.oauth 에 담겨 get_oauth 로 핸들러에 주입된다.

흐름(Authorization Code): 프론트가 provider 동의화면 → code → 백엔드 POST → 여기서 교환:
    code --(token_uri)--> access_token --(userinfo)--> provider_uid · nickname (· email)
provider_uid = 그 provider 의 불변 회원 식별자(카카오=회원번호, 구글=sub) = app_user.(provider,provider_uid) UNIQUE 키.
email 은 OAuthProfile 에 담기지만 **저장하지 않는다**(계정연동 결정 전 — queries.upsert_oauth_user 주석).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

_TIMEOUT = 5.0  # provider 왕복 2콜(token→userinfo) 합산 상한. 로그인 UX 허용 범위.


class OAuthError(Exception):
    """provider 토큰 교환/조회 실패(네트워크·4xx·형식오류). 라우터가 401 로 매핑."""


@dataclass(frozen=True)
class OAuthProfile:
    """provider 가 확인해 준 신원."""
    provider_uid: str
    nickname: str
    email: str | None = None


class OAuthProvider(Protocol):
    async def exchange(self, code: str, redirect_uri: str | None = None) -> OAuthProfile: ...


@dataclass
class OAuthClients:
    """provider 별 어댑터 묶음. lifespan 이 settings 로 만들어 AppCtx.oauth 에 담는다."""
    kakao: OAuthProvider
    google: OAuthProvider


# ── 카카오 ────────────────────────────────────────────────────────────────
class KakaoProvider:
    """카카오 로그인: code → 토큰 → /v2/user/me. provider_uid=회원번호(id), nickname=프로필 닉네임."""
    _TOKEN_URI = "https://kauth.kakao.com/oauth/token"
    _USER_URI = "https://kapi.kakao.com/v2/user/me"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    async def exchange(self, code: str, redirect_uri: str | None = None) -> OAuthProfile:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                tok = await c.post(self._TOKEN_URI, data={
                    "grant_type": "authorization_code",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": redirect_uri or self._redirect_uri,
                    "code": code,
                })
                tok.raise_for_status()
                access = tok.json()["access_token"]
                me = await c.get(self._USER_URI,
                                 headers={"Authorization": f"Bearer {access}"})
                me.raise_for_status()
                body = me.json()
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise OAuthError(f"kakao exchange failed: {e}") from e
        uid = body.get("id")
        if uid is None:
            raise OAuthError("kakao: response missing member id")
        # 닉네임: 동의 시 kakao_account.profile.nickname, 레거시는 properties.nickname. 없으면 기본값.
        nickname = (body.get("kakao_account", {}).get("profile", {}).get("nickname")
                    or body.get("properties", {}).get("nickname")
                    or "카카오사용자")
        return OAuthProfile(provider_uid=str(uid), nickname=nickname)


# ── 구글 ──────────────────────────────────────────────────────────────────
class GoogleProvider:
    """구글 로그인(OIDC): code → 토큰 → userinfo. provider_uid=sub, nickname=name."""
    _TOKEN_URI = "https://oauth2.googleapis.com/token"
    _USER_URI = "https://openidconnect.googleapis.com/v1/userinfo"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    async def exchange(self, code: str, redirect_uri: str | None = None) -> OAuthProfile:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                tok = await c.post(self._TOKEN_URI, data={
                    "grant_type": "authorization_code",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": redirect_uri or self._redirect_uri,
                    "code": code,
                })
                tok.raise_for_status()
                access = tok.json()["access_token"]
                info = await c.get(self._USER_URI,
                                   headers={"Authorization": f"Bearer {access}"})
                info.raise_for_status()
                body = info.json()
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise OAuthError(f"google exchange failed: {e}") from e
        sub = body.get("sub")
        if not sub:
            raise OAuthError("google: response missing sub")
        email = body.get("email")
        nickname = body.get("name") or (email.split("@")[0] if email else None) or "구글사용자"
        return OAuthProfile(provider_uid=str(sub), nickname=nickname, email=email)
