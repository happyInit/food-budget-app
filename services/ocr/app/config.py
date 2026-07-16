"""env 설정 — 챗봇 services/chat/app/config.py 컨벤션 재사용."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ocr_backend: str = "vision"                    # vision (현재 유일 — 팀장 결정). 향후 tesseract/vision_first
    max_image_bytes: int = 8 * 1024 * 1024         # 업로드 상한(가드)

    # Gemini Vision (유료예외 — AGENTS.md 재승인 문서화 대상)
    # ⚠️ 챗봇과 **별도 키**를 쓴다(서비스별 .env로 분리). 같은 키로도 동작하지만, OCR(비전·장당
    #    과금)과 챗봇(refine) 비용을 **서비스 단위로 명확히 구분·추적**하려 키를 분리한다 — 사용량·
    #    청구를 각각 독립 모니터링/상한 관리 가능(유료예외 거버넌스에 부합). 값은 신규 발급 키.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"      # 비전 정확도용 flash(비용 OK 결정). PoC로 튜닝
    gemini_timeout_s: float = 60.0                 # 비전 호출 상한(초). flash-latest 비전이 실측 ~40s → 여유 60s
    image_max_side: int = 1600                     # 업로드 이미지 최장변 상한(px) — 초과 시 축소(속도·비용↓)

    # PG (ocr_receipt 저장은 백엔드 담당 — 여기선 NER item_master 조회 등 향후용)
    pghost: str = "192.168.0.8"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""


settings = Settings()
