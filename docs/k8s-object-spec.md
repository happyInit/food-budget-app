# K8s 오브젝트 스펙 (deep-dive)

> **어떤 오브젝트를 · 왜 · 내부적으로 어떻게 동작하는가.** 결정의 근거는 [`k8s-migration-plan.md`](./k8s-migration-plan.md), 구축 현황은 [`k8s-infra-status.md`](./k8s-infra-status.md). 이 문서는 **그 결정을 오브젝트 수준으로 내리는 층**이다.
> 작성 2026-07-24 · 섹션별로 합의하며 누적한다 (미작성 섹션은 §0 로드맵에 ⬜).

## 0. 로드맵

| # | 섹션 | 상태 |
|---|---|---|
| 1 | Namespace 설계 | ✅ |
| 2 | 워크로드 (Deployment/StatefulSet/DaemonSet/Job) | ✅ |
| 3 | Probe 3종 | ✅ |
| 4 | Service · EndpointSlice | ✅ |
| 4.5 | DB 연결단 (Pooler) | ✅ |
| 5 | Gateway API | ⬜ |
| 6 | 스토리지 (SC/PV/PVC) | ⬜ |
| 7 | 설정·비밀 (ConfigMap/Secret/ExternalSecret) | ⬜ |
| 8 | 오퍼레이터 CR | ⬜ |
| 9 | 스케일·가용성 (HPA/KEDA/PDB) | ⬜ |
| 10 | 보안 (NetworkPolicy/RBAC/SecurityContext) | ⬜ |
| 11 | 메시 오브젝트 | ⬜ |
| 12 | compose → K8s 전체 매핑표 | ⬜ |

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

[`k8s-migration-plan.md §4.3`](./k8s-migration-plan.md)에서 정한 메시 경계(app 포함 / data 제외 / Job 제외)가 **정확히 네임스페이스 경계**다. 우연이 아니라, 주입 라벨이 ns 단위라서 그렇게 그어야 선언적으로 성립한다.

| ns | 담는 것 | 메시 주입 | 왜 갈렸나 |
|---|---|---|---|
| `app` | FastAPI 9 + frontend | **ON** | mTLS·L7 관측·카나리 대상 |
| `data` | PG·ES·Kafka·Redis *(오퍼레이터가 생성)* | **OFF** | 오퍼레이터 가정 보존 + 비-HTTP 프로토콜 |
| `pipeline` | Kafka 컨슈머 4 + CronJob 11 | **OFF** | 아래 ⚠️ |
| `observability` | LGTM + MinIO | OFF | 리소스 격리 — 관측이 앱을 굶기면 안 된다 |
| `argocd` | ArgoCD | OFF | 클러스터 전역 쓰기 권한 → RBAC 격리 |
| `*-system` | istio · metallb · cnpg · elastic · strimzi · keda · external-secrets · cert-manager | OFF | 오퍼레이터별 관례 |

⚠️ **pipeline ns 를 통째로 OFF 하는 근거** — 주입은 ns 라벨이 기본이고 파드 어노테이션으로 개별 예외를 둘 수 있어서 "컨슈머 ON / Job OFF" 로 섞을 수도 있다. 그런데 **컨슈머가 말하는 상대가 Kafka(바이너리)와 PG(와이어 프로토콜)** 라 L7 이득이 0 이다. 얻는 것 없이 예외 규칙만 늘어나므로 **ns 전체 OFF 가 맞다.** (§4.2 "L7 을 어디서 쓰는가"의 회수 지점)

### 1.3 frontend 를 별도 ns 로 분리하지 않는다

**전제 변화부터** — `frontend/nginx.conf` 의 `/api/*` `proxy_pass` 블록 15개는 K8s 에서 **전부 HTTPRoute 로 대체된다.** 프론트엔드의 역할이 바뀐다:

| | compose | K8s |
|---|---|---|
| nginx 역할 | **게이트웨이** — 유일 노출 포트 + `/api/*` 리버스 프록시 | **정적 파일 서버만** |
| 라우팅 주체 | `nginx.conf` location 블록 | **HTTPRoute** (선언적·GitOps 대상) |
| 백엔드 호출 | nginx → 서비스명 DNS | **없음** — 프론트는 백엔드를 부르지 않는다 |

**결론: `app` ns 하나 + 파드 라벨(`tier=frontend|backend`) 로 구분한다.**

- 분리의 실익은 NetworkPolicy 를 다르게 붙이는 것인데, **NetworkPolicy 는 ns 가 아니라 파드 라벨로 선택**한다. `tier=frontend` 에 egress-deny 를 거는 것은 같은 ns 에서도 된다.
- 워크로드 10개(프론트 1 + 백엔드 9)에 ns 2개는 얇고, 크로스-ns FQDN·정책 중복 비용만 생긴다.
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
| 폴러 8 | **CronJob** | 실제 크론: 컬리 18:30 · 오아시스 19:10/04:10 · 딜 06:05/08:05 · 레시피 화·토 20:00 · matview 매시 :20 · ES재색인 화·토 21:30 (UTC) |
| deal-pruner · user-data-pruner · chat-insights | **CronJob 으로 전환** ✅합의 | 지금은 sleep 루프 상주 — 컨테이너 시절의 타협이었다 |
| ranking-serving / ranking-retrain | Deployment / **CronJob** | 모델은 MinIO 경유(플랜 §5.5) → **볼륨 불필요** |
| PG · ES · Kafka · Redis | **CR** (`Cluster` · `Elasticsearch` · `Kafka`) | StatefulSet 은 **오퍼레이터가 만든다** — 우리가 쓰는 오브젝트가 아니다 |
| MinIO | **StatefulSet** | 우리가 직접 만드는 **유일한** StatefulSet |
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
| 앱 9 + frontend | ClusterIP | HTTPRoute 가 가리킴 |
| Istio Gateway | **LoadBalancer** | **딱 1개** (플랜 §3.3 EKS 이식 규칙) |
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
HPA (min 2, max 4) 가정
  무거운 4개 × 4 replica × 10 = 160
  가벼운 4개 × 4 replica ×  5 =  80
  파이프라인 컨슈머 4 + CronJob 11 + PGSync + ranking = 30+
                                    ────────────────
                                    270+  vs  max_connections 100
```

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
- ⚠️ **P1 검증 항목** — 스모크만 돌리면 prepare 임계 전이라 **안 터지고 넘어간다.** 반드시 반복 부하로 확인할 것

**② PGSync 는 Pooler 를 우회한다**

PGSync 7.1.0 은 **LISTEN/NOTIFY** 로 변경을 감지하는데(`pgsync-adoption.md`), 세션에 묶인 기능이라 **transaction 풀링에서 동작하지 않는다.** → PGSync 는 `pg-rw` **직접 접속**, 앱만 Pooler 경유로 라우팅을 가른다.

> 그 밖의 transaction 모드 제약(advisory lock · 세션 `SET` · 임시 테이블)을 쓰는 코드가 있는지 P1 에서 함께 확인한다.

### 4.5.4 부수 기회 — `-ro` 활용 (별건)

CNPG 는 `pg-rw`(primary)·`pg-ro`(standby)를 나눠 준다. 읽기 쿼리를 standby 로 보내면 primary 부하가 크게 줄지만 **앱이 현재 읽기/쓰기를 나누지 않아 9개 서비스 코드 변경**이 따른다. 인프라는 **두 엔드포인트를 준비만** 해 두고, 전환은 별도 이슈로 뺀다.
