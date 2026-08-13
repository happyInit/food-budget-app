"""video 서비스 설정 — 12-factor(env). 비밀은 로깅/출력하지 않는다.

모델·플래그 기본값은 `ml/video-recipe/README.md`의 비용 설계를 그대로 따른다
(영상 토큰이 비용의 90%+ → 1차 추출은 최저가 모델, 재분석은 하드실패 건만, 정제는 기본 OFF).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # ── Gemini(영상 이해) ────────────────────────────────────────────────
    # ⚠️ Bedrock으로 이관 불가 — Bedrock은 YouTube URL 입력을 받지 못한다.
    #    근거: docs/ai-model-selection-final.md · bedrock-migration-design.md §6
    video_gemini_api_key: str = ""
    video_extract_model: str = "gemini-3.5-flash-lite"   # 1차 추출(최저가) — 영상 1회 통과
    video_retry_model: str = "gemini-3.5-flash"          # 하드실패 1회만 재분석
    video_refine_model: str = "gemini-3.5-flash"         # 텍스트 정제
    video_refine_enabled: bool = False                   # 기본 OFF(비용)
    video_timeout_s: float = 120.0                       # 영상 분석은 길다 — OCR(60s)보다 여유

    # ── Redis (잡 상태 · 교차유저 캐시) ──────────────────────────────────
    # ⚠️ 잡 상태를 인메모리로 두면 replica를 못 늘린다(OCR이 겪은 #296).
    #    이 서비스는 **처음부터 Redis**로 외부화해 replica-safe로 시작한다(#298).
    redishost: str = "localhost"
    redisport: int = 6379
    # 🔴 ElastiCache(C-14) 페일오버 대비 — 체크리스트 1-14. Multi-AZ 전환은 DNS 이름이 유지된 채
    #    뒤의 노드가 바뀌므로 **기존 커넥션이 끊기고 재연결이 필요**하다. 아래 둘이 그 창을 덮는다.
    redis_health_check_s: int = 30                       # 유휴 커넥션 재사용 전 PING — 죽은 소켓 차단
    redis_job_retries: int = 3                           # 잡 상태 경로만 재시도(캐시·락은 degrade)
    redis_job_retry_base_s: float = 0.05                 # 지수 백오프 기준 — 0.05 → 0.1 → 0.2
    job_ttl_s: int = 3600                                # 잡 상태 보존(1h)
    cache_ttl_s: int = 2592000                           # 추출 결과 교차유저 캐시(30일) → 재요청 0원
    lock_ttl_s: int = 180                                # 단일비행 락 — 같은 URL 동시 요청 중복 분석 방지

    # ── PostgreSQL (gazetteer — 재료명→item_id 정규화) ──────────────────
    # 추출 결과가 item_id를 못 얻으면 재료비·재고·알림과 연결되지 않는다.
    pghost: str = "localhost"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""

    # ── 서비스 ──────────────────────────────────────────────────────────
    environment: str = "dev"
    log_level: str = "INFO"


settings = Settings()
