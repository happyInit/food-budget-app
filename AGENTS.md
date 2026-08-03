# AGENTS.md — food-budget-app

이 파일은 AI 코딩 에이전트(Claude Code, Copilot, Cursor 등)를 위한 프로젝트 컨텍스트.

> 최신화 **2026-08-03** — PGSync CDC·레시피 검색의 안정 alias `recipes_live` 전환 중간 상태와
> config-first merge gate 반영(직전 전면 갱신 2026-07-31).
> 🔴 **이 문서와 `CLAUDE.md` 가 충돌하면 `CLAUDE.md` 가 맞다.** 여기는 그 요약·진입점이다.

## 프로젝트
월 식비 예산 기반 밀플래닝 앱. 20~30대 1인 가구 대상.
핵심 루프: 레시피 재료 추출(NER) → 마켓컬리·오아시스 가격 비교(ES) → 예산 계획·추적.
AI 해커톤 + 인프라 캡스톤 겸용 (5인, 8-9주).

## 정본(SSOT)은 하나가 아니라 영역별로 나뉜다

**"design.md 가 전부의 정본"이던 시절은 끝났다.** 영역마다 정본이 다르고, 엉뚱한 문서를 고치면 반영이 안 된다.

| 영역 | 정본 | 비고 |
|---|---|---|
| 제품·도메인·AI 설계 | `docs/design.md` | ⚠️ **단 §8.4(인프라)는 superseded** — 아래 인프라 행을 따른다 |
| **인프라 상태·운영·접속** | `docs/mp_k8s_infra_status.md` | 인프라를 바꾸면 **여기를 갱신**한다 |
| 인프라 결정·근거·컷오버(why/how) | `docs/mp_k8s_infra_migration_plan.md` | 결정을 바꿀 땐 여기서 바꾸고 status 로 반영 |
| **앱 OLTP 스키마** | `docs/prd/schema-production.md` (DDL `…-production.sql`) | ⚠️ `schema-app-oltp.md` 는 참고 초안 — **수정 금지** |
| 백엔드 코드 컨벤션 | `services/CONVENTIONS.md` | 레퍼런스 구현 = `services/account/` |
| 도메인 용어집 | `CONTEXT.md` | 표준 품목·Gazetteer·소비기한·레시피북 |

## 기술 스택
- **언어:** Python 단일 (백엔드 + ML + 파이프라인)
- **API:** FastAPI · Pydantic v2 · PyJWT · confluent-kafka
- **DB 접근:** 🔴 **psycopg3 + `row_factory=dict_row`** (2026-07-15 결정). **ORM·Alembic 미사용** — SQLAlchemy 를 새로 들이지 말 것. 마이그레이션 = 멱등 DDL(`schema-production.sql`), 운용은 CNPG.
- **DB:** PostgreSQL(OLTP + 경량 가격 이력) · Elasticsearch(레시피+상품 검색, nori) · Redis(현재가·추출 캐시)
  *(ClickHouse 드롭 — 고볼륨 시계열 승격 시 재도입)*
- **메시징:** Kafka — **Strimzi(RF=3) 인클러스터 가동 중** + KEDA(컨슈머 scale-to-zero)
- **프론트:** React + Vite + TypeScript, PWA (TanStack Query·Zustand·Tailwind)
- **ML:** CRF(sklearn-crfsuite)·XGBoost·LightGBM — 전부 CPU 전용
  ⚠️ 챗봇 의도분류는 **현재 규칙 기반으로만 동작**한다 — FastText 는 미설치(컴파일 필요), sklearn 폴백도 이미지에 안 들어가 있어 학습 경로가 skip 된다(2026-07-31 확인). "FastText 로 돈다"고 전제하지 말 것.
- **배포(현행):** **kubeadm K8s 5노드**(호스트 A·B, Cilium·Istio·MetalLB·ArgoCD) + 클러스터 밖 **호스트 C `.10`**(Harbor·Jenkins·SonarQube). 레지스트리 = **Harbor `mealplanning/`**.
  **CI = Jenkins**(레포 루트 `Jenkinsfile`) → config 레포(`:sha` 핀) → **CD = ArgoCD 단독**.
  ~~GitHub Actions self-hosted 러너(`fb-ci`)~~ = **2026-07-27 은퇴**, Ansible `github_runner` 롤도 **2026-07-31 삭제**. `.github/workflows/` 는 이관 레퍼런스로 보존되나 전부 `runs-on: self-hosted` 라 **실행 불가**.
- **배포(향후 조건부):** AWS 하이브리드(EC2·Karpenter) — 이전 여부 미확정. **EKS 이식을 전제로 온프렘을 짓는다.**

## 백엔드 서비스 — 11개 (2026-07-31 실물 정본)

`services/` 아래 11개. **design.md §5 의 "7개(Gateway/User/…/ML Serving)" 목록은 낡았다** — 아래가 현실이다.

| 서비스 | 역할 |
|---|---|
| `account` | Auth(로그인·JWT 발급) + User(프로필·월 예산) |
| `pantry` | 냉장고 재고 CRUD + 소비기한 임박 조회 |
| `recipe` | 레시피 탐색·상세 (데이터 티어 읽기) |
| `recipebook` | 레시피 북마크(스크랩) |
| `price` | 현재가·이력·시세추천·핫딜 (데이터 티어 읽기) |
| `mealplan` | Cart(장바구니) + Expense(식비) + Recommend(추천) |
| `notify` | 알림함 — 목록 조회 + 읽음 처리 |
| `chat` | 챗봇 5단계 파이프라인(질문분석→병렬검색→컨텍스트조립→생성→응답조립) |
| `ocr` | 영수증 OCR (chat 과 동형 구조) |
| `operations` | 크로스-서비스 이상탐지 |
| `video` | YouTube 영상→레시피 추출. ⚠️ **빌드는 되지만 미배포** — config 레포에 매니페스트가 없다 |

- **`Gateway` 는 서비스가 아니다** — Istio Gateway API(`mp-gw-public-istio`, 공개 `.14` / 내부 `.15`)가 그 역할을 한다.
- **ML 서빙**은 `services/` 가 아니라 `ml/recipe-ranking` → 워크로드 `mp-ranking-serving`.
- 배포 실물(ns `app`) = 위 백엔드 10 + `mp-ranking-serving` + `mp-frontend` + 게이트웨이·터널.
- 🔴 **크로스-서비스 데이터는 DB 조인이 아니라 API 호출**로 가져온다(스키마-퍼-서비스 · role 격리).

## 절대 제약 — 코드 작성 시 반드시 준수
1. **GPU 사용 금지** — PyTorch, TensorFlow, CUDA 의존 코드 작성 불가. CPU 전용 ML만.
2. **비상업 크롤링** — 마켓컬리·오아시스마켓(신선+가공), 만개의레시피만 허용. 다른 상업 사이트 크롤링 코드 작성 금지.
   *(쿠팡=보류(robots+Akamai 차단) · 지마켓 타임딜=드롭(Cloudflare → 오아시스 딜로 대체) · 냉장고를부탁해=드롭(만개 단일) → design §3.2·§3.3)*
3. **학생 예산** — GPU 인스턴스, 유료 SaaS API (OpenAI 등) 호출 코드 금지.
   - **예외 (2026-07-09 승인):** 유저 온디맨드 **YouTube 영상→레시피 추출**(P1)에 한해 외부 멀티모달 LLM API(**Gemini**) 호출 허용. 온디맨드·유저 트리거·**비용 상한 관리 전제**. 상세 `docs/video-recipe-ai.md`. 그 외 상시 경로엔 유료 API 금지.
   - **예외 확대 (2026-07-18, 잠정 — 서비스 정확도 우선):** 정확도 확보 목적으로 Gemini를 아래 경로에 추가 사용. ~~정식 팀 재승인 대기 + AWS 이관 시 FinOps 비용 검토 필수(승인 전 잠정 운영).~~ ✅ **이 '잠정/재승인 대기'는 2026-07-30 AI 담당 결정으로 해소 — 아래 '확정' 참조.**
     - **챗봇 생성** — `GENERATOR_BACKEND=gemini`(prod 활성). 비용 가드 = cost-break(#155 — 월 예산 초과 시 template 자동 강등). *(→ 2026-07-28 `bedrock` nova-micro로 대체 확정, 아래 갱신·확정 참조)*
     - **영수증 OCR** — `OCR_BACKEND=vision`(Gemini Vision). 현재 키만 스테이징(ocr 이미지 미빌드로 미기동).
     - 결정로그 = design §4.1·§10, `ai-spec.md` §5·§7·§8.
   - **갱신 (2026-07-28, 실측 확정 — AWS 이관 반영):** 위 "AWS 이관 시 FinOps 비용 검토"를 **누적 ~1,750건 실측으로 이행**했다. 근거 `docs/ai-model-selection-final.md`.
     - **비용 주체 전환**: 아래 경로는 **개인 Gemini API 키 → 팀 AWS Bedrock 크레딧**으로 이관하므로 "학생 예산(개인 유료 SaaS)" 제약에서 **벗어난다**.
       - **챗봇 생성** — `GENERATOR_BACKEND=bedrock`, `apac.amazon.nova-micro-v1:0`(서울). 프로덕션 경로 20/20으로 Gemini와 **품질 동률**, 안전(환각) 25/25 동일 · 40% 저렴 · 2배 빠름 · 데이터 국내 처리.
       - **리뷰 감정분류 · 텍스트→구조화 추출**(신규) — 동일 모델.
     - **Gemini 모델 유지 → 🔴 GCP Vertex AI 호스팅 이전 확정**(Bedrock 이전은 기술적 불가지만, **개인 Google AI API 키 → 팀 GCP 프로젝트(Vertex)로 비용 주체 전환** = "개인 유료 SaaS" 제약 벗어남. 키리스 연동 `docs/hybrid-cloud-federation-plan.md` · 전환 `docs/gcp-migration-plan.md`·PR #387):
       - **영수증 OCR** — Bedrock 대안이 한국어 판독 실패(Nova 통짜 환각, claude-3-haiku 글자 오독). Gemini Vision 유지, **Vertex AI 호스팅**.
       - **영상→레시피 / 유튜브 분석** — Bedrock에 YouTube URL 입력 자체가 없음. Gemini 유지, **Vertex AI 호스팅**.
       - **OCR 티어7 품목분류** — 도메인 판단 태스크로 Bedrock 미달(20/25 < 25/25). Gemini(Vertex) 유지.
     - **비용 가드 유지**: cost-break(#155) 월 예산 강등은 Gemini(Vertex) 잔여 경로에 그대로 적용.
   - 🔴 **확정 (2026-07-30, AI 담당 결정 — 팀 재승인 불요):** 유료/외부 LLM 예외 경로의 **최종 승인 집합** = **① chat 생성 = AWS Bedrock `nova-micro`(서울) · ② 영수증 OCR = GCP Vertex AI(Gemini) · ③ 영상·유튜브 = GCP Vertex AI(Gemini) · ④ 리뷰 감정분류·구조화 = Bedrock `nova-micro`**. 비용 주체는 전부 **팀 크레딧/프로젝트**(AWS Bedrock 크레딧 · 팀 GCP 프로젝트)라 개인 유료 SaaS 제약을 벗어난다. 정본 = `docs/ai-features-roadmap.md`.

## 명명 규칙 — 🔴 새로 만드는 것은 전부 `mp-` (`fb-` 금지)
K8s 오브젝트·이미지·S3 버킷·VM·볼륨·DB 롤·레포·브랜치 등 **이름을 새로 짓는 전부**.
- **예외 = 기존 실물 이름**(`fb-data`·`fb-secrets` ns·`fb-local-ca`·`fb-ci-harbor` 등)은 **그대로 참조**한다. 참조를 깨뜨리면 배포가 죽는다.
- K8s 상세(= `Service` 는 bare `account`·`recipe`…, 그 외는 `mp-` 접두사) = `docs/mp_k8s_infra_status.md §2.3`.

## 코드 컨벤션
- Python: FastAPI + Pydantic v2, async 우선. **DB 는 raw psycopg3**(위 참조) — 레퍼런스 = `services/account/`, 규약 = `services/CONVENTIONS.md`(AppCtx 주입 seam · DB-free 테스트).
- 프론트: TypeScript strict, TanStack Query for 서버 상태, Zustand for 클라이언트 상태
- Docker: 멀티스테이지 빌드, 프론트는 nginx:alpine 정적 서빙
- 테스트: pytest (백엔드), Vitest (프론트)
- **이미지 태깅 = 3태그** — `:<sha>`(불변 신원) + `:X.Y.Z`(릴리스 런에서만) + `:latest`(가변 편의).
  🔴 **K8s/config 레포 핀은 반드시 `:sha`** — `:latest` 면 ArgoCD 가 변경을 감지 못 하고 롤백 경로가 사라진다.

## 실제 디렉토리 구조 (2026-07-31 실물)
```
food-budget-app/
├── docs/            # 설계 문서군 (design.md · mp_k8s_* · prd/ · agents/)
├── services/        # 백엔드 11개 (위 표) — account 가 컨벤션 레퍼런스
├── ml/              # ingredient-ner(CRF) · recipe-ranking(LightGBM) · chat-insights · video-recipe
├── pipelines/       # ingest(적재·이상탐지) · stream(Kafka 프로듀서/컨슈머) · common 성격 모듈
├── crawler/         # oasis · kurly · 10k_recipe
├── deploy/          # 루트 Dockerfile 보조 · pgsync(mp-pgsync 빌드 컨텍스트) · k8s(⚠️ stale 유물)
├── frontend/        # React/Vite/PWA
├── infra/           # ansible/ · terraform/ · certs/ · scripts/
└── reports/         # 산출물
```
- **K8s 매니페스트는 이 레포에 없다** — 별도 **config 레포 `happyInit/mealplanning-config`**(app-of-apps, ArgoCD).
- ⚠️ `deploy/README.md` 와 `deploy/k8s/` 는 **폐기·stale**(구 `.8` VM 시절). `deploy/pgsync/` 만 살아 있다.
- `ml/price-anomaly` 는 없다 — 이상탐지는 `pipelines/ingest/detect_price_anomaly.py`.

## 데이터 흐름 요약
```
마켓컬리·오아시스 폴러 ──→ Kafka ──→ PG(경량 가격 이력) + ES(상품 인덱스) + Redis(현재가 캐시)
                                  └─→ 이상탐지 컨슈머 ──→ 최저가 알림 fan-out (KEDA)
만개의레시피 크롤러  ──→ Kafka ──→ NER ──→ ES (레시피 인덱스)
오아시스 딜(15/17시) ──→ Kafka ──→ PG + Redis (딜/핫딜 알림)
YouTube URL (유저)  ──→ 사전필터+캐시 ──→ Gemini 추출 ──→ CRF NER ──→ ES + PG (레시피북)
영수증 (유저)       ──→ OCR ──→ PG (냉장고 재고 + 캘린더)
```
PG→ES 색인은 **PGSync CDC**가 안정 alias `recipes_live` 에 쓰고, 이 alias 가 현재 nori 매핑의 물리 인덱스
`recipes_v2` 를 가리킨다. 앱도 `ES_INDEX=recipes_live` 로 같은 alias 를 읽는다. 배치 `recipes` 는 축소된
DR 폴백이며 무손실 대체가 아니다. 인덱스 settings/mapping 정본은 config 레포
`ops/pgsync-stable-alias/recipes-index.json`이다. 🔴 alias 뒤의 물리 인덱스명을 앱·PGSync 설정에 직접 넣거나 앱 레포에
mapping 사본을 새로 만들지 말 것.
이 app 문서/schema 변경보다 config ops SSOT가 먼저 merge돼야 한다. 아직 기록되지 않은 config PR/commit은
`PENDING_AFTER_CONFIG_MERGE`이며, 그 SHA가 확정되기 전에 이 참조 변경을 merge하지 않는다.

## Agent skills
- **이슈 트래커** = GitHub Issues(`happyInit/food-budget-app`, `gh` CLI). 외부 PR 은 트리아지 대상이 아니다 → `docs/agents/issue-tracker.md`
- **트리아지 라벨** = `needs-triage`/`needs-info`/`ready-for-agent`/`ready-for-human`/`wontfix` → `docs/agents/triage-labels.md`
- **도메인 문서** = `CONTEXT.md` + `docs/adr/` → `docs/agents/domain.md`
  `docs/adr/`는 존재하며 현재 `0001-deployment-strategy-canary.md`가 카나리 배포전략 결정을 기록한다.
  그 밖의 기존 결정은 계속 **각 영역 정본 문서에 인라인**으로 있다 — 인프라 결정·근거 =
  `docs/mp_k8s_infra_migration_plan.md`, 해소된 결정 목록 = `CLAUDE.md §인프라` 하단 "✅ 해소됨".
  새 ADR을 만들거나 상태를 바꿀 때는 `docs/agents/domain.md`의 규칙과 기존 ADR 번호를 먼저 확인한다.

## 작업 시 주의
- **설계 문서 수정 전 반드시 사용자 확인. 확정된 사항만 기록.** 추천을 결정처럼 쓰지 말 것.
- **완성된 코드를 통째로 생성하지 말 것** — 조각내서 설명하며 진행(학습 목적).
- **PR 워크플로** — 2026-07-12부터 `main` 직접 커밋 금지. feature 브랜치 + PR.
- 🔴 **미정 항목을 임의로 결정하지 말 것.** 현재 남은 미정 = **5인 역할분담 + 9주 타임라인**.
  ⚠️ 반대로 **이미 해소된 것을 재논의하지 말 것** — CNI=**Cilium** · 서비스 메시=**Istio sidecar** · Gateway API 구현체=**Istio** · 외부 LB=**MetalLB** · 부트스트랩=**kubeadm 직접** · Redis 오퍼레이터=**OT-Container-Kit**. 근거는 `docs/mp_k8s_infra_migration_plan.md`.
- 용어: ~~유통기한~~ → **소비기한**(2023 개정).
