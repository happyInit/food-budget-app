"""env var 컨벤션 — account와 동일 PG* 이름(pipelines/ingest/_db.py 재사용).

⚠️ price/recipe와 달리 **모듈 전역 `settings = Settings()` 를 두지 않는다.**
Settings는 lifespan에서 1회 생성해 AppCtx에 담아 전달 → 함수가 전역을 읽지 않음(주입 seam).

pantry는 JWT를 **발급하지 않고** account가 발급한 access 토큰을 **검증만** 한다 →
jwt_secret/jwt_alg 만 필요(access_ttl·refresh_ttl 불요). secret 은 account와 동일 값 공유.
"""
from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

# ── JWT_SECRET fail-fast (AWS 이관 체크리스트 0-12) — account/app/config.py 복제 ──
# 🔴 커밋된 placeholder 로는 기동하지 않는다. 폴백이 있으면 env 주입이 빠져도 앱은 **정상 기동**하고
#    그 순간부터 "레포만 보면 아는 키"로 토큰을 검증한다 → 토큰 위조가 가능한데 증상이 없다.
# ⚠️ ConfigError 가 ValueError 를 상속하지 **않는** 이유: pydantic 은 검증 중의 ValueError 를
#    ValidationError 로 감싸면서 입력 dict 전체(PGPASSWORD 포함)를 에러 메시지에 찍는다(실측).
JWT_SECRET_MIN_LEN = 32
JWT_SECRET_PLACEHOLDERS = frozenset({"dev-insecure-change-me", "change-me", "changeme", "secret"})


class ConfigError(RuntimeError):
    """기동을 막는 설정 오류. 🔴 메시지에 비밀 **값**을 넣지 않는다(로그로 샌다)."""


def require_jwt_secret(value: str) -> None:
    """없음·placeholder·과단축 이면 기동을 막는다."""
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

    # 데이터베이스 (단일 PG — pantry 스키마 소유 + public 데이터 티어 읽기(shelf_life_ref·item_master))
    pghost: str = "localhost"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""
    pg_pool_min: int = 1
    # Pooler(PgBouncer) 경유라 앱 풀은 작게 잡는다 — 다중화는 Pooler 가 한다(object_spec §4.5).
    pg_pool_max: int = 5

    # 인증 검증 (🔴 jwt_secret 은 env 필수·account와 **동일 값**. placeholder 폴백 제거)
    jwt_secret: str = ""
    jwt_alg: str = "HS256"

    def model_post_init(self, _context: Any) -> None:
        require_jwt_secret(self.jwt_secret)
