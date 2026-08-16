"""video 서비스 설정 — 12-factor(env). 비밀은 로깅/출력하지 않는다.

모델·플래그 기본값은 `ml/video-recipe/README.md`의 비용 설계를 그대로 따른다
(영상 토큰이 비용의 90%+ → 1차 추출은 최저가 모델, 재분석은 하드실패 건만, 정제는 기본 OFF).
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # ── Gemini(영상 이해) ────────────────────────────────────────────────
    # ⚠️ Bedrock으로 이관 불가 — Bedrock은 YouTube URL 입력을 받지 못한다.
    #    근거: docs/ai-model-selection-final.md · bedrock-migration-design.md §6
    # 🔵 GenAI 환경변수 규약은 서비스마다 다르다 — 표 = `services/CONVENTIONS.md` §4.1.
    #    (2026-08-16 그 차이 때문에 "video 가 처음부터 안 됐다" 는 오진이 났다)
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
    #
    # 🔴 **기본값 = 현행 온프렘 동작**(이슈 #642 · #644 이원화 원칙). 온프렘엔 ElastiCache 가 없어
    #    이 방어가 필요 없고, 켜면 최악 지연이 3s → 9.16s 로 늘어 사용자 대기가 길어진다.
    #    새 동작은 `overlays/eks` 에서 명시적으로 켠다 — 그게 이 방어가 실제로 필요한 곳이다.
    redis_health_check_s: int = 0                        # 0 = 비활성(현행) · EKS 는 30
    # ⚠️ `ge=1` — 0 을 주면 `_retrying` 이 명령을 **아예 실행하지 않고** 오도하는 TypeError 를
    #    낸다(비판 검토 🟡11 실증). "재시도 없음"은 0 이 아니라 **1**(= 1회 시도)이다.
    redis_job_retries: int = Field(default=1, ge=1)      # 1 = 재시도 없음(현행) · EKS 는 3
    # 🔴 백오프 기준을 0.05 → 0.5 로 올린 근거 (실측 2026-08-13):
    #
    #   Redis 상태별 실제 지연 (retries=3 · socket_timeout=3)
    #     연결 거부(엔드포인트 0)  base 0.05 → <b>0.15초</b>   base 0.5 → <b>1.5초</b>
    #     패킷 블랙홀(무응답)      base 0.05 → 9.16초    base 0.5 → 10.5초
    #
    #   🔴 종전 0.05 는 **연결 거부 상황에서 0.15초 만에 3회를 소진**해 사실상 재시도가 아니었다.
    #      온프렘 Sentinel 페일오버는 `<name>-master` 엔드포인트가 **~26초 공백**이고
    #      (docs/mp_k8s_redis_ha_handoff.md:115 실측) 그게 정확히 "연결 거부" 형태다.
    #      26초를 덮으려면 백오프가 26초여야 하는데 그건 사용자를 그만큼 세우는 것이라 안 한다.
    #      ⇒ **목표는 26초 갭이 아니라 1~2초짜리 재연결 블립**이고, 0.5 가 그 창을 덮는다.
    #
    #   상한을 1.5초로 잡은 이유 = 프론트 폴링 간격이 **2초**다(queries.ts `refetchInterval`).
    #   그보다 길면 서버가 폴링 주기를 붙들어 오히려 나빠진다.
    #
    #   🔴 서버 재시도의 진짜 값어치는 **POST 경로**에 있다 — `GET /extract/{job_id}` 는
    #      React Query 가 `retry: 1` + 2초 폴링으로 이미 다시 오지만(main.tsx:16),
    #      `POST /extract`(mutation)는 **클라이언트 재시도가 0** 이라 서버가 유일한 방어다.
    redis_job_retry_base_s: float = 0.5                  # 0.5 → 1.0 (합 1.5초 < 폴링 2초)
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
