"""env var 컨벤션 — pipelines/ingest/_db.py 의 PG* 이름을 그대로 재사용."""
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

    redishost: str = "192.168.0.8"
    redisport: str = "6379"

    generator_backend: str = "template"   # template | gemini (bedrock=Nova/Claude, AWS 이전 후)
    extractor_backend: str = "rule"        # rule | ner (ner=CrfSpanExtractor in-process 로드)
    ner_model_path: str = ""               # 비우면 기본경로(ml/ingredient-ner/data/model/crf_ingredient.pkl)

    # Gemini 생성 백엔드 (opt-in — 기본 template 유지, 팀 재승인 전까지 실험용).
    # 프로덕션 활성은 AGENTS.md 유료예외 재승인 필요(chat-assistant-ai.md §3).
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"   # 별칭=항상 최신 최저가 lite(버전 deprecated 회피)
    gemini_max_output_tokens: int = 200           # 다듬기 응답이라 짧게 → 비용 최소
    gemini_temperature: float = 0.3               # 낮게 → 환각 억제
    gemini_timeout_s: float = 8.0                 # 초과 시 template 출력으로 fallback
    # 비용 최소화 레버:
    gemini_refine_recommend_only: bool = True     # 가격·영양은 이미 깔끔 → 레시피 추천만 다듬음(호출↓)
    gemini_cache_ttl_s: int = 2592000             # 동일 근거 다듬기 결과 Redis 캐시(30일) → 재호출 0원

    max_message_len: int = 200
    daily_request_cap: int = 200           # 유저별 일일 요청 상한(가드레일, §guardrails)


settings = Settings()
