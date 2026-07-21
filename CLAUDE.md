# CLAUDE.md — food-budget-app (월 식비 예산 기반 밀플래닝)

작업 전 필독. **설계 정본 = `docs/design.md`** (소스오브트루스, 재파생 금지).

## 프로젝트
월 식비 예산 기반 밀플래닝 앱. 레시피 재료 추출 → 마켓컬리 현재가 비교 → 예산 계획·추적.
AI 해커톤 + 인프라 캡스톤 겸용 (5인, 8-9주).

## 절대 제약
- **AI 전부 CPU** (GTX 1060 3GB → GPU 학습 불가). CRF/XGBoost/LightGBM만. *(예외: YouTube 영상 추출은 외부 Gemini API — AGENTS.md 절대제약 3 예외 참조)*
- **학생 예산** — GPU 인스턴스 금지, AWS Spot+셀프호스트.
- **데이터** — 공공 오픈데이터/공식 API + **교육용 비상업 크롤링 허용** (마켓컬리·오아시스마켓 신선+가공, 만개의레시피).
  단, 비상업 목적·비공개 전제. *(쿠팡 크롤은 robots+Akamai 블로커로 보류 → 마켓컬리로 대체, design.md §3·§8)*

## 기술 스택 (확정)
**단일 언어(Python): FastAPI API + ML + 데이터 파이프라인.**
PG(OLTP + 경량 가격 이력) + Elasticsearch(레시피+상품 검색) + Redis. *(ClickHouse 드롭 — 고볼륨 시계열 승격 시 재도입)*
Kafka(Strimzi) + KEDA. kubeadm on AWS, Terraform, GitHub Actions+ECR+ArgoCD.
프론트=React/Vite/PWA. → 상세 §6

## 인프라 (IaC) — SSOT = `docs/infra-status.md`

**현행 인프라 상태·세부의 단일 소스 = `docs/infra-status.md`** (팀 공유: Proxmox 호스트·4-VM·데이터티어·접근·IaC·로드맵·이슈). **인프라 변경 시 거기 갱신.** *(§기술스택의 kubeadm/AWS/ArgoCD는 향후 목표 — 현행은 온프렘 Proxmox + Docker compose.)*
- **현행 배포**: Proxmox(`192.168.0.12`) + 4-VM: `fb-data`(.8 PG·ES·Redis·Kafka) · `fb-app-ai`(.9 FastAPI 8+ML) · `fb-ci-harbor`(.10 Harbor·러너) · `fb-monitoring`(.11 LGTM). Ubuntu 24.04.
- **Terraform** = `infra/terraform/` — Proxmox VM 프로비저닝(`bpg/proxmox` · 템플릿 9001 클론). **state = PG 원격 backend**(fb-data `terraform_state` DB, 공유·잠금). `terraform init -backend-config=backend.conf && terraform plan/apply`. 비밀 = `credentials.env`·`backend.conf`(**gitignored**).
- **Ansible** = `infra/ansible/` — 공통설정 + 서비스 배포(**멱등**). `site.yml`(전체) · `inventory.ini`(4-VM `all` 그룹) · remote_user=`ubuntu`·become. roles: `base`·`tfstate_db`·`data_tier`·`monitoring`(+`monitoring_agents`)·`harbor`·`github_runner`·`ca_trust`·`cd_deploy_key`·`data_pipeline`·`team_ssh_keys`. `ansible all -m ping && ansible-playbook site.yml`(특정 롤: `--tags <name>`).
- **팀 SSH 키 추가**: 공개키를 `infra/ansible/roles/team_ssh_keys/files/<이름>.pub`에 넣고 `ansible-playbook site.yml --tags team_keys` (**additive** — 기존 키 보존·잠금방지, 멱등).
- **비밀(전부 gitignored)**: `ansible/secrets.yml` · `terraform/credentials.env`·`backend.conf` · `infra/certs/*.key`(로컬 CA). **접근**: `ssh ubuntu@192.168.0.{8,9,10,11}` · Harbor `https://.10` · Grafana `https://.11:3000`(로컬 CA HTTPS, `infra/certs/ca.crt` 신뢰) · Proxmox `https://.12:8006`.

## 스키마·서비스 정본 (SSOT — 2026-07-15 확정)
- **앱 OLTP 스키마 = `docs/prd/schema-production.md`** (적용 DDL `docs/prd/schema-production.sql`). ⚠️ `schema-app-oltp.md`는 참고 초안(superseded — **수정 X**). 데이터 티어 = `docs/prd/schema-public-data.sql`.
- **구조**: 스키마-퍼-서비스 하이브리드(단일 PG·role 격리·`data` 공유 읽기). FK 정책 — 크로스-서비스=논리 `bigint`값(JWT 신뢰) / 같은 스키마=진짜 FK / `data`=진짜 FK. 크로스-서비스 데이터는 **DB 조인 말고 API 호출**.
- **백엔드 서비스 코드 컨벤션 = `services/CONVENTIONS.md`**, 정본 레퍼런스 = **`services/account/`** (AppCtx 주입 seam · raw psycopg · DB-free 테스트).
- **도메인 용어집 = `CONTEXT.md`** (표준 품목·Gazetteer·소비기한·레시피북). 용어: ~~유통기한~~ → **소비기한**(2023 개정, docs 정렬 완료).
- **DB 접근 = psycopg3 + `row_factory=dict_row`** (2026-07-15 결정, ORM/Alembic 미사용). 마이그레이션 = 멱등 DDL(`schema-production.sql`). ⚠️ 미정: 포트/compose SoT.
- **이미지 태깅 = 3태그** (2026-07-16 확정, PR #97): `:<sha>`(불변 신원) + `:X.Y.Z`(릴리스 핀·불변) + `:latest`(가변 편의). **버전 태그 `:X.Y.Z`는 릴리스 런(`workflow_dispatch`)에서만** 빌드·push — 자동 `main` push 는 `:<sha>`+`:latest`만(불변성 + 부분빌드 landmine 회피). 버전 SoT = 각 워크플로의 `APP_VERSION` env — **앱·파이프라인은 별개 트랙**(따로 올림): app=`build-push-app.yml`(현재 `1.1.1`) / 파이프라인=`build-push-pipeline.yml`(현재 `1.1.7`). 내부 semver: **MAJOR**=마이그레이션급·계약파괴 / **MINOR**=하위호환 기능 / **PATCH**=버그픽스·설정. compose 기본값 = `${IMAGE_TAG:-…}` — 파이프라인=루트 `docker-compose.yml` → 릴리스 핀 `1.1.7` / **app=`deploy/app/docker-compose.yml` → `latest`**(앱 트랙은 릴리스 런을 아직 안 돌려 실배포가 `:latest` — 옛 핀을 기본값으로 두면 수동 `compose up` 시 전 서비스 조용히 롤백. 릴리스 컷 도입 시 `APP_VERSION`·`.9:.env`·이 기본값을 함께 올릴 것). 배포 핀 = app 자동 push `:latest`·릴리스 `:APP_VERSION` / 파이프라인은 CD 없음 → fb-data operator 가 `IMAGE_TAG` 지정(기본 = 릴리스 핀).

## 커스텀 AI (ChatGPT-moat, 전부 CPU)
- P0: 한식 재료 NER(CRF) · 최저가 알림(통계 이상탐지, ⚠️ baseline 4주→오탐↑)
- P1: 신선도 예측(XGBoost) · 레시피 랭킹(LightGBM)
- P2: 챗봇(의도분류+템플릿)
- 영양소 분석 = DB 룩업 (AI 아님)
- ~~드롭~~: 할인 주기 예측(LightGBM) — 8주로 할인 사이클 부족(예측 불가)

## 데이터소스
- 마켓컬리 (신선+가공, 현재가+경량 이력, 핵심 SKU 정기 폴링 일1~2회 + 롱테일 온디맨드) ⚠️ robots·ToS 회색지대
- 오아시스마켓 (신선+가공, 판매가+경량 이력, 카테고리 폴링 가격 일1~2회 + 딜 15/17시 + 롱테일 온디맨드) ⚠️ robots·ToS 회색지대
- 만개의레시피 크롤링 (레시피 DB, 주 1회)
- YouTube Data API + Gemini (유저 URL → 멀티모달 추출 → CRF NER, 온디맨드 · 유료 API 예외 승인)
- 유저 영수증 OCR (냉장고 재고 + 캘린더 식비)
- ⏸ 보류: 쿠팡 크롤 (robots+Akamai 블로커 → 마켓컬리로 대체)
- ❌ 드롭: 지마켓 타임딜(Cloudflare 차단 → 오아시스 타임/마감세일로 대체, design.md §3.3), 냉장고를부탁해(공식 구조화 0건 → 레시피=만개의레시피 단일, design.md §3.3), 도매시장 경락가, KAMIS, 식약처 COOKRCP01, 기상청, 온라인가격, 할인 예측·엥겔지수, ClickHouse(고볼륨 승격 시 재도입)

## 멘토 피드백 (2026-07 멘토링 지적사항)
- **정량적 데이터 근거 보강** — DAU·트래픽 추정치·저장량 등 숫자 기반 설계 필요
- **다자간(multi-party) 트래픽** — 최저가 알림 fan-out(마켓컬리 통제 소스) + 레시피북 공유
- **예측 가능한 트래픽 스파이크** — 일일 피크타임 (11-12시, 17-18시) 메인 / 명절 보조

## 작업 규칙 (중요)
- **문서 수정 전 물어보고, 확정된 것만 기록.** 내 추천을 결정처럼 쓰지 말 것.
- 학습 목적: 손으로 이해하며 — 완성품 덤프 X, 조각내 설명 먼저.
- 설계 결정: 숫자+근거로 종이 위에서. 실인프라 테스트 제안 X.

## 미정 (사용자 결정 대기 — 임의로 정하지 말 것)
- CNI + 서비스 메쉬 (Cilium 유력, 보류)
- Gateway API 구현체 (Cilium Gateway / Envoy Gateway / Traefik — CNI에 연동)
- 5인 역할분담 + 9주 타임라인

## Agent skills

### Issue tracker

Issues live in GitHub Issues on `happyInit/food-budget-app` via the `gh` CLI; external PRs are **not** a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary — `needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
