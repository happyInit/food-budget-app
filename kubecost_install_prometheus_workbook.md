# Kubecost 설치·Prometheus 연동 워크북

> 대상: `food-budget-app` 온프레미스 kubeadm 클러스터
> 작성 기준: 2026-07-30
> 설치 대상 버전: Kubecost Helm chart `3.2.0`
> 목적: Kubecost를 현재 서버 구성에 맞게 설치하고, 기존 `kube-prometheus-stack`에서 Kubecost 자체 상태 메트릭을 수집·검증한다.

---

## 1. 결론부터 보기

이 서버에서는 다음 구성을 사용한다.

| 항목 | 이 서버의 값 |
|---|---|
| Kubernetes | kubeadm `1.34.x` |
| Kubernetes API | `192.168.0.17:6443` |
| 노드 | `k8s-master(.17)`, `k8s-worker-b1(.18)`, `k8s-worker-b2(.19)`, `k8s-worker-a1(.20)` |
| Kubecost namespace | `cost` |
| Kubecost release | `kubecost` |
| Kubecost cluster ID | `mealplanning-k8s` |
| StorageClass | `openebs-lvm` |
| Prometheus | `observability` namespace의 `kube-prometheus-stack` |
| Grafana | `https://grafana.mealbong.cloud/` |
| 외부 공개 방식 | 기본은 공개하지 않고 `kubectl port-forward` 사용 |

### 중요한 구조 차이

Kubecost 3.x는 비용 계산을 위해 이 서버의 Prometheus DB를 직접 재사용하지 않는다.

```text
Kubernetes API / kubelet / cAdvisor
              │
              ▼
      Kubecost FinOps Agent
              │
              ▼
 Kubecost Local Store + Aggregator
              │
              ▼
         Kubecost UI/API

Kubecost FinOps Agent / Aggregator의 /metrics
              │
              ▼
기존 kube-prometheus-stack → 기존 Grafana
```

- 비용 데이터: Kubecost FinOps Agent와 Kubecost 저장소가 처리한다.
- 비용·allocation 메트릭과 운영 상태 메트릭: 기존 Prometheus가 `ServiceMonitor`로 수집한다.
- 따라서 과거 일반 Prometheus 구성처럼 ConfigMap의 `scrape_configs`를 직접 수정하지 않는다.
- 현재 Prometheus는 라벨 없는 `ServiceMonitor`도 전체 namespace에서 선택하도록 이미 구성되어 있다.

### 기본 Pod 구성과 필수 여부

이 워크북의 values로 설치하면 상시 실행되는 workload와 Pod는 다음과 같다.

| Kubernetes 리소스 | Pod | 개수 | 필수 여부 | 역할 |
|---|---|---:|---|---|
| Deployment | `kubecost-finopsagent` | 1 | 필수 | Kubernetes 사용량과 비용 계산용 데이터를 수집 |
| Deployment | `kubecost-local-store` | 1 | 조건부 필수 | 수집 데이터를 로컬 PVC에 저장 |
| StatefulSet | `kubecost-aggregator` | 1 | 필수 | 데이터를 집계하고 비용 조회 API 제공 |
| Deployment | `kubecost-frontend` | 1 | 선택 | Kubecost 웹 UI 제공 |

기본 설치 결과:

```text
Deployment 3개 + StatefulSet 1개
상시 Pod 4개
Pod당 애플리케이션 컨테이너 1개 = 상시 컨테이너 총 4개
```

데이터 흐름:

```text
finopsagent → local-store → aggregator → frontend
   수집           저장          집계/API         웹 화면
```

구성별 최소 Pod 수:

| 사용 목적 | 필요한 Pod | 상시 Pod 수 |
|---|---|---:|
| Kubecost 웹 UI로 비용 조회 | 네 구성요소 모두 | 4 |
| 웹 UI 없이 API만 사용 | `frontend` 제외 | 3 |
| 외부 federated object storage 사용 | `local-store`를 외부 저장소로 대체 | 구성에 따라 3 |

주의:

- 기존 Prometheus는 `finopsagent`, `local-store`, `aggregator`를 대체하지 않는다.
- `local-store`는 외부 federated object storage를 정확히 구성한 경우에만 비활성화한다.
- `frontend`를 끄려면 values에 `frontend.enabled: false`를 지정한다.
- `helm test`를 실행하면 `basic-health` 테스트 Pod 1개가 일시적으로 생성될 수 있다. 상시 Pod 수에는 포함하지 않는다.
- 현재 비활성화한 `networkCosts`를 켜면 DaemonSet이 생성되어 node마다 Pod 1개가 추가된다.
- `ServiceMonitor`는 Prometheus 설정 리소스이므로 Pod나 컨테이너를 추가하지 않는다.

---

## 2. 변경 관리 원칙

Kubecost는 **ArgoCD를 통해서만 배포한다**. `helm upgrade --install`이나 `kubectl apply`로 운영 리소스를 직접 생성하지 않는다.

이 서버의 배포 경로:

```text
food-budget-app Ansible
  ├─ cost namespace 생성
  └─ platform AppProject에 Helm repo·namespace 허용
                    │
                    ▼
happyInit/mealplanning-config
  └─ platform/argocd/kubecost.yaml
                    │
                    ▼
platform-root Application
                    │
                    ▼
kubecost child Application
                    │
                    ▼
Kubecost Helm chart → cost namespace
```

정본 분리:

| 대상 | 정본 |
|---|---|
| `cost` namespace | Kubecost Application의 `managedNamespaceMetadata` |
| `platform` AppProject 허용 목록 | 이 저장소의 `k8s_argocd` role |
| Kubecost Chart 버전·values | `happyInit/mealplanning-config`의 `platform/argocd/kubecost.yaml` 단일 파일 |
| 렌더링된 Kubernetes workload | ArgoCD가 생성·관리 |

Kubecost는 단일 YAML 설치 원칙에 따라 `CreateNamespace=true`를 사용한다. PSS label은 같은 Application의 `managedNamespaceMetadata`로 관리해 namespace 생성과 정책 소유권을 분리하지 않는다.

---

## 3. 설치 전 리스크와 용량

Kubecost 3.2.0 기본값은 소규모 실습용치고 가볍지 않다.

| 항목 | Chart 기본값 | 이 서버에서의 판단 |
|---|---:|---|
| Aggregator DB PVC | `128Gi` | A1 실제 여유를 반영해 `64Gi`로 시작 |
| Local Store PVC | `32Gi` | 유지 |
| Aggregator 설정 PVC | `1Gi` | 유지 |
| Cloud Cost 설정 PVC | `1Gi` | Cloud Cost를 끄면 생성하지 않음 |
| Aggregator memory request | `3Gi` | 설치 전 allocatable 여유 확인 필수 |
| Network Costs | 기본 활성 | 첫 설치는 비활성 권장 |
| Cloud Cost | 기본 활성 | 온프레미스 검증 단계에서는 비활성 |
| Forecasting | 기본 활성 | 첫 설치는 비활성 권장 |
| Cluster Controller | 기본 활성 | 자동 변경 방지를 위해 첫 설치는 비활성 |

> Aggregator DB는 block storage가 필요하다. 이 서버의 `openebs-lvm`은 LVM LocalPV block storage이므로 적합하다. NFS로 바꾸지 않는다.

### 설치 전 자원 확인

```bash
kubectl get nodes -o wide
kubectl top nodes
kubectl get storageclass
kubectl get pvc,pv -A
kubectl get lvmnode -n openebs -o yaml
```

노드별 예약 가능 자원 확인:

```bash
kubectl describe nodes \
  | sed -n '/Name:/p;/Allocated resources:/,/Events:/p'
```

OpenEBS VG 여유는 각 worker에서 확인한다.

```bash
sudo vgs openebs-vg
sudo lvs
```

설치 진행 조건:

- [ ] 모든 노드가 `Ready`
- [ ] `openebs-lvm` StorageClass 존재
- [ ] `openebs-lvm`의 `volumeBindingMode`가 `WaitForFirstConsumer`
- [ ] 단일 worker에 Aggregator용 메모리 3Gi 이상 예약 가능
- [ ] A1(`192.168.0.20`) OpenEBS VG에 Aggregator용 65Gi + 운영 여유가 있음
- [ ] B2 OpenEBS VG에 Local Store용 32Gi + 운영 여유가 있음
- [ ] 클러스터 전체 OpenEBS VG에 Kubecost PVC용 97Gi + 운영 여유가 있음
- [ ] Prometheus Operator와 ServiceMonitor CRD가 정상

```bash
kubectl get storageclass openebs-lvm -o yaml
kubectl get crd servicemonitors.monitoring.coreos.com
kubectl get prometheus -n observability
```

### ArgoCD 배포 전제

Kubecost child Application을 추가하기 전에 이 저장소에서 AppProject 울타리를 먼저 연다.

`infra/ansible/roles/k8s_argocd/defaults/main.yml`에서:
   - `argocd_platform_source_repos`에 `https://kubecost.github.io/kubecost/` 추가
   - `argocd_platform_namespaces`에 `cost` 추가

Application이 생성할 namespace의 목표 상태:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: cost
  labels:
    pod-security.kubernetes.io/enforce: baseline
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
```

Ansible 반영:

```bash
cd infra/ansible
ansible-playbook k8s.yml --tags argocd --check --diff
ansible-playbook k8s.yml --tags argocd
```

전제 확인:

```bash
kubectl -n argocd get appproject platform -o yaml
kubectl -n argocd get application platform-root
kubectl -n argocd get secret repo-food-budget-config
```

통과 조건:

- [ ] `platform` AppProject의 `sourceRepos`에 Kubecost Chart repo가 있음
- [ ] `platform` AppProject의 `destinations`에 `cost` namespace가 있음
- [ ] `platform-root`가 `Synced`, `Healthy`
- [ ] `happyInit/mealplanning-config` repository 연결 상태가 정상

---

## 4. 현재 상태 백업

재실행 전에 기존 설치 여부부터 확인한다.

```bash
kubectl -n argocd get application kubecost 2>/dev/null || true
kubectl get namespace cost 2>/dev/null || true
kubectl get all,pvc,servicemonitor -n cost 2>/dev/null || true
```

기존 Application이 있으면 ArgoCD 상태, 렌더 결과와 PVC 상태를 보관한다.

```bash
mkdir -p /tmp/kubecost-backup
argocd app get kubecost -o yaml \
  > /tmp/kubecost-backup/application.yaml
argocd app manifests kubecost \
  > /tmp/kubecost-backup/manifest.yaml
kubectl get pvc -n cost -o yaml \
  > /tmp/kubecost-backup/pvc.yaml
```

values와 Application의 진짜 이력은 config 저장소 Git 커밋이다. 기존 PVC를 확인하기 전에는 Application, PVC 또는 namespace를 삭제하지 않는다.

---

## 5. Chart 버전 확인

```bash
helm repo add kubecost https://kubecost.github.io/kubecost/
helm repo update kubecost
helm search repo kubecost/kubecost --versions | head -20
helm show chart kubecost/kubecost --version 3.2.0
```

Chart 기본값을 로컬에서 확인한다.

```bash
helm show values kubecost/kubecost --version 3.2.0 \
  > /tmp/kubecost-3.2.0-default-values.yaml
```

버전 정책:

- 최초 설치는 이 문서에서 검증한 `3.2.0`으로 고정한다.
- `latest`를 사용하지 않는다.
- 버전 변경 시 `helm diff upgrade` 또는 `helm template` 결과를 먼저 검토한다.
- 3.x major 변경 승인 플래그의 필요 여부는 Chart와 라이선스 조건을 설치 직전에 다시 확인한다.

---

## 6. 이 서버용 values

다음 values는 config 저장소 `happyInit/mealplanning-config`의 `platform/argocd/kubecost.yaml`에서 `spec.source.helm.valuesObject` 아래에 인라인으로 둔다. 이 Application 파일 하나가 운영 정본이다.

```yaml
global:
  clusterId: mealplanning-k8s
  defaultStorageClass: openebs-lvm

# 첫 설치에서는 자동 최적화/중단 기능을 열지 않는다.
clusterController:
  enabled: false

# 온프레미스 리소스 배분 검증 단계에서는 클라우드 청구 연동을 사용하지 않는다.
cloudCost:
  enabled: false

# 먼저 기본 비용 배분을 안정화한 뒤 필요할 때 켠다.
forecasting:
  enabled: false

# Cilium/Istio 환경에서 네트워크 비용 DaemonSet은 별도 검증 후 활성화한다.
networkCosts:
  enabled: false
  serviceMonitor:
    enabled: false

localStore:
  enabled: true
  nodeSelector:
    kubernetes.io/hostname: k8s-worker-b2
  resources:
    requests:
      cpu: 50m
      memory: 256Mi
    limits:
      memory: 1Gi
  persistentVolume:
    enabled: true
    storageClass: openebs-lvm
    size: 32Gi

aggregator:
  enabled: true
  # 192.168.0.20 = k8s-worker-a1.
  nodeSelector:
    kubernetes.io/hostname: k8s-worker-a1
  # A1의 실제 VG 여유 약 89Gi를 고려한 시작값이다.
  # openebs-lvm은 allowVolumeExpansion=true이므로 사용량을 보고 늘린다.
  retention1d: 30
  retention1h: 14
  retention10m: 7
  persistentConfigsStorage:
    storageClass: openebs-lvm
    storageRequest: 1Gi
  aggregatorDbStorage:
    storageClass: openebs-lvm
    storageRequest: 64Gi
  resources:
    requests:
      cpu: 100m
      memory: 3Gi
  serviceMonitor:
    enabled: true
    interval: 1m
    scrapeTimeout: 10s

finopsagent:
  enabled: true
  # A1의 Aggregator 3Gi 예약 공간을 침범하지 않도록 B2에 고정한다.
  nodeSelector:
    kubernetes.io/hostname: k8s-worker-b2
  # 기존 kube-prometheus-stack → 기존 Grafana 경로에 Kubecost 메트릭을 편입한다.
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
      namespace: observability
      interval: 1m
      scrapeTimeout: 10s
      # kube-prometheus-stack의 kube-state-metrics와 중복되는 KSMv1 복사본은
      # 외부 Prometheus 수집 단계에서만 버린다. FinOps Agent 내부 비용 계산에는 영향 없다.
      metricRelabelings:
        - action: drop
          sourceLabels: [__name__]
          regex: "kube_.*"
  agent:
    collectorDataSource:
      enabled: true
      scrapeInterval: 60s

frontend:
  enabled: true
  nodeSelector:
    kubernetes.io/hostname: k8s-worker-a1

telemetry:
  enabled: false
```

### 왜 이 값인가

- `openebs-lvm`: 이 프로젝트에서 확정한 온프레미스 StorageClass다.
- `64Gi`: A1의 실측 VG 여유 약 89Gi에서 설정 PVC 1Gi와 운영 여유를 남기는 초기값이다. 기본값은 128Gi이며, 사용량을 관찰해 PVC를 늘린다.
- 보존 기간 `30/14/7일`: 작은 온프레미스 클러스터의 초기 기준이다. 실제 증가율을 본 뒤 조정한다.
- `cloudCost: false`: 현재는 AWS CUR/Cost Explorer가 아니라 온프레미스 내부 단가 단계다.
- `clusterController: false`: Kubecost가 workload 크기나 namespace 상태를 자동 변경하지 못하게 한다.
- `networkCosts: false`: Cilium, Istio sidecar, PSS와의 동작을 별도 검증하기 전까지 host 접근 DaemonSet을 추가하지 않는다.
- `aggregator.serviceMonitor.enabled: true`: 기존 Prometheus에 Kubecost Aggregator 운영 메트릭을 편입한다.
- `finopsagent.metrics.serviceMonitor.enabled: true`: 비용·allocation 메트릭을 기존 Prometheus와 Grafana에서 조회할 수 있게 한다.
- FinOps Agent의 `kube_*` 메트릭 drop: 기존 kube-state-metrics와의 중복 시계열만 외부 Prometheus에서 제거한다.
- `telemetry: false`: 외부 익명 텔레메트리 전송을 기본 차단한다.

### 렌더링 검증

```bash
argocd app manifests kubecost > /tmp/kubecost-rendered.yaml
```

확인:

```bash
grep -n 'storageClassName: openebs-lvm' /tmp/kubecost-rendered.yaml
grep -n 'kind: ServiceMonitor' /tmp/kubecost-rendered.yaml
grep -n 'kind: PersistentVolumeClaim' /tmp/kubecost-rendered.yaml
```

서버 측 검증:

```bash
kubectl apply --dry-run=server -f /tmp/kubecost-rendered.yaml
```

---

## 7. 설치

이 저장소 루트에 준비한 `kubecost.yaml`을 config 저장소의 `platform/argocd/kubecost.yaml`로 추가한다. values는 Application에 인라인되어 있어 별도 values 파일이 필요 없다.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kubecost
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: platform
  source:
    repoURL: https://kubecost.github.io/kubecost/
    chart: kubecost
    targetRevision: 3.2.0
    helm:
      releaseName: kubecost
      valuesObject:
        # 전체 값은 저장소 루트 kubecost.yaml 참조
        global:
          clusterId: mealplanning-k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: cost
  syncPolicy:
    automated:
      prune: false
      selfHeal: true
    managedNamespaceMetadata:
      labels:
        pod-security.kubernetes.io/enforce: baseline
        pod-security.kubernetes.io/warn: restricted
        pod-security.kubernetes.io/audit: restricted
    retry:
      limit: 5
      backoff:
        duration: 20s
        factor: 2
        maxDuration: 5m
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

정책 설명:

- `platform-root`가 `platform/argocd/*.yaml`을 자동 발견한다.
- Chart와 values를 단일 Application의 `valuesObject`로 관리한다.
- Chart 버전은 `targetRevision: 3.2.0`으로 고정한다.
- `CreateNamespace=true`와 `managedNamespaceMetadata`가 namespace와 PSS label을 함께 만든다.
- `prune: false`로 둬 Git 파일 삭제가 즉시 Kubecost workload/PVC 삭제로 번지지 않게 한다.
- `selfHeal: true`로 클러스터 수동 변경을 Git 상태로 되돌린다.

배포 순서:

```bash
# mealplanning-config 저장소에서 수행
git checkout -b feat/platform-kubecost
git add platform/argocd/kubecost.yaml
git commit -m "feat(platform): deploy kubecost via ArgoCD"
git push origin feat/platform-kubecost
```

1. config 저장소에 PR을 만들고 리뷰한다.
2. PR을 `main`에 merge한다.
3. GitHub webhook 또는 ArgoCD 주기 refresh로 `platform-root`가 child Application을 생성한다.
4. `kubecost` Application이 자동 sync한다.

관찰:

```bash
kubectl -n argocd get application platform-root kubecost -w
kubectl -n cost get pods,pvc -w
```

강제 수동 sync가 필요한 경우에만:

```bash
argocd app sync kubecost
argocd app wait kubecost --health --sync --timeout 1200
```

> 설치를 서두르기 위해 `helm upgrade --install`을 병행하지 않는다. ArgoCD와 Helm CLI가 같은 Kubernetes 리소스를 동시에 관리하면 소유권과 롤백 기준이 갈라진다.

---

## 8. 설치 검증

### 8.1 ArgoCD와 workload

```bash
kubectl -n argocd get application kubecost
argocd app get kubecost
kubectl get pods -n cost -o wide
kubectl get deploy,statefulset,daemonset -n cost
kubectl get events -n cost --sort-by=.lastTimestamp | tail -50
```

통과 조건:

- [ ] ArgoCD Application이 `Synced`, `Healthy`
- [ ] 모든 필수 Pod가 `Running` 및 Ready
- [ ] `Pending`, `CrashLoopBackOff`, `ImagePullBackOff` 없음
- [ ] 비활성화한 Cloud Cost, Forecasting, Network Costs가 생성되지 않음

### 8.2 PVC와 노드 고정

```bash
kubectl get pvc,pv -n cost -o wide
kubectl describe pvc -n cost
```

통과 조건:

- [ ] 모든 PVC가 `Bound`
- [ ] StorageClass가 모두 `openebs-lvm`
- [ ] Aggregator의 두 PVC가 같은 zone/node 제약 안에서 바인딩
- [ ] OpenEBS VG 여유 공간이 운영 안전 범위 내에 남음

LocalPV 특성:

- 데이터는 PV가 생성된 node의 LVM VG에 있다.
- 해당 node 장애 시 다른 node에 단순 재스케줄해 바로 붙는 공유 스토리지가 아니다.
- Kubecost는 핵심 서비스 데이터가 아니라 관측/비용 데이터이므로 이 제약을 수용한다.
- 장기 보존이 필요해지면 federated object storage와 백업 정책을 별도로 설계한다.

### 8.3 서비스와 endpoint

```bash
kubectl get service,endpoints,endpointslice -n cost
kubectl get servicemonitor -n cost -o yaml
kubectl get servicemonitor -n observability \
  kubecost-finopsagent -o yaml
```

ServiceMonitor가 실제 Service의 label과 port name을 선택하는지 확인한다.

정상 렌더 결과는 ServiceMonitor 3개다.

| ServiceMonitor | namespace | 용도 |
|---|---|---|
| `kubecost-finopsagent` | `observability` | 비용·allocation 메트릭 |
| `kubecost-aggregator` | `cost` | Aggregator 상태 |
| `kubecost-aggregator-clickhouse` | `cost` | 내장 DB 상태 |

---

## 9. Prometheus 연동 검증

현재 저장소의 `kube-prometheus-stack`은 아래 설정을 사용한다.

```yaml
prometheus:
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false
    podMonitorSelectorNilUsesHelmValues: false
```

따라서 `cost` namespace의 ServiceMonitor도 별도 `release` label 없이 선택할 수 있다.

### 9.1 Prometheus가 ServiceMonitor를 선택했는지 확인

```bash
kubectl get prometheus -n observability -o yaml \
  | sed -n '/serviceMonitorSelector:/,/podMonitorSelector:/p'

kubectl get servicemonitor -A | grep -i kubecost
```

Prometheus UI를 임시 포워딩한다.

```bash
PROM_SVC="$(kubectl get svc -n observability \
  -l app.kubernetes.io/name=prometheus \
  -o jsonpath='{.items[0].metadata.name}')"

kubectl port-forward -n observability \
  "service/${PROM_SVC}" 9090:9090
```

브라우저:

```text
http://127.0.0.1:9090/targets
```

통과 조건:

- [ ] Kubecost Aggregator target이 보임
- [ ] 상태가 `UP`
- [ ] 마지막 scrape 오류가 없음

PromQL:

```promql
up{namespace="cost"}
```

메트릭 이름 탐색:

```promql
count by (__name__) ({namespace="cost"})
```

> Kubecost 3.x의 비용 UI 데이터가 보이는지와 Prometheus의 Kubecost target이 `UP`인지는 서로 다른 검증이다. 전자는 FinOps Agent/Local Store/Aggregator 경로, 후자는 운영 메트릭 scrape 경로다.

### 9.2 기존 Grafana에서 확인

추가 Grafana를 설치하지 않는다. 기존 `https://grafana.mealbong.cloud/`의 Prometheus datasource가 같은 in-cluster Prometheus를 가리키므로 ServiceMonitor target이 `UP`이 되면 Grafana Explore에서 바로 조회할 수 있다.

Grafana → Explore → Prometheus에서 순서대로 확인한다.

```promql
up{namespace="cost"}
```

```promql
count(node_total_hourly_cost)
```

```promql
count(container_cpu_allocation)
```

```promql
count(container_memory_allocation_bytes)
```

```promql
count(pv_hourly_cost)
```

통과 조건:

- [ ] Kubecost 관련 target이 모두 `UP`
- [ ] `node_total_hourly_cost`가 1개 이상
- [ ] CPU·memory allocation 시계열이 1개 이상
- [ ] 기존 kube-state-metrics의 `kube_*` 시계열 개수가 갑자기 두 배가 되지 않음

비용 배분의 정본 화면은 Kubecost UI다. 기존 Grafana는 Kubecost 메트릭과 상태를 통합 관찰하는 용도로 사용한다.

### 9.3 Prometheus target이 없을 때

```bash
kubectl describe servicemonitor -n cost
kubectl get svc -n cost --show-labels
kubectl get endpointslice -n cost
kubectl logs -n observability \
  statefulset/prometheus-kube-prometheus-stack-prometheus \
  --since=15m 2>/dev/null || true
```

확인 순서:

1. ServiceMonitor selector와 Service label이 일치하는가?
2. ServiceMonitor endpoint의 `port`가 Service의 port **name**과 일치하는가?
3. Prometheus의 namespace selector가 `cost`를 포함하는가?
4. NetworkPolicy가 `observability` → `kubecost`를 차단하는가?
5. Istio sidecar/mTLS가 scrape 요청을 막는가?

ConfigMap에 임의의 `scrape_configs`를 추가하지 않는다. Operator가 생성한 Prometheus 설정은 수동 수정 대상이 아니다.

---

## 10. Kubecost UI 확인

기본 확인은 외부 노출 없이 포트 포워딩으로 한다.

```bash
kubectl get svc -n cost
kubectl port-forward -n cost \
  service/kubecost-frontend 9090:9090
```

브라우저:

```text
http://127.0.0.1:9090
```

UI 통과 조건:

- [ ] Cluster ID가 `mealplanning-k8s`
- [ ] `app`, `data`, `pipeline`, `observability` namespace가 표시됨
- [ ] CPU와 RAM allocation이 0이 아님
- [ ] 15~30분 뒤 namespace/workload별 비용 데이터가 생성됨
- [ ] currency와 custom price의 의미를 팀이 이해하고 있음

외부 공개가 필요하면 개별 `LoadBalancer` Service를 만들지 않는다. 이 프로젝트 규칙상 `type: LoadBalancer`는 Gateway 전용이다. 내부 Istio Gateway에 `HTTPRoute`와 TLS를 추가해 노출한다.

---

## 11. 온프레미스 단가 설정

AWS 청구 연동 전에는 Kubecost 기본값을 “실제 서버 청구액”으로 오해하면 안 된다.

먼저 아래 비용을 월 단가로 합의한다.

| 비용 항목 | 산정 예 |
|---|---|
| CPU | 서버 구매비 감가상각 × CPU 비율 |
| RAM | 서버 구매비 감가상각 × RAM 비율 |
| Storage | SSD 구매비 감가상각 + 백업 비용 |
| 전력 | 평균 소비전력 × 시간 × kWh 단가 |
| 네트워크 | 내부망은 0 또는 고정비, 인터넷 egress만 별도 |

그 뒤 Chart의 `finopsagent.agent.kubecost.customPrices`를 사용한다.

```yaml
finopsagent:
  agent:
    kubecost:
      customPrices:
        enabled: true
        CPU: "<시간당 vCPU 단가>"
        RAM: "<GiB당 시간 단가>"
        storage: "<GiB당 시간 단가>"
        internetNetworkEgress: "<GiB당 단가>"
        regionNetworkEgress: "0"
        zoneNetworkEgress: "0"
```

값은 예시 숫자로 임의 입력하지 않는다. 회계 기준과 전기요금 기준일을 문서에 남긴 뒤 반영한다.

---

## 12. 장애 처리

### ArgoCD Sync 실패 또는 timeout

```bash
argocd app get kubecost
argocd app diff kubecost
kubectl get pods,pvc -n cost -o wide
kubectl get events -n cost --sort-by=.lastTimestamp | tail -80
```

주요 원인:

- Aggregator 3Gi memory request를 만족하는 node 없음
- `openebs-lvm` VG 용량 부족
- PVC가 같은 배치 영역에 잡히지 않음
- 이미지 registry `icr.io` 접근 실패
- PSS 또는 admission policy 거부

### PVC가 Pending

```bash
kubectl describe pvc -n cost
kubectl get storageclass openebs-lvm -o yaml
kubectl get pods -n openebs -o wide
```

StorageClass를 default로 patch하지 않는다. Kubecost values에 `openebs-lvm`을 명시하는 방식이 다른 PVC에 영향을 주지 않아 안전하다.

### Aggregator가 OOMKilled

```bash
kubectl get pod -n cost -o custom-columns=\
'NAME:.metadata.name,RESTARTS:.status.containerStatuses[*].restartCount,REASON:.status.containerStatuses[*].lastState.terminated.reason'
kubectl top pods -n cost --containers
```

메모리 request를 무작정 낮추지 않는다. 실측 peak와 node allocatable을 확인하고 limit/request를 함께 조정한다.

### UI 비용 데이터가 비어 있음

```bash
kubectl logs -n cost -l app.kubernetes.io/name=kubecost-finops-agent \
  --since=30m --all-containers=true
kubectl logs -n cost -l app.kubernetes.io/name=kubecost-aggregator \
  --since=30m --all-containers=true
```

실제 label은 Chart 렌더 결과와 `kubectl get pods --show-labels`로 확인한다. 데이터는 설치 직후 즉시 완성되지 않으므로 15~30분 관찰한다.

---

## 13. 업그레이드와 롤백

업그레이드 전:

```bash
git -C <mealplanning-config-path> log --oneline -- \
  platform/argocd/kubecost.yaml
argocd app get kubecost
kubectl get pvc -n cost -o wide
```

새 Chart 버전으로 로컬 렌더링한다.

```bash
helm template kubecost kubecost/kubecost \
  --namespace cost \
  --version <새-버전> \
  --values /tmp/kubecost-values.yaml \
  > /tmp/kubecost-next.yaml
```

검증 후 `platform/argocd/kubecost.yaml`의 `targetRevision`을 PR로 변경한다. merge 뒤 ArgoCD 상태를 확인한다.

```bash
argocd app get kubecost
argocd app wait kubecost --health --sync --timeout 1200
```

롤백은 Helm CLI가 아니라 config 저장소에서 문제 커밋을 revert한다.

```bash
git -C <mealplanning-config-path> revert <문제-커밋>
git -C <mealplanning-config-path> push origin <브랜치>
```

revert PR을 merge하면 ArgoCD가 이전 버전을 렌더링한다.

> Git revert도 PVC 데이터 포맷 다운그레이드를 보장하지 않는다. major/minor 변경 전에 Kubecost release note와 DB migration 호환성을 확인하고, 데이터 포맷이 바뀐 업그레이드는 별도 복구 계획을 세운다.

---

## 14. 제거

제거는 명시적 승인 후에만 한다. `platform-root`는 `prune: false`이므로 Git 파일만 삭제해도 기존 child Application과 workload가 자동 삭제되지 않는다.

```bash
argocd app get kubecost
argocd app resources kubecost
kubectl get pvc,pv -n cost -o wide
```

제거 순서:

1. config 저장소에서 `platform/argocd/kubecost.yaml` 삭제 PR을 merge한다.
2. PVC 보존 여부를 결정하고 백업한다.
3. 사람이 child Application 삭제를 명시 실행한다.

```bash
kubectl get pvc,pv -n cost -o yaml \
  > /tmp/kubecost-pvc-before-delete.yaml
kubectl -n argocd delete application kubecost
```

Application의 resource finalizer 때문에 관리 workload가 삭제된다. Chart의 keep annotation이 적용된 PVC는 남을 수 있으므로 반드시 재확인한다.

```bash
kubectl get all,pvc -n cost
```

values 파일, namespace와 PVC 삭제는 데이터 복구 필요 여부를 확인한 다음 별도 수행한다. `kubectl delete namespace cost`로 한 번에 정리하지 않는다.

---

## 15. 최종 IaC 편입 체크리스트

- [ ] Application이 `cost` namespace와 PSS label을 생성
- [ ] `platform` AppProject에 Kubecost Chart repo와 namespace 허용
- [ ] config 저장소 `platform/argocd/kubecost.yaml` 단일 child Application 생성
- [ ] 직접 Helm 설치 없이 `platform-root`가 child를 인수
- [ ] Chart version `3.2.0` 고정
- [ ] `clusterId: mealplanning-k8s`
- [ ] 모든 PVC에 `openebs-lvm` 명시
- [ ] Aggregator 3Gi memory가 노드 예산에 반영
- [ ] Cloud Cost, Forecasting, Cluster Controller 기본 비활성
- [ ] Aggregator ServiceMonitor 활성
- [ ] Prometheus target `UP`
- [ ] Kubecost UI allocation 데이터 생성
- [ ] 외부 공개 시 내부 Gateway + HTTPRoute 사용
- [ ] NetworkPolicy 및 Istio mTLS 검증
- [ ] 온프레미스 단가 산식 별도 승인
- [ ] 백업·업그레이드·제거 절차 검증

---

## 16. 작업 결과 기록

```text
작업 일시:
작업자:
Kubecost chart version:
Kubecost app version:
mealplanning-config commit:
ArgoCD sync revision:
설치 namespace:
Aggregator 배치 node:
PVC / PV:
OpenEBS VG 설치 전 여유:
OpenEBS VG 설치 후 여유:
Prometheus target:
UI 최초 데이터 생성 시각:
적용한 custom price:
미해결 이슈:
롤백 기준:
```

---

## 참고

- 프로젝트 정본: `docs/design.md`
- K8s 이전 계획: `docs/mp_k8s_infra_migration_plan.md`
- K8s 인프라 상태: `docs/mp_k8s_infra_status.md`
- Prometheus 설치 코드: `infra/ansible/roles/k8s_observability/`
- OpenEBS 설치 코드: `infra/ansible/roles/k8s_storage/`
- ArgoCD AppProject·platform-root 코드: `infra/ansible/roles/k8s_argocd/`
- GitOps config 저장소: `happyInit/mealplanning-config`
- Kubecost 3.2.0 Helm values: `helm show values kubecost/kubecost --version 3.2.0`
- Kubecost 공식 Chart: <https://github.com/kubecost/cost-analyzer-helm-chart>
- kube-prometheus-stack 공식 Chart: <https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack>
