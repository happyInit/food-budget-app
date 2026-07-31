"""env var 컨벤션 — account와 동일 PG* 이름(pipelines/ingest/_db.py 재사용).

⚠️ price/recipe와 달리 **모듈 전역 `settings = Settings()` 를 두지 않는다.**
Settings는 lifespan에서 1회 생성해 AppCtx에 담아 전달 → 함수가 전역을 읽지 않음(주입 seam).

pantry는 JWT를 **발급하지 않고** account가 발급한 access 토큰을 **검증만** 한다 →
jwt_secret/jwt_alg 만 필요(access_ttl·refresh_ttl 불요). secret 은 account와 동일 값 공유.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 데이터베이스 (단일 PG — pantry 스키마 소유 + public 데이터 티어 읽기(shelf_life_ref·item_master))
    pghost: str = "192.168.0.8"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""
    pg_pool_min: int = 1
    # Pooler(PgBouncer) 경유라 앱 풀은 작게 잡는다 — 다중화는 Pooler 가 한다(object_spec §4.5).
    pg_pool_max: int = 5

    # 인증 검증 (⚠️ jwt_secret 은 account와 **동일 값**을 .env 로 주입 — 코드 기본값은 개발용 placeholder)
    jwt_secret: str = "dev-insecure-change-me"
    jwt_alg: str = "HS256"
