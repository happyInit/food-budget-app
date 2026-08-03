"""env var 컨벤션 — pipelines/ingest/_db.py · services/chat 의 PG*/ES* 이름 재사용."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pghost: str = "localhost"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""
    pg_pool_min: int = 1
    # Pooler(PgBouncer) 경유라 앱 풀은 작게 잡는다 — 다중화는 Pooler 가 한다(object_spec §4.5).
    pg_pool_max: int = 5

    eshost: str = "localhost"
    esport: str = "9200"
    # ECK(P2)는 인증을 강제한다. 값이 없으면 무인증 — 현행 VM ES 동작이 그대로 유지된다.
    es_user: str = ""
    es_password: str = ""

    # 레시피 검색 백엔드. ES 인덱스(index_recipes_es.py) 적재 완료 → 기본 "es"(nori 형태소).
    # 리스트·검색 모두 ES 기준으로 통일. ES 장애 시 핸들러가 PG로 자동 degrade.
    search_backend: str = "es"  # es | pg
    es_index: str = "recipes"

    page_size: int = 20

    # 서빙 대상 레시피 소스. 만개의레시피(10K)만 서비스에 노출.
    # (COOKRCP01=식약처, EPIS=농식품 — 서빙 제외. 필요 시 콤마로 확장)
    serve_source: str = "10K"


settings = Settings()
