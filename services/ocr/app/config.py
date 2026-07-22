"""env 설정 — 챗봇 services/chat/app/config.py 컨벤션 재사용."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ocr_backend: str = "vision"                    # vision(운영) | mock(dev/데모/CI, 키·과금 X). 향후 tesseract/vision_first
    max_image_bytes: int = 8 * 1024 * 1024         # 업로드 상한(가드)

    # Gemini Vision (유료예외 — AGENTS.md 재승인 문서화 대상)
    # ⚠️ 챗봇과 **별도 키**를 쓴다(서비스별 .env로 분리). 같은 키로도 동작하지만, OCR(비전·장당
    #    과금)과 챗봇(refine) 비용을 **서비스 단위로 명확히 구분·추적**하려 키를 분리한다 — 사용량·
    #    청구를 각각 독립 모니터링/상한 관리 가능(유료예외 거버넌스에 부합). 값은 신규 발급 키.
    gemini_api_key: str = ""
    # 실물 13장 벤치마크(docs/ocr-model-benchmark.md): 이 lite가 성공률 92%·0.45원/장·2.8s로 최적.
    # 채택 = -latest 별칭(=벤치마크한 바로 그 모델). `gemini-3.5-flash-lite` 명시는 미존재(404)라
    # 이 모델을 콕 집으려면 별칭뿐. ⚠️ 별칭 드리프트는 GCP 빌링 예산상한 + 주기 재확인으로 방어.
    gemini_model: str = "gemini-flash-lite-latest"   # thinking 예산은 gemini_thinking_budget 병행
    # thinking 예산: -1=동적(모델 자율·소량), 0=완전 끄기, 양수=상한 토큰.
    # ⚠️ `-latest` 별칭이 3.x flash-lite로 롤링된 뒤 **0(끄기)은 400 INVALID_ARGUMENT로 거부**된다
    #    (구 2.5 lite에선 0 허용됐음 — 별칭 드리프트). 그래서 기본은 -1(동적). 값이 거부되면
    #    vision.py가 thinking_config를 빼고 1회 재시도(_is_bad_argument 폴백)해 서비스는 유지.
    gemini_thinking_budget: int = -1
    gemini_timeout_s: float = 60.0                 # 비전 호출 상한(초). 실측 ~2~5s이나 여유 60s
    image_max_side: int = 1600                     # 업로드 이미지 최장변 상한(px) — 초과 시 축소(속도·비용↓)

    # 분류 캐스케이드 참조 데이터(§7.2) — repo 자산 재사용. 배포 시 패키징 경로로 env override.
    #   없으면 해당 단계만 skip(서비스는 계속 동작) — 라이브 호출 없이 룩업·규칙만.
    dict_item_master_path: str = ""   # 식재료 gazetteer 소스(빈값=repo 기본경로 자동)
    shelf_life_path: str = ""         # item_name→storage 시드(DB shelf_life_ref 실패 시 파일 폴백)
    # 경계정책(생수·얼음·홍삼정)은 정책이라 코드 상수(_EDGE_POLICY) — 경로/env 없음.

    # PG (ocr_receipt 저장은 백엔드 담당 — 여기선 NER item_master 조회 등 향후용)
    pghost: str = "192.168.0.8"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""


settings = Settings()
