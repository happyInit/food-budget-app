"""env var 컨벤션 — pipelines/ingest/_db.py 의 PG* 이름 재사용. (account 정본 복제 + notify 트림.)

⚠️ price/recipe와 달리 **모듈 전역 `settings = Settings()` 를 두지 않는다.**
Settings는 lifespan에서 1회 생성해 AppCtx에 담아 전달 → 함수가 전역을 읽지 않음(주입 seam).
notify는 토큰을 발급하지 않고 verify_access만 하므로 access/refresh TTL 설정은 두지 않는다.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 데이터베이스 (단일 PG, 이 서비스는 notify 스키마 소유 — schema-production.sql)
    pghost: str = "localhost"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""

    # 커넥션 풀 (env 튜닝 — 워커 수·PG max_connections와 한 세트로 조정. docs 인프라 핸드오프 참조)
    pg_pool_min: int = 1
    pg_pool_max: int = 5

    # 인증 — account가 발급한 access JWT를 **검증만** 한다(발급 X).
    # ⚠️ jwt_secret 은 반드시 .env 로 주입 — 코드 기본값은 개발용 placeholder.
    jwt_secret: str = "dev-insecure-change-me"
    jwt_alg: str = "HS256"
