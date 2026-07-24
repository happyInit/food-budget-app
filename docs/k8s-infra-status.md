# 인프라 현황 (Kubernetes) — SSOT

> **팀 공유용 인프라 상태 단일 소스.** `CLAUDE.md §인프라`가 이 문서를 가리킨다. **인프라 변경 시 여기를 갱신한다.**
> 최초 작성 2026-07-24 (SSOT 이관)
>
> 🔴 **지금 이 클러스터는 존재하지 않는다.** 아래는 전부 **⬜ 미착수**이며, 선행조건(물리 호스트 B·C)이 미확보다.
> **오늘의 운영·장애대응·접속은 [`docker-infra-status.md`](./docker-infra-status.md)를 본다** — 실가동 중인 것은 그쪽이다.
>
> | 용도 | 문서 |
> |---|---|
> | **인프라 SSOT (목표 아키텍처·구축 현황)** | **이 문서** |
> | 이전 결정·근거·컷오버 절차 (why/how) | [`k8s-migration-plan.md`](./k8s-migration-plan.md) |
> | 현행 실가동 시스템 (지금 돌아가는 것) | [`docker-infra-status.md`](./docker-infra-status.md) |
>
> **역할 분담**: 이 문서는 *무엇이 서 있는가(what)*, 플랜은 *왜 그렇게 정했고 어떻게 옮기는가(why/how)*. 결정을 바꿀 때는 플랜에서 바꾸고 여기로 반영한다.

---

## 0. 한눈에 요약

| 항목 | 상태 |
|---|---|
| 물리 호스트 A (`192.168.0.12`, i7-10700F/32GB) | ✅ 가동 (현재 Docker 트랙 운용 중) |
| **물리 호스트 B** (클러스터용, 32GB) | ⬜ **미확보 — 이전 전체의 선행조건** |
| **물리 호스트 C** (CI/CD·레지스트리) | ⬜ **미확보** |
| K8s 클러스터 (master ×1 + worker ×4) | ⬜ 미착수 |
| Cilium (CNI · kube-proxy 대체 · WireGuard) | ⬜ 미착수 |
| Istio (sidecar 메시 + Gateway API) | ⬜ 미착수 |
| MetalLB (L2, 풀 `.14`–`.16`) | ⬜ 미착수 |
| OpenEBS LVM LocalPV (동적 프로비저닝) | ⬜ 미착수 |
| MinIO (LGTM 백엔드 · 모델 아티팩트) | ⬜ 미착수 |
| 데이터 티어 in-cluster (PG·ES·Redis·Kafka, 전부 HA) | ⬜ 미착수 |
| LGTM in-cluster | ⬜ 미착수 (현재 fb-monitoring VM 에서 가동 중) |
| Jenkins (CI, 호스트 C) | ⬜ 미착수 (현재 GitHub Actions self-hosted 러너) |
| ArgoCD (CD, GitOps) | ⬜ 미착수 |
| External Secrets Operator | ⬜ 미착수 |
| S3 오프사이트 백업 | ⬜ 미착수 |

**진행률 = 0%.** 착수 트리거는 호스트 B·C 확보이며, 시점은 미정([`k8s-migration-plan.md §11`](./k8s-migration-plan.md)).

---

## 1. 목표 토폴로지

```
Host A (기존 .12, 32GB)          Host B (신규, 32GB)
├─ worker-a1  14GB               ├─ master     3GB
└─ worker-a2  14GB               ├─ worker-b1 13GB
                                 └─ worker-b2 13GB

Host C (.177 — 클러스터 밖, K8s 미참여 · VirtualBox 위 Ubuntu 24.04)
└─ Harbor · Jenkins(컨트롤러 + 고정 docker 에이전트)
```

🔴 **호스트 C 의 VirtualBox 어댑터는 반드시 브리지 모드.** NAT 면 `.177` 을 LAN 에서 못 받고, **클러스터 노드가 Harbor 에서 이미지를 못 당겨 배포가 전면 실패**한다. (Cloudflare Tunnel 은 아웃바운드라 무관하지만 Harbor pull 은 인바운드다.)

**배치 원칙** — 무흔적 급사 3회(2026-07-19·07-21×2)가 **전부 호스트 A**였다. 그래서:
- **master·quorum 다수(ES 2 · Kafka 2 · Redis Sentinel 2) = 호스트 B**
- **PG·Redis primary = 호스트 A** (페일오버 중재자가 B에 있으므로 primary가 B면 B 급사 시 자동 승격 불가)

→ *실측된 장애 모드*(A 급사)에서 자동 복구가 성립한다. 근거 = [`k8s-migration-plan.md §2.2·§5.2`](./k8s-migration-plan.md).

### 1.1 IP 주소 배치 (192.168.0.0/24)

| 대역 | 용도 | 상태 |
|---|---|---|
| `.8`–`.11` | 현행 VM 4대 (컷오버 P6에서 회수) | 사용 중 |
| `.12` | 물리 호스트 A | 사용 중 |
| `.13` | 물리 호스트 B | ⬜ 예약 |
| `.14`–`.16` | **MetalLB IP 풀** (`.14` 공개 GW · `.15` 내부 GW · `.16` 예비) | ⬜ 예약 |
| `.17`–`.21` | K8s 노드 5대 | ⬜ 예약 |
| `.177` | 물리 호스트 C (CI/CD·레지스트리) | ⬜ 예약 |

🔴 **공유기 DHCP 범위가 `.13`–`.21`·`.177`과 겹치면 ARP 충돌**이 난다. 특히 `.177`은 기본 DHCP 풀(`.100`–`.200`)에 들 가능성이 높아 제외·정적예약이 필수다. **P0 착수 전 확인 항목.**

---

## 2. 컴포넌트 구성 (확정 사양)

결정 근거는 전부 [`k8s-migration-plan.md`](./k8s-migration-plan.md)에 있다. 여기는 *무엇으로 정해졌는가*만 적는다.

| 계층 | 구성 | 상태 |
|---|---|---|
| **컨트롤플레인** | **kubeadm 직접** (Kubespray 기각 — 플랜 §2.5) · master ×1 (VIP/HAProxy 불필요) · etcd 스냅샷 → S3 | ⬜ |
| **CNI** | Cilium (eBPF) · kube-proxy 대체 · `socketLB.hostNamespaceOnly=true` 🔴 | ⬜ |
| **라우팅 모드** | VXLAN 으로 시작 → **P0 iperf3 측정 후 P1 전 확정·락** (예상 native) | ⬜ |
| **노드 간 암호화** | Cilium WireGuard | ⬜ |
| **외부 LB** | MetalLB (L2) · 풀 `.14`–`.16` · **`type: LoadBalancer` 는 게이트웨이 1개만** | ⬜ |
| **남북 L7** | Gateway API · 구현체 = Istio · TLS 종단 | ⬜ |
| **서비스 메시** | Istio **sidecar** (ambient 기각) · app 9개만 주입 · data ns·Job 제외 | ⬜ |
| **스토리지** | OpenEBS LVM LocalPV (CSI · RWO · WaitForFirstConsumer) — **RWX 금지** | ⬜ |
| **오브젝트** | MinIO(내부: LGTM 백엔드·모델 아티팩트) + AWS S3(백업, ap-northeast-2) | ⬜ |
| **접근통제** | 표준 NetworkPolicy + Cilium CNP FQDN egress (Gemini 아웃바운드) | ⬜ |
| **Secret** | External Secrets Operator | ⬜ |
| **인증서** | cert-manager (온프렘 CA Issuer → EKS 시 ACM/LE 로 교체) | ⬜ |
| **관측** | LGTM in-cluster (저장소 = MinIO) + Hubble + Istio telemetry | ⬜ |
| **CI** | Jenkins (호스트 C) · JCasC + Jenkinsfile · Cloudflare Tunnel 웹훅 · 고정 docker 에이전트 | ⬜ |
| **CD** | ArgoCD (GitOps) · **별도 config 레포** 경유 · overlays/onprem·eks | ⬜ |
| **레지스트리** | Harbor (호스트 C = VirtualBox VM, 클러스터 밖 유지) | ✅ 가동 중(현재 `.10`) → ⬜ 호스트 C 이전 |

### 2.1 데이터 티어 (전 컴포넌트 HA, in-cluster)

| | 구성 | 배치 | RAM |
|---|---|---|---|
| **PG** (CloudNativePG) | primary + standby · **비동기 복제** 🔴 | primary=A · standby=B | 2×2 = 4GB |
| **ES** (ECK) | 3 노드 · `number_of_replicas: 1` | B에 2 · A에 1 | 3×1.5 = 4.5GB |
| **Kafka** (Strimzi) | KRaft combined 3 · RF=3 · `min.insync.replicas=2` 🔴 | B에 2 · A에 1 | 3×1 = 3GB |
| **Redis** | primary + replica + Sentinel ×3 · **비영속 유지** 🔴 | primary=A · Sentinel B에 2 | ~1.2GB |
| **Pooler** (PgBouncer) | CNPG `Pooler` CRD · `transaction` 모드 · replica 2 + PDB 🔴 | A·B 분산 | ~0.3GB |
| | | **합계** | **~13GB** |

> **CNPG·ECK 는 클라우드 서비스가 아니다.** 이름의 "Cloud"는 *cloud-native*(K8s 네이티브)를 뜻하며, 둘 다 **우리 클러스터에 설치하는 오퍼레이터**다. 매니지드(RDS·OpenSearch·MSK)로 갈아타지 않는다.

**워커 RAM 예산** — 가용 ~54GB 대비 소비 추정 ~33.7GB, 여유 ~20GB.

---

## 3. 🔴 구축 시 반드시 지킬 것 (사고 이력 기반)

전부 **실제로 겪은 사고**에서 나온 항목이다. 상세 = [`docker-infra-status.md §7`](./docker-infra-status.md) · [`k8s-migration-plan.md §10`](./k8s-migration-plan.md).

- **Kafka**: `auto.create.topics.enable=false` · `KafkaTopic` CRD 가 토픽 생성의 **유일 경로** · **PV 실사용 검증**
  - 근거: 2026-07-20 브로커 자동생성이 `create_topics.py`를 무력화(1파티션 사고) · 2026-07-21 `KAFKA_LOG_DIRS` 미배선으로 recreate 시 **토픽 전멸**
- **Cilium**: `socketLB.hostNamespaceOnly=true` — 없으면 Istio 사이드카가 가로챌 ClusterIP가 사라져 **mTLS가 조용히 깨진다**
- **Redis**: 영속성(AOF/RDB) **끄기** — 2026-07-22 호스트 급사 → AOF 손상 → PGSync 16시간 크래시루프(무알람)
- **PG**: 2 인스턴스에서 **동기 복제 금지** — standby 사망 시 primary 쓰기 정지
- **DB 커넥션**: HPA 를 켜면 파드마다 풀이 생겨 `max_connections`(100)를 넘는다(추정 270+) → **CNPG `Pooler`(transaction) 필수.** psycopg3 prepared statement 충돌·PGSync LISTEN/NOTIFY 우회 = P1 검증항목 (`k8s-object-spec.md §4.5`)
- **NetworkPolicy**: default-deny 시 CoreDNS(53)·istiod(15012) egress 예외 필수
- **ES**: 노드 `vm.max_map_count=262144` (ECK 기동 전)
- **DHCP**: 공유기 할당 범위가 `.13`–`.21`·`.177`과 겹치지 않을 것 (§1.1)
- **호스트 C 인벤토리**: `vms` 그룹에 넣지 말고 **새 그룹 `cicd` + `group_vars/cicd.yml`**. `vms` 면 `base` 롤이 `docker_data_disk`(`/dev/sdb`)를 ext4 포맷 시도한다 — `stat` 가드가 있어 디스크가 없으면 no-op 이지만, 호스트 C 는 Harbor 이미지·Jenkins 워크스페이스 때문에 전용 디스크를 붙이는 게 정상이라 **`/dev/sdb` 가 실제로 존재할 공산이 크다.** 우연히 걸리지 않게 `cicd.yml` 에서 의도적으로 지정할 것
- **호스트 C 브리지 어댑터** (§1) — NAT 면 이미지 pull 불가
- **단일 파일 bind mount**: 파일을 교체하면 inode가 바뀌어 컨테이너가 고아 inode를 계속 본다 → SIGHUP 리로드가 무력. 재생성 필요 (K8s 에서는 ConfigMap 으로 해소)

---

## 4. IaC

| 구성 | 위치 | K8s 이전 시 변화 |
|---|---|---|
| **Terraform** | [`infra/terraform/`](../infra/terraform) | 유지 — **Proxmox(A·B) 전용.** state = PG 원격 backend. **호스트 C 는 대상 아님**(VirtualBox — 프로바이더 안 씀) |
| **Ansible** | [`infra/ansible/`](../infra/ansible) | 유지 — 노드 베이스라인(sysctl·LVM VG·kubeadm 선행조건). **호스트 C 포함**(SSH 만 닿으면 되므로 하이퍼바이저 종류 무관) · 새 그룹 `cicd`. 서비스 배포 롤은 ArgoCD 로 이관 |
| **매니페스트** | `deploy/k8s/` | ⚠️ **stale** — ECR·placeholder 시절 유물이고 앱 매니페스트는 부재. 재작성 필요 |
| **Jenkins 설정** | JCasC + Jenkinsfile (Git) | 신규 |
| **ArgoCD 선언** | 별도 config 레포 | 신규 |

### 4.1 IaC 경계 — 호스트 C

**Terraform = Proxmox(A·B) 전용 / Ansible = 호스트 C 포함 전체.**

호스트 C 는 VirtualBox 라 Terraform 밖이지만 **Ansible 대상에는 포함한다.** Harbor·Jenkins 를 손으로 올리면 그 머신이 죽었을 때 **레지스트리 복구가 기억에 의존**하게 되는데, 레지스트리는 클러스터 복구의 전제(이미지가 없으면 아무것도 못 뜬다)라 특히 아프다.

- 적용 롤: `base`(docker) · `harbor`(**이미 있고 멱등**) · `ca_trust`(로컬 CA) · `monitoring_agents`(node-exporter·cAdvisor·Alloy — 관측 대상에서 빠지지 않게) · `team_ssh_keys` · `jenkins`(신규)
- **호스트 C 재구축 = 수동 VM 생성 + Ansible** — 이 한 스텝만 IaC 밖이다. 그 스텝을 문서화된 절차로 남길 것
- `qemu-guest-agent`(base 롤)는 VirtualBox 에서 무의미하다 — 해롭진 않으나 VBox 는 Guest Additions

**백업 대상**: etcd 스냅샷 · PG(barman-cloud PITR) · ES 스냅샷 · **`JENKINS_HOME`** · Secret 암호화 사본 → 전부 S3.

---

## 5. 이전 절차

컷오버는 **상태없는 것부터 점진**(P0~P6), PG만 다운타임. 단계별 상세·롤백·체크리스트 = [`k8s-migration-plan.md §10`](./k8s-migration-plan.md).

| 단계 | 내용 | 상태 |
|---|---|---|
| P0 | 호스트 B·C 증설 · 5노드 · 기반 컴포넌트 · **라우팅 모드 측정** · 🔴 **백업·복구 검증**(데이터 티어가 P1 로 앞당겨져 선행 필수) | ⬜ |
| P0.5 | 호스트 C 에 Harbor 이전 + Jenkins 구축 · GH Actions 병행 검증 후 전환 | ⬜ |
| P1 | **데이터 티어** (PG·ES·Redis·Kafka + Pooler) 구축 + VM→K8s 복제 따라잡기 | ⬜ |
| P2 | **앱 + 전환창** — 앱 9 + Gateway 배포 → 프로모트 + 유입 전환 (앱·DB 동시, 유일한 다운타임) | ⬜ |
| P3 | 파이프라인 (컨슈머·CronJob·KEDA) | ⬜ |
| P4 | fb-data VM 해체 · LGTM in-cluster 이전 · RAM·IP 회수 | ⬜ |

---

## 6. 미결

1. **이전 착수 시점** — 호스트 B·C 확보 시점과 9주 타임라인의 정합 (5인 역할분담·타임라인 미정)
2. **Cilium 라우팅 모드 최종** — 결정 방식은 확정(P0 iperf3 → P1 전 락), 판단 근거만 실측 대기
3. **Redis 오퍼레이터 선정** — 페일오버 시 master Service 를 실제로 갱신하는지 P0 실물 검증 필요(앱 코드 수정 0이 요구사항)

---

*이 문서는 인프라 상태 변경 시 갱신한다. 결정을 바꿀 때는 [`k8s-migration-plan.md`](./k8s-migration-plan.md)에서 바꾸고 여기로 반영한다. 현행 Docker 스택 운영은 [`docker-infra-status.md`](./docker-infra-status.md).*
