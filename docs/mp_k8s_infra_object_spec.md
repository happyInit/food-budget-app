# K8s 오브젝트 스펙 (deep-dive)

> **어떤 오브젝트를 · 왜 · 내부적으로 어떻게 동작하는가.** 결정의 근거는 [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md), 구축 현황은 [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md). 이 문서는 **그 결정을 오브젝트 수준으로 내리는 층**이다.
> 작성 2026-07-24 · 섹션별로 합의하며 누적한다. **§1~§13 완료.** · **2026-07-27 계획 검증 인터뷰 결정 반영**(ns 인벤토리 11 워크로드·PGSync 편입·LB 2 GW·readiness 의도 명시·kube-prometheus-stack·코드 변경 목록 정정 등 — 단계 번호는 재편된 P0~P4 기준, 플랜 §10)

## 0. 로드맵

| # | 섹션 | 상태 |
|---|---|---|
| 1 | Namespace 설계 | ✅ |
| 2 | 워크로드 (Deployment/StatefulSet/DaemonSet/Job) | ✅ |
| 3 | Probe 3종 | ✅ |
| 4 | Service · EndpointSlice | ✅ |
| 4.5 | DB 연결단 (Pooler) | ✅ |
| 5 | Gateway API | ✅ |
| 6 | 스토리지 (SC/PV/PVC) | ✅ |
| 7 | 설정·비밀 (ConfigMap/Secret/ExternalSecret) | ✅ |
| 8 | 오퍼레이터 CR | ✅ |
| 9 | 스케일·가용성 (HPA/KEDA/PDB) | ✅ |
| 10 | 보안 (NetworkPolicy/RBAC/SecurityContext) | ✅ |
| 11 | 메시 오브젝트 | ✅ |
| 12 | compose → K8s 전체 매핑표 | ✅ |
| 13 | 파드 설계 최적화 (멀티컨테이너 패턴·init·리소스) | ✅ |

---

## 1. Namespace 설계

### 1.1 네임스페이스는 "정리 폴더"가 아니다

흔한 오해가 조직도처럼 나누는 것인데, 네임스페이스가 실제로 하는 일은 **이름의 유효범위(scope)** 와 **정책이 붙는 지점**을 제공하는 것이다. 그 자체는 보안 경계가 아니다 — 격리는 NetworkPolicy·RBAC 이 하고, ns 는 그것들이 *붙는 자리*다.

**ns 단위로만 붙는 것**

| 붙는 것 | 의미 |
|---|---|
| `istio-injection=enabled` 라벨 | **사이드카 주입이 ns 단위** |
| NetworkPolicy | ns 안에서만 유효 |
| ResourceQuota / LimitRange | ns 총량·기본값 |
| Role / RoleBinding | ns 범위 권한 |
| 기본 ServiceAccount | ns 마다 자동 생성 |

→ **설계 기준은 "무엇을 함께 묶느냐"가 아니라 "어디에 서로 다른 정책을 붙일 것이냐"다.**

### 1.2 우리 ns — 메시 경계가 곧 ns 경계다

[`mp_k8s_infra_migration_plan.md §4.3`](./mp_k8s_infra_migration_plan.md)에서 정한 메시 경계(app 포함 / data 제외 / Job 제외)가 **정확히 네임스페이스 경계**다. 우연이 아니라, 주입 라벨이 ns 단위라서 그렇게 그어야 선언적으로 성립한다.

| ns | 담는 것 | 메시 주입 | 왜 갈렸나 |
|---|---|---|---|
| `app` | FastAPI 9 + frontend + **ranking-serving** = **11 워크로드** | **ON** | mTLS·L7 관측·카나리 대상. ranking-serving 은 mealplan 이 HTTP 로 부르는 소비자라 메시 안(§4.2 타임아웃 근거) |
| `data` | PG·ES·Kafka·Redis *(오퍼레이터가 생성)* + **PGSync·redis-pgsync**(우리 Deployment) | **OFF** | 오퍼레이터 가정 보존 + 비-HTTP 프로토콜. PGSync 는 상대(PG·ES·전용 Redis)가 전부 data 안이라 정책이 ns 내에서 닫힘 |
| `pipeline` | Kafka 컨슈머 4 + CronJob 11 + **ranking-retrain** | **OFF** | 아래 ⚠️ |
| `observability` | LGTM + MinIO | OFF | 리소스 격리 — 관측이 앱을 굶기면 안 된다 |
| `argocd` | ArgoCD | OFF | 클러스터 전역 쓰기 권한 → RBAC 격리 |
| `*-system` | istio · metallb · cnpg · elastic · strimzi · keda · external-secrets · cert-manager | OFF | 오퍼레이터별 관례 |

⚠️ **pipeline ns 를 통째로 OFF 하는 근거** — 주입은 ns 라벨이 기본이고 파드 어노테이션으로 개별 예외를 둘 수 있어서 "컨슈머 ON / Job OFF" 로 섞을 수도 있다. 그런데 **컨슈머가 말하는 상대가 Kafka(바이너리)와 PG(와이어 프로토콜)** 라 L7 이득이 0 이다. 얻는 것 없이 예외 규칙만 늘어나므로 **ns 전체 OFF 가 맞다.** (§4.2 "L7 을 어디서 쓰는가"의 회수 지점)

### 1.3 frontend 를 별도 ns 로 분리하지 않는다

**전제 변화부터** — `frontend/nginx.conf` 의 `/api/*` `proxy_pass` 블록 **13개**는 K8s 에서 **전부 HTTPRoute 로 대체된다.** 프론트엔드의 역할이 바뀐다:

| | compose | K8s |
|---|---|---|
| nginx 역할 | **게이트웨이** — 유일 노출 포트 + `/api/*` 리버스 프록시 | **정적 파일 서버만** |
| 라우팅 주체 | `nginx.conf` location 블록 | **HTTPRoute** (선언적·GitOps 대상) |
| 백엔드 호출 | nginx → 서비스명 DNS | **없음** — 프론트는 백엔드를 부르지 않는다 |

**결론: `app` ns 하나 + 파드 라벨(`tier=frontend|backend`) 로 구분한다.**

- 분리의 실익은 NetworkPolicy 를 다르게 붙이는 것인데, **NetworkPolicy 는 ns 가 아니라 파드 라벨로 선택**한다. `tier=frontend` 에 egress-deny 를 거는 것은 같은 ns 에서도 된다.
- 워크로드 11개(프론트 1 + 백엔드 9 + ranking-serving)에 ns 2개는 얇고, 크로스-ns FQDN·정책 중복 비용만 생긴다.
- **재검토 트리거**: 팀이 커져 tier 별 RBAC 을 갈라야 할 때, 또는 프론트를 별도 배포 주기로 뗄 때.

### 1.4 ns 에 붙일 정책 3종

**① PriorityClass — 노드 압박 시 죽는 순서**

```
data-critical (높음)  →  app-normal  →  pipeline-low (낮음)
```

kubelet 이 자원 부족으로 파드를 쫓아낼 때(eviction) 이 순서를 본다. **크롤러가 먼저 죽고 DB 가 마지막에 죽는** 구조를 선언으로 만드는 장치다. 디스크 폭주 때 전 게스트 iowait 74% 를 겪은 만큼(`docker-infra-status.md §7`), 한 놈이 폭주할 때 무엇을 지킬지 미리 정해둔다.

**② ResourceQuota — `pipeline` ns 에만**

크롤러·재학습이 폭주해도 앱 몫을 못 먹게 총량 상한을 건다. **`data` 에는 걸지 않는다** — DB 가 쿼터에 막혀 못 뜨는 쪽이 훨씬 나쁘다.

**③ LimitRange — `app` ns**

requests/limits 를 안 적은 파드에 기본값을 넣는다. 없으면 **BestEffort 클래스로 떠서 eviction 1순위**가 되는데, 이건 조용히 발생한다.

---

## 2. 워크로드 오브젝트

### 2.1 선택 기준은 하나 — "파드가 서로 구별되는가?"

| | 파드의 성격 | 관리 주체 |
|---|---|---|
| **Deployment** | **교체 가능(fungible)** — 이름·저장소·순서 무의미 | ReplicaSet |
| **StatefulSet** | **고유 신원** — 안정적 이름(`pg-0`) · 붙어 다니는 PVC · 순서 보장(0→1→2 생성, 역순 삭제) | 직접 |
| **DaemonSet** | 노드당 1개 | 직접 |
| **Job / CronJob** | **완료가 목적** (끝나야 성공) | 직접 |

### 2.2 우리 매핑 (코드베이스 조사로 확정)

| 워크로드 | 오브젝트 | 근거 |
|---|---|---|
| FastAPI 9 + frontend | **Deployment** | `read_only: true` · 로컬 쓰기 없음 확인. PG 풀은 *연결*이지 상태가 아니다 |
| Kafka 컨슈머 4 (retail-refiner · deal-notifier · recipe-refiner · user-event-sink) | **Deployment** + KEDA ScaledObject | lag 기반 0↔N |
| 폴러 8 | **CronJob** — `spec.timeZone: Asia/Seoul` | 현행 크론탭의 UTC 환산(vixie-cron `CRON_TZ` 미지원 우회)을 KST 로 복원 — 주석의 KST 의도가 정본이 된다 |
| deal-pruner · user-data-pruner · chat-insights | **CronJob 으로 전환** ✅합의 | 지금은 sleep 루프 상주 — 컨테이너 시절의 타협이었다 |
| ranking-serving / ranking-retrain | Deployment(`app` ns·메시 ON) / **CronJob**(`pipeline` ns) | 모델은 MinIO 경유(플랜 §5.5) → **볼륨 불필요** |
| **PGSync** | **Deployment replicas=1 고정** (`data` ns) | 논리 복제 슬롯 = 단일 소비자, 스케일 불가. `pg-rw` 직접(§4.5.3) · PriorityClass 는 app 급(서빙 인덱스 생산자) |
| **redis-pgsync** | Deployment 1 (비영속, `data` ns) | 앱 Redis(Sentinel)와 통합 금지 — AOF 사고 격리 교훈 |
| PG · ES · Kafka · Redis | **CR** (`Cluster` · `Elasticsearch` · `Kafka`) | 하위 워크로드는 **오퍼레이터가 만든다** — 우리가 쓰는 오브젝트가 아니다. ⚠️ **ES·Kafka 는 StatefulSet, PG(CNPG)는 Pod 를 직접 관리한다**(§8.5) |
| MinIO | **StatefulSet** — **replicas=1(SNSD)·호스트 B 고정** | 우리가 직접 만드는 **유일한** StatefulSet. "전 컴포넌트 HA"의 문서화된 예외(플랜 §5.4) |
| Cilium agent · node-exporter · Alloy | **DaemonSet** | 노드당 1개 |

> **앱 계층에 PVC 가 하나도 없다.** `ranking-model` 공유 볼륨을 MinIO 로 옮긴 플랜 §5.5 결정 덕에 앱·ML·파이프라인 전체가 볼륨 없이 돈다. "전 볼륨 RWO" 규율이 실제로는 "앱은 볼륨 자체가 없음"이 됐다.

### 2.3 내부동작 ① — Deployment 는 파드를 직접 만들지 않는다

```
Deployment ──manages──> ReplicaSet ──manages──> Pod
```

업데이트 시:

1. 새 spec 으로 **새 ReplicaSet 생성** (replicas=0)
2. `maxSurge` 만큼 새 RS 를 늘린다
3. 새 파드가 **Ready 가 되면** 구 RS 를 `maxUnavailable` 만큼 줄인다
4. 2~3 반복
5. 구 RS 는 replicas=0 으로 **남는다** → `kubectl rollout undo` 가 이것으로 동작 (`revisionHistoryLimit` 개까지 보관)

**3번의 "Ready" 판정이 전부다.** readinessProbe 가 없으면 컨테이너 프로세스가 뜨는 순간 Ready 로 간주되어, **아직 초기화 중인 파드로 트래픽이 들어간다.** 우리 앱은 startup 에서 `pool.open()`(PG 커넥션 풀)을 돌고 chat 은 gazetteer 를 인메모리 로드한다(compose 에서 `start_period: 30s`). → §3 으로 이어진다.

### 2.4 내부동작 ② — StatefulSet 을 직접 쓰지 않는 이유

StatefulSet 이 보장하는 것은 **신원과 저장소뿐**이다. PG 에 필요한 것은 페일오버·백업·PITR·재구성인데 **StatefulSet 은 그중 아무것도 하지 않는다.**

오퍼레이터는 CR 하나를 읽고 StatefulSet + Service(`-rw`/`-ro`) + Secret + PVC + 백업 스케줄을 **통째로 만들고, 계속 감시하며 목표 상태로 되돌린다**(reconcile 루프). primary 가 죽으면 standby 를 승격하고 `-rw` Service 의 대상을 바꾸는 것도 이 루프다.

> StatefulSet 을 직접 쓰면 **그 운영 지식을 우리가 다시 구현해야 한다.** 플랜 §5.2 에서 "스토리지 복제 대신 DB 자체 복제 + 오퍼레이터 페일오버"를 고른 결정이 여기서 회수된다.

### 2.5 내부동작 ③ — Job/CronJob 함정 3개

**① 사이드카가 Job 을 영원히 안 끝나게 한다** — Job 은 **모든 컨테이너가 종료**돼야 Complete 인데 Envoy 는 죽지 않는다. → `pipeline` ns 주입 OFF 로 **구조적으로** 해결한다(예외 규칙이 아니라 경계로).

**② `concurrencyPolicy: Forbid`** — 이전 실행이 안 끝났는데 다음 스케줄이 오면? **컬리 크롤은 Playwright 라 무겁고, 겹치면 크롤 예의에도 어긋난다.** (플랜의 "수집 = 고정 1 replica, 수평확장 금지"와 같은 취지)

**③ `startingDeadlineSeconds`** — 노드 다운으로 스케줄을 놓쳤을 때 언제까지 따라잡을지. 정하지 않으면 복구 직후 밀린 Job 이 한꺼번에 터진다. **매시 도는 `poller-price-matview`** 가 특히 해당된다.


---

## 3. Probe 3종

### 3.1 각각 다른 질문에 답한다

| Probe | 묻는 것 | 실패하면 |
|---|---|---|
| **liveness** | "이 프로세스를 죽이고 다시 띄워야 하나?" | **컨테이너 재시작** |
| **readiness** | "지금 트래픽을 받아도 되나?" | **EndpointSlice 에서 제거** (재시작 안 함) |
| **startup** | "아직 부팅 중인가?" | 성공할 때까지 **liveness·readiness 유예** |

**결정적 차이 — readiness 실패는 파드를 죽이지 않는다.** DB 가 잠깐 끊겼을 때 이걸 liveness 로 잡으면 전 파드가 재시작 루프에 빠져 **장애가 증폭된다.** readiness 로 잡으면 트래픽만 빠지고 복구 시 자동 복귀한다.

### 3.2 우리 코드는 이미 이 함정을 피해 놨다

```python
# services/chat/app/main.py
@app.get("/health")
async def health() -> dict:
    # 프로세스 liveness — degraded 여도 200(재시작 루프 방지). 의존성 준비 상태는 필드로 노출.
    return {"status": "ok" if state.get("ready") else "degraded"}
```

**의존성이 죽어도 200 을 반환한다.** 나머지 8개 서비스도 무조건 200 이다. → **`/health` 를 liveness·readiness 양쪽에 그대로 쓴다.**

- FastAPI lifespan 에서 `pool.open()` 이 끝나야 uvicorn 이 연결을 받으므로 **`/health` 200 = startup 완료**다. readiness 신호로 유효하다.
- chat 의 "degraded 200" 은 **의도된 서빙 가능 상태**다(template 생성기·rule 추출기·되묻기 폴백). EndpointSlice 에 남기는 것이 맞다.

🔴 **의도 명시 (2026-07-27 확정) — 우리 readiness 는 startup 게이트일 뿐, 런타임 의존성 상태를 반영하지 않는다.** §3.1 의 "DB 끊김을 readiness 로 잡는다"는 일반론 설명이고 우리 선택이 아니다. 근거: ① 우리 DB 는 **단일 공유 PG** — 의존성을 readiness 에 반영하면 PG 장애 시 전 파드가 동시에 EndpointSlice 에서 빠져 **부분 성능저하가 전면 503 으로 증폭**된다(뺄 곳이 없는데 빼는 것) ② DB 없이도 되는 엔드포인트(chat 폴백 등)까지 죽는다 ③ "떠 있지만 고장난" **개별 파드**는 readiness 가 아니라 메시의 outlier detection(§11.4)이 잡는다. 3층 분담: **readiness = startup** / **outlier detection = 런타임 개별 파드** / **앱 폴백·빠른 실패 = 의존성 전체 다운**.

### 3.3 compose → K8s 에서 바뀌는 것

compose 는 httpGet 이 없어 exec 로 우회했다:

```yaml
test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8001/health', timeout=3)"]
```

**매 체크마다 python 프로세스를 fork** 한다(9 서비스 × 30초). K8s 는 **kubelet 이 직접 HTTP 호출**하므로 프로세스 생성이 0 이다.

### 3.4 설정값 (compose 에서 유도)

| | startupProbe | readinessProbe | livenessProbe |
|---|---|---|---|
| 앱 8개 | `period 5s · failureThreshold 6` (=30초) | `period 10s · failureThreshold 3` | `period 30s · failureThreshold 3` |
| **chat** | `period 5s · failureThreshold 12` (=**60초**) | 〃 | 〃 |
| frontend | `/healthz` · `period 5s · threshold 4` | 〃 | 〃 |

chat 만 긴 이유는 **gazetteer 인메모리 로드**(compose `start_period: 30s`). startupProbe 가 없으면 초기화 시간 > liveness 임계값이 되어 **부팅 중에 죽고 영원히 못 뜨는 루프**에 빠진다.

> 과거엔 `initialDelaySeconds` 로 때웠는데, 그것은 "느린 시작 허용"과 "빠른 장애 감지"를 동시에 못 한다(delay 를 키우면 평시 감지도 느려짐). startupProbe 가 이 트레이드오프를 없앤다.

⚠️ **probe 는 kubelet 이 노드에서 파드 IP 로 직접 호출한다** — Service 를 거치지 않는다. default-deny NetworkPolicy 에서 **노드→파드 ingress 를 막으면 전 파드가 죽는다**(§10).

---

## 4. Service · EndpointSlice

### 4.1 Service 는 프록시가 아니라 선언이다

Service 를 만들면 실제로 생기는 것은 셋이다:

1. **ClusterIP** — 가상 IP. **어떤 네트워크 인터페이스에도 붙어 있지 않다.**
2. **DNS 레코드** — CoreDNS 가 `account.app.svc.cluster.local` → ClusterIP
3. **EndpointSlice** — selector 에 맞고 **Ready 인** 파드 IP 목록

**3번이 §3 과 연결된다.** readiness 실패 → EndpointSlice 에서 제거 → 트래픽이 안 간다. **무중단 롤링 업데이트의 실제 메커니즘**이 이것이다.

### 4.2 ClusterIP → 파드 IP 변환은 누가 하나

| | kube-proxy (iptables) | **Cilium eBPF (우리)** |
|---|---|---|
| 저장 | 노드마다 iptables DNAT 체인 | 커널 eBPF 해시맵 |
| 조회 | O(n) 순회 | O(1) |
| 시점 | 패킷이 나갈 때 | **소켓/tc 훅** |

kube-proxy 를 대체했으므로 **Service 는 순전히 선언이고 실제 변환은 커널 eBPF 맵**에서 일어난다.

**여기서 `socketLB.hostNamespaceOnly=true`(플랜 §3.1) 가 왜 필수인지 설명된다.** Cilium 의 socket-level LB 는 `connect()` **시점에** ClusterIP 를 파드 IP 로 바꾼다 — 패킷이 소켓을 떠나기도 전에. 그런데 **Istio 사이드카는 "목적지가 ClusterIP 인 트래픽"을 가로채도록 리다이렉트를 건다.** socket LB 가 먼저 주소를 바꿔버리면 **가로챌 ClusterIP 가 애초에 없다** → Envoy 를 안 거치고 → mTLS·L7 라우팅·라우트별 메트릭이 전부 조용히 사라진다. `hostNamespaceOnly=true` 는 socket LB 를 호스트 네임스페이스로만 제한해 파드 안에서는 ClusterIP 가 살아남게 한다.

### 4.3 우리가 만들 Service

| Service | 타입 | 비고 |
|---|---|---|
| 앱 9 + frontend + ranking-serving | ClusterIP | HTTPRoute 가 가리킴 (ranking-serving 은 mealplan 만 호출 — Route 없음) |
| Istio Gateway ×2 (공개 `.14` · 내부 `.15`) | **LoadBalancer** | **게이트웨이 전용, 상시 2개** (플랜 §3.3 EKS 이식 규칙 — 개별 서비스 노출 금지) |
| `pg-rw` · `pg-ro` · ES · Kafka bootstrap | ClusterIP | **오퍼레이터가 생성** |
| MinIO | **headless** (`clusterIP: None`) | 아래 |

**headless 가 필요한 이유** — ClusterIP 는 로드밸런싱을 하므로 **특정 파드를 지목할 수 없다.** Kafka 브로커·ES 노드·PG replica 는 개별 지목이 필수라, headless Service 가 파드마다 DNS 를 만든다(`kafka-0.kafka-headless.data.svc`). DNS 가 ClusterIP 대신 **파드 IP 를 직접** 돌려준다. **StatefulSet 의 안정적 신원이 소비되는 지점**이다.

### 4.4 ⚠️ Istio 함정 — 포트 이름

Istio 는 **포트 이름(또는 `appProtocol`)으로 프로토콜을 판별**한다. 이름이 없거나 `http` 로 시작하지 않으면 **TCP 로 취급** → L7 라우팅·라우트별 RED 메트릭이 안 나온다.

```yaml
ports:
  - name: http        # ← 이 한 줄이 없으면 플랜 §4.2 의 "라우트별 p99" 가 통째로 사라진다
    port: 8004
    appProtocol: http
```

메시 채택 명분의 절반이 L7 관측인데, 이 한 줄로 무력화된다.

---

## 4.5 DB 연결단 — CNPG Pooler (PgBouncer)

### 4.5.1 HPA 를 켜는 순간 커넥션 예산이 무너진다

**현행 커넥션 예산** (compose, 서비스당 1 replica)

| 서비스 | pool max | 소계 |
|---|---|---|
| account · pantry · mealplan · recipe | 10 | 40 |
| chat · price · notify · recipebook | 5 | 20 |
| **합계** | | **≈60 / `max_connections` 100** |

**커넥션 풀은 파드마다 생긴다.** replica 가 늘면 그대로 곱해진다:

```
전 서비스 HPA (min 2, max 4) 를 가정한 상한 시나리오:
  무거운 4개 × 4 replica × 10 = 160
  가벼운 4개 × 4 replica ×  5 =  80
  파이프라인 컨슈머 4 + CronJob 11 + PGSync + ranking = 30+
                                    ────────────────
                                    270+  vs  max_connections 100
```

*(캘리브레이션: 확정된 HPA 대상은 account 뿐(§9.3)이라 실제 초기 수치는 이보다 작다 — account ×4 + 나머지 ×2 기준 ~120+30 ≈ 150. 그래도 100 을 넘고, KEDA 컨슈머 burst·후속 HPA 확대를 생각하면 결론은 같다.)*

🔴 **즉 HPA 가 CPU 가 아니라 DB 커넥션에 먼저 막힌다.** account 의 bcrypt CPU 포화(100VU 에서 한도의 98%)를 풀려고 도입하는 것이 HPA 인데, 스케일아웃하는 순간 커넥션 벽에 부딪힌다 — **HPA 채택 명분 자체가 무효화된다.**

**`max_connections` 를 올리는 것은 답이 아니다.** PG 는 커넥션마다 **프로세스를 하나씩** 띄운다(~5–10MB). 300 커넥션이면 1.5–3GB 인데 PG 파드 한도가 2GB 다. 컨텍스트 스위칭 비용도 붙는다.

### 4.5.2 구성 — `Pooler` CRD, transaction 모드

CNPG 의 1급 오브젝트라 오퍼레이터가 관리한다(별도 스택이 아니다).

```
앱 파드(작은 풀 3~5) ──> Pooler(PgBouncer) ──다중화──> PG (실제 커넥션 20~30)
```

- `poolMode: transaction` — 트랜잭션이 끝나면 커넥션을 반납해 다중화 효과가 크다. (session 모드는 클라이언트 세션 내내 점유해 이득이 거의 없고, statement 모드는 트랜잭션을 깬다.)
- **Pooler 는 SPOF 가 되면 안 된다** — 모든 DB 트래픽이 지나므로 **replica 2 이상 + PDB** 필수. probe 는 CNPG 가 붙인다.
- **앱 풀을 줄인다** — `max_size` 10 → **3~5**. 앱 풀은 "bouncer 까지의 연결"이다. 안 줄이면 bouncer 앞단에서 같은 폭증이 재현된다.

### 4.5.3 🔴 우리 코드에 걸리는 함정 2개

**① psycopg3 prepared statement — 설정이 코드에 하나도 없다**

psycopg3 는 같은 쿼리가 반복되면 **자동으로 서버측 prepare** 를 건다. transaction 풀링에선 다음 실행이 **다른 백엔드로 갈 수 있어** `prepared statement "..." does not exist` 가 난다.

`services/*/app/db.py` 전체에 **`prepare_threshold` 설정이 한 곳도 없다** → 기본값 그대로 = 그대로 터진다.

- 해결 ①: `prepare_threshold=None` 으로 비활성 (간단, 약간의 성능 손실)
- 해결 ②: PgBouncer 1.21+ 의 prepared statement 지원 활성(`max_prepared_statements`)
- ⚠️ **P3 검증 항목** — 스모크만 돌리면 prepare 임계 전이라 **안 터지고 넘어간다.** 반드시 반복 부하로 확인할 것

**② PGSync 는 Pooler 를 우회한다**

PGSync 7.1.0 은 **LISTEN/NOTIFY** 로 변경을 감지하는데(`pgsync-adoption.md`), 세션에 묶인 기능이라 **transaction 풀링에서 동작하지 않는다.** → PGSync 는 `pg-rw` **직접 접속**, 앱만 Pooler 경유로 라우팅을 가른다.

> 그 밖의 transaction 모드 제약(advisory lock · 세션 `SET` · 임시 테이블)을 쓰는 코드가 있는지 P3 에서 함께 확인한다.

### 4.5.4 부수 기회 — `-ro` 활용 (별건)

CNPG 는 `pg-rw`(primary)·`pg-ro`(standby)를 나눠 준다. 읽기 쿼리를 standby 로 보내면 primary 부하가 크게 줄지만 **앱이 현재 읽기/쓰기를 나누지 않아 9개 서비스 코드 변경**이 따른다. 인프라는 **두 엔드포인트를 준비만** 해 두고, 전환은 별도 이슈로 뺀다.


---

## 5. Gateway API

### 5.1 Ingress 가 동결된 이유 — 역할 분리가 스펙에 없었다

Ingress 의 근본 문제는 **L7 기능이 스펙에 없어 전부 어노테이션으로 우회**했다는 것이다. 구현체마다 어노테이션이 달라 이식성이 0 이 되고, 무엇보다 **인프라 담당과 앱 담당이 같은 오브젝트를 편집**하게 된다.

Gateway API 는 그것을 **3계층으로 쪼개 스펙에 박았다:**

| 오브젝트 | 소유자 | 정하는 것 |
|---|---|---|
| **GatewayClass** | 인프라 제공자 | 어떤 구현체인가 (= `istio`) |
| **Gateway** | **클러스터 운영자** | 리스너·포트·TLS·어느 ns 의 Route 를 받을지 |
| **HTTPRoute** | **앱 개발자** | 경로 → 서비스 |

5인 팀 역할분담에 그대로 매핑된다 — 인프라 담당이 Gateway 를 소유하고 서비스 담당이 자기 HTTPRoute 를 GitOps 로 올린다. **"누가 무엇을 바꿀 수 있는가"가 RBAC 으로 강제된다.**

### 5.2 Gateway 가 실제로 만드는 것

```
Gateway 생성 → istiod 가 감지
            → Envoy Deployment + Service(type: LoadBalancer) 생성
            → MetalLB 가 그 Service 에 .14 할당
```

**이 체인이 플랜 §3.3 의 "`type: LoadBalancer` 는 게이트웨이 전용(상시 2개)" 규칙과 연결된다** — Gateway 하나가 곧 LoadBalancer Service 하나다. 그래서 게이트웨이 수 = LB 수 = EKS 이식 시 교체 대상 수이고, 이를 **서비스 수와 무관한 상수 2**로 묶는 것이 규칙의 실질이다. *(종전 "딱 1개" 문구는 바로 아래 `.15` 내부 GW 구성과 자기모순이라 2026-07-27 재정의 — 플랜 §3.3.)*

구성: `.14` 공개 Gateway(HTTPS 443 TLS 종단 + HTTP 80 리다이렉트) · `.15` 내부 Gateway(Grafana·ArgoCD·MinIO 콘솔).

### 5.3 nginx `/api/*` location 13개 → HTTPRoute

| nginx location | backendRef |
|---|---|
| `/api/recipes/book` · `/mine` · `/shared` | `recipebook:8006` |
| `/api/recipes` | `recipe:8001` |
| `/api/mealplan/assistant` | `chat:8003` |
| `/api/mealplan` · `/api/expenses` | `mealplan:8007` |
| `/api/notifications` | `notify:8008` |
| `/api/pantry/ocr` | `ocr:8010` |
| `/api/pantry` | `pantry:8005` |
| `/api/auth` · `/api/users` | `account:8004` |
| `/api/prices` | `price:8002` |
| `/` (SPA) | `frontend:80` |

⚠️ **매칭 의미가 다르다**

| | nginx `location /api/recipes` | Gateway API `PathPrefix: /api/recipes` |
|---|---|---|
| 방식 | **문자열** 프리픽스 | **경로 세그먼트** 단위 |
| `/api/recipes/123` | 매칭 ✅ | 매칭 ✅ |
| `/api/recipesXYZ` | **매칭됨** ⚠️ | **매칭 안 됨** |

Gateway API 가 **더 엄격**해 우리에겐 유리하지만, 세그먼트 경계를 넘는 경로를 쓰고 있었다면 404 가 된다 — **P2 검증 항목.**

우선순위는 문제없다. nginx 주석의 *"최장 프리픽스 우선이라 순서 무관"* 과 마찬가지로 **Gateway API 도 스펙에 우선순위가 정의**돼 있어(정확 매치 > 긴 prefix) `/api/recipes/book` 이 `/api/recipes` 보다 먼저 잡힌다.

### 5.4 🔴 `/internal/metrics/*` 9개는 통째로 사라진다

```nginx
location = /internal/metrics/recipe {
    allow 192.168.0.11; deny all; access_log off;
    set $u recipe:8001; proxy_pass http://$u/metrics;
}
```

**"서비스 포트를 호스트에 노출하지 않으면서 fb-monitoring 만 내부 `/metrics` 를 긁게 하려는" compose 시절의 우회**다. K8s 에서는:

- Prometheus 가 **클러스터 안**에 있어 **파드 IP:포트로 직접 스크레이프**한다
- 대상 발견은 **ServiceMonitor/PodMonitor** — kube-prometheus-stack(Prometheus Operator) 채택으로 확정(플랜 §9.0)
- IP allowlist(`allow 192.168.0.11`)는 **NetworkPolicy** 가 대신한다
- ⚠️ **P1 과도기**: 저장·룰 평가는 아직 `.11` — in-cluster **Prometheus agent** 가 파드를 긁어 `.11` 로 remote_write 한다(파드 CIDR 은 LAN 비라우팅이라 `.11` 이 직접 못 긁는다). P4 에 전체 이관.

→ **location 9개 + allowlist 규칙이 사라지고 ServiceMonitor 1~2개로 대체된다.** compose 시절의 우회가 K8s 에서 소멸하는 대표 사례.

### 5.5 nginx.conf 에 남는 것

| 사라지는 것 | 남는 것 |
|---|---|
| `/api/*` 프록시 **13개** → HTTPRoute | 정적 서빙 (`root` · `/assets/` 캐시 헤더) |
| `/internal/metrics/*` **9개** → ServiceMonitor | **SPA 폴백** `try_files $uri /index.html` |
| `resolver 127.0.0.11` (compose DNS) | `gzip` 설정 |
| 프록시 헤더(`X-Forwarded-*`) → Gateway 처리 | `/healthz` |

**SPA 폴백은 nginx 에 남는다** — Gateway 는 파일시스템을 모른다. HTTPRoute 는 `/` → frontend Service 까지만 보내고 그 안에서 nginx 가 `try_files` 를 계속한다.

### 5.6 🔴 놓치기 쉬운 것 — 업로드 크기 제한

```nginx
client_max_body_size 15m;   # 영수증 OCR 업로드 등 여유
```

**Envoy 는 기본 제한이 nginx 와 다르다.** 이 설정을 Gateway 로 옮기지 않으면 **영수증 OCR 업로드가 413 으로 죽는다.** nginx 가 게이트웨이 자리에서 빠지며 같이 사라지는 설정이라 **컷오버 체크리스트 항목**이다.

### 5.7 크로스-ns 참조 — ReferenceGrant

- Gateway 가 다른 ns 의 HTTPRoute 를 받으려면 → Gateway 의 `allowedRoutes`
- HTTPRoute 가 **다른 ns 의 Service** 를 `backendRef` 하려면 → **`ReferenceGrant` 필수**(기본 거부)

**우리는 HTTPRoute 와 Service 가 같은 `app` ns** 라 ReferenceGrant 가 필요 없다. §1.3 에서 frontend 를 별도 ns 로 나누지 않은 결정이 여기서도 비용을 아낀다.

### 5.8 카나리 — `backendRefs` weight

```yaml
backendRefs:
  - name: account
    port: 8004
    weight: 90
  - name: account-canary
    port: 8004
    weight: 10
```

플랜 §13 의 카나리 카드가 여기서 구현된다. 판정 신호(5xx율)는 Istio telemetry 가 제공한다.

### 5.9 타임아웃은 이식되고 재시도는 안 된다

- **타임아웃**: HTTPRoute 의 `timeouts` — **표준 필드**라 EKS 로 그대로 이식 *(단 §8.3 의 경고 그대로 — Gateway API 필드는 채널별 성숙도가 다르니 쓰는 버전에서 GA 여부를 확인하고 쓴다)*
- **재시도**: 아직 구현체 확장(Istio `VirtualService`) — **이식 시 재작성**

플랜 §4.2 의 "chat→pantry 타임아웃 · chat→account 재시도" 중 **재시도만 이식 비용이 있다.**


---

## 6. 스토리지 (StorageClass · PV · PVC)

### 6.1 세 오브젝트의 역할 분리

| | 답하는 질문 | 만드는 주체 |
|---|---|---|
| **StorageClass** | "어떤 **종류**의 저장소인가" — 프로비저너·파라미터·정책 | 클러스터 관리자 |
| **PVC** | "이만큼 **필요하다**" — 크기·접근모드·SC 이름 | 워크로드 |
| **PV** | 실제 저장소 조각 | **CSI 드라이버가 자동 생성**(동적 프로비저닝) |

**PVC 가 인터페이스이고 PV 가 구현이다.** 앱은 PV 를 몰라야 하고, 그래야 온프렘 LVM ↔ EBS 교체가 성립한다.

### 6.2 바인딩 생애주기 — `WaitForFirstConsumer` 가 왜 필수인가

```
PVC 생성 → [Pending]  ← WaitForFirstConsumer 면 여기서 멈춘다
   ↓
스케줄러가 "파드를 어느 노드에 놓을지" 결정
   ↓
CSI 드라이버가 그 노드에서 LV 생성 → PV 생성
   ↓
PVC ↔ PV 바인딩 → kubelet 마운트 → 파드 시작
```

`Immediate` 모드면 **PVC 생성 즉시 PV 를 만든다.** 그런데 로컬 볼륨은 **특정 노드에 묶인다.** 순서가 거꾸로 되어 스케줄러가 "이 PV 가 있는 노드"에만 파드를 놓을 수 있고, 최악의 경우 **PV 가 worker-a1 에 생겼는데 그 노드에 여유가 없어 파드가 영원히 Pending** 이다.

`WaitForFirstConsumer` 는 **스케줄링을 먼저 하고 저장소를 그 노드에 만든다.** EBS 도 AZ 에 묶이므로 같은 이유로 이 모드를 쓴다 → 플랜 §5.3 의 "동작 의미 일치" 주장이 여기서 증명된다.

### 6.3 RWO 가 스케줄링을 제약한다 — 그리고 그것이 §5.3 결정의 이유

RWO 는 **단일 노드**에서만 마운트된다. 즉 **PVC 를 쓰는 파드는 그 노드에 고정**된다. 노드가 죽으면 로컬 PV 도 그 노드에 있으므로 **다른 노드로 재스케줄이 불가능**하다(파드는 Pending 에 머문다).

**그래서 복제를 스토리지가 아니라 DB 에 맡긴 것이 필연이 된다:**

| 죽은 것 | 복구 주체 |
|---|---|
| worker 노드 | ❌ 스토리지는 못 따라간다 |
| PG primary | ✅ CNPG 가 B 의 standby 를 승격 |
| ES 노드 | ✅ replica 가 다른 노드에 |
| Kafka 브로커 | ✅ RF=3 |

플랜 §5.3 의 *"복제는 스토리지 레이어가 아니라 DB 자체 복제에 맡긴다"* 는 취향이 아니라 **RWO 로컬 PV 를 고른 순간의 논리적 귀결**이었다.

> **같은 제약이 Prometheus 에도 적용된다.** 메트릭은 Prometheus 로컬 PV 에 있으므로(플랜 §9.1) 노드가 죽으면 가시성을 잃는다. → **Prometheus 파드를 호스트 B 에 nodeAffinity 로 고정**해 *실측된 장애 모드*(호스트 A 급사)에서 관측이 생존하게 한다.

### 6.4 우리 PVC 목록 — 놀랍도록 적다

| 소비자 | PVC | 생성 주체 |
|---|---|---|
| PG (CNPG) | `volumeClaimTemplate` ×2 | 오퍼레이터 |
| ES (ECK) | ×3 | 오퍼레이터 |
| Kafka (Strimzi) | ×3 | 오퍼레이터 |
| MinIO | **×1** (단일 replica·호스트 B 고정 — 플랜 §5.4) | **우리**(StatefulSet) |
| **Prometheus** | ×1 (호스트 B 고정) | 우리 |
| **Loki · Tempo** | WAL 용 소형 ×2 (P4) | 우리 |
| **Redis · redis-pgsync** | **없음** | 비영속(플랜 §5.2) |
| **앱 11 · 파이프라인 · PGSync** | **없음** | 볼륨 자체가 없다 |

Loki·Tempo 는 청크·블록 저장이 **MinIO 백엔드**라 대용량 PVC 는 없지만, **수신 버퍼(WAL)용 소형 PVC 는 필요**하다 — 이건 캐시가 아니라서 유실되면 아직 안 올라간 로그·트레이스가 사라진다(관측 데이터라 수용 가능하되, "PVC 불필요"로 착각하지 말 것). Redis 에 PVC 가 없다는 것이 "영속성 끄기" 결정의 오브젝트 수준 표현이다.

### 6.5 `volumeClaimTemplate` — StatefulSet 만의 것

Deployment 에는 `volumeClaimTemplate` 이 **없다.** replica 들이 **같은 PVC 를 공유**하려 하는데 RWO 면 전부 같은 노드에 묶이거나 충돌한다.

StatefulSet 은 **파드마다 PVC 를 따로** 만든다(`data-pg-0`, `data-pg-1`). 그리고 **파드가 재생성돼도 같은 PVC 에 다시 붙는다** — ordinal 이 신원이기 때문이다. §2.1 의 "붙어 다니는 PVC" 가 이 메커니즘이다.

### 6.6 `reclaimPolicy` — 지우면 데이터가 사라지는가

| | PVC 삭제 시 |
|---|---|
| `Delete` | PV·실제 볼륨까지 **삭제** |
| `Retain` | PV·데이터 **남음**(수동 정리 필요) |

**StorageClass 를 두 개 만든다:**

| SC | reclaimPolicy | 대상 |
|---|---|---|
| `openebs-lvm`(기본) | `Delete` | MinIO · Prometheus 등 재생성 가능한 것 |
| **`openebs-lvm-retain`** | **`Retain`** | **PG · ES · Kafka** |

실수로 CR 을 지웠을 때 데이터가 즉사하지 않게 하는 마지막 방어선이다. Retain 은 재사용 시 수동 정리가 필요하지만 PVC 가 10개 남짓이라 비용이 작다.

### 6.7 볼륨 확장 — 늘리기만 되고 줄이기는 안 된다

`allowVolumeExpansion: true` → PVC 크기를 수정하면 CSI 가 LV 를 확장하고 파일시스템을 늘린다. **축소는 불가능**하다. → **작게 시작해 확장 가능하게 두는 것이 정석.** EBS gp3 도 확장만 되므로 여기서도 의미가 일치한다.

### 6.8 🔴 선행작업 — 노드에 LVM VG 가 미리 있어야 한다

OpenEBS LVM LocalPV 는 **노드에 VG 가 존재해야** 동작한다. 없으면 PVC 가 영원히 Pending 이다.

```
Terraform: 워커 VM 에 추가 디스크 부착
    ↓
Ansible:   pvcreate → vgcreate (예: vg-openebs)
    ↓
StorageClass: parameters.volgroup: "vg-openebs"
```

⚠️ **기존 `base` 롤의 `docker_data_disk` 포맷과 혼동 금지.** 워커 노드는 디스크가 **셋**이 될 수 있다 — OS · (선택) docker · **LVM VG 용(신규)**. 호스트 C 의 `/dev/sdb` 함정(`mp_k8s_infra_status.md §3`)과 같은 계열이므로 디바이스를 명시적으로 지정한다.

### 6.9 스냅샷은 백업이 아니다

`VolumeSnapshot` / `VolumeSnapshotClass` 로 스냅샷을 뜰 수 있지만 **로컬 스냅샷은 같은 노드·같은 디스크에 있다.** 노드가 죽으면 원본과 스냅샷이 함께 사라진다.

→ **스냅샷 = 빠른 롤백용**(마이그레이션 직전 등) · **백업 = S3**(플랜 §6.3). 둘을 혼동하면 플랜 §5.4 에서 MinIO/S3 를 실패 도메인으로 나눈 논리가 무너진다.

### 6.10 EKS 이식 — PVC 는 무수정이다

| | 온프렘 | EKS | 이식 |
|---|---|---|---|
| SC 이름 | `openebs-lvm` | `gp3` | **오버레이** |
| 프로비저너 | `local.csi.openebs.io` | `ebs.csi.aws.com` | **오버레이** |
| **PVC 매니페스트** | 동일 | 동일 | **무수정** |
| **volumeClaimTemplate** | 동일 | 동일 | **무수정** |
| 접근모드 RWO · WFC | 동일 | 동일 | 무수정 |

**바뀌는 것은 SC 정의뿐이고 PVC 는 한 글자도 안 바뀐다.** 플랜 §5.3 의 "SC 이름 하드코딩 금지" 규칙이 여기서 값을 한다.


---

## 7. 설정 · 비밀

### 7.1 ConfigMap vs Secret — 생각보다 차이가 작다

**Secret 은 base64 인코딩일 뿐 암호화가 아니다.** etcd at-rest 암호화를 따로 켜야 진짜 암호화가 된다. 실질적 차이는 셋뿐이다:

| | 의미 |
|---|---|
| **RBAC 을 따로 걸 수 있다** | "ConfigMap 은 읽되 Secret 은 못 읽는" 역할 분리 |
| **노드에 tmpfs 로 마운트** | 디스크에 남지 않음 |
| **로그·이벤트 노출이 적다** | `kubectl describe` 가 값을 뿜지 않음 |

→ **"Secret 에 넣었으니 안전하다"는 오해를 먼저 깨야 한다.** 실제 보호는 **ESO + RBAC + etcd 암호화**가 한다.

### 7.2 주입 방식과 갱신 전파 — 핵심 내부동작

| | `env` 주입 | `volume` 마운트 |
|---|---|---|
| 갱신 시 | **파드를 재시작해야 반영** | kubelet 이 주기적으로 파일 갱신(~1분) |
| 이유 | 프로세스 환경변수는 **시작 시 고정** | 파일이라 교체 가능 |
| 앱 요구사항 | 없음 | **파일 변경 감지 로직 필요** |

우리 앱은 `pydantic BaseSettings` 로 env 를 읽는다 — **시작 시 고정**이라 volume 마운트를 해도 못 읽는다. → **env 주입 + 롤아웃**이 맞다.

🔴 **고전적 함정 — ConfigMap 을 바꿔도 파드가 재시작되지 않는다.** Deployment spec 이 안 바뀌었기 때문이다. "설정 바꿨는데 반영이 안 된다"가 여기서 나온다.

해결은 **kustomize `configMapGenerator` 의 해시 접미사**다:

```
app-common-7f4d2c9   ← 내용이 바뀌면 이름이 바뀐다
      ↓
Deployment 의 configMapRef 이름도 바뀜 → spec 변경 → 자동 롤아웃
```

**GitOps 에서 ConfigMap 을 다루는 표준 방식**이고 ArgoCD 가 그대로 지원한다.

### 7.3 `.env` 43개 해체

현행은 **`.9` 에 `.env` 파일 하나**가 상주하며 전 서비스가 공유한다. K8s 에서는 성격별로 갈린다:

| 성격 | 개수 | 예 | 갈 곳 |
|---|---|---|---|
| **비밀** | **4+2** | `PGPASSWORD` · `JWT_SECRET` · `CHAT_GEMINI_API_KEY` · `GEMINI_API_KEY` + **신규 `ES_USER`·`ES_PASS`**(ECK 인증 — 플랜 §5.2) | **Secret ← ExternalSecret** (백엔드 = K8s provider, §6.4) |
| 인프라 좌표 | ~9 | `PGHOST` · `ESHOST` · `REDISHOST` · OTEL 엔드포인트 | ConfigMap — **IP → Service DNS** |
| 관측 설정 | ~12 | `OTEL_*` · `LOG_LEVEL` · `ENVIRONMENT` | ConfigMap(공통) |
| 기능 플래그 | ~13 | `CHAT_*_ENABLED` · `RANKING_ML_ENABLED` · `MONTHLY_CAP_ENABLED` | ConfigMap(**서비스별**) |
| 서비스 좌표 | 3 | `ACCOUNT_BASE_URL` · `PANTRY_BASE_URL` · `RANKING_SERVING_URL` | ConfigMap — Service DNS |
| **compose 전용 → 소멸** | **2** | `IMAGE_TAG` · `COMPOSE_PROFILES` | kustomize `images:` / 별도 ArgoCD Application |

**주목할 변화 — 인프라 좌표가 환경 무관해진다.** `PGHOST=192.168.0.8` 이 `pg-rw.data.svc` 로 바뀌는데 이 값은 **온프렘이든 EKS 든 동일**하다. 지금 `.env` 의 상당 부분이 "이 VM 의 IP"를 적어두는 용도였고 그것이 통째로 사라진다.

**ConfigMap 은 두 층으로 나눈다:**

| ConfigMap | 담는 것 | 왜 |
|---|---|---|
| `app-common` | OTEL · PG/ES 좌표 · ENVIRONMENT · LOG_LEVEL | 전 서비스 공유 |
| `chat-config` · `mealplan-config` … | 서비스별 기능 플래그 | **한 서비스 플래그를 바꿀 때 9개가 다 재시작되지 않게** |

하나로 합치고 `envFrom` 을 쓰면 키 하나 추가에 전 서비스가 롤아웃된다.

### 7.4 §4.5 와 이어지는 발견 — 풀 축소에 코드 수정이 필요한 서비스

§4.5 에서 "Pooler 도입 시 앱 풀을 10 → 3~5 로 줄인다"고 했는데 실제 코드는 **절반만 env 로 조정된다**:

| | 풀 설정 | ConfigMap 으로 조정 |
|---|---|---|
| chat · account · notify · price | `settings.pg_pool_max` | ✅ 가능 |
| **pantry · mealplan · recipe · recipebook** | **`max_size` 하드코딩**(10·10·10·5) | ❌ **코드 수정 필요** |

→ **P3 에 "4개 서비스의 풀 크기 env 화" 작업이 추가된다** *(종전 "3개"는 오류 — `services/recipebook/app/db.py` 도 `max_size=5` 하드코딩)*. 작은 변경이지만 안 하면 Pooler 를 붙여도 그 4개는 계속 하드코딩 값을 잡는다.

### 7.5 `JWT_SECRET` — 전 서비스가 같아야 한다

`.env.example` 주석: *"7개 동일해야 토큰 상호검증"*. K8s 에서는 **하나의 Secret 을 여러 Deployment 가 참조**하면 된다.

**가능한 이유는 전부 같은 `app` ns 에 있기 때문이다.** Secret 은 ns 를 넘지 못하므로 §1.3 에서 frontend 를 별도 ns 로 나누지 않은 결정이 여기서도 값을 한다 — 나눴으면 Secret 복제 메커니즘이 필요했다.

### 7.6 Gemini 키 2개는 분리를 유지한다

`CHAT_GEMINI_API_KEY` 와 `GEMINI_API_KEY`(ocr)는 **비용 귀속을 가르려고** 이미 분리돼 있다. Secret 도 2개로 유지한다 — 합치면 "챗이 쓴 돈"과 "OCR 이 쓴 돈"을 나눌 수 없다.

플랜 §6.1 의 FQDN egress 와 짝을 이룬다: **앱 층(키 분리 + 월 예산 캡 7,200원) + 네트워크 층(FQDN 제한)** 이중 방어.

### 7.7 ExternalSecret 이 실제로 하는 일

```
SecretStore        ← 백엔드 연결 정의 (온프렘 백엔드 / EKS = Secrets Manager)
    ↑ 참조
ExternalSecret     ← "어떤 키를 어떤 Secret 으로 만들지"
    ↓ ESO 컨트롤러가 refreshInterval 마다 동기화
Secret             ← 평범한 K8s Secret
    ↓
파드 (envFrom)     ← 앱은 ExternalSecret 을 모른다
```

**핵심은 앱이 ExternalSecret 을 모른다는 것이다.** 평범한 Secret 을 참조할 뿐이다. → **백엔드를 바꿔도 앱 매니페스트가 한 글자도 안 바뀐다.** 플랜 §8 에서 ESO 를 "백엔드 교체만으로 이식"이라 평가한 근거다.

⚠️ **회전 시 함정** — ESO 가 Secret 을 갱신해도 **env 주입이면 파드가 자동 재시작되지 않는다**(§7.2 재발). 우리 규모에선 회전이 잦지 않으므로 **수동 롤아웃으로 충분**하다고 명시한다(Reloader 같은 컨트롤러를 더 들이지 않는다).

### 7.8 imagePullSecret — Harbor, 그리고 EKS 에서 소멸

Harbor 는 프라이빗 레지스트리라 **모든 파드가 pull secret** 을 필요로 한다. 파드마다 적지 말고 **ServiceAccount 에 붙이면** 그 SA 를 쓰는 파드에 자동 적용된다 — ns 마다 `default` SA 에 다는 것이 실용적이다.

**EKS 전환 시 이 오브젝트는 사라진다** — ECR 은 IRSA 로 인증하므로 pull secret 자체가 불필요하다. 플랜 §8 "레지스트리 🟡" 의 실제 작업 내용이 이것이다.

### 7.9 함정 정리

| | 함정 |
|---|---|
| 🔴 | **Secret 은 base64 일 뿐** — 안전하다고 착각하지 말 것 (7.1) |
| 🔴 | **ConfigMap 을 바꿔도 파드가 재시작 안 됨** → configMapGenerator 해시 (7.2) |
| 🔴 | **하나의 ConfigMap + `envFrom`** → 키 하나에 전 서비스 롤아웃 (7.3) |
| 🔴 | **평문 Secret 을 Git 에 넣지 않는다** — ESO 채택의 이유 |
| ⚠️ | 4개 서비스 풀 크기가 하드코딩 → env 화 필요 (7.4) |


---

## 8. 오퍼레이터 CR

### 8.1 CRD + 컨트롤러 = 쿠버네티스의 확장 메커니즘

내장 오브젝트(Deployment·Service…)와 오퍼레이터의 CR 사이에 **구조적 차이가 없다.** 둘 다 같은 패턴이다:

```
API 스키마(타입)  +  컨트롤러(그 타입을 보고 일하는 루프)
```

Deployment 도 마찬가지다 — `Deployment` 타입이 있고 `deployment-controller` 가 ReplicaSet 을 만든다. **CRD 는 "타입을 추가하는 방법"이고 오퍼레이터는 "그 타입의 컨트롤러"다.**

그래서 **오퍼레이터 = 운영 지식을 컨트롤러로 코드화한 것**이라는 정의가 나온다. `Cluster` CR 에 `instances: 2` 라고 쓰면 "PG 를 2대 띄우고 하나를 primary 로 만들고 복제를 걸고 primary 가 죽으면 승격한다"는 **DBA 의 지식이 코드로 실행**된다.

### 8.2 reconcile 루프 — level-triggered 이지 event-driven 이 아니다

```
loop:
  desired ← CR 을 읽는다          (있어야 할 상태)
  actual  ← 실제 클러스터를 읽는다  (지금 상태)
  if desired ≠ actual: 차이를 메운다
```

**"이벤트가 왔을 때 반응"이 아니라 "주기적으로 차이를 확인"이다.** 그 결과:

- 오퍼레이터가 잠깐 죽었다 살아나도 **놓친 이벤트를 복구할 필요가 없다** — 다음 루프에서 현재 상태를 다시 본다
- 누가 `kubectl delete` 로 하위 리소스를 지워도 **다음 루프가 다시 만든다**
- 🔴 반대로 **손으로 고친 것이 조용히 되돌려진다** — 오퍼레이터를 처음 쓸 때 겪는 실무 함정이다

### 8.3 우리가 쓸 CR 목록 — 인프라의 상당 부분이 이미 CR 이다

| 오퍼레이터 | CR | 용도 |
|---|---|---|
| **CloudNativePG** | `Cluster` · **`Pooler`** · `ScheduledBackup` | PG + PgBouncer(§4.5) + 백업 |
| **ECK** | `Elasticsearch` | ES 3노드 |
| **Strimzi** | `Kafka` · **`KafkaTopic`** | Kafka + **토픽 생성의 유일 경로** |
| Redis operator | (CR) | primary+replica+Sentinel |
| **KEDA** | `ScaledObject` | Kafka lag 0↔N |
| **cert-manager** | `Issuer` · `Certificate` | TLS |
| **ESO** | `SecretStore` · `ExternalSecret` | 비밀 동기화(§7.7) |
| **Cilium** | `CiliumNetworkPolicy` · `CiliumLoadBalancerIPPool`(미사용) | FQDN egress |
| **MetalLB** | `IPAddressPool` · `L2Advertisement` | `.14`–`.16` |
| **Gateway API** | `GatewayClass` · `Gateway` · `HTTPRoute` | **이것도 CRD 다** |
| **Istio** | `PeerAuthentication` · `VirtualService`(재시도) | 메시 |
| **Prometheus Operator** | `ServiceMonitor` · `PodMonitor` · `PrometheusRule` | 대상 발견 + 알림규칙 20개 이관 (kube-prometheus-stack — 플랜 §9.0) |
| **ArgoCD** | `Application` · `AppProject` | GitOps |

> **Gateway API 가 CRD 라는 점이 중요하다.** 코어 API 가 아니라 별도 설치물이고 **버전이 알파/베타/GA 로 나뉜다.** `HTTPRoute` 는 GA 지만 일부 필드(예: `timeouts`)는 그렇지 않을 수 있다 — 쓰기 전에 채널·버전 확인이 필요하다.

### 8.4 하위 트리와 `ownerReferences` — 지우면 어디까지 사라지나

```
Cluster (CR)
 └─ ownerReference ─┬─ Pod / PVC
                    ├─ Service (pg-rw, pg-ro)
                    ├─ Secret (인증서·비번)
                    └─ ConfigMap
```

**부모가 사라지면 garbage collector 가 자식을 지운다**(cascading delete). 즉 **`kubectl delete cluster pg` 한 줄로 PVC 까지 날아갈 수 있다.**

→ §6.6 의 `reclaimPolicy: Retain` 이 **마지막 방어선**이다(PVC 가 GC 돼도 PV·데이터는 남는다). CNPG 의 PVC 보존 옵션과 **둘 다 켜서 방어선을 이중화**한다.

### 8.5 🔴 §2 정정 — CNPG 는 StatefulSet 을 쓰지 않는다

§2.2 에서 "PG·ES·Kafka 의 StatefulSet 은 오퍼레이터가 만든다"고 적었으나 **CNPG 는 예외**다. CNPG 는 **Pod 와 PVC 를 직접 관리**한다.

**왜 거부했는가가 §2.4 의 논지를 더 강하게 만든다:**

| StatefulSet 의 전제 | PG 의 현실 |
|---|---|
| 신원 = ordinal (`pg-0` 이 항상 같은 역할) | **역할(primary/replica)이 파드 사이를 이동**한다. 페일오버는 ordinal 과 무관 |
| 롤링 업데이트를 ordinal 순서로 | PG 는 **replica 먼저 → 전환 → 구 primary 마지막**이어야 안전 |
| 파드는 서로 대체 가능 | primary 와 replica 는 **하는 일이 다르다** |

즉 CNPG 는 "StatefulSet 만으론 부족하다"를 넘어 **"StatefulSet 의 의미론이 PG 에 틀리다"**고 판단했다. §2.4 의 논지("StatefulSet 이 보장하는 건 신원과 저장소뿐")보다 한 단계 나아간 근거다.

⚠️ 제품 고유의 설계 결정이므로 **P2 에서 실물 확인**한다(`kubectl get sts -n data`).

### 8.6 finalizer — 삭제가 멈추는 이유

```
kubectl delete cluster pg
  → deletionTimestamp 설정됨 (아직 존재)
  → 오퍼레이터가 정리 작업 수행
  → 오퍼레이터가 finalizer 제거
  → 그제야 삭제
```

🔴 **오퍼레이터가 죽은 상태에서 CR 을 지우면 finalizer 를 풀 주체가 없어 영원히 `Terminating` 에 걸린다.** 강제로 finalizer 를 지우면 하위 리소스가 고아로 남는다.

→ **정리 순서는 항상 CR 먼저 → 오퍼레이터 나중.**

### 8.7 오퍼레이터가 죽으면 무슨 일이 일어나나

**master ×1 을 정당화한 플랜 §2.1 과 정확히 같은 구조다:**

| | 계속되는 것 | 멈추는 것 |
|---|---|---|
| 오퍼레이터 다운 | **PG 는 계속 서빙**한다 (파드는 독립적으로 돈다) | **페일오버·스케일·백업 스케줄** = 변경 능력 |

**데이터플레인은 살고 컨트롤 능력만 죽는다.** 그래서 오퍼레이터 자체를 HA 로 만들 필요가 크지 않다(replica 1 로 충분).

**이것이 §5.2 배치 결정과 얽힌다** — PG primary 를 호스트 A 에 둔 이유가 "B 의 오퍼레이터가 승격시켜 준다"였는데, **호스트 B 가 죽으면 master 와 함께 오퍼레이터도 죽어** 승격이 불가능해진다. 그때는 primary(A)가 살아 있어 서빙이 계속되므로 **승격이 필요 없다** — 논리가 닫혀 있다.

### 8.8 업그레이드 — CRD 가 클러스터 스코프라는 것의 의미

**CRD 에는 네임스페이스가 없다(클러스터 전역).** 따라서:

- 오퍼레이터 업그레이드는 **CRD 스키마를 바꿔 클러스터 전체에 영향**을 준다
- 순서: **CRD 먼저 → 오퍼레이터 → CR**
- 🔴 **Helm 은 기본적으로 CRD 를 업그레이드하지 않는다**(`helm upgrade` 가 `crds/` 를 건드리지 않음) → **조용히 구버전 CRD 가 남아 새 필드가 무시되는** 함정. ArgoCD 로 관리하면 CRD 도 선언에 포함되어 완화된다 — GitOps 의 부수 이득이다

### 8.9 함정 정리

| | 함정 |
|---|---|
| 🔴 | **CR 삭제 = cascading delete** — PVC 까지 GC. `Retain` + 오퍼레이터 보존 옵션 이중화 (8.4) |
| 🔴 | **오퍼레이터를 먼저 지우면 CR 이 영원히 Terminating** — CR 먼저, 오퍼레이터 나중 (8.6) |
| 🔴 | **손으로 고친 것이 조용히 되돌려진다** — reconcile 은 level-triggered (8.2) |
| 🔴 | **Helm 이 CRD 를 업그레이드 안 함** — 구버전 CRD 가 남아 새 필드가 무시됨 (8.8) |
| ⚠️ | Gateway API 도 CRD — 필드별 GA/베타 채널 확인 필요 (8.3) |


---

## 9. 스케일 · 가용성

### 9.1 HPA 가 실제로 계산하는 것

```
desiredReplicas = ceil( currentReplicas × ( 현재 메트릭 / 목표 메트릭 ) )
```

`targetCPUUtilization: 70` 에 현재 5개 파드가 평균 90% 면 → `ceil(5 × 90/70)` = **7개**.

🔴 **"CPU 사용률"의 분모는 `limits` 가 아니라 `requests` 다.**

| requests | limits | 실제 사용 | HPA 가 보는 사용률 |
|---|---|---|---|
| 500m | 2000m | 1000m | **200%** (limits 기준이면 50%) |

→ **requests 를 실제 평상 사용량에 맞추지 않으면 HPA 가 과민하거나 무감각해진다.** 플랜 §3.1 의 "requests = 관측된 평상 사용량"이 여기서 회수된다.

**플래핑 방지**: `behavior.scaleDown.stabilizationWindowSeconds`(기본 300초)가 축소를 지연시킨다. 확대는 빠르고 축소는 느린 기본값이 우리 피크 패턴(11–12·17–18시)에 맞다.

### 9.2 🔴 account HPA — §4.5 가 여기서 마무리된다

HPA 도입의 **유일한 실측 근거**:

```
bcrypt CPU 포화 — cpus 0.75 → 2.0 상향 후에도 100VU 에서 한도의 98%
PG active 커넥션 0  ← DB 병목이 아님을 런타임 메트릭으로 확인
```

**순수 CPU 바운드**라 HPA 의 교과서적 대상이다. 그런데 §4.5 대로:

```
HPA 로 replica 증가 → 파드마다 커넥션 풀 생성 → max_connections 100 초과
                              ↓
                    HPA 가 CPU 가 아니라 DB 에 막힌다
```

**Pooler 가 HPA 의 전제조건**이며 순서가 있다:

1. **Pooler 구축**(P2) → 2. **앱 풀 축소**(4개는 코드 수정 §7.4) → 3. **그다음 HPA**(P3)

순서를 어기면 **"HPA 를 켰는데 오히려 느려지는"** 현상이 난다(커넥션 고갈로 대기 누적). 부하테스트에서 mealplan 이 보인 패턴(50VU 부터 TPS 고정·응답시간만 증가)이 정확히 그 모양이다.

### 9.3 HPA 대상과 비대상

| | 대상 | 근거 |
|---|---|---|
| ✅ **account** | HPA (CPU 70%) | bcrypt CPU 포화 실측 |
| 🟡 recipe · price · mealplan | HPA — **관측 후** | 피크타임 집중. 근거를 만든 뒤 켠다 |
| ❌ frontend | 고정 2 | 정적 서버 — CPU 를 안 쓴다 |
| ❌ **폴러 CronJob** | **고정 1** | **크롤 예의 + 중복 수집.** 수평 확장 금지 |
| ❌ 데이터 티어 | 오토스케일 아님 | 상태저장 |

**"일단 전부 HPA"를 하지 않는 이유** — 근거 없이 켜면 requests 오설정과 맞물려 진동한다. **account 만 실측 근거가 있고 나머지는 K8s 에서 관측 후 켠다.** 발표에서도 "측정 → 근거 → 적용" 순서가 강하다.

### 9.4 KEDA — HPA 가 못 하는 두 가지

KEDA 는 HPA 를 **대체하지 않고 감싼다.** `ScaledObject` 를 만들면 KEDA 가 내부적으로 HPA 를 생성하고 외부 메트릭(Kafka lag)을 먹여준다.

| | HPA | KEDA |
|---|---|---|
| 스케일 근거 | CPU·메모리(+커스텀 메트릭 어댑터) | **Kafka lag · 큐 길이 · cron** |
| **최소 replica** | **1**(0 불가) | **0 가능** |

**동작 순서** — 0 에서 깨우는 것은 HPA 가 못 하므로 **KEDA 가 직접** 0→1 을 올리고, 그 뒤 1→N 을 HPA 가 맡는다. 이 이중 구조를 알아야 "0→1 은 되는데 1→N 이 안 된다" 류 디버깅이 가능하다.

| 워크로드 | 트리거 | min |
|---|---|---|
| retail-refiner · recipe-refiner · deal-notifier | Kafka lag | **0** |
| user-event-sink | Kafka lag | 0 *(유입이 상시라 실제로는 0 에 잘 안 간다)* |
| 폴러 CronJob | — | KEDA 불필요(CronJob 이 이미 그 역할) |

⚠️ **콜드스타트 감수 여부를 확인할 것** — 0→1 은 이미지 pull + 컨테이너 시작 + Kafka consumer group 리밸런싱까지 수 초~수십 초다. 크롤 반영이 실시간일 필요가 없어 **우리는 감수 가능**하다.

### 9.5 PDB — 자발적 중단만 막는다

🔴 **PodDisruptionBudget 은 노드 장애를 막지 못한다.**

| | PDB 가 막나 |
|---|---|
| `kubectl drain`(노드 정비·업그레이드) | ✅ **막는다** |
| 오토스케일러의 노드 축소 | ✅ 막는다 |
| **노드 급사·커널 패닉** | ❌ **못 막는다** |
| OOM kill · eviction | ❌ 못 막는다 |

우리 급사 3회 같은 것은 PDB 의 영역이 아니다 — 그것은 replica 분산(플랜 §5.2)이 담당한다.

| 대상 | `minAvailable` | 왜 |
|---|---|---|
| **Pooler** | **1** | 🔴 모든 DB 트래픽이 지난다 — drain 중 0 이 되면 전면 장애 |
| Istio Gateway | 1 | 유입 경로 |
| 앱(replica ≥2) | 1 | |
| 데이터 티어 | 오퍼레이터가 관리 | CNPG·Strimzi 가 자체 PDB 생성 |

⚠️ **함정: `minAvailable: 1` 인데 replica 가 1 이면 drain 이 영원히 막힌다.** → **PDB 를 붙이는 워크로드는 replica ≥ 2** 가 전제다.

### 9.6 topologySpreadConstraints — `whenUnsatisfiable` 이 결정적이다

```yaml
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway     # ← 여기가 중요
```

| | 의미 | 위험 |
|---|---|---|
| `DoNotSchedule` | 균형을 못 맞추면 **Pending** | 🔴 **한 호스트가 죽으면 남은 호스트에 스케줄이 안 된다** |
| **`ScheduleAnyway`** | 균형을 선호하되 안 되면 배치 | 균형이 깨질 수 있다 |

**우리는 `ScheduleAnyway` 여야 한다.** 호스트 A 급사 시 파드가 B 로 몰리는 것을 허용해야 자가치유가 성립한다. `DoNotSchedule` 이면 "균형을 지키려다 서비스가 안 뜨는" 최악이 된다.

> **데이터 티어는 반대다** — quorum 다수를 B 에 두는 §5.2 배치는 **의도적 불균형**이라 spread 가 아니라 `nodeAffinity` 로 못 박는다.

### 9.7 실측 기반 rollout 순서 (재편된 단계 기준 — 플랜 §10)

```
P1  앱이 K8s 에서 실트래픽 서빙 → requests/limits 평상 사용량 실측 축적
     ↓
P2  Pooler 구축 (데이터 티어와 함께)
     ↓
P3  앱 풀 축소(4개는 코드 수정 §7.4) → 반복부하로 prepared statement 검증(§4.5.3)
     ↓
    account HPA 켜기 → 부하테스트 재검증(원본 조건 30/50/100/200VU)
     ↓
    KEDA ScaledObject (컨슈머 0↔N)
```

**HPA 를 Pooler·실측 뒤에 두는 이유** — requests 가 실측 없이 정해지면 §9.1 의 분모가 틀려 HPA 전체가 무의미해진다. 앱-먼저 재편 덕에 P1~P2 동안 평상 사용량이 자연히 쌓인다.


---

## 10. 보안

### 10.1 NetworkPolicy 는 "화이트리스트 스위치"다

**파드에 NetworkPolicy 가 하나도 없으면 전부 허용.** 그런데 **그 파드를 선택하는 정책이 하나라도 생기는 순간 명시하지 않은 것은 전부 차단**된다.

```
정책 0개          →  all allow
정책 1개(ingress) →  그 정책의 ingress 만 허용
                     egress 는? → egress 정책이 없으면 여전히 all allow
```

**ingress 와 egress 는 독립적으로 스위치가 켜진다.** `ingress` 만 적은 정책을 붙이면 egress 는 무제한이다.

### 10.2 🔴 default-deny 를 켜면 클러스터가 죽는 3가지

| 막히는 것 | 증상 | 필요한 예외 |
|---|---|---|
| **CoreDNS (53/UDP·TCP)** | **모든 이름 해석 실패** — 앱이 DB 도 못 찾는다 | `kube-system` CoreDNS 로 egress |
| **istiod (15012)** | 사이드카가 설정을 못 받음 → **mTLS·라우팅 붕괴** | `istio-system` 으로 egress |
| **kubelet probe** | **전 파드 Unhealthy → 무한 재시작** | **노드에서 오는 ingress** |

**세 번째가 가장 놓치기 쉽다.** §3.4 대로 **probe 는 Service 를 거치지 않고 kubelet 이 파드 IP 로 직접** 호출한다. 파드 셀렉터로만 정책을 짜면 "노드"라는 출처가 규칙에 없어 막히고, **증상이 "앱이 다 죽음"이라 NetworkPolicy 를 의심하기까지 오래 걸린다.**

> Cilium 은 `fromEntities: [host, remote-node]` 로 표현할 수 있지만, **표준 NetworkPolicy 를 쓰기로 한 플랜 §6.1 결정 때문에 노드 CIDR 을 `ipBlock` 으로 직접 관리해야 하는 비용**이 발생한다.

### 10.3 우리 정책 설계 — tier 라벨이 여기서 쓰인다

| 대상 | ingress | egress |
|---|---|---|
| **`tier=frontend`** | Gateway 에서만 | **DNS 만** — 백엔드 호출이 0 이므로(§1.3) |
| `tier=backend` | Gateway + 같은 ns 내 backend | `data` ns · DNS · istiod *(P1~P2 한정: + `192.168.0.8` ipBlock — VM 데이터 과도기, P2 에 제거)* |
| `data` ns | `app` backend + **`pipeline` ns**(컨슈머·CronJob → PG·Kafka) + 모니터링 | 자기들끼리(복제) + PGSync→ES |
| **chat · ocr** | 〃 | 〃 + **Gemini FQDN**(§10.4) *(youtube 는 미통합 — 플랜 §4.3)* |

**프론트엔드의 egress 가 DNS 뿐**이라는 것이 좋은 보안 진술이다 — 프론트 파드가 털려도 **거기서 갈 수 있는 곳이 없다.**

### 10.4 CiliumNetworkPolicy FQDN egress — 표준으로 불가능한 것

표준 NetworkPolicy 는 **IP/CIDR 만** 다룬다. Gemini API 는 CDN 뒤라 IP 가 수시로 바뀌어 **"IP 목록으로 외부 API 허용"이 원리적으로 불가능**하다.

```
파드가 generativelanguage.googleapis.com 조회
   ↓
Cilium DNS 프록시가 응답을 가로채 학습 → 그 IP 를 TTL 동안 허용목록에 추가
   ↓
그 IP 로의 연결만 통과
```

**DNS 응답을 정책의 입력으로 쓰는 것**이 핵심이고, 플랜 §9 의 "Hubble 이 DNS 질의를 본다"와 같은 메커니즘 위에 선다.

⚠️ **전제: 파드가 클러스터 DNS 를 써야 한다.** 앱이 DNS 를 우회해 IP 로 직접 붙으면 학습할 것이 없어 차단된다.

**왜 실질적인가** — Gemini 는 **유료 API** 이고 월 예산 캡(7,200원)·키 분리(§7.6)가 이미 구현돼 있다. 키가 유출되면 **실제 돈이 나간다.** 앱 층 + 네트워크 층 이중 방어.

### 10.5 SecurityContext — compose 에서 이미 절반 해뒀다

| compose | K8s | 상태 |
|---|---|---|
| `cap_drop: [ALL]` | `capabilities.drop: [ALL]` | ✅ 적용됨 |
| `read_only: true` | `readOnlyRootFilesystem: true` | ✅ 적용됨 |
| `cap_add: [NET_BIND_SERVICE]`(frontend) | 〃 | ✅ |
| — | **`runAsNonRoot: true`** | ⬜ 신규 |
| — | **`allowPrivilegeEscalation: false`** | ⬜ 신규 |
| — | `seccompProfile: RuntimeDefault` | ⬜ 신규 |

⚠️ **frontend 의 `NET_BIND_SERVICE` 는 없앨 수 있다.** compose 에선 nginx 가 `:80` 에 바인딩해야 했지만, K8s 에서는 **컨테이너 포트를 8080 으로 바꾸고 Service 에서 80→8080 매핑**하면 특권 포트를 쓰지 않는다. 단 `runAsNonRoot` 까지 가려면 **nginx 공식 이미지는 root 로 기동**하므로 비특권 변형(`nginx-unprivileged` 계열)으로 교체가 필요하다 — frontend Dockerfile 변경 1건(P1).

### 10.6 RBAC — 실제로 필요한 곳은 적다

**우리 앱은 K8s API 를 쓰지 않는다.** 따라서 앱용 ServiceAccount 는 권한이 0 이면 되고,

🔴 **`automountServiceAccountToken: false`** 를 명시해야 한다. 기본값이 `true` 라 **토큰이 자동 마운트되는데, 앱이 안 쓰면 공격 표면일 뿐**이다.

| 주체 | 권한 |
|---|---|
| 오퍼레이터들 | 자기 CR + 하위 리소스 |
| **ArgoCD** | 🔴 **클러스터 전역 쓰기** — `argocd` ns 격리(§1.2)의 이유 |
| Jenkins | **클러스터 접근 불필요** — config 레포에 커밋만 한다(플랜 §7.3) |
| Prometheus/Alloy | 서비스 디스커버리용 읽기 |

**Jenkins 가 클러스터 권한을 갖지 않는 것이 config 레포 방식의 부수 이득**이다.

### 10.7 Pod Security Standards

```
pod-security.kubernetes.io/enforce: restricted
```

| 레벨 | 의미 |
|---|---|
| `privileged` | 제한 없음 |
| `baseline` | 명백히 위험한 것만 차단 |
| **`restricted`** | runAsNonRoot·capability drop·seccomp 강제 |

**`app`·`pipeline` ns 는 `restricted`** 로 갈 수 있다 — §10.5 대로 조건을 대부분 이미 만족한다.

⚠️ **`data`·`*-system` ns 는 안 된다.** 오퍼레이터·CNI·CSI 는 특권이 필요하다(Cilium 은 eBPF 로드, OpenEBS 는 LVM 조작). **restricted 를 클러스터 전역으로 걸면 인프라가 뜨지 않는다.**

### 10.8 함정 정리

| | 함정 |
|---|---|
| 🔴 | **default-deny 시 CoreDNS·istiod·kubelet probe 예외** — 없으면 클러스터가 통째로 안 뜬다 (10.2) |
| 🔴 | **ingress/egress 스위치가 독립** — ingress 만 적으면 egress 무제한 (10.1) |
| 🔴 | **`automountServiceAccountToken: false`** — 안 쓰는 토큰은 공격 표면 (10.6) |
| 🔴 | **PSS `restricted` 를 전역으로 걸면 인프라가 안 뜬다** — ns 선별 적용 (10.7) |
| ⚠️ | FQDN egress 는 파드가 클러스터 DNS 를 써야 성립 (10.4) |
| ⚠️ | 표준 NetworkPolicy 는 **노드 CIDR 을 직접 관리**해야 한다 (10.2) |


---

## 11. 메시 오브젝트

### 11.1 사이드카 주입은 MutatingAdmissionWebhook 이다

```
kubectl apply (파드 생성 요청)
   ↓
API 서버 → istiod 의 webhook 으로 파드 spec 전송
   ↓
webhook 이 spec 을 수정해 반환 (istio-proxy 컨테이너 추가)
   ↓
수정된 spec 이 etcd 에 저장 → 스케줄
```

**두 가지가 따라 나온다:**

1. **주입은 파드가 만들어지는 시점에만** 일어난다 → ns 에 라벨을 붙여도 **이미 떠 있는 파드는 그대로**다. `kubectl rollout restart` 가 필요하다. *"라벨 붙였는데 왜 mTLS 가 안 되지?"* 의 답.
2. **파드 spec 을 남이 고친다** → GitOps 에서 ArgoCD 가 drift 로 볼 수 있어 `ignoreDifferences` 설정이 필요하다.

### 11.2 🔴 트래픽 가로채기 방식이 §10.7 과 충돌한다

Envoy 의 가로채기는 **iptables REDIRECT** 규칙이다. 문제는 **누가 규칙을 심느냐**다:

| 방식 | 심는 주체 | 필요 권한 |
|---|---|---|
| **init container**(기본) | `istio-init` | 🔴 **`NET_ADMIN` capability** |
| **Istio CNI plugin** | CNI 가 파드 생성 시 | **파드 권한 불필요** |

**`app` ns 를 PSS `restricted` 로 하기로 한 §10.7 과 정면 충돌한다** — `restricted` 는 `NET_ADMIN` 을 금지한다. → **Istio CNI plugin 이 사실상 필수**다.

그리고 §4.2 의 socketLB 함정이 정확히 이 지점이다. REDIRECT 는 **"목적지가 ClusterIP 인 패킷"** 을 잡는데, socket LB 가 `connect()` 에서 파드 IP 로 바꿔버리면 **잡을 대상이 없다**:

```
정상:  앱 → [ClusterIP] → iptables REDIRECT → Envoy → mTLS → 상대 Envoy
파손:  앱 → [파드IP]    → (조건 불일치)      → 평문 직행
```

**세 조각이 하나의 그림이다**: `socketLB.hostNamespaceOnly` + Istio CNI plugin + PSS restricted.

### 11.3 PeerAuthentication — PERMISSIVE 로 시작한다

| 모드 | 받는 트래픽 |
|---|---|
| `PERMISSIVE` | **mTLS 와 평문 둘 다** |
| `STRICT` | **mTLS 만** — 평문 거부 |

🔴 **처음부터 STRICT 면 컷오버가 깨진다.** P1 구간에는 사이드카 유무가 섞이고 `data`·`pipeline` ns 는 **의도적으로 메시 밖**(§1.2)이라 평문으로 온다.

```
P1 초반   PERMISSIVE(기본)  ← 섞여 있어도 동작
   ↓
전 app 파드 사이드카 확인(컨테이너 수 검증)
   ↓
P1 후반   app ns 만 STRICT  ← data ns 는 계속 평문(정상)
```

**STRICT 는 ns 단위로 건다.** 클러스터 전역 STRICT 는 `data` ns 통신을 죽인다.

### 11.4 HTTPRoute vs VirtualService — 역할 분담

| 기능 | 어디에 |
|---|---|
| 경로 라우팅 · 가중치(카나리) · **타임아웃** | **HTTPRoute**(표준 · 이식됨) |
| **재시도** · 서킷브레이커 · outlier detection | **Istio `VirtualService`/`DestinationRule`**(확장 · 재작성) |

**원칙: 표준으로 되는 것은 HTTPRoute, 안 되는 것만 Istio CR.** EKS 이식 시 재작성 범위를 최소화한다.

`DestinationRule` 의 실질 용도 둘:
- **연결 풀 상한** — Envoy 레벨의 백엔드 동시 연결 제한. §4.5 의 DB 커넥션 문제와 **같은 사고방식**이 HTTP 층에 적용된다
- **outlier detection** — 5xx 를 반복하는 파드를 일시 제외(passive health check). readiness probe 가 못 잡는 **"떠 있지만 고장난"** 상태를 잡는다

### 11.5 `Sidecar` 리소스 — 메모리가 설정 범위에 비례한다

기본값으로 istiod 는 **모든 서비스 엔드포인트를 모든 사이드카에 밀어넣는다**(EDS). 서비스가 늘수록 Envoy 각각의 메모리가 커진다.

```yaml
kind: Sidecar
spec:
  egress:
    - hosts: ["./*", "istio-system/*"]   # 자기 ns + 시스템만
```

§4.1 에서 사이드카를 100MB 로 계산했는데 **그 값이 설정 범위에 비례**한다. 서비스 9개인 지금은 문제없지만 원리를 알고 넣어둔다.

### 11.6 Job 제외의 실제 메커니즘

| | 방법 |
|---|---|
| **ns 단위** | `istio-injection` 라벨 없음 → webhook 이 안 건드림 |
| 파드 단위 예외 | `sidecar.istio.io/inject: "false"` 어노테이션 |

`pipeline` ns 를 통째로 OFF(§1.2)하므로 **어노테이션이 필요 없다.** 예외를 하나씩 다는 것보다 경계로 긋는 편이 나은 이유 — 새 CronJob 을 추가할 때 **잊어버릴 수가 없다.**

### 11.7 Telemetry — L7 메트릭의 수도꼭지

§9.1 에서 계산한 **"Istio 사이드카 25~75k 시리즈"** 가 여기서 조절된다. 기본 차원(source/destination workload·service·response code·flags)이 곱해져 카디널리티가 폭발하는데, **안 쓰는 차원을 끄면 시리즈가 크게 준다.**

→ **P1(메시 가동 직후)에서 실제 시리즈 수를 재고 Prometheus 메모리를 보며 조정**한다. §9.1 예상치가 빗나가면 여기가 첫 조정 지점이다.

---

## 12. compose → K8s 전체 매핑

### 12.1 오브젝트 대응

| compose | K8s | 비고 |
|---|---|---|
| `services:` 항목 | **Deployment**(앱·컨슈머) / **CronJob**(폴러) | §2.2 |
| `image:` | `spec.containers[].image` + kustomize `images:` | `IMAGE_TAG` 소멸 |
| `environment:` | **ConfigMap** + **Secret**(←ExternalSecret) | §7.3 |
| `.env` 파일 | ConfigMap 2층 + Secret 4+2개(ES auth 신규) | §7.3 |
| `healthcheck:`(exec) | **`httpGet`** readiness/liveness/**startup** | 프로세스 fork 소멸 §3.3 |
| `start_period:` | **`startupProbe`** | §3.4 |
| `depends_on:` | ❌ 없음 → **readiness + 앱 재시도** | 아래 ⚠️ |
| `restart: unless-stopped` | Deployment(컨트롤러가 항상 유지) | |
| `mem_limit` / `cpus` | `resources.requests` / `limits` | **HPA 의 분모가 requests** §9.1 |
| `networks: fbnet` | ns + **NetworkPolicy** | §10.3 |
| 서비스명 DNS(`account:8004`) | **Service DNS**(`account.app.svc`) | §4.1 |
| `ports: "80:80"` | **Gateway + HTTPRoute** | LoadBalancer 는 GW 전용(상시 2) |
| `volumes:`(ranking-model) | ❌ **소멸** → MinIO | RWX 제거 §5.5 |
| `profiles:`(ocr·ranking) | 별도 ArgoCD Application | |
| `deploy/app/docker-compose.yml` | kustomize base + overlays | |

⚠️ **`depends_on` 에 대응물이 없다.** K8s 는 기동 순서를 보장하지 않으므로 **앱이 의존성 부재를 견뎌야** 한다. 우리 앱은 `/health` 가 의존성과 무관하게 200 을 주고(§3.2) 폴백이 구현돼 있어 **이미 그 모델**이다.

### 12.2 통째로 사라지는 것 — 이것이 이전의 실질이다

| 사라지는 것 | 대체 | 규모 |
|---|---|---|
| nginx `/api/*` 프록시 | HTTPRoute | **13 블록** |
| nginx `/internal/metrics/*` + IP allowlist | ServiceMonitor + NetworkPolicy | **9 블록** |
| `resolver 127.0.0.11` | CoreDNS | |
| `X-Forwarded-*` 헤더 세팅 | Gateway | |
| `create_topics.py` | **KafkaTopic CRD** | 사고 재발 방지 |
| `crontab.fb-pollers` + `install-pollers.sh` | **CronJob** | 8 폴러 |
| exec healthcheck(python fork) | `httpGet` | 9 서비스 |
| `.env` 파일(`.9` 상주) | ConfigMap/Secret + **ESO** | 43 항목 |
| `IMAGE_TAG` · `COMPOSE_PROFILES` | kustomize / ArgoCD App | |
| `ranking-model` 공유 볼륨 | MinIO | **RWX 의존 제거** |
| CI 의 SSH 배포 스텝 | **ArgoCD** | |
| sleep 루프 상주 3개 | CronJob | §2.2 |
| **postgres-exporter** | CNPG 내장 메트릭 | §13.2 |

**"compose 시절의 우회"가 K8s 의 1급 개념으로 승격되는 것**이 이전의 본질이다. nginx 가 게이트웨이를, cron 이 스케줄러를, `.env` 가 설정 저장소를 흉내 내던 것들이 각각 제 자리를 찾는다.

### 12.3 새로 생기는 것

| 신규 | 왜 |
|---|---|
| **Pooler**(PgBouncer) | 🔴 HPA 의 전제조건 §4.5 |
| PDB | drain 보호 §9.5 |
| PriorityClass · ResourceQuota · LimitRange | ns 정책 §1.4 |
| ServiceMonitor | 메트릭 게이트웨이 대체 |
| ExternalSecret · SecretStore | 비밀 외부화 §7.7 |
| NetworkPolicy · CiliumNetworkPolicy | §10.3–10.4 |
| Certificate · Issuer | TLS §5.2 |
| ScaledObject | 0↔N §9.4 |
| PeerAuthentication · Sidecar · Telemetry | 메시 §11 |
| **metrics-server** | HPA 의 resource metrics API 전제 (플랜 §9.0) |
| **PrometheusRule** | 알림규칙 20개의 CR 이관 (kube-prometheus-stack) |
| **Prometheus agent** (P1 한정) | 파드 스크레이프 → `.11` remote_write 브릿지 — P4 에 철수 |
| **마이그레이션 Job** | `schema-production.sql` 자동 적용 경로가 없었다 §13.4 |
| **모델 다운로드 initContainer** | 앱 코드 변경 없이 RWX 제거 §13.3 |

### 12.4 앱 코드 변경이 필요한 것 — 3항목 (2026-07-27 정정)

| | 내용 | 근거 | 시점 |
|---|---|---|---|
| 1 | **pantry·mealplan·recipe·recipebook 의 `max_size` 하드코딩 → env 화** (4개 — 종전 "3개"는 recipebook 누락 오류) | Pooler 도입 시 풀 축소 §7.4 | P3 |
| 2 | **psycopg3 `prepare_threshold` 처리** | transaction 풀링 충돌 §4.5.3 | P3 |
| 3 | **ES basic_auth 3곳** — recipe·chat `db.py` + `pipelines/ingest/_db.py` (각 1~2줄 + env) | ECK 인증 강제 — 플랜 §5.2 | P2 전 |

*(+ 코드는 아니지만 frontend Dockerfile 의 비특권 이미지 교체 §10.5 — P1.)*

**나머지는 전부 인프라 층에서 끝난다.** 팀이 `read_only`·`cap_drop`·의존성 무관 `/health`·폴백을 이미 구현해 둔 덕이고, 이것이 이전 리스크를 크게 낮춘다.


---

## 13. 파드 설계 최적화 (멀티컨테이너 패턴 · init · 리소스)

멀티컨테이너 패턴 3종(sidecar / **ambassador** / **adapter**)과 init 관점에서 훑되, **적용할 곳과 적용하면 안 되는 곳을 함께** 정리한다.

| 패턴 | 적용처 | 판정 |
|---|---|---|
| **Ambassador** | PgBouncer 를 사이드카로 | ❌ **기각** — 문제를 못 고친다 (§13.1) |
| **Adapter** | exporter 4개 | 🟢 오퍼레이터 내장/사이드카로 이동 (§13.2) |
| **Init** | ranking 모델 다운로드 | 🟢 **채택 — 앱 코드 변경을 없앤다** (§13.3) |
| **Init** | DB 마이그레이션 | ⚠️ init 아니라 **Job** (§13.4) |
| **Init** | 의존성 대기 | ❌ 안티패턴 (§13.5) |
| **Native sidecar** | Envoy 순서 보장 | 🟡 안전장치 (§13.6) |
| — | **CPU limits 정책** | 🔴 **실측 근거 있는 최대 리스크** (§13.7) |
| — | preStop hook | 🟢 무중단 배포의 마지막 조각 (§13.8) |

### 13.1 ❌ Ambassador — PgBouncer 를 사이드카로 두면 안 된다

직관적으로는 매력적이다. 앱이 `localhost:6432` 로 붙으면 네트워크 홉이 사라지고 Pooler 가 SPOF 가 아니게 된다. **그런데 우리 문제를 전혀 못 고친다.**

```
사이드카 bouncer:  파드마다 bouncer 1개 → 각자 PG 에 server connection 을 연다
                   default_pool_size 5 × 파드 20개 = 100 커넥션   ← 곱셈이 그대로
중앙 Pooler:       모든 앱이 하나를 공유 → 총 server connection 을 한 곳에서 캡
```

§4.5 의 문제는 **"파드마다 풀이 생겨 곱해지는 것"** 인데, 사이드카 bouncer 는 **곱셈 대상을 앱 풀에서 bouncer 풀로 바꿀 뿐**이다. 총량을 캡할 수 있는 것은 중앙 집중뿐이다. → **중앙 Pooler(Deployment) 유지가 맞다.**

### 13.2 🟢 Adapter — exporter 4개가 재배치된다

현재 `postgres/redis/es/kafka-exporter` 가 별도 compose 서비스다.

| | K8s 에서 |
|---|---|
| postgres-exporter | **소멸** — CNPG 가 메트릭 내장 |
| kafka-exporter | Strimzi CR 에 JMX exporter 선언(내장) |
| es-exporter | ECK 구성 또는 사이드카 |
| redis-exporter | 오퍼레이터의 exporter 사이드카 옵션 |

전형적인 **Adapter 패턴**(앱 출력을 표준 인터페이스로 변환)이 **오퍼레이터에 흡수**되는 사례다. → §12.2 "사라지는 것" 에 추가.

### 13.3 🟢 Init container — ranking 모델. 앱 코드 변경을 없앤다

**§5.5(플랜)에 구멍이 있었다.** 모델을 MinIO 로 옮기면 serving 이 S3 클라이언트를 갖게 되어 **앱 코드 변경**이 필요하다 — §12.4 의 "코드 변경 2개" 에 세 번째가 될 뻔했다.

```
initContainer (mc/aws-cli):  MinIO → emptyDir:/models/ranker.pkl
        ↓
serving 컨테이너:  RANKING_MODEL_PATH=/models/ranker.pkl   ← 코드 그대로
```

**RWX 제거를 앱 코드 변경 0 으로 달성한다.** retrain 의 업로드도 CronJob command 를 래퍼로 감싸면(`python retrain.py && mc cp …`) 파이썬 수정이 필요 없다.

⚠️ 재학습 후 반영(`/reload`)은 **CronJob 종료 후 serving 을 `rollout restart`** 하면 init 이 새 모델을 받는다 — 이것도 코드 변경 0.

### 13.4 ⚠️ DB 마이그레이션 — init 이 아니라 Job

**프로덕션 자동 적용 경로가 없다.** `schema-production.sql` 을 참조하는 것은 `dev-db.sh` 뿐이고 실제로는 수동이다.

| | 판정 |
|---|---|
| init container | ❌ **replica 마다 동시 실행 → 레이스** |
| **Job / ArgoCD PreSync hook** | ✅ 한 번만 실행 |

멱등 DDL 이라 재실행은 안전하지만 **동시 실행은 다른 문제**다(같은 DDL 을 두 세션이 치면 락 경합·에러). → §12.3 "새로 생기는 것" 에 추가.

### 13.5 ❌ 의존성 대기 init — 안티패턴

"PG 가 뜰 때까지 기다리는 init container" 는 흔한 실수다. K8s 는 **재시작으로 수렴**하는 모델이고 우리 앱은 이미 의존성 부재를 견딘다(§3.2). init 에서 기다리면 startup 만 늦어지고 실패 모드가 하나 는다.

### 13.6 🟡 Native sidecar — Envoy 순서 보장

K8s 1.28+ 의 `initContainers` + `restartPolicy: Always` 는 **앱보다 먼저 준비되고 나중에 종료**된다. "앱이 Envoy 보다 먼저 떠서 첫 요청이 실패하는" 고전 레이스가 사라진다.

우리 실전 영향은 작다 — 앱→PG 는 메시 밖이고 chat→pantry 는 기동 직후에 부르지 않는다. **켜두면 좋은 안전장치** 수준이며 Istio 버전 확인이 필요하다.

### 13.7 🔴 CPU limits — 부하테스트 병목의 재발 위험

**사이드카보다 중요하다.** 부하테스트에서 account 의 병목이 `cpus: 0.75` 였고 2.0 으로 올려 30VU 를 해결했다. 그런데 K8s 의 `resources.limits.cpu` 는 **CFS quota 로 스로틀링**한다 — **노드에 유휴 CPU 가 있어도 quota 를 넘으면 강제로 멈춘다.**

즉 **compose 에서 겪은 그 병목을 K8s 에서 그대로 재현할 수 있다.**

| | 권장 |
|---|---|
| **memory limits** | ✅ **필수** — OOM 보호(Tempo 768M 크래시루프 전례) |
| **CPU requests** | ✅ 정확히 — HPA 의 분모(§9.1) |
| **CPU limits** | ⚠️ **생략하거나 넉넉하게** — 특히 account(bcrypt 는 버스트가 본질) |

단 **`pipeline` ns 는 예외** — ResourceQuota 로 총량을 캡하기로 했으므로(§1.4) limits 가 있어야 한다. 크롤러가 앱을 굶기는 것을 막는 쪽이 우선이다.

### 13.8 🟢 preStop hook — 무중단 배포의 마지막 조각

파드를 지우면 **EndpointSlice 제거와 SIGTERM 이 동시에** 일어난다. 엔드포인트 전파(eBPF 맵·Envoy)에 시간이 걸려 **SIGTERM 이후에도 트래픽이 들어온다.**

```yaml
lifecycle:
  preStop:
    exec: { command: ["sleep", "5"] }
terminationGracePeriodSeconds: 30
```

§2.3 의 롤링 업데이트에 빠져 있던 조각이다. 없으면 **배포마다 소량의 5xx** 가 나고, 카나리 판정(5xx율)까지 오염시킨다.

### 13.9 나머지

- **QoS class** — Guaranteed 는 **CPU·메모리 모두** `requests == limits` 여야 한다. §13.7 의 "CPU limits 생략" 권고와 양립 불가이므로 **우리 파드는 Burstable 이 정상**이고, eviction 방어는 QoS 가 아니라 **PriorityClass(§1.4)가 담당**한다. *(종전 "메모리만 일치시키는 절충으로 Guaranteed + 이중 방어" 서술은 오류 — 메모리만 일치면 Burstable 이다. 메모리 requests=limits 는 QoS 등급과 무관하게 OOM 예측성을 위해 여전히 권장.)*
- 🔴 **디버깅** — 우리 컨테이너는 `read_only` + `cap_drop: ALL` 이라 **exec 로 들어가기 어렵다.** `kubectl debug -it <pod> --image=busybox --target=<container>`(ephemeral container)가 답이며 **운영 문서에 넣어둘 것.** 하드닝의 대가다.
- **frontend tmpfs** — compose 의 `tmpfs: /var/cache/nginx, /run` 은 `emptyDir: {medium: Memory}` 로 직접 대응된다.
