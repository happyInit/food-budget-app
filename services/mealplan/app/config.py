"""env var 컨벤션 — account/app/config.py 를 복제(주입 seam). 모듈 전역 `settings` 없음.

Settings는 lifespan에서 1회 생성해 AppCtx에 담아 전달 → 함수가 전역을 읽지 않음.
mealplan 전용 추가: 크로스서비스 어댑터(budget=account, pantry) base URL (schema-per-service:
DB 조인 금지 → API 호출 seam). 실제 배선 전엔 default placeholder(어댑터가 degrade).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 데이터베이스 (단일 PG, 이 서비스는 mealplan 스키마 소유 — schema-production.md §1)
    pghost: str = "192.168.0.8"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""

    # 인증 (account가 발급한 JWT를 검증만 함 — jwt_secret 은 반드시 .env 로 account와 동일 값 주입)
    jwt_secret: str = "dev-insecure-change-me"
    jwt_alg: str = "HS256"
    access_ttl_min: int = 30
    refresh_ttl_days: int = 14

    # 크로스서비스 seam(어댑터 base URL) — 예산=account User API, 재고=pantry API.
    #   schema-per-service 규칙: account.user_budget·pantry.pantry_item 직접 조인 금지 → API 호출.
    account_base_url: str = "http://account:8004"
    pantry_base_url: str = "http://pantry:8005"

    # P1 개인화 랭킹 학습데이터 — 추천 노출을 activity.recipe_impression에 기록(설계 clickstream §3ⓐ).
    #   기본 OFF·best-effort(테이블 부재/실패는 조용히 skip → 추천 응답 무손상). 동의·스키마 준비 후 ON.
    impression_log_enabled: bool = False
