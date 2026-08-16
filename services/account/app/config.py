"""env var 컨벤션 — pipelines/ingest/_db.py 의 PG* 이름 재사용.

⚠️ price/recipe와 달리 **모듈 전역 `settings = Settings()` 를 두지 않는다.**
Settings는 lifespan에서 1회 생성해 AppCtx에 담아 전달 → 함수가 전역을 읽지 않음(주입 seam).
"""
from __future__ import annotations

import os
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

# ── 빌드 신원 (Blue-Green 시연·운영 판별용) ────────────────────────────────────
# 🔴 이 값을 **손으로 적지 않는다.** K8s 에서는 파드 템플릿 해시(`rollouts-pod-template-hash`)를
#    downward API 로 주입한다 — 템플릿이 바뀌면 쿠버네티스가 다시 계산하므로 **어긋날 수가 없다.**
#    손으로 적은 버전 문자열은 이미지만 갈리고 문자열은 그대로일 때 *거짓말을 하고*, 그 거짓말은
#    "지금 트래픽이 어느 버전에 가 있나" 를 판정하는 순간에 정확히 쓸모없어진다.
# ⚠️ Settings 와 달리 모듈 전역 상수로 두지 않고 **함수**다 — 이 파일 머리말의 "전역 상태를 읽지
#    않는다" 규약을 지키기 위해서고, 덕분에 테스트가 monkeypatch 로 갈아끼울 수 있다.
RELEASE_UNSET = "dev"


def release() -> str:
    """빌드/배포 신원. 미주입이면 `dev` — 🔵 여기서는 기동을 막지 않는다.

    JWT_SECRET(위)과 달리 이 값이 없다고 **위험해지지는 않는다**. 관측이 흐려질 뿐이라
    fail-fast 대상이 아니다. 두 개를 같은 규칙으로 다루면 표시용 값 하나가 서비스를 못 뜨게 한다.
    """
    return os.getenv("MP_RELEASE", "").strip() or RELEASE_UNSET

# ── JWT_SECRET fail-fast (AWS 이관 체크리스트 0-12) ─────────────────────────────
# 🔴 커밋된 placeholder 로는 기동하지 않는다. 폴백이 있으면 env 주입이 빠져도 앱은 **정상 기동**하고
#    그 순간부터 "레포만 보면 아는 키"로 토큰을 서명·검증한다 → 토큰 위조가 가능한데 증상이 없다.
#    그래서 없거나 placeholder 면 기동을 막는다(K8s 에선 CrashLoopBackOff 로 즉시 드러난다).
# ⚠️ ConfigError 가 ValueError 를 상속하지 **않는** 이유: pydantic 은 검증 중의 ValueError 를
#    ValidationError 로 감싸면서 `input_value=` 에 **입력 dict 전체(PGPASSWORD 포함)를 찍는다**(실측).
#    비밀을 크래시 로그로 흘리지 않으려면 pydantic 이 가로채지 않는 예외여야 한다.
JWT_SECRET_MIN_LEN = 32
JWT_SECRET_PLACEHOLDERS = frozenset({"dev-insecure-change-me", "change-me", "changeme", "secret"})


class ConfigError(RuntimeError):
    """기동을 막는 설정 오류. 🔴 메시지에 비밀 **값**을 넣지 않는다(로그로 샌다)."""


def require_jwt_secret(value: str) -> None:
    """없음·placeholder·과단축 이면 기동을 막는다. 통과하면 아무것도 반환하지 않는다."""
    s = (value or "").strip()
    if not s:
        raise ConfigError("JWT_SECRET 미주입 — 기본값 폴백을 제거했다(0-12). env/ESO 로 주입하라.")
    if s.lower() in JWT_SECRET_PLACEHOLDERS:
        raise ConfigError("JWT_SECRET 이 개발용 placeholder 다(0-12) — 실제 비밀을 주입하라.")
    if len(s) < JWT_SECRET_MIN_LEN:
        raise ConfigError(
            f"JWT_SECRET 이 너무 짧다({len(s)}자 < {JWT_SECRET_MIN_LEN}자) — HS256 서명키다."
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 데이터베이스 (단일 PG, 이 서비스는 account 스키마 소유 — schema-production.md §1)
    pghost: str = "localhost"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""

    # 커넥션 풀 (env 튜닝 — 워커 수·PG max_connections와 한 세트로 조정. docs 인프라 핸드오프 참조)
    pg_pool_min: int = 1
    # P3: Pooler 경유 — 10 → 5. 다중화는 Pooler 가 한다(object_spec §4.5·§7.4).
    pg_pool_max: int = 5

    # 로그인 스로틀 (#534 — bcrypt CPU 몰림/무차별대입 방어. app/throttle.py). bcrypt cost 는 안 낮춤.
    #   동시성 캡: pod 는 부하 시 ~5 core 버스트 → 동시 8 + 얕은 대기 8, 그 위는 429(fan-out 몰림 방어).
    login_bcrypt_max_concurrent: int = 8
    login_bcrypt_max_waiting: int = 8
    #   고정창: 이메일당 10/분(사람은 안 걸림·봇 차단), IP당 100/분(0=끔 — NAT 오탐 피하려 넉넉히·XFF 전제).
    login_rate_per_email: int = 10
    login_rate_per_ip: int = 100
    login_rate_window_s: int = 60

    # 인증 (🔴 jwt_secret 은 env 필수 — placeholder 폴백 제거. 빈 값이면 아래 model_post_init 이 기동 차단)
    jwt_secret: str = ""
    jwt_alg: str = "HS256"
    access_ttl_min: int = 30
    refresh_ttl_days: int = 14

    # 소셜 로그인 OAuth (⚠️ *_client_secret 은 .env/ESO 로만 주입 — 코드엔 값 없음.
    #   redirect_uri 는 provider 콘솔 등록값과 정확히 일치해야 함. env: KAKAO_CLIENT_ID 등)
    kakao_client_id: str = ""
    kakao_client_secret: str = ""
    kakao_redirect_uri: str = "https://app.mealbong.cloud/auth/kakao/callback"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "https://app.mealbong.cloud/auth/google/callback"

    def model_post_init(self, _context: Any) -> None:
        require_jwt_secret(self.jwt_secret)
