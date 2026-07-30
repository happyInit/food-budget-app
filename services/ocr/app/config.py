"""env 설정 — 챗봇 services/chat/app/config.py 컨벤션 재사용."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ocr_backend: str = "vision"                    # vision(운영) | mock(dev/데모/CI, 키·과금 X). 향후 tesseract/vision_first
    max_image_bytes: int = 8 * 1024 * 1024         # 업로드 상한(가드)

    # ── Redis (잡 상태 외부화 #296) ──────────────────────────────────────
    # 인메모리로 두면 replica를 늘리는 순간 'POST 받은 파드 != GET 받은 파드'가 되어
    # 결과 조회가 404가 난다 → replicas:1 · HPA 없음에 묶였다. Redis로 옮겨 제약을 푼다.
    # 비우면 인메모리 폴백(단일 replica 개발환경). ⚠️ 그 상태로 replicas>1 금지.
    redishost: str = "192.168.0.8"
    redisport: int = 6379
    job_ttl_s: int = 3600                          # 잡 상태 보존(1h) — 폴링 후 자연 소멸

    # Gemini Vision (유료예외 — AGENTS.md 재승인 문서화 대상)
    # ⚠️ 챗봇과 **별도 키**를 쓴다(서비스별 .env로 분리). 같은 키로도 동작하지만, OCR(비전·장당
    #    과금)과 챗봇(refine) 비용을 **서비스 단위로 명확히 구분·추적**하려 키를 분리한다 — 사용량·
    #    청구를 각각 독립 모니터링/상한 관리 가능(유료예외 거버넌스에 부합). 값은 신규 발급 키.
    gemini_api_key: str = ""
    # ── Gemini 백엔드 (docs/gcp-migration-plan.md §3.1) ──────────────────────
    # api_key(기본) = 개인 키 직접 호출 · vertex = 팀 GCP Vertex AI(ADC 인증).
    # ⚠️ 현행 경로를 지우지 않는다 — Vertex 에서 문제가 나면 env 하나로 즉시 롤백한다.
    genai_backend: str = "api_key"
    # Vertex 모드에서만 사용. location 기본값을 두지 않는 이유 = 리전이 데이터 레지던시를
    # 결정하므로(영수증은 개인정보) 조용히 글로벌로 붙으면 안 된다.
    gcp_project_id: str = ""
    gcp_location: str = ""
    # 실물 13장 벤치마크(docs/ocr-model-benchmark.md): 이 lite가 성공률 92%·0.45원/장·2.8s로 최적.
    # ⚠️ 예전엔 `-latest` 별칭을 썼으나(3.5-flash-lite가 미출시라 별칭뿐이었음), 별칭이 3.x 세대로
    #    롤링되며 OCR 전량 실패(400)를 유발 → **특정 버전 핀 고정**으로 전환. 이제 `gemini-3.5-flash-lite`가
    #    정식 출시돼 명시 지정 가능(실서버 검증). 핀이라 갑작스런 세대 교체는 막힘. 언젠가 이 버전이
    #    폐기되면 404로 즉시 드러나므로 그때 버전만 올리면 됨(env override로도 교체 가능).
    gemini_model: str = "gemini-3.5-flash-lite"      # thinking 예산은 gemini_thinking_budget 병행
    # thinking 예산: 0=완전 끄기, 양수=상한 토큰, -1=동적(모델 자율).
    # ⚠️ 3.x flash-lite는 **0(끄기)을 400 INVALID_ARGUMENT로 거부**한다(구 2.5 lite에선 허용).
    #    대신 하한 미만의 작은 양수(1)를 주면 추론 단계를 건너뛰어 **thinking 토큰 0** = 구 tb=0과 동일 동작
    #    (실측: tb=1·32·128 모두 thinking 0 / tb=-1은 단순추출에도 288토큰 소모 → 비용 손해라 미채택).
    #    OCR은 추출작업이라 추론 불필요(벤치 92%가 추론 off 기준) → 기본 1로 사실상 끄기 유지.
    #    혹시 값이 거부돼도 vision.py가 thinking_config를 빼고 1회 재시도(_is_bad_argument 폴백)해 서비스 유지.
    gemini_thinking_budget: int = 1
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
