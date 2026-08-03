# CIS Kubernetes Benchmark 감사 — 2026-08-03 1회 실측

> **도구** = `aquasec/kube-bench:latest` · **대상** = kubeadm 1.34.10 · Cilium 1.19.6(kubeProxyReplacement)
> **방식** = 읽기 전용 Job 2개(`k8s-master` / `k8s-worker-b1`). 클러스터 상태 변경 없음. 수거 후 Job 삭제.
> **재실행** = `docs/` 하단 §5 의 매니페스트를 다시 apply.

---

## 0. 결과 요약

| 대상 | PASS | FAIL | WARN |
|---|---:|---:|---:|
| **control plane** (master·etcd·controlplane·policies) | 48 | **10** | 48 |
| **worker node** (`k8s-worker-b1` 대표) | 16 | **3** | 6 |

🔴 **FAIL 13건을 액면대로 읽으면 안 된다.** 아래 §1 처럼 **성격이 셋으로 갈린다** —
우리 아키텍처 선택 때문에 원리적으로 FAIL 인 것(오탐), 지금 고치면 클러스터가 깨지는 것,
그리고 **진짜 갭**. 실제 조치 대상은 **13건 중 5건**이다.

---

## 1. FAIL 13건 3분류

### 🔴 A. 진짜 갭 — 조치 대상 (5건)

| # | 항목 | 실측 | 왜 진짜인가 |
|---|---|---|---|
| **1.2.16~19** | `--audit-log-path` 외 3종 | **apiserver 에 audit 플래그가 하나도 없다** (`kubectl get pod -l component=kube-apiserver` 커맨드 확인) | **감사 로그가 통째로 꺼져 있다.** "누가 무엇을 언제 지웠나" 를 사후에 물을 수단이 없다. 4건은 사실상 **한 덩어리**(경로·보존·개수·크기) |
| **1.2.15 · 1.3.2 · 1.4.1** | `--profiling=false` × 3 | 플래그 없음 = **기본값 `true`** | apiserver·controller-manager·scheduler 의 pprof 엔드포인트가 열려 있다. 인증은 걸리지만 **끌 이유가 있고 끄는 비용이 거의 0** |
| **4.1.1 · 4.1.9** | kubelet 파일 권한 644 → 600 | 두 워커 파일 모두 기본값 | 저위험이지만 **Ansible 한 줄**이라 안 할 이유가 없다 |
| **1.1.12** | etcd 데이터 디렉터리 소유권 `etcd:etcd` | kubeadm 기본 = `root:root` | 영향은 낮다(정적 파드가 root 로 돔). **단일 멤버 etcd** 라 손대다 깨지면 클러스터가 통째로 간다 → 우선순위 최하 |

> **묶어 보면 실질 작업은 3덩이다**: ① 감사 로그 켜기(4건) ② profiling 끄기(3건) ③ kubelet 권한(2건).

### ⚠️ B. 지금 고치면 깨지는 것 — 보류 (1건)

| # | 항목 | 🔴 왜 지금 안 하나 |
|---|---|---|
| **1.2.5** | `--kubelet-certificate-authority` 미설정 | 지적 자체는 맞다 — apiserver 가 kubelet 의 서빙 인증서를 **검증하지 않는다**(apiserver↔kubelet 구간 MITM 여지). **그런데 kubeadm 기본 kubelet 서빙 인증서는 자체서명이라, 이 플래그만 켜면 검증이 실패해 `kubectl logs`·`exec`·`top` 이 클러스터 전역에서 죽는다.** 제대로 하려면 `serverTLSBootstrap: true` + kubelet CSR 승인이 선행돼야 한다(노드 5대 전부). → **별건으로 분리.** 발표 전에 손대는 건 금물 |

### ✅ C. 우리 아키텍처상 원리적 오탐 — 조치 불필요 (1건)

| # | 항목 | 실측 |
|---|---|---|
| **4.3.1** | kube-proxy metrics 가 localhost 바인딩이 아님 | **kube-proxy 가 설치돼 있지 않다** — `kubectl -n kube-system get ds kube-proxy` → `NotFound`. Cilium `kubeProxyReplacement` 로 대체했기 때문이다. 검사기가 존재하지 않는 컴포넌트를 검사한 것 |

### 나머지 — `--service-account-extend-token-expiration` (1.2.30)

기본값 `true` 라 FAIL 이지만, `false` 로 바꾸면 **토큰 갱신을 못 따라오는 구형 클라이언트가 조용히 인증에 실패**한다.
우리 워크로드가 전부 최신 SA 토큰을 쓰는지 확인 전에는 건드릴 값이 아니다 → **보류(B 와 같은 성격)**.

---

## 2. WARN 54건에 대해 — 🔴 이 도구를 오해하기 가장 쉬운 지점

### 2.1 kube-bench 는 "전체 스캔기" 가 아니다

체크가 두 종류이고, **성격이 완전히 다르다**:

| | **Automated** | **Manual** |
|---|---|---|
| 기계가 하는 일 | 플래그·파일권한을 **실제로 읽고 판정** | **판정하지 않는다.** 항상 WARN + 가이드 문구 출력 |
| 결과의 의미 | PASS/FAIL = **검증된 사실** | WARN = *"여긴 사람이 봐야 한다"* |
| 이번 실측 | master 58 · node 19 | master **48** · node **6** |

🔴 **우리 WARN 54건은 100% `(Manual)` 이다** (Automated WARN 0건 — 실측).
즉 **우리 클러스터 상태와 무관하게 항상 뜨는 값**이고, 여기서 위반 여부를 읽어낼 수 없다.

왜 이런 항목이 있냐면 CIS 원문 자체가 *"Minimize wildcard use in Roles"*,
*"Ensure that default service accounts are not actively used"* 같은 문장이기 때문이다.
**"최소화"의 기준은 조직마다 다르다** → CIS 가 아예 "사람이 판단" 으로 분류했고 kube-bench 는 그걸 따른다.

**정리하면** — 설정 플래그·파일 권한은 **진짜로 전수 스캔**해서 현재 상태를 준다(= FAIL 13건).
*"정책이 적절한가"* 는 **스캔 자체를 하지 않는다**(= WARN 54건).

### 2.2 그래서 WARN 은 "질문지"로 쓴다 — 우리 답 (2026-08-03 라이브 실측)

| Manual 항목 | 우리 답 (근거) |
|---|---|
| `5.1.1` cluster-admin 최소 사용 | 바인딩 **4개**. `system:masters`·`kubeadm:cluster-admins` = kubeadm 기본 / `mp-bongsu-cluster-admin`·`mp-taehyun-cluster-admin` = **의도적**. RBAC Phase1 에서 5인 중 **2명만** admin, 나머지는 app-dev·observability·data-dev (`docs/mp_k8s_rbac_plan.md`) |
| `5.2.x` Pod Security Standards | **ns 라벨로 강제 중.** `app`·`fb-secrets`·`mp-users` = **restricted** · `data`·`argocd`·`pipeline`·`observability` 등 9개 = **baseline** |
| `5.3.2` ns 별 NetworkPolicy | `app` 3(+CNP 4) · `data` 8(+1) · `pipeline` 2(+5) · `argocd` 6 (`docs/mp_netpol_zerotrust_flow.md`) |
| `5.1.5` default SA 미사용 | 워크로드가 전용 SA 사용 — 제로트러스트 트랙 산출물 |
| `5.3.1` CNI 가 NetworkPolicy 지원 | **Cilium 1.19.6** — NetworkPolicy + CiliumNetworkPolicy(FQDN·엔티티) 둘 다 사용 중 |
| (해당 없음) mTLS | Istio PeerAuthentication **STRICT** (app ns 메시) |

### 2.3 🔴 답하다 보니 드러난 진짜 구멍 2개

WARN 을 질문지로 소화한 결과, **검사기가 준 게 아니라 우리가 찾은** 갭이다:

| 갭 | 실측 | 판단 |
|---|---|---|
| `observability` ns 에 **NetworkPolicy 0개** | app·data·pipeline·argocd 는 있는데 여기만 비었다 | Prometheus·Loki·Grafana·**MinIO** 가 사는 ns 다. MinIO 엔 이제 **PG 덤프**가 들어간다 → 우선순위 재평가 필요 |
| 시스템 ns 에 **PSA 라벨 없음** | `kube-system`·`istio-system`·`cert-manager`·`metallb-system`·`openebs`·`external-secrets` | 시스템 컴포넌트는 baseline 도 못 지키는 경우가 많아 **의도적 미적용일 수 있으나, 결정으로 기록된 바가 없다** |

> **이것이 이 도구의 올바른 사용법이다.** WARN 을 무시하는 것도, 54건에 겁먹는 것도 아니고,
> **하나씩 답해보고 답이 안 나오는 칸을 찾는 것**.

---

## 3. 권고 순서

| 순위 | 조치 | 소요 | 위험 |
|---|---|---|---|
| **1** | **profiling 끄기 3종** — kubeadm `ClusterConfiguration` 의 `extraArgs` | 15분 | 낮음(재시작 = 정적 파드 롤) |
| **2** | **kubelet 파일 권한 600** — Ansible `k8s` 롤에 `mode` 명시 | 10분 | 낮음 |
| **3** | **감사 로그 활성화** — audit policy 파일 + hostPath 볼륨 + 4개 플래그 | 40~60분 | 중간 — 🔴 **디스크 감시 필수**. 마스터 디스크가 차면 apiserver 가 선다. `maxsize`·`maxbackup` 을 반드시 같이 건다 |
| **4** | etcd 디렉터리 소유권 | 10분 | 🔴 단일 멤버 etcd — 이득 대비 위험이 커서 **맨 뒤** |
| **보류** | `1.2.5` kubelet CA · `1.2.30` SA 토큰 | 별건 | 잘못 켜면 `logs`/`exec` 전역 사망 |

> 🔴 **1·2 는 IaC 로 넣는다**(kubeadm ClusterConfiguration / Ansible). 마스터에 손으로 넣으면
> 다음 `kubeadm upgrade` 나 노드 재구축에서 조용히 사라진다 — 이 클러스터는 재구축 전제로 만들었다.

---

## 4. 이 감사가 못 본 것

| 영역 | 이유 |
|---|---|
| 워커 3대(`a1`·`a2`·`b2`) | 대표 1대(`b1`)만 실행. **베이스라인이 Ansible 로 동일**하므로 결과도 같을 것으로 본다 — 다만 *가정*이지 실측이 아니다 |
| 컨테이너 이미지 취약점 | 범위 밖 (CI 의 Trivy 게이트가 담당) |
| 런타임 이상행위 | 범위 밖 (kube-bench 는 설정 감사 도구다) |

---

## 5. 재실행 방법

매니페스트 = `docs/manifests/kube-bench-audit.yaml` (읽기 전용 · `kube-system` · 실행 후 삭제).

```bash
kubectl apply -f docs/manifests/kube-bench-audit.yaml
kubectl -n kube-system wait --for=condition=complete job/mp-kube-bench-master --timeout=180s
kubectl -n kube-system logs job/mp-kube-bench-master
kubectl -n kube-system logs job/mp-kube-bench-node
kubectl delete -f docs/manifests/kube-bench-audit.yaml   # 반드시 정리
```

⚠️ **상시 배포하지 않는다.** `hostPID` + 호스트 경로 다수를 마운트하는 파드라 상주시키면
그 자체가 공격 표면이다. 감사 때만 띄우고 지운다.
