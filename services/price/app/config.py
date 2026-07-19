"""env var 컨벤션 — pipelines/ingest/_db.py 의 PG* 이름 재사용."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pghost: str = "192.168.0.8"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""

    # 커넥션 풀 (env 튜닝 — 워커 수·PG max_connections와 한 세트로 조정. docs 인프라 핸드오프 참조)
    pg_pool_min: int = 1
    pg_pool_max: int = 5

    # Redis 캐시 — 현재가·핫딜은 읽기 편중이고 가격은 일1~2회만 변경 → 짧은 TTL로 DB 왕복 대폭↓.
    #   무효화 = TTL(크롤 주기보다 훨씬 짧아 staleness 무시 가능) + 크롤 후 refresh 스크립트가 flush.
    redishost: str = "192.168.0.8"
    redisport: str = "6379"
    cache_enabled: bool = True
    cache_current_ttl_s: int = 300     # 현재가 캐시 TTL(5분)
    cache_hotdeals_ttl_s: int = 120    # 핫딜 캐시 TTL(2분)

    default_limit: int = 20
    history_limit: int = 200


settings = Settings()
