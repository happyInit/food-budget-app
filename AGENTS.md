# AGENTS.md — food-budget-app

이 파일은 AI 코딩 에이전트(Claude Code, Copilot, Cursor 등)를 위한 프로젝트 컨텍스트.

> 최신화 2026-07-13 — design.md §3(소스)·§4(AI)·§5(서비스)·§6/§8(스택·배포) 반영.

## 프로젝트
월 식비 예산 기반 밀플래닝 앱. 20~30대 1인 가구 대상.
핵심 루프: 레시피 재료 추출(NER) → 마켓컬리·오아시스 가격 비교(ES) → 예산 계획·추적.

## 설계 정본
`docs/design.md`가 SSOT. 설계 결정은 이 문서에서 확인.
코드·인프라·문서는 design.md에서 파생 — 충돌 시 design.md가 우선.

## 기술 스택 (design §6.1)
- **언어:** Python 단일 (백엔드 + ML + 파이프라인)
- **API:** FastAPI (모든 서비스) · Pydantic v2 · SQLAlchemy+Alembic · PyJWT · confluent-kafka
- **DB:** PostgreSQL(OLTP + 경량 가격 이력) · Elasticsearch(레시피+상품 검색, nori) · Redis(현재가·추출 캐시)
  *(ClickHouse 드롭 — 고볼륨 시계열 승격 시 재도입, design §6.1·§10)*
- **메시징:** Kafka — 현재 Docker(VM1 상주), Strimzi는 K8s 이전 시 목표
- **프론트:** React + Vite + TypeScript, PWA (TanStack Query·Zustand·Tailwind)
- **ML:** CRF(sklearn-crfsuite)·XGBoost·LightGBM·FastText(챗봇 의도분류) — 전부 CPU 전용
- **배포 — 현재 베이스라인 (design §8.4):** Docker Compose · 온프렘 Proxmox 4-VM 셀프호스트 ·
  **Harbor** 레지스트리(`192.168.0.10/food-budget`) · GitHub Actions self-hosted 러너(`fb-ci`) CI
- **배포 — 목표/조건부 (design §6.1·§8.4):** kubeadm K8s(Strimzi·HPA+KEDA·ArgoCD) +
  AWS(EC2·Karpenter·ECR)·Terraform — 하이브리드 이전은 향후 확정

## MSA 서비스 (7개, design §5)
Gateway / User / Pantry / Recipe / Price / MealPlan / ML Serving

## 절대 제약 — 코드 작성 시 반드시 준수
1. **GPU 사용 금지** — PyTorch, TensorFlow, CUDA 의존 코드 작성 불가. CPU 전용 ML만.
2. **비상업 크롤링** — 마켓컬리·오아시스마켓(신선+가공), 만개의레시피만 허용. 다른 상업 사이트 크롤링 코드 작성 금지.
   *(쿠팡=보류(robots+Akamai 차단) · 지마켓 타임딜=드롭(Cloudflare → 오아시스 딜로 대체) · 냉장고를부탁해=드롭(만개 단일) → design §3.2·§3.3)*
3. **학생 예산** — GPU 인스턴스, 유료 SaaS API (OpenAI 등) 호출 코드 금지.
   - **예외 (2026-07-09 승인):** 유저 온디맨드 **YouTube 영상→레시피 추출**(P1)에 한해 외부 멀티모달 LLM API(**Gemini**) 호출 허용. 온디맨드·유저 트리거·**비용 상한 관리 전제**. 상세 `docs/video-recipe-ai.md`. 그 외 상시 경로엔 유료 API 금지.
   - **예외 확대 (2026-07-18, 잠정 — 서비스 정확도 우선):** 정확도 확보 목적으로 Gemini를 아래 경로에 추가 사용. **정식 팀 재승인 대기 + AWS 이관 시 FinOps 비용 검토 필수**(승인 전 잠정 운영).
     - **챗봇 생성** — `GENERATOR_BACKEND=gemini`(prod 활성). 비용 가드 = cost-break(#155 — 월 예산 초과 시 template 자동 강등).
     - **영수증 OCR** — `OCR_BACKEND=vision`(Gemini Vision). 현재 키만 스테이징(ocr 이미지 미빌드로 미기동).
     - 결정로그 = design §4.1·§10, `ai-spec.md` §5·§7·§8.

## 코드 컨벤션
- Python: FastAPI + Pydantic v2, async 우선, SQLAlchemy 2.0 스타일
- 프론트: TypeScript strict, TanStack Query for 서버 상태, Zustand for 클라이언트 상태
- Docker: 멀티스테이지 빌드, 프론트는 nginx:alpine 정적 서빙
- 테스트: pytest (백엔드), Vitest (프론트)

## 디렉토리 구조 (목표 MSA)
```
food-budget-app/
├── docs/                      # 설계 정본 (design.md = SSOT)
├── services/                  # MSA 백엔드 서비스
│   ├── gateway/
│   ├── user-service/
│   ├── pantry-service/
│   ├── recipe-service/
│   ├── price-service/
│   ├── meal-plan-service/     # 캘린더 식비추적 + 성과지표(안 버린 재료)
│   └── ml-serving/
├── ml/                        # AI 모델 학습 코드
│   ├── ingredient-ner/        # [P0] CRF NER
│   ├── price-anomaly/         # [P0] 최저가 이상탐지 (z-score)
│   ├── freshness-predictor/   # [P1] XGBoost
│   ├── recipe-ranker/         # [P1] LightGBM
│   └── chatbot/               # [P2] 의도분류(FastText)+템플릿
├── data-pipeline/             # Kafka 크롤링/폴링 파이프라인
│   ├── crawlers/              # 만개의레시피 (주 1회 배치)   # 냉부=드롭
│   ├── pollers/               # 마켓컬리·오아시스 가격(일1~2회) · 오아시스 딜(15/17시)   # 쿠팡=보류·지마켓=드롭
│   └── kafka/                 # 토픽 설정, 스키마
├── frontend/                  # React/Vite/PWA
└── infra/                     # 인프라 코드
    ├── k8s/
    ├── terraform/
    └── docker/
```
> ⚠️ 위는 **목표** 구조. **현재 구현된 실제 레이아웃**: `crawler/`(oasis·kurly·10k_recipe) · `pipelines/`(ingest·stream) · `deploy/`(Dockerfile·compose·폴러 cron·CI) · `docs/`. services/·ml/·frontend/·infra/는 아직 미구현.

## 데이터 흐름 요약
```
마켓컬리·오아시스 폴러 ──→ Kafka ──→ PG(경량 가격 이력) + ES(상품 인덱스) + Redis(현재가 캐시)
                                  └─→ 이상탐지 컨슈머 ──→ 최저가 알림 fan-out (KEDA)
만개의레시피 크롤러  ──→ Kafka ──→ NER ──→ ES (레시피 인덱스)
오아시스 딜(15/17시) ──→ Kafka ──→ PG + Redis (딜/핫딜 알림)
YouTube URL (유저)  ──→ 사전필터+캐시 ──→ Gemini 추출 ──→ CRF NER ──→ ES + PG (레시피북)
영수증 (유저)       ──→ OCR ──→ PG (냉장고 재고 + 캘린더)
```

## 작업 시 주의
- 설계 문서 수정 전 반드시 사용자 확인. 확정된 사항만 기록.
- 미정 항목(CNI, Gateway API 구현체, 역할분담)을 임의로 결정하지 말 것.
- 완성된 코드를 통째로 생성하지 말 것 — 조각내서 설명하며 진행.
