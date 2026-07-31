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
    # Sentinel 모드(분기 C — K8s) — 콤마구분 "host:port" 나열, sentinel 파드 3개 전부(단일 DNS 금지).
    # 값이 있으면 db.py 가 Service 대신 Sentinel 로 master 를 찾는다. 비우면 위 단일 호스트 폴백
    # — 현행 VM(.8) 동작 불변. 근거 = docs/mp_k8s_redis_ha_handoff.md §4(분기 C).
    redis_sentinels: str = ""
    redis_master_group: str = "mymaster"   # 🔴 소문자 — 인라인 sentinel 의 기본 그룹명(CR 로 못 바꿈)
    cache_enabled: bool = True
    cache_current_ttl_s: int = 300     # 현재가 캐시 TTL(5분)
    cache_hotdeals_ttl_s: int = 120    # 핫딜 캐시 TTL(2분)

    default_limit: int = 20
    history_limit: int = 200

    # 관심 등록/해제(#29·#30)만 인증이 필요하다 — 조회 API는 지금처럼 공개.
    # ⚠️ jwt_secret 은 반드시 .env 로 주입 — 코드 기본값은 개발용 placeholder.
    #    account 서비스와 **같은 값**이어야 발급 토큰을 검증할 수 있다.
    jwt_secret: str = "dev-insecure-change-me"
    jwt_alg: str = "HS256"


settings = Settings()
