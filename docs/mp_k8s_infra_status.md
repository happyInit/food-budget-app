# 인프라 현황 (Kubernetes) — SSOT

> **팀 공유용 인프라 상태 단일 소스.** `CLAUDE.md §인프라`가 이 문서를 가리킨다. **인프라 변경 시 여기를 갱신한다.**
> 최초 작성 2026-07-24 (SSOT 이관) · **2026-07-27 전면 갱신** — 계획 검증 인터뷰의 결정 18건 반영(단계 재편·호스트 확보·CI 전환 완료 등). 결정 근거 = [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)
>
> 🟢 **클러스터 + 기반 스택 가동** (2026-07-27) — 호스트 B 3노드(kubeadm 1.34.10 + Cilium 1.19.6) 위에 MetalLB·OpenEBS·cert-manager·MinIO·ESO·관측·Istio·ArgoCD 까지 올라갔다. **P0 완료 (2026-07-28)** — 마지막 항목이던 S3 백업·복구 왕복은 **P2 직전 선행조건으로 이동**(같은 날 결정 — 무백업 노출 창은 P2 컷오버부터라 게이트 위치만 옮긴 것, 데이터 티어 전 증명 원칙 유지). §0 표가 정확한 현황이다.
> 🟢 **LGTM 선배포** (2026-07-28) — P4 항목이던 "LGTM in-cluster" 중 **스택 세우기만 앞당겨** Loki·Tempo·Alloy 가 **ArgoCD Application**(platform AppProject)으로 가동. **컷오버(알림 20개·Slack·`.11` 철거)는 P4 유지** — 상세·근거 = §4.3.
> **오늘의 운영·장애대응·접속은 [`docker-infra-status.md`](./docker-infra-status.md)를 본다** — 실가동 중인 것은 그쪽이다.
>
> | 용도 | 문서 |
> |---|---|
> | **인프라 SSOT (목표 아키텍처·구축 현황)** | **이 문서** |
> | 이전 결정·근거·컷오버 절차 (why/how) | [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md) |
> | 현행 실가동 시스템 (지금 돌아가는 것) | [`docker-infra-status.md`](./docker-infra-status.md) |
> | **P1 앱 이전 담당자 핸드오프** | [`mp_k8s_p1_app_handoff.md`](./mp_k8s_p1_app_handoff.md) |
> | **P2 데이터 이전 런북** (2026-07-28 확정) | [`mp_k8s_p2_data_runbook.md`](./mp_k8s_p2_data_runbook.md) |
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
| **관측 — LGTM 선배포** (Loki·Tempo·Alloy, **ArgoCD 관리**) | ✅ **2026-07-28 가동**(§4.3) — Loki 7.1.0(SingleBinary·MinIO 백엔드·168h) · Tempo 1.24.4(모놀리식·MinIO) · Alloy 1.11.0(DaemonSet 3노드·**kube-system**) · Grafana 데이터소스 자동 배선 · **로그 유입 + MinIO 청크 플러시 실증**. 컷오버는 P4 |
| ArgoCD (CD, GitOps — **유일한 CD**) | ✅ **10.2.1 가동 완료** — platform AppProject + Application 3(LGTM, §4.3) + **앱 트랙 연결 실증 완료**(§4.2, 2026-07-28): config 레포(`happyInit/mealplanning-config`) · ESO 경유 자격증명 · AppProject `mealplanning` · 실 fetch·kustomize 렌더 검증. 앱 Application 적용은 P1(앱 담당자) |
| External Secrets Operator (**Kubernetes provider**) | ✅ **2.8.0** — 정본 ns `fb-secrets` + 읽기전용 SA · `ClusterSecretStore/fb-kubernetes` Ready |
| S3 오프사이트 백업 | ⬜ **P2 직전 선행조건**(2026-07-28 P0 에서 이동) — 준비물 = 버킷+IAM 키. 🔴 **왕복(백업→복원) 증명 없이 P2 착수 금지** — 인클러스터 PG 가 실데이터 정본이 되는 순간부터 무백업 창이 생긴다 |
| cert-manager | ✅ **v1.21.0** — 로컬 CA 승계 `ClusterIssuer/fb-local-ca` Ready(새 CA 를 만들지 않아 신뢰 재배포 불필요) |
| 클러스터 공통 오브젝트 | ✅ zone 레이블(`topology.kubernetes.io/zone=host-b`) · ns 5종+PSS · PriorityClass 3종 |
| **공개 Gateway `.14` + HTTPRoute 10** (P1) | ✅ **2026-07-28 가동·검증** — `mp-gw-public`(HTTP 80. TLS 는 라우팅 검증 후 별건) · nginx `/api/*` 13경로 이관 · **`.9` 대비 18경로 응답 100% 일치**(불일치 0) · 업로드 한도 복원(EnvoyFilter buffer 15Mi — object_spec §5.6 정정분). 정본 = config 레포 `gateway/`. 🔴 **유입 전환은 아직**(실서비스는 `.9`) |

**P0 대부분 완료** (2026-07-27) — 전 과정이 IaC 다: Terraform(노드 VM 3대) → Ansible `k8s.yml`(베이스라인 → `kubeadm init` → 조인 → Cilium → 공통 오브젝트 → 기반 스택 8종). **플레이북 전체 재실행 = `changed=0`**.

**실측으로 검증한 것**: **master 하드 파워오프 중 인그레스 무중단 151/151**(§1.0) · 3노드 Ready · cilium health 3/3 · 크로스노드 ClusterIP+CoreDNS = HTTP 200(kube-proxy 없이 eBPF LB) · 워커 2대 PVC 왕복 · MetalLB 풀 미지정=Pending/지정=`.14`+LAN HTTP 200 · CNI 체이닝 `['cilium-cni','istio-cni']` · `kubectl top` 응답 · master 상주 **1,938Mi = allocatable 의 41%**(6GB 상향 판단의 실측 근거).

**P0 완료 (2026-07-28)** — 기반 스택·라우팅 락·master 킬 테스트·config 레포 연결(app-of-apps 가동)·LGTM 선배포까지 전부 ✅. 마지막 항목이던 **S3 백업·복구 왕복은 P2 직전 선행조건으로 이동**(2026-07-28 결정 — §5 P2 행). 다음 = **P1 앱 이전** — P1 준비물(ResourceQuota·LimitRange·imagePullSecret)은 담당자와 함께, 팀 타임라인 정합은 여전히 미결([§6](#6-미결)).

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

### 1.0 master 강제종료 실측 (2026-07-27)

`qm stop`(하드 파워오프 — 우리가 겪은 "무흔적 급사"와 같은 조건)으로 §2.1 의 주장을 실측했다.
대상: nginx 2 replica(워커 1대씩) + MetalLB LB `.14`, 1초 간격 샘플링.

| 항목 | 실측 |
|---|---|
| **인그레스 중단** | **0** — 151 샘플 전부 HTTP 200(apiserver 부재 71 샘플 포함) |
| apiserver 부재 | 3분 3초 (의도적 대기 포함) |
| **복구** | **전원 투입 → 26초 만에 apiserver 응답** (kubelet 활성 +17초) |
| 서빙 파드 재시작 | **0** (양쪽 워커) · cilium **agent** 도 워커에서 0 |

⚠️ **다만 "아무 일도 안 일어난다"는 아니다** — apiserver 를 상시 watch 하는 컴포넌트는 재시작한다:
cert-manager 1회 · cainjector 4회 · cilium-**operator** 3회 · kube-state-metrics 5회.
전부 apiserver 복귀 후 자동 회복했고 데이터패스와 무관하다(에이전트는 eBPF 맵으로 계속 서빙).
→ **"변경 능력만 잃고 서빙은 유지"가 실측으로 성립.** P1 에서 실제 Istio Gateway·앱 경로로 한 번 더 확인한다.

🔴 이 테스트가 **증명하지 않는 것**: master 부재 중 cilium-agent 가 재시작되면 그 노드는 복구하지 못한다
(`k8sServiceHost` = master IP 직접). 단일 master 의 구조적 한계이며 물리 3대 전에는 못 없앤다.

### 1.0.1 Cilium 라우팅 모드 = **VXLAN 확정·락** (2026-07-27 실측)

⚠️ **지금은 반쪽만 측정 가능하다** — 노드 3대가 전부 호스트 B *안*이라 노드 간 트래픽이 물리 NIC 를
타지 않는다. 그래서 측정된 것은 **캡슐화·암호화의 CPU 비용**이지 링크 특성이 아니다.

| 경로 | 대역폭 |
|---|---|
| 파드→파드 (VXLAN + WireGuard) | **2.25 Gbps**(4스트림) / **2.37 Gbps**(단일 스트림) |
| 호스트→호스트 (캡슐화·암호화 없음) | **40.2 Gbps** |

**해석이 중요하다**: 비율(18배)이 아니라 **절대값**을 봐야 한다. 호스트 A↔B 물리 링크는 **1 GbE** 이고,
암호화·캡슐화를 전부 켠 상태의 CPU 천장이 **2.25 Gbps = 실배선의 2배 이상**이다.
→ 실링크에서는 VXLAN 이든 native 든 **선을 먼저 채운다. 라우팅 모드를 throughput 근거로 고르는 논리는
이 숫자로 사실상 무력해졌다.** 단일 스트림이 4스트림과 같은 것도 같은 얘기다(코어 병렬성이 아니라
암호화·캡슐화 처리 자체가 천장).

native 로 갈 이유로 남는 것: ① 패킷당 CPU 절감 ② MTU 효율(VXLAN 헤더 50B ≈ 3~4% 페이로드 손실)
③ 디버깅 단순성. 전제 조건(전 노드 같은 L2)은 A·B 가 같은 `/24` 라 충족한다.

**남은 측정 2건 — 해소처 확정(2026-07-28 2차 grilling Q13)**: ⓐ A↔B 실링크 대역·지연(worker-a1 필요)
= **P2 게이트 ③**(a1 합류 직후 iperf) ⓑ **집계 대역**(Kafka RF=3 + ES 복제 + PG WAL + LGTM→MinIO 동시
— 플랜이 실제로 걱정한 것) = **P2 풀 리허설의 정식 산출물**(NIC 피크 기록 → 전환창 go/no-go, 지속 ~70%
초과 시 배치 조정·본딩 검토). 상세 = [P2 런북 머리말·§7](./mp_k8s_p2_data_runbook.md).

### 1.0.2 🔴 호스트 B KSM 메모리 오염 사건 (2026-07-28) — KSM 영구 비활성

**증상**: master VM 에서만 서로 다른 바이너리 다수가 랜덤 주소 크래시 — GPF 10건(ansible python3 ×8·apport ×2,
01:12~03:19 UTC) + helm 세그폴트 + **kube-apiserver SIGSEGV 2회**(`fatal error: fault`) + etcd 크래시 1회.
전형적 **게스트 메모리 오염** 패턴. 워커 2대·호스트 dmesg 무결(MCE/EDAC 없음)·발룬 3 VM 전부 꺼짐.

**정황**: LGTM 선배포로 VM 상주가 늘며 호스트 B 램 90%(VM 28.7G/32G) → **ksmtuned 공격 모드,
KSM 병합 4.75GB**(125만 페이지) 상태. master 는 ansible 이 단명 프로세스를 다량 스폰해 CoW 가 가장 격렬한 VM.

**조치(2026-07-28, 승인 완료)**: `echo 2 > /sys/kernel/mm/ksm/run`(정지+전량 언머지) + `ksmtuned` stop·disable.
언머지 후 호스트 used 25.0→29.5GB·free ~2.5GB·스왑 폭주 없음. **이후 동일 워크로드(플레이북 전체) 재현 = GPF 0·크래시 0.**
비상 대비로 **etcd 스냅샷 확보**(`snap-emergency-20260728.db` 38MB — master `/var/lib/etcd/` + 오프 VM 사본, sha256 검증).

- 🔴 **호스트 B 에 KSM 을 다시 켜지 말 것**(재구축 시 ksmtuned 재활성 주의 — 이 조치는 IaC 밖 수동 설정이다)
- 관찰 방법: `ssh ubuntu@.17 'sudo dmesg -T | grep -cE "general protection|segfault"'` — 당시 기준선 **10**(2026-07-28. ⚠️ 이후 재부팅으로 **0 리셋** — 아래 참조)
- 여파: KSM 절약분이 사라져 호스트 B 여유 ~2.5GB — 부족해지면 워커 11→10GB 감축이 예비안

**🔴 재발 확인 (2026-07-28 오후) — KSM 무죄, 물리 RAM 유력으로 승격.** KSM 완전 off 상태에서
GPF 10→**12**: `landscape-sysinfo`(05:07 UTC)·`unattended-upgrades`(06:14 UTC, **libapt-pkg C++**
— 파이썬 아님). 둘 다 **부하와 무관한 유휴 시스템 데몬**이고, 같은 시간대에 돌린 무거운 ansible 런들은
무사 — 랜덤 시점·랜덤 바이너리·랜덤 주소 = 전형적 램 오염. 워커 2대·호스트 dmesg 는 여전히 0건
→ **master VM 이 앉은 물리 램 영역 불량**이 최유력. etcd 스냅샷 2호 확보(`snap-20260728-2.db`, 오프 VM).
- 🔴 **다음 조치 = memtest86+** (호스트 B 전체 다운 수 시간 — 일정 사용자 결정 대기). 불량 주소 확인 시
  선택지: RAM 교체 또는 Proxmox 커널 `memmap` 으로 불량 영역 마스킹(저예산 대안)
- 임시 완화 후보: master VM cold restart 로 램 배치 재추첨(컨트롤플레인 1~2분 부재 — 서빙 유지는
  §1.0 실측으로 성립. 단 **복불복**이며 수리가 아니다)

**🔴 오염이 디스크까지 도달 — etcd WAL 파손·스냅샷 복원 (2026-07-28 저녁).** memtest 준비로 VM 을
정상 종료 후 재기동하자 etcd 가 `walpb: crc mismatch` 로 크래시루프 — **램 오염이 etcd WAL 에 쓰레기를
써 넣었고 그게 디스크에 남은 것**(램 불량 가설의 물증이자, 오염 창의 쓰기가 신뢰 불가함을 실증).
**복원 절차(성공 — 이대로가 etcd 복구 런북이다)**: ① 사전 스냅샷(`snap-20260728-3-premtest.db`,
셧다운 7분 전·sha256 양측 검증) ② kubelet stop ③ `ctr -n k8s.io run … registry.k8s.io/etcd:3.6.5-0
etcdutl snapshot restore <snap> --name k8s-master --initial-cluster … --data-dir <new>`(호스트에 etcdutl
없어도 이미지로 실행) ④ 파손 `member` → `member.bad` 로 보존·복원본 투입 ⑤ kubelet start →
컨트롤플레인 1/1 · 노드 3 Ready · ArgoCD 전 앱 정상 복귀. **유실 = 0**(7분 창은 셧다운 준비 중이라 무변화).
- 교훈: **스냅샷은 "파괴적 작업 직전" 반드시** — 이번 건이 관행의 실전 검증. S3 오프사이트(P2 게이트)의
  필요성도 재실증(이번엔 스냅샷이 로컬에 있어 살았지만, 호스트 통째 손실이면 오프사이트만 남는다)
- 재부팅 후 GPF 기준선 리셋 = **0**(새 카운트 시작 — 램 배치 재추첨 효과 여부는 memtest 가 판정)
- 잔여물: master `/var/lib/etcd/member.bad`(파손 원본 — memtest 결론 후 삭제) · memtest86+ 설치·grub
  엔트리는 야간 실행용으로 존치
- 🔴 **memtest 는 아직 미실행**(2026-07-28 저녁 확인: 호스트 B 는 16:15 에 일반 pve 커널로 복귀,
  `grub-editenv list` 의 `next_entry` 비어 있음 = 원샷 엔트리가 장전된 적 없음). 실행 = `qm shutdown 301/302/303`
  → `grub-reboot memtest86+ && reboot`. **LVM 이라 원샷 플래그가 자동으로 안 지워진다** — memtest 후
  Proxmox 로 복귀할 때 GRUB 수동 선택 + `grub-editenv /boot/grub/grubenv unset next_entry` 필요
✅ **결정: VXLAN 유지·락** (2026-07-27). 처리량 근거가 사라진 상태에서 native 가 주는 건 MTU 3~4% 인데,
전환은 Cilium agent 재시작 + **파드 네트워크 순단**을 요구한다 — 얻는 것보다 지불이 크다.
따라서 "A↔B 실링크 측정을 기다린다 → worker-a1 을 앞당긴다"는 일정 모순도 함께 해소됐다(측정을 기다릴 이유가 없다).

🔴 **재검토 트리거는 성능이 아니라 링크 포화다** — P2 직전 집계 측정에서 1GbE 가 포화하면
답은 라우팅 모드가 아니라 **NIC 본딩·2.5GbE·배치 조정**이다(라우팅 모드로는 3~4% 밖에 못 되찾는다).
근거 상세 = [플랜 §3.2](./mp_k8s_infra_migration_plan.md).

### 1.1 IP 주소 배치 (192.168.0.0/24)

| 대역 | 용도 | 상태 |
|---|---|---|
| `.8` · `.9` · `.11` | 현행 VM 3대 (fb-data · fb-app-ai · fb-monitoring) — `.9`=P1 후, `.8`·`.11`=P4 에서 회수 | 사용 중 |
| `.10` | **물리 호스트 C** (Harbor·Jenkins·SonarQube — 구 fb-ci-harbor VM 에서 IP·인증서 승계, **영구**) | ✅ 사용 중 |
| `.12` | 물리 호스트 A (Proxmox `k8s2`) | 사용 중 |
| `.14`–`.16` | **MetalLB IP 풀** (`.14` 공개 GW · `.15` 내부 GW · `.16` 카나리·업그레이드 일시 병행용 여유) | 예약 |
| **`.17`–`.19`** | **K8s 노드 3대** — `k8s-master` · `k8s-worker-b1` · `k8s-worker-b2` (호스트 B) | ✅ 사용 중 |
| `.20`–`.21` | K8s 노드 램프분 (worker-a1 = P1 후 · worker-a2 = P4) | 예약 — 🔴 **할당 직전 실점유 확인 필수**(arp/ping 스윕 + 공유기 DHCP 예약 대조. `.13` 도 예약해 뒀다가 타인 VBox 장비가 물고 있어 폐기했다). 점유 시 다음 빈 IP 로 밀고 **tfvars·pg_hba·이 표를 같은 값으로 정렬** |
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
| ArgoCD | **10.2.1** (v3.4.5) | platform AppProject + Application 3(LGTM) — 앱 트랙 배선은 §4.2 대기 |
| Loki | 차트 **7.1.0** (3.6.8) | **SingleBinary**·MinIO 백엔드·168h — ArgoCD Application(§4.3) |
| Tempo | 차트 **1.24.4** (2.9.0) | 모놀리식·MinIO 백엔드·168h — ArgoCD Application(§4.3) |
| Alloy | 차트 **1.11.0** (v1.18.0) | DaemonSet·**kube-system**(hostPath) — ArgoCD Application(§4.3) |

| 계층 | 구성 | 상태 |
|---|---|---|
| **컨트롤플레인** | **kubeadm 직접** (Kubespray 기각 — 플랜 §2.5) · master ×1 (VIP/HAProxy 불필요) · etcd 스냅샷 → S3 · **metrics-server**(HPA 전제) | 🔶 init 완료(1.34.10, `controlPlaneEndpoint=.17:6443` · kubelet 예약 명시) · **etcd 스냅샷·metrics-server 미착수** |
| **CNI** | Cilium (eBPF) · kube-proxy 대체 · `socketLB.hostNamespaceOnly=true` 🔴 | ✅ 1.19.6 — `cni.exclusive=false` 도 선반영(Istio CNI 체이닝 전제) |
| **라우팅 모드** | ✅ **VXLAN 확정·락** (2026-07-27 실측 — 예상이던 native 를 뒤집음) | ✅ 가동 중. 근거 = §1.0.1 / [플랜 §3.2](./mp_k8s_infra_migration_plan.md) |
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

| ns | 담는 것 | 메시 | PSS enforce(실물) |
|---|---|---|---|
| `app` | FastAPI 9 + frontend + **ranking-serving** = **11 워크로드** | **ON** | **restricted** + `istio-injection: enabled` |
| `data` | PG·ES·Kafka·Redis(오퍼레이터 생성) + **PGSync·redis-pgsync** | OFF | **baseline**(warn/audit=restricted) |
| `pipeline` | Kafka 컨슈머 4 + CronJob 11 + **ranking-retrain** | OFF | **baseline**(warn/audit=restricted) |
| `observability` · `argocd` · `*-system` | 관측·CD·오퍼레이터 | OFF | **baseline**(warn/audit=restricted) |

🔴 **data·pipeline 을 baseline 으로 둔 이유** = 오퍼레이터(CNPG·ECK·Strimzi)가 만드는 파드를 restricted 로 막으면
P2 에서 원인 찾기 어려운 실패가 난다. **단 baseline 도 특권 initContainer 는 거부** — ECK 의
`vm.max_map_count` init 이 여기 걸려서 노드 sysctl 선반영으로 우회한다(런북 §9-9).
**PriorityClass 실값**(매니페스트에 이 이름 그대로 — 없는 이름 = 스케줄 거부):
`data-critical` 1000000 · `app-normal` 100000 · `pipeline-low` 1000. 정의 = `roles/k8s_cluster_base`.

*youtube(영상 추출)는 워크로드가 아니다 — `ml/video-recipe/` 는 코드만 존재하고 어느 서비스에도 배선돼 있지 않다(미통합). 통합 시점에 배선·ns 를 결정한다.*

### 2.3 워크로드 네이밍 규칙 (2026-07-28 확정)

**`Service` 는 bare(`account`·`recipe`…), 그 외 오브젝트는 `mp-` 접두사.**

| 대상 | 이름 | 예 |
|---|---|---|
| **Service** `metadata.name` | **bare** (접두사 X) | `account`, `recipe`, `chat` |
| Deployment·ExternalSecret·타깃 Secret·ArgoCD Application `metadata.name` | `mp-<svc>` | `mp-account`, `mp-account-secrets` |
| `app:` 라벨 (Service selector·Prometheus 그룹핑·`OTEL_SERVICE_NAME`) | **bare** (논리 신원) | `app: account` |
| 공유 오브젝트(`app-common` ConfigMap 등) | 서술형 이름 유지 | `app-common` |

- 🔴 **왜 Service 만 bare 인가** — Service 이름이 곧 클러스터 DNS 다. 서비스 간 호출과 frontend nginx 리버스프록시가 **전부 bare 이름**으로 서로를 부른다(`http://account:8004`, `nginx.conf: set $u recipe:8001`). Service 에 `mp-` 를 붙이면 이 계약이 전부 깨진다(NXDOMAIN). 반대로 Deployment/App 이름은 아무도 DNS 로 안 읽으므로 접두사가 무해하다. → mp-mealplan 파드에서 `account`·`pantry`·`ranking-serving` bare DNS 해석 실증(2026-07-28).
- `mp-` 의 목적 = kubectl/ArgoCD 목록에서 앱 워크로드를 한눈에 식별(이미지·Harbor 프로젝트 `mealplanning/mp-*` 와 정합). DNS·라벨 신원과는 분리한다.
- 이미지 레포는 `mp-<svc>-service`(백엔드 8) · `mp-ranking-serving` · `mp-frontend`(‑service 접미사 없음).
- **frontend 는 PSS restricted 대응으로 nginx 를 `listen 8080`(비특권 포트)으로 재빌드**한다 — 포트 80 은 NET_BIND_SERVICE 를 요구하는데 restricted 가 금지한다.

---

## 3. 🔴 구축 시 반드시 지킬 것 (사고 이력 기반)

전부 **실제로 겪은 사고**에서 나온 항목이다. 상세 = [`docker-infra-status.md §7`](./docker-infra-status.md) · [`mp_k8s_infra_migration_plan.md §10`](./mp_k8s_infra_migration_plan.md).

- **Kafka**: `auto.create.topics.enable=false` · `KafkaTopic` CRD 가 토픽 생성의 **유일 경로** · **PV 실사용 검증**
  - 근거: 2026-07-20 브로커 자동생성이 `create_topics.py`를 무력화(1파티션 사고) · 2026-07-21 `KAFKA_LOG_DIRS` 미배선으로 recreate 시 **토픽 전멸**
- **Cilium**: `socketLB.hostNamespaceOnly=true` — 없으면 Istio 사이드카가 가로챌 ClusterIP가 사라져 **mTLS가 조용히 깨진다**
- 🔴 **PSS restricted × Istio 자동생성 파드 = 반복되는 3연타.** `app` ns 에 뭔가 새로 뜨지 않으면 **먼저 PSS 를 의심**한다. 지금까지 셋 다 같은 뿌리(Istio 가 만들어 주는 파드가 restricted 요건을 안 채움)였다:
  ① istio-init(root+NET_ADMIN) → `pilot.cni.enabled=true` 로 istio-validation 전환 ② frontend nginx 80 → 비특권 이미지 8080 ③ **Gateway 파드 seccompProfile 누락 → `gateways.securityContext`**(2026-07-28). ⚠️ ③은 **Service 가 `.14` 를 정상으로 받아서** 겉보기엔 정상이고 파드만 0 개다 — `PROGRAMMED=False` 와 ReplicaSet 이벤트를 봐야 보인다
- **Gateway 업로드 한도**: Envoy 는 본문 크기 제한이 **없다**(nginx 와 "다른" 게 아니라 없음 — 실측). `client_max_body_size` 대체물로 **EnvoyFilter buffer 필터**를 반드시 같이 올린다 — 안 하면 무제한 업로드가 열린다(object_spec §5.6)
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
| **Terraform** | [`infra/terraform/`](../infra/terraform) | 유지 — **Proxmox(A·B) 전용.** state = PG 원격 backend(⚠️ **P2 에 S3 백엔드로 이관** — VM PG 가 K8s 로 가면 "state 가 자기가 만든 클러스터 안에" 있는 순환 의존이 된다. 런북 Q4·§2-B). 호스트 B 는 **별개 스탠드얼론이라 provider alias `b`**(`vms_k8s.tf` = K8s 노드 3대). **호스트 C 는 대상 아님**(VirtualBox — 프로바이더 안 씀). ⚠️ 은퇴 VM 203 은 **state 에서 제거해 추적 제외** — tfvars 에 되살리면 `.10` 이 호스트 C 와 충돌 |
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
kubectl -n observability port-forward svc/kube-prometheus-stack-grafana 3000:80   # Grafana port-forward (비상용)
#   Grafana 상시 접속 = http://<아무 노드 IP>:30300 (NodePort, 2026-07-28 — 예: http://192.168.0.17:30300)
#   admin / secrets.yml:grafana_admin_password. LB 는 게이트웨이 전용 규칙이라 NodePort 를 쓴다.
#   P1 에서 내부 게이트웨이(.15) HTTPRoute 뒤로 옮기고 NodePort 는 회수한다.
kubectl -n observability port-forward svc/kube-prometheus-stack-prometheus 9090:9090
kubectl -n observability port-forward svc/minio-console 9001:9001                 # MinIO (fbadmin / secrets.yml:minio_root_password)
kubectl -n argocd       port-forward svc/argocd-server 8080:443                   # ArgoCD (admin)
#   ArgoCD 초기 비번: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
#   🔴 최초 로그인 후 비번 변경 + argocd-initial-admin-secret 삭제
```

⚠️ `admin.conf` 는 **cluster-admin 자격증명**이다(무기한·취소 불가). 팀 공용으로 뿌리지 말 것 — 사람별 계정은 ESO·OIDC 도입 시점에 별도로 판단한다. 임시로 나눠줄 땐 `kubectl create token` 기반 ServiceAccount 토큰을 쓴다.

### 4.2 GitOps config 레포 — **생성·배선 완료 (2026-07-28) · 소유자 배포키 등록만 남음**

**레포 생성됨**: `happyInit/mealplanning-config` (private, 앱 담당자 작성). 실구조는 **app-of-apps** —
`argocd/applications/*.yaml`(child Application — root 가 자동으로 집는 구조) + `services/<svc>/base` +
`overlays/onprem·eks`. *(종전 문서의 `apps/` 디렉토리 가정은 이 실구조로 대체.)* `account.yaml` 정합
확인 완료: `project: mealplanning` · `namespace: app` · **자동 sync 미활성**(P2 전 자동 CD 없음 원칙 준수, 주석으로 준비됨).

**배선 적용 완료** (2026-07-28, `--tags argocd` · failed=0): 정본 Secret(fb-secrets) → ESO 복제
Ready(SecretSynced) → `argocd` ns repository Secret(라벨 확인) + AppProject `mealplanning` 생성.

| 항목 | 값 |
|---|---|
| 자격증명 경로 | `fb-secrets` ns Secret(정본) → **ESO** → `argocd` ns repository Secret. 🔴 ArgoCD 에 직접 안 박는다 |
| AppProject | `mealplanning` — 배포 허용 ns = **app·data·pipeline** 뿐, 클러스터 스코프 리소스 생성 금지(`clusterResourceWhitelist: []`) · `mealplanning-root` — argocd ns 에 `argoproj.io/Application` 만 · `platform` — **sourceRepos = grafana 차트 1개 · destinations = observability·kube-system · 클러스터 스코프 = ClusterRole·Binding 2종**(정의 = `roles/k8s_argocd` defaults·templates) |
| ⚠️ P2 예정 변경 | 🔴 **platform AppProject 3종 동시 확장**(런북 Q1) — 오퍼레이터·데이터 CR 을 `project=platform` 으로 담으려면 sourceRepos(+차트 4·config 레포) · destinations(+data·오퍼레이터 ns) · 클러스터 스코프(+CRD·웹훅)를 **전부** 넓혀야 한다. 하나만 고치면 child sync 가 그대로 죽는다 |
| 정본 | 배선(Secret·ExternalSecret·AppProject) = **Ansible `roles/k8s_argocd`** / 앱 매니페스트 = **config 레포**(argocd/applications + services) |
| 배포키 | `secrets.yml: argocd_repo_ssh_key`(2026-07-28 생성, ed25519) — ✅ **소유자 등록 완료**(read-only) |
| URL 일치 규칙 | 🔴 repository Secret 의 URL 과 Application `source.repoURL` 은 **문자열까지 일치**해야 한다(ssh/https 혼용 금지) — 현재 둘 다 `git@github.com:happyInit/mealplanning-config.git` ✓ |

✅ **연결 실증 완료 (2026-07-28)** — 소유자가 배포키 등록 후 끝단까지 검증: ① 배포키로 `git ls-remote`
읽기 인증 성공 ② **임시 Application(sync 없음)으로 ArgoCD 실 fetch 실증** — 비교 연산 `OutOfSync`(정상 —
미배포 상태) · revision 이 레포 HEAD 와 일치 · ComparisonError 없음(= `services/account/overlays/onprem`
**kustomize 렌더도 통과**). 실증 후 임시 Application 철거(전례 동일 패턴). **앱 Application 적용(app-of-apps
root)은 P1 에 앱 담당자 런북으로 진행한다** — 배선은 인프라 몫, 배포는 앱 트랙 몫.

**app-of-apps root 지원 (2026-07-28 추가)** — 앱 담당자가 root(`mealplanning-root` Application)를 먼저
적용해 봤더니 `InvalidSpecError` 로 막혀 있었다(실측): root 는 **argocd ns 에 child Application 오브젝트를**
만들어야 하는데 `mealplanning` 프로젝트 허용 ns 는 app·data·pipeline 뿐. mealplanning 에 argocd ns 를
추가하는 안은 화이트리스트가 전역(`*/*`)이라 기각 → **root 전용 AppProject `mealplanning-root` 신설**
(destination = argocd ns 만 · 리소스 = `argoproj.io/Application` 한 종류만). 울타리 검증 완료(임시 root 로
비교 통과 후 철거). 🔴 **root Application 의 `spec.project` 는 `mealplanning-root` 여야 한다** — child 는
지금처럼 `mealplanning`. ✅ **전환 완료(2026-07-28)** — 앱 담당자가 root project 변경, root **Synced/Healthy**
도달(automated sync 로 account 인수). child account = OutOfSync/Missing 은 정상(실배포는 P1 수동 sync).
**app-of-apps 가동 — config 레포 트랙 전체 종결.**

✅ **repository Secret 단일화 완료 (2026-07-28)** — 앱 담당자가 같은 URL 로 수동 시크릿
(`mealplanning-config-repo`)을 만들어 둬 중복이었다(ArgoCD 는 동일 URL 시크릿이 여럿이면 비결정 픽 —
간헐 실패형 장애 예약). **합의 후 수동본 삭제, 정본 = ESO 경유 `repo-food-budget-config` 하나**로 단일화.
삭제 직후 refresh 는 DeadlineExceeded 가 한 번 났고(사용 중 시크릿 제거의 과도기) **hard refresh 로
정상 복귀 — ESO 자격증명의 실사용까지 이때 확증됐다**(그전 성공은 수동본을 탔을 수 있음). 앱 담당자의
GitHub 배포키·레포·Application 은 전부 그대로. **배선은 클러스터에 1회** — 팀원별 반복 작업이 아니다
(팀원에게 필요한 건 레포 write 와 클러스터/ArgoCD 접근뿐).

⚠️ **GitHub 권한 구조 주의** — 개인 계정 레포는 **소유자 1명만 admin**이고 콜라보레이터는 전부 write 로 고정된다
(admin·maintain 롤은 조직 레포 전용). 그래서 **배포키·브랜치 보호·웹훅은 소유자만** 만질 수 있다.
P2 의 Jenkins 자동 태그 커밋에는 **쓰기 가능한** 자격증명이 하나 더 필요한데 그것도 소유자 몫이다.

🔴 **ArgoCD Application 삭제는 캐스케이드가 아니다** — `resources-finalizer.argocd.argoproj.io` 가 없으면
Application 을 지워도 **배포된 리소스는 그대로 남는다**(실측 확인). P1 에서 앱을 걷어낼 때 주의.

### 4.3 ArgoCD 플랫폼 트랙 — LGTM 선배포 (2026-07-28 가동)

P4 항목이던 "LGTM in-cluster 이전" 중 **스택 세우기만 앞당겼다** (리스크 검사 후 확정 — 근거는
[플랜 §9](./mp_k8s_infra_migration_plan.md): P1 브리지가 메트릭만 커버해 K8s 앱 로그가 P1~P3 동안
`kubectl logs` 뿐이던 공백 해소 + 워커 예산표 §2.2 가 이미 Loki 1G·Tempo 2G 를 포함 + 3노드가 전부
호스트 B 안이라 물리 1GbE 를 안 탄다). 🔴 **컷오버는 P4 유지** — 알림규칙 20개·Slack 수신자·Grafana
대시보드 이관·`.11` 철거는 여기서 안 했다. **그전까지 in-cluster LGTM 은 예비 스택**이고 프로덕션 관측은 `.11`.

| 항목 | 값 |
|---|---|
| 구성 | **Loki**(SingleBinary·PVC 10Gi·retention 168h) · **Tempo**(모놀리식·PVC 10Gi·168h) — observability ns / **Alloy**(DaemonSet 3노드, 파드 로그 테일 → Loki) — **kube-system**(hostPath 필수 → node-exporter 수칙) |
| 백엔드 | MinIO 버킷 `loki`·`tempo`(P0 생성분). **자격증명은 Secret `lgtm-minio-creds` + `-config.expand-env=true`** — values 평문 금지 |
| 관리 | **ArgoCD Application ×3** (project=**platform**, automated+selfHeal+prune, finalizer 포함) · 소스 = **공개 Helm 차트 레포 직접**(자격증명·config 레포 불요) · values = Application 인라인 |
| 정본 | AppProject `platform` = **`roles/k8s_argocd`**(존치) / Application·Secret·데이터소스 CM = **`roles/k8s_platform_apps`** — ⚠️ **이사 방식 확정(2026-07-28 런북 Q2)**: 멀티소스(`$values`)가 아니라 **config 레포 `platform/argocd/` 의 child Application 으로 이사**하고, 그 뒤 **`k8s_platform_apps` 태스크는 은퇴**한다(Ansible 바닥 = AppProject + platform-root 하나). 순서 고정 = git 추가 → root 인수 확인 → **같은 날** 롤 은퇴 |
| Grafana | kps Grafana sidecar 가 `grafana_datasource` 라벨 CM(`lgtm-grafana-datasources`)을 자동 로드 — Loki `:3100`·Tempo `:3200`. kps values 무변경 |
| 검증(2026-07-28) | 3 Application Synced/Healthy · 플랫폼 ns 8종 로그 유입 · **강제 flush → MinIO 청크 실증** · Tempo 폴러 무에러 · master +136Mi(limits 256Mi 내) · 재실행 `changed=0` |

**차트 함정 (실측 — 값 바꿀 때 재확인)**: ① Loki 기본 모드 = SimpleScalable + chunks-cache(memcached 8Gi)
— SingleBinary 로 갈 때 **read/write/backend replicas 를 명시적으로 0** 으로 꺼야 한다(validate.yaml 이
deploymentMode 무관하게 검사 → ComparisonError 로 실측). ② Tempo `_ports.tpl` 이
`receivers.jaeger.*` 를 직접 참조 — **jaeger 수신자를 제거하면 렌더가 죽는다**(기본값 유지).
③ Loki 는 `persistence.storageClass`, Tempo 는 `persistence.storageClassName`(키가 다름).
④ 트레이스 유입 배선(Istio telemetry→Tempo OTLP `:4317`)은 소비자가 생기는 P1 에서.
⑤ in-cluster Alertmanager 수신자 없음 + `.11` 은 파드 CIDR 을 못 봄 → **이 스택이 죽어도 무알람**
(예비 스택이라 수용 — ServiceMonitor 는 켜 둬서 in-cluster Prometheus 로 수동 확인 가능).

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
| P0 | 호스트 B 3노드 · 기반(Cilium·Istio·MetalLB·OpenEBS·MinIO·cert-manager·ESO·ArgoCD·kube-prometheus-stack·metrics-server) · **라우팅 모드 iperf3 측정·락** · ~~백업·복구 경로 검증~~(→P2 직전) | ✅ **완료(2026-07-28)** — LGTM 선배포(§4.3)·config 레포 연결·app-of-apps 가동(§4.2)까지. **S3 백업·복구 왕복은 P2 직전으로 이동**(2026-07-28 결정) |
| P1 | **앱 이전** — Gateway(`.14`)+HTTPRoute+앱 11(env=VM 데이터 좌표) → 유입 전환(nginx→GW) · **in-cluster Prometheus agent→`.11` remote_write** · `.9` 정지(🔴 `.env` 백업 필수)→파괴 · 구 `.10` VM 파괴 → **worker-a1(~12GB) 생성 = 4노드** | ⬜ **다음 단계** |
| P2 | 🔴 **선행: S3 백업·복구 왕복 증명**(P0 에서 이동 — 이거 없이 착수 금지) · **데이터 티어 + 파이프라인 전환창** — PG·ES·Redis·Kafka+Pooler+PGSync 구축 · PG 복제 따라잡기 → 전환창: 프로모트 + 파이프라인 동시 전환(사전 dark-deploy) + 앱 ConfigMap 좌표 갱신 (유일한 다운타임) | ⬜ **런북 확정**([`p2_data_runbook`](./mp_k8s_p2_data_runbook.md) — 2026-07-28 grilling Q1~Q10) |
| P3 | **스케일** — Pooler 검증 → 앱 풀 축소 → account HPA → KEDA lag 스케일링 | ⬜ |
| P4 | 정리 — `.8`·`.11` 해체 · **LGTM 컷오버**(스택은 ✅ 선배포 2026-07-28 §4.3 — 남은 것 = 알림규칙 20개·Slack·Grafana 대시보드 이관 + agent 철수) · worker-a1 14GB 확장 + worker-a2 = **5노드 완성** | ⬜ |

**과도기 명시 사항**: ① P2 전까지 자동 CD 없음(앱 변경 = 수동 반영) ② P1~P2 앱 파드 egress 에 `192.168.0.8`(VM 데이터) ipBlock 허용 — P2 에서 제거 ③ 파드→VM 구간은 WireGuard 미적용(현행 compose 와 동일한 평문 — 후퇴 아님).

---

## 6. 미결

1. **이전 착수 시점** — 선행조건은 충족. 5인 역할분담·9주 타임라인과의 정합만 남음
2. ~~**Cilium 라우팅 모드 최종**~~ → ✅ **해소(2026-07-27): VXLAN 확정·락**(§1.0.1). 남은 집계 대역 측정도 **해소처 확정** — P2 리허설 산출물(§1.0.1·런북 §7)
3. **Redis 오퍼레이터 선정** — 페일오버 시 master Service 를 실제로 갱신하는지 **P2 준비 A-1 에서 실물 검증**(앱 코드 수정 0이 요구사항 — 불가 시 Sentinel-aware 전환 = **접속 코드 4곳**: chat·price `db.py` + `pipelines/stream/_redis.py` + `pipelines/ingest/refresh_price_matview.py`, 별도 이슈)
4. **PR 시점 pytest 게이트 공백** — 러너 은퇴로 GH `ci-test` 사망, Jenkins 는 main 머지 후에만 검사. 후속 = Jenkins 멀티브랜치 PR 빌드
5. **호스트 B 물리 RAM 판정** — memtest86+ **미실행**(§1.0.2). 결과에 따라 RAM 교체 vs `memmap` 마스킹 vs 용의선상 이동(커널·KVM)

---

*이 문서는 인프라 상태 변경 시 갱신한다. 결정을 바꿀 때는 [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)에서 바꾸고 여기로 반영한다. 현행 Docker 스택 운영은 [`docker-infra-status.md`](./docker-infra-status.md).*
