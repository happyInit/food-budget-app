# K8s 이전 계획 (집약)

> 🔵 **실행 정본은 [`k8s-migration-plan.md`](./k8s-migration-plan.md) 로 옮겨졌다** (2026-07-23 결정 확정 — 데이터 티어 in-cluster · Istio sidecar · OpenEBS 동적 프로비저닝 · EKS 이식성 감사 · 컷오버 P0~P6). **이 문서는 그 이전의 배경·출처 집약본으로 보존한다** — 아래 §7 선행 미결과 §8 갭 중 다수는 정본에서 해소됐다.
>
> **상태: ⬜ 향후 조건부 — 미착수.** 현행 배포 = Docker Compose 온프렘 Proxmox 4-VM.
> **이 문서는 정본이 아니라 집약본이다.** 각 항목의 정본은 출처 열에 표기했고, 내용 변경은 정본에서 하고 여기로 반영한다.
> 정본 계층: 토폴로지·스펙 = [`design.md §8.4`](./design.md) · 현행 인프라 상태 = [`infra-status.md`](./infra-status.md) · 백업/DR = [`backup-strategy.md §3`](./backup-strategy.md) · 단계별 검증 = [`resource-validation-plan.md §3`](./resource-validation-plan.md)
> 최초 작성: 2026-07-23 (기존 8개 문서에 흩어진 K8s 관련 기술을 모음. 새 결정 없음.)

---

## 0. 위치와 범위

| 항목 | 내용 | 출처 |
|---|---|---|
| 현행 | Docker(compose) 베이스라인, Proxmox 4-VM | `design.md §8.4` · `infra-status.md` |
| 로드맵 상 순위 | `future` / 상태 `⬜ 조건부` | `infra-status.md §6` |
| 단계 서사 | **Docker → K8s → AWS** (측정 → 실부하로 조이기 → 돈으로 조이기) | `resource-validation-plan.md` |
| 발표 프레이밍 | Docker·Proxmox·Harbor·GH Actions = **현 베이스라인** / K8s·AWS = **향후 데모·클라우드 티어** (구분해 발표) | `tech-stack.md` |
| 목표 스택 | kubeadm · FastAPI Gateway · HPA+KEDA · Strimzi · ArgoCD | `design.md §6.1` |

⚠️ **이전 트리거 조건은 정의된 바 없다.** 전 문서가 "조건부"라고만 쓰고 있고, *무엇이 충족되면 이전하는가*는 미결(§8-1).

---

## 1. 목표 토폴로지 — 하이브리드

**방향 확정**: PG/ES/Redis는 K8s **밖** 유지(안정·데이터 안전), Kafka·앱·AI·ArgoCD는 K8s **안**.
(`design.md §8.4` · `backup-strategy.md §3.1`)

```text
Kubernetes                        Kubernetes 외부 · fb-data VM
├─ Gateway · API · AI serving     ├─ PostgreSQL
├─ Kafka (Strimzi)                ├─ Elasticsearch
├─ KEDA · HPA                     └─ Redis
└─ ArgoCD
```

- 앱 → 외부 DB 접근 = **selector 없는 Service + 수동 Endpoints/EndpointSlice** 로 매핑. 이 경로는 데이터 계층 접근 **용도로만** 사용한다. (`design.md §8.4` · `backup-strategy.md §3.2`)
- K8s 애플리케이션은 가능한 한 **stateless** 로 운영한다. (`backup-strategy.md §3.1`)
- Kafka 는 Strimzi 이전 대상이나 **Kafka 데이터 보호 정책은 별도 결정 필요** — S3 가 Kafka persistent volume 을 대체하지 않는다. (`backup-strategy.md §3.1`, §8-3)
- ArgoCD 선언·앱 설정은 **Git 이 정본**. Git 에 둘 수 없는 Secret 의 암호화 사본만 S3 불변 보관소에 백업. (`backup-strategy.md §3.1`)
- 상태저장 서비스(PG 등)를 K8s 내부로 옮기는 안은 **현 범위 밖**. 변경 시 지연·IOPS·fsync 지원 블록 스토리지를 다시 선정해야 한다. (`backup-strategy.md §3.4`)

---

## 2. 리소스 영향 (스펙 변동 요인)

현 4-VM 스펙은 **Docker 기준 산정**이므로 이전 시 재배분이 필요하다. (`design.md §8.4`)

| 요인 | 영향 |
|---|---|
| K8s 오버헤드 | kubelet + CNI + 오퍼레이터 **~1.5~2GB/노드** |
| Kafka VM1 → VM2 (Strimzi) | VM1 RAM ↓ · VM2 RAM ↑ |
| ArgoCD 신규 | 추가 할당 |
| VM → K8s 노드 전환 | 전반 RAM 재배분 |

**단일노드 주의** — K8s 가 VM2 단일노드면 멀티노드 스케줄 데모가 제한된다. 워커 VM 추가 시 해소. (`design.md §8.4`)

**현 호스트 물리 한계** (참고): i7-10700F 8코어/16스레드 · 32GB(31GiB 가용) · 현 VM 할당 합계 26GB. (`design.md §8.4` · `infra-status.md §1`)

### 2.1 연동 결정 — SonarQube

**SonarQube(코드품질/SAST) 도입 = K8s 이전 시점으로 연기** (2026-07-15 결정). 단일호스트 RAM 여유 부족으로 현재 미도입. (`design.md §8.4`)

- 전제: 신규 **동일스펙 노드(i7-10700F/32GB) 1대 추가 → 2노드 클러스터** 후 배치
- 배치안(**미정**): Server = 여유노드 고정(벌룬 off)/StatefulSet + DB = 외부 PG(VM1) 재사용 · Scanner = CI(GH Actions) 스텝
- ⚠️ 이전 시 선행: 2노드 quorum witness(qdevice) · 노드 `vm.max_map_count=524288`

---

## 3. 스케일링 계획

K8s 단계의 목표 = **"실부하로 조이기"** — requests/limits 정밀화 + HPA/KEDA 튜닝 + 부하테스트. Docker 베이스라인 실측을 시작값으로 쓴다. (`resource-validation-plan.md §3`)

### 3.1 requests / limits

- **requests** = 관측된 평상 사용량(스케줄링 기준). 높으면 노드 낭비, 낮으면 과밀·경합
- **limits** = 피크 + 헤드룸. 메모리는 초과 시 OOMKill 이므로 여유 있게
- Docker 베이스라인 → 초기값 → 실부하 관측 → 조정 반복. (선택) VPA recommendation 모드로 권고치 참고
- compose 의 `cpus`/replica 가 K8s `resources.requests/limits` + HPA 로 매핑된다 (`design.md §8.5`)

### 3.2 티어별 오토스케일

| 티어 | 스케일 방식 | 튜닝 포인트 |
|---|---|---|
| 요청 서비스 (Gateway·User·Pantry·Recipe·Price·MealPlan·Expense·Notification) | **HPA** (CPU/RPS) | 목표 사용률 60~70%, min/max replica, 피크 대응 |
| 워커 (NER·이상탐지·OCR·추출) | **KEDA** (Kafka lag/큐) | 트리거 임계값, idle→0, 콜드스타트 |
| 수집 (크롤러·폴러) | **고정 1 replica** | 수평 확장 금지(크롤 예의·중복). CronJob / KEDA cron |
| AI 서빙 (ML Serving) | HPA (CPU) | CPU-bound, 병목 시 분리 검토 |
| 저장소 (PG·ES·Redis·Kafka) | 오토스케일 아님 | 하이브리드로 K8s 밖(§1). 읽기 복제·샤딩은 별도 |

### 3.3 부하 테스트

- 도구: k6 / Locust 등
- 재현할 프로파일 — 일일 피크(11-12·17-18시) 레시피 검색+가격 조회 집중(`design.md §8.1`) · 최저가 알림 fan-out 버스트(`design.md §8.2`)
- 관측: p50/p95/p99 지연, 에러율, HPA·KEDA 반응(scale-out 속도·scale-to-zero), 저장소 병목
- 결과로 requests/limits · HPA 임계값 · replica 범위를 확정

### 3.4 부하테스트 실측과의 연결 (2026-07-19)

nGrinder 실측 **~200 VUser 부근 포화**(응답 8~20s). VM CPU 는 여유(18%)였고 병목은 코드·설정 레벨 → 물질화 뷰 전환 + Redis 캐시로 1차 해소. (`design.md §8.5` · `perf-loadtest-fixes.md`)

다만 **잔여 포화의 근본 해법은 K8s 수평 확장**이라고 복수 문서가 명시한다:

- 컨테이너 `cpus` · 워커 수 · PG `max_connections` 상한이 포화의 1차 원인 → 근본 확장 = K8s 수평 (`design.md §8.5`)
- 수직 확장 여지는 작다. "진짜 스케일 = 수평 확장(K8s 이전 계획)" (`perf-infra-handoff.md §5`)
- account 를 **replica + HPA**(CPU/RPS 타깃)로 승격 → "부하테스트로 병목 발견 → HPA 로 해결" 서사 (`design.md §8.5`)

---

## 4. 백업 / DR

**S3 오프사이트 백업 도입 시점 = K8s 이전 단계.** 현 Compose 단계에서는 적용하지 않는다. (`backup-strategy.md` — 이전 관련 기술이 가장 상세한 문서)

### 4.1 원칙

- 백업 실행 주체는 **클러스터 밖** — `fb-data` VM 의 **systemd timer + Ansible**. K8s CronJob 이 아니다. *(이유: K8s 전체가 중단돼도 백업 경로가 유지돼야 함)*
- S3 는 PG 데이터 디렉터리나 K8s PVC 를 **대체하지 않는다**. 실행 데이터는 VM 블록 스토리지, S3 로는 백업 객체만 전송
- **K8s ServiceAccount 에 백업 bucket 쓰기 권한을 부여하지 않는다.** 앱 Pod 가 PG 백업 자격증명을 갖지 않도록 한다
- 향후 사용자 업로드 파일을 S3 에 둘 때는 백업 bucket 이 아닌 **별도 콘텐츠 bucket** + 제한된 presigned URL 정책

### 4.2 구성 (목표 — `backup-strategy.md §2.4`)

Amazon S3 서울 리전(`ap-northeast-2`), 목적이 다른 bucket 2개. 이름은 전역 고유여야 하므로 코드·문서에 고정하지 않고 `BACKUP_S3_REPO_BUCKET` / `BACKUP_S3_VAULT_BUCKET` 환경변수로 주입.

```text
fb-data systemd timer
├─ pgBackRest       → S3 repo bucket / postgres
├─ ES snapshot      → S3 repo bucket / elasticsearch
└─ dump·config·archive → S3 vault bucket
```

- ES: 매일 **14시·02시** snapshot, **14일 보존**, S3 Standard 유지(**Glacier 계열 전환 금지** — 도구 관리 repository 객체를 임의 이동·삭제하면 복구 저장소 손상)
- 장애 시 snapshot 복원 또는 PG 기반 재색인

### 4.3 복구 순서

1. Terraform·Ansible 로 VM·네트워크 복구
2. S3 의 pgBackRest backup + WAL 로 PostgreSQL 복구
3. S3 snapshot 으로 ES 복구 또는 PG 에서 재색인
4. Redis 재생성 + PGSync 상태 복구
5. **K8s 노드와 ArgoCD 복구 → 애플리케이션 재배포**
6. 로그인·예산·냉장고·레시피·가격비교 smoke test

---

## 5. 보안

| 항목 | 등급 | 내용 | 출처 |
|---|---|---|---|
| Secret 관리 | P1 | **K8s 전환 시 Sealed Secrets / External Secrets(Vault)** — 평문 Secret 리소스 지양 | `security-checklist.md §4` |
| VM 간 통신 | P0 | compose bridge 는 단일호스트 한정. VM 간을 하나의 가상 네트워크로 묶으려면 **Swarm overlay 또는 K8s CNI 로 승격** 필요 | `security-checklist.md §7` |
| 런타임 하드닝 | P0/P1 | 리소스 limit(적용됨) · `read_only: true` + tmpfs 등은 compose/K8s 공통 체크리스트 | `security-checklist.md §3` |

> 참고: 내부망 `vmbr1`(10.10.10.0/24)은 2026-07-20 4대 NIC 라이브지만 **add-only 단계** — 서비스 엔드포인트(~20개 파일)는 여전히 `192.168.0.x`. 내부망 이전은 K8s 이전과 별개 작업. (`infra-status.md §1`)

---

## 6. 이미 있는 산출물 (코드)

`deploy/k8s/` — **현재 미사용**, 후속 보존용. Docker 에 집중. (`deploy/README.md`)

| 파일 | 내용 |
|---|---|
| [`deploy/k8s/retail-ingest.yaml`](../deploy/k8s/retail-ingest.yaml) (222줄) | Strimzi KafkaTopic ×2 (`retail.crawl.raw` · `retail.deal.raw`) · CronJob ×4 (oasis·kurly·deal 폴러, deal-pruner) · Deployment ×2 (retail-refiner, deal-notifier) · **KEDA ScaledObject ×2** (Kafka lag, min 0) |
| [`deploy/k8s/recipe-ingest.yaml`](../deploy/k8s/recipe-ingest.yaml) (88줄) | KafkaTopic `recipe.crawl.raw` · recipe-poller CronJob(주1회, 일 18:00 UTC = 월 03:00 KST) · recipe-refiner |

**Docker ↔ K8s 대응 매핑** (`pipelines/stream/README.md` · `proposals/clickstream-consumer-retention-design.md`)

| Docker 현행 | K8s 대체 |
|---|---|
| `create_topics.py` (멱등 토픽 생성) | Strimzi `KafkaTopic` |
| cron 폴러 (`crontab.fb-pollers`) | `CronJob` |
| 상주 컨슈머 컨테이너 | `Deployment` + **KEDA ScaledObject**(lag 0↔N) |

⚠️ **매니페스트는 stale.** 이미지·네임스페이스·시크릿이 `<placeholder>` 이고 주석이 "ECR 이미지로 교체"를 전제한다 — 현행은 **Harbor**(`192.168.0.10/food-budget`) 다. 또한 앱 서비스(FastAPI 8개 + nginx) 매니페스트는 **아예 없다**(파이프라인만 존재). PGSync·clickstream 등 이후 추가분도 미반영. (§8-4)

---

## 7. 선행 미결 (CLAUDE.md·design §10 의 "사용자 결정 대기")

이전 착수 전에 결정이 필요한 항목. **임의로 정하지 말 것.**

| 항목 | 현 상태 | 출처 |
|---|---|---|
| **CNI + 서비스 메쉬** | Cilium 유력, **보류** | `design.md §10` |
| **Gateway API 구현체** | Cilium Gateway / Envoy Gateway / Traefik — CNI 에 연동 | `design.md §10` |
| **AWS ↔ Proxmox 관계** | 레지스트리 Harbor vs ECR 미정 | `design.md §8.4·§10` |
| **Kafka 데이터 보호 정책** | 별도 결정 필요 (S3 ≠ Kafka PV 대체) | `backup-strategy.md §3.1` |
| **sda(250GB) 활용** | IO 격리/백업/확장 후보, 미정 | `design.md §8.4` |
| 5인 역할분담 + 9주 타임라인 | 미정 | `design.md §10` |

---

## 8. 갭 (이 문서 작성 시점에 비어 있는 것)

집약 과정에서 드러난, **어느 문서에도 없는** 항목. 채우려면 별도 결정·작업이 필요하다.

1. **이전 트리거 조건 부재** — 전부 "조건부"인데 무엇이 충족되면 이전하는지 기준이 없다.
2. **하드웨어 선행조건이 묻혀 있음** — 노드 1대 추가(i7-10700F/32GB) 없이는 단일노드가 되어 멀티노드 스케줄 데모 서사가 성립하지 않는다. 그런데 이 요구가 §2.1 SonarQube 논의 안에만 적혀 있다.
3. **Kafka 데이터 보호 정책 미결** — Strimzi 이전 대상이나 PV/보존 정책이 백지(§7).
4. **`deploy/k8s/*.yaml` 이 현행과 어긋남** — ECR·placeholder 시절 유물. 앱 서비스 매니페스트는 부재(§6).
5. **이전 절차(runbook) 없음** — "무엇을 어떤 순서로 옮기는가"가 `backup-strategy.md §3.3` 의 *복구* 순서 말고는 없다. 컷오버·롤백 계획 부재.
