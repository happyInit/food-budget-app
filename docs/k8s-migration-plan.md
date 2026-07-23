# K8s 이전 최종 플랜 (정본)

> **이 문서는 K8s 이전의 실행 정본이다.** 결정·근거·컷오버 순서를 담는다.
> 관계: 집약본 [`k8s-migration.md`](./k8s-migration.md)(기존 8개 문서에서 모은 배경) · 현행 인프라 [`infra-status.md`](./infra-status.md) · 설계 정본 [`design.md`](./design.md) · 백업 [`backup-strategy.md`](./backup-strategy.md)
> 작성 2026-07-23 · 상태 = **결정 완료(아래 §1) + 결정 대기 3건(§10)**
> 선행조건: **물리 호스트 2대** (호스트 B 확보됨/확보 예정 — 미확보 시 이 플랜 전체가 착수 불가, §2.1)

---

## 0. 이 플랜의 두 가지 목적

1. **서비스 명분** — 실측·실장애가 요구한 것만 도입한다. 규모에 안 맞는 기술은 그 사실을 숫자로 기각한다.
2. **EKS 이식성** — 온프렘 K8s는 종착지가 아니라 **AWS EKS로 가는 관문**이다. 모든 구성요소를 "EKS에서 무엇이 바뀌는가" 기준으로 골랐다(§7).

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
| 라우팅 모드 | VXLAN 시작 (최종 ❓ §10) | 네트워크 설정 의존성 0 |
| 앱 외부 LB | MetalLB (L2) — **LoadBalancer Service는 GW 1개만** | 가정용 공유기 = BGP 불가 (§3.3) |
| 남북 L7 | Gateway API, 구현체 = Istio | Ingress는 동결 API·표준 승계 (§3.3) |
| 서비스 메시 | **Istio sidecar** (ambient 기각) | §4 |
| 데이터 티어 | **전부 in-cluster** — PG(CNPG)·ES(ECK)·Redis·Kafka(Strimzi) | §5 |
| 스토리지 | **OpenEBS LVM LocalPV** (동적 프로비저닝·CSI) | EBS gp3와 동작 의미 일치 (§5.2) |
| 오브젝트 스토리지 | **MinIO**(내부: LGTM·모델) + **AWS S3**(백업) | §5.3 |
| DB 홉 암호화 | **Cilium WireGuard 켬** | 전 구간 in-cluster → 한 플래그로 전부 커버 (§6.2) |
| 접근통제 | 표준 NetworkPolicy + **Cilium CNP FQDN egress** | §6.1 |
| Secret | **External Secrets Operator** | 백엔드 교체만으로 EKS 이식 (§6.4) |
| 관측 | **LGTM in-cluster** + Hubble + Istio telemetry | §8 |
| 클러스터 밖 잔류 | **Harbor · GitHub Actions 러너** (전용 VM) | 레지스트리·CI가 클러스터에 의존하면 클러스터 장애 시 복구 수단이 함께 죽는다 |
| DNS | CoreDNS | |
| vmbr1 내부망 | 미사용 (단일 NIC) | 파드 통신은 CNI 오버레이가 처리 |
| 컷오버 | 상태없는 것부터 점진 (P0~P6) | §9 |

---

## 2. 클러스터 토폴로지

### 2.1 왜 master ×1인가 — 고도화를 수학으로 기각한 지점

물리 호스트가 2대인데 master를 3개 두면 **반드시 2:1로 몰린다.** 2개 있는 쪽 호스트가 죽으면 quorum(과반 2)이 깨져 컨트롤플레인이 정지한다. 즉 3-master는 이 조건에서 **HA 비용만 내고 HA를 못 받는 구조**다. 물리 3대가 되기 전까지 컨트롤플레인 HA는 착시이므로, 단일 master로 단순화하고 완전 HA는 물리 증설 로드맵으로 미룬다.

- **apiserver VIP(HAProxy/keepalived/kube-vip) 불필요** — 모든 노드가 `master IP:6443`을 직접 본다. VIP는 apiserver가 2개 이상일 때 필요한 컨트롤플레인 HA 장치이지 CNI/kube-proxy의 역할이 아니다.
- **master 장애 시 무엇이 죽고 무엇이 사는가** — 데이터플레인은 계속 서빙한다(기존 파드 가동·kube-proxy 대체 eBPF 맵·Istio 사이드카 라우팅 유지). 죽는 것은 *변경 능력*이다: 신규 스케줄·오토스케일·배포·재스케줄 불가. 복구 = etcd 스냅샷 + IaC 재구축.
- **발표 Q&A 대비**: etcd 스냅샷 복원 소요 시간을 1회 실측해 숫자로 보유할 것.

### 2.2 노드 배치 (RAM 예산)

```
Host A (기존 192.168.0.12, i7-10700F/32GB)   Host B (신규, 32GB)
├─ worker-a1   14GB                          ├─ master      3GB
└─ worker-a2   14GB                          ├─ worker-b1  13GB
   (호스트 몫 ~2GB)                            └─ worker-b2  13GB
                                                (여유 ~3GB)
※ Harbor·CI 러너 VM이 A에 상주하면 A 워커는 11.5GB씩으로 조정
```

**master를 신규 호스트 B에 두는 이유**: 무흔적 급사 3회(2026-07-19·07-21×2)가 **전부 호스트 A**에서 발생했다. 컨트롤플레인을 B에 두면 *실제로 일어난 장애 모드*(A 급사)에서 master가 생존해 파드 재스케줄이 작동한다 — 자가치유 데모가 가상 시나리오가 아니라 실제 장애 시나리오에서 성립한다. B 급사 시 컨트롤플레인 상실은 문서화된 한계로 수용한다.

**워커 RAM 예산** — 가용 ~54GB 대비 소비 추정 ~33GB, **여유 ~21GB**:

| 소비처 | RAM |
|---|---|
| K8s 시스템 (kubelet + Cilium agent, 워커 4대) | ~5.2GB |
| 스토리지 프로비저너 (OpenEBS LVM CSI) | ~0.5GB |
| 데이터 티어 (PG 2×2 · ES 3×1.5 · Kafka 3×1 · Redis 0.5) | ~12GB |
| LGTM in-cluster + MinIO | ~6.5GB |
| 오퍼레이터 (CNPG·ECK·Strimzi·KEDA·cert-manager·ESO) + ArgoCD | ~3.5GB |
| Istio (istiod 0.5 + GW 0.2 + 사이드카 9×0.1) | ~1.6GB |
| 앱 9개 | ~2.8GB |
| 파이프라인 컨슈머·CronJob | ~1.5GB |

### 2.3 토폴로지 라벨 — EKS AZ로 무수정 매핑

노드에 `topology.kubernetes.io/zone` 라벨을 붙인다(Host A = `zone-a`, Host B = `zone-b`). 분산 제약은 **노드 이름 기반 anti-affinity가 아니라 `topologySpreadConstraints`** 로 작성한다. EKS로 옮기면 같은 매니페스트가 진짜 AZ 분산으로 동작한다 — 이식성이 "주장"이 아니라 코드가 되는 지점.

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

**VXLAN으로 시작하는 이유**: ① 네트워크 설정 의존성 0 ② 노드 추가·VM 이동에 강함 ③ "다른 노드 파드끼리 통신 안 됨" 부트스트랩 실패 모드를 통째로 제거. 우리 노드는 다 같은 L2라 native도 가능하지만 **"놀랄 일 없는 기본값"이 VXLAN**이다. 실측 병목이 잡히면 native로 전환한다(§10-2).

### 3.3 남북 인그레스

- **MetalLB (L2 모드)** — `IPAddressPool` + `L2Advertisement`. 가정용 공유기 환경이라 BGP 피어링이 불가능해 L2가 유일한 현실적 선택이다. Cilium LB IPAM은 끈다.
  - L2의 알려진 한계(리더 노드 1대가 인그레스 전량 수신, 페일오버 수 초)는 실측 대비 무해하다 — 500VU 피크 테스트에서 p95 12ms·CPU 18.7%로 인그레스가 병목 근처도 가지 않았다.
- **Gateway API, 구현체 = Istio** — `GatewayClass=istio` · `Gateway`(MetalLB LB IP 리스너 + TLS 종단) · `HTTPRoute`(`/`→frontend, `/api/*`→각 서비스). Ingress는 동결된 API이고 Gateway API가 공식 승계다. 메시가 Istio인 이상 게이트웨이도 Istio로 통일해 L7 프록시 혼용(Envoy 계열 2종)을 피한다.
- 🔵 **EKS 이식 규칙 — `type: LoadBalancer` Service는 Istio 게이트웨이 딱 하나만 만든다.** MetalLB는 EKS로 이식되지 않는 유일한 필수 교체 대상(EKS = AWS Load Balancer Controller/NLB)인데, LoadBalancer Service를 하나로 제한하면 이식 작업이 **Service 1개의 어노테이션 교체**로 끝난다. 서비스마다 LoadBalancer를 뿌리면 이식 비용이 서비스 수만큼 곱해진다.

---

## 4. 서비스 메시 — Istio sidecar

### 4.1 sidecar vs ambient (확정: sidecar)

| 판단 축 | 내용 |
|---|---|
| **ambient의 존재 이유** | 사이드카 수천 개의 리소스·업그레이드 비용. **우리는 사이드카가 9개고 그 문제를 갖고 있지 않다.** |
| **L7 필요성** | ambient의 경량 이점은 "mTLS만 필요할 때" 성립. 우리는 카나리·라우트별 RED·타임아웃/재시도가 채택 명분이라 ambient에서도 waypoint(=Envoy)가 필요 → 실질 격차 축소 |
| **비용 실측** | 사이드카 9×~100MB + istiod ~0.5GB + GW ~0.2GB ≈ **~1.6GB = 증설 후 총 RAM의 2.5%** |
| **Cilium 조합** | sidecar+Cilium은 `socketLB.hostNamespaceOnly` 한 줄로 해결되는 검증된 조합. ambient+Cilium은 ztunnel 리다이렉션과 CNI 체이닝이 얽혀 사례가 적음 → 8~9주 일정에서 리스크 |
| **학습·포트폴리오** | sidecar가 프로덕션 배포의 압도적 다수이자 공용어 |

**재검토 트리거**: 파드 수가 수백 단위로 커지면 ambient를 재검토한다. (몰라서 안 쓴 것이 아니라 알고 미룬 것 — 발표 방어선.)

### 4.2 L7을 실제로 어디서 쓰는가

메시 명분의 핵심 질문이므로 코드 근거로 명시한다.

**① 남북 — 사용자 트래픽 100%.** 현행 frontend nginx가 하는 일(`/`=정적, `/api/*`=8개 서비스 경로 프록시, 유일 노출 포트 :80)이 그대로 Istio Gateway + HTTPRoute로 넘어온다. 모든 유저 요청이 예외 없이 L7을 거치므로, 동서 트래픽 규모와 무관하게 성립하는 최대 소비처다.

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

- **app 서비스 9개 = 메시 안** — 앱 코드 수정 0으로 mTLS·L7 관측·카나리·재시도/타임아웃 획득.
- **data 네임스페이스 = 메시 밖 (사이드카 X)** — 오퍼레이터(CNPG/ECK/Strimzi)가 StatefulSet·프로브·페일오버를 자기 방식대로 관리하므로 Envoy 주입이 그 가정을 깬다. PG 와이어·Redis RESP·Kafka 바이너리는 비-HTTP라 L7 이득 없이 비용·위험만 남는다. 대신 **NetworkPolicy(접근) + WireGuard(암호화)** 로 처리한다.
- **Job/CronJob(retrain·youtube·크롤러) = 사이드카 제외** — Job은 모든 컨테이너가 종료돼야 Complete인데 Envoy는 안 죽어 **Job이 영원히 안 끝난다.**
  - 각주: K8s 1.28+ native sidecar로 종료 문제 자체는 해결됐지만, 이 Job들의 상대는 PG·Kafka·외부 API라 메시에 넣을 이유가 애초에 없다 → 제외가 여전히 정답.
- **egress(Gemini)** = Istio가 아니라 Cilium FQDN egress 담당 (§6.1).

---

## 5. 데이터 플랫폼 (in-cluster)

### 5.1 배치 — 전부 클러스터 안, 워커 위

PG(CloudNativePG) · ES(ECK) · Redis · Kafka(Strimzi) 를 모두 `data` 네임스페이스의 StatefulSet으로 운영한다. **fb-data VM은 컷오버 완료 후 해체한다.**

- 앱→DB = ClusterIP Service (CNPG는 `-rw`/`-ro`) + NetworkPolicy
- 분산 = `topologySpreadConstraints`로 두 존(=두 물리 호스트)에 분산
- **ES는 자체 master 선출 → 홀수 quorum 필요** (3노드). 물리 2대라 2:1 분산이므로 **부분 HA**임을 명시한다 — 2개 있는 호스트가 죽으면 ES는 quorum을 잃는다. PG/Redis는 primary-standby라 2대에서도 견딘다.
- **Kafka = KRaft combined 3노드, RF=3, persistent-claim.** 롤링 재시작 중에도 무중단이라 KEDA lag 스케일링 데모가 안정적으로 성립한다.
  - 🔴 **브로커 자동 토픽 생성(`auto.create.topics.enable`)은 끈다.** 2026-07-20 클릭스트림 개통 때 브로커 자동생성이 `create_topics.py`를 조용히 무력화해 1파티션 토픽 사고가 났다. K8s에서는 **`KafkaTopic` CRD가 토픽 생성의 유일 경로**다.
  - 🔴 **PV는 반드시 명시적으로 배선한다.** 2026-07-21에 `KAFKA_LOG_DIRS` 미배선으로 볼륨이 비어 있다가 recreate 시 **토픽이 전멸**했다. Strimzi `storage.type=persistent-claim` + 볼륨 마운트 확인을 컷오버 체크리스트에 포함한다.

### 5.2 스토리지 = OpenEBS LVM LocalPV (동적 프로비저닝)

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

### 5.3 오브젝트 스토리지 = MinIO(내부) + S3(백업)

| 용도 | 저장소 | 이유 |
|---|---|---|
| LGTM 백엔드 (Mimir·Loki·Tempo) | **MinIO** | 고볼륨·저가치 데이터. 실제 S3면 PUT 요청비가 누적되고, 가정망 업링크가 끊기면 관측이 중단된다 |
| ranking 모델 아티팩트 | **MinIO** | §5.4 |
| DB 백업 (CNPG barman-cloud·ES 스냅샷·etcd) | **AWS S3** (ap-northeast-2) | 재해복구가 생명 — 오프사이트가 본질 |

둘 다 S3 API라 EKS 이식은 **엔드포인트·자격증명 교체**뿐이다.

### 5.4 🔴 `ranking-model` RWX 의존 제거 (EKS 비용 지뢰)

현행 compose는 `ranking-retrain`(쓰기)과 `ranking-serving`(읽기)이 `ranking-model` 볼륨의 `/models/ranker.pkl`을 공유한다(`deploy/app/docker-compose.yml:250,275` · `ml/recipe-ranking/SERVING.md`). K8s에서 이건 **RWX**인데 — 로컬 PV도 EBS도 RWX를 못 하고, **EKS에서는 EFS를 사서 써야 한다**(유료·고지연).

**→ 모델 아티팩트를 MinIO(S3 API)로 옮긴다.** retrain이 업로드하고, serving이 `/reload` 시 다운로드한다. 이미 `RANKING_RELOAD_URL` 푸시 고리가 구현돼 있어 훅이 준비된 상태다.

이로써 **"전 볼륨 RWO"** 규율이 서고, 이게 EBS와 정확히 같은 제약이라 이식이 무손실이 된다. 신규 RWX 요구가 생기면 이 규율 위반으로 간주하고 오브젝트 스토리지로 우회한다.

---

## 6. 보안

### 6.1 접근통제

- **표준 K8s NetworkPolicy** (L3/4) — 네임스페이스 격리·DB 접근 통제. 이식성 우선.
- **Cilium NetworkPolicy(CNP) FQDN egress** — 외부 LLM(Gemini) 아웃바운드를 도메인 단위로 통제. `chat`·`ocr`·`youtube` 파드만 `generativelanguage.googleapis.com`으로 허용.
  - **이 서비스에서 위협 모델이 진짜인 이유**: Gemini는 유료 API이고, 이미 월 예산 상한(7,200원 · `MONTHLY_CAP_ENABLED`)과 비용 격리용 키 분리(`CHAT_GEMINI_API_KEY` ↔ `GEMINI_API_KEY`)가 구현돼 있다. 키 유출·오남용 = 실제 금전 사고다. **앱 층(예산 캡) + 네트워크 층(FQDN egress) 이중 방어**로 발표한다.
- 🔴 **default-deny 도입 시 함정**: CoreDNS(53)와 istiod(15012) egress 예외를 빼먹으면 클러스터가 조용히 마비된다. netpol 체크리스트에 명시.

### 6.2 암호화

| 구간 | 방식 |
|---|---|
| 사용자 → GW | HTTPS (Istio GW가 TLS 종단) |
| app ↔ app (동서) | mTLS (메시) |
| app → DB / 노드 간 전부 | **Cilium WireGuard** |

데이터 티어가 전부 in-cluster가 되면서 **WireGuard 한 플래그가 DB 홉을 포함한 노드 간 전 트래픽을 투명 암호화**한다. 인증서 관리 0. (PG-SSL은 DB별 인증서·로테이션 부담이라 WireGuard가 있는 이상 이중투자 — 비채택.)

> 하이브리드(DB를 클러스터 밖 VM에 두는 안)였다면 앱→DB 홉이 클러스터를 벗어나 WireGuard가 덮지 못했고 PG-SSL이 필요했다. **in-cluster 결정이 이 문제를 소멸시켰다** — 두 결정이 연동돼 있다.

### 6.3 백업 / DR

- **etcd 스냅샷 → S3** (master ×1 SPOF 보완). ArgoCD/GitOps가 복구를 돕지만 Git 밖 상태가 있어 스냅샷을 대체하지 못한다.
- **PG** = CNPG barman-cloud → S3 (WAL 아카이빙 + PITR)
- **ES** = 스냅샷 → S3, 매일 14시·02시, 14일 보존. **Glacier 계열 전환 금지**(도구 관리 repository 객체를 임의 이동하면 복구 저장소가 손상된다).
- **Kafka** = RF=3 + PV. S3는 Kafka PV를 대체하지 않는다. 재크롤 가능한 토픽과 그렇지 않은 토픽(클릭스트림)을 구분해 보존 정책을 정한다.
- **백업 자격증명 격리** — 앱 ServiceAccount에 백업 bucket 쓰기 권한을 주지 않는다. 백업 주체는 오퍼레이터(CNPG)의 전용 ServiceAccount다.

**복구 순서**: Terraform/Ansible로 노드 복구 → K8s + ArgoCD 복구 → 오퍼레이터 설치 → S3에서 PG PITR 복구 → ES 스냅샷 복원(또는 PG에서 재색인) → Redis 재생성 → 앱 재배포 → 로그인·예산·냉장고·레시피·가격비교 smoke test.

### 6.4 Secret = External Secrets Operator

현행은 `ansible/secrets.yml` + fb-app-ai에 상주하는 `.env`다. GitOps로 가면 이 모델이 성립하지 않는다.

- **ESO 선택 이유**: `ExternalSecret` CR은 그대로 두고 **백엔드만 교체**하면 EKS로 이식된다(온프렘 백엔드 → AWS Secrets Manager + IRSA). 회전·감사로그도 백엔드가 제공한다.
- Sealed Secrets는 복호키가 클러스터에 묶여 클러스터 재구축·EKS 이식 시 전량 재봉인이 필요하고 회전이 수동이라 비채택.

---

## 7. EKS 이식성 감사

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
| StorageClass | 🟡 | `openebs-lvm` → `gp3` | **SC 이름 하드코딩 금지** (§5.2) |
| 존 분산 | 🟡 | 노드 라벨 → 진짜 AZ | **topologySpreadConstraints 사용** (§2.3) |
| TLS 인증서 | 🟡 | 로컬 CA → ACM/Let's Encrypt | **cert-manager를 온프렘부터 도입**, Issuer만 교체 |
| 레지스트리 | 🟡 | Harbor → ECR | 이미지 참조를 kustomize `images:`로 외부화 |
| ES `vm.max_map_count` | 🟡 | 노드 sysctl → 관리형 노드그룹 launch template user-data | 노드 부트스트랩 항목으로 문서화 |
| **MetalLB** | 🔴 교체 | AWS Load Balancer Controller (NLB) | **LoadBalancer Service는 GW 1개만** (§3.3) |
| **Secret 백엔드** | 🔴 교체 | ESO 백엔드 → Secrets Manager + IRSA | ESO 채택으로 CR은 보존 (§6.4) |
| **RWX 볼륨** | 🔴 비용 | EFS 필요 (유료·고지연) | **RWX 의존 금지** — 오브젝트 스토리지로 우회 (§5.4) |
| **LGTM 저장소** | 🔴 재구성 | 로컬 PV였다면 전면 재구성 | **오브젝트 스토리지 백엔드로 구성** (§5.3) |

**이식성을 코드로 만드는 장치**: ArgoCD `overlays/onprem` · `overlays/eks` 2개 오버레이를 처음부터 만든다. base 매니페스트는 공통이고, 위 🟡🔴 항목만 오버레이에서 다르다. "EKS로 갈 수 있다"가 문서상의 주장이 아니라 **레포에 실재하는 디렉터리**가 된다.

---

## 8. 관측

세 소스가 서로 다른 층을 답하고, 대시보드는 Grafana 한 곳에서 만든다.

| 소스 | 층 | 신호 |
|---|---|---|
| **Hubble** (Cilium) | 네트워크 L3/4 | flow 로그(허용/DROPPED), 정책 판정, 서비스 의존맵, DNS 질의 |
| **Istio telemetry** | 앱 요청 (RED) | 라우트별 RPS·p50/p99·5xx율 |
| **LGTM** | 저장·시각화 | Mimir·Loki·Tempo·Grafana |

```
[Hubble /metrics] · [Istio /metrics] · [app /metrics]
      └→ Alloy(스크레이프) ─remote_write→ Mimir ─PromQL→ Grafana
```

- Hubble·Istio 모두 Prometheus 포맷 `/metrics`를 노출하므로 **Alloy 스크레이프 대상에 추가만** 하면 된다. 신규 스택 0.
- **LGTM은 in-cluster**로 이전하되 저장소는 MinIO(§5.3). Grafana·Alertmanager 설정은 현행 자산을 그대로 승계한다.
- 🔴 **Alertmanager Slack 웹훅 주의** — 현행 ansible 롤에서 `--limit monitoring`을 그냥 돌리면 웹훅이 삭제되는 함정이 있었다. K8s 이전 시 웹훅은 **ESO로 관리**해 이 계열 사고를 구조적으로 없앤다.
- **mTLS 활성 후 Hubble의 앱 트래픽 시야는 L3/4까지**(페이로드는 암호화). L7은 Istio 텔레메트리 담당 — 이 역할 분리를 발표에서 먼저 밝힌다.
- **네트워크 신호의 서비스 가치**: PG로의 flow 폭증(읽기 폭주 조기 탐지 — mealplan 커넥션 풀 포화 같은 패턴) · DROPPED flow 급증(정책 위반·스캔) · DNS 이상(NXDOMAIN 급증). 이 시계열은 최저가 알림에 쓰는 **통계 이상탐지에 그대로 먹여** 자동 알림으로 확장 가능하다 — AI 파트와 인프라 파트 발표를 잇는 다리.

---

## 9. 컷오버 계획

**원칙**: 현행 compose 서비스를 죽이지 않고, **리스크 오름차순**으로 옮긴다. 각 단계는 독립 롤백 가능하고, 단계마다 발표용 중간 산출물이 나온다.

| 단계 | 내용 | 롤백 | 산출물 |
|---|---|---|---|
| **P0 기반** | Host B 증설 · 5노드 부팅 · Cilium(+WireGuard) · Istio · MetalLB · OpenEBS · MinIO · cert-manager · ESO · ArgoCD | 클러스터 폐기 (현행 무영향) | 클러스터 · 오버레이 구조 |
| **P1 앱** | FastAPI 9개 + Gateway 배포. **DB는 아직 fb-data VM 참조** (selector 없는 Service + EndpointSlice). 검증 후 유입을 nginx → Istio GW로 전환 | 유입을 nginx로 되돌림 | mTLS · L7 메트릭 · **HPA** |
| **P2 Kafka** | Strimzi 3노드 · KafkaTopic CRD로 토픽 재생성 · 컨슈머/CronJob 전환 | 컨슈머를 VM Kafka로 되돌림 | **KEDA lag 스케일링** |
| **P3 Redis** | 비영속 캐시 → 무손실 전환 | 엔드포인트 되돌림 | |
| **P4 ES** | ECK 3노드 신규 구축 → **PG에서 재색인**(PGSync 포함) → 무손실 전환 | 구 ES로 되돌림 | ECK 오퍼레이터 |
| **P5 PG** | CNPG 구축 → 논리복제로 따라잡기 → **짧은 전환창**(유일한 다운타임) | 구 PG로 되돌림(전환창 내) | **CNPG 페일오버 데모** |
| **P6 정리** | fb-data VM 해체 · LGTM in-cluster 이전 · RAM 회수 | — | 최종 토폴로지 |

**컷오버 체크리스트 (사고 이력 기반)**
- [ ] Kafka: `auto.create.topics.enable=false` 확인 · KafkaTopic CRD 유일경로 · **PV 실사용 확인**(`describe`로 마운트 검증)
- [ ] Cilium: `socketLB.hostNamespaceOnly=true` · mTLS 실동작 확인(평문 캡처로 반증)
- [ ] NetworkPolicy: CoreDNS(53)·istiod(15012) egress 예외
- [ ] ES: 노드 `vm.max_map_count=262144` (ECK 기동 전)
- [ ] 각 단계 완료 시 백업 경로 동작 확인 (백업 없는 상태로 다음 단계 진입 금지)

---

## 10. 결정 대기 (임의 확정 금지)

1. **Cilium 라우팅 모드 최종** — VXLAN 유지 vs 실측 후 native 전환 (§3.2)
2. **MetalLB IP 풀 대역** — 공유기 DHCP 할당 범위 확인 후 확정 (예: `192.168.0.200~220`)
3. **이전 트리거 시점** — 호스트 B 확보 시점과 9주 타임라인의 정합 (5인 역할분담·타임라인이 미정 상태)

---

## 11. 팀장 계획서(`k8s-infra-plan.md`) 대비 변경점

| 항목 | 계획서 | 이 문서 | 이유 |
|---|---|---|---|
| 데이터 티어 | in-cluster (§8) | **동일 채택** + 동적 프로비저닝 명시 | 기존 정본(`design.md §8.4`의 하이브리드)을 뒤집는 결정 → ADR 후보 |
| 스토리지 | 미기재 | **OpenEBS LVM LocalPV 확정** | StatefulSet 전제인데 CSI 결정이 없었음 |
| Kafka | **누락** | Strimzi 3노드 RF=3 · PV · auto-create 금지 | 파이프라인 중심 서비스인데 §8에 없었음 |
| DB 홉 암호화 | ❓ 미정 | **WireGuard 켬** | in-cluster 확정으로 전 구간 커버 가능해짐 |
| EKS 이식성 | 미기재 | **§7 신설** | 온프렘 K8s는 EKS로 가는 관문이라는 전제 |
| MetalLB | 채택 | 채택 + **LoadBalancer 1개 제한 규칙** | EKS 이식 시 유일한 필수 교체 대상 |
| Secret | 미기재 | **ESO** | GitOps 전환의 전제조건 |
| LGTM | 스택 변경 없음 | **in-cluster + MinIO 백엔드** | 로컬 PV면 EKS 이식 시 전면 재구성 |
| 관측 대상 | Hubble·Istio·app | 동일 + **Alertmanager 웹훅 ESO 관리** | 현행 ansible 롤의 웹훅 삭제 함정 해소 |
| socketLB 함정 | 미기재 | **§3.1 명시** | Cilium+Istio 조합의 전제조건 |
| Harbor·CI | 미기재 | **클러스터 밖 VM 명시** | 클러스터 장애 시 복구 수단 보존 |

계획서의 다음 항목은 **그대로 채택**했다: master ×1 근거 · VIP 불필요 · VXLAN 시작 · MetalLB L2 · Gateway API=Istio · **sidecar** · DB 메시 제외 · Job 사이드카 제외 · Hubble · FQDN egress · CoreDNS 플로우 · vmbr1 미사용.

---

## 12. 발표 서사 — "쿠버네티스의 꽃"

네트워킹·메시·관측이 뿌리와 줄기라면, 꽃은 **선언한 상태를 시스템이 스스로 유지하고 부하에 맞춰 몸집을 바꾸는 것**이다. 우리는 이 명분을 **실측과 실제 사고**로 갖고 있다 — 만들어낸 시나리오가 아니다.

**🌸 HPA — 수직의 끝을 실측으로 보고 수평으로 풀었다**
account 로그인이 bcrypt 때문에 CPU를 0.75→2.0코어로 올린 뒤에도 **100VU에서 한도의 98% 포화**(PG active 커넥션 0으로 DB 병목이 아님을 런타임 메트릭으로 확인). 수직 확장의 한계가 숫자로 찍혀 있다. HPA(목표 사용률 60~70%)로 replica 확장 → **"부하테스트 → 병목 발견 → 수직 한계 실증 → 수평 해결"** 완결 서사.

**🌸 KEDA — 스파이크에만 키우고 평시엔 0으로 잠든다**
우리 트래픽은 예측 가능한 스파이크형이다: 식사 피크(11–12·17–18시) · 오아시스 딜 크롤(15:05·17:05) · 최저가 알림 fan-out(멘토가 지목한 다자간 트래픽). Kafka lag 트리거로 컨슈머를 0↔N 스케일(**ScaledObject 초안이 `deploy/k8s/retail-ingest.yaml`에 이미 존재**), 예측 피크는 cron 스케일러로 선제 확장. **scale-to-zero는 학생 예산에서 유휴 리소스를 실제로 반납**하므로 "규모 대비 과설계" 반박을 정면으로 뒤집는다.

**🌸 자가치유 — 우리가 실제로 겪은 장애의 재현**
시연: 워커 노드 강제 다운 → topologySpread + PDB로 파드가 살아있는 호스트로 재스케줄, 서비스 무중단. 근거: **호스트 급사 3회 · pgsync 16시간 무감지 크래시루프.** master를 호스트 B에 둔 덕에 *실제로 일어난 장애 모드*에서 이 데모가 성립한다.

**🌸 오퍼레이터 — CRD로 도메인 지식을 코드화**
CNPG primary 강제 종료 → 자동 페일오버 → 앱이 `-rw` Service로 무중단 재연결. 스토리지 복제 대신 **DB 자체 복제 + 오퍼레이터 페일오버**를 고른 §5.2 결정이 여기서 회수된다.

**🌸 GitOps + 카나리 — 메시 투자의 회수 지점**
ArgoCD + Istio 트래픽 스플릿으로 피크타임 배포를 10% 카나리 → 5xx율(Istio 텔레메트리) 기준 자동 롤백. **이게 있어야 sidecar 채택 명분이 완성된다** — mTLS+관측만으로는 절반이고, 카나리가 "왜 굳이 sidecar까지 갔는가"의 최종 답이다.

**🌸 이식성 — 이 클러스터는 종착지가 아니다**
`overlays/onprem` ↔ `overlays/eks` 2-오버레이로 "EKS로 갈 수 있다"를 레포에 실재하는 코드로 보여준다(§7). 온프렘에서 배운 것이 클라우드에서 그대로 쓰인다는 것이 이 프로젝트의 마지막 카드.
