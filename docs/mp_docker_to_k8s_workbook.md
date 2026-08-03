# 워크북 — Docker Compose 4-VM → Kubernetes 이전

> 작성 2026-08-03 · 대상 = `happyInit/food-budget-app` (월 식비 예산 밀플래닝 앱, 5인 · AI 해커톤 + 인프라 캡스톤 겸용)
> 이전 기간 = **2026-07-26 ~ 2026-07-31** (6일). 구 인프라 = Proxmox 단일 호스트 위 Docker Compose 4-VM.
>
> **이 문서의 성격**: 사후 워크북이다. "무엇을 어떤 순서로 했고, 각 숫자를 왜 그렇게 정했고, 무엇이 깨졌는가"를 남긴다. 절차 지시서가 아니라 **판단의 기록**이다.
> **2026-08-03 T-3 중간 보고 반영**: P2 당시 `recipes_pgsync` 사실은 역사로 보존하고,
> `recipes_live → recipes_v2`(nori)와 stable slot `foodbudget_recipes_live` 전환 보고를 별도로 표시한다.
> config ops SSOT 선행 merge(`PENDING_AFTER_CONFIG_MERGE`)와 timestamp가 있는 재검증 전에는
> T-3 완료·최종 라이브 수치로 읽지 않는다.

---

## 0. 이 문서의 규칙

이전 기간의 서술은 여러 문서에 흩어져 있고 일부가 라이브와 어긋난다. 그래서 이 워크북은 세 규칙을 지켜 작성했다.

**① 모든 사실은 라이브에서 재확인했다.** 문서 서술을 옮기지 않았다. 날짜는 git 이력·PR 머지 시각·**클러스터 오브젝트의 `creationTimestamp`** 로, 숫자는 `kubectl`·`psql`·ES API·`vgs`·node-exporter 실측으로 확인했다. 오브젝트 생성 시각이 문서보다 강한 증거이므로 충돌 시 그것을 따랐다.

**② 문서가 틀린 곳은 라이브 값을 적고 각주로 표시했다.** 워크북을 쓰는 과정에서 문서·주석의 어긋남을 확인했다. 대표적인 것:

| 문서 서술 | 라이브 사실 |
|---|---|
| `worker-a1` = 14336MB (확장 대기) | **12288MB.** 확장은 커밋 `b9c07a6` 에서 **보류 결정**됐다. `terraform.tfvars:51`·`mp_k8s_infra_status.md:89` 가 stale |
| KEDA scale-to-zero = 컨슈머 **3종** | **4종 전부** min 0 (2026-08-02 `09d206b`) |
| 내부 도구 이름 **6종** | **7종** — ArgoCD UI 가 07-30 20:31 추가 |
| "etcd 스냅샷·metrics-server **미착수**" | **둘 다 가동 중** — 타이머 S3 성공 3회, metrics-server Running. 문서가 실제보다 비관적 |
| `docs/adr/` 없음 (ADR 0건) | **존재** — ADR-0001(2026-08-03) |
| 계획서: 호스트 C = `.177` 별도 물리 | 실제로는 **`.10` 승계 VirtualBox VM**. `.177` 은 코드에 0건 |
| Istio 메시 = app ns **11 워크로드** | Deployment **15개** / 사이드카 주입 파드 **17개** + 게이트웨이 2 |

**③ "HA" 라는 단어를 무자격으로 쓰지 않는다.** 실측 결과 현 구성은 대칭 HA 가 아니라 **host-A 내구성**이다(§7.5). 그 비대칭은 의도된 설계지만, "전 컴포넌트 HA" 라는 서술은 사실이 아니므로 §7.6 에 반례를 열거했다.

**④ Docker 시절 부하 수치를 K8s 와 직접 비교하지 않는다.** 기준 VM(`.9`, 6vCPU/3.8GiB)이 P4 에서 파괴돼 이식이 성립하지 않는다. config 커밋 `b15857d` 이 이 경계를 명시했다. 비교가 필요한 곳에는 경계선을 표시했다.

---

## 1. 전체 타임라인

### 1.1 한눈에

| # | 날짜(KST) | 단계 | 핵심 산출물 | 우선순위 근거 |
|---|---|---|---|---|
| 0 | **07-26 22:48** | **구 CI/CD 해체 → 호스트 C 투입** | Jenkins·SonarQube·Harbor on `.10` | 레지스트리는 **클러스터 구축의 전제**다. 이미지를 못 당기면 그 뒤 전부가 막힌다 |
| 1 | 07-27 21:43–21:46 | 클러스터 부트스트랩 | kubeadm 3노드 + Cilium | — |
| 2 | 07-28 09:09–09:58 | 기반 스택 10종 | ns·MetalLB·OpenEBS·cert-manager·MinIO·ESO·관측·Istio·ArgoCD | 앱보다 먼저. 앱이 의존하는 층 |
| 3 | 07-28 12:10–21:05 | **P1 앱 이전** | 백엔드 10 + frontend + Gateway `.14` 유입 | **앱 먼저** — 데이터는 구 VM 에 두고 stateless 만 옮겨 위험 분리 |
| 4 | 07-28 21:49 | 노드 램프 3→4 | `worker-a1` (host-a) | `.9` 정지·구 CI VM 파괴로 **회수된 자원**이 재원 |
| 5 | 07-29 ~ **07-30 08:46** | **P2 데이터 컷오버** | PG·ES·Kafka·Redis in-cluster, PGSync CDC | 백업 왕복 증명이 선행조건 |
| 6 | 07-30 10:56–15:42 | **모니터링 이전** | 규칙·Slack·물리계층·로그·대시보드·내부 GW `.15` | 구 P4 에서 **당겨 실행** — 철거 예정 인프라에 과도기 투자 안 함 |
| 7 | 07-30 22:01–23:32 | **P3 스케일** | Pooler 전면전환·account HPA·KEDA scale-to-zero | 데이터 티어 안정 후 |
| 8 | 07-31 10:58–12:43 | **P4 해체** | 노드 4→5, 은퇴 VM 3대 파괴 | 되돌릴 수 없는 단계라 마지막 |

### 1.2 순서의 인과 — 자원 제약이 순서를 강제했다

이 순서는 취향이 아니다. **물리 RAM 과 디스크가 순서를 결정했다.** 커밋 본문에 근거가 남아 있다.

**① 구 CI 서버 파괴 → 자원 회수 → 노드 램프 → 데이터 티어 HA**

> `84fc531`: *"**`.9` 정지(RAM 회수)·203 파괴(디스크 회수) 후** 호스트 A 에 K8s 워커 추가. **이로써 2-호스트 HA 배치가 실물로 성립한다(= P2 데이터 티어의 전제).**"*

호스트 A 는 31GiB 에 구 VM 26GB 가 상주했다. 구 VM 을 비우지 않으면 K8s 워커를 올릴 RAM 이 없고, 워커가 2개 호스트에 걸치지 않으면 데이터 티어를 분산할 대상이 없다. 그래서 **해체가 구축의 선행조건**이었다.

**② 구 CI VM 은퇴가 IP 충돌 회피 때문이었다**

> `d6e802a`: *"은퇴 VM 203 은 terraform state 에서 제거해 추적하지 않는다. **코드가 정지 상태를 되돌려 `.10` 을 호스트 C 와 다투는 사고를 막는 것이 목적** — tfvars 복원 금지."*

신 호스트 C 가 구 VM 의 `.10` 을 승계했으므로, Terraform 이 구 VM 을 되살리면 **IP 충돌로 레지스트리가 죽고 배포가 전면 실패**한다.

**③ 백업 증명 게이트를 P0 에서 P2 앞으로 옮겼다**

> PR #332: *"마지막 P0 항목이던 **S3 백업·복구 왕복**을 **P2 직전 선행조건**으로 이동 → P0 공식 종결. 게이트를 없앤 게 아니라 옮긴 것: **무백업 노출 창은 P2 컷오버(인클러스터 PG 가 실데이터 정본이 되는 순간)부터** 생긴다."*

**④ 게이트를 리허설에서 분리한 이유**

> PR #365: *"리허설 §7 에서 **분리해 단독 검증**했다. **게이트를 리허설 안에 두면 P2 착수가 리허설 일정에 인질이 된다.**"*

**⑤ 모니터링 롤 삭제가 컷오버 완료 검증에 종속됐다**

> PR #423: *"대시보드·알람 **정의가 이 롤에 있었기** 때문에, **이식 여부를 확인하기 전에는 지울 수 없었다.** … `alert-rules.yml` 알람 20종 — **20/20 대응 확인 · 순손실 0**"*

**⑥ 쿼터가 전환창 롤아웃의 전제였다**

> PR #346: *"4Gi로 잡았다가 LimitRange 기본값 주입 후 실측이 2816Mi라, **전환창의 전체 앱 롤아웃(2배 ≈5.6Gi)이 막힐** 구조였다 → app 6Gi."*

**⑦ VM 파괴는 선언을 고쳐야 끝난다**

> PR #422: *"이 VM 들은 Terraform 관리 대상이라 **손으로 지우면 다음 `apply` 가 다시 만든다.** 같은 날 그 **정반대 방향**(정지만 하고 선언을 안 고쳐서 apply 가 되살리려던 것)을 이미 밟았다."*

### 1.3 단계별 라이브 증거

날짜 검증은 **오브젝트 생성 시각**을 1차 근거로 삼았다. 아래는 대표값이다(UTC 표기는 `creationTimestamp` 원본).

| 단계 | 라이브 근거 |
|---|---|
| 3노드 등록 | `k8s-master`·`worker-b1`·`worker-b2` = `2026-07-27T12:43:08~20Z` |
| Cilium | `cilium-secrets` ns `12:46:13Z` · 이미지 `cilium:v1.19.6` · **kube-proxy DaemonSet 없음** |
| ns·PriorityClass | `data`·`pipeline`·`observability`·`app`·`argocd` **전부 `07-28T00:09:39Z`**, PriorityClass 3종 동시각 |
| 앱 Application 10 | `mp-account`·`mp-price`·`mp-recipe` 등 **전부 `07-28T08:25:05Z`** |
| 공개 GW `.14` | `Gateway app/mp-gw-public` + `svc … 192.168.0.14` **`07-28T11:10:01Z`** · HTTPRoute 10개 `11:16:40~41Z` |
| 노드 램프 | `worker-a1 07-28T12:49:28Z`(zone host-a) → `worker-a2 07-31T01:58:58Z` |
| PG 클러스터 | `Cluster/pg 07-29T08:26:35Z`, `bootstrap.pg_basebackup.source=vm-pg` → 현재 **`timelineID: 2`** = 승격 1회 = 리허설이 아닌 실컷오버 |
| Kafka·ES | `Kafka 07-29T06:26:19Z` RF=3 · `Elasticsearch 07-29T06:33:59Z` 3노드 |
| Pooler 전환 | 오브젝트는 `07-29T06:40:12Z` 부터 존재, **전환(`PGHOST→pg-pooler`)은 07-30 22:53** (config #53) |
| KEDA | `ns keda 07-30T14:09:53Z` · ScaledObject 4종 `14:19:39~40Z` |
| VM 파괴 | `terraform.tfvars` → **`vms = {}`**, 이력 주석에 201·202·203·204 전부 기재 |

---

## 2. 0단계 — 구 CI/CD 서버 해체 → 호스트 C 투입

**가장 먼저 한 일이다.** 레지스트리 없이는 클러스터에 아무것도 배포할 수 없기 때문이다.

### 2.1 무엇을 교체했나

| 대상 | 이전 | 이후 |
|---|---|---|
| CI 엔진 | GitHub Actions **self-hosted 러너**(구 VM 안) | **Jenkins** (호스트 C, Multibranch + 웹훅) |
| 레지스트리 | Harbor (구 `fb-ci-harbor` VM) | Harbor (호스트 C) — **`.10` IP·로컬 CA 인증서 승계** |
| 코드 품질 | 없음 | SonarQube 신설 (비차단 측정) |
| 물리 위치 | Proxmox 게스트 VM (vmid 203) | 별도 머신의 VirtualBox 게스트 |

### 2.2 시점 (라이브 근거)

| 날짜(KST) | 사건 | 근거 |
|---|---|---|
| 07-26 20:33 / 21:59 | `jenkins`·`sonarqube` Ansible 롤 신설 | `git log --diff-filter=A -- roles/jenkins/` → `d3a569f` / `f125ca7` |
| 07-26 22:11 | **신 Harbor 최초 채우기** (`SERVICES=all`) — 즉 신 레지스트리는 빈 상태에서 시작했다 | `d20d3fd` |
| **07-26 22:48** | **투입 확정** — PR 제목이 주소를 못 박았다: *"infra(ci): Jenkins + SonarQube 롤 + CI 파이프라인 **(호스트 .10)**"* | **PR #309** |
| 07-27 16:36 | GH Actions 트리거 **비활성**(`workflow_dispatch` 만) | `792aff4` |
| 07-27 21:14 | 구 VM 203 **은퇴** — `terraform state rm` | `d6e802a` |
| ~07-28 21:51 | 구 VM 203 **실물 파괴 (수동)** — 디스크 220GB 회수 | `84fc531` 본문 |
| 07-31 15:09 | `github_runner` 롤 **디렉터리 삭제** | `4cf664e` |

파괴가 수동이었던 이유와 그 부작용도 라이브에 흔적이 있다 — PR #346 이 *"A쪽 템플릿 9002 에 **7/27 203 이관 중단**이 남긴 stale `migrate` 락이 있어 clone 이 HTTP 500 으로 실패"* 를 기록했다. **정지·이관 중단이 다음 단계의 프로비저닝을 막았다.**

### 2.3 🔴 이 단계가 남긴 교훈 — 머신 교체가 IaC 에 기록되지 않았다

인벤토리와 `group_vars` 는 **지금도 구 VM 이름으로 `.10` 을 가리킨다.**

```
[ci]
fb-ci-harbor ansible_host=192.168.0.10      # ← 이 문자열은 07-26 이후 한 번도 안 바뀌었다
```

`git show d3a569f:inventory.ini` 와 `git show HEAD:inventory.ini` 의 `[ci]` 블록이 **동일**하다. `group_vars/all.yml:41` 도 `mp_hostwatch_sink_host: "192.168.0.10" # 호스트 C (fb-ci-harbor)` 로 남아 있다.

- 실무 영향은 없다 — Ansible 은 SSH 로 `.10` 에 닿기만 하면 된다.
- 그러나 **"이 이름 뒤의 실물이 언제 무엇으로 바뀌었는가"가 IaC 에 없다.** 이름 승계(기존 실물 이름은 그대로 참조)의 부작용이다.
- 다음 사람이 인벤토리만 보면 **아직 Proxmox VM 이라고 오해한다.**

---

## 3. 앱 이전 (P1) — 07-28

### 3.1 원칙: 앱 먼저, 데이터는 구 VM 에 남긴다

stateless 만 먼저 옮기고 데이터 좌표는 구 VM(`.8`)을 그대로 가리켰다. `app-common` ConfigMap 이 그 좌표를 들었다(`PGHOST=192.168.0.8`). 이렇게 하면 **앱 이전 실패와 데이터 이전 실패가 섞이지 않는다.**

과도기 대가도 명시적으로 수용했다 — 앱 파드 egress 에 `192.168.0.8` ipBlock 허용, 파드→VM 구간 WireGuard 미적용(구 compose 와 동일한 평문이라 후퇴는 아님).

### 3.2 실행 순서

| 순서 | 무엇 | 라이브 근거 |
|---|---|---|
| 1 | config 레포 신설 (K8s 매니페스트 전용) | 첫 커밋 `91bee88 07-28 12:10:40 +0900` |
| 2 | `mealplanning-root` app-of-apps | Application `07-28T04:29:13Z` |
| 3 | `app-common` ConfigMap (구 `.8` 좌표) | `07-28T06:26:47Z` |
| 4 | 백엔드 10 Application + Deployment | Application 10개 `08:25:05Z` / Deployment 4종 `08:26:01Z` + 6종 `08:28:50Z` |
| 5 | frontend (replicas 2) | `10:53:20~24Z` |
| 6 | **공개 Gateway `.14` + HTTPRoute 10** — nginx `/api/*` 13경로 이관 | `11:10:01Z` / `11:16:40~41Z` |
| 7 | 유입 전환 (`.9` → `.14`) | 앞단 프록시·DNS 없이 **접속 주소만 교체** |
| 8 | `.9` 정지 (인벤토리 제거) | `157b8ec` / PR #345 |
| 9 | 노드 램프 3→4 (`worker-a1`) | `07-28T12:49:28Z` |

### 3.3 검증 방식

- **`.9` 대비 18경로 응답 100% 일치**(불일치 0)를 확인한 뒤 유입을 전환했다. 정적 자산·SPA 딥링크까지 포함했다.
- 업로드 한도는 별도 복원이 필요했다 — nginx `client_max_body_size` 등가물이 Envoy 에 없어 **EnvoyFilter buffer 15MiB** 로 명시했다.
- 순서 수칙: **관측 잡 제거 → 반영 → 정지**. `PrometheusTargetDown` 이 `up == 0` 전역 규칙이라 순서를 어기면 알람 폭풍이 난다.

---

## 4. 데이터 컷오버 (P2) — 07-29 ~ 07-30

### 4.1 컴포넌트마다 방식이 다르다 — 그게 핵심 판단이다

**네 컴포넌트를 같은 방식으로 옮기지 않았다.** 복제 비용과 재파생 가능성이 다르기 때문이다.
아래 `recipes_pgsync`·첫 bootstrap 값은 **P2 전환 당시 증거**이며 현행 이름이 아니다.

| 컴포넌트 | 방식 | 근거 | 라이브 증거 |
|---|---|---|---|
| **PostgreSQL** | `pg_basebackup` 물리 복제 → replica 로 따라잡기 → **promote** → REINDEX → roll-forward | 유일하게 재파생이 불가능한 데이터. **promote 직후 REINDEX 는 musl→glibc collation 차이 때문**이다(구 VM 이 alpine 계열) | `pg_control_checkpoint()` → **`timeline_id = 2`** · WAL 아카이브 `00000002...` |
| **Elasticsearch** | **재파생** (백업·복원 안 함) | PG 에서 재색인 가능하고 실측 **7초**다. 백업 정본이 ES 를 **의도적으로 제외**한다 | **P2 당시** `recipes_pgsync` 8,963 docs(서빙) / `recipes` 5,900(DR 폴백). **현재** `recipes_live → recipes_v2` |
| **Kafka** | **드레인 후 빈 클러스터 신규 생성** — 토픽 데이터 미이전 | 컨슈머 lag=0 을 확인하면 재생 대상이 없다. 토픽은 CRD 로 선생성(빈 토픽 무해) | 🔴 전 토픽 **`earliest offset = 0`** → **한 바이트도 이관되지 않았음이 오프셋으로 증명된다** |
| **Redis** | **재생성** — 데이터 이전 0 | 구 compose 가 `--save "" --appendonly no` 였다. 캐시라 재생성이 정답 | PVC **0건**, `aof_enabled:0`, `DBSIZE 0` |
| **PGSync** | 슬롯 신규 생성 → **초기 전량 동기화** (구 체크포인트 미승계) | — | **P2 당시** Job `mp-pgsync-bootstrap` Completed, 소요 **5초**. T-3 stable-alias bootstrap은 별도 후속 작업 |
| **tfstate DB** | **K8s 로 안 옮기고 S3 backend 로 이관 후 DROP** | *"K8s PG 로 가면 순환 의존"* — 인프라를 만드는 도구의 상태가 그 인프라 안에 있게 된다 | `foodbudget` 만 존재. `terraform_state` **부재** = DROP 실행 완료 |

### 4.2 유실 0 을 무엇으로 증명했는가

| 증거 | 값 |
|---|---|
| 원본 행수 기준선 (S3 보존) | **40 테이블 / 350,850 행** (07-29 14:07:43 KST) |
| 컷오버 산출 리허설 | **41 테이블 / 630,889 행 — VM 과 완전 일치** |
| 최종 덤프 | `s3://mp-backup-ap2/pg-final/2026-07-30/` — `foodbudget.sql.gz` **19.2 MiB** + dev + tfstate + globals + **`SHA256SUMS`** (07-30 00:04:15 KST) |
| 해시 검증 | SHA256SUMS 의 4개 해시가 실제 오브젝트와 **전부 일치** |
| 타임라인 | **2** — promote 1회의 증거 |
| ES 정합 | **P2 당시** PG `public.recipe` **8,963** = ES `recipes_pgsync` **8,963 docs**. **T-3 중간 보고**는 PG 8,963 = `recipes_live` 8,963이며 최종 재검증 대기 |

⚠️ **행수 350,850 → 630,889 → ~735K 는 모순이 아니라 서로 다른 시점의 스냅샷**이다(그 사이 크롤 사이클이 돌았다). **유실 0 의 진짜 근거는 "쓰기 봉인 후 양쪽 목록 대조"** 이다. P2의 타임라인 2·최종 덤프 SHA256과, 정확한 조회 시각이 없는 T-3 중간 count 보고를 같은 증거창으로 합치지 않는다.

### 4.3 전환창 실제 타임라인

| 시각 (KST) | 사건 |
|---|---|
| 07-29 16:25 | **게이트 ① barman-cloud S3 백업→복원 왕복 단독 검증 종결** (P2 착수 선행조건) |
| 07-29 16:33 → 16:47 | promote **리허설** (장전 → 원복) |
| **07-29 22:06:08** | **전환창 T-1 장전** — promote 커밋 머지 + 앱 좌표 + ES basic_auth |
| 07-29 22:16:49 | **promote 실행** — CNPG 가 `pg-app` Secret 생성 |
| 07-29 22:17:53 | `00000002.history.gz` S3 도착 = **타임라인 전환 확정** |
| 07-29 23:01:48 | ES `recipes_pgsync` 인덱스 생성 |
| 07-29 23:05:16→21 | PGSync bootstrap (**5초**) |
| **07-29 23:56:37** | **`ES_INDEX` 플립 + un-dark** — 전환 완료 |
| 07-30 00:04:15 | 최종 덤프 S3 |
| 07-31 12:43:57 | `.8` VM **파괴** |

**promote → `ES_INDEX` 플립 = 1시간 39분 48초.** 문서의 *"열화 ~25분"* 은 앱 무중단 구간을 뺀 값이고 **커밋·오브젝트만으로는 재구성되지 않는다.**

### 4.4 백업·복구 왕복의 라이브 잔존 증거

| 오브젝트 | 상태 |
|---|---|
| `ObjectStore/mp-pg-backup` | barman-cloud → `s3://mp-backup-ap2/pg` · retention 30d · `firstRecoverabilityPoint 2026-07-29T08:44:23Z` |
| `Backup` CR **6개 전부 completed** | 리허설 재구축 · `mp-pg-base-tl2-20260730`(**tl2** = promote 후 첫 base) · 일일 백업 **4일 연속 무결손** |
| S3 barman | base backup 6개, **1,325 오브젝트 / 497 MiB**. 최신 WAL 이 수 분 전 = **연속 아카이빙 라이브** |
| 복구 실측 | 리허설: Cluster 삭제 → PVC 회수 → `pg_basebackup` **45초** → healthy **116초** (전체 238초) |

🔴 **`platform/pg/cluster.yaml` 의 `externalClusters.host: 192.168.0.8` 이 아직 살아 있다.** bootstrap 은 생성 시점 1회만 유효하니 무해하지만, **Cluster CR 을 재생성하면 존재하지 않는 VM 을 물어 부트스트랩 자체가 실패한다.**

### 4.5 🔴 PGSync 슬롯 `active=f` 는 정상이다 — 오독 주의

| 항목 | 라이브 |
|---|---|
| 현행 슬롯 | `foodbudget_recipes_live` · `test_decoding`. PGSync 폴 사이의 **`active = f`는 정상** |
| 실제 진행 | T-3에서 recipe INSERT→UPDATE→DELETE가 `recipes_live`에 순서대로 반영되고 stable slot 소비가 전진함을 확인 |
| 구 슬롯 | `foodbudget_recipes_pgsync`는 rollback window용 inactive 상태. 소비하지 않으므로 retained WAL이 증가해 종료시각 뒤 폐기 대상 |
| P2 역사값 | 구 슬롯의 유지 WAL **16 MB 고정**, current LSN과 12 kB 차이, restart LSN 11분에 64 MB 전진은 당시 건강 증거였음 |

⇒ `active=f` 를 "지금 멈춰 있다" 로 읽으면 틀린다. **실제 부채는 프로브 0개 + 가용성 기반 알람식**이다 — `mp-pgsync` 는 liveness·readiness 둘 다 없고 `replicas=1` 이며 `MpPGSyncDown` 식이 `replicas_available < 1` 이라 **"떠 있는데 일 안 하는" 상태를 원리적으로 못 잡는다.** `max_slot_wal_keep_size = -1`(무제한)이라 정지가 길어지면 WAL 이 PG 볼륨을 채운다.
T-2가 retained-WAL 알람을 1GiB/critical로 앞당겼지만 소비 정지를 직접 증명하는 프로브는 아니다.

---

## 5. 모니터링 이전 — 07-30 (5시간 56분, 하루에 끝냈다)

### 5.1 이전 전 / 후

| | 구 `.11` (Docker compose) | 현재 in-cluster |
|---|---|---|
| 메트릭 | `prom/prometheus:**latest**` | `prometheus:v3.13.1-distroless` (kube-prometheus-stack 80.4.0) |
| 알림 | `prom/alertmanager:**latest**`, `alert-rules.yml` **단일 파일** | `alertmanager:v0.33.1` + PrometheusRule CR |
| 대시보드 | `grafana/grafana:**latest**` | `grafana:13.1.1` + k8s-sidecar |
| 로그 | `loki:**latest**` (파일시스템) | `loki:3.6.8` (**MinIO S3**) |
| 트레이스 | `tempo:**latest**` (로컬 볼륨) | `tempo:2.9.0` (**MinIO S3**) |
| 에이전트 | 각 VM 의 Alloy·node-exporter·cAdvisor | Alloy DS `v1.18.0` + node-exporter `v1.12.1` + KSM `v2.19.1` |
| 오퍼레이터 | 없음 | `prometheus-operator:v0.92.1` |

🔴 **구 스택은 전 컴포넌트가 `:latest` 무핀이었다.** 이전의 실질 산출물 하나가 **"재현 가능한 버전 핀"** 이다.

### 5.2 무엇을 이식했는가

| 항목 | 라이브 값 |
|---|---|
| **PrometheusRule** | 총 40 CR / 알람 **169개**. 그중 **우리 것 = 10 CR / 알람 35개**, 나머지 134 는 차트 제공 |
| **스크레이프** | ServiceMonitor 21(우리 것 2 — `mp-app-services` 는 **12 endpoint → Istio 병합 15020**) · PodMonitor 3(**전부 우리 것**) · Probe 0 |
| **클러스터 밖 스크레이프** | `additionalScrapeConfigs` Secret — **5 타깃 전부 UP**: `hypervisor` `.12`·`.22` / `vm-node` `.10` / `vm-cadvisor` `.10:8080` / `vm-alloy` `.10:12345` |
| 실동작 증명 | `node_hwmon_temp_celsius{job="hypervisor"}` → **fb-proxmox 57°C · mp-proxmox-b 58°C** |
| **Grafana 대시보드** | 우리 것 **13장이 단일 ConfigMap** 에 들어 있고 `ServerSideApply=true` 어노테이션이 붙어 있다 — **last-applied 256KB 한도 회피 조치가 라이브에 남아 있는 형태**다 |
| **Alertmanager 라우팅** | 수신자 3(`null`/`slack-default`→`#monitoring`/`slack-critical`→`#alerts-critical`), `severity=critical` 은 repeat 1h, 억제규칙 3 |
| Slack 웹훅 주입 | `api_url_file` ← Secret ← **ExternalSecret**(`ClusterSecretStore fb-kubernetes`, refresh 1h, `SecretSynced=True`) — 웹훅이 매니페스트에 평문으로 안 들어간다 |

### 5.3 LGTM 은 컷오버보다 이틀 먼저 세웠다

**07-28 12:11 선배포**(P0 단계) → 07-30 컷오버. 스택 세우기와 컷오버를 분리해 **"스택이 뜨는가" 와 "정본을 옮기는가" 를 따로 검증**했다.

백엔드 실존 확인: MinIO 에 **`loki` ≈231 MiB / 10,987 오브젝트**, **`tempo` ≈78 MiB / 246 오브젝트**, `models` **0 B**(생성만 되고 미사용 — §8.5 의 모델 미도달과 같은 원인).

클러스터 밖 로그 유입 = 호스트 C Alloy → **`https://loki.mealbong.cloud/loki/api/v1/push`**(내부 GW `.15`, HTTP 204). `/var/log/mp-hostwatch/<라벨>.log` 도 같이 실어 보낸다(§9.1 의 증거 싱크).

### 5.4 구 `.11` 의존이 실제로 끊겼는가

| 검사 | 결과 |
|---|---|
| `Prometheus.spec.remoteWrite` | **비어 있음** — 브리지(07-28 신설)는 07-30 14:11 제거 |
| 라이브 오브젝트에 `192.168.0.11`·`.8` | ConfigMap·Secret·NetworkPolicy·CNP·ServiceEntry·PrometheusRule **전부 0건** |
| Grafana 데이터소스 | 전부 인클러스터 |
| NodePort | Grafana `30300` · Loki `31100` **회수 확인**(남은 것은 kubecost 1개) |
| VM | `.11` ping DOWN, Terraform 선언 제거 후 apply 로 파괴 |

### 5.5 진행 순서 (전부 07-30)

① 10:51 규칙·PodMonitor 이식 → ② 12:05 Slack 라우팅 인클러스터 → ③ 12:20 물리계층 스크레이프(`.12`·`.10`)+규칙 → ④ 13:54 클러스터 밖 로그 유입 → ⑤ 14:09 대시보드 13장 + **remoteWrite 브리지 제거** → 15:21 내부 GW `.15` → 15:42 NodePort 회수 → 16:47 Tempo 규칙 편입.

**순서의 핵심은 ⑤ 다** — 브리지를 마지막에 끊었다. 대시보드가 인클러스터에서 뜨는 것을 확인하기 전에 끊으면 관측이 비는 구간이 생긴다.

---

## 6. 리소스 할당 근거

### 6.1 노드 사이징

| 노드 | 선언(Terraform) | 라이브 allocatable | Proxmox 호스트 | 요청률 / 실사용 |
|---|---|---|---|---|
| `k8s-master` | 2 core / 6144MB | 1600m / **4702Mi** | B | 실사용 3470Mi = **74%** |
| `k8s-worker-a1` | 6 / **12288MB** | 5600m / 10736Mi | A | 65% / 67% |
| `k8s-worker-a2` | 6 / 11264MB | 5600m / 9729Mi | A | 63% / 43% |
| `k8s-worker-b1` | 6 / 11264MB | 5600m / 9728Mi | B | **82%** / 58% |
| `k8s-worker-b2` | 6 / 11264MB | 5600m / 9729Mi | B | 75% / 67% |

**kubelet 예약이 계획과 정확히 일치한다** — capacity − allocatable = 전 노드 균일 **400m / 1224Mi** = `systemReserved 512Mi + kubeReserved 512Mi + evictionHard 200Mi`.

**master 6GB 의 근거** (커밋 `6ab1e5e`, 원문):

> master 3GB 는 상주 추정(2.3–4.4GB)의 하한에만 걸린다. **apiserver 메모리는 노드 수가 아니라 watch 캐시가 정하고**(전역 watch 컨트롤러 10개 · ArgoCD LIST-all), taint 를 걸어도 DaemonSet 이 master 에 올라와 0.6–1GB 를 먹는다. … **재원 = B 워커 13→11GB ×2.**

🔴 **즉 `b1`·`b2` = 11264MB 의 유일한 근거는 "master 6GB 의 재원" 이고 워크로드 산정이 아니다.** 라이브가 그 판단을 지지한다 — master 실사용 3470Mi / allocatable 4702Mi = 74%, 3GB 였다면 축출 상태다.

`a1` = 12288MB 의 근거도 워크로드 요구가 아니라 **회수된 여유**다(`.9` 정지 → 호스트 A 여유 ~12GB). `a2` = 11264MB 는 *"b1/b2 와 동일"* 이 근거의 전부다.

**단일 워커 상실 시 여유(실측 계산)** — 워커 4대 allocatable 합 22400m / 39922Mi, 요청 합 10330m(46%) / 28477Mi(71%):

| 상실 노드 | 잔여 메모리 요청률 |
|---|---|
| a1 | **98%** |
| a2 / b1 / b2 | **94%** |

→ **어느 워커 1대가 죽어도 메모리 요청이 잔여 allocatable 의 94~98% 다.** 데이터 티어 HA 는 선언상 성립하지만 **재스케줄 여유가 사실상 없다**(Pending 발생). CPU 는 61% 로 무해하다.

### 6.2 워크로드 requests/limits

| ns | 파드 | 요청 CPU | 요청 MEM |
|---|---|---|---|
| data | 19 | 3750m | 12992Mi |
| app | 20 | 3150m | 4352Mi |
| cost | 4 | 660m | 3895Mi |
| observability | 9 | 550m | 2816Mi |
| kube-system | 29 | 1710m | 1404Mi |
| **전체** | **121** | **11180m** | **28925Mi** |

🔴 **네이티브 사이드카가 app ns 메모리 요청의 42% 를 먹는다.** K8s 1.34 + Istio 1.30 은 `istio-proxy` 를 `initContainers[].restartPolicy: Always` 로 띄우므로 `spec.containers` 만 합산하면 누락된다. 주입 템플릿 실측 = `requests 10m/96Mi`. 파드 19개 × 96Mi = **1824Mi / 4352Mi = 41.9%**.

이 함정이 매니페스트에 기록돼 있다 (`platform/argocd/kubecost.yaml:70-72`):

> ⚠️ 노드 여유는 `describe node` 의 Allocated resources 로 볼 것 — `spec.containers` 만 합산하면 **Istio 네이티브 사이드카**가 빠져 a1 에서 672Mi 를 과소계상한다.

**측정 근거가 있는 값** (인용):

| 값 | 근거 |
|---|---|
| account `cpu 500m` | *"250m→500m (2026-08-01) … 로그인 부하시 pod당 ~400~900m(bcrypt) 관측 — 250m 기준 HPA util% 가 **1532%** 로 무의미했다"* |
| price `cpu 300m` | *"Stage2 부하시 0.5~0.7 core 관측 — 100m 는 과소예약"* |
| mealplan `cpu 150m` | *"thin proxy — 부하 무관하게 ~145m 바닥"* |
| `mp-poller-kurly` `1Gi → 2Gi` | *"실측 피크 1131Mi(2026-07-30 검증 런)"* / *"1Gi 는 **OOMKill 실장애**(chromium 크롤 피크 1131Mi > 1Gi), 2Gi = 여유 ~45%"* |
| PG `memory req=lim 2Gi` | *"메모리 req=lim = OOM 예측성 … 2Gi 는 실측 295Mi 대비 ~7배 + 페이지캐시 몫. **CPU limits 는 넣지 않는다**"* |
| **cpu limit 부재(전 앱)** | *"bcrypt 는 버스트가 본질. **CFS 스로틀 = 로그인 병목 재발**"* |

🔴 **나머지 12/15 서비스의 `limits.memory` 는 근거가 `# OOM 보호(compose mem_limit 정합)` 뿐이다** — K8s 실측이 아니라 **docker-compose 상속값**이다. 파이프라인 22/23 워크로드의 `128Mi/512Mi` 도 동일하다.

### 6.3 요청 vs 실사용

| ns | 요청 CPU | 실사용 | 이용률 | 요청 MEM | 실사용 | 이용률 |
|---|---|---|---|---|---|---|
| app | 3090m | **119m** | **4%** | 4128Mi | 1866Mi | 45% |
| data | 3750m | 193m | 5% | 12992Mi | 7467Mi | 57% |
| cost | 660m | 53m | 8% | 3895Mi | 1322Mi | 34% |
| observability | 550m | 77m | 14% | 2816Mi | **2635Mi** | **94%** |

노드 합계 CPU 실사용 1336m / capacity 27600m = **4.8%** (한가한 시각 스냅샷 — 피크가 아니다).

**과대 요청 상위**: `kubecost-aggregator` 메모리 2.9배(3072Mi 요청 = 클러스터 최대 단일 요청) · `pg-1/2` cpu 42배·메모리 7.2배(의도된 값) · `mp-account` **cpu 128배** · `mp-price`·`mp-recipe` cpu 77배 · `mp-redis` 메모리 15배.

🔴 **과소 요청 — 축출 위험**: `grafana` 요청 128Mi 대비 실사용 **371Mi(2.9배)에 메모리 한도 없음** · `prometheus` 1024Mi 대비 **1364Mi(1.33배)**. 이것이 observability ns 이용률 94% 의 정체이고, 두 파드는 **Burstable + priority 0** 이라 노드 압박 시 가장 먼저 축출될 후보다.

ES/Kafka 는 heap 지배형이라 req≈lim 이 정상이다(ES heap max 2.26GiB / used 1.17GiB, ECK 기본 = limit 의 50%).

### 6.4 쿼터 · LimitRange · PriorityClass

| ns | ResourceQuota | used | 판정 |
|---|---|---|---|
| `app` | cpu 6 / mem **6Gi** | 3150m / 4352Mi (51% / 71%) | HPA max 시 **80% / 90%** — 들어가지만 타이트 |
| `pipeline` | cpu 3 / mem 3Gi | 50m / 128Mi | KEDA max + kurly 동시 = 22% / **83%** |
| `data`·`observability`·`cost`·`kube-system` | **없음** | — | 🔴 `cost`(3895Mi)·`data`(12992Mi)가 무제한 |

`LimitRange` 2개(`app`·`pipeline`) = `defaultRequest 10m/128Mi · default limits memory 512Mi`. **max/min/maxLimitRequestRatio 없음** → 기본값 채우기 전용이고 상한 방어는 없다.

PriorityClass = `data-critical 1000000` (15파드) · `app-normal 100000` (8파드) · `pipeline-low 1000`.

🔴 **`ResourceQuota`·`LimitRange`·`PriorityClass` 매니페스트가 config 레포에 0건이다.** 전부 손 `apply` 된 클러스터 오브젝트다 → GitOps 밖이고 재구축 시 소실된다. `PriorityClass` 는 `git log -S'kind: PriorityClass' --all` 에도 없다.

🔴 **app 티어 priorityClass 가 절반만 적용된 상태다.** `notify`·`operations`·`pantry`·`price`·`recipe`·`recipebook`·`video`·`frontend`·`cloudflared`·**`mp-gw-public-istio`** 가 priority 0 = `pipeline-low`(1000) 인 크롤러보다 **낮다**. 배치 분할 이유도 쿼터였다 — 동시 롤아웃 서지 3,296Mi > 여유 2,016Mi.

### 6.5 스토리지

**선언 351Gi(PVC 20개) / 실사용 8.04GiB = 2.4%.**

| PVC | 용량 | 실사용 | 판정 |
|---|---|---|---|
| `kubecost/aggregator-db` | 64Gi | 0.17G | 🔴 최악 |
| `kubecost/local-store` | 32Gi | 0.82G | 과대 |
| `observability/minio` | 50Gi | 0.41G | 과대 |
| `observability/prometheus` | 30Gi | **3.72G (12.7%)** | 유일하게 근사 (15d 보존 시 ~31% 추정) |
| `data/kafka × 3` | 20Gi | 0.07~0.09G | 과대 |
| `data/pg × 2` | 20Gi | 0.26G | 과대 |
| `data/pg-wal × 2` | 10Gi | **1.06G (10.9%)** | 근사 |
| `data/es × 3` | 10Gi | 0.00~0.01G | 🔴 실 인덱스 **16.0MB 총합** → 약 **1900배** |

🔴 **OpenEBS LVM LocalPV 는 thick 프로비저닝이다 — 과대 선언이 VG 를 즉시 먹는다.** 노드별 `vgs` 실측(전부 `openebs-vg` 150.00g): a1 여유 88g · a2 53g · b1 70g · **b2 38g**.

**이 압박이 실사고를 냈고 매니페스트에 근거가 남아 있다** (`platform/argocd/kubecost.yaml:48-51`):

> 이 32Gi 가 b2 의 openebs-vg 여유를 48Gi → 16Gi 로 줄였고, 그 탓에 **Kafka 브로커 재배치(20Gi PVC)가 b2 에서 막혔다(실사고).**

`storage_disk_gb = 150` 자체의 근거는 PVC 수요 산정이 아니라 **씬풀 점유율**뿐이다(`씬풀(794G) 점유 = 90 + 240×2 = 570G(72%)`).

### 6.6 QoS

**Burstable 95 · BestEffort 25 · Guaranteed 1**(유일한 Guaranteed 는 업스트림 차트 기본값이라 우리 결정이 아니다).

메모리만 req=lim 으로 맞춘 곳(PG 2Gi · ES 1536Mi · Kafka 1Gi · Redis 256Mi)은 **전부 Burstable** 이다 — cpu limit 을 일부러 안 걸었기 때문이다. 즉 **Guaranteed 를 노린 게 아니라 메모리 OOM 예측성만 노린 설계**다. 근거(커밋 `b64008b4`):

> BestEffort → Burstable: 무리소스면 커널 OOM 점수 최악(1000)이라, kubelet 이 못 따라잡는 순간 스파이크에선 **PriorityClass 와 무관하게 PG 가 노드의 첫 희생자**가 된다(2026-07-30 컬리 폴러 OOM 건에서 확인).

🔴 **그런데 `pg-pooler` 2파드가 BestEffort 다.** `priorityClassName: data-critical`(1000000)인데 QoS 는 최하위다 — `platform/pooler/pooler.yaml` 에 `resources` 블록이 없다. **PG 를 BestEffort→Burstable 로 고친 것과 똑같은 취약점이 그 앞단 PgBouncer 에 그대로 남아 있고, PgBouncer 가 죽으면 앱 8종이 전부 DB 를 잃는다.** 실사용은 32Mi/57Mi 라 비용은 무의미한 수준이다.

### 6.7 오토스케일

**HPA 2개** — `mp-account`·`mp-recipe`, 둘 다 `ContainerResource cpu · Utilization 70 · min 2 / max 4`.

| 결정 | 근거 |
|---|---|
| `max 4` | *"노드 4대 · 커넥션 4×5=20 으로 PgBouncer `max_client_conn 100` 안쪽"* |
| `min 2` | *"예측 가능한 피크타임(11-12·17-18시) … min 1 이면 스파이크가 파드 하나를 때리는 동안 HPA 가 반응할 시간(메트릭 지연 + 파드 기동 + holdApplicationUntilProxyReady)이 없다"* |
| **`ContainerResource`**(≠`Resource`) | *"파드에 istio-proxy 가 함께 살고 그 requests 가 10m 뿐이라, 파드 전체 기준으로 보면 프록시가 조금만 튀어도 비율이 흔들린다. 앱 컨테이너만 본다(K8s 1.30 GA)"* — §6.2 의 사이드카 42% 가 이 판단을 뒷받침한다 |
| **HPA 전제 = Pooler** | *"순서를 어기면 HPA 가 CPU 가 아니라 DB 커넥션에 먼저 막힌다 … 'HPA 를 켰는데 오히려 느려지는' 현상"* |
| recipe HPA 도입 | *"동시 1000명서 recipe_search p95 2.7s(단일 pod CPU ~1.2core plateau). replica 1→4 통제 재현서 같은 부하가 **45.6ms(59× ↓)**"* |
| 전면 HPA 기각 | *"'일단 전부 HPA' 는 requests 오설정과 맞물려 진동한다"* |

**KEDA ScaledObject 4개** — 전부 `min 0 / lagThreshold 10 / polling 30 / cooldown 300`, Kafka lag 트리거.

`maxReplicaCount` 가 **파티션 수와 정확히 일치**한다(3/3/3/2). 근거: *"maxReplicaCount 는 **파티션 수를 넘기지 않는다** — Kafka 는 파티션 하나를 컨슈머 하나에만 주므로 그 이상은 놀고만 있다."*

min 0 도달 조건(커밋 `9d8d346`): *"① 오프셋 커밋 — 없으면 KEDA 가 lag 를 0 으로 보고해 **영영 안 깨어난다** / ② 콜드스타트 14초 … 폴링 더해 최악 ~45초 / ③ `pollingInterval`·`cooldownPeriod` 는 min 0 에서만 유효"*. 만료 안전마진 = `offsets.retention 7일` vs 크롤 최대 간격 4일(수→일) → **여유 3일**.

### 6.8 PG 커넥션 풀 산정

| 층 | 선언 | 라이브 |
|---|---|---|
| PG `max_connections` | **미선언**(의도적 공백) | **100** — *"CNPG 기본값이 이미 정답이라 `postgresql.parameters` 를 비워 둔다"* |
| PG `shared_buffers` | 미선언 | 128MB (PG 기본, 튜닝 안 함) |
| Pooler | `instances 2`, `poolMode transaction` | `max_client_conn 100`·`default_pool_size 20` = **pgbouncer 컴파일 기본값** |
| 앱 `pg_pool_max` | env 0건 | 이미지 기본값 **5**(min 1), 전 서비스 |
| 실제 커넥션 | — | PG 총 13 backend / client 6 · PgBouncer `cl_active 8`, `sv_idle 0` |

**최악 케이스 재계산**: 앱 파드 최대 = account 4 + recipe 4 + 나머지 7종 × 1 = 15 파드 × 5 = **75 클라이언트** vs `max_client_conn 100` → 여유. 백엔드는 `default_pool_size 20 × 2` = 40 vs `max_connections 100` → 여유. **HPA `max 4` 의 커넥션 논리는 라이브에서 성립한다.**

🔴 **그런데 그 논리의 핵심 수치 2개(`max_client_conn`·`default_pool_size`)가 매니페스트에 없다** — pgbouncer 상속 기본값이고, 이번 조사에서 `SHOW CONFIG` 로 처음 확인했다. 업스트림이 기본값을 바꾸면 HPA 정당화가 조용히 무너진다.

Pooler 전환 실증(커밋 `a0ae90e`): *"카나리 실증(price, 1/9): 부하 600건/동시 30 → 599 req/s · p50 11ms · p95 29ms · 5xx 0 · **백엔드 커넥션 5개로 다중화**"*.

### 6.9 🔴 근거를 찾지 못한 숫자

워크북을 쓰면서 **레포·커밋·주석 어디에도 산정 근거가 없는 값 22건**을 확인했다. 다음 사람이 "이 숫자는 검증된 것"으로 오해하지 않게 남긴다.

**노드/Terraform** — `cores = 2`(master)·`6`(워커) **vCPU 근거 0건**(호스트 A 는 8C/16T 인데 선언 12 vCPU, 물리코어 초과가 어디에도 인정돼 있지 않다) · 호스트 B CPU 모델·코어수 미기재 · `disk_gb 50`·`containerd_disk_gb 40` 수치 산정 없음 · `storage_disk_gb 150` 은 씬풀 검산만.

**오토스케일** — `lagThreshold 10` ×4 · `pollingInterval 30` ×4 · `cooldownPeriod 300` ×4 · HPA `averageUtilization 70` — 전부 동작 재서술만 있고 "왜 그 값"이 없다. `MpConsumerBacklogStuck` 임계 100 은 커밋이 스스로 미확정으로 표기(*"일요일 만개레시피 크론 실적을 보고 조인다"*).

**커넥션/쿼터** — PgBouncer `max_client_conn`·`default_pool_size`(미선언 상속) · `Pooler.instances 2` · Pooler `resources` 부재 사유 · `ResourceQuota` **6core/6Gi 와 3/3Gi 의 근거 0건** · PriorityClass value 3종의 **크기·간격** 근거 없음 · LimitRange 값 근거 0건.

**워크로드** — 12/15 서비스 `limits.memory`(compose 상속) · 파이프라인 `cpu 50m` · kubecost `memory 3Gi`(배치 근거는 상세한데 **3Gi 자체는 없다**, 실사용 34%) · kubecost 스토리지 64Gi/32Gi · MinIO 50Gi·Loki/Tempo 10Gi·Prometheus 30Gi 의 보존기간↔용량 산정식 · PDB `minAvailable 1` 을 `maxUnavailable 1` 대신 고른 이유 · `mp-price-anomaly-notifier` 만 KEDA 예외인 사유.

---

## 7. HA 구성

### 7.1 계층별

| 계층 | 구성 | HA 보장 |
|---|---|---|
| master | ×1, zone=host-b, taint `NoSchedule` | ❌ 단일 |
| etcd | 멤버 1개, v3.6.5, DB 94MB | ❌ 단일 |
| kube-proxy | **없음** — Cilium `kube-proxy-replacement=true`, VXLAN, WireGuard | ✅ 설계대로 |
| 단일 master 상쇄 | `mp-etcd-backup.timer` **매일 02:00 KST → S3**, 최근 3회 전부 성공, 로컬 스냅샷 3개(32–39MB) | 🔶 복구 수단만 |

### 7.2 워크로드 분산

**hard 2계층 = 진짜 보장 (4개뿐)** — `DoNotSchedule` + `nodeTaintsPolicy: Honor` + `matchLabelKeys: [pod-template-hash]`, 축 = zone + hostname:

| 워크로드 | replicas | 현재 분포 |
|---|---|---|
| `mp-account` | 2 | a2 / b2 = host-a / host-b ✅ |
| `mp-frontend` | 2 | a2 / b1 ✅ |
| `mp-gw-public-istio` | 2 | a1 / b1 ✅ |
| `mp-recipe` | 2 | a2 / b2 ✅ |

**soft = 보장 아님 (9개)** — `tier: backend` + `ScheduleAnyway`. **전부 replicas=1** 이라 제약이 셀 파드가 하나뿐이고 분산 대상이 없다. `mp-video`·`mp-cloudflared-app` 은 TSC 자체가 없다.

**"soft 는 보장이 아니다"를 세 커밋이 실측으로 증명했다:**

> `e9b6ee1`: *"soft(ScheduleAnyway) 는 보장이 아니라 힌트였다. 실측: `mp-recipe` 2 replica → a1+a2 = **전부 host-a**, `mp-frontend` → b1+b2 = **전부 host-b**. 둘 다 zone TSC 가 이미 걸려 있는데도 몰렸다."*

> `ac54aa6`: *"hard/soft 문제가 아니었다. TSC 는 스케줄 시점에 selector 에 걸리는 **모든** 파드를 세는데, 롤링 업데이트 중엔 아직 안 죽은 구 RS 파드가 거기 낀다 … 매 순간 제약은 지켜졌는데 최종 상태가 몰린다. **갈라진 2개는 운이었다.**"*

→ 그래서 `matchLabelKeys: [pod-template-hash]` 를 넣어 구 RS 를 계산에서 뺐다.

🔴 **함정**: 워크로드당 `topologyKey` 는 유일해야 한다. strategic-merge 의 patchMergeKey 가 `topologyKey` 라 같은 축 항목이 둘이면 병합이 깨지고 **`maxSkew` 가 조용히 소실**된다(`dry-run` 에서 확인).

**PDB** — app 4종·es·kafka·pooler·redis-replication·pg-primary. 🔴 **Sentinel StatefulSet `mp-redis-s`(3파드)에 PDB 가 없다** — `mp-redis-replication` 의 selector 는 데이터 파드 2개만 잡는다. **정족수를 쥔 컴포넌트가 무보호다.**

### 7.3 zone 레이블 — 왜 노드 이름이 아닌가

zone=**host-a**: `worker-a1`·`worker-a2` / zone=**host-b**: `master`·`worker-b1`·`worker-b2`.

> `cefde8a`: *"1차 반영(hostname TSC)에서 두 파드가 a1·a2 로 떴다 — 노드는 갈라졌지만 **둘 다 물리 호스트 A** 다. 이 클러스터의 실제 고장 이력은 '**무흔적 급사 3회, 전부 호스트 A**' 라서, 노드 SPOF 를 없애는 대신 **호스트 SPOF 를 새로 만든 꼴**이 됐다."*

표준 키(`topology.kubernetes.io/zone`)를 쓴 이유는 TSC·볼륨 토폴로지가 이 키를 기본으로 이해하기 때문이고, **EKS 로 옮기면 그대로 진짜 AZ 가 된다.**

### 7.4 데이터 티어 실측

| 컴포넌트 | 구성 | 라이브 | 🔴 갭 |
|---|---|---|---|
| **PG** (CNPG) | 2 instances, anti-affinity `required` on zone | primary `pg-1`@a1 / standby `pg-2`@b1, **timelineID 2**, lag 0.5~3ms, HA 슬롯 on, `unsupervised` 페일오버, barman → S3 daily | **`minSyncReplicas: 0` · `synchronous_standby_names` 빈 값 = 비동기** → 페일오버 시 커밋 유실 가능 |
| **ES** (ECK) | 3노드 green, zone awareness on, nodeSelector 로 zone 고정 | `recipes_live → recipes_v2` pri1/rep1 · `recipes` **green pri1/rep1/docs5,900** (#9) | **3노드 전부 master-eligible → 정족수 2 이고 2/3 이 host-b**. ~~`recipes` rep0·b2 단독~~은 2026-08-03 해소 |
| **Kafka** (Strimzi KRaft) | 3 combined, RF=3, `min.insync=2`, hard TSC | 토픽 10개 전부 RF=3, **ISR 완전**(`__consumer_offsets` 50파티션 포함), MaxFollowerLag 0 | **controller 2/3 이 host-b**. 커밋 `f571fc3` 이 인정 — *"⚠️ 이 제약은 대칭이라 '다수가 B' 까지는 표현하지 못한다"* |
| **Redis** (OT-Container-Kit) | master+replica, **인라인 Sentinel** size 3 / quorum 2 | Sentinel 이 실제 master(`10.244.1.207`=mp-redis-0) 지목 ✅, `num-other-sentinels 2` | **Sentinel 2/3 + master 전부 host-b** → host-b 상실 시 생존 Sentinel 1 → **페일오버가 아예 일어나지 않는다**. 그리고 **배치 원칙("Redis primary 는 A") 위반** — zone TSC 는 maxSkew 만 강제하고 ordinal-0 의 zone 은 정하지 않는다 |
| **MinIO** | replicas 1, zone=host-b 고정, LocalPV b2 못박음 | 문서화된 예외 | `strategy maxUnavailable 0 / maxSurge 100%` 가 단일 RWO LocalPV 와 모순(서지 파드가 볼륨을 못 붙는다) |

### 7.5 🔴 "HA" 가 아니라 "host-A 내구성"이다

**host-b 에 몰린 것**: 컨트롤플레인 전부(etcd·apiserver·scheduler·controller-manager) · ES 정족수 2/3 · Kafka KRaft 정족수 2/3 · Redis Sentinel 정족수 2/3 · Redis master · MinIO(단일) · Prometheus · Alertmanager · Loki · Tempo · ArgoCD 5/8.

→ **host-b 상실 시 자동복구가 원리적으로 불가능하다** — 복구를 수행할 주체(컨트롤플레인)가 같이 죽는다. 반대로 **host-a 상실은 PG 페일오버 한 번으로 생존한다**(단 비동기라 유실 가능).

**이 비대칭은 의도적이다** — 배치 원칙이 *"급사 3회가 전부 호스트 A → master·quorum 다수·Prometheus·MinIO 는 B"* 이고, 실제 고장 이력이 그렇다. **다만 워크북에 "HA" 로 적으면 사실이 아니고, "host-A 내구성" 이라고 적어야 정확하다.**

**호스트 상실 시 재스케줄이 용량으로 막힌다** (`describe node` memory requests):

| 시나리오 | 이전 대상 | 수용 여유 | 판정 |
|---|---|---|---|
| host-b 상실 | 15.3Gi | host-a 여유 **7.1Gi** | **절반도 안 들어간다** |
| host-a 상실 | 13.1Gi | host-b 여유 **4.0Gi** | **1/3 도 안 들어간다** |

게다가 limits 는 이미 초과 커밋 상태다(b1 **154%** · b2 130% · a1 98% · a2 93%).

**스테이트풀은 "재스케줄"이 없다** — PV 20개 전부 `openebs.io/nodename` 단일 노드 못박음. 사본이 있는 것만 살아남는다. **사본 0**: MinIO(b2) · Prometheus(b2) · Alertmanager(b2) · Loki(b1) · Tempo(b1) · kubecost 3볼륨(a2) · pipeline 상태 2볼륨(a1). ~~ES `recipes`~~는 #9로 replica 1 확보.

### 7.6 "보장이라 적혀 있지만 보장이 아닌 것"

| # | 서술 | 실제 |
|---|---|---|
| 1 | "**전 컴포넌트 HA**" (MinIO 만 예외) | 예외는 MinIO 만이 아니다 — **Prometheus·Alertmanager·Loki·Tempo·istiod·내부 GW·ArgoCD 가 전부 단일 replica**. ~~ES `recipes` rep0~~은 #9로 해소 |
| 2 | "Kafka 3브로커 RF=3" | RF·ISR 은 완전하나 **controller 2/3 이 host-b** |
| 3 | "ES 3노드 green" | 3노드 **전부 master-eligible**, 2/3 이 host-b → host-b 상실 = 클러스터 정지. green 은 현재 상태이지 내구성 진술이 아니다 |
| 4 | "Redis master+replica+Sentinel3" | Sentinel 2/3 + master 전부 host-b → **quorum 미달로 페일오버 불가**. Sentinel 에 PDB 도 없다 |
| 5 | "**클라이언트 Sentinel-aware**" | **price·chat 2종만**. `ocr`·`video` 는 평문 `redishost` 로 갱신 안 되는 `mp-redis-master` Service 를 본다 |
| 6 | "PG 2인스턴스 · 복제 lag ms 급" | lag 은 사실이나 **비동기** — 페일오버는 되지만 **유실 0 을 보장하지 않는다** |
| 7 | "Pooler 경유"(P3 성과) | Pooler 2 replica 가 a1·b1 로 갈라진 건 **template 에 TSC·affinity 가 null** 이라 **우연**이다 |
| 8 | 백엔드 11종 TSC | 9종이 soft + replicas 1 → **분산 대상이 없다**. 원 커밋은 그 한정을 적었는데 상위 요약에서 떨어졌다 |
| 9 | descheduler = "zone 분산 자동 복구" | 대상 = **app ns ∩ hard TSC ∩ replicas≥2 ∩ PDB 보유 = 4종뿐**. `PodsWithoutPDB`·`PodsWithPVC` 보호로 나머지는 구조적 제외(의도된 설계) |
| 10 | "PG·Redis primary 는 A" | PG 는 a1 ✅ / **Redis master 는 b1 = host-b** ❌ |
| 11 | "etcd 스냅샷·metrics-server 미착수" | **역방향 오류** — 둘 다 가동 중 |

### 7.7 유입·자동복구

- **`type: LoadBalancer` Service 가 전 클러스터 2개뿐** — `.14` 공개 / `.15` 내부. MetalLB 풀 `autoAssign: false` 로 강제하고 L2Advertisement 는 master 를 제외한다. **"LB 는 게이트웨이 전용" 규칙이 라이브로 검증된다.** `.16` 은 예비(카나리·신구 병행)
- 공개 GW replicas 2 + hard TSC + PDB ✅ / **내부 GW replicas 1, PDB 없음** ❌ / **istiod replicas 1, istio-system PDB 0건** ❌
- **descheduler** CronJob `*/30` KST, 정책 = `RemovePodsViolatingTopologySpreadConstraint` + `DefaultEvictor(minPodAge 5m, minReplicas 2, nodeFit)` + `podProtections: PodsWithPVC, PodsWithoutPDB`, `maxNoOfPodsToEvictTotal 2`. 최근 2회 실행에서 8개 제약 전부 `already balanced`, `totalEvicted=0` 정상
- **분산 감시 알람 실존** — `MpDeploymentPodsOnSingleNode`·`MpDeploymentPodsOnSingleZone`(20분 지속 + 10샘플) + 그 파생이 조용히 틀어지는 걸 막는 `MpNodeZoneMapUnknown`(노드 이름 정규식 가드)

---

## 8. 애플리케이션 특수 대응

일반적 K8s 모범사례가 아니라 **이 앱 때문에 생긴 대응**만 적는다.

### 8.1 앱 코드가 바뀐 지점

| 무엇 | compose | K8s | 왜 |
|---|---|---|---|
| psycopg 준비문 | 기본 `prepare_threshold=5` | `prepare_threshold=None` | PgBouncer transaction 풀링은 트랜잭션마다 백엔드가 바뀌어 `prepared statement does not exist` |
| DB 풀 | `max_size=10` | `pg_pool_max=5` | 파드가 늘어도 PG 커넥션이 곱해지지 않게 |
| Redis | `Redis(host=...)` | `Sentinel(...).master_for(...)` 분기 | 오퍼레이터가 ordinal-0 을 master 로 고집 → 노드 상실 중 master Service 엔드포인트가 빈다 |
| ES 인증 | 무인증 http | `basic_auth` 조건부 | ECK 는 인증을 강제한다. VM 의 맨 ES 는 안 했다 |
| OCR 잡 상태 | 프로세스 메모리 `dict` | Redis `JobStore` | POST 받은 파드 ≠ GET 받은 파드 → 404. **replica 확장 선행조건** |
| nginx 포트 | `listen 80` + `cap_add: NET_BIND_SERVICE` | `listen 8080`, capability 전부 drop | PSS restricted 가 `NET_BIND_SERVICE` 를 금지 |
| GCP SA 키 | 파일 경로 | **원시 JSON env** 우선 | RO rootfs + 비루트 + 앱/인프라 레포 분리 → 파일 마운트가 별 레포 변경을 요구 |
| OAuth 클라이언트 | 새 `AsyncClient`, 평탄 5s | 공유 클라이언트 + `connect=10s` + 재시도 + 기동 시 `warm_dns()` | `ndots:5` 검색도메인 헛질 + CoreDNS 콜드 캐시가 connect 5s 초과 → **첫 로그인 401** |
| chat-insights skip | `return 2` | `return 0` | CronJob 은 비0 = Job Failed → 매일 오탐 |

🔴 **"K8s 탓" 으로 적힌 커밋 3건은 실제로 컨테이너 패키징 버그였다.** `crawler/kurly/Dockerfile` 의 `_topics.py` COPY 누락 · `video/main.py` 의 `os.environ.get` default 인자가 **항상 즉시 평가**되어 `IndexError` · `video/Dockerfile` 의 `gazetteer.py` 미동봉. 세 건이 같은 클래스다 — **compose 가 넓은 트리를 마운트/COPY 해서 가려져 있던 암묵적 파일시스템 레이아웃 가정이, 서비스별 슬림 이미지로 쪼개지며 첫 파드 부팅에서 드러났다.**

### 8.2 커넥션 풀 — Pooler 전면 적용이 아니라 예외를 남겼다

Pooler 경유 8종(account·chat·mealplan·notify·pantry·price·recipe·recipebook) / **직결 4종**:

| 예외 | 좌표 | 이유 |
|---|---|---|
| `ocr` | `pg-rw` | 세션 스코프 `SET statement_timeout`·`read_only` 가드가 transaction 풀링에서 **에러 없이 조용히 무효화**된다 |
| `ranking-serving` | `pg-rw` | `psycopg.connect()` 직접 호출 → `prepare_threshold=None` 패치 범위 밖 |
| PGSync·pipeline | `pg-rw` | `LISTEN/NOTIFY` 가 세션 기능이라 transaction 풀링에서 죽는다 |
| `operations` | **`211.46.52.152:15432`** (제3자 PG) | 내부 CNPG 여유 확보 전 임시. 🔴 **풀 축소·준비문 패치가 이 서비스에는 무효**다 — 좌표가 CNPG 를 향하지 않는다 |

### 8.3 검색 인덱스 전환 — P2 부작용과 T-3 중간 전환 보고

#### P2 당시 구조와 문제

| | 배치 `recipes` | CDC `recipes_pgsync` (**당시 서빙**) |
|---|---|---|
| 산출 | `index_recipes_es.py`가 drop→create, settings 인라인 | PGSync가 자동 생성 |
| servable 게이트 | **색인 시점** (SQL `HAVING`) | **쿼리 시점** (`term servable:true`) |
| docs | 5,900 | 8,963 (그중 servable=true = **5,900**) |

게이트를 옮긴 이유는 CDC가 EPIS·COOKRCP01을 포함한 원천 전건을 복제하기 때문이다. 코퍼스도
`servable=false`로 스탬프하고 앱 쿼리가 최종 방어선이 됐다. 같은 게이트 로직이 배치와 plugin
두 곳에 있으므로 한쪽만 바꾸면 `recipes`와 `recipes_live`가 어긋난다.

여기서 서로 다른 두 근인이 드러났다.

1. **검색 품질 근인** — nori plugin은 설치돼 있었지만 index settings/mapping을 생성하는 tracked
   경로가 없었다. PGSync가 동적 매핑으로 `recipes_pgsync`를 먼저 만들어 analyzer와 exact mapping이
   빠졌다.
2. **세대교체 충돌 근인** — PGSync logical index에 물리 이름을 써 slot 이름까지 결합됐다.
   물리 세대를 `recipes_v2`로 바꾸면 새 slot과 full bootstrap이 필요해 권한 충돌이 반복됐다.

P2 당시 `_analyze(돼지고기김치찌개)`는 배치 `recipes`에서
`돼지고기·돼지·고기·김치찌개·김치·찌개`, 서빙 `recipes_pgsync`에서는 통짜 한 토큰이었다.
실제 `multi_match`도 `돼지고기` 162 vs 218(−26%), `김치찌개` 8 vs 13(−38%)이었다.

동적 매핑으로 exact 필드가 `text+.keyword`가 된 문제도 있었다. 다만 이후 추적에서 실제 서빙 대상
`source='10K'`의 category 원천값이 전량 NULL임을 확인했다. 따라서 현재 category 0건의 근인은
매핑이 아니라 크롤러/정제 데이터이며, T-3 성공 기준은 nori 리콜·count·CRUD CDC다.

#### T-3 목표 구조와 중간 보고 상태

```
PG recipe / recipe_ingredient
        │ PGSync CDC (slot: foodbudget_recipes_live)
        ▼
recipes_live ──alias──▶ recipes_v2 (nori + 명시 mapping + replica 1)
        ▲
mp-recipe ES_INDEX
```

아래 수치는 실행 에이전트 완료 보고에서 왔고 정확한 라이브 조회 시각이 기록되지 않았다. config ops
SSOT merge 뒤 같은 검증을 새 timestamp로 반복하기 전에는 최종값이나 완료 근거로 사용하지 않는다.

| 중간 검증 | 보고 결과 |
|---|---|
| 정합 | PG 8,963 = `recipes_live` 8,963 |
| nori | `김치찌개 → 김치찌개·김치·찌개` |
| 실제 API | `김치찌개` 13건 · `김치` 275건 |
| CDC | INSERT→UPDATE→DELETE 왕복, 최종 잔재 없음 |
| DR 폴백 | `recipes` green · pri 1 · rep 1 · docs 5,900 (#9 완료) |

앱 읽기와 PGSync 쓰기를 `recipes_live`로 고정해 physical generation과 slot identity를 분리했다.
정상 세대교체는 새 물리 인덱스 생성·초기 동기화 뒤 **final-sync/LSN barrier**를 통과하고 alias를
원자적으로 옮긴다. bootstrap role은 preflight가 stable slot/`_view`/trigger 재구축 필요를 확인한
DR·artifact/schema-trigger 복구에만 한시적으로 활성화한다.

mapping 정본은 config 레포 `ops/pgsync-stable-alias/recipes-index.json`이다. 이 app 변경보다 해당
config ops SSOT가 먼저 merge돼야 하며 아직 PR/commit은 `PENDING_AFTER_CONFIG_MERGE`다. 호출자가 0건이던
`deploy/pgsync/recipes_pgsync.index.json`은 삭제했으며 앱 레포에 mapping 사본을 다시 만들지 않는다.

구 backing은 전환 직후부터 stale해지므로 alias만 되돌리는 rollback은 안전하지 않다. 구 consumer
manifest·LSN barrier·exact confirmation을 갖춘 tracked runbook 전에는 rollback 설명을 실행 절차로
사용하지 않는다. 운영 정본은 `mp_k8s_infra_status.md §7.1-3a`다.

### 8.4 PSS restricted 대응

| 무엇 | compose | K8s |
|---|---|---|
| ns 강제 | 없음 | `app` **enforce restricted** / `pipeline`·`data` enforce baseline(warn restricted) |
| 유저 | Dockerfile `USER 10001` (compose 는 검사 안 함) | 동일 + **Pod `securityContext` 필드 명시 필수** — PSS 는 admission 에서 매니페스트를 보고 이미지 내부 `USER` 는 안 본다 |
| RO rootfs | `read_only: true` | `readOnlyRootFilesystem: true` + **거의 전 서비스에 `emptyDir /tmp` 신규 추가** — admission 이 실제로 관철하자 암묵적 `/tmp` 쓰기가 드러났다 |
| nginx | 이미지 기본 | `chown nginx /var/cache/nginx /run` + emptyDir 3종 |

🔴 **`pipeline`·`data` ns 는 root 가 남았다** — 이미지에 `USER` 가 없어 매니페스트만으로 켜면 전 파이프라인이 기동 불가다. 유예는 의도적이고 `pipelines/kustomization.yaml` 에 명시돼 있다.

🔴 **그런데 그 유예에 함정이 있다** — 같은 파일의 RFC-6902 `op: add` 패치가 `consumers.yaml` 에 적힌 `runAsNonRoot`/`runAsUser` 블록을 **통째로 덮어쓴다**(경로 존재 시 replace). **파일에는 non-root 라고 적혀 있고 라이브는 root 다.** 매니페스트를 읽고 "적용됐다"고 믿으면 안 되는 실례다.

후속 리스크: `pipeline` 에 RO rootfs 를 실제로 걸면 **Playwright 크롤러가 브라우저 프로필·캐시 쓰기로 깨진다** → emptyDir 배선이 선행돼야 한다.

### 8.5 상태 저장 워크로드

| 무엇 | compose | K8s | 판정 |
|---|---|---|---|
| OCR·video 잡 상태 | 프로세스 메모리 / (신규) | Redis Store | replica-safe 달성. **단 실제 replica 는 둘 다 1, HPA 없음** — 확장 "가능"이 확인됐을 뿐 |
| 크롤 상태 | compose 볼륨 | PVC `mp-recipe-crawl-state` (RWO, 단일 파드 CronJob) | 성립 |
| chat 리포트 | 호스트 바인드 마운트 | PVC `mp-chat-reports` | 성립 |
| PGSync 플러그인 | compose 볼륨 | ConfigMap → **initContainer 로 emptyDir 복사** | ConfigMap 직마운트의 `..data` 심링크를 플러그인 로더가 모듈로 오인해 `ModuleNotFoundError` |
| PGSync 실행 | compose 컨테이너 | `args: [-c, /app/schema.json, **-d**]` | `-d` 없으면 1회 동기화 후 종료를 무한 반복 |
| 🔴 **ML 모델 공유** | named volume `ranking-model`(사실상 RWX) | **볼륨 삭제 → `emptyDir`**. initContainer·MinIO·S3 코드 전부 없음 | **RWX 회피는 성공, 대체는 미완.** 라이브 `/models` **빈 디렉터리**, `/health` = `model_loaded:false` → 개인화 랭킹이 상시 규칙 폴백. 🔴 `/health` 가 `status:ok` 를 반환해 **프로브·ArgoCD 는 Healthy 로 보인다** |
| 크롤러 `/dev/shm` | Docker 기본 64MB | **전용 emptyDir(Memory) 없음**, 코드에 `--disable-dev-shm-usage` 도 없음 | 갭. 지금까지 안 터졌을 뿐 근본 대응 없음 |

### 8.6 CronJob 전환 — `timeZone` 을 쓴 근거가 실장애다

compose 의 상주 sleep 루프 + 호스트 root crontab 이 전부 K8s CronJob 으로 넘어갔다. 라이브 **21개, 전부 `timeZone: Asia/Seoul`**.

compose 시절 근거가 원문으로 남아 있다(`deploy/crontab.fb-pollers:8-13`):

> `CRON_TZ=Asia/Seoul` 을 썼으나 **Debian vixie cron 3.0pl1 이 `CRON_TZ` 를 파싱하지 않고**(cronie 확장), 게스트 TZ 가 UTC 라 **전 스케줄이 의도보다 9시간 일찍 돌았다** — 오아시스 딜은 리셋 직후(15/17시 KST)를 노린 건데 실제론 새벽에 돌아 **수확 1건**. 요일도 하루 밀렸다(일→토).

`CronJob.spec.timeZone` 이 이 UTC 환산 우회를 없앴다. 스케줄 근거는 전부 앱 도메인에서 나온다 — 오아시스 딜 소스 리셋 15:00/17:00 +5분 · 점심 피크(11-12) 회피로 13:10 · 컬리는 Playwright 라 심야 1회 · 레시피 크롤(05:00) → Kafka → refiner 드레인 대기 후 06:30 재색인.

### 8.7 netpol — 허용목록이 곧 데이터소스 인벤토리다

티어별 default-deny 는 표준 `NetworkPolicy`(9개), **외부 목적지는 전부 Cilium `toFQDNs`**(10개). 이유: 표준 netpol 은 IP/CIDR 만 다루는데 OAuth·Gemini·크롤 대상이 전부 CDN 뒤라 **IP 고정이 원리적으로 불가능**하다. Cilium DNS 프록시가 DNS 응답에서 IP 를 학습해 TTL 동안만 허용한다.

허용 FQDN 전수가 **앱 소스의 실제 호출처와 1:1 대응한다** — 카카오·구글 OAuth · Vertex/Gemini · Bedrock · 컬리(`*.kurly.com` 와일드카드 = Playwright 가 끌어오는 CDN 서브도메인) · 오아시스 · 만개의레시피 · S3(barman).

🔴 **드롭된 데이터소스(KAMIS·COOKRCP01·EPIS)는 목록에 없다** — 사문화 코드가 남아 있지만 되살리면 **조용한 성공이 아니라 Cilium drop 으로 드러난다.** 즉 netpol allow-list 가 사실상 "살아 있는 데이터소스 인벤토리" 로 기능한다.

비-FQDN 특수 허용 2건: pg → `toEntities: kube-apiserver` · **kubelet 프로브가 istio-proxy `:15021` 로 rewrite 되지 않고 파드 포트로 직접(소스=노드 IP) 오기 때문에 노드 서브넷 `ipBlock: 192.168.0.0/24` 가 필요**하다.

🔴 **검증 방법론 — 이걸 모르면 netpol 검증이 전부 거짓 양성이 된다.** 메시 안 파드에서 맨 TCP `connect()` 는 Istio iptables 가 `127.0.0.1:15001` 로 REDIRECT 하므로 **정책과 무관하게 항상 성공한다.** 실제 검증은 **TLS 핸드셰이크까지 완료**해야 한다. 실측으로 확인했다 — 미허용 도메인은 맨 connect 즉시 성공, 핸드셰이크는 6초 후 timeout.

### 8.8 표준과 다르게 한 결정

1. **Pooler 전면 적용이 아니라 4종 예외** — transaction 풀링에서 세션 기능은 에러가 아니라 **조용한 무효화**로 깨진다
2. **Redis master Service 를 안 쓰고 앱을 고쳤다** — 인프라를 고칠 수 없으니(오퍼레이터가 ordinal-0 고집) 앱 4곳을 고쳤다
3. **servable 게이트를 색인 시점 → 쿼리 시점으로** — CDC 는 전건 복제라 색인 시점 배제가 성립하지 않는다
4. **ES 를 커스텀 이미지로 재패키징** — ECK 는 오퍼레이터가 파드를 만들어 "기동 후 플러그인 설치" 자리가 없다. 빌드 시 `elasticsearch-plugin list | grep -q analysis-nori` 로 검증한다. P2 당시 서빙 인덱스가 plugin을 쓰지 않던 부채는 T-3의 `recipes_live → recipes_v2`로 해소됐다(§8.3)
5. **account 에 CPU limit 없음** — bcrypt 는 버스트가 본질, CFS 스로틀 = 로그인 병목 재발
6. **TSC 를 replica 수에 따라 다르게** — replica 1 은 soft(hard 면 노드 포화 시 Pending), HPA 받는 것만 hard 2계층
7. **CronJob 을 KST 로 선언** — 스케줄이 앱 데이터 소스 시각에 묶여 있다(§8.6)
8. **netpol egress = FQDN 화이트리스트** (§8.7)
9. **미사용 FQDN 을 의도적으로 유지** — 유료 AI API 백엔드 전환(api_key ↔ Vertex) 롤백 레버
10. **`automountServiceAccountToken: false` 를 앱 전역에 걸고, 그 대가로 자체 K8s 관측 기능을 끈 채 출하** — `operations` 의 증거 수집기가 토큰 경로를 못 찾아 `OPERATIONS_KUBERNETES_EVIDENCE_ENABLED=false`. 🔴 **결정으로 기록된 곳이 없다 — 매니페스트 env 값 하나로만 존재한다**
11. **RWX 를 볼륨 삭제로 회피** — 회피는 성공, 대체(MinIO)는 미완(§8.5)

---

## 9. 트러블슈팅 — 폭발반경 상위 3건

선정 기준 = **(동시에 영향받은 호스트·서비스 수) × (지속시간) × (데이터 위험)**. 후보 13건에서 3건을 골랐다. **4위는 Kafka `KAFKA_LOG_DIRS` 미배선**(2024-10-26부터 잠재 → 07-21 recreate 로 토픽 4개 전멸. 유실 0 은 운이었다).

각 건에서 **재발 방지가 지금 라이브에 실제로 남아 있는지**까지 확인했다. 문서에만 있는 것은 그렇게 표시했다.

### 9.1 물리 하이퍼바이저 A(`.12`) 무흔적 급사 3회 — 근인 미확정

**언제·무엇·어디까지** — 2026-07-19 17:03 · 07-21 18:09:45 · 07-21 23:49:52 (KST). 세 번 다 **패닉·OOM·MCE·I/O 에러 없이** 로그가 끊기고 **8~15시간** 꺼져 있었다(수동 전원 투입). `.12` 위에 4-VM 전부가 있었으므로 **앱·데이터·CI·모니터링이 동시에 정지**, 누적 다운타임 **24~45시간**.

**2차 피해 3건이 여기서 파생됐다** — 이게 폭발반경을 1위로 만든 이유다:

| 2차 피해 | 내용 |
|---|---|
| `redis-pgsync` AOF 손상 | **PGSync 16시간 무알람 크래시루프** |
| Tempo OOM | **12~13초 간격 8회**, 매회 anon-rss 781,440 kB(오차 128 kB 이내) → 급사로 루프가 "끝났다" |
| Tempo 블록 손상 | 그 순간 쓰이던 **블록 15개의 `meta.json` 이 0바이트** → 압축·보존 **33시간 정지, 384회 반복, 무알람** |

**근인 — 미확정.** 발열 가설은 약화됐다(냉각 후 유휴 61~67°C, `_crit_`=100, thermal throttle·MCE 0건). "정체불명 디스크 읽기 폭주"(390~400 MB/s · 9,230 IOPS · util 99% · 28분 · 2회)도 별건으로 미규명이다.

**복구** — 수동 전원 투입 + 컴포넌트별 개별 복구. Tempo 손상 블록은 **삭제가 아니라 `/var/tmp/tempo-corrupt-20260723/` 로 이동**한 뒤 재생성해 `blocklist_length=515` 를 회복했다(증거 보존).

**재발 방지 — 라이브 확인분**

| 방어 | 라이브 |
|---|---|
| 하이퍼바이저 온도·디스크 감시 | `job="hypervisor"` **2 타깃 UP**, 실값 57/58°C |
| 알람 5종 | `MpHypervisorTempHigh`·`TempCritical`·`TempCritAlarm`·`ExporterDown`·**`DiskReadBurst`**(`>100 MiB/s` 5m) |
| 🔴 **클러스터 밖 증거 싱크** (핵심) | 호스트 C `/var/log/mp-hostwatch/{fb-proxmox,mp-proxmox-b}.log` **라이브 기록 중**. `mp-hostwatch-beacon.timer` **active, 1분 주기**(`state=up age=53s`) |
| IO 폭주 워처 | `.12`·`.22` 양쪽 `mp-ioburst-watch.service` **active+enabled**. 🔴 **실제로 발동한 덤프가 있다** — 호스트 B `burst-20260802T230013Z.txt` **189줄**, `dev=sdb read_mbs=114.13 threshold=100` + PSI·PID별 io 델타·`qm list` |
| Tempo 2차 피해 대응 | `MpTempoBlocklistIndexBroken` = `absent(tempodb_blocklist_length) and on() (up{job="tempo"}==1)` — **"죽지 않고 조용히 일 안 하는" 상태를 정확히 겨눈다** |

**탐지 — 당시 없었다.** Prometheus 가 `.12` 위 VM 이라 급사와 함께 죽었다. **구조적으로 자기 자신의 전면 장애를 관측할 수 없었다.** 지금은 **관측자를 클러스터 밖(호스트 C)에 두어** 해결됐고 설계 근거가 커밋에 남아 있다 — *"호스트 B 가 죽으면 기록·수신·발화가 동시에 죽어 **증거가 0** 이 된다"*.

🔴 **다만 그 사고의 원본 데이터는 소멸했다** — `.11` Prometheus TSDB(07-16~07-28, 급사 3회·온도 추이 원본)가 **P4 에서 사본 없이 파괴**됐다(트레이드오프로 명시됨).

### 9.2 호스트 B 비-ECC RAM 결함 → 조용한 메모리·디스크 오염 (07-28 ~ 07-29)

**언제·무엇·어디까지** — 3국면으로 번졌다:

1. **07-28 01:12~03:19 UTC · master VM** — 서로 다른 바이너리가 랜덤 주소에서 크래시. **GPF 10건** + helm segfault + **kube-apiserver SIGSEGV 2회** + etcd 크래시
2. **같은 날 저녁** — **etcd WAL `walpb: crc mismatch`** = 램 오염이 **디스크까지 도달**. 컨트롤플레인 크래시루프
3. **07-29 · worker-b1 확산** — 이번엔 "읽는 바이트가 실제로 달라지는" 형태. 같은 파일이 파드마다 **5가지 다른 해시**(`7daf3866`→`e6dad178`→`5ea5dc9b`→`06d3451d`→`613d9689`), alloy(471MB)가 b1 에서만 **21시간 크래시루프**

**범위 = K8s 컨트롤플레인 전체 + 워커 1대 + P2 착수 1.5일 지연**(memtest 가 선행조건으로 승격됐다).

**근인 — 확정.** `stressapptest` 10분(b1 VM 내부 4GB) → **hardware incidents 396,320건**. `dmidecode` = DDR4 16GB×2, **`Error Correction Type: None`(비-ECC)** → **MCE/EDAC 무기록이 무죄 증거가 아니었다.** 램 교체 후 동일 조건 재검사 **0건**, 3-VM 동시 33.2TB 전송 PASS, memtest86+ PASS.

**복구 — 파괴적 작업 앞에 증거를 남긴 순서가 핵심이다**: ① 직전 스냅샷(`snap-20260728-3-premtest.db`, sha256 양측 검증) ② kubelet stop ③ `ctr` 로 `etcdutl snapshot restore`(호스트에 `etcdutl` 이 없어도 이미지로 실행) ④ 파손 `member` → **`member.bad` 로 보존**(삭제 아님) ⑤ kubelet start → 컨트롤플레인 1/1, 노드 3 Ready, **유실 0**. b1 은 손상 스냅샷 7개를 chainID 로 지목해 purge → 재다운로드. 최종 = **물리 RAM 교체**.

**재발 방지 — 라이브 확인분**

| 방어 | 라이브 |
|---|---|
| 🔴 **비트로트 카나리** (문서에 없는 실물) | `kube-system/mp-bitrot-canary-b1`·`-b2` CronJob **`*/30` KST, 미정지**. 512MB 고정 blob 을 **O_DIRECT(저장 경로) vs 페이지캐시(메모리 경로) 두 갈래로 SHA256 재읽기**, b2 = 대조군 |
| etcd 스냅샷 → S3 | `mp-etcd-backup.timer` **active**, 최근 성공 확인, etcd 2,573 keys / 94 MB. 사고 당시 수동 스냅샷 8개도 S3 에 보존 |
| etcd at-rest 암호화 | 07-31 IaC 편입 |
| KSM 영구 비활성 (호스트 **B**) | **성립** — `.22`: `ksm/run=0`, `pages_shared=0`, `ksmtuned` disabled+inactive |
| GPF 기준선 | master·b1 모두 `dmesg` GPF/segfault **0** (uptime 4d20h) |

**탐지 — 당시 알람 0.** master 크래시는 사람이 `dmesg` 를 봐서, b1 오염은 **alloy 가 우연히 카나리 역할**을 해서 21시간 뒤에 드러났다 — `containerd` 는 pull 시점 digest 만 보고 **압축해제된 스냅샷은 재검증하지 않는다.**

🔴 **지금도 남은 구멍 2개**:
- **카나리 실패를 보는 알람이 없다.** 우리 알람 35개 중 `mp-bitrot-canary` 를 참조하는 식이 **0건**이다. **탐지 장치는 세웠는데 통보 경로가 비어 있다.**
- 🔴 **호스트 A(`.12`)는 `ksmtuned` enabled+active 이고 `pages_shared=346,494`(≈1.35 GB 병합 중)다.** 수칙이 호스트 B 한정이라 규칙 위반은 아니지만, **PG primary·Redis primary·ES·Kafka 가 앉은 호스트에서 같은 기전이 살아 있다.**
- 잔재: master `/var/lib/etcd/member.bad` 가 아직 있다(문서는 "memtest 결론 후 삭제" 라 적었고 memtest 는 07-29 에 끝났다).

### 9.3 파드 DNS `.local` search 하이재킹 → **그 수정 시도가 낸 13분 전면 DNS 장애** (2026-08-02)

이 건은 **두 국면**이고, 두 번째가 첫 번째보다 폭발반경이 컸다.

**국면 1 — 잠재 5일+.** 노드 DHCP 가 준 search 도메인 `local` + `ndots:5` 때문에 4-dot FQDN(`<svc>.<ns>.svc.cluster.local`)이 **절대이름 취급을 못 받고** 4번째 후보 `...cluster.local.local` 이 ISP 리졸버까지 나갔다. ISP 가 NXDOMAIN 을 **공인 IP `218.38.137.28`** 로 하이재킹했다. 실측 **13/60 = 21.7%**.

| 실피해 | 내용 |
|---|---|
| `tempo-0` | **5일간 421회 재시작** — 기동마다 MinIO ListObjects 가 공인 IP 로 나가 i/o timeout → store init fail-fast |
| `loki` | 우연히 정답을 뽑아 살아 있던 **미폭발 지뢰** |
| `alloy` | **전 클러스터 로그를 평문 HTTP 로 push** = 오해석 시 로그 본문 외부 유출 경로 |
| `cloudflared` 오리진 | 오해석 시 **외부 유입 전면 차단** |

🔴 **역설적으로 "제대로" 완전수식이름을 쓴 쪽만 깨졌다.** 짧은 `.svc` 를 쓴 쪽은 안전했다.

**국면 2 — 전면 장애 13분.** 정본 조치로 CoreDNS 에 `local:53 { template ANY ANY { rcode NXDOMAIN } }` 를 넣자 **클러스터 DNS 가 전면 정지**했다. `kafka-combined-0` 파드 재생성 **3회**.

**근인 — 양쪽 다 확정.**
- 하이재킹 = 노드 search 의 `local` + `ndots:5` + ISP NXDOMAIN 하이재킹의 합
- 전면 장애 = 🔴 **`local` 이 `cluster.local` 의 상위 존**이라 CoreDNS 최장매칭이 `pg-rw.data.svc.cluster.local` 조차 `local` 블록으로 보내고, template 이 전부 NXDOMAIN 을 답하며 **`kubernetes` 플러그인은 호출조차 되지 않는다**

🔴 **왜 사전 검증이 못 잡았는지까지 확정됐다** — `--dry-run=server` 는 **ConfigMap 스키마만**, CoreDNS `reload` 는 **Corefile 문법만** 본다. **둘 다 존 계층의 의미를 보지 않는다.** 두 검증을 통과했고 둘 다 무의미했다.

**복구** — Corefile 원복. Kafka **ISR 3/3 · under-replicated 0** 완전 회복. 라이브 확증: `kafka-combined-0` `restartCount=3`, `finishedAt 2026-08-02T11:33:01Z`(exitCode 1)가 조치 커밋 창(20:05~20:40 KST) 안에 정확히 들어간다.

**재발 방지 — 🔴 구조적 방어가 사실상 없다**

| 조치 | 상태 |
|---|---|
| 4-dot FQDN → `.svc` 단축형 5곳 | ✅ 머지. config 레포 잔여 4-dot = 주석 1줄 |
| CoreDNS Corefile | ✅ **stock 상태**(정상 원복) |
| 존 가드 | ❌ **배포 안 함** — 위험이 확정됐으므로 |
| 가드 감시 알람 `MpCoreDNSLocalGuardMissing` | ❌ **명시적으로 제거** |
| config CI 의 `svc.cluster.local` 금지 린트 | ❌ **제안만, 미구현** |
| 근본 조치 = kubelet `resolvConf` 로 노드 search 에서 `local` 제거 | ❌ **제안만, 미구현** |
| 파드 `dnsConfig`/`ndots` 오버라이드 | ❌ app ns 전 Deployment **0건** |
| 🔴 남은 4-dot | `observability/lgtm-grafana-datasources` 가 **`loki…svc.cluster.local:3100`·`tempo…:3200`** 을 그대로 쓴다 — 커밋의 "레포 내 잔여 0건" 검증이 이 ConfigMap 을 놓쳤다 |

**탐지** — 국면 1 은 **5일간 탐지 없이** 갔다(Tempo 421회 재시작이 알람으로 이어지지 않았다 — `MpTempoDown` 과 `absent()` 가드가 **사후 신설**이다). 국면 2 는 사람이 즉시 알았다(적용 직후 전면 장애). **현재도 DNS 오해석 자체를 보는 알람은 0건**이고, **근인(노드 DHCP search 도메인)이 그대로 살아 있어 노드 재구축·kubeadm 업그레이드로 되살아난다.**

### 9.4 세 사고가 공통으로 말하는 것

| 교훈 | 근거 |
|---|---|
| **관측자를 관측 대상 안에 두면 전면 장애를 못 본다** | 9.1 — Prometheus 가 `.12` 위 VM 이라 급사와 함께 죽었다. 해결 = 증거 싱크를 클러스터 밖으로 |
| **"기록이 없다"가 "문제가 없다"가 아니다** | 9.2 — 비-ECC 라 MCE/EDAC 무기록이었고, 그게 오히려 오진을 유도했다 |
| **스키마·문법 검증은 의미를 보지 않는다** | 9.3 — `--dry-run=server` 와 `reload` 둘 다 통과하고 둘 다 무의미했다 |
| **가장 아픈 건 죽는 게 아니라 조용히 일 안 하는 것이다** | 9.1 Tempo 33시간·PGSync 16시간·9.2 b1 21시간·9.3 Tempo 5일 — 넷 다 **무알람**이었다 |
| **탐지 장치를 세우고 통보를 안 붙이면 없는 것과 같다** | 9.2 — 비트로트 카나리는 30분마다 도는데 그 실패를 보는 알람이 0건이다 |

---

## 10. 이전 후 남은 미완 (라이브 확정)

이전 자체의 사고는 아니지만 **이전 과정에서 생겨 지금도 남아 있는 것**이다. 전부 2026-08-03 실측이다.

| # | 무엇 | 라이브 증거 |
|---|---|---|
| 1 | 🔴 **OTEL 샘플링 회귀 10% → 100%** | compose 는 `OTEL_TRACES_SAMPLER=parentbased_traceidratio` / `ARG=0.1`. K8s 는 config 레포 전체에 `SAMPLER` **0건** → SDK 기본 `always_on`. compose 주석에 **2026-07-21 Tempo OOM 크래시루프로 1.0→0.1 로 내린 이력**이 있고, K8s 에서 그 완화가 사라졌으며 **Tempo 는 07-28~08-02 닷새간 죽어 있었다.** 즉 "왜 낮췄는지"가 compose 파일 주석에만 있었고 매니페스트로 옮겨오지 않았다 |
| 2 | 🔴 **`ranking-serving` 모델 미도달** | `/models` 빈 디렉터리, `/health` = `model_loaded:false`. `/health` 가 `ok` 라 프로브·ArgoCD 는 Healthy |
| 3 | 🔴 **`mp-ocr-config-canary` 4시간+ 크래시루프** | `Init:1/2`, 재시작 28회. 사이드카 로그 = `failed to sign CSR … dial tcp 10.111.58.185:15012(istiod): i/o timeout`. **istiod 는 정상**(Ready, 재시작 0). 근인 = Job 파드 라벨에 **`tier: backend` 가 없어** istiod egress 를 여는 `mp-backend` netpol 에 안 걸리는데, Cilium `mp-ocr-egress-fqdn` 은 `app in (ocr, ocr-config-canary)` 로 **이 파드를 선택해 egress default-deny** 를 만들고 그 목록에 istiod 가 없다. **막는 쪽만 받고 여는 쪽은 못 받았다.** 대조군 = 정상인 `mp-ocr` 파드는 `tier=backend` 를 갖는다 |
| 4 | 🔴 **`descheduler` Application `InvalidSpecError`** | `application repo https://kubernetes-sigs.github.io/descheduler/ is not permitted in project 'platform'`. 라이브 `sourceRepos` 7개에 그 URL 이 **없다** — 손 patch 로 넣었던 값이 조정으로 사라졌다. CronJob 워크로드는 남아 30분마다 정상 실행(`evicted 0`)되지만 **Application 은 더 이상 수렴하지 않는다** |
| 5 | 🔴 **`rollouts` Application `Unknown`** | `namespace 'argo-rollouts' do not match any of the allowed destinations`. ADR-0001 선행조건이 Ansible 에 커밋됐으나 **미적용** |
| 6 | **`mp-video` 가 OTEL env 를 못 받았다** | 파드 기동(08-02 10:34Z)이 CM 갱신(22:07 KST)보다 앞선다. `envFrom` 은 기동 시 1회 평가이고 Reloader·`checksum/config` 가 **0건** |
| 7 | **OTEL 계측 커버리지 7/12** | `opentelemetry-instrument` 래퍼가 chat·ocr·operations·video Dockerfile 에 없다. CM 값만으로는 스팬이 안 나간다 |
| 8 | **`ocr`·`video` Redis 가 Sentinel-aware 아님** | env 는 받지만 **코드가 읽지 않는다**. 정상 상태에서는 안 드러나고 **장애 중에만 갈라진다** |
| 9 | **`operations` Loki·Tempo 기본값이 4-dot FQDN** | `loki.observability.svc.cluster.local:3100`. `ndots:5` 라 절대이름 취급이 안 되고 `…cluster.local.local` 이 ISP 로 나가 **NXDOMAIN 이 공인 IP 로 하이재킹**된다(실측 21.7%). 두 기능이 기본 False 라 잠복 |
| 10 | **`dnsConfig ndots:2` 동반 조치 미이행** | 커밋 `f477d14` 가 약속했으나 config 레포에 `ndots` **0건**. 앱측 완화(`warm_dns` + connect 10s)만 들어갔고 근본 비용은 계속 지불 중 |
| 11 | **frontend nginx 에 죽은 Docker resolver** | 라이브 파드에 `resolver 127.0.0.11` 인데 파드 nameserver 는 `10.96.0.10`. 라이브 로그 `recv() failed (111) … resolver: 127.0.0.11:53` → `499`. Gateway 가 `/api/*` 를 직접 라우팅하므로 무해하나 이미지에 죽은 설정이 남아 있다 |
| 12 | **`chat` Bedrock 백엔드 잠복 갭** | `BedrockGenerator` 가 완성돼 있고 factory 가 값을 수용하는데 `mp-chat-egress-fqdn` 은 Gemini 만 허용한다. ConfigMap 한 값을 뒤집는 순간 **CNP 동반 변경 없이는 조용히 타임아웃** |
| 13 | 🔴 **Harbor·Jenkins 백업 — 버킷 자체가 없다** | 문서는 `s3://mp-harbor-backup-ap2` 매일 02:20 KST · `s3://mp-jenkins-backup-ap2` 02:40 KST 라고 적는다. 실제로는 호스트 C 에 **두 유닛 다 없고**, 계정에 **두 버킷 자체가 존재하지 않는다**(있는 것 = `mp-backup-ap2`·`mp-etcd-backup-ap2`·`mp-image-backup-ap2`·`mp-source-backup-ap2`). Harbor 백업 실물 **0건**, Jenkins 는 07-29 수동 1건(157 MiB)뿐. **"타이머가 없다"보다 한 단계 더 나쁘다** |
| 14 | 🔴 **ES exporter 가 없어 대시보드 1장이 영구 빈 패널** | `detail-elasticsearch.json` 이 `elasticsearch_indices_*` 를 질의하는데 **ES exporter 워크로드·스크레이프 잡이 존재하지 않는다**(`sum by(job)(up)` 에 없고 `get all -A` 에도 없다). 같은 이유로 `MpES*`·`MpKafka*`(브로커)·`MpMinIO*` 알람도 **0건** |
| 15 | 🔴 **호스트 A 에 KSM 이 살아 있다** | `.12`: `ksmtuned` **enabled+active**, `pages_shared=346,494`(≈1.35 GB 병합 중). 수칙이 호스트 B 한정이라 위반은 아니지만 **PG primary·Redis primary·ES·Kafka 가 앉은 호스트**다(§9.2) |
| 16 | **비트로트 카나리에 통보 경로가 없다** | CronJob 은 30분마다 도는데 우리 알람 35개 중 `mp-bitrot-canary` 를 참조하는 식이 **0건**(§9.2) |
| 17 | **`member.bad` 잔재** | master `/var/lib/etcd/member.bad` — 문서는 "memtest 결론 후 삭제"라 적었고 memtest 는 07-29 종결됐다 |
| 18 | 문서 stale | `platform/policies/README.md` 는 "netpol 이 아직 없다"고 적는데 같은 디렉터리에 default-deny 가 있다 · `ai-services-deploy-spec.md §3` 은 OCR 잡상태를 "Redis 이관 전"으로 적는데 이관은 완료됐다 · `§4.1` 롤 표는 `ioburst_watch` 가 "호스트 C 에만" 있다고 적는데 실제로는 **하이퍼바이저 `.12`·`.22` 양쪽에서 active** · `CLAUDE.md` 내부 도구 **6종 → 실제 7종**(`argo.mealbong.cloud` 누락) |
| 19 | ⚠️ **커밋 메시지만 읽으면 오독되는 것** | `4dbebae` 는 *"🔴 실호스트 미적용"* 이라 적었으나 **적용됐다** — 30분 뒤 `425cf39`("실배포에서 잡은 버그 3건")가 후속으로 붙었고 지금 라이브로 돈다. **커밋 본문의 상태 표기는 그 커밋 시점의 것이고 후속 커밋이 뒤집을 수 있다** |

---

## 11. 다음 사람을 위한 검증 명령

이 워크북의 숫자를 재확인하는 경로다. **문서를 믿지 말고 이걸 돌릴 것.**

```bash
# 타임라인 — 오브젝트 생성 시각이 문서보다 강한 증거다
kubectl get nodes -o custom-columns=NAME:.metadata.name,CREATED:.metadata.creationTimestamp
kubectl get ns,application -A --sort-by=.metadata.creationTimestamp

# 리소스 — 사이드카를 빼먹지 않으려면 describe node 를 볼 것
kubectl describe node <n> | grep -A8 'Allocated resources'
kubectl get resourcequota,limitrange -A
kubectl top nodes; kubectl top pods -A --containers

# 스토리지 — thick 프로비저닝이라 VG 여유가 실제 제약이다
kubectl exec -n openebs <lvm-plugin-pod> -- vgs

# HA — 선언이 아니라 현재 분포를 볼 것
kubectl get pods -A -o wide
kubectl get pdb -A -o custom-columns=NS:.metadata.namespace,N:.metadata.name,ALLOWED:.status.disruptionsAllowed
kubectl get cluster,elasticsearch,kafka,redisreplication -n data

# 검색 인덱스 — 현행 stable alias와 실제 analyzer/DR replica를 함께 본다
ES=$(kubectl get secret -n data es-es-elastic-user -o jsonpath='{.data.elastic}'|base64 -d)
kubectl exec -n data es-es-b-0 -c elasticsearch -- curl -s -u "elastic:$ES" \
  'http://localhost:9200/_alias/recipes_live'                              # backing=recipes_v2
kubectl exec -n data es-es-b-0 -c elasticsearch -- curl -s -u "elastic:$ES" \
  'http://localhost:9200/recipes_live/_settings?filter_path=**.analysis'    # 비어 있으면 회귀
kubectl exec -n data es-es-b-0 -c elasticsearch -- curl -s -u "elastic:$ES" \
  -X POST 'http://localhost:9200/recipes_live/_analyze' \
  -H 'Content-Type: application/json' -d '{"field":"name","text":"돼지고기김치찌개"}'
kubectl exec -n data es-es-b-0 -c elasticsearch -- curl -s -u "elastic:$ES" \
  'http://localhost:9200/_cat/indices/recipes?format=json&h=health,index,pri,rep,docs.count' # green/1/1/5900

# netpol — 맨 connect 는 항상 성공한다. TLS 핸드셰이크까지 가야 한다
kubectl exec -n app <pod> -c <app> -- python3 -c \
  "import ssl,socket;ssl.create_default_context().wrap_socket(socket.create_connection(('www.google.com',443),timeout=8),server_hostname='www.google.com')"
```

---

*이 워크북은 2026-08-03 라이브 실측 기준이다. 인프라 현황의 정본은 [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md), 이전 결정·근거는 [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md) 이다. 이 문서는 그 둘을 대체하지 않고, **이전 과정을 재현·학습 가능한 형태로 남기는 것**이 목적이다.*
