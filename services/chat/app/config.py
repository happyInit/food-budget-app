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

    generator_backend: str = "template"   # template | bedrock | gemini (bedrock/gemini 미구현)
    extractor_backend: str = "rule"        # rule | ner (ner는 NER 완성 전까지 미구현)

    max_message_len: int = 200
    daily_request_cap: int = 200           # 유저별 일일 요청 상한(가드레일, §guardrails)


settings = Settings()
