# AGENTS.md — food-budget-app

이 파일은 AI 코딩 에이전트(Claude Code, Copilot, Cursor 등)를 위한 프로젝트 컨텍스트.

## 프로젝트
월 식비 예산 기반 밀플래닝 앱. 20~30대 1인 가구 대상.
핵심 루프: 레시피 재료 추출(NER) → 쿠팡 가격 비교(ES) → 예산 계획·추적.

## 설계 정본
`docs/design.md`가 SSOT. 설계 결정은 이 문서에서 확인.
코드·인프라·문서는 design.md에서 파생 — 충돌 시 design.md가 우선.

## 기술 스택
- **언어:** Python 단일 (백엔드 + ML + 파이프라인)
- **API:** FastAPI (모든 서비스)
- **DB:** PostgreSQL(OLTP), ClickHouse(쿠팡 가격 시계열), Elasticsearch(레시피+상품 검색, nori), Redis(캐시)
- **메시징:** Kafka (Strimzi on K8s)
- **프론트:** React + Vite + TypeScript, PWA
- **ML:** CRF(sklearn-crfsuite), XGBoost, LightGBM — 전부 CPU 전용
- **인프라:** kubeadm K8s on AWS, Terraform, ArgoCD, GitHub Actions

## MSA 서비스 (7개)
Gateway / User / Pantry / Recipe / Price / MealPlan / ML Serving

## 절대 제약 — 코드 작성 시 반드시 준수
1. **GPU 사용 금지** — PyTorch, TensorFlow, CUDA 의존 코드 작성 불가. CPU 전용 ML만.
2. **비상업 크롤링** — 쿠팡·오아시스마켓(신선+가공), 만개의레시피만 허용. 다른 상업 사이트 크롤링 코드 작성 금지. *(지마켓 타임딜·냉장고를부탁해=드롭 → design.md §3.3. 지마켓은 오아시스 딜로 대체)*
3. **학생 예산** — GPU 인스턴스, 유료 SaaS API (OpenAI 등) 호출 코드 금지.
   - **예외 (2026-07-09 승인):** 유저 온디맨드 **YouTube 영상→레시피 추출**(#0, P1)에 한해 외부 멀티모달 LLM API(**Gemini**) 호출 허용. 온디맨드·유저 트리거·**비용 상한 관리 전제**. 상세 `docs/video-recipe-ai.md`. 그 외 상시 경로에는 유료 API 금지 유지.

## 코드 컨벤션
- Python: FastAPI + Pydantic v2, async 우선, SQLAlchemy 2.0 스타일
- 프론트: TypeScript strict, TanStack Query for 서버 상태, Zustand for 클라이언트 상태
- Docker: 멀티스테이지 빌드, 프론트는 nginx:alpine 정적 서빙
- 테스트: pytest (백엔드), Vitest (프론트)

## 디렉토리 구조
```
food-budget-app/
├── docs/                      # 설계 정본 (design.md = SSOT)
├── services/                  # MSA 백엔드 서비스
│   ├── gateway/
│   ├── user-service/
│   ├── pantry-service/
│   ├── recipe-service/
│   ├── price-service/
│   ├── meal-plan-service/     # 캘린더 + 엥겔지수 포함
│   └── ml-serving/
├── ml/                        # AI 모델 학습 코드
│   ├── ingredient-ner/        # [P0] CRF NER
│   ├── price-anomaly/         # [P0] 최저가 이상탐지
│   ├── freshness-predictor/   # [P1] XGBoost
│   ├── recipe-ranker/         # [P1] LightGBM
│   └── deal-cycle-predictor/  # [P1] 할인 주기 예측
├── data-pipeline/             # Kafka 크롤링/폴링 파이프라인
│   ├── crawlers/              # 만개의레시피 (주 1회 배치)  # 냉부=드롭(design §3.3)
│   ├── pollers/               # 쿠팡 (일 2회), 오아시스 타임/마감세일 (일 2회 15/17시)  # 지마켓 타임딜=드롭(Cloudflare)
│   └── kafka/                 # 토픽 설정, 스키마
├── frontend/                  # React/Vite/PWA
└── infra/                     # 인프라 코드
    ├── k8s/
    ├── terraform/
    └── docker/
```

## 데이터 흐름 요약
```
쿠팡 크롤러 ──→ Kafka ──→ ClickHouse (가격 이력) + ES (상품 인덱스)
만개의레시피 크롤러 ──→ Kafka ──→ NER ──→ ES (레시피 인덱스)
YouTube URL (유저) ──→ 사전필터+캐시 ──→ Gemini 추출 ──→ CRF NER ──→ ES + PG (레시피북)
영수증 (유저) ──→ OCR ──→ PG (냉장고 재고 + 캘린더)
오아시스 타임/마감세일 ──→ Kafka ──→ PG + Redis (딜/핫딜 알림)   # 지마켓 타임딜 드롭(Cloudflare) → 오아시스 대체
```

## 작업 시 주의
- 설계 문서 수정 전 반드시 사용자 확인. 확정된 사항만 기록.
- 미정 항목(CNI, Gateway API 구현체, 역할분담)을 임의로 결정하지 말 것.
- 완성된 코드를 통째로 생성하지 말 것 — 조각내서 설명하며 진행.
