"""env var 컨벤션 — account 서비스와 동일(PG* 이름 + JWT). account에서 그대로 복사.

⚠️ price/recipe와 달리 **모듈 전역 `settings = Settings()` 를 두지 않는다.**
Settings는 lifespan에서 1회 생성해 AppCtx에 담아 전달 → 함수가 전역을 읽지 않음(주입 seam).

이 서비스(recipebook)는 로그인/회원가입이 없다 → JWT는 **검증(verify_access)만** 한다.
account가 발급한 access 토큰을 신뢰(재검증 안 함) → jwt_secret/jwt_alg만 실사용.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 데이터베이스 (단일 PG, 이 서비스는 recipebook 스키마 소유 — schema-production.sql §recipebook)
    pghost: str = "localhost"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""
    pg_pool_min: int = 1
    # Pooler(PgBouncer) 경유라 앱 풀은 작게 잡는다 — 다중화는 Pooler 가 한다(object_spec §4.5).
    pg_pool_max: int = 5

    # 인증 (⚠️ jwt_secret 은 반드시 .env 로 주입 — 코드 기본값은 개발용 placeholder)
    #   account와 동일 secret/alg 여야 account 발급 토큰을 검증할 수 있다.
    jwt_secret: str = "dev-insecure-change-me"
    jwt_alg: str = "HS256"
    access_ttl_min: int = 30
    refresh_ttl_days: int = 14

    # Elasticsearch — 공개 발행 레시피 목록/검색(list_shared_recipes). PGSync CDC 가 색인.
    #   기본값은 app-common ConfigMap 실측(인클러스터 ES)과 맞춘다.
    eshost: str = "es-es-http.data.svc"
    esport: str = "9200"
    # ECK(P2)는 인증을 강제한다. 값이 없으면 무인증 — 현행 VM ES 동작이 그대로 유지된다.
    es_user: str = ""
    es_password: str = ""
    # 인덱스는 항상 alias `user_recipes_live`. 🔴 물리 인덱스명(user_recipes_v1)을 박지 않는다
    # (alias 뒤 물리 인덱스는 운영이 교체할 수 있다 — AGENTS.md 참조).
    es_index: str = "user_recipes_live"
