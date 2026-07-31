# P1 앱 이전 담당자 핸드오프

> **이 문서의 범위** — P0(클러스터 + 기반 스택)이 끝난 시점에서, **앱을 K8s 로 옮기는 사람이 알아야 할 것만** 적는다.
> 현황·아키텍처 정본은 [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md), 결정 근거·컷오버 절차는
> [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md), 오브젝트 수준 설계는
> [`mp_k8s_infra_object_spec.md`](./mp_k8s_infra_object_spec.md) 다. **여기서 그 내용을 복제하지 않는다** — 링크로 가리킨다.
> 작성 2026-07-27 (P0 완료 시점)

---

## 1. 먼저 붙어보기 (5분)

```bash
# kubectl 클라이언트는 apiserver ±1 마이너까지만 지원 → 1.34.x 를 쓴다
curl -LO https://dl.k8s.io/release/v1.34.10/bin/linux/amd64/kubectl
install -m 0755 kubectl ~/.local/bin/kubectl

# kubeconfig 는 **머지**한다(기존 컨텍스트 덮어쓰지 말 것). 절차 = status §4.0
ssh ubuntu@192.168.0.17 'sudo cat /etc/kubernetes/admin.conf' > /tmp/mp.conf
cp ~/.kube/config ~/.kube/config.bak
KUBECONFIG=~/.kube/config:/tmp/mp.conf kubectl config view --flatten > /tmp/merged
install -m 0600 /tmp/merged ~/.kube/config && kubectl config use-context mp-k8s

kubectl get nodes            # 3대 Ready 면 정상
kubectl get pods -A          # kube-proxy 가 **없는 게** 정상이다(Cilium 이 대체)
```

⚠️ `admin.conf` 는 무기한·취소 불가한 cluster-admin 자격증명이다. 팀에 그대로 뿌리지 말 것.

---

## 2. 네가 물려받는 것 — 이름과 규칙

앱 매니페스트를 쓸 때 **그대로 참조해야 하는 실제 이름들**이다.

| 종류 | 이름 | 알아야 할 것 |
|---|---|---|
| 네임스페이스 | `app` | 🔴 **PSS `enforce: restricted`** + `istio-injection: enabled` 이미 붙어 있다 |
| | `data` · `pipeline` · `observability` · `argocd` | 전부 `enforce: baseline` + `warn/audit: restricted` |
| 비밀 정본 ns | `fb-secrets` | 여기 Secret 을 두면 ESO 가 워크로드 ns 로 복제한다 |
| SecretStore | `ClusterSecretStore/fb-kubernetes` | `ExternalSecret` 의 `secretStoreRef` 에 쓸 이름 |
| PriorityClass | `data-critical` > `app-normal` > `pipeline-low` | 앱 워크로드는 **`app-normal`**. PGSync 도 app 급이다 |
| StorageClass | `openebs-lvm`(기본·Delete) · `openebs-lvm-retain`(Retain) | 둘 다 **RWO·WaitForFirstConsumer**. 🔴 **RWX 는 존재하지 않는다** |
| LB 풀 | `gateway-pool` (`.14`–`.16`) | 🔴 아래 3-⑤ 참조 |
| 인증서 발급자 | `ClusterIssuer/fb-local-ca` | 로컬 CA 승계 — 전 노드·팀이 이미 신뢰한다 |
| 노드 레이블 | `topology.kubernetes.io/zone=host-b` | 배치 고정이 필요하면 이 키를 쓴다(현재 3대 전부 host-b) |
| 레지스트리 | `192.168.0.10/mealplanning/*` | 앱 트랙 베이스라인 = **`:1.1.9`** |
| **config 레포** | 🔴 **아직 없다 — 네가 만든다** | 앱 매니페스트가 들어갈 별도 레포. 연결 배선·절차는 준비돼 있다(status §4.2, 3분). ⚠️ **P2 에 인프라가 같은 레포에 `platform/`(데이터 티어·오퍼레이터)·`pipelines/` 를 추가한다** — `apps/` 아래로 몰아 두면 충돌 없다([런북 §3](./mp_k8s_p2_data_runbook.md)) |
| AppProject | `mealplanning` | 레포 연결 시 Ansible 이 만든다. 배포 허용 ns = **app·data·pipeline** 뿐 |

**가용 자원**(2026-07-27 실측): 워커 allocatable **각 9.5 GiB / 5.6 CPU**, 현재 요청량 15~21% →
3노드 기준 빈자리는 ~15 GiB 지만 🔴 **그게 앱 몫은 아니다.** P2 에 데이터 티어 **13.4 GiB** 가 같은
클러스터로 들어오고, 예산상 **앱(사이드카 포함) 몫 ≈ 5.1 GiB · 파이프라인 ≈ 1.5 GiB** 다
([플랜 §2.2 예산표](./mp_k8s_infra_migration_plan.md) · [P2 런북 §9-11](./mp_k8s_p2_data_runbook.md)).
requests 를 이 선 안에서 잡아라 — **P1 완료 직후 `ResourceQuota` 로 캡이 걸린다**(앱 ns ≈4Gi + 사이드카,
[런북 Q14](./mp_k8s_p2_data_runbook.md)). 넘겨 잡으면 P2 데이터 티어가 스케줄 불가로 막힌다.

---

## 3. 🔴 반드시 밟는 함정 — 모르면 시간을 태운다

**① `app` ns 는 PSS `restricted` 다.** 다음을 만족하지 않는 파드는 **생성 자체가 거부**된다:
`runAsNonRoot: true` · `allowPrivilegeEscalation: false` · `capabilities.drop: ["ALL"]` ·
`seccompProfile.type: RuntimeDefault`. **frontend nginx 가 여기 걸린다** — 80 포트는 특권 포트라
비특권 이미지로 바꾸고 **8080 리스닝**으로 전환해야 한다([플랜 §10 P1 체크리스트](./mp_k8s_infra_migration_plan.md)).
*(관측 스택의 node-exporter 도 같은 벽에 막혀 kube-system 으로 옮겼다 — 전례가 있다.)*

**② `type: LoadBalancer` 에 풀 주석이 없으면 영원히 Pending 이다.** MetalLB 풀을 `autoAssign: false`
로 두어 "LB 는 게이트웨이 전용, 상시 2개" 규칙을 컨트롤러가 강제하게 했다. Gateway 서비스에:
```yaml
metadata:
  annotations:
    metallb.universe.tf/address-pool: gateway-pool
```
없으면 IP 를 안 준다. **이건 버그가 아니라 가드다.**

**③ 업로드 크기 제한이 사라진다.** nginx `client_max_body_size 15m` 를 Gateway 로 이관하지 않으면
**영수증 OCR 업로드가 413** 이다. 상세 = [object_spec §5.6](./mp_k8s_infra_object_spec.md).

**④ PathPrefix 매칭 규칙이 다르다.** nginx 는 문자열 프리픽스, Gateway API 는 **세그먼트 단위**라
`/api/recipesXYZ` 류가 404 로 갈린다. 13개 location 을 옮길 때 하나씩 확인할 것([object_spec §5.3](./mp_k8s_infra_object_spec.md)).

**⑤ `.9` 를 파괴하기 전에 `.env` 를 백업하라.** JWT_SECRET·Gemini 키 등 **비밀의 실질 정본**이 거기에만 있다.
날리면 복구 불가다. 백업 → `fb-secrets` ns 에 Secret 으로 심고 → ESO 로 `app` ns 에 복제하는 순서.

**⑥ RWO + 단일 replica 워크로드는 `strategy: Recreate`.** 기본 RollingUpdate 는 새 파드가 같은 로컬 PV 를
두 번 마운트하려다 `device already mounted` 로 교착한다(MinIO 에서 실제로 밟았다).

**⑦ 노드 고정은 `nodeSelector`/affinity 로.** `nodeName` 을 직접 박으면 스케줄러를 건너뛰어
`WaitForFirstConsumer` PVC 가 영영 Pending 이다.

**⑧ 이미지 핀은 `:sha`.** `:latest` 는 ArgoCD 가 변경을 감지할 수 없고 롤백 대상도 없다.

**⑨ ArgoCD Application 삭제는 캐스케이드가 아니다.** `resources-finalizer.argocd.argoproj.io` 를 안 붙이면
Application 을 지워도 **배포된 리소스가 그대로 남는다**(P0 에서 실측 확인). 앱을 걷어낼 때 유령이 남는다.

**⑩ CronJob 은 `spec.timeZone: Asia/Seoul`.** 단 **파이프라인 CronJob 11개(크론탭 8줄 + 상주 루프 3)의
환산표·매니페스트는 P2 인프라 몫**이다([런북 Q12](./mp_k8s_p2_data_runbook.md)) — P1 에서 만들 필요 없다.
앱 ns 에 자체 CronJob 을 둘 일이 생기면 그때 이 수칙을 적용하라.

---

## 4. 이미 처리돼 있어서 **안 해도 되는** 것

- **사이드카 주입용 initContainer/NET_ADMIN 불필요** — Istio CNI 가 깔려 있고 Cilium conflist 에 체이닝돼 있다
  (`['cilium-cni','istio-cni']` 실증). 앱 파드에 특권을 줄 필요가 없다(= ①의 restricted 와 양립).
- **앱 기동 순서 문제** — `holdApplicationUntilProxyReady: true` 를 istiod 에 이미 켰다. 우리 앱은 기동
  즉시 PG·ES·Kafka 에 붙는데, 이게 없으면 사이드카 iptables 준비 전에 첫 연결이 깨진다.
- **Gateway API CRD** — v1.6.1 standard 채널 설치됨. `Gateway`·`HTTPRoute` 를 바로 쓸 수 있다.
- **노드의 Harbor CA 신뢰** — containerd 가 `.10` 에서 이미지를 당길 수 있다. 다만 **`imagePullSecret` 은
  따로 만들어야 한다**(레지스트리 인증은 별개).
- **관측 배관** — Prometheus 가 ServiceMonitor 를 ns 상관없이 잡도록 selector 를 풀어 뒀다.
  `ServiceMonitor` 만 만들면 스크레이프된다.

---

## 5. 아직 **없는** 것 — 기대하지 말 것

| 없는 것 | 그래서 P1 에서는 |
|---|---|
| **config 레포 자체 · ArgoCD Application** | ArgoCD 는 설치됐고 **연결 배선은 준비**돼 있다(ESO 경유, 실증 완료). **레포 생성은 네 몫** — 만들고 배포키 등록 후 URL·키만 채우면(status §4.2) 배선이 완성된다. 그다음 `apps/` 에 매니페스트를 커밋하고 Application 을 만드는 게 P1 의 일(= 플랜의 "GitOps 배포 개통"). ⚠️ **Jenkins 자동 태그 커밋은 P2** — 그때까지 이미지 `:sha` 갱신은 **사람이 커밋**한다 |
| **in-cluster 데이터 티어** | PG·ES·Redis·Kafka 는 **아직 VM `.8`** 이다. 앱 ConfigMap 의 좌표를 `.8` 로 두고, egress NetworkPolicy 에 `192.168.0.8` ipBlock 을 열어야 한다(제거 = P2 관찰창 종료 후). 🔴 **이 ConfigMap 이 P2 전환창의 갱신 대상**이다 — PG·ES(+`ES_INDEX`·basic_auth env)·Kafka·Redis 좌표를 **한 ConfigMap 에 모아** 두면 창에서 한 번에 바꾼다. 흩어 놓으면 15분 창이 위험해진다 |
| **S3 백업** | 미착수(버킷·IAM 키 대기). 중요한 것을 클러스터에만 두지 말 것 |
| **ResourceQuota · LimitRange** | 미설정. requests 를 안 적은 파드는 BestEffort 로 떠서 축출 1순위가 된다 — **매니페스트에 직접 적어라**. ⚠️ **P1 완료 직후 도입 예정**(§2 예산 참조 — 캡은 P1 실측 requests 로 보정해 정한다) |
| **Alertmanager 수신자** | in-cluster AM 은 수신자가 비어 있다. Slack 은 P4 까지 VM `.11` 이 쏜다 |
| **RWX 스토리지** | 설계상 금지. 공유가 필요하면 MinIO(S3 API)를 쓴다 |

---

## 6. 작업 경계 — 어디에 뭘 쓰나

| 대상 | 도구 | 위치 |
|---|---|---|
| 노드·기반 스택(Cilium·MetalLB·OpenEBS·cert-manager·MinIO·ESO·관측·Istio·ArgoCD) | **Ansible** | `infra/ansible/k8s.yml` + `roles/k8s_*` |
| 앱 매니페스트(Deployment·Service·**ConfigMap**·HTTPRoute·NetworkPolicy·ExternalSecret) | **ArgoCD** (이미지 태그 갱신은 P2 까지 사람이 커밋) | **네가 만들 config 레포**의 `apps/` |
| VM 프로비저닝(worker-a1 등)·데이터 티어·파이프라인 | **인프라 트랙**(Terraform·Ansible·`platform/`) | 네 몫이 아니다 — §7 의 인계 신호만 주면 된다 |

기반 스택을 손볼 일이 생기면 **helm 을 직접 치지 말고** 롤의 values 템플릿을 고치고 플레이북을 돌린다:
```bash
cd infra/ansible && ansible-playbook k8s.yml --tags istio     # 예: istio 만
ansible-playbook k8s.yml                                      # 전체(정상이면 changed=0)
```
설치된 values 실물은 master 의 `/etc/kubernetes/*-values.yaml`, 매니페스트는 `/etc/kubernetes/fb/` 에 있다.
🔴 `/etc/kubernetes/manifests/` 는 kubelet 의 static pod 디렉토리다 — 거기에 파일을 두지 말 것.

---

## 7. P1 완료 판정 체크리스트

플랜의 P1 체크리스트가 정본이다([§10](./mp_k8s_infra_migration_plan.md)). 여기서는 **P0 산출물과 맞물리는 것**만 추린다.

- [ ] `app` ns 11 워크로드가 **PSS restricted 를 통과**해 뜬다(frontend 8080 포함)
- [ ] Gateway 2개가 `.14`(공개)·`.15`(내부) 를 실제로 받았다 — 풀 주석 확인
- [ ] `/api/*` 13경로가 HTTPRoute 로 이관됐고 **세그먼트 매칭 차이**를 케이스별로 확인했다
- [ ] **15MB 업로드가 413 없이 통과**한다(OCR 경로)
- [ ] mTLS 가 실제로 걸렸다 — 평문 캡처로 **반증**해 볼 것
- [ ] Prometheus → `.11` remote_write 수신 확인, 앱 대시보드 연속성 유지
- [ ] `.9` 정지 **전** `.env` 백업 완료 + `fb-secrets` 에 이관
- [ ] **master 강제종료 재시험** — 이번엔 실제 Gateway·앱 경로로. P0 실측치(인그레스 중단 0 · 복구 26초)가 기준선이다([status §1.0](./mp_k8s_infra_status.md))
- [ ] 🔴 **인프라에 인계 신호** — `.9` 정지(+`.env` 백업 완료)까지 끝나면 알린다. 그 다음(`.9`·구 fb-ci-harbor VM **해체** → RAM 회수 → **worker-a1 12GB 생성** = 4노드 → ResourceQuota 적용)은 **인프라 트랙이 이어받는다**([런북 §2-C-0](./mp_k8s_p2_data_runbook.md)). P2 는 이 4번째 노드 없이 착수할 수 없다 — **P1 이 늦으면 P2 가 그만큼 밀린다**
- [ ] P1 실측 requests 합계를 인프라에 공유(ResourceQuota 캡 산정 입력 — §2)

---

## 8. 막혔을 때

```bash
# 파드가 안 뜬다 → 거의 항상 PSS 아니면 스케줄링이다
kubectl -n app describe pod <name> | tail -20
kubectl get events -n app --sort-by=.lastTimestamp | tail -20

# 서비스가 안 닿는다 → kube-proxy 가 없다는 걸 기억할 것(eBPF)
kubectl -n kube-system exec ds/cilium -c cilium-agent -- cilium-dbg status --verbose | head -40
kubectl -n kube-system exec ds/cilium -c cilium-agent -- cilium-dbg service list | head

# 사이드카가 이상하다
istioctl proxy-status                     # 또는: kubectl -n istio-system logs deploy/istiod
kubectl -n app get pod <name> -o jsonpath='{.spec.containers[*].name}'   # istio-proxy 있는지

# 클러스터를 통째로 다시 세워야 한다면 (P0 자산은 전부 IaC 다)
cd infra/ansible && ansible-playbook k8s.yml
```

사고 이력 기반 필수수칙 전체 = [status §3](./mp_k8s_infra_status.md). **읽고 시작하는 게 싸다.**
