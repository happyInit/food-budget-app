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

import asyncio
from dataclasses import dataclass
from typing import Protocol

import httpx

# connect(=DNS+TLS)만 넉넉히, read/write/pool 은 타이트하게. 콜드 첫 로그인의 병목은
# CoreDNS 콜드 캐시(ndots 검색도메인 헛질)라 connect 예산만 늘리면 실패가 사라진다.
_TIMEOUT = httpx.Timeout(5.0, connect=10.0)

_RETRY_ATTEMPTS = 2       # 최초 시도 + 재시도 1회
_RETRY_BACKOFF = 0.2      # 초, 시도마다 선형 증가

# 🔴 '서버 도달 전' 실패만 재시도 대상 — authorization code 는 단일 사용이라, 요청이 나간
#    뒤(ReadTimeout·4xx)에 재시도하면 'code already used' 로 오히려 깨진다.
_CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def make_http_client() -> httpx.AsyncClient:
    """lifespan 이 만들어 provider 들에 공유 주입하는 커넥션 풀(앱 수명 동안 keep-alive).
    매 로그인 새 클라이언트를 열지 않아 TLS·커넥션이 재사용된다."""
    return httpx.AsyncClient(timeout=_TIMEOUT)


async def warm_dns(urls: tuple[str, ...]) -> None:
    """provider 도메인을 미리 해석해 CoreDNS 캐시를 데운다. CoreDNS 캐시는 클러스터 공유라
    이 1회로 첫 유저 로그인까지 웜이 된다. lifespan 이 백그라운드 태스크로 띄운다(기동 안 막음).
    best-effort — 실패·지연이 서비스를 막지 않도록 host 별 타임아웃 + 예외 무시."""
    loop = asyncio.get_running_loop()

    async def _resolve(host: str) -> None:
        try:
            await asyncio.wait_for(loop.getaddrinfo(host, 443), timeout=5.0)
        except Exception:  # noqa: BLE001 — 워밍업 실패/지연이 서비스를 막으면 안 된다
            pass

    await asyncio.gather(*(_resolve(h) for h in {httpx.URL(u).host for u in urls}))


async def _post_token(http: httpx.AsyncClient, url: str, *, data: dict) -> httpx.Response:
    """code→token 교환 POST. code 단일 사용이라 connect 단계 실패(코드 미소비)만 재시도한다."""
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            r = await http.post(url, data=data)
            r.raise_for_status()
            return r
        except _CONNECT_ERRORS:
            if attempt + 1 == _RETRY_ATTEMPTS:
                raise
            await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))


async def _get_userinfo(http: httpx.AsyncClient, url: str, *, headers: dict) -> httpx.Response:
    """userinfo 조회 GET. idempotent 라 connect·read 트랜지언트 모두 재시도 안전."""
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            r = await http.get(url, headers=headers)
            r.raise_for_status()
            return r
        except (*_CONNECT_ERRORS, httpx.ReadTimeout):
            if attempt + 1 == _RETRY_ATTEMPTS:
                raise
            await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))


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

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str,
                 http: httpx.AsyncClient) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._http = http

    async def exchange(self, code: str, redirect_uri: str | None = None) -> OAuthProfile:
        try:
            tok = await _post_token(self._http, self._TOKEN_URI, data={
                "grant_type": "authorization_code",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": redirect_uri or self._redirect_uri,
                "code": code,
            })
            access = tok.json()["access_token"]
            me = await _get_userinfo(self._http, self._USER_URI,
                                     headers={"Authorization": f"Bearer {access}"})
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

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str,
                 http: httpx.AsyncClient) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._http = http

    async def exchange(self, code: str, redirect_uri: str | None = None) -> OAuthProfile:
        try:
            tok = await _post_token(self._http, self._TOKEN_URI, data={
                "grant_type": "authorization_code",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": redirect_uri or self._redirect_uri,
                "code": code,
            })
            access = tok.json()["access_token"]
            info = await _get_userinfo(self._http, self._USER_URI,
                                       headers={"Authorization": f"Bearer {access}"})
            body = info.json()
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise OAuthError(f"google exchange failed: {e}") from e
        sub = body.get("sub")
        if not sub:
            raise OAuthError("google: response missing sub")
        email = body.get("email")
        nickname = body.get("name") or (email.split("@")[0] if email else None) or "구글사용자"
        return OAuthProfile(provider_uid=str(sub), nickname=nickname, email=email)


# lifespan 워밍업 대상 — 두 provider 의 4개 엔드포인트 도메인(콜드 DNS 선캐싱).
WARMUP_URLS = (
    KakaoProvider._TOKEN_URI, KakaoProvider._USER_URI,
    GoogleProvider._TOKEN_URI, GoogleProvider._USER_URI,
)
