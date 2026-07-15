"""env var 컨벤션 — pipelines/ingest/_db.py · services/chat 의 PG*/ES* 이름 재사용."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pghost: str = "192.168.0.8"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""

    eshost: str = "192.168.0.8"
    esport: str = "9200"

    # 레시피 검색 백엔드. ES 인덱스(index_recipes_es.py) 적재 전에는 "pg".
    # 적재 후 "es" 로 바꾸면 nori 형태소 검색 사용.
    search_backend: str = "pg"  # pg | es

    page_size: int = 20

    # 서빙 대상 레시피 소스. 만개의레시피(10K)만 서비스에 노출.
    # (COOKRCP01=식약처, EPIS=농식품 — 서빙 제외. 필요 시 콤마로 확장)
    serve_source: str = "10K"


settings = Settings()
