# 인프라 현황 (Kubernetes) — SSOT

> **팀 공유용 인프라 상태 단일 소스.** `CLAUDE.md §인프라`가 이 문서를 가리킨다. **인프라 변경 시 여기를 갱신한다.**
> 최초 작성 2026-07-24 (SSOT 이관) · **2026-07-27 전면 갱신** — 계획 검증 인터뷰의 결정 18건 반영(단계 재편·호스트 확보·CI 전환 완료 등). 결정 근거 = [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)
>
> 🟢 **클러스터 + 기반 스택 가동** (2026-07-27) — 호스트 B 3노드(kubeadm 1.34.10 + Cilium 1.19.6) 위에 MetalLB·OpenEBS·cert-manager·MinIO·ESO·관측·Istio·ArgoCD 까지 올라갔다. **남은 P0 = S3 백업·복구 왕복 · iperf3 라우팅 모드 락 · master 강제종료 테스트 · config 레포 연결** — §0 표가 정확한 현황이다.
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
| **K8s 노드 VM 3대** (Terraform · 호스트 B) | ✅ **생성 완료** (2026-07-27) — `k8s-master` `.17`(6GB·2c) · `k8s-worker-b1` `.18` · `k8s-worker-b2` `.19`(11GB·6c 각) · swap 없음 |
| K8s 클러스터 (master ×1 + worker ×4, **노드 램프** §1) | ✅ **3노드 Ready** (2026-07-27) — kubeadm **1.34.10** · **kube-proxy 미설치**(Cilium 대체) · containerd 2.2.6 |
| Cilium (CNI · kube-proxy 대체 · WireGuard) | ✅ **1.19.6** — `kubeProxyReplacement: true` · Tunnel(VXLAN) · WireGuard(peers 2) · `ipam.mode=kubernetes`(podCIDR `10.244.0.0/16`) · cluster health 3/3 |
| Istio (sidecar 메시 + Gateway API) | ✅ **컨트롤플레인** 1.30.3 — istiod + **istio-cni**(Cilium conflist 에 체이닝 실증: `['cilium-cni','istio-cni']`) + **Gateway API CRD v1.6.1**. Gateway·HTTPRoute 실물은 P1 |
| MetalLB (L2, 풀 `.14`–`.16`) | ✅ **0.16.1** — 풀 `autoAssign=false`(게이트웨이 전용 강제) · 스모크: 풀 미지정=Pending / 지정=`.14` 할당 + LAN HTTP 200 |
| OpenEBS LVM LocalPV (동적 프로비저닝) | ✅ **1.9.1** — SC `openebs-lvm`(기본·Delete) + `openebs-lvm-retain`(Retain), 둘 다 WaitForFirstConsumer. 워커 2대 왕복 검증 완료 |
| MinIO (Loki·Tempo 백엔드 · 모델 아티팩트 — **단일 replica·B 고정**) | ✅ **차트 5.4.0 / RELEASE.2025-09-07** — PVC 50Gi · zone=host-b 고정 · 버킷 loki·tempo·models 생성됨 |
| 데이터 티어 in-cluster (PG·ES·Redis·Kafka HA + PGSync) | ⬜ 미착수 |
| 관측 (kube-prometheus-stack + metrics-server) | ✅ **87.20.0 + 3.13.1** — Prometheus(B 고정·PVC 30Gi·15d) · Grafana · Alertmanager(수신자 없음) · node-exporter 는 **kube-system**(PSS) · `kubectl top` 응답 확인. **앱 관측·Slack 알림은 P4 까지 `.11` VM** |
| ArgoCD (CD, GitOps — **유일한 CD**) | 🔶 **설치 완료**(10.2.1 / v3.4.5) — **Application 0개**. config 레포 미정이라 연결 대기 · P2 까지 자동 CD 없음 |
| External Secrets Operator (**Kubernetes provider**) | ✅ **2.8.0** — 정본 ns `fb-secrets` + 읽기전용 SA · `ClusterSecretStore/fb-kubernetes` Ready |
| S3 오프사이트 백업 | ⬜ **미착수 — 사용자 준비물 대기**(버킷 + IAM 키). P0 체크리스트의 백업·복구 왕복 검증이 여기 묶여 있다 |
| cert-manager | ✅ **v1.21.0** — 로컬 CA 승계 `ClusterIssuer/fb-local-ca` Ready(새 CA 를 만들지 않아 신뢰 재배포 불필요) |
| 클러스터 공통 오브젝트 | ✅ zone 레이블(`topology.kubernetes.io/zone=host-b`) · ns 5종+PSS · PriorityClass 3종 |

**P0 대부분 완료** (2026-07-27) — 전 과정이 IaC 다: Terraform(노드 VM 3대) → Ansible `k8s.yml`(베이스라인 → `kubeadm init` → 조인 → Cilium → 공통 오브젝트 → 기반 스택 8종). **플레이북 전체 재실행 = `changed=0`**.

**실측으로 검증한 것**: 3노드 Ready · cilium health 3/3 · 크로스노드 ClusterIP+CoreDNS = HTTP 200(kube-proxy 없이 eBPF LB) · 워커 2대 PVC 왕복 · MetalLB 풀 미지정=Pending/지정=`.14`+LAN HTTP 200 · CNI 체이닝 `['cilium-cni','istio-cni']` · `kubectl top` 응답 · master 상주 **1,938Mi = allocatable 의 41%**(6GB 상향 판단의 실측 근거).

**남은 P0** — 🔴 **S3 백업·복구 왕복**(사용자 준비물: 버킷+IAM 키) · 🔴 **iperf3 라우팅 모드 측정·락**(⚠️ 노드 3대가 전부 호스트 B 안이라 물리 NIC 를 안 탄다 — 유의미한 A↔B 측정은 worker-a1 이 생긴 뒤) · **master 강제종료 테스트**(인그레스 유지) · **config 레포 연결**(이름·가시성 미정) · P1 준비물(ResourceQuota·LimitRange·imagePullSecret). 팀 타임라인 정합은 여전히 미결([§6](#6-미결)).

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
| **`.17`–`.19`** | **K8s 노드 3대** — `k8s-master` · `k8s-worker-b1` · `k8s-worker-b2` (호스트 B) | ✅ 사용 중 |
| `.20`–`.21` | K8s 노드 램프분 (worker-a1 = P1 후 · worker-a2 = P4) | 예약 |
| **`.22`** | **물리 호스트 B** (Proxmox `k8s1`) | ✅ 사용 중 |

🔴 **공유기 DHCP 범위가 `.14`–`.21`(예약 대역)과 겹치면 ARP 충돌**("가끔 안 됨" 형 장애) — 시작 주소를 **`.23` 이상**으로. **확인 생략하고 진행함**(2026-07-27 결정): 대역은 `1–254` 전체가 DHCP 후보지만 사용자 간 암묵적 합의로 운용되며, 노드 생성 전 `.14`–`.21` 8개 주소가 ping 무응답인 것만 확인했다. → 나중에 산발적 단절·`Duplicate address detected` 가 나오면 **1순위 용의자**. 특히 MetalLB VIP(`.14`–`.16`)는 gratuitous ARP 로 광고하므로 정적 노드 IP 보다 충돌에 민감하다. *(`.13` 은 타인 장비(VirtualBox 게스트)가 상주해 예약에서 제외 — 구 계획의 호스트 B 예약분이었으나 `.22` 로 변경. `.177` 예약도 폐기 — 호스트 C 가 `.10` 승계.)*

---

## 2. 컴포넌트 구성 (확정 사양)

결정 근거는 전부 [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)에 있다. 여기는 *무엇으로 정해졌는가*만 적는다.

**버전 핀 (2026-07-27 설치분)** — 🔴 **상한을 정하는 건 Cilium 이다**: 최신 릴리스 1.19.6 이 e2e 검증한 K8s = **1.31–1.34**. Istio 1.30 은 1.32–1.36 을 덮으므로 교집합 최댓값이 1.34 다. **1.35·1.36 으로 올리지 말 것** — kube-proxy 대체(eBPF)는 K8s API·커널 결합이 깊어 "하위호환으로 될 수도"에 걸 자리가 아니다. 1.33 은 이미 EOL. ⚠️ 1.34 EOL = **2026-10-27** → Cilium 1.20 릴리스 후 `kubeadm upgrade` 로 1.35 (무중단 마이너 업그레이드 = 발표 데모 소재).

| 대상 | 핀 | 비고 |
|---|---|---|
| Kubernetes | **1.34.10** | `apt-mark hold` (kubelet·kubeadm·kubectl) — 마이너 자동 상승 = 스큐 파손 |
| Cilium | **1.19.6** | Helm 차트. 값 = `/etc/kubernetes/cilium-values.yaml`(→ 나중에 config 레포로 이관) |
| containerd | **2.2.6** | Docker 공식 저장소. ⚠️ 2.x 는 pause 키 이름이 `sandbox`(1.7 = `sandbox_image`) |
| Helm | **3.21.3** | Helm 4 회피 — ArgoCD 번들 렌더러가 3.x 계열이라 렌더 결과를 맞춘다 |
| MetalLB | **0.16.1** | FRR-K8s 끔(BGP 전용). 풀 `autoAssign=false` |
| OpenEBS LVM LocalPV | **1.9.1** | SC 2종. 노드 VG = `openebs-vg`(scsi2) |
| cert-manager | **v1.21.0** | CRD 를 차트가 관리(`crds.enabled`) |
| MinIO | 차트 **5.4.0** / 이미지 **RELEASE.2025-09-07T16-13-09Z** | ⚠️ GitHub 릴리스 태그 ≠ 이미지 태그(§3) |
| kube-prometheus-stack | **87.20.0** (Operator v0.92.1) | node-exporter 는 **끄고**(`nodeExporter.enabled=false`) kube-system 에 별도 |
| prometheus-node-exporter | **4.56.1** | kube-system 배치 — 호스트 접근 필요(§3) |
| metrics-server | **3.13.1** | `--kubelet-insecure-tls`(정석 전환 = kubelet `serverTLSBootstrap` + CSR 승인) |
| External Secrets | **2.8.0** | Kubernetes provider |
| Istio | **1.30.3** | base + istiod + cni(체이닝) |
| Gateway API | **v1.6.1** | standard 채널 |
| ArgoCD | **10.2.1** (v3.4.5) | 설치만 — Application 0개 |

| 계층 | 구성 | 상태 |
|---|---|---|
| **컨트롤플레인** | **kubeadm 직접** (Kubespray 기각 — 플랜 §2.5) · master ×1 (VIP/HAProxy 불필요) · etcd 스냅샷 → S3 · **metrics-server**(HPA 전제) | 🔶 init 완료(1.34.10, `controlPlaneEndpoint=.17:6443` · kubelet 예약 명시) · **etcd 스냅샷·metrics-server 미착수** |
| **CNI** | Cilium (eBPF) · kube-proxy 대체 · `socketLB.hostNamespaceOnly=true` 🔴 | ✅ 1.19.6 — `cni.exclusive=false` 도 선반영(Istio CNI 체이닝 전제) |
| **라우팅 모드** | VXLAN 으로 시작 → **P0 iperf3 측정 후 P1 전 확정·락** (예상 native) | 🔶 VXLAN 가동 중 · **측정 미실시** |
| **노드 간 암호화** | Cilium WireGuard (파드 간 — 호스트 네트워크까지 덮으려면 `nodeEncryption` 별도) | ✅ `cilium_wg0` peers 2 (`nodeEncryption: Disabled`) |
| **외부 LB** | MetalLB (L2) · 풀 `.14`–`.16` · **`type: LoadBalancer` 는 게이트웨이 전용 — 상시 2개**(공개 `.14` + 내부 `.15`), 개별 서비스 노출 금지 | ⬜ |
| **남북 L7** | Gateway API · 구현체 = Istio · TLS 종단 | ⬜ |
| **서비스 메시** | Istio **sidecar** (ambient 기각) · **app ns 11 워크로드**(FastAPI 9 + frontend + ranking-serving)만 주입 · data·pipeline ns 제외 | ⬜ |
| **스토리지** | OpenEBS LVM LocalPV (CSI · RWO · WaitForFirstConsumer) — **RWX 금지** | 🔶 워커에 VG `openebs-vg`(150G) 준비됨 · **CSI 오퍼레이터·StorageClass 미설치** |
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
- **DHCP**: 공유기 할당 범위가 `.14`–`.21`(예약 대역)과 겹치지 않을 것, 시작 주소 `.23` 이상 — **확인은 생략하고 진행함**(§1.1). 산발적 단절 시 1순위 용의자
- **게스트 디스크 이름은 scsi 인덱스 순서와 다르다** — 워커 실측(2026-07-27): `scsi1`(containerd 40G) = **`/dev/sdc`**, `scsi2`(OpenEBS 150G) = **`/dev/sdb`**. Ansible 은 `/dev/sdX` 를 하드코딩하지 말고 **`/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsiN`** 를 쓸 것 — 뒤바뀌면 **OpenEBS VG 용 raw 디스크를 containerd 용으로 mkfs** 한다(스토리지 계층이 조용히 사라짐). 호스트 C 의 `docker_data_disk=/dev/sdb` 관례를 그대로 복사하면 밟는 함정
- **호스트 C 인벤토리**: `[ci]` 그룹(= `vms` 자식)으로 관리한다 — base 롤은 VirtualBox 대응 완료(qemu-guest-agent 스킵), `group_vars/ci.yml` 에 `docker_data_disk` **의도적 명시됨**(2026-07-27). 디스크 구성을 바꾸면 그 값을 먼저 갱신할 것. *(구 계획의 "cicd 그룹 분리" 수칙은 이 방식으로 대체됨)*
- **호스트 C 브리지 어댑터** (§1) — NAT 면 이미지 pull 불가
- 🔴 **RWO 단일 replica 워크로드는 `strategy: Recreate`** — 기본 RollingUpdate 는 새 파드를 먼저 띄우는데 로컬 PV 는 두 번 마운트할 수 없다 → 새 파드가 `verifyMount: device already mounted` 로 영원히 ContainerCreating. MinIO 에서 실제로 밟았다(2026-07-27). PGSync 등 같은 성질에 모두 해당
- 🔴 **`nodeName` 직접 지정 금지** — 스케줄러를 건너뛰므로 `WaitForFirstConsumer` PVC 가 영영 Pending 이다(선택 노드 주석이 안 붙는다). 노드 고정은 반드시 `nodeSelector`/affinity 로
- 🔴 **호스트 접근이 필요한 워크로드(node-exporter 류)는 `kube-system` 에** — hostNetwork·hostPID·hostPath·hostPort 는 PSS `baseline` 에서 거부된다. ns 를 privileged 로 낮추지 말고 워크로드를 옮긴다(관측 ns 의 Grafana·MinIO 가드를 지키기 위해)
- ⚠️ **차트 서브차트 토글은 부모 조건 키를 봐야 한다** — kube-prometheus-stack 의 node-exporter 는 `prometheus-node-exporter.enabled` 가 아니라 **`nodeExporter.enabled`** 로 꺼진다(Chart.yaml 의 condition). 별칭에 false 를 줘도 그대로 렌더된다
- ⚠️ **GitHub 릴리스 태그 ≠ 컨테이너 이미지 태그** — MinIO 는 GitHub 최신(2025-10-15)의 이미지가 quay 에 없어 ImagePullBackOff. 이미지 핀은 레지스트리 태그 목록에서 확인할 것
- **단일 파일 bind mount**: 파일을 교체하면 inode가 바뀌어 컨테이너가 고아 inode를 계속 본다 → SIGHUP 리로드가 무력. 재생성 필요 (K8s 에서는 ConfigMap 으로 해소)

---

## 4. IaC

| 구성 | 위치 | K8s 이전 시 변화 |
|---|---|---|
| **Terraform** | [`infra/terraform/`](../infra/terraform) | 유지 — **Proxmox(A·B) 전용.** state = PG 원격 backend. 호스트 B 는 **별개 스탠드얼론이라 provider alias `b`**(`vms_k8s.tf` = K8s 노드 3대). **호스트 C 는 대상 아님**(VirtualBox — 프로바이더 안 씀). ⚠️ 은퇴 VM 203 은 **state 에서 제거해 추적 제외** — tfvars 에 되살리면 `.10` 이 호스트 C 와 충돌 |
| **Ansible** | [`infra/ansible/`](../infra/ansible) | 유지 — **K8s 는 전용 플레이북 `k8s.yml`**(롤 `k8s_node`·`k8s_control_plane`·`k8s_worker_join`·`k8s_cilium`). 🔴 **K8s 노드는 `vms` 그룹에 넣지 않는다** — site.yml 의 base 롤이 `docker_data_disk`(/dev/sdb)를 포맷하고 워커의 sdb 는 OpenEBS raw 디스크다. **호스트 C = `[ci]` 그룹**(base 롤 VirtualBox 대응 완료). 서비스 배포 롤은 ArgoCD 로 이관 |
| **Jenkins** | 레포 루트 `Jenkinsfile` + `roles/jenkins`(compose) | ✅ 가동 — CATALOG 14 이미지·릴리스 태깅. JCasC 코드화는 후속 |
| **매니페스트** | `deploy/k8s/` | ⚠️ **stale** — ECR·placeholder 시절 유물이고 앱 매니페스트는 부재. 재작성 필요 |
| **ArgoCD 선언** | 별도 config 레포 | 신규 (P0) — 이미지 핀은 `:sha` |

### 4.0 클러스터 접속 (`kubectl`)

master 노드에서는 root·`ubuntu` 둘 다 `~/.kube/config` 가 배치돼 있다(`k8s_control_plane` 롤). 로컬 워크스테이션에서 쓰려면:

```bash
# 1) 클라이언트 버전 맞추기 — kubectl 은 apiserver ±1 마이너까지만 지원(스큐)
curl -LO https://dl.k8s.io/release/v1.34.10/bin/linux/amd64/kubectl
curl -LO https://dl.k8s.io/release/v1.34.10/bin/linux/amd64/kubectl.sha256
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check
install -m 0755 kubectl ~/.local/bin/kubectl        # sudo 불필요

# 2) kubeconfig 를 **머지**한다 (기존 컨텍스트를 덮어쓰지 말 것)
ssh ubuntu@192.168.0.17 'sudo cat /etc/kubernetes/admin.conf' > /tmp/mp-k8s.conf
#    kubeadm 기본 이름(cluster=kubernetes / user=kubernetes-admin)은 흔해서 충돌한다
#    → cluster·user·context 를 mp-k8s / mp-k8s-admin / mp-k8s 로 바꾼 뒤 머지
cp ~/.kube/config ~/.kube/config.bak
KUBECONFIG=~/.kube/config:/tmp/mp-k8s.conf kubectl config view --flatten > /tmp/merged
install -m 0600 /tmp/merged ~/.kube/config
kubectl config use-context mp-k8s
```

**설치된 것 들여다보기** (전부 ClusterIP — 외부 노출은 게이트웨이 전용 규칙 §3.3):

```bash
kubectl -n observability port-forward svc/kube-prometheus-stack-grafana 3000:80   # Grafana (admin / secrets.yml:grafana_admin_password)
kubectl -n observability port-forward svc/kube-prometheus-stack-prometheus 9090:9090
kubectl -n observability port-forward svc/minio-console 9001:9001                 # MinIO (fbadmin / secrets.yml:minio_root_password)
kubectl -n argocd       port-forward svc/argocd-server 8080:443                   # ArgoCD (admin)
#   ArgoCD 초기 비번: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
#   🔴 최초 로그인 후 비번 변경 + argocd-initial-admin-secret 삭제
```

⚠️ `admin.conf` 는 **cluster-admin 자격증명**이다(무기한·취소 불가). 팀 공용으로 뿌리지 말 것 — 사람별 계정은 ESO·OIDC 도입 시점에 별도로 판단한다. 임시로 나눠줄 땐 `kubectl create token` 기반 ServiceAccount 토큰을 쓴다.

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
| P0 | 호스트 B 3노드 · 기반(Cilium·Istio·MetalLB·OpenEBS·MinIO·cert-manager·ESO·ArgoCD·kube-prometheus-stack·metrics-server) · **라우팅 모드 iperf3 측정·락** · 🔴 **백업·복구 경로 검증** | 🔶 **기반 스택 전부 ✅**(2026-07-27) · 남은 것 = S3 백업·복구 왕복 · iperf3 측정·락 · master 강제종료 테스트 · config 레포 연결 |
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
