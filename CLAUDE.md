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
Kafka(Strimzi) + KEDA. **kubeadm(온프렘 → EKS 이식 전제), Terraform, Jenkins + Harbor + ArgoCD.**
프론트=React/Vite/PWA. → 상세 §6

## 인프라 (IaC) — SSOT = `docs/k8s-infra-status.md`

**인프라 상태·세부의 단일 소스 = `docs/k8s-infra-status.md`** (목표 아키텍처·구축 현황·사고기반 필수수칙). **인프라 변경 시 거기 갱신.**
이전 결정·근거·컷오버 절차(why/how) = **`docs/k8s-migration-plan.md`**.

> 🔴 **클러스터는 아직 존재하지 않는다** (선행조건 = 물리 호스트 B·C 미확보, 진행률 0%).
> **오늘의 운영·장애대응·접속은 `docs/docker-infra-status.md`** — 실가동 중인 Docker compose 스택은 그쪽이 레퍼런스다(SSOT 아님, 컷오버 P6 완료 시 폐기).

- **목표 토폴로지**: 물리 3대 — 클러스터용 A·B(kubeadm, master ×1 + worker ×4) + **호스트 C `.177`**(Harbor·Jenkins, 클러스터 밖).
- **네트워킹**: Cilium(eBPF·kube-proxy 대체·WireGuard) · MetalLB L2(풀 `.14`–`.16`) · Gateway API(구현체 Istio) · **Istio sidecar 메시**.
- **데이터 티어**: 전부 in-cluster·**전 컴포넌트 HA** — PG(CloudNativePG) · ES(ECK) · Redis(Sentinel) · Kafka(Strimzi RF=3). 스토리지 = OpenEBS LVM LocalPV(동적 프로비저닝, **RWX 금지**) · 오브젝트 = MinIO(내부) + S3(백업).
  *CNPG·ECK 의 "Cloud"는 cloud-native 를 뜻한다 — 클라우드 서비스가 아니라 우리 클러스터에 설치하는 오퍼레이터다. 매니지드로 갈아타지 않는다.*
- **CI/CD**: **Jenkins(CI, 호스트 C) → 별도 config 레포 → ArgoCD(CD)**. Jenkins 는 배포하지 않는다.
- **배치 원칙**: 급사 3회가 전부 호스트 A → **master·quorum 다수는 B**, **PG·Redis primary 는 A**.
- **Terraform** = `infra/terraform/` — Proxmox VM 프로비저닝(`bpg/proxmox` · 템플릿 9001 클론). **state = PG 원격 backend**(fb-data `terraform_state` DB, 공유·잠금). `terraform init -backend-config=backend.conf && terraform plan/apply`. 비밀 = `credentials.env`·`backend.conf`(**gitignored**).
- **Ansible** = `infra/ansible/` — 공통설정 + 서비스 배포(**멱등**). `site.yml`(**VM 4대 = `vms` 그룹**) · `hypervisor.yml`(**물리 `.12` 전용** — node-exporter 온도감시) · remote_user=`ubuntu`·become. roles: `base`·`tfstate_db`·`data_tier`·`monitoring`(+`monitoring_agents`)·`harbor`·`github_runner`·`ca_trust`·`cd_deploy_key`·`data_pipeline`·`team_ssh_keys`·`node_exporter_host`. `ansible vms -m ping && ansible-playbook site.yml`(특정 롤: `--tags <name>`).
  🔴 **site.yml 플레이는 `hosts: all` 이 아니라 `hosts: vms`** — `all` 은 인벤토리 전 호스트를 자동 포함해 하이퍼바이저까지 닿고, 그러면 `base` 롤이 `.12` 의 `/dev/sdb`(= 전 VM 스토리지 `pve` VG)를 docker 전용 디스크로 포맷 시도한다. 새 전-호스트 플레이를 추가할 때 `all` 로 쓰지 말 것(`base` 롤에 방어 assert 있음). 상세 = `docs/docker-infra-status.md §1.1`.
- **팀 SSH 키 추가**: 공개키를 `infra/ansible/roles/team_ssh_keys/files/<이름>.pub`에 넣고 `ansible-playbook site.yml --tags team_keys` (**additive** — 기존 키 보존·잠금방지, 멱등).
- **비밀(전부 gitignored)**: `ansible/secrets.yml` · `terraform/credentials.env`·`backend.conf` · `infra/certs/*.key`(로컬 CA).
- **접속 정보**(현행 실가동 VM·Harbor·Grafana·Proxmox) = `docs/docker-infra-status.md §4`. 클러스터 구축 후에는 `docs/k8s-infra-status.md` 로 이관한다.

## 스키마·서비스 정본 (SSOT — 2026-07-15 확정)
- **앱 OLTP 스키마 = `docs/prd/schema-production.md`** (적용 DDL `docs/prd/schema-production.sql`). ⚠️ `schema-app-oltp.md`는 참고 초안(superseded — **수정 X**). 데이터 티어 = `docs/prd/schema-public-data.sql`.
- **구조**: 스키마-퍼-서비스 하이브리드(단일 PG·role 격리·`data` 공유 읽기). FK 정책 — 크로스-서비스=논리 `bigint`값(JWT 신뢰) / 같은 스키마=진짜 FK / `data`=진짜 FK. 크로스-서비스 데이터는 **DB 조인 말고 API 호출**.
- **백엔드 서비스 코드 컨벤션 = `services/CONVENTIONS.md`**, 정본 레퍼런스 = **`services/account/`** (AppCtx 주입 seam · raw psycopg · DB-free 테스트).
- **도메인 용어집 = `CONTEXT.md`** (표준 품목·Gazetteer·소비기한·레시피북). 용어: ~~유통기한~~ → **소비기한**(2023 개정, docs 정렬 완료).
- **DB 접근 = psycopg3 + `row_factory=dict_row`** (2026-07-15 결정, ORM/Alembic 미사용). 마이그레이션 = 멱등 DDL(`schema-production.sql`). *(K8s 이전 후 CNPG 가 운용 — `docs/k8s-infra-status.md §2.1`)*
- **이미지 태깅 = 3태그** (2026-07-16 확정, PR #97): `:<sha>`(불변 신원) + `:X.Y.Z`(릴리스 핀·불변) + `:latest`(가변 편의). **버전 태그 `:X.Y.Z`는 릴리스 런에서만** 빌드·push — 자동 `main` push 는 `:<sha>`+`:latest`만(불변성 + 부분빌드 landmine 회피). **앱·파이프라인은 별개 버전 트랙**(따로 올림). 내부 semver: **MAJOR**=마이그레이션급·계약파괴 / **MINOR**=하위호환 기능 / **PATCH**=버그픽스·설정.
  - **이 정책은 CI 구현체와 무관하게 유지된다** — 현행 GitHub Actions 의 `APP_VERSION` env·compose 기본값 등 구현 세부와 현재 버전은 `docs/docker-infra-status.md`, Jenkins 이관 후 규칙은 `docs/k8s-migration-plan.md §7.4`.

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
