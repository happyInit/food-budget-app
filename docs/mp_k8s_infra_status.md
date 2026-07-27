# 인프라 현황 (Kubernetes) — SSOT

> **팀 공유용 인프라 상태 단일 소스.** `CLAUDE.md §인프라`가 이 문서를 가리킨다. **인프라 변경 시 여기를 갱신한다.**
> 최초 작성 2026-07-24 (SSOT 이관) · **2026-07-27 전면 갱신** — 계획 검증 인터뷰의 결정 18건 반영(단계 재편·호스트 확보·CI 전환 완료 등). 결정 근거 = [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)
>
> 🔴 **클러스터는 아직 존재하지 않는다** (P0 미착수). 단 **선행조건은 전부 충족됐다** — 호스트 B·C 확보 완료, CI 는 이미 호스트 C 의 Jenkins 로 전환 완료(구 계획의 "P0.5"가 선행 완료됨).
> **오늘의 운영·장애대응·접속은 [`docker-infra-status.md`](./docker-infra-status.md)를 본다** — 실가동 중인 것은 그쪽이다.
>
> | 용도 | 문서 |
> |---|---|
> | **인프라 SSOT (목표 아키텍처·구축 현황)** | **이 문서** |
> | 이전 결정·근거·컷오버 절차 (why/how) | [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md) |
> | 현행 실가동 시스템 (지금 돌아가는 것) | [`docker-infra-status.md`](./docker-infra-status.md) |
>
> **역할 분담**: 이 문서는 *무엇이 서 있는가(what)*, 플랜은 *왜 그렇게 정했고 어떻게 옮기는가(why/how)*. 결정을 바꿀 때는 플랜에서 바꾸고 여기로 반영한다.

---

## 0. 한눈에 요약

| 항목 | 상태 |
|---|---|
| 물리 호스트 A (`192.168.0.12`, i7-10700F/32GB) | ✅ 가동 (현재 Docker 트랙 운용 중) |
| **물리 호스트 B** (클러스터용, 32GB) | ✅ **가동** — Proxmox 9.1.1(호스트명 `k8s1`) @ `.22` · **템플릿 9002 이관 완료** (2026-07-27) |
| **물리 호스트 C** (CI/CD·레지스트리, `.10`) | ✅ **가동** — Harbor·Jenkins·SonarQube. 구 fb-ci-harbor VM 의 `.10`·인증서 승계 |
| **CI = Jenkins** (호스트 C, 레포 루트 `Jenkinsfile`) | ✅ **전환 완료** — pollSCM 1분 폴링. GH Actions 러너 은퇴(트리거 비활성) |
| **Harbor 신규 프로젝트** `mealplanning/` | ✅ 앱 10종 `:1.1.9` 베이스라인 (구 `food-budget/*` 이미지는 구 VM 과 함께 소멸 예정 — 백필 안 함) |
| K8s 클러스터 (master ×1 + worker ×4, **노드 램프** §1) | ⬜ 미착수 |
| Cilium (CNI · kube-proxy 대체 · WireGuard) | ⬜ 미착수 |
| Istio (sidecar 메시 + Gateway API) | ⬜ 미착수 |
| MetalLB (L2, 풀 `.14`–`.16`) | ⬜ 미착수 |
| OpenEBS LVM LocalPV (동적 프로비저닝) | ⬜ 미착수 |
| MinIO (Loki·Tempo 백엔드 · 모델 아티팩트 — **단일 replica·B 고정**) | ⬜ 미착수 |
| 데이터 티어 in-cluster (PG·ES·Redis·Kafka HA + PGSync) | ⬜ 미착수 |
| 관측 (kube-prometheus-stack + metrics-server) | ⬜ 미착수 (현재 fb-monitoring VM 가동 중) |
| ArgoCD (CD, GitOps — **유일한 CD**) | ⬜ 미착수 |
| External Secrets Operator (**Kubernetes provider**) | ⬜ 미착수 |
| S3 오프사이트 백업 | ⬜ 미착수 |

**착수 트리거는 충족.** 남은 것은 팀 타임라인 정합뿐([§6 미결](#6-미결)).

---

## 1. 목표 토폴로지 — 노드는 램프로 늘어난다

**호스트 A 의 RAM 은 현행 VM 과 K8s 워커를 동시에 수용하지 못한다** (31GiB 에 VM 26GB 상주). 그래서 노드는 한 번에 5대가 아니라 **컷오버 단계를 따라 3→4→5 대로 늘어난다**:

```
P0        Host B 만 3노드:  master 6GB + worker-b1 11GB + worker-b2 11GB
          (Host A 는 현행 프로덕션 VM 그대로)
P1 후     구 .10 VM 파괴 + .9 정지 → Host A 여유 ~12GB
          → worker-a1 (~12GB) 생성 = 4노드  ← §2.1 HA 배치가 이때부터 실물 성립
P4        .8·.11 해체 → worker-a1 을 14GB 로 확장 + worker-a2 (14GB) 생성 = 5노드 완성
```

```
최종:  Host A (.12, 32GB)             Host B (.22, 32GB)
       ├─ worker-a1  14GB             ├─ master     6GB
       └─ worker-a2  14GB             ├─ worker-b1 11GB
                                      └─ worker-b2 11GB

Host C (.10 — 클러스터 밖, K8s 미참여 · VirtualBox 위 Ubuntu 24.04)
└─ Harbor · Jenkins(컨트롤러 + 고정 docker 에이전트) · SonarQube   ✅ 가동 중
```

⚠️ **master 는 6GB — 3GB 로 잡지 말 것**(2026-07-27 상향). apiserver 메모리는 노드 수가 아니라 **watch 캐시**(전역 watch 컨트롤러 10개 · ArgoCD LIST-all)가 정하고, taint 를 걸어도 DaemonSet 이 master 에 올라와 0.6–1GB 를 먹는다 → 상주 추정 **2.3–4.4GB**. 사후 증설은 단일 컨트롤플레인 재부팅을 요구한다. 계산 근거 = [플랜 §2.2](./mp_k8s_infra_migration_plan.md).

⚠️ **Proxmox 호스트명이 직관과 반대다**: 호스트 B = `k8s1` · 호스트 A = `k8s2`. 무해하지만 콘솔·태스크 로그를 볼 때 혼동 주의. 호스트 B 는 **Proxmox 클러스터 없이 스탠드얼론**으로 운용한다(2026-07-27 확정 — 2노드 quorum 함정 + "컨트롤플레인 장애가 타 계층으로 번지는 결합 회피" 원칙. clusterjoin 시도 흔적은 해체 완료). 템플릿 `9002` 사본이 B 에 있어 K8s 노드 VM 클론 소스로 쓴다.

🔴 **호스트 C 의 VirtualBox 어댑터는 반드시 브리지 모드.** NAT 면 `.10` 을 LAN 에서 못 받고, **클러스터 노드가 Harbor 에서 이미지를 못 당겨 배포가 전면 실패**한다. (현재 브리지로 가동 중 — 어댑터 설정 변경 금지.)

**배치 원칙** — 무흔적 급사 3회(2026-07-19·07-21×2)가 **전부 호스트 A**였다. 그래서:
- **master·quorum 다수(ES 2 · Kafka 2 · Redis Sentinel 2) = 호스트 B**
- **PG·Redis primary = 호스트 A** (페일오버 중재자가 B에 있으므로 primary가 B면 B 급사 시 자동 승격 불가)
- **Prometheus·MinIO = 호스트 B 고정** (A 급사 시 관측·모델 경로 생존 — 로컬 PV 라 노드 고정)

→ *실측된 장애 모드*(A 급사)에서 자동 복구가 성립한다. 근거 = [`mp_k8s_infra_migration_plan.md §2.2·§5.2`](./mp_k8s_infra_migration_plan.md).

### 1.1 IP 주소 배치 (192.168.0.0/24)

| 대역 | 용도 | 상태 |
|---|---|---|
| `.8` · `.9` · `.11` | 현행 VM 3대 (fb-data · fb-app-ai · fb-monitoring) — `.9`=P1 후, `.8`·`.11`=P4 에서 회수 | 사용 중 |
| `.10` | **물리 호스트 C** (Harbor·Jenkins·SonarQube — 구 fb-ci-harbor VM 에서 IP·인증서 승계, **영구**) | ✅ 사용 중 |
| `.12` | 물리 호스트 A (Proxmox `k8s2`) | 사용 중 |
| `.14`–`.16` | **MetalLB IP 풀** (`.14` 공개 GW · `.15` 내부 GW · `.16` 카나리·업그레이드 일시 병행용 여유) | 예약 |
| `.17`–`.21` | K8s 노드 5대 | 예약 |
| **`.22`** | **물리 호스트 B** (Proxmox `k8s1`) | ✅ 사용 중 |

🔴 **공유기 DHCP 범위가 `.14`–`.21`(예약 대역)과 겹치면 ARP 충돌**("가끔 안 됨" 형 장애) — 시작 주소를 **`.23` 이상**으로. **P0 착수 전 확인 항목.** *(`.13` 은 타인 장비(VirtualBox 게스트)가 상주해 예약에서 제외 — 구 계획의 호스트 B 예약분이었으나 `.22` 로 변경. `.177` 예약도 폐기 — 호스트 C 가 `.10` 승계.)*

---

## 2. 컴포넌트 구성 (확정 사양)

결정 근거는 전부 [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)에 있다. 여기는 *무엇으로 정해졌는가*만 적는다.

| 계층 | 구성 | 상태 |
|---|---|---|
| **컨트롤플레인** | **kubeadm 직접** (Kubespray 기각 — 플랜 §2.5) · master ×1 (VIP/HAProxy 불필요) · etcd 스냅샷 → S3 · **metrics-server**(HPA 전제) | ⬜ |
| **CNI** | Cilium (eBPF) · kube-proxy 대체 · `socketLB.hostNamespaceOnly=true` 🔴 | ⬜ |
| **라우팅 모드** | VXLAN 으로 시작 → **P0 iperf3 측정 후 P1 전 확정·락** (예상 native) | ⬜ |
| **노드 간 암호화** | Cilium WireGuard (파드 간 — 호스트 네트워크까지 덮으려면 `nodeEncryption` 별도) | ⬜ |
| **외부 LB** | MetalLB (L2) · 풀 `.14`–`.16` · **`type: LoadBalancer` 는 게이트웨이 전용 — 상시 2개**(공개 `.14` + 내부 `.15`), 개별 서비스 노출 금지 | ⬜ |
| **남북 L7** | Gateway API · 구현체 = Istio · TLS 종단 | ⬜ |
| **서비스 메시** | Istio **sidecar** (ambient 기각) · **app ns 11 워크로드**(FastAPI 9 + frontend + ranking-serving)만 주입 · data·pipeline ns 제외 | ⬜ |
| **스토리지** | OpenEBS LVM LocalPV (CSI · RWO · WaitForFirstConsumer) — **RWX 금지** | ⬜ |
| **오브젝트** | MinIO(내부: Loki·Tempo 백엔드·모델 아티팩트) — **단일 replica(SNSD)·호스트 B 고정·"전 컴포넌트 HA"의 문서화된 예외** + AWS S3(백업, ap-northeast-2) | ⬜ |
| **접근통제** | 표준 NetworkPolicy + Cilium CNP FQDN egress (Gemini — chat·ocr) | ⬜ |
| **Secret** | ESO — **백엔드 = Kubernetes provider**(전용 소스 ns 의 Secret, 적재는 Ansible←secrets.yml). EKS 시 백엔드만 Secrets Manager+IRSA 로 교체 | ⬜ |
| **인증서** | cert-manager (온프렘 CA Issuer → EKS 시 ACM/LE 로 교체) | ⬜ |
| **관측** | **kube-prometheus-stack**(Prometheus Operator · ServiceMonitor · PrometheusRule — 알림규칙 20개 이관) · Prometheus 로컬 PV·**호스트 B 고정** · Loki·Tempo(MinIO 백엔드) · Grafana·Alertmanager 는 기존 설정 승계 · Hubble · Istio telemetry | ⬜ |
| | *Mimir 기각(규모 1~15%·알림경로 길어짐 — 플랜 §9.1) · P1 과도기 = in-cluster Prometheus **agent 모드** → `.11` remote_write(알림 자산 무손실)* | |
| **CI** | **Jenkins** (호스트 C · 레포 루트 `Jenkinsfile` · 고정 docker 에이전트) — CATALOG 14 이미지 + `RELEASE_VERSION` 릴리스 태깅 + pytest·Trivy 게이트 + SonarQube(측정) · 트리거 = pollSCM 1분(웹훅/Tunnel 은 로드맵) | ✅ **가동** |
| **CD** | **ArgoCD 가 유일한 CD** (GitOps · 별도 config 레포 · overlays/onprem·eks · **config 레포 핀은 `:sha`** — `:latest` 금지). Jenkins 는 과도기에도 배포하지 않는다 → **P2 전까지 앱 변경 반영 = 수동** | ⬜ |
| **레지스트리** | Harbor (호스트 C `.10`) · 프로젝트 **`mealplanning/`** · 앱 트랙 베이스라인 `:1.1.9` (파이프라인 트랙 1.1.10+ 과 별개) | ✅ **가동** |
| **CronJob 시간대** | `spec.timeZone: Asia/Seoul` — 현행 크론탭의 UTC 환산(vixie-cron `CRON_TZ` 미지원 우회)을 KST 로 복원 | ⬜ |

### 2.1 데이터 티어 (in-cluster · P2 에서 구축)

| | 구성 | 배치 | RAM |
|---|---|---|---|
| **PG** (CloudNativePG) | primary + standby · **비동기 복제** 🔴 | primary=A · standby=B | 2×2 = 4GB |
| **ES** (ECK) | 3 노드 · `number_of_replicas: 1` · 🔴 **인증 켬 + HTTP TLS 끔**(암호화는 WireGuard 담당 — PG-SSL 비채택과 동일 논리) · **nori 커스텀 이미지**(`mp-elasticsearch-nori`) | B에 2 · A에 1 | 3×1.5 = 4.5GB |
| **Kafka** (Strimzi) | KRaft combined 3 · RF=3 · `min.insync.replicas=2` 🔴 · `auto.create.topics.enable=false` | B에 2 · A에 1 | 3×1 = 3GB |
| **Redis** | primary + replica + Sentinel ×3 · **비영속 유지** 🔴 | primary=A · Sentinel B에 2 | ~1.2GB |
| **Pooler** (PgBouncer) | CNPG `Pooler` CRD · `transaction` 모드 · replica 2 + PDB 🔴 | A·B 분산 | ~0.3GB |
| **PGSync** | Deployment **replicas=1 고정**(복제 슬롯=단일 소비자) · `pg-rw` **직접 접속**(Pooler 우회 — LISTEN/NOTIFY) · PriorityClass 는 app 급(서빙 인덱스 생산자) | — | ~0.3GB |
| **redis-pgsync** | 비영속 Deployment 1 — **앱 Redis 와 통합 금지**(AOF 사고 격리 교훈) | — | ~0.1GB |
| | | **합계** | **~13.4GB** |

> **CNPG·ECK 는 클라우드 서비스가 아니다.** 이름의 "Cloud"는 *cloud-native*(K8s 네이티브)를 뜻하며, 둘 다 **우리 클러스터에 설치하는 오퍼레이터**다. 매니지드(RDS·OpenSearch·MSK)로 갈아타지 않는다.

### 2.2 네임스페이스 (메시 경계 = ns 경계)

| ns | 담는 것 | 메시 |
|---|---|---|
| `app` | FastAPI 9 + frontend + **ranking-serving** = **11 워크로드** | **ON** |
| `data` | PG·ES·Kafka·Redis(오퍼레이터 생성) + **PGSync·redis-pgsync** | OFF |
| `pipeline` | Kafka 컨슈머 4 + CronJob 11 + **ranking-retrain** | OFF |
| `observability` · `argocd` · `*-system` | 관측·CD·오퍼레이터 | OFF |

*youtube(영상 추출)는 워크로드가 아니다 — `ml/video-recipe/` 는 코드만 존재하고 어느 서비스에도 배선돼 있지 않다(미통합). 통합 시점에 배선·ns 를 결정한다.*

---

## 3. 🔴 구축 시 반드시 지킬 것 (사고 이력 기반)

전부 **실제로 겪은 사고**에서 나온 항목이다. 상세 = [`docker-infra-status.md §7`](./docker-infra-status.md) · [`mp_k8s_infra_migration_plan.md §10`](./mp_k8s_infra_migration_plan.md).

- **Kafka**: `auto.create.topics.enable=false` · `KafkaTopic` CRD 가 토픽 생성의 **유일 경로** · **PV 실사용 검증**
  - 근거: 2026-07-20 브로커 자동생성이 `create_topics.py`를 무력화(1파티션 사고) · 2026-07-21 `KAFKA_LOG_DIRS` 미배선으로 recreate 시 **토픽 전멸**
- **Cilium**: `socketLB.hostNamespaceOnly=true` — 없으면 Istio 사이드카가 가로챌 ClusterIP가 사라져 **mTLS가 조용히 깨진다**
- **Redis**: 영속성(AOF/RDB) **끄기** — 2026-07-22 호스트 급사 → AOF 손상 → PGSync 16시간 크래시루프(무알람)
- **PG**: 2 인스턴스에서 **동기 복제 금지** — standby 사망 시 primary 쓰기 정지
- **DB 커넥션**: HPA 를 켜면 파드마다 풀이 생겨 `max_connections`(100)에 부딪힌다 → **CNPG `Pooler`(transaction) 가 HPA 의 전제.** psycopg3 prepared statement 충돌·PGSync LISTEN/NOTIFY 우회 = P2 검증항목 (`mp_k8s_infra_object_spec.md §4.5`)
- **ES**: 노드 `vm.max_map_count=262144` (ECK 기동 전) · **ECK 는 인증 강제** — 앱 3곳(recipe·chat db.py + `pipelines/ingest/_db.py`) basic_auth 필요, PGSync 는 env 2개
- **NetworkPolicy**: default-deny 시 CoreDNS(53)·istiod(15012) egress + kubelet probe ingress 예외 필수 · **pipeline ns → data ns**(PG·Kafka) 허용 잊지 말 것
- **DHCP**: 공유기 할당 범위가 `.14`–`.21`(예약 대역)과 겹치지 않을 것, 시작 주소 `.23` 이상 (§1.1)
- **호스트 C 인벤토리**: `[ci]` 그룹(= `vms` 자식)으로 관리한다 — base 롤은 VirtualBox 대응 완료(qemu-guest-agent 스킵), `group_vars/ci.yml` 에 `docker_data_disk` **의도적 명시됨**(2026-07-27). 디스크 구성을 바꾸면 그 값을 먼저 갱신할 것. *(구 계획의 "cicd 그룹 분리" 수칙은 이 방식으로 대체됨)*
- **호스트 C 브리지 어댑터** (§1) — NAT 면 이미지 pull 불가
- **단일 파일 bind mount**: 파일을 교체하면 inode가 바뀌어 컨테이너가 고아 inode를 계속 본다 → SIGHUP 리로드가 무력. 재생성 필요 (K8s 에서는 ConfigMap 으로 해소)

---

## 4. IaC

| 구성 | 위치 | K8s 이전 시 변화 |
|---|---|---|
| **Terraform** | [`infra/terraform/`](../infra/terraform) | 유지 — **Proxmox(A·B) 전용.** state = PG 원격 backend. **호스트 C 는 대상 아님**(VirtualBox — 프로바이더 안 씀) |
| **Ansible** | [`infra/ansible/`](../infra/ansible) | 유지 — 노드 베이스라인(sysctl·LVM VG·kubeadm 선행조건). **호스트 C = `[ci]` 그룹으로 포함**(base 롤 VirtualBox 대응 완료). 서비스 배포 롤은 ArgoCD 로 이관 |
| **Jenkins** | 레포 루트 `Jenkinsfile` + `roles/jenkins`(compose) | ✅ 가동 — CATALOG 14 이미지·릴리스 태깅. JCasC 코드화는 후속 |
| **매니페스트** | `deploy/k8s/` | ⚠️ **stale** — ECR·placeholder 시절 유물이고 앱 매니페스트는 부재. 재작성 필요 |
| **ArgoCD 선언** | 별도 config 레포 | 신규 (P0) — 이미지 핀은 `:sha` |

### 4.1 IaC 경계 — 호스트 C

**Terraform = Proxmox(A·B) 전용 / Ansible = 호스트 C 포함 전체.**

호스트 C 는 VirtualBox 라 Terraform 밖이지만 **Ansible `[ci]` 그룹으로 관리한다**(가동 중 — Harbor·Jenkins·SonarQube 전부 롤로 배포됨). 레지스트리는 클러스터 복구의 전제(이미지가 없으면 아무것도 못 뜬다)라 손구성 금지.

- 적용 롤: `base`(docker · VirtualBox 대응) · `harbor` · `ca_trust` · `team_ssh_keys` · `jenkins` · `sonarqube` · **`monitoring_agents`**(node-exporter·cAdvisor·Alloy — 2026-07-27 스킵 철회: 호스트 C 는 클러스터 밖이라 인클러스터 관측이 영원히 못 보고, Harbor 는 무감시면 안 되는 SPOF)
- **호스트 C 재구축 = 수동 VM 생성 + Ansible** — 이 한 스텝만 IaC 밖이다
- ~~`github_runner`~~ — 은퇴(Jenkins 대체, 2026-07-27 플레이에서 제거)

**백업 대상**: etcd 스냅샷 · PG(barman-cloud PITR) · ES 스냅샷 · **`JENKINS_HOME`** · Secret 암호화 사본 → 전부 S3.

---

## 5. 이전 절차 (2026-07-27 재편 — 앱 먼저)

**"상태없는 것부터"로 재편됐다** — 앱 좌표가 전부 env 라 VM 데이터 티어를 그대로 보게 할 수 있어, 데이터-먼저 안의 근거였던 "브릿지 비용"이 소멸했기 때문. 단계별 상세·롤백·체크리스트 = [`mp_k8s_infra_migration_plan.md §10`](./mp_k8s_infra_migration_plan.md).

| 단계 | 내용 | 상태 |
|---|---|---|
| 선행 | ~~호스트 B·C 확보 · CI Jenkins 전환 · Harbor 이전~~ | ✅ **완료** |
| P0 | 호스트 B 3노드 · 기반(Cilium·Istio·MetalLB·OpenEBS·MinIO·cert-manager·ESO·ArgoCD·kube-prometheus-stack·metrics-server) · **라우팅 모드 iperf3 측정·락** · 🔴 **백업·복구 경로 검증** | ⬜ |
| P1 | **앱 이전** — Gateway(`.14`)+HTTPRoute+앱 11(env=VM 데이터 좌표) → 유입 전환(nginx→GW) · **in-cluster Prometheus agent→`.11` remote_write** · `.9` 정지(🔴 `.env` 백업 필수)→파괴 · 구 `.10` VM 파괴 → **worker-a1(~12GB) 생성 = 4노드** | ⬜ |
| P2 | **데이터 티어 + 파이프라인 전환창** — PG·ES·Redis·Kafka+Pooler+PGSync 구축 · PG 복제 따라잡기 → 전환창: 프로모트 + 파이프라인 동시 전환(사전 dark-deploy) + 앱 ConfigMap 좌표 갱신 (유일한 다운타임) | ⬜ |
| P3 | **스케일** — Pooler 검증 → 앱 풀 축소 → account HPA → KEDA lag 스케일링 | ⬜ |
| P4 | 정리 — `.8`·`.11` 해체 · LGTM in-cluster 이전 · worker-a1 14GB 확장 + worker-a2 = **5노드 완성** | ⬜ |

**과도기 명시 사항**: ① P2 전까지 자동 CD 없음(앱 변경 = 수동 반영) ② P1~P2 앱 파드 egress 에 `192.168.0.8`(VM 데이터) ipBlock 허용 — P2 에서 제거 ③ 파드→VM 구간은 WireGuard 미적용(현행 compose 와 동일한 평문 — 후퇴 아님).

---

## 6. 미결

1. **이전 착수 시점** — 선행조건은 충족. 5인 역할분담·9주 타임라인과의 정합만 남음
2. **Cilium 라우팅 모드 최종** — 결정 방식은 확정(P0 iperf3 → P1 전 락), 판단 근거만 실측 대기
3. **Redis 오퍼레이터 선정** — 페일오버 시 master Service 를 실제로 갱신하는지 **P0~P2 사이 실물 검증**(앱 코드 수정 0이 요구사항 — 불가 시 chat·price Sentinel-aware 전환은 별도 이슈)
4. **PR 시점 pytest 게이트 공백** — 러너 은퇴로 GH `ci-test` 사망, Jenkins 는 main 머지 후에만 검사. 후속 = Jenkins 멀티브랜치 PR 빌드

---

*이 문서는 인프라 상태 변경 시 갱신한다. 결정을 바꿀 때는 [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)에서 바꾸고 여기로 반영한다. 현행 Docker 스택 운영은 [`docker-infra-status.md`](./docker-infra-status.md).*
