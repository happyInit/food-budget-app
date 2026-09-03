# CLAUDE.md — food-budget-app (월 식비 예산 기반 밀플래닝)

작업 전 필독. **설계 정본 = `docs/design.md`** (소스오브트루스, 재파생 금지).
⚠️ 단 **인프라 부분(`design.md §8.4` 온프렘·하이브리드)은 superseded** — 인프라는 아래 §인프라의 SSOT 를 따른다.

## 🔴 현재 형상 = Lightsail 1대 (2026-09-02 · AWS 전면 철거 완료)

**프로젝트는 끝났고, 지금 살아 있는 것은 포트폴리오 시연용 단일 호스트뿐이다.**

```
사용자 → Cloudflare (app.mealbong.cloud, 주황)
          └→ Cloudflare Tunnel `mp-portfolio`
              └→ nginx(frontend) → 앱 11종
                                    └→ PostgreSQL · Elasticsearch(nori) · Redis
```

| | 값 |
|---|---|
| 호스트 | **Lightsail `mp-portfolio`** · `medium_3_0`(2 vCPU / 4 GiB / 80 GiB) · `3.38.8.131` · ap-northeast-2a |
| 배포 | **Docker Compose 15 컨테이너** — `deploy/portfolio/docker-compose.yml` |
| 진입 | `app.mealbong.cloud` (인바운드 포트 0 — 터널이 아웃바운드로 붙는다) |
| 첫 화면 | 랜딩 → **「체험해보기」** = 게스트 세션 예열 후 `/home` (가입·로그인 불필요) |
| 데이터 | PG 43테이블 · 레시피 10,051 · 소매가 315,341 · ES `recipes_live` 10,051(servable 6,637) |
| 비용 | **월 약 $24** (철거 전 $690) |

### 🔴 없는 것 — 아래 문서를 읽고 "그러니까 이걸 쓰자"로 가면 안 된다

**EKS · ECR · ALB · WAF · NAT · ElastiCache · GuardDuty · CloudTrail 트레일 · Lambda · SQS ·
GitLab · ArgoCD · Karpenter · Istio · Prometheus/Loki/Tempo · 운영/FinOps 대시보드 — 전부 파괴됐다**
(2026-09-02, Terraform 4스택 279 리소스). **CI 도 없다** — 이미지는 박스에서 직접 빌드한다.

`docs/mp_aws_prep_checklist.md`(C-1~C-89) · `docs/mp_k8s_infra_status.md` ·
`docs/mp_aws_migration_plan.md` 는 **역사 기록으로만 유효하다.** 그 문서들이 서술하는
인프라는 실재하지 않는다. 설계 근거·의사결정 이력을 찾을 때만 읽고, **현행 판단의 출발점으로
쓰지 말 것.**

### 남겨 둔 AWS 자원 (이게 전부다)

| | 이유 |
|---|---|
| Lightsail `mp-portfolio` + 스냅샷 `mp-portfolio-20260902` | 서비스 본체 · 재해복구 |
| `s3://mp-backup-ap2` | **Lightsail 스택의 tfstate + 매일 백업 + 재구축 시드** — 지우면 안 된다 |
| `s3://mp-cloudtrail-ap2` | Object Lock **COMPLIANCE**라 삭제 불가. 2026-11-16 이후 가능 |

### 온프렘의 현재 상태 — 🔴 아직 켜져 있지만 아무것도 서빙하지 않는다

`app.mealbong.cloud` 가 Lightsail 로 넘어가면서(2026-09-02) 온프렘 5노드 클러스터는
**유입이 0** 이 됐다. 크롤 CronJob 은 계속 돌지만 **S3 업로드는 실패한다** — 목적지
버킷 `mp-crawl-ap2` 와 그 IAM 키를 철거에서 지웠기 때문이다. 처분은 **미정**(사용자 보류).

## 프로젝트
월 식비 예산 기반 밀플래닝 앱. 레시피 재료 추출 → 마켓컬리 현재가 비교 → 예산 계획·추적.
AI 해커톤 + 인프라 캡스톤 겸용 (5인, 8-9주).

## 절대 제약
- **AI 전부 CPU** (GTX 1060 3GB → GPU 학습 불가). CRF/XGBoost/LightGBM만. *(예외: YouTube 영상 추출은 외부 Gemini API — AGENTS.md 절대제약 3 예외 참조)*
- **학생 예산** — GPU 인스턴스 금지, 셀프호스트 우선.
  🔴 ~~AWS Spot~~ 은 **C-29 로 미채택**(2026-08-09). Blue-Green 은 promote 후 green 이 **프로덕션 그 자체**가 되고 파드가 이사하지 않아 "배포할 때만 Spot"이 성립하지 않고, 상시 Spot 도 **메모리의 10%에만 걸린다**(우리가 사는 건 CPU 가 아니라 메모리 — 실측 CPU 요청/실사용 9.4배 vs 메모리 1.1배).
- **데이터** — 공공 오픈데이터/공식 API + **교육용 비상업 크롤링 허용** (마켓컬리·오아시스마켓 신선+가공, 만개의레시피).
  단, 비상업 목적·비공개 전제. *(쿠팡 크롤은 robots+Akamai 블로커로 보류 → 마켓컬리로 대체, design.md §3·§8)*

## 기술 스택 (확정)
**단일 언어(Python): FastAPI API + ML + 데이터 파이프라인.**
PG(OLTP + 경량 가격 이력) + Elasticsearch(레시피+상품 검색) + Redis. *(ClickHouse 드롭 — 고볼륨 시계열 승격 시 재도입)*
프론트=React/Vite/PWA.
⛔ **Kafka(Strimzi)·KEDA·kubeadm·Jenkins·Harbor·ArgoCD 는 더 이상 돌지 않는다**(2026-09-02 철거).
   수집 파이프라인 코드(`pipelines/`·`crawler/`)는 **남겨 뒀지만 실행하지 않는다** — 데이터는 스냅샷 고정.
   현행 배포는 **Docker Compose 한 벌**이다(§운영).

## 명명 규칙 — 🔴 새로 만드는 것은 전부 `mp-` (`fb-` 금지)

**앞으로 생성하는 모든 이름은 `mp-` 접두사를 쓴다.** 대상 = 컨테이너·이미지·S3 버킷/프리픽스·볼륨·DB 롤·레포·브랜치 등 **이름을 새로 짓는 전부**.
🔴 **`fb-`(food-budget 시절 잔재)는 신규에 절대 쓰지 않는다** — 내가 임의로 `fb` 를 섞어 제안하는 것도 금지(예: ~~`mp-fb-backup`~~ → `mp-backup`).
- 예외 = **기존 실물 이름**(`fb-data`·`fb-app-ai`·`fb-secrets` ns·`fb-local-ca`·`fb-kubernetes` SecretStore 등)은 **그대로 참조**한다. 리네임은 별건이고, 참조를 깨뜨리면 배포가 죽는다.
- Compose 서비스명은 bare 다(`account`·`recipe`…) — 컨테이너 이름은 프로젝트명 `mealplanning` 이 앞에 붙는다.

## 운영 — 박스 하나에 SSH

```bash
ssh mp-portfolio                                  # ~/.ssh/config 별칭 (키 = ~/.ssh/mp-lightsail.pem)
ssh mp-portfolio 'cd ~/app/deploy/portfolio && sudo docker compose ps'
ssh mp-portfolio 'cd ~/app/deploy/portfolio && sudo docker compose logs --tail=100 recipe'
```

🔴 **`kubectl` 은 이제 아무 데도 안 닿는다** — EKS 는 파괴됐고 온프렘은 이 노트북 LAN 밖이다.
🔴 **compose 명령은 `sudo` 가 필요하다**(ubuntu 가 docker 그룹에 없다).
🔵 코드는 `~/app`(GitHub 클론) · 스택은 `~/app/deploy/portfolio` · systemd 유닛 `mealplanning.service`.

### 배포 — CI 가 없다. 박스에서 직접 빌드한다

```bash
# 로컬에서 편집 → 커밋 → GitHub 로 push
git push github <브랜치>

# 박스에서 당겨서 다시 빌드
ssh mp-portfolio 'cd ~/app && git fetch -q origin <브랜치> && git merge --ff-only FETCH_HEAD'
ssh mp-portfolio 'cd ~/app/deploy/portfolio && sudo docker compose build <서비스> && sudo docker compose up -d <서비스>'
```

🔴 **`origin` 이 레포마다 다르다.** 이 노트북의 `origin` 은 **파괴된 GitLab**을 가리키므로
   `git push origin` 은 실패한다 — **`git push github`** 를 쓴다. 박스의 `origin` 은 GitHub 이다.
🔴 **전체 빌드는 30~40분**(2 vCPU). 단건은 1~3분. 프론트만 고쳤으면 `frontend` 만 빌드한다.
🔴 **프론트 OAuth 키는 빌드타임에 번들로 박힌다**(`VITE_*`). `.env` 없이 빌드하면
   **빌드는 성공하고 런타임에 소셜 로그인만 조용히 깨진다.** 과거에 겪은 함정이다.

### 테스트 — 컨테이너 안에서 돌린다

로컬에 pytest 가 없다. 배포 이미지가 곧 실행 환경이므로 거기서 돈다:

```bash
tar cf - services/<svc> ml/ | ssh mp-portfolio 'cat > /tmp/t.tar'
ssh mp-portfolio 'cd /tmp && rm -rf t && mkdir t && tar xf t.tar -C t &&
  sudo docker run --rm -v /tmp/t:/repo -w /repo/services/<svc> mealplanning-<svc>:latest \
    sh -c "python -m pytest tests/ -q"'
```

🔴 **레포 루트 구조를 마운트해야 한다** — `services/<svc>` 만 올리면 `ml/` 을 참조하는
   테스트가 `IndexError` 로 죽고, 그게 "코드가 깨진 것"으로 오독된다(2026-09-02 실제 오진).

### 백업 — 매일 04:15 KST · **복원 검증 완료**

`deploy/portfolio/backup.sh` (ubuntu crontab) → `s3://mp-backup-ap2/portfolio-backup/`.
자격증명 = IAM 사용자 `mp-portfolio-backup`(스코프 = 그 프리픽스 PutObject) · `.env`(600).

🟢 **2026-09-02 실제로 복원해 대조했다** — 격리 PG 에 부어 스키마 9 · 테이블 43 ·
   레시피 10,051 · 소매가 315,341 · 유저 1,254 가 **운영본과 완전 일치**. 덤프는 살아 있다.
🔴 덤프가 1MB 미만이면 스크립트가 업로드를 **중단**한다 — 빈 덤프로 좋은 백업을 덮지 않으려는 것.
🔴 재해복구는 **Lightsail 스냅샷**(`mp-portfolio-20260902`)이 빠르다. 덤프는 데이터만 되돌린다.

### 인프라 코드

`infra/terraform/mp-portfolio/` — Lightsail 인스턴스·고정IP·방화벽·백업 IAM (6 리소스).
state = `s3://mp-backup-ap2/tfstate/portfolio.tfstate`. 프로필 = `mp-platform`.

```bash
cd infra/terraform/mp-portfolio && ~/projects/.tfbin/terraform plan
```

⛔ **`infra/terraform/{aws,aws-ai,aws-platform,mp-dashboard}` 는 전부 빈 state 다.**
   코드는 이력·학습용으로 남겨 뒀다. `apply` 하면 파괴한 인프라가 되살아나며 과금이 재개된다.
⛔ `infra/ansible/` 도 마찬가지 — 대상 호스트(온프렘·호스트 C)는 이 노트북에서 안 닿는다.

## 스키마·서비스 정본 (SSOT — 2026-07-15 확정)
- **앱 OLTP 스키마 = `docs/prd/schema-production.md`** (적용 DDL `docs/prd/schema-production.sql`). ⚠️ `schema-app-oltp.md`는 참고 초안(superseded — **수정 X**). 데이터 티어 = `docs/prd/schema-public-data.sql`.
- **구조**: 스키마-퍼-서비스 하이브리드(단일 PG·role 격리·`data` 공유 읽기). FK 정책 — 크로스-서비스=논리 `bigint`값(JWT 신뢰) / 같은 스키마=진짜 FK / `data`=진짜 FK. 크로스-서비스 데이터는 **DB 조인 말고 API 호출**.
- **백엔드 서비스 코드 컨벤션 = `services/CONVENTIONS.md`**, 정본 레퍼런스 = **`services/account/`** (AppCtx 주입 seam · raw psycopg · DB-free 테스트).
- **도메인 용어집 = `CONTEXT.md`** (표준 품목·Gazetteer·소비기한·레시피북). 용어: ~~유통기한~~ → **소비기한**(2023 개정, docs 정렬 완료).
- **DB 접근 = psycopg3 + `row_factory=dict_row`** (2026-07-15 결정, ORM/Alembic 미사용). 마이그레이션 = 멱등 DDL(`schema-production.sql`). *(K8s 이전 후 CNPG 가 운용 — `docs/mp_k8s_infra_status.md §2.1`)*
- **이미지 태깅 = 3태그** (2026-07-16 확정, PR #97): `:<sha>`(불변 신원) + `:X.Y.Z`(릴리스 핀·불변) + `:latest`(가변 편의). **버전 태그 `:X.Y.Z`는 릴리스 런에서만** 빌드·push — 자동 `main` push 는 `:<sha>`+`:latest`만(불변성 + 부분빌드 landmine 회피). **앱·파이프라인은 별개 버전 트랙**(따로 올림). 내부 semver: **MAJOR**=마이그레이션급·계약파괴 / **MINOR**=하위호환 기능 / **PATCH**=버그픽스·설정.
  - ⛔ **이 정책은 이제 적용 대상이 없다.** 레지스트리(ECR·Harbor)도 CI(Jenkins·GitLab)도 파괴됐고,
    이미지는 박스에서 `docker compose build` 로 만들어 **로컬 `mealplanning-<서비스>:latest` 하나로만 존재**한다.
    태그 전략·불변성 논의는 **레지스트리를 다시 둘 때** 되살린다. 근거는 `docs/mp_k8s_infra_migration_plan.md §7.3~7.4`.

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

- 🔴 **온프렘 처분** — 5노드 클러스터가 켜져 있으나 유입 0, 크롤 S3 업로드는 실패 중(§현재 형상).
  끌지·남길지 결정 대기(2026-09-02 사용자 보류).
- 🔴 **영상·OCR 유료 키의 Google 청구 상한** — 코드 상한은 걸었지만(`video_monthly_budget_won` 3,000원)
  그건 Redis 장애 시 통과하는 fail-open 층이다. **하드스톱은 콘솔에서 사람이 걸어야 한다.**
  ⚠️ OCR·video 는 **같은 키**를 쓰고 chat 은 별개 키다(2026-08-30 실측).

> ⛔ **아래 결정들은 인프라와 함께 소멸했다** — 재논의 대상이 아니라 **역사**다.
> Redis 오퍼레이터(OT-Container-Kit·Sentinel) · CNI(Cilium) · 서비스 메쉬(Istio) · Gateway API ·
> 외부 LB(MetalLB) · 부트스트랩(kubeadm) · 관측(kube-prometheus-stack) · CD(ArgoCD) ·
> ESO 백엔드 · 컷오버 순서(P0~P4) — 근거는 `docs/mp_k8s_infra_migration_plan.md` 에 남아 있다.
> 현행 Redis 는 **Compose 의 `redis:7-alpine` 단일 컨테이너**다(Sentinel 없음).

## Agent skills

### Issue tracker

Issues live in GitHub Issues on `happyInit/food-budget-app` via the `gh` CLI; external PRs are **not** a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary — `needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

`docs/adr/`는 존재하며 현재 `0001-deployment-strategy-canary.md`가 카나리 배포전략 결정을 기록한다.
그 밖의 기존 결정은 계속 각 영역 정본 문서에 인라인으로 있다 — 인프라 결정·근거는
`docs/mp_k8s_infra_migration_plan.md`(⛔ **역사 기록** — 그 인프라는 실재하지 않는다, §현재 형상).
새 ADR을 만들거나 상태를 바꿀 때는 `docs/agents/domain.md`의 규칙과 기존 ADR 번호를 먼저 확인한다.
