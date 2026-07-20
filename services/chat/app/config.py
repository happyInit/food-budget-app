"""env var 컨벤션 — pipelines/ingest/_db.py 의 PG* 이름을 그대로 재사용."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    pghost: str = "192.168.0.8"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""

    # 커넥션 풀 (env 튜닝 — 워커 수·PG max_connections와 한 세트로 조정. docs 인프라 핸드오프 참조)
    pg_pool_min: int = 1
    pg_pool_max: int = 5

    # 하위 저장소 호출 상한 — 느린 ES/PG가 커넥션을 무한 점유해 풀을 고갈시키는 것을 방지.
    es_request_timeout_s: float = 3.0
    pg_statement_timeout_ms: int = 8000

    eshost: str = "192.168.0.8"
    esport: str = "9200"

    redishost: str = "192.168.0.8"
    redisport: str = "6379"

    generator_backend: str = "template"   # template | gemini (bedrock=Nova/Claude, AWS 이전 후)
    extractor_backend: str = "rule"        # rule | ner (ner=CrfSpanExtractor in-process 로드)
    ner_model_path: str = ""               # 비우면 기본경로(ml/ingredient-ner/data/model/crf_ingredient.pkl)
    intent_ml_enabled: bool = False        # true+모델파일 있으면 규칙 미해결(unknown) 시 ML 의도분류 보강(prep-ahead)
    intent_ml_path: str = ""               # chat-insights 이식포맷 모델 경로(+.meta.json). 비우면 규칙만
    alias_path: str = ""                   # 정규화 인덱스(변형→표준철자). 비우면 app/data/aliases.json

    # Gemini 생성 백엔드 (opt-in — 기본 template 유지, 팀 재승인 전까지 실험용).
    # 프로덕션 활성은 AGENTS.md 유료예외 재승인 필요(chat-assistant-ai.md §3).
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"   # 별칭=항상 최신 최저가 lite(버전 deprecated 회피)
    gemini_max_output_tokens: int = 200           # 다듬기 응답이라 짧게 → 비용 최소
    gemini_temperature: float = 0.3               # 낮게 → 환각 억제
    gemini_timeout_s: float = 3.0                 # 초과 시 template fallback. 콜드 refine 실측 ~1s라 3s 여유+최악상한↓(속도 강점 유지)
    # 비용 최소화 레버:
    gemini_refine_recommend_only: bool = True     # 가격·영양은 이미 깔끔 → 레시피 추천만 다듬음(호출↓)
    gemini_cache_ttl_s: int = 2592000             # 동일 근거 다듬기 결과 Redis 캐시(30일) → 재호출 0원

    max_message_len: int = 200
    daily_request_cap: int = 200           # 유저/IP별 일일 요청 상한(가드레일, §guardrails)
    rate_limit_enabled: bool = False       # true면 상한 초과 시 유료 생성(Gemini) → 무료 template 강등(설계 §7). 기본 OFF=현동작 유지
    rate_limit_window_s: int = 86400       # 상한 카운터 TTL(24h)

    # 월 예산 상한(글로벌 비용 브레이크) — Google 청구캡(8,000원) 전에 우아하게 template 강등.
    #   근거·값 선정: docs/chat-monthly-cost-cap-analysis.md. 기본 OFF=현동작 유지.
    monthly_cap_enabled: bool = False        # true면 월 누적 유료호출 비용이 예산 초과 시 template 강등
    monthly_budget_won: int = 7200           # Google 청구캡 8,000원의 90%(하드스톱 전 강등 + 오차 버퍼)
    gemini_cost_per_call_won: float = 0.06   # 실측 호출당 비용(요율·환율 변동 시 갱신) → 예산÷단가=호출상한
    monthly_cap_window_s: int = 3024000      # 카운터 TTL ~35일(월 자동 리셋)

    # 멀티턴 맥락 (opt-in — 기본 OFF로 기존 단일턴 경로 무손상). Redis 단기 세션, 영속 X.
    multiturn_enabled: bool = False        # true여야 세션 로드·저장·팔로우업 승계 동작
    multiturn_max_turns: int = 8           # 세션당 유지할 최근 턴 수(user+bot 합산)
    multiturn_ttl_s: int = 3600            # 세션 TTL(초) — 단기(1시간), 프라이버시 최소

    # account 제외재료 API 양방향 연동(개인화 영속화) — 기본 OFF. **인증(JWT) 생기면 활성**.
    #   read: 마이 페이지 제외재료를 챗봇 추천에 적용 / write: 챗봇 "빼줘"를 마이 페이지에 영속.
    #   남의 서비스는 API로만 접근(직접 DB 아님). 미설정/미인증이면 전부 무동작(현재와 동일).
    account_integration_enabled: bool = False
    chat_persist_enabled: bool = False     # true면 인증(동의) 유저 대화를 chat.chat_message에 영속(#127, 대화분석 입력)
    account_base_url: str = ""             # 예 http://192.168.0.9:PORT (account 서비스)

    # OpenTelemetry Trace. 로컬 기본값은 비활성이라 Tempo가 없어도 개발·테스트에 영향 없음.
    # 운영 Compose에서만 활성화하고 fb-monitoring VM의 공개 OTLP gRPC 포트로 직접 전송한다.
    otel_traces_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "192.168.0.11:4317"
    otel_exporter_otlp_insecure: bool = True
    otel_traces_sampler_ratio: float = 1.0


settings = Settings()
