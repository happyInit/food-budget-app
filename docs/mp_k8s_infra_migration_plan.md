# K8s 이전 최종 플랜 (정본)

> **이 문서는 K8s 이전의 실행 정본이다.** 결정·근거·컷오버 순서를 담는다.
> 관계: 집약본 [`mp_k8s_infra_migration.md`](./mp_k8s_infra_migration.md)(기존 8개 문서에서 모은 배경) · 현행 인프라 [`docker-infra-status.md`](./docker-infra-status.md) · 설계 정본 [`design.md`](./design.md) · 백업 [`backup-strategy.md`](./backup-strategy.md)
> 작성 2026-07-23 · **2026-07-27 계획 검증 인터뷰로 대폭 갱신** — 컷오버 순서 재편(앱 먼저, §10)·CI 전환 완료 반영·결정 대기 해소분 반영
> 선행조건: **전부 충족** ✅ — 호스트 B 확보 완료 · 호스트 C(`.10`) 가동 중(Harbor·Jenkins·SonarQube, §7) · 신 Harbor `mealplanning/` 앱 베이스라인 `:1.1.9`

---

## 0. 이 플랜의 두 가지 목적

1. **서비스 명분** — 실측·실장애가 요구한 것만 도입한다. 규모에 안 맞는 기술은 그 사실을 숫자로 기각한다.
2. **EKS 이식성** — 온프렘 K8s는 종착지가 아니라 **AWS EKS로 가는 관문**이다. 모든 구성요소를 "EKS에서 무엇이 바뀌는가" 기준으로 골랐다(§8).

두 목적이 충돌할 때의 우선순위: **이식성 > 온프렘 최적화**. (예: LGTM 저장소를 로컬 PV 대신 오브젝트 스토리지로 두는 것 — 온프렘만 보면 과하지만 EKS에서 재구성이 사라진다.)

---

## 1. 결정 요약

| 영역 | 결정 | 근거 |
|---|---|---|
| 노드 구성 | master ×1 + worker ×4 (물리 2대) | 물리 2대에서 master ×3 = 가짜 HA (§2.1) |
| apiserver VIP/HAProxy | 불필요 | master ×1의 귀결 |
| etcd 백업 | S3 스냅샷 (단일노드 SPOF 보완) | §6.3 |
| CNI | **Cilium** (eBPF) | 레이어 통일 → Hubble 전량 관측 (§3.1) |
| kube-proxy | Cilium eBPF로 대체 | 〃 |
| 라우팅 모드 | ✅ **VXLAN 확정·락** (2026-07-27 실측) | CPU 천장 2.25 Gbps > 물리 링크 1 GbE → **선이 먼저 찬다.** native 로 얻는 건 MTU 3~4% 뿐이라 순단 비용을 지불할 이유가 없다 (§3.2) |
| 앱 외부 LB | **MetalLB (L2)** — 풀 `192.168.0.14-16` · Cilium LB IPAM 검토 후 기각 · **LoadBalancer 는 게이트웨이 전용, 상시 2개**(공개 `.14`+내부 `.15`) | 공유기 = BGP 불가 · Cilium L2 는 Lease(API) 의존 (§3.3·§2.3) |
| 남북 L7 | Gateway API, 구현체 = Istio | Ingress는 동결 API·표준 승계 (§3.3) |
| 서비스 메시 | **Istio sidecar** (ambient 기각) | §4 |
| 데이터 티어 | **전부 in-cluster** — PG(CloudNativePG)·ES(ECK)·Redis·Kafka(Strimzi) *(둘 다 이름에 Cloud 가 있지만 클라우드 서비스가 아니라 우리 클러스터에 설치하는 오퍼레이터다)* | §5 |
| **데이터 티어 HA** | **전 컴포넌트 HA** — PG primary+standby · ES 3 · Kafka 3(RF=3) · **Redis primary+replica+Sentinel** | 다수는 호스트 B에 (§5.2) |
| 스토리지 | **OpenEBS LVM LocalPV** (동적 프로비저닝·CSI) | EBS gp3와 동작 의미 일치 (§5.3) |
| 오브젝트 스토리지 | **MinIO**(내부: LGTM·모델) + **AWS S3**(백업) | §5.4 |
| DB 홉 암호화 | **Cilium WireGuard 켬** | 전 구간 in-cluster → 한 플래그로 전부 커버 (§6.2) |
| 접근통제 | 표준 NetworkPolicy + **Cilium CNP FQDN egress** | §6.1 |
| Secret | **External Secrets Operator** — 백엔드 = **Kubernetes provider**(비용 0·신규 인프라 0) | 백엔드 교체만으로 EKS 이식 (§6.4) |
| **ES 접근** | **ECK 인증 켬 + HTTP TLS 끔** — 암호화는 WireGuard 담당(PG-SSL 비채택과 동일 논리). 앱 3곳 basic_auth 수정 | §5.2·§6.2 |
| 관측 | **kube-prometheus-stack**(Operator·ServiceMonitor·PrometheusRule) + Loki·Tempo(MinIO) + Hubble + Istio telemetry + **metrics-server**(HPA 전제) | §9 |
| **CI** | **Jenkins** (GitHub Actions에서 교체) — ✅ **전환 완료**(호스트 C 가동·러너 은퇴) | §7 |
| **CD** | **ArgoCD** (GitOps) — Jenkins는 CD를 하지 않는다. **P2 전 자동 CD 없음(앱 변경 = 수동 반영)** | §7.3·§7.4 |
| 클러스터 밖 잔류 | **Harbor · Jenkins = 제3 물리 머신** (클러스터 2대와 분리) | 레지스트리·CI가 클러스터에 의존하면 클러스터 장애 시 복구 수단이 함께 죽는다 |
| DNS | CoreDNS | |
| vmbr1 내부망 | 미사용 (단일 NIC) | 파드 통신은 CNI 오버레이가 처리 |
| 컷오버 | **앱 먼저 (P0~P4)** — 2026-07-27 재편: 앱 좌표가 전부 env 라 데이터-먼저 안의 근거(브릿지 비용)가 소멸 | §10 |
| **노드 램프** | 3노드(B) → 4노드(P1 후 worker-a1) → 5노드(P4) — 호스트 A RAM 이 현행 VM 과 동시 수용 불가 | §2.2 |

---

## 2. 클러스터 토폴로지

### 2.1 왜 master ×1인가 — 고도화를 수학으로 기각한 지점

물리 호스트가 2대인데 master를 3개 두면 **반드시 2grafana_admin_password: "hFGkA9fryBwwzZj9HOtHCM9N"1로 몰린다.** 2개 있는 쪽 호스트가 죽으면 quorum(과반 2)이 깨져 컨트롤플레인이 정지한다. 즉 3-master는 이 조건에서 **HA 비용만 내고 HA를 못 받는 구조**다. 물리 3대가 되기 전까지 컨트롤플레인 HA는 착시이므로, 단일 master로 단순화하고 완전 HA는 물리 증설 로드맵으로 미룬다.

- **apiserver VIP(HAProxy/keepalived/kube-vip) 불필요** — 모든 노드가 `master IP:6443`을 직접 본다. VIP는 apiserver가 2개 이상일 때 필요한 컨트롤플레인 HA 장치이지 CNI/kube-proxy의 역할이 아니다.
- **master 장애 시 무엇이 죽고 무엇이 사는가** — 데이터플레인은 계속 서빙한다(기존 파드 가동·kube-proxy 대체 eBPF 맵·Istio 사이드카 라우팅 유지). 죽는 것은 *변경 능력*이다: 신규 스케줄·오토스케일·배포·재스케줄 불가. 복구 = etcd 스냅샷 + IaC 재구축.
- **발표 Q&A 대비**: etcd 스냅샷 복원 소요 시간을 1회 실측해 숫자로 보유할 것.

### 2.2 노드 배치 (RAM 예산) — 노드는 램프로 늘어난다

🔴 **"P0 에서 5노드 부팅"은 물리적으로 불가능하다.** 호스트 A(31GiB)에는 현행 프로덕션 VM 이 26GB 상주 중이라, 목표 워커 28GB(14×2)를 동시에 올릴 수 없다(합 54GB > 31GiB). 그래서 노드는 컷오버 단계를 따라 **3→4→5 대로 늘린다**:

```
P0        Host B 만 3노드 (master 6GB + worker-b1 11GB + worker-b2 11GB)
          Host A 는 현행 VM 그대로 (프로덕션 계속)
P1 후     구 .10 VM 파괴 + .9 정지 → A 여유 ~12GB → worker-a1(~12GB) 생성 = 4노드
          └ 이때부터 §5.2 의 2-호스트 HA 배치가 실물로 성립 (P2 데이터 티어의 전제)
P4        .8·.11 해체 → worker-a1 을 14GB 로 확장 + worker-a2(14GB) 생성 = 5노드 완성
```

**최종 상태:**

```
Host A (기존 192.168.0.12, i7-10700F/32GB)   Host B (.22, 32GB · Proxmox `k8s1`)
├─ worker-a1   14GB                          ├─ master      6GB
└─ worker-a2   14GB                          ├─ worker-b1  11GB
   (호스트 몫 ~2GB)                            └─ worker-b2  11GB
                                                (호스트+qemu 몫 ~4GB)

Host C (.10 — 클러스터 밖, K8s 미참여 · VirtualBox)   ✅ 가동 중
└─ Harbor · Jenkins(컨트롤러 + 고정 에이전트) · SonarQube
```

**호스트 A·B는 워커 RAM을 전액 쓴다** — Harbor·CI가 제3 머신으로 빠져 클러스터 노드와 자원 경합이 없다(§7).

**master를 신규 호스트 B에 두는 이유**: 무흔적 급사 3회(2026-07-19·07-21×2)가 **전부 호스트 A**에서 발생했다. 컨트롤플레인을 B에 두면 *실제로 일어난 장애 모드*(A 급사)에서 master가 생존해 파드 재스케줄이 작동한다 — 자가치유 데모가 가상 시나리오가 아니라 실제 장애 시나리오에서 성립한다. B 급사 시 컨트롤플레인 상실은 문서화된 한계로 수용한다.

**master RAM = 6GB (2026-07-27 상향 — 종전 3GB)** — 3GB 는 상주 추정의 *하한에만* 걸린다. 구성요소별 추정: OS·systemd 0.25–0.4 + containerd·kubelet 0.2–0.4 + etcd 0.3–0.6 + **apiserver 0.7–1.5** + controller-manager·scheduler 0.28–0.55 + **cilium-agent 0.4–0.7**(WireGuard·Hubble) + DaemonSet(istio-cni·node-exporter·로그에이전트) 0.15–0.25 = **2.3–4.4GB**. 두 가지가 "3노드니까 작아도 된다"는 직관을 깬다:

1. **apiserver 메모리는 노드 수가 아니라 watch 캐시가 정한다.** 클러스터 전역을 watch 하는 컨트롤러가 istiod · ArgoCD · Prometheus Operator · CNPG · ECK · Strimzi · KEDA · cert-manager · ESO · Cilium operator = **10개**고, ArgoCD 풀 리싱크는 LIST-all 을 친다. 3노드라도 apiserver 1GB+ 가 정상이며 리싱크·CRD 적용 때 스파이크가 붙는다.
2. **taint 를 걸어도 DaemonSet 은 master 에 올라온다**(전부 control-plane toleration 보유) → 0.6–1GB. "master = 컨트롤플레인만"이라는 계산에서 빠지는 몫이다.

정적 파드는 `system-node-critical` 이라 kubelet 이 `oom_score_adj=-997` 을 주므로 **apiserver/etcd 가 먼저 OOM 되지는 않는다.** 대신 증상이 더 지저분하다: DaemonSet 축출 → etcd 페이지캐시 회수 → fsync 지연 → 리더 플랩 → apiserver 5xx. 3GB 에서는 `--kube-reserved`/`--system-reserved` 를 의미있게 잡을 여지도 없다. 게다가 **사후 증설은 단일 컨트롤플레인 재부팅을 요구**한다(과거 apply→게스트 재부팅→initrd 파손 이력) → 생성 시점에 넉넉히 잡는 쪽이 압도적으로 싸다.

**kubelet 예약을 명시한다**(2026-07-27 적용, kubeadm `KubeletConfiguration`): `systemReserved` 512Mi + `kubeReserved` 512Mi + `evictionHard.memory.available` 200Mi. 기본값은 예약 0 · 축출 임계 100Mi 라서 노드가 꽉 차면 kubelet·containerd·sshd 가 파드와 같은 메모리를 다투다 **노드 자체를 잃는다**(파드 하나를 잃는 것과 급이 다르다). 대가는 allocatable 감소 — master ~4.9Gi · 워커 ~9.7Gi. 이 감소분은 이미 아래 예산표의 "K8s 시스템" 행이 잡고 있던 몫이다.

재원은 **B 워커에서 1GB×2**(13→11GB). B 실측 32,000MB 중 Proxmox 호스트가 idle 에 1,883MB 를 쓰고 qemu 오버헤드가 VM 당 0.15–0.3GB 이므로, 종전 배분 3+13+13=**29GB 는 이미 경계를 넘어 있었다**(스왑·KSM 에 의존).

**워커 RAM 예산 (최종 5노드 기준)** — 가용 ~50GB 대비 소비 추정 ~36GB, **여유 ~14GB**:

| 소비처 | RAM |
|---|---|
| K8s 시스템 (kubelet + Cilium agent, 워커 4대) | ~5.2GB |
| 스토리지 프로비저너 (OpenEBS LVM CSI) | ~0.5GB |
| 데이터 티어 **HA 구성** (PG 2×2 · ES 3×1.5 · Kafka 3×1 · Redis 1.2 · Pooler 0.3 · **PGSync+redis-pgsync 0.4**) | ~13.4GB |
| 관측 스택 + MinIO (Prometheus 2.5 · Loki 1 · Tempo 2 · Grafana/AM 0.4 · MinIO 1) + metrics-server·kube-state | ~7.2GB |
| 오퍼레이터 (CNPG·ECK·Strimzi·KEDA·cert-manager·ESO·Prometheus Operator) + ArgoCD | ~3.7GB |
| Istio (istiod 0.5 + GW ×2 0.4 + 사이드카 11×0.1) | ~2.0GB |
| 앱 11 워크로드 (FastAPI 9 + frontend + ranking-serving) | ~3.1GB |
| 파이프라인 컨슈머·CronJob | ~1.5GB |

### 2.3 IP 주소 배치 (192.168.0.0/24)

추가로 필요한 정적 IP 는 **5개**(K8s 노드 5대 — 호스트 B 는 `.22` 사용 확정, 2026-07-27). MetalLB 풀(§3.3)과 충돌하지 않게 대역을 미리 갈라 둔다. *(호스트 C 는 구 fb-ci-harbor 의 `.10` 을 승계해 신규 IP 가 필요 없었다. 구 계획의 예약 중 `.13` 은 타인 장비 상주로 제외, `.177` 은 폐기.)*

| 대역 | 용도 | 상태 |
|---|---|---|
| `.8` · `.9` · `.11` | 현행 VM 3대 (fb-data · fb-app-ai · fb-monitoring) — `.9`=P1 후, `.8`·`.11`=P4 회수 | 사용 중 |
| **`.10`** | **물리 호스트 C** (Harbor·Jenkins·SonarQube — IP·인증서 승계, **영구**) | ✅ 사용 중 |
| `.12` | 물리 호스트 A (Proxmox `k8s2`) | 사용 중 |
| **`.14`–`.16`** | **MetalLB IP 풀** (§3.3) | 예약 |
| **`.17`–`.21`** | K8s 노드 5대 (master + worker ×4) | 예약 |
| **`.22`** | **물리 호스트 B** (Proxmox `k8s1`) | ✅ 사용 중 |

- 🔴 **공유기 DHCP 할당 범위가 `.14`–`.21`(예약 대역)과 겹치면 안 된다.** 겹치면 공유기가 같은 주소를 단말에 나눠줘 **ARP 충돌**이 나고, 증상이 "가끔 안 됨"이라 추적이 매우 어렵다. DHCP 시작 주소를 **`.23` 이상**으로 올릴 것. **P0 착수 전 확인 항목**이다. *(`.13` 은 타인 장비(VBox 게스트) 상주 — 예약 부적합. 실사고 전례: 2026-07-27 구 fb-ci-harbor 가 onboot 자동기동으로 신 호스트 C 와 `.10` ARP 충돌 — 이런 형태의 장애다.)*

### 2.4 토폴로지 라벨 — EKS AZ로 무수정 매핑

노드에 `topology.kubernetes.io/zone` 라벨을 붙인다(Host A = `zone-a`, Host B = `zone-b`). 분산 제약은 **노드 이름 기반 anti-affinity가 아니라 `topologySpreadConstraints`** 로 작성한다. EKS로 옮기면 같은 매니페스트가 진짜 AZ 분산으로 동작한다 — 이식성이 "주장"이 아니라 코드가 되는 지점.

### 2.5 클러스터 부트스트랩 = kubeadm 직접 (Kubespray 검토 후 기각)

**전제 정정 — Kubespray 는 kubeadm 의 대안이 아니다.** Kubespray 는 내부적으로 kubeadm 을 호출하는 Ansible 자동화다. 따라서 선택지는 "kubeadm vs Kubespray" 가 아니라 **"kubeadm 을 직접 치느냐, Ansible 이 감싼 것을 쓰느냐"** 다.

| | **kubeadm 직접 (채택)** | Kubespray |
|---|---|---|
| K8s 최신 버전 | **업스트림 apt 저장소에서 즉시** | Kubespray 릴리스가 지원하는 범위 내 |
| 도구 일관성 | 우리 Ansible 롤을 직접 작성 | 이미 Ansible 을 쓰는 것과 결이 맞음 |
| 노드 추가·업그레이드 | 플레이북 직접 작성 | **플레이북 제공** |
| **Cilium 세밀 제어** | **Helm values 직접** | `cilium_*` 변수 경유 — 필요한 옵션 노출 여부 확인 필요 |
| 학습 가치 | **컨트롤플레인 부트스트랩을 손으로 이해** | 추상화가 감춤 |
| 코드베이스 | 우리 롤만 | 대형 저장소가 `infra/ansible/` 과 공존 |

**⚠️ 버전 관련 사실**: Kubespray 는 `kube_version` 으로 버전을 지정하지만 **바이너리 체크섬이 저장소에 미리 박힌 버전만** 설치된다(없는 버전을 적으면 다운로드 검증에서 실패). 릴리스마다 지원 K8s 범위가 고정되고 새 마이너까지 시차가 있다. **"최신 K8s"가 목표라면 kubeadm 직접이 항상 더 빠르다.** 정확한 지원 범위는 쓰려는 Kubespray 릴리스의 릴리스노트에서 확인할 것.

**기각 사유 2개**

1. 🔴 **Cilium 설정이 유난히 까다로운 조합이다.** 우리는 `socketLB.hostNamespaceOnly=true`(없으면 mTLS 무음 파손, §3.1) · kube-proxy 대체 · WireGuard(§6.2) · **P0 의 VXLAN↔native 전환 실험**(§3.2)까지 해야 한다. 이 옵션들이 Kubespray 변수로 전부 노출되지 않으면 **Kubespray 로 깔고 Helm 으로 덮어쓰는 이중 관리**가 되고, 그 순간 Kubespray 를 쓴 이점이 사라진다.
2. **학습 목적과 충돌한다.** `CLAUDE.md` 작업 규칙이 "손으로 이해하며"이고 이건 인프라 캡스톤이다. **5노드 규모에서 Kubespray 의 자동화 이득(대규모 노드 관리·업그레이드)은 작은데**, 발표에서 "컨트롤플레인을 어떻게 부트스트랩했는가"를 설명할 근거는 얇아진다.

**재검토 트리거**: 노드 수가 두 자릿수로 늘거나, 클러스터를 반복 재생성해야 하는 국면이 오면 Kubespray 를 다시 본다. (그때는 자동화 이득이 학습 손실을 넘는다.)

---

## 3. 네트워킹

### 3.1 CNI = Cilium, kube-proxy 대체

Cilium agent는 kube-proxy와 같은 DaemonSet이다. 배치 구조는 동일하고 내부 구현만 바뀐다.

| | kube-proxy (iptables) | Cilium (eBPF) |
|---|---|---|
| 저장 | iptables 규칙 | 커널 eBPF 해시맵 |
| 조회 | O(n) 선형 순회 | O(1) |
| 갱신 | 엔드포인트마다 체인 재작성 | 엔트리 증분 |

**우리 규모에서의 진짜 실익은 성능이 아니라 레이어 통일이다.** 서비스 ~10개·엔드포인트 수십 개 규모에서 O(1) vs O(n)은 부차적이다. 실익은 파드 라우팅·서비스 LB·NetworkPolicy를 Cilium 하나가 처리해 **Hubble이 그 결정을 전부 관측**할 수 있다는 것 — kube-proxy가 따로 돌면 iptables DNAT는 Hubble 시야 밖이다. 결과적으로 **Cilium = L3/4 주인 / Istio = L7 주인**으로 레이어가 깔끔히 갈리고, 이게 담당자 간 발표 분업 구조와도 일치한다.

- master ×1이라 kube-proxy-free 부트스트랩의 순환 문제(apiserver를 ClusterIP로 못 잡음)를 VIP 없이 해결: `k8sServiceHost=<master IP>` 직접 지정.
- 🔴 **필수 설정 — `socketLB.hostNamespaceOnly=true`**: Cilium의 socket-level LB는 `connect()` 시점에 ClusterIP를 파드 IP로 미리 해소한다. 그러면 Istio 사이드카가 가로챌 ClusterIP가 사라져 **mTLS·L7 라우팅이 조용히 깨진다**("다 정상인데 mTLS만 안 됨" 류의 디버깅 지옥). 이 한 줄이 Cilium+Istio 조합의 전제조건이다.

### 3.2 라우팅 모드 = VXLAN으로 시작

파드는 노드/LAN(192.168.0.x)과 다른 대역의 IP를 받는데, LAN 라우터는 그 대역을 어디로 보낼지 모른다. 해결책은 두 가지다.

- **네이티브 라우팅**: 포장 없이 라우팅. 물리 네트워크가 파드 대역을 알아야 한다(전 노드 같은 L2면 `autoDirectNodeRoutes`, 서브넷이 갈리면 BGP). 빠르지만 네트워크 설정에 의존.
- **터널(VXLAN)**: 파드 패킷을 UDP 8472로 한 겹 포장. LAN은 평범한 노드↔노드 UDP로만 보므로 **물리 네트워크가 파드 CIDR을 몰라도 된다.** 헤더 ~50B + 캡슐화 CPU(eBPF라 미미).

**VXLAN으로 시작하는 이유**: ① 네트워크 설정 의존성 0 ② 노드 추가·VM 이동에 강함 ③ "다른 노드 파드끼리 통신 안 됨" 부트스트랩 실패 모드를 통째로 제거. **"놀랄 일 없는 기본값"이 VXLAN**이다.

**단, 시작값일 뿐 최종값이 아니다.** 아래 두 전제가 이 플랜 안에서 바뀌면서 native 쪽 무게가 커졌다.

#### 전제 변화 ① — WireGuard를 켜면 캡슐화가 두 겹이 된다

| 조합 | 오버헤드 | 파드 MTU (1500 기준) |
|---|---|---|
| Native | 0 | 1500 |
| Native + WireGuard | ~60B | ~1440 |
| VXLAN | ~50B | 1450 |
| **VXLAN + WireGuard** | **~110B** | **~1390** |

헤더 바이트보다 **인캡/디캡 + 암호화가 CPU를 이중으로 먹는 것**이 실질 비용이다. WireGuard 채택(§6.2)이 확정된 이상 이건 상시 비용이 된다.

#### 전제 변화 ② — 데이터 티어 in-cluster 로 노드 간 벌크 트래픽이 생겼다

원래 동서 트래픽은 앱 간 HTTP 몇 개뿐이라 오버헤드가 무의미했다. 지금은 상시 대용량이 흐른다:

- **Kafka RF=3** — 프로듀스 1건마다 노드 간 복제 2회
- **ES `replicas: 1`** — 색인마다 노드 간 복제
- **PG WAL 스트리밍** — primary(A) → standby(B) 상시
- **LGTM → MinIO** — 메트릭·로그·트레이스 전량이 노드를 건너 오브젝트 스토리지로

1GbE 링크에서 이 정도 벌크가 상시 흐르면 오버헤드가 "무시 가능"에서 **"측정 가능"**으로 넘어온다.

#### 비교

| | VXLAN (터널) | Native Routing |
|---|---|---|
| 네트워크 사전조건 | 없음 — 노드끼리 UDP 8472만 닿으면 됨 | 파드 CIDR 라우팅 필요. **전 노드 같은 L2면 `autoDirectNodeRoutes=true`로 자동** |
| 오버헤드 | 헤더 50B + 인캡/디캡 CPU | **0** |
| NIC 오프로드 | 캡슐화가 체크섬·TSO/GRO 오프로드를 무력화할 수 있음(virtio 지원 편차) | **온전히 활용** |
| WireGuard 조합 | **이중 캡슐화** | 단일 |
| 와이어 디버깅 | tcpdump에 외부 헤더만 — 파드 IP 보려면 디캡 | **파드 IP가 그대로 보임** |
| 토폴로지 변화 | 노드 추가·서브넷 분리에 강함 | 같은 L2 가정이 깨지면 BGP 필요 |

> **우리 조건 확인**: 노드 VM은 호스트 A·B 양쪽 모두 `vmbr0` → `192.168.0.0/24` **단일 L2**다. `autoDirectNodeRoutes`로 **라우터·BGP를 전혀 건드리지 않고** native가 성립한다. 즉 "native는 네트워크 설정 의존"이라는 통념은 **우리 환경에선 해당되지 않는다.**

#### 🔴 결정 방식 — P0에서 측정하고 P1 전에 잠근다

**"실측 병목이 잡히면 그때 전환"은 함정이다.** 라우팅 모드 변경은 Cilium agent 재시작 + 파드 네트워크 순단을 동반하는데, 병목이 드러날 때쯤이면 PG·ES·Kafka가 이미 라이브인 P5 이후다 — **가장 비싼 시점에 하게 된다.**

1. **P0**: VXLAN으로 클러스터를 세운다(부트스트랩 변수 축소라는 원래 논리는 유효).
2. **클러스터가 뜨자마자 측정** — 워크로드가 아직 없어 순단 비용이 0인 유일한 구간이다. 파드 간 `iperf3`로 **VXLAN·native 양쪽**, 각각 **WireGuard 켠 상태**에서:
   - 처리량(1GbE 대비 실효) · CPU 사용률(인캡+암호화 비용) · 파드 MTU 실측
3. **숫자로 확정 → P1(앱) 진입 전 락.** 이후 변경하지 않는다.

~~예상은 native 채택~~ → **측정 결과 뒤집혔다. 아래가 확정이다.**

#### ✅ 확정 — **VXLAN 유지·락** (2026-07-27)

**실측**(호스트 B 내부, WireGuard 켠 상태 · 상세 = [`status §1.0.1`](./mp_k8s_infra_status.md)):

| 경로 | 대역폭 |
|---|---|
| 파드→파드 (VXLAN + WireGuard) | **2.25 Gbps**(4스트림) / **2.37 Gbps**(단일) |
| 호스트→호스트 (캡슐화·암호화 없음) | **40.2 Gbps** |

**왜 예상이 틀렸는가** — 위 §전제 변화 ①·②의 논증은 "오버헤드가 1GbE 에서 측정 가능해진다"를 전제로
native 에 무게를 실었다. 그런데 재 보니 **캡슐화·암호화를 전부 켠 상태의 CPU 천장이 2.25 Gbps 로
물리 링크(1 GbE)의 2배 이상**이다. 즉 **선이 먼저 찬다** — 이 조건에서 native 로 바꿔 얻는 처리량은 0 이다.
(단일 스트림이 4스트림과 같은 값인 것도 같은 얘기다: 코어 병렬성이 아니라 암호화·캡슐화 처리 자체가 천장.)

**native 에 남는 근거와 그 무게**: ① 패킷당 CPU 절감 — 노드가 다른 일도 해야 하므로 의미는 있으나
현재 노드 CPU 사용률이 1~10% 라 급하지 않다 ② MTU 3~4%(1390 → 1440) ③ tcpdump 가독성.
**반대편 비용**: 전환은 Cilium agent 재시작 + 파드 네트워크 순단이고, 이 플랜이 스스로 적었듯
"가장 비싼 시점에 하게 되는" 함정을 피하려면 지금 잠그는 게 맞다. **얻는 것이 3~4% 인데 순단을
지불할 이유가 없다.**

🔴 **재검토 트리거는 성능이 아니라 "링크 포화"다** — P2 직전의 **집계 대역 측정**(Kafka RF=3 +
ES 복제 + PG WAL + LGTM→MinIO 동시)에서 1GbE 가 실제로 포화하면, 그때 답은 라우팅 모드 변경이
아니라 **NIC 본딩·2.5GbE 업그레이드·배치 조정**이다. 라우팅 모드로는 3~4% 밖에 못 되찾는다.

발표 서사도 그대로 성립한다 — **"놀랄 일 없는 기본값으로 시작 → 측정 → 예상을 뒤집고 확정"**.

### 3.3 남북 인그레스

- **MetalLB (L2 모드)** — `IPAddressPool` + `L2Advertisement`. 가정용 공유기 환경이라 BGP 피어링이 불가능해 L2가 유일한 현실적 선택이다. **Cilium LB IPAM은 끈다**(IP 이중 할당 방지).
  - L2의 알려진 한계(리더 노드 1대가 인그레스 전량 수신, 페일오버 수 초)는 실측 대비 무해하다 — 500VU 피크 테스트에서 p95 12ms·CPU 18.7%로 인그레스가 병목 근처도 가지 않았다.
  - **IP 풀 = `192.168.0.14-192.168.0.16` (3개)** — 전체 주소 배치는 §2.3.

    | IP | 용도 |
    |---|---|
    | `.14` | **Istio 인그레스 게이트웨이(공개)** — 실제 서비스 트래픽 |
    | `.15` | 내부 전용 게이트웨이 — Grafana·ArgoCD·MinIO 콘솔(관리 트래픽을 공개 경로와 분리) |
    | `.16` | 예비 — 게이트웨이 업그레이드·카나리 시 신구 병행 |

    **3개면 충분한 이유**: 아래 EKS 이식 규칙(LoadBalancer = **게이트웨이 전용, 상시 2개**)이 IP 소비를 구조적으로 막는다. 나머지 노출은 전부 두 게이트웨이에 `HTTPRoute`로 호스트명·경로만 갈라 붙는다. 모자라도 **`IPAddressPool` 편집으로 무중단 확장 가능**하므로 일방통행 결정이 아니다.

#### 왜 Cilium LB IPAM이 아닌가 (검토 후 기각)

Cilium이 CNI인 이상 `CiliumLoadBalancerIPPool` + `CiliumL2AnnouncementPolicy`로 MetalLB를 대체할 수 있고, 실제로 매력적인 선택지였다.

| | MetalLB (L2) | Cilium LB IPAM + L2 Announcement |
|---|---|---|
| 추가 컴포넌트 | controller + speaker DaemonSet (~100–200MB) | **0** (Cilium 내장) |
| 데이터패스 | 도착 후는 어차피 Cilium eBPF | 전 구간 Cilium |
| 성숙도·트러블슈팅 자료 | **사실상 표준, 사례 방대** | 신생, 사례 적음 |
| **리더 선출** | **memberlist(gossip)** | **K8s Lease(API 서버 의존)** |
| EKS 이식 | 🔴 교체 | 🔴 교체 (차이 없음) |

L2 모드의 근본 한계(리더 1대가 전량 수신·초 단위 페일오버)는 **양쪽이 동일**하므로 성능으로 고를 문제가 아니다. 기각 사유는 하나다:

> 🔴 **Cilium L2 Announcement의 리더 선출은 K8s Lease 기반 = API 서버 의존이다.** master ×1인 우리 구조에서 **호스트 B(=master) 급사 시 Lease 갱신이 불가능해져 광고가 멈추면, 살아있는 호스트 A에 파드가 전부 있어도 외부 유입이 통째로 끊긴다.** 이는 §2.1에서 master ×1을 채택한 핵심 근거("master가 죽어도 데이터플레인은 계속 서빙한다")를 정면으로 뒤집는다. **컨트롤플레인 장애가 인그레스 장애로 번지는 결합**을 피하려고 광고 계층만 분리했다.

**잃는 것은 작다** — MetalLB가 소유하는 것은 **ARP 광고뿐**이고, 패킷이 노드에 도착한 뒤의 서비스 LB는 어차피 Cilium eBPF다. "Cilium = L3/4 주인"이라는 §3.1의 서사는 유지된다.

- ⚠️ **위 Lease 의존 서술은 메커니즘에서 추론한 것이므로 P0에서 실측 검증한다** — master를 강제 종료하고 외부에서 인그레스 IP로 요청이 계속되는지 확인. (MetalLB를 쓰더라도 §2.1의 전제를 검증하는 테스트이므로 어차피 해야 한다.)
- **재검토 트리거**: 물리 3대 확보로 master HA가 성립하면 Lease 의존이 문제가 아니게 되므로 Cilium LB IPAM을 다시 검토한다. BGP 가능한 라우터가 생기는 경우도 마찬가지(그때는 Cilium BGP Control Plane이 유리).
- **Gateway API, 구현체 = Istio** — `GatewayClass=istio` · `Gateway`(MetalLB LB IP 리스너 + TLS 종단) · `HTTPRoute`(`/`→frontend, `/api/*`→각 서비스). Ingress는 동결된 API이고 Gateway API가 공식 승계다. 메시가 Istio인 이상 게이트웨이도 Istio로 통일해 L7 프록시 혼용(Envoy 계열 2종)을 피한다.
- 🔵 **EKS 이식 규칙 — `type: LoadBalancer` Service 는 게이트웨이 전용이다(개별 서비스 노출 금지). 상시 2개: 공개 GW(`.14`) + 내부 GW(`.15`).** *(2026-07-27 재정의 — 종전 "딱 1개" 문구는 같은 절의 `.15` 내부 GW 설계와 자기모순이었다.)* 규칙의 실질은 **개수가 서비스 수와 무관한 상수**라는 것 — MetalLB는 EKS로 이식되지 않는 유일한 필수 교체 대상(EKS = AWS Load Balancer Controller/NLB)인데, GW 전용이면 이식 작업이 **Service 2개의 어노테이션 교체**로 끝난다(내부 GW 는 internal NLB 어노테이션 — 표준 패턴). 서비스마다 LoadBalancer를 뿌리면 이식 비용이 서비스 수만큼 곱해진다. `.16` 은 상시 GW 가 아니라 업그레이드·카나리 때 신구 병행용 풀 여유다.

---

## 4. 서비스 메시 — Istio sidecar

### 4.1 sidecar vs ambient (확정: sidecar)

| 판단 축 | 내용 |
|---|---|
| **ambient의 존재 이유** | 사이드카 수천 개의 리소스·업그레이드 비용. **우리는 사이드카가 11개고 그 문제를 갖고 있지 않다.** |
| **L7 필요성** | ambient의 경량 이점은 "mTLS만 필요할 때" 성립. 우리는 카나리·라우트별 RED·타임아웃/재시도가 채택 명분이라 ambient에서도 waypoint(=Envoy)가 필요 → 실질 격차 축소 |
| **비용 실측** | 사이드카 11×~100MB + istiod ~0.5GB + GW ×2 ~0.4GB ≈ **~2.0GB = 증설 후 총 RAM의 3%** |
| **Cilium 조합** | sidecar+Cilium은 `socketLB.hostNamespaceOnly` 한 줄로 해결되는 검증된 조합. ambient+Cilium은 ztunnel 리다이렉션과 CNI 체이닝이 얽혀 사례가 적음 → 8~9주 일정에서 리스크 |
| **학습·포트폴리오** | sidecar가 프로덕션 배포의 압도적 다수이자 공용어 |

**재검토 트리거**: 파드 수가 수백 단위로 커지면 ambient를 재검토한다. (몰라서 안 쓴 것이 아니라 알고 미룬 것 — 발표 방어선.)

### 4.2 L7을 실제로 어디서 쓰는가

메시 명분의 핵심 질문이므로 코드 근거로 명시한다.

**① 남북 — 사용자 트래픽 100%.** 현행 frontend nginx가 하는 일(`/`=정적, `/api/*`=9개 서비스 경로 프록시[location 13개], 유일 노출 포트 :80)이 그대로 Istio Gateway + HTTPRoute로 넘어온다. 모든 유저 요청이 예외 없이 L7을 거치므로, 동서 트래픽 규모와 무관하게 성립하는 최대 소비처다.

**② 동서 — 실제 배선된 HTTP 호출** (`deploy/app/docker-compose.yml` 기준):

| 호출 | env | L7이 하는 일 |
|---|---|---|
| chat → pantry | `PANTRY_BASE_URL` (기본 ON) | 타임아웃 → 되묻기 폴백을 빠르게 트리거 |
| chat → account | `ACCOUNT_BASE_URL` | 타임아웃 + 멱등 GET 재시도 |
| mealplan → ranking-serving | `RANKING_SERVING_URL` | 타임아웃이 규칙순 폴백의 트리거 속도를 결정 |
| ranking-retrain → serving `/reload` | `RANKING_RELOAD_URL` | 재시도 |

여기에 아키텍처 원칙(`CLAUDE.md`: **"크로스-서비스 데이터는 DB 조인 말고 API 호출"**)이 동서 HTTP를 늘어나는 방향으로 고정한다.

**③ 배포·관측 — 트래픽 양과 무관한 소비처.** 서비스 9개 각각의 카나리 배포(HTTPRoute weight) + 라우트별 RED 메트릭. 동서 호출이 0이어도 이건 쓴다.

> **정직한 캘리브레이션**: mTLS 자체는 L7이 아니다(ambient의 L4 ztunnel로도 된다). "mTLS 때문에 sidecar"는 틀린 논증이고, 정확한 근거는 **타임아웃/재시도 · 카나리 · 라우트별 메트릭**이다. 동서 호출 수가 현재 4곳으로 소박하다는 것도 인정하고 들어간다 — 방어선은 "최대 소비처는 남북 전량 + 전 서비스 배포이며, 동서는 API-호출 원칙 때문에 늘어나는 방향으로 고정돼 있다".

### 4.3 메시 경계

- **`app` ns 11 워크로드 = 메시 안** — FastAPI 9 + frontend + **ranking-serving**. 앱 코드 수정 0으로 mTLS·L7 관측·카나리·재시도/타임아웃 획득. *(ranking-serving 을 메시에 넣는 근거 = §4.2 표의 "mealplan→serving 타임아웃이 폴백 트리거 속도를 결정" — 메시 밖이면 그 근거가 죽는다.)*
- **data 네임스페이스 = 메시 밖 (사이드카 X)** — 오퍼레이터(CNPG/ECK/Strimzi)가 하위 워크로드·프로브·페일오버를 자기 방식대로 관리하므로 Envoy 주입이 그 가정을 깬다. PG 와이어·Redis RESP·Kafka 바이너리는 비-HTTP라 L7 이득 없이 비용·위험만 남는다. 대신 **NetworkPolicy(접근) + WireGuard(암호화)** 로 처리한다. **PGSync·redis-pgsync 도 data ns**(상대가 전부 data 안 — PG·ES·전용 Redis).
- **Job/CronJob(retrain·크롤러) = 사이드카 제외** — Job은 모든 컨테이너가 종료돼야 Complete인데 Envoy는 안 죽어 **Job이 영원히 안 끝난다.**
  - 각주: K8s 1.28+ native sidecar로 종료 문제 자체는 해결됐지만, 이 Job들의 상대는 PG·Kafka·외부 API라 메시에 넣을 이유가 애초에 없다 → 제외가 여전히 정답.
- **egress(Gemini)** = Istio가 아니라 Cilium FQDN egress 담당 (§6.1). 대상 = **chat·ocr** 파드. *(구 서술의 "youtube 파드"는 존재하지 않는다 — `ml/video-recipe/` 는 코드만 있고 어느 서비스에도 배선돼 있지 않다(미통합). 통합 시점에 워크로드·egress 를 함께 결정한다.)*

---

## 5. 데이터 플랫폼 (in-cluster)

### 5.1 배치 — 전부 클러스터 안, 워커 위

PG(CloudNativePG) · ES(ECK) · Redis · Kafka(Strimzi) 를 모두 `data` 네임스페이스에서 오퍼레이터 CR 로 운영한다*(하위 워크로드는 ES·Kafka=StatefulSet, CNPG=Pod 직접 관리 — `mp_k8s_infra_object_spec.md §8.5`)*. **fb-data VM은 컷오버 완료 후 해체한다.**

- 앱→DB = ClusterIP Service (CNPG는 `-rw`/`-ro`) + NetworkPolicy
- 분산 = `topologySpreadConstraints`로 두 존(=두 물리 호스트)에 분산 — **배치 규칙은 §5.2**
- **Kafka = KRaft combined 3노드, RF=3, persistent-claim.** 롤링 재시작 중에도 무중단이라 KEDA lag 스케일링 데모가 안정적으로 성립한다.
  - 🔴 **브로커 자동 토픽 생성(`auto.create.topics.enable`)은 끈다.** 2026-07-20 클릭스트림 개통 때 브로커 자동생성이 `create_topics.py`를 조용히 무력화해 1파티션 토픽 사고가 났다. K8s에서는 **`KafkaTopic` CRD가 토픽 생성의 유일 경로**다.
  - 🔴 **PV는 반드시 명시적으로 배선한다.** 2026-07-21에 `KAFKA_LOG_DIRS` 미배선으로 볼륨이 비어 있다가 recreate 시 **토픽이 전멸**했다. Strimzi `storage.type=persistent-claim` + 볼륨 마운트 확인을 컷오버 체크리스트에 포함한다.

### 5.2 HA 구성 — 물리 2대에서 얻을 수 있는 최대치

**전 컴포넌트를 HA로 구성한다.** 다만 물리가 2대뿐이라 *어떤 종류의 HA인지*가 컴포넌트마다 다르고, 그 차이가 배치를 결정한다.

#### 근본 제약과 그것을 유리하게 쓰는 법

quorum 기반 시스템(ES · Kafka KRaft · Redis Sentinel)은 3 멤버가 **반드시 2:1로 갈린다.** 2가 있는 쪽 호스트가 죽으면 quorum이 깨진다 — **master ×3을 기각한 것과 똑같은 수학**이다(§2.1). 물리 2대에서 이건 못 없앤다.

**하지만 어느 쪽 절반을 살릴지는 고를 수 있다.** 다수(2)를 **호스트 B**에, 소수(1)를 **호스트 A**에 둔다:

| 시나리오 | 결과 |
|---|---|
| **A 급사** (2026-07-19·07-21×2에 실제로 3번 일어난 장애) | B에 quorum 2/3 생존 → **자동 복구 ✅** |
| B 급사 (미발생) | quorum 상실 → 수동 개입 ❌ |

master를 B에 둔 것과 같은 논리다(§2.2). **실측된 장애 모드를 기준으로 배치한다**가 데이터 티어 전체에 일관되게 적용된다.

#### 컴포넌트별 구성

| | HA 방식 | 구성 | 배치 | RAM |
|---|---|---|---|---|
| **PG** (CNPG) | 오퍼레이터 중재 | primary + standby | **primary=A · standby=B** | 2×2 = 4GB |
| **ES** (ECK) | quorum (master 선출) | 3 노드 · `number_of_replicas: 1` | **B에 2 · A에 1** | 3×1.5 = 4.5GB |
| **Kafka** (Strimzi) | quorum (KRaft) | 3 노드 · RF=3 · `min.insync.replicas=2` | **B에 2 · A에 1** | 3×1 = 3GB |
| **Redis** | Sentinel (오퍼레이터 관리) | primary + replica + Sentinel ×3 | **primary=A · replica=B · Sentinel B에 2·A에 1** | ~1.2GB |
| **Pooler** (PgBouncer) | CNPG `Pooler` CRD · `poolMode: transaction` · replica 2 + PDB | A·B 분산 | ~0.3GB |
| **PGSync** (PG→ES CDC) | 해당 없음 — **replicas=1 고정**(논리 복제 슬롯 = 단일 소비자, 스케일 불가) | `pg-rw` **직접 접속**(Pooler 우회) | ~0.3GB |
| **redis-pgsync** | 해당 없음 — 비영속 1개. **앱 Redis 와 통합 금지**(AOF 사고 격리 교훈) | — | ~0.1GB |
| | | | **합계** | **~13.4GB** |

> **PGSync 주의 3가지** — ① PriorityClass 는 pipeline-low 가 아니라 **app 급**: 먹여살리는 `recipes_pgsync` 가 프로덕션 서빙 인덱스다. ② PG 프로모트 시 복제 슬롯이 새 primary 로 따라오지 않는다 — **슬롯 재생성 + 초기 재동기화가 P2 전환창 런북 항목**. ③ 컨테이너 이미지는 `mp-pgsync`(Jenkins CATALOG — 종전 `.8` 로컬 빌드의 Harbor 승격).

#### ES 접근 = 인증 켬 + HTTP TLS 끔 (2026-07-27 확정)

현행 ES 는 `security off`(내부망 신뢰)지만 **ECK 는 8.x 에서 인증을 기본 강제**하고 완전 비활성을 지원하지 않는다. 결정:

- **HTTP 계층 TLS 는 끈다**(`http.tls.selfSignedCertificate.disabled: true`) — §6.2 에서 PG-SSL 을 "WireGuard 가 있는 이상 이중투자"로 비채택한 것과 **동일한 논리**다. 앱은 CA 신뢰 처리 없이 basic auth 만 붙이면 된다.
- **인증은 켠다** — mTLS·NetworkPolicy·FQDN egress 이중방어를 발표하는 팀이 ES 만 익명이면 서사가 깨지고, EKS 이식 시 어차피 인증이 필요하다. 자격증명은 ESO Secret 으로 주입.
- **코드 영향(전수 조사)**: `services/recipe/app/db.py` · `services/chat/app/db.py` · `pipelines/ingest/_db.py` 3곳에 basic_auth 각 1~2줄 + PGSync 는 env 2개(`ELASTICSEARCH_USER/PASSWORD`) + es-exporter URI. **nori 플러그인 커스텀 이미지(`mp-elasticsearch-nori`)도 ECK 준비물**(현행도 로컬 빌드 커스텀).

#### PG만 양방향 생존한다 — primary를 A에 두는 이유

CNPG의 페일오버는 PG 내부 quorum이 아니라 **오퍼레이터(+K8s API)가 중재**한다. 그래서 primary를 **크래시가 잦은 A**에 두는 것이 역설적으로 옳다:

- **A 급사** → 컨트롤플레인(B)이 살아 있으니 오퍼레이터가 B의 standby를 승격 ✅
- **B 급사** → primary(A)가 그대로 서빙, 페일오버 자체가 불필요 ✅

primary가 B에 있으면 B 급사 시 master·오퍼레이터가 함께 죽어 **자동 승격이 불가능**해진다. Redis도 같은 이유로 primary=A다.

#### Redis HA — 왜 하는가, 그리고 함정

> **"그냥 캐시니까 없어도 된다"가 성립하지 않는다.** Redis는 chat 멀티턴 세션(`services/chat/app/db.py`)과 **price 캐시**를 담는데, 그 price 캐시는 nGrinder 200VU 포화를 해소한 대책의 절반이다(`perf-loadtest-fixes.md`). Redis가 죽으면 **해소했던 병목이 그대로 돌아온다** — 가용성 문제다.

- 🔴 **앱 코드 수정 0이 요구사항이다.** Sentinel 방식은 보통 클라이언트가 Sentinel을 알아야 해서 `services/chat/app/db.py`와 `services/price`를 고쳐야 한다. 이를 피하려면 **오퍼레이터가 "현재 primary를 가리키는 Service"를 제공**해 앱은 그 이름 하나만 보게 해야 한다.
  - **P0 검증 항목** — 오퍼레이터 후보(Spotahome `redis-operator` · OT-CONTAINER-KIT `redis-operator` 등)가 **페일오버 시 그 Service의 대상을 실제로 갱신하는지 실물로 확인**한다. 문서만 보고 확정하면 컷오버에서 터진다.
  - 확인 결과 불가하면 **폴백 = 앱을 Sentinel-aware로 전환**(chat·price 2곳). 이 경우 앱 변경이므로 별도 이슈로 뺀다.
- 🔴 **영속성(AOF/RDB)은 켜지 않는다.** 2026-07-22에 호스트 급사 → `redis-pgsync` AOF 손상 → PGSync가 16시간 크래시루프에 빠진 사고가 있었다(PR #275로 영속성 제거해 해소). 캐시·세션은 유실돼도 재생성되므로 **HA는 붙이되 영속성은 끈 상태를 유지**한다. HA의 목적은 데이터 보존이 아니라 **연속성**이다.

#### 나머지 함정 2개

- 🔴 **PG 동기 복제를 켜지 마라(2 인스턴스에서).** 동기 복제 + standby 사망 = **primary가 쓰기를 멈춘다.** HA 하려다 가용성을 잃는 전형적 함정이다. **비동기(CNPG 기본)** 로 두고 페일오버 시 수 초 손실은 S3 WAL 아카이빙(PITR, §6.3)으로 보완한다. 동기가 꼭 필요하면 인스턴스 3개 + `maxSyncReplicas: 1` 이어야 한다.
- 🔴 **Kafka `min.insync.replicas=2` 없이는 RF=3이 무의미하다.** 이게 없으면 복제본이 뒤처진 상태에서도 프로듀서가 성공 응답을 받아 장애 시 데이터를 잃는다.

### 5.3 스토리지 = OpenEBS LVM LocalPV (동적 프로비저닝)

각 워커에 전용 가상 디스크를 붙여 LVM VG를 만들고(Ansible), OpenEBS LVM CSI 드라이버로 **동적 프로비저닝**한다.

| 속성 | OpenEBS LVM LocalPV | AWS EBS gp3 | 일치 |
|---|---|---|---|
| 인터페이스 | CSI | CSI | ✅ |
| 접근 모드 | RWO | RWO | ✅ |
| 바인딩 | WaitForFirstConsumer | WaitForFirstConsumer | ✅ |
| 볼륨 확장 | 지원 | 지원 | ✅ |
| 스냅샷 | 지원 | 지원 | ✅ |
| 존 고정 | 노드 고정 | AZ 고정 | ✅ |

**동작 의미가 거의 일대일로 대응하므로 EKS 이식은 StorageClass 이름 교체로 끝난다.** 로컬 IO라 PG/ES 성능도 최상이다. 복제는 스토리지 레이어가 아니라 **DB 자체 복제**(CNPG standby·ES replica·Kafka RF=3)에 맡긴다 — 이중 복제로 인한 fsync 지연·RAM 낭비를 피하고, 노드 사망 시 복구는 **오퍼레이터 페일오버**가 담당한다(= 이 플랜의 자가치유 데모).

🔵 **이식 규칙**: 매니페스트에 `storageClassName`을 하드코딩하지 않는다. kustomize overlay 변수로 빼서 온프렘=`openebs-lvm`, EKS=`gp3`로 갈아끼운다.

### 5.4 오브젝트 스토리지 = MinIO(내부) + S3(백업)

| 용도 | 저장소 | 이유 |
|---|---|---|
| **Loki·Tempo 백엔드** | **MinIO** | 고볼륨·저가치 데이터. 실제 S3면 PUT 요청비가 누적되고, 가정망 업링크가 끊기면 관측이 중단된다 |
| 메트릭 (Prometheus TSDB) | **로컬 PV** | Prometheus 유지 결정(§9.1) — 오브젝트 스토리지를 쓰지 않는다 |
| ranking 모델 아티팩트 | **MinIO** | §5.5 |
| DB 백업 (CNPG barman-cloud·ES 스냅샷·etcd) | **AWS S3** (ap-northeast-2) | 재해복구가 생명 — 오프사이트가 본질 |

둘 다 S3 API라 EKS 이식은 **엔드포인트·자격증명 교체**뿐이다.

🔴 **MinIO = 단일 replica(SNSD) · 호스트 B nodeAffinity 고정 — "전 컴포넌트 HA"의 문서화된 예외다** (2026-07-27 확정). distributed 모드는 드라이브 4+ 가 정석이라 물리 2대에선 어차피 반쪽 HA 고 RAM·복잡도만 는다. 예외가 허용되는 근거: 소비자가 전부 지연 허용(모델=retrain 재업로드 · serving 은 mealplan 규칙순 폴백이 받침 · Loki/Tempo=168h 관측데이터)이고 **백업·DR 은 애초에 진짜 S3 라 MinIO 와 무관**하다. B 고정 근거 = Prometheus B 고정(§9.1)과 동일 + **A 급사 시 ranking-serving 이 B 로 재스케줄될 때 initContainer 가 MinIO 를 불러야 한다**(MinIO 가 A 에 있었다면 재스케줄 자체가 막힘). SC 는 `openebs-lvm`(Delete) — 담긴 게 전부 재생성 가능물.

### 5.5 🔴 `ranking-model` RWX 의존 제거 (EKS 비용 지뢰)

현행 compose는 `ranking-retrain`(쓰기)과 `ranking-serving`(읽기)이 `ranking-model` 볼륨의 `/models/ranker.pkl`을 공유한다(`deploy/app/docker-compose.yml:250,275` · `ml/recipe-ranking/SERVING.md`). K8s에서 이건 **RWX**인데 — 로컬 PV도 EBS도 RWX를 못 하고, **EKS에서는 EFS를 사서 써야 한다**(유료·고지연).

**→ 모델 아티팩트를 MinIO(S3 API)로 옮긴다.** retrain이 업로드하고, serving이 `/reload` 시 다운로드한다. 이미 `RANKING_RELOAD_URL` 푸시 고리가 구현돼 있어 훅이 준비된 상태다.

이로써 **"전 볼륨 RWO"** 규율이 서고, 이게 EBS와 정확히 같은 제약이라 이식이 무손실이 된다. 신규 RWX 요구가 생기면 이 규율 위반으로 간주하고 오브젝트 스토리지로 우회한다.

---

## 6. 보안

### 6.1 접근통제

- **표준 K8s NetworkPolicy** (L3/4) — 네임스페이스 격리·DB 접근 통제. 이식성 우선.
- **Cilium NetworkPolicy(CNP) FQDN egress** — 외부 LLM(Gemini) 아웃바운드를 도메인 단위로 통제. `chat`·`ocr` 파드만 `generativelanguage.googleapis.com`으로 허용 *(youtube 는 미통합 — §4.3 각주)*.
  - **이 서비스에서 위협 모델이 진짜인 이유**: Gemini는 유료 API이고, 이미 월 예산 상한(7,200원 · `MONTHLY_CAP_ENABLED`)과 비용 격리용 키 분리(`CHAT_GEMINI_API_KEY` ↔ `GEMINI_API_KEY`)가 구현돼 있다. 키 유출·오남용 = 실제 금전 사고다. **앱 층(예산 캡) + 네트워크 층(FQDN egress) 이중 방어**로 발표한다.
- 🔴 **default-deny 도입 시 함정**: CoreDNS(53)와 istiod(15012) egress 예외를 빼먹으면 클러스터가 조용히 마비된다. netpol 체크리스트에 명시.

### 6.2 암호화

| 구간 | 방식 |
|---|---|
| 사용자 → GW | HTTPS (Istio GW가 TLS 종단) |
| app ↔ app (동서) | mTLS (메시) |
| app → DB / 노드 간 전부 | **Cilium WireGuard** |

데이터 티어가 전부 in-cluster가 되면서 **WireGuard 한 플래그가 DB 홉을 포함한 노드 간 파드 트래픽을 투명 암호화**한다. 인증서 관리 0. (PG-SSL은 DB별 인증서·로테이션 부담이라 WireGuard가 있는 이상 이중투자 — 비채택. **ES HTTP TLS 도 같은 논리로 끈다** — §5.2.) ⚠️ 기본 커버 범위는 **파드 간** 트래픽이다 — 호스트 네트워크 구간(etcd·apiserver·kubelet)까지 덮으려면 `encryption.nodeEncryption` 별도 활성이 필요하다(내부 LAN 이라 기본은 미적용, 필요 시 P0 에서 결정).

> 하이브리드(DB를 클러스터 밖 VM에 두는 안)였다면 앱→DB 홉이 클러스터를 벗어나 WireGuard가 덮지 못했고 PG-SSL이 필요했다. **in-cluster 결정이 이 문제를 소멸시켰다** — 두 결정이 연동돼 있다.

### 6.3 백업 / DR

- **etcd 스냅샷 → S3** (master ×1 SPOF 보완). ArgoCD/GitOps가 복구를 돕지만 Git 밖 상태가 있어 스냅샷을 대체하지 못한다.
- **PG** = CNPG barman-cloud → S3 (WAL 아카이빙 + PITR)
- **ES** = 스냅샷 → S3, 매일 14시·02시, 14일 보존. **Glacier 계열 전환 금지**(도구 관리 repository 객체를 임의 이동하면 복구 저장소가 손상된다).
- **Kafka** = RF=3 + PV. S3는 Kafka PV를 대체하지 않는다. 재크롤 가능한 토픽과 그렇지 않은 토픽(클릭스트림)을 구분해 보존 정책을 정한다.
- **`JENKINS_HOME`** = S3 (잡 설정·크리덴셜·빌드 이력). JCasC로 설정을 Git에 둬도 이 상태는 파일로 남는다 (§7.2).
- **백업 자격증명 격리** — 앱 ServiceAccount에 백업 bucket 쓰기 권한을 주지 않는다. 백업 주체는 오퍼레이터(CNPG)의 전용 ServiceAccount다.

**복구 순서**: Terraform/Ansible로 노드 복구 → K8s + ArgoCD 복구 → 오퍼레이터 설치 → S3에서 PG PITR 복구 → ES 스냅샷 복원(또는 PG에서 재색인) → Redis 재생성 → 앱 재배포 → 로그인·예산·냉장고·레시피·가격비교 smoke test.

### 6.4 Secret = External Secrets Operator (백엔드 = Kubernetes provider)

현행은 `ansible/secrets.yml` + fb-app-ai에 상주하는 `.env`다. GitOps로 가면 이 모델이 성립하지 않는다.

- **ESO 선택 이유**: `ExternalSecret` CR은 그대로 두고 **백엔드만 교체**하면 EKS로 이식된다(→ AWS Secrets Manager + IRSA). 회전·감사로그도 백엔드가 제공한다.
- **온프렘 백엔드 = Kubernetes provider** (2026-07-27 확정) — 전용 소스 ns 의 K8s Secret 을 백엔드로 삼고, 적재는 Ansible 이 기존 `secrets.yml` 에서 한다. **비용 0 · 신규 상태저장 인프라 0.**
  - Vault/OpenBao 기각 — unseal·스토리지·HA 운영 부담이 이 규모 편익을 초과하고, EKS 가면 버려질 운영 지식.
  - AWS Secrets Manager 즉시 채택안 기각 — 월 $0.40/비밀 비용. EKS 전환 시점에 백엔드만 교체한다(그게 ESO 를 고른 이유다).
- Sealed Secrets는 복호키가 클러스터에 묶여 클러스터 재구축·EKS 이식 시 전량 재봉인이 필요하고 회전이 수동이라 비채택.

---

## 7. CI/CD — Jenkins(CI) + ArgoCD(CD)

**CI 전환은 완료됐다** (2026-07-27 현재): Jenkins 가 호스트 C(`.10`)에서 가동 중이고, GH Actions 러너는 은퇴(워크플로 트리거 비활성·파일 보존). **CD 는 ArgoCD 가 맡는다 — Jenkins 는 과도기에도 배포하지 않는다** (아래 §7.4).

### 7.1 명분 — 무엇을 얻고 무엇을 잃는가

> **정직한 캘리브레이션**: "빌드를 온프렘에서 돌린다"는 교체 이유가 **아니다** — 이미 self-hosted 러너로 달성돼 있고, 실행 주체는 원래 우리 것이었다. 실제로 얻는 것은 **컨트롤러(스케줄링·크리덴셜·플러그인·플러그인 생태계)까지 자체 운영**하는 것이고, 그 대가로 잃는 것이 셋 있다. 셋 다 회수 장치를 붙였다.

| 잃는 것 | 회수 장치 |
|---|---|
| **아웃바운드-온리 트리거** (GH 러너는 GitHub로 long-poll → NAT·유동 IP 무관) | **Cloudflare Tunnel** — 아웃바운드 커넥션으로 웹훅 수신. 포트포워딩 0, 공유기 무수정, Jenkins를 인터넷에 직접 노출하지 않음 |
| **config-in-git** (워크플로가 레포에 있어 DR이 공짜) | **JCasC + Jenkinsfile** — 컨트롤러 설정과 파이프라인을 모두 Git으로 되돌림 |
| **관리형 업데이트** (GitHub이 러너·러너 인프라를 갱신) | 회수 불가 — **플러그인·CVE 유지보수가 신규 부담으로 남는다**(수용) |

### 7.2 구성

- **컨트롤러 = 제3 물리 머신(Host C, `.10`)** ✅ 가동 — **VirtualBox 위 Ubuntu 24.04**, Harbor·SonarQube 와 동거, **클러스터 밖**. 클러스터가 통째로 죽어도 빌드·레지스트리가 살아 복구 수단이 보존된다(§2.2). 구 fb-ci-harbor VM 의 **`.10` IP·인증서를 승계**해 이미지 참조·CA 신뢰·secrets 가 전부 무수정으로 유지됐다. 구 VM 은 파괴 예정(구 `food-budget/*` 이미지는 함께 소멸 — 백필 안 함, 신 Harbor 는 `mealplanning/` 프로젝트 · 앱 베이스라인 `:1.1.9`).
  - 🔴 **VirtualBox 어댑터는 브리지 모드 필수** — NAT 면 `.10` 을 LAN 에서 못 받아 **클러스터 노드가 Harbor 에서 이미지를 못 당긴다**(배포 전면 실패).
  - **IaC 경계**: VirtualBox 라 **Terraform 대상이 아니지만**(프로바이더 안 씀), **Ansible `[ci]` 그룹으로 관리한다**(가동 중 — base 롤 VirtualBox 대응·`group_vars/ci.yml` 의 `docker_data_disk` 의도적 명시). 재구축 = **수동 VM 생성 + Ansible**(이 한 스텝만 IaC 밖). 상세 = [`mp_k8s_infra_status.md §4.1`](./mp_k8s_infra_status.md).
- **에이전트 = 같은 머신의 고정 docker 에이전트.** 현행 러너와 실행 모델이 동일해 이식 리스크가 최소이고, 레이어 캐시가 그대로 살아 빌드 시간이 늘지 않는다.
  - **K8s 동적 에이전트를 쓰지 않은 이유**: 이미지 빌드가 Docker를 요구해 파드에서는 Kaniko 등으로 갈아타야 하고, 빌드 부하가 클러스터 RAM을 잠식하며, 레이어 캐시를 다시 설계해야 한다. **빌드 전용 머신이 이미 따로 있으므로 얻는 게 없다.** (파드 수가 늘고 빌드가 잦아지면 재검토.)
- **트리거 = pollSCM 1분 폴링** (현행 — 노출 0). 즉시 트리거(GitHub 웹훅 → Cloudflare Tunnel)는 로드맵.
- **파이프라인 = 레포 루트 `Jenkinsfile`** — CATALOG **14 이미지**(앱 10 + ranking-serving·data-pipeline·crawler-kurly·pgsync) · 서비스별 pytest 게이트(DB-free 7종) · SonarQube(측정·비차단) · Trivy CRITICAL 게이트(차단) · `RELEASE_VERSION` 파라미터로 `:X.Y.Z` 릴리스 태깅(3태그 정책 — SERVICES 명시 강제, 트랙 별칭 `app`/`pipeline`).
- **크리덴셜 = Jenkins Credentials Store** (Harbor 계정 · GitHub 토큰 · config 레포 쓰기 키). 앱 레포 쓰기 권한은 주지 않는다(§7.3).
- 🔴 **`JENKINS_HOME`이 신규 백업 대상이다.** JCasC로 설정을 Git에 두더라도 빌드 이력·크리덴셜·플러그인 상태는 파일로 남는다 → S3 백업 대상에 추가(§6.3).

### 7.3 CI→CD 인계 — 별도 config 레포

```
개발자 push ─(pollSCM 1분 · 웹훅/Tunnel 은 로드맵)→ Jenkins
   ├ 변경감지 → pytest → 빌드 → Trivy 게이트 → Harbor push (:sha·:latest, 릴리스는 :X.Y.Z)
   └ config 레포에 이미지 태그 커밋   ← P2 에 신설 (지금 Jenkins 는 push 로 끝)
                        ↓
                  ArgoCD 감지 → 클러스터 동기화
```

🔴 **config 레포의 이미지 핀은 `:sha` 다 — `:latest` 금지.** `:latest` 는 태그가 안 변해 ArgoCD 가 감지할 변경이 없고 롤백 대상도 없다. 3태그 정책 그대로 — `:sha` = 불변 신원(GitOps 핀), `:X.Y.Z` = 릴리스 마킹, `:latest` = 수동 편의.

**왜 앱 레포가 아니라 별도 레포인가**

1. **CI 루프를 구조적으로 차단** — 앱 레포에 태그를 커밋하면 그 커밋이 다시 CI를 부른다. 경로 필터로 막을 수는 있지만, *막아야 하는 것*보다 *불가능한 것*이 낫다.
2. **배포 이력이 앱 히스토리와 분리** — "언제 무엇이 배포됐는가"가 독립된 히스토리로 남고, 롤백이 `git revert` 하나가 된다.
3. **최소권한** — Jenkins는 앱 레포에 쓰기 권한이 필요 없다.

### 7.4 GH Actions → Jenkins 이관 결과 (2026-07-27 현재)

| 현행 GitHub Actions (비활성·보존) | Jenkins 구현 상태 |
|---|---|
| `detect` 잡의 변경감지 매트릭스 | ✅ CATALOG srcs 프리픽스 + 스키마 SQL 트리거·output 제외 승계 |
| Trivy CRITICAL 게이트 (`--exit-code 1`) | ✅ 동일 (`docker run aquasec/trivy`) |
| **3태그 전략**(`:sha`·`:X.Y.Z`·`:latest`) | ✅ `RELEASE_VERSION` 파라미터 — **규칙 자체는 불변**, 트랙별 버전 독립(앱 1.1.9· / 파이프라인 1.1.10·) |
| Harbor 로그인/push | ✅ Jenkins Credentials (`harbor-cred`) |
| pytest (구 ci-test.yml — PR 게이트) | 🟡 **서비스별·main 머지 후**로 이동. PR 시점 게이트는 공백 — 후속 = 멀티브랜치 PR 빌드 |
| Trivy 결과 → node_exporter textfile 메트릭 | ⬜ 미구현 (후속) |
| `workflow_dispatch` = 릴리스 런 | ✅ 파라미터 빌드(`SERVICES` + `RELEASE_VERSION`) |
| **`.9` SSH compose 배포 + 헬스체크** | ❌ **이식하지 않는다** — 아래 |

🔴 **Jenkins 는 과도기에도 배포하지 않는다** (2026-07-27 확정 — 종전 "과도기엔 Jenkins 가 SSH compose 배포를 계속한다" 서술 폐기). 최초의 CD 는 P2 의 ArgoCD 다. 귀결:
- **P2 전까지 자동 CD 없음** — main 머지가 프로덕션(`.9`)에 자동 반영되지 않는다. 앱 변경 반영 = 수동(`.9` 에서 pull+up — 단 compose 는 구 네이밍이라 mp-* 이미지는 retag 필요). 빈도가 낮아 수용.
- 종전 체크리스트의 "과도기 이중배포 금지" 항목은 **전제가 사라져 삭제** — Jenkins 가 배포를 안 하니 이중 경로 자체가 불가능하다.

### 7.5 EKS 이식성

Jenkins는 GitHub에도 AWS에도 묶이지 않아 **이식 결합도가 GitHub Actions보다 오히려 낮다.** Harbor→ECR 전환 시 바뀌는 것은 크리덴셜과 이미지 URL뿐이다. 다만 컨트롤러가 상태저장이라, "Jenkins를 옮긴다"는 곧 **`JENKINS_HOME` 이전**을 뜻한다 — 이것이 GH Actions에는 없던 이전 비용이다.

---

## 8. EKS 이식성 감사

이 플랜의 두 번째 목적. **"온프렘에서 EKS로 갈 때 무엇이 바뀌는가"** 를 구성요소별로 확정해 둔다.

| 구성요소 | 이식성 | EKS에서 바뀌는 것 | 지금 지킬 규칙 |
|---|---|---|---|
| Gateway API + HTTPRoute | 🟢 최상 | 없음 | 이식 자산 중 가장 강함 |
| Istio (sidecar·mTLS·PeerAuthentication) | 🟢 | 없음 | |
| CNPG · ECK · Strimzi · KEDA | 🟢 | 없음 (또는 RDS/OpenSearch/MSK로 선택 전환) | 접속정보는 Secret/ConfigMap으로만 참조 |
| ArgoCD | 🟢 | 없음 | **overlays/onprem · overlays/eks 2-오버레이** |
| NetworkPolicy / CNP | 🟢 | 정책 자산 100% 보존 | |
| 백업 S3 | 🟢 | 없음 | 처음부터 진짜 S3 사용 |
| KEDA·HPA | 🟢 | 없음 (+ Karpenter 조합 가능) | |
| Cilium | 🟡 재설정 | EKS 기본은 VPC CNI → Cilium은 ENI 모드로 설치. `k8sServiceHost`를 EKS 엔드포인트로 | 정책 CRD는 그대로 |
| VXLAN | 🟡 | 동작함 (SG에 UDP 8472 허용) — 또는 ENI 모드 | |
| StorageClass | 🟡 | `openebs-lvm` → `gp3` | **SC 이름 하드코딩 금지** (§5.3) |
| 존 분산 | 🟡 | 노드 라벨 → 진짜 AZ | **topologySpreadConstraints 사용** (§2.4) |
| TLS 인증서 | 🟡 | 로컬 CA → ACM/Let's Encrypt | **cert-manager를 온프렘부터 도입**, Issuer만 교체 |
| 레지스트리 | 🟡 | Harbor → ECR | 이미지 참조를 kustomize `images:`로 외부화 |
| **Jenkins (CI)** | 🟢 | 없음 — 클러스터 밖 제3 머신에 그대로 | GitHub·AWS 어디에도 안 묶임. 이전 비용은 `JENKINS_HOME` 이동뿐 (§7.5) |
| ES `vm.max_map_count` | 🟡 | 노드 sysctl → 관리형 노드그룹 launch template user-data | 노드 부트스트랩 항목으로 문서화 |
| **MetalLB** | 🔴 교체 | AWS Load Balancer Controller (NLB — 내부 GW 는 internal NLB) | **LoadBalancer 는 GW 전용·상시 2개** (§3.3) |
| **Secret 백엔드** | 🔴 교체 | ESO 백엔드: K8s provider → Secrets Manager + IRSA | ESO 채택으로 CR은 보존 (§6.4) |
| **RWX 볼륨** | 🔴 비용 | EFS 필요 (유료·고지연) | **RWX 의존 금지** — 오브젝트 스토리지로 우회 (§5.5) |
| **LGTM 저장소** | 🔴 재구성 | 로컬 PV였다면 전면 재구성 | **오브젝트 스토리지 백엔드로 구성** (§5.4) |

**이식성을 코드로 만드는 장치**: ArgoCD `overlays/onprem` · `overlays/eks` 2개 오버레이를 처음부터 만든다. base 매니페스트는 공통이고, 위 🟡🔴 항목만 오버레이에서 다르다. "EKS로 갈 수 있다"가 문서상의 주장이 아니라 **레포에 실재하는 디렉터리**가 된다.

---

## 9. 관측

세 소스가 서로 다른 층을 답하고, 대시보드는 Grafana 한 곳에서 만든다.

| 소스 | 층 | 신호 |
|---|---|---|
| **Hubble** (Cilium) | 네트워크 L3/4 | flow 로그(허용/DROPPED), 정책 판정, 서비스 의존맵, DNS 질의 |
| **Istio telemetry** | 앱 요청 (RED) | 라우트별 RPS·p50/p99·5xx율 |
| **저장·시각화** | — | **Prometheus**(메트릭·로컬 PV) · Loki·Tempo(MinIO) · Grafana |

```
[Hubble /metrics] · [Istio /metrics] · [app /metrics]
      └→ Prometheus(스크레이프 + 저장 + 규칙평가) ─PromQL→ Grafana
  [app 로그·트레이스] └→ Alloy → Loki·Tempo (백엔드 = MinIO) → Grafana
```

- Hubble·Istio 모두 Prometheus 포맷 `/metrics`를 노출하므로 **Prometheus 스크레이프 대상(ServiceMonitor)에 추가만** 하면 된다. 신규 스택 0.

### 9.0 배포 방식 = kube-prometheus-stack (2026-07-27 확정)

Prometheus 를 **Prometheus Operator(kube-prometheus-stack)** 로 배포한다 — 단, 구성요소는 골라 쓴다: operator + Prometheus + **kube-state-metrics** + `ServiceMonitor`(대상 발견) + `PrometheusRule`(알림규칙 20개 이관 — **문법 동일, 포장만 CR**). Grafana·Alertmanager 는 번들 대신 **기존 설정 승계**.

- **plain Prometheus + `kubernetes_sd_configs` 기각** — kube-state-metrics·K8s 기본 대시보드·스크레이프 relabeling 을 전부 수제로 짜는 비용이 Operator 학습 비용을 초과한다. GitOps(ArgoCD)와 CR 상성도 Operator 쪽이 좋다.
- 단일 프로세스 Prometheus(스크레이프+저장+규칙평가 로컬 완결 — §9.1 의 Mimir 기각 논리)는 **그대로 유지된다.** Operator 는 그 Prometheus 를 *관리*할 뿐 데이터 경로를 바꾸지 않는다.
- **metrics-server 를 P0 에 함께 설치한다** — HPA 의 resource metrics API 전제(§13 HPA 카드의 빠져 있던 전제 컴포넌트).
- **P1 과도기 브릿지**: 같은 스택의 **Prometheus agent 모드**를 클러스터에 띄워 K8s 파드를 스크레이프하고 `.11` Prometheus 로 `remote_write` 한다(수신 플래그만 활성). 앱이 K8s 로 가면 `.11` 이 파드 IP 를 못 긁는 공백(nginx `/internal/metrics/*` 경로 소멸 + 파드 CIDR 은 LAN 비라우팅)을 메우면서, **알림규칙 20개·Grafana·Alertmanager 는 `.11` 에 그대로** — 알림 자산 무손실. LGTM 전체 in-cluster 이전은 P4.
  ✅ **로그 쪽 공백은 선배포로 해소**(2026-07-28) — 이 브리지는 메트릭만 커버해 K8s 앱 로그가 P1~P3 동안 `kubectl logs` 뿐이었는데, Loki·Tempo·Alloy 를 앞당겨 세워(status §4.3) **K8s 파드 로그는 P1 첫날부터 in-cluster Loki 로** 모인다. 메트릭 브리지 계획은 그대로다.

### 9.1 메트릭 저장소 = Prometheus 유지 (Mimir 검토 후 기각)

⚠️ **전제 정정** — 종전 서술은 Mimir 를 전제했으나 **현행 스택은 Prometheus** 다. 팀장 계획서의 "Mimir = LGTM 의 M" 서술을 승계하면서 현행과 대조하지 못한 것으로, **Prometheus→Mimir 전환은 결정된 바 없었다.** 실측 후 **Prometheus 유지**로 확정한다.

**실측 (2026-07-24, fb-monitoring)**

| | 값 |
|---|---|
| 활성 시리즈 | **32,653** |
| 샘플 유입 | 983/초 |
| **RSS** | **270 MB** |
| 타깃 | 34 |
| TSDB (15일) | 1.4 GB |

**K8s 이전 후 예상 ~100~200k 시리즈** (kubelet·cAdvisor 5~10k · kube-state 5~10k · apiserver ~10k · Cilium+Hubble 5~20k · **Istio 사이드카 25~75k**[지배적] · exporter ~10k). RSS 환산 **1.5~2.5GB**.

**기각 사유** — **단일 Prometheus 는 수백만 시리즈를 처리한다. 우리 예상치는 그 용량의 1~15%다.** 즉 Mimir 의 존재 이유(단일 Prometheus 로 감당 안 되는 수평 확장)가 **우리에겐 해당되지 않는다.** 그리고 대가가 크다:

- 🔴 **알림 규칙 20개 이관 리스크** — 사고 이력이 코드화된 자산이다(Kafka 토픽 전멸·Tempo 블록리스트 파손·PGSync 크래시루프·하이퍼바이저 온도/디스크)
- 🔴 **알림 경로가 길어진다** — Prometheus 는 스크레이프·저장·규칙평가가 **한 프로세스**라 로컬에서 완결된다. Mimir 는 `Alloy → remote_write → distributor → ingester → ruler` 로, **유입이 막히면 임계값 규칙이 데이터 부재로 조용히 안 울린다.** 이는 `observability-health` 그룹을 만든 계기였던 **"죽지 않고 조용히 일을 안 하는"** 실패 유형 그 자체다
- RAM +1~2GB · 장애 시 디버깅 경로 증가 · MinIO 가 알림의 전제가 됨(Tempo OOM 과 같은 계열)

**Prometheus 유지의 유일한 약점과 완화** — 로컬 PV 라 §6.3 의 노드 고정 문제가 적용된다(노드 사망 시 메트릭 가시성 상실). → **Prometheus 파드를 호스트 B 에 nodeAffinity 로 고정**한다. 급사 3회가 전부 호스트 A 였으므로 **실측된 장애 모드에서 관측이 생존**한다 — master·quorum 다수를 B 에 둔 논리와 같다.

**재검토 트리거**: 장기 보존(수개월)이 필요해지거나 단일 Prometheus 가 메모리에 막힐 때. 그때는 **Prometheus 를 유지한 채 Mimir 를 `remote_write` 장기저장으로 병행**하는 편이 알림 자산을 건드리지 않아 안전하다.

- **Loki·Tempo 는 in-cluster + MinIO 백엔드**(§5.4). Grafana·Alertmanager 설정은 현행 자산을 그대로 승계한다.
  ✅ **스택 세우기는 선배포 완료**(2026-07-28 — P4 에서 분리, 리스크 검사 후 확정): Loki·Tempo·Alloy 가 **ArgoCD Application**(platform AppProject)으로 가동, 검증까지 완료(status §4.3). 판단 근거 = ① 워커 예산표(§2.2)가 이미 Loki 1G·Tempo 2G 포함 ② 3노드가 전부 호스트 B 안이라 물리 1GbE 무관 ③ P1 로그 공백 해소. **P4 에 남는 것 = 컷오버**(알림규칙 20개·Slack 수신자·Grafana 대시보드 이관 + agent 철수 + `.11` 해체).
- 🔴 **Alertmanager Slack 웹훅 주의** — 현행 ansible 롤에서 `--limit monitoring`을 그냥 돌리면 웹훅이 삭제되는 함정이 있었다. K8s 이전 시 웹훅은 **ESO로 관리**해 이 계열 사고를 구조적으로 없앤다.
- **mTLS 활성 후 Hubble의 앱 트래픽 시야는 L3/4까지**(페이로드는 암호화). L7은 Istio 텔레메트리 담당 — 이 역할 분리를 발표에서 먼저 밝힌다.
- **네트워크 신호의 서비스 가치**: PG로의 flow 폭증(읽기 폭주 조기 탐지 — mealplan 커넥션 풀 포화 같은 패턴) · DROPPED flow 급증(정책 위반·스캔) · DNS 이상(NXDOMAIN 급증). 이 시계열은 최저가 알림에 쓰는 **통계 이상탐지에 그대로 먹여** 자동 알림으로 확장 가능하다 — AI 파트와 인프라 파트 발표를 잇는 다리.

---

## 10. 컷오버 계획 (2026-07-27 재편 — 앱 먼저)

**원칙**: 현행 compose 서비스를 죽이지 않고 옮기며, 각 단계는 독립 롤백이 가능하고 단계마다 발표용 중간 산출물이 나온다.

⚠️ **순서 재편의 경위** — 종전 계획(2026-07-23)은 "데이터 티어 먼저"였다. 그 근거는 *"앱 먼저면 selector 없는 Service + EndpointSlice 브릿지라는 버려질 작업이 필요하다"*였는데, **검증 결과 그 브릿지는 필요 없었다**: 앱의 데이터 좌표(PGHOST·ESHOST·Kafka)가 전부 env 라, K8s 의 앱이 ConfigMap 값으로 VM 데이터 티어(`.8`)를 그대로 보면 되고 데이터 컷오버 때 그 값을 Service DNS 로 바꾸면 끝이다. 원래 원칙("리스크 오름차순 — 상태없는 것부터")으로 회귀하면서 덤이 셋 생긴다: ① 데이터 티어가 옮겨갈 시점엔 클러스터가 몇 주간 실트래픽으로 검증된 뒤다(종전 안의 자인된 리스크 소멸) ② `.9`·`.10` 회수로 worker-a1 을 12GB 로 키울 수 있다(§2.2 램프) ③ 앱·파이프라인이 같은 VM 데이터를 보므로 이중 데이터 소스가 아예 안 생긴다.

보상 장치는 유지한다:
- 🔴 **백업·복구 검증은 P2 직전** (2026-07-28 P0 에서 이동 — 준비물[버킷+IAM 키] 대기로 P0 게이트에서 분리). **원칙은 동일하다: 데이터 티어 전에 증명.** 무백업 노출 창은 P2 컷오버(인클러스터 PG 가 실데이터 정본이 되는 순간)부터 생기므로, 게이트를 그 직전으로 옮긴 것이지 없앤 게 아니다. **P2 는 이 왕복 증명 없이 착수하지 않는다.**
- 🔴 **VM 데이터 티어(`.8`)는 P4 까지 살려둔다**(전환 후 정지 상태) — 문제가 나면 앱 ConfigMap 을 VM 좌표로 되돌리는 경로가 남는다.

| 단계 | 내용 | 롤백 | 산출물 |
|---|---|---|---|
| **선행** ✅ | ~~호스트 B·C 확보 · Harbor 이전(`.10` 승계) · Jenkins 전환 · GH Actions 비활성 · **호스트 B Proxmox 가동(`.22`·스탠드얼론 확정) + 템플릿 9002 이관** · 이미지 4종 초기 릴리스~~ — **완료(2026-07-27)** | — | Jenkins 파이프라인 · 신 Harbor `mealplanning/*`(앱 1.1.9·파이프라인 1.1.11·pgsync 7.1.0) · B 클론 템플릿 |
| **P0 기반** | Host B **3노드** 부팅 · Cilium(+WireGuard) · Istio(+**Istio CNI plugin**) · MetalLB · OpenEBS · MinIO · cert-manager · ESO(K8s provider) · ArgoCD + config 레포 신설 · **kube-prometheus-stack + metrics-server** · **라우팅 모드 iperf3 측정 후 락** · ~~백업·복구 경로 검증~~(→ **P2 직전** 이동, 2026-07-28) | 클러스터 폐기 (현행 무영향) | 클러스터 · 오버레이 구조 · 라우팅 모드 실측 데이터 |
| **P1 앱** | Gateway(`.14`·`.15`) + HTTPRoute + **앱 11 워크로드** 배포(env=VM 데이터 좌표 · egress ipBlock `.8` 허용) · **in-cluster Prometheus agent → `.11` remote_write** · 검증 후 **유입 전환**(nginx→GW) → `.9` 정지(🔴 **`.env` 백업 필수** — 비밀 실질 정본)·며칠 관찰 후 파괴 · 구 `.10` VM 파괴 → **worker-a1(~12GB) 생성 = 4노드** | 유입을 `.9` nginx 로 되돌림 (`.9` 는 정지 보존 — 정지 VM 은 RAM 0) | **mTLS · L7 메트릭 · 카나리 경로** · GitOps 배포 개통 |
| **P2 데이터+파이프라인 전환창** | 🔴 **선행: S3 백업·복구 왕복 증명**(2026-07-28 P0 에서 이동 — 이거 없이 착수 금지) · CNPG·ECK·Strimzi·Redis(+Pooler·PGSync) 구축(§5.2 배치) · **PG 만 스트리밍 복제**로 따라잡기(K8s→VM 아웃바운드) · ES 는 **PG 에서 재파생**(사전 배치 재색인→`recipes`) · 파이프라인 매니페스트 **사전 dark-deploy**(CronJob suspend·replicas 0) → **전환창**: VM 크론 정지·lag 0 드레인 → PG 프로모트 → 앱 ConfigMap 좌표 갱신(+ES basic_auth·`recipes` 인덱스) → 파이프라인 기동(KafkaTopic CRD·빈 토픽) → PGSync 슬롯 생성·초기 동기화 → `recipes_pgsync` 플립 | 앱 ConfigMap 을 VM 좌표로 되돌림 (`.8` 은 P4 까지 정지 보존. ⚠️ 전환창 이후 K8s PG 에 쌓인 쓰기는 역복제 경로가 없어 유실 — 롤백 결정은 전환창 직후 짧은 관찰창 안에) | **CNPG 페일오버 데모** · 파이프라인 in-cluster |
| **P3 스케일** | Pooler 반복부하 검증 → 앱 풀 축소(4개 서비스 env 화 포함) → **account HPA**(부하테스트 재검증) → **KEDA** ScaledObject(컨슈머 0↔N) | HPA·KEDA 끄기 (배포 경로 무영향) | **HPA** · **KEDA lag 스케일링** · **Sentinel 페일오버 데모** |
| **P4 정리** | `.8`·`.11` 해체 · **LGTM 컷오버**(스택은 ✅ 2026-07-28 선배포 — 남은 것 = 알림규칙·Slack·대시보드 이관 + agent 철수) · worker-a1 14GB 확장 + worker-a2 생성 = **5노드** · RAM·IP 회수 | — | 최종 토폴로지 |

**컷오버 체크리스트 (사고 이력 기반)**

*P0*
- [ ] **공유기 DHCP 할당 범위가 `.14`–`.21` 과 겹치지 않는지(시작 `.23` 이상) 확인** (ARP 충돌 → "가끔 안 됨" 형 장애, §2.3) — **P0 착수 전**
- [ ] Cilium: `socketLB.hostNamespaceOnly=true` · **LB IPAM 꺼짐 확인**(MetalLB 와 IP 이중 할당 방지)
- [x] **라우팅 모드 확정·락 = VXLAN** (2026-07-27) — 파드 간 iperf3(WireGuard 켠 상태) 2.25 Gbps vs 물리 1GbE → 선이 먼저 찬다(§3.2). ⚠️ **A↔B 집계 대역**(Kafka RF=3 + ES 복제 + PG WAL + LGTM→MinIO 동시)은 **P2 직전 항목으로 이관** — 노드가 전부 호스트 B 안이라 P0 에선 물리 링크를 못 탄다
- [x] **master 강제 종료 테스트 — 인그레스 무중단 151/151** (2026-07-27 완료, status §1.0)
- [ ] ~~백업·복구 왕복 검증~~ → **P2 직전으로 이동**(2026-07-28 결정 — *P2 (데이터)* 절 선행조건 참조)

*P1 (앱)*
- [ ] 🔴 **`.9` 파괴 전 `.env` 백업** — JWT_SECRET·Gemini 키 등 비밀의 실질 정본. 날리면 복구 불가
- [ ] 🔴 **업로드 크기 제한을 Gateway 로 이관** — nginx `client_max_body_size 15m`. 안 옮기면 **영수증 OCR 업로드가 413** (`mp_k8s_infra_object_spec.md §5.6`)
- [ ] **PathPrefix 세그먼트 매칭 차이 검증** — nginx 는 문자열 프리픽스, Gateway API 는 세그먼트 단위라 `/api/recipesXYZ` 류가 404 (§5.3)
- [ ] mTLS 실동작 확인(평문 캡처로 반증) · frontend 는 비특권 이미지(PSS restricted — `NET_BIND_SERVICE` 제거, 8080 리스닝)
- [ ] Prometheus agent → `.11` remote_write 수신 확인 · 앱 대시보드·알림 연속성 확인
- [ ] 과도기 NetworkPolicy: 앱 egress 에 `192.168.0.8` ipBlock (P2 에서 제거할 것 — 제거 항목으로 P2 에 재등장)
- [ ] CronJob `spec.timeZone: Asia/Seoul` — UTC 크론탭 11개의 KST 환산표 작성(주석의 KST 의도가 정본)

*P2 (데이터+파이프라인)*
- [ ] Kafka: `auto.create.topics.enable=false` 확인 · KafkaTopic CRD 유일경로 · **PV 실사용 확인**(`describe`로 마운트 검증) · `min.insync.replicas=2`
- [ ] ES: 노드 `vm.max_map_count=262144` (ECK 기동 전) · `number_of_replicas: 1` · nori 커스텀 이미지 · **인증 켬+HTTP TLS 끔**(§5.2) — 앱 3곳 basic_auth·PGSync env 반영 확인
- [ ] ES 데이터: **복제하지 않는다** — 사전 배치 재색인(`recipes`, K8s standby 소스) → 컷오버 시 앱 `ES_INDEX=recipes`(DR 폴백 설계 회수) → PGSync 초기 동기화 후 `recipes_pgsync` 플립
- [ ] Kafka 데이터: **복제하지 않는다** — VM 크론 정지 → lag 0 드레인 확인 → 빈 토픽 시작(클릭스트림 이력의 SoT 는 PG `activity.user_event`)
- [ ] PG: 복제가 **비동기**인지 확인 (2 인스턴스 + 동기 = standby 사망 시 쓰기 정지)
- [ ] 🔴 **PGSync: 슬롯은 프로모트를 따라오지 않는다** — 신규 primary 에 슬롯 생성 + 초기 재동기화가 런북 항목. Pooler 우회(`pg-rw` 직접 — LISTEN/NOTIFY 는 transaction 풀링 불가)
- [ ] Redis: 영속성(AOF/RDB) **꺼져 있는지** 확인 · **오퍼레이터가 페일오버 시 master Service 대상을 실제로 갱신하는지 실물 검증** (안 되면 앱 Sentinel-aware 전환 = 별도 이슈, §5.2)
- [ ] 데이터 티어 배치: quorum 다수(ES 2 · Kafka 2 · Sentinel 2)가 **호스트 B**, PG·Redis primary 가 **호스트 A**, worker-a1 이 존재하는지(§2.2 램프) 확인
- [ ] 과도기 egress ipBlock(`.8`) 제거 · matview CronJob 재개 확인(매시 :20 — 자가복구 설계)

*P3 (스케일)*
- [ ] 🔴 **psycopg3 prepared statement — Pooler(transaction) 와의 충돌을 반복부하로 검증** (스모크만 돌리면 prepare 임계 전이라 안 터지고 넘어간다). 해결 = `prepare_threshold=None` 또는 PgBouncer prepared statement 지원
- [ ] 앱 커넥션 풀 축소 (`max_size` 10 → 3~5) — **env 화 대상은 4개 서비스**(pantry·mealplan·recipe·recipebook 하드코딩)
- [ ] advisory lock · 세션 `SET` · 임시 테이블 사용처가 있는지 확인 (transaction 모드 제약)
- [ ] HPA 는 requests 실측 후에만 (분모가 requests — `mp_k8s_infra_object_spec.md §9.1`)

*상시*
- [ ] 각 단계 완료 시 백업 경로 동작 확인 (백업 없는 상태로 다음 단계 진입 금지)

---

## 11. 결정 대기 (임의 확정 금지)

1. ~~**Cilium 라우팅 모드 최종**~~ → ✅ **해소(2026-07-27): VXLAN 확정·락.** 실측이 예상(native)을 뒤집었다 — 근거 = §3.2. 재검토 트리거는 P2 직전 집계 대역 포화이며, 그때의 답도 라우팅 모드가 아니라 NIC 증설이다
2. **Redis 오퍼레이터 선정** — 페일오버 시 master Service 를 실제로 갱신하는지 **P0~P2 사이 실물 검증** (§5.2 — 앱 코드 수정 0 요구. 불가 시 chat·price Sentinel-aware 전환 = 별도 이슈)
3. **이전 착수 시점** — 선행조건은 충족(호스트 B·C ✅). 5인 역할분담·9주 타임라인과의 정합만 남음
4. **PR 시점 pytest 게이트** — 러너 은퇴로 공백(Jenkins 는 main 머지 후 검사). 후속 = Jenkins 멀티브랜치 PR 빌드 (§7.4)

> ~~MetalLB IP 풀 대역~~ — 확정 `.14`–`.16`(§3.3). ~~호스트 B·C 확보~~ — 완료. ~~ESO 백엔드~~ — K8s provider 확정(§6.4). ~~ES 인증~~ — 켬+TLS 끔 확정(§5.2). ~~과도기 CD~~ — 없음 확정(§7.4).

---

## 12. 팀장 계획서(`k8s-infra-plan.md`) 대비 변경점

| 항목 | 계획서 | 이 문서 | 이유 |
|---|---|---|---|
| 데이터 티어 | in-cluster (§8) | **동일 채택** + 동적 프로비저닝 명시 | 기존 정본(`design.md §8.4`의 하이브리드)을 뒤집는 결정 → ADR 후보 |
| 스토리지 | 미기재 | **OpenEBS LVM LocalPV 확정** | StatefulSet 전제인데 CSI 결정이 없었음 |
| Kafka | **누락** | Strimzi 3노드 RF=3 · PV · auto-create 금지 | 파이프라인 중심 서비스인데 §8에 없었음 |
| DB 홉 암호화 | ❓ 미정 | **WireGuard 켬** | in-cluster 확정으로 전 구간 커버 가능해짐 |
| EKS 이식성 | 미기재 | **§8 신설** | 온프렘 K8s는 EKS로 가는 관문이라는 전제 |
| MetalLB | 채택 | 채택 + **LoadBalancer 1개 제한 규칙** | EKS 이식 시 유일한 필수 교체 대상 |
| Secret | 미기재 | **ESO** | GitOps 전환의 전제조건 |
| **CI** | 미기재(현행 GH Actions 전제) | **Jenkins 로 교체** · 제3 물리 머신 | 컨트롤러까지 자체 운영. 트리거·config-in-git 손실은 Tunnel·JCasC 로 회수 (§7.1) |
| **CD** | ArgoCD (계획서 §0) | 동일 + **Jenkins 는 CD 안 함** · 별도 config 레포 | CI 루프 구조적 차단 + 배포 이력 분리 (§7.3) |
| LGTM | 스택 변경 없음 | **in-cluster + MinIO 백엔드** | 로컬 PV면 EKS 이식 시 전면 재구성 |
| 관측 대상 | Hubble·Istio·app | 동일 + **Alertmanager 웹훅 ESO 관리** | 현행 ansible 롤의 웹훅 삭제 함정 해소 |
| socketLB 함정 | 미기재 | **§3.1 명시** | Cilium+Istio 조합의 전제조건 |
| Harbor·CI | 미기재 | **클러스터 밖 VM 명시** | 클러스터 장애 시 복구 수단 보존 |

계획서의 다음 항목은 **그대로 채택**했다: master ×1 근거 · VIP 불필요 · VXLAN 시작 · MetalLB L2 · Gateway API=Istio · **sidecar** · DB 메시 제외 · Job 사이드카 제외 · Hubble · FQDN egress · CoreDNS 플로우 · vmbr1 미사용.

---

## 13. 발표 서사 — "쿠버네티스의 꽃"

네트워킹·메시·관측이 뿌리와 줄기라면, 꽃은 **선언한 상태를 시스템이 스스로 유지하고 부하에 맞춰 몸집을 바꾸는 것**이다. 우리는 이 명분을 **실측과 실제 사고**로 갖고 있다 — 만들어낸 시나리오가 아니다.

**🌸 HPA — 수직의 끝을 실측으로 보고 수평으로 풀었다**
account 로그인이 bcrypt 때문에 CPU를 0.75→2.0코어로 올린 뒤에도 **100VU에서 한도의 98% 포화**(PG active 커넥션 0으로 DB 병목이 아님을 런타임 메트릭으로 확인). 수직 확장의 한계가 숫자로 찍혀 있다. HPA(목표 사용률 60~70%)로 replica 확장 → **"부하테스트 → 병목 발견 → 수직 한계 실증 → 수평 해결"** 완결 서사.

**🌸 KEDA — 스파이크에만 키우고 평시엔 0으로 잠든다**
우리 트래픽은 예측 가능한 스파이크형이다: 식사 피크(11–12·17–18시) · 오아시스 딜 크롤(15:05·17:05) · 최저가 알림 fan-out(멘토가 지목한 다자간 트래픽). Kafka lag 트리거로 컨슈머를 0↔N 스케일(ScaledObject 초안 = `deploy/k8s/retail-ingest.yaml` — ⚠️ 그 디렉토리는 stale·재작성 대상), 예측 피크는 cron 스케일러로 선제 확장. **scale-to-zero는 학생 예산에서 유휴 리소스를 실제로 반납**하므로 "규모 대비 과설계" 반박을 정면으로 뒤집는다.

**🌸 자가치유 — 우리가 실제로 겪은 장애의 재현**
시연: 워커 노드 강제 다운 → topologySpread + PDB로 파드가 살아있는 호스트로 재스케줄, 서비스 무중단. 근거: **호스트 급사 3회 · pgsync 16시간 무감지 크래시루프.** master를 호스트 B에 둔 덕에 *실제로 일어난 장애 모드*에서 이 데모가 성립한다.

**🌸 오퍼레이터 — CRD로 도메인 지식을 코드화**
CNPG primary 강제 종료 → 자동 페일오버 → 앱이 `-rw` Service로 무중단 재연결. 스토리지 복제 대신 **DB 자체 복제 + 오퍼레이터 페일오버**를 고른 §5.2 결정이 여기서 회수된다.

**🌸 GitOps + 카나리 — 메시 투자의 회수 지점**
**Jenkins(CI) → config 레포 → ArgoCD(CD)** 로 책임이 갈린 뒤, ArgoCD + Istio 트래픽 스플릿으로 피크타임 배포를 10% 카나리 → 5xx율(Istio 텔레메트리) 기준 자동 롤백. **이게 있어야 sidecar 채택 명분이 완성된다** — mTLS+관측만으로는 절반이고, 카나리가 "왜 굳이 sidecar까지 갔는가"의 최종 답이다.

**🌸 이식성 — 이 클러스터는 종착지가 아니다**
`overlays/onprem` ↔ `overlays/eks` 2-오버레이로 "EKS로 갈 수 있다"를 레포에 실재하는 코드로 보여준다(§8). 온프렘에서 배운 것이 클라우드에서 그대로 쓰인다는 것이 이 프로젝트의 마지막 카드.
