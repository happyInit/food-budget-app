"""env var 컨벤션 — pipelines/ingest/_db.py 의 PG* 이름 재사용.

⚠️ price/recipe와 달리 **모듈 전역 `settings = Settings()` 를 두지 않는다.**
Settings는 lifespan에서 1회 생성해 AppCtx에 담아 전달 → 함수가 전역을 읽지 않음(주입 seam).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # 인증 (⚠️ jwt_secret 은 반드시 .env 로 주입 — 코드 기본값은 개발용 placeholder)
    jwt_secret: str = "dev-insecure-change-me"
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
