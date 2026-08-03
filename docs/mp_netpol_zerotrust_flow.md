# Zero-Trust NetworkPolicy — 트래픽 흐름 (발표용 정리)

> 월 식비 밀플래닝 K8s 인프라 · Cilium + Istio · tier-1~4 적용 완료(2026-08-01)
> 정본 스펙 = `docs/mp_k8s_infra_object_spec.md §10.3·§10.4` · 롤아웃 = mealplanning-config PR #74–79
> **이 문서는 발표용 서술 정리** — 정확한 규칙 정본은 위 object_spec.

---

## 0. 한 장 요약 (thesis)

> **클러스터의 모든 파드는 원래 서로 자유롭게 통신한다. 우리는 그걸 뒤집었다.**
> 명시적으로 허용한 출발지·포트만 통과하고 **나머지는 전부 차단(default-deny)**.
> app·data·pipeline·observability **워크로드 4계층**을 잠갔다.

핵심 반전: **"막은 것"이 규칙이고 "뚫은 것"이 예외다.** 아래 허용 목록은 짧고, 차단은 그 나머지 전부다.

> ⚠️ **범위를 정확히 말할 것** — "클러스터 전체"가 아니라 **워크로드 계층**이다.
> 플랫폼·오퍼레이터 ns 13개(파드 75개)에는 아직 정책이 없다. 이건 빠뜨린 게 아니라
> **후순위로 둔 판단**이고, 근거와 다음 순서는 [§9](#9-적용-범위-결정-어디까지-잠글-것인가--2026-08-03) 에 있다.
> 발표에서 "전부 잠갔다"고 말하면 ns 목록 한 번에 뒤집힌다. **"워크로드 계층은 잠갔고,
> 플랫폼 ns 는 이유가 있어 후순위"** 가 정확하고 더 좋은 답이다.

---

## 1. 개념 — DEFAULT ALLOW → ZERO TRUST

| | DEFAULT ALLOW (기존 K8s 기본) | ZERO TRUST (우리 적용) |
|---|---|---|
| 파드 간 통신 | **전부 허용** | 정책이 허용한 것만 |
| 한 곳 침해 시 | DB·타 서비스로 **측면 이동 자유** | 갈 수 있는 곳이 미리 정해져 격리 |
| 규칙의 성격 | 막을 것을 하나씩 blacklist | **허용할 것만 whitelist, 나머지 deny** |

> NetworkPolicy는 "화이트리스트 스위치"다 — **파드를 선택하는 정책이 하나라도 생기는 순간, 명시하지 않은 것은 전부 차단**된다. (`object_spec §10.1`)

---

## 2. 클러스터 구조 — 4개 네임스페이스 + 트러스트 경계

| ns | 역할 | 메시(Istio) | 경계 수단 |
|---|---|---|---|
| **app** | 서비스 계층 (frontend + backend ×11) | ✅ **STRICT mTLS** | PeerAuthentication + NetworkPolicy |
| **data** | 데이터 스토어 (Redis·ES·PG·Kafka) | ❌ 메시 밖 | **NetworkPolicy가 유일 경계** |
| **pipeline** | 수집·가공 (컨슈머·크롤러·배치) | ❌ 메시 밖 | **NetworkPolicy가 유일 경계** |
| **observability** | 관측 스택 + 내부 게이트웨이 + **MinIO** | ❌ 메시 밖 | NetworkPolicy + CiliumNetworkPolicy(엔티티) |

> 🔴 **observability 는 2026-08-03 에 뒤늦게 합류했다.** 원래 티어 계획(워크로드 tier-1~4)에
> 없었는데, 같은 날 **PG 온사이트 백업이 MinIO 에 DB 전체 논리 덤프를 넣기 시작**하면서
> "아무 ns 의 아무 파드나 붙을 수 있는 곳에 DB 사본이 있다"가 됐다. 계획의 구멍이었다(§9).

> **메시 밖(data·pipeline)** = 사이드카가 없어 kubelet probe가 파드 IP로 직접 온다 → 정책에 **노드 ipBlock(192.168.0.0/24)** 예외가 필요하고, STRICT mTLS는 무관하다. netpol만이 이 계층의 L3/L4 경계다.

---

## 3. 유입 경로 (North-South) — 정문은 하나다

```
인터넷/사용자
   │  HTTPS (아웃바운드 터널)
   ▼
Cloudflare Tunnel (mp-app)
   │
   ▼
Gateway (Istio · MetalLB .14, 공개 LB 전용)
   │  mTLS
   ▼
app ns  (frontend / backend)
```

- ✅ 외부에서 들어오는 **유일한 경로 = Cloudflare Tunnel → Gateway**.
- ⛔ 인터넷에서 **어떤 파드로도 직접 진입 불가** (Gateway 강제).

---

## 4. 네임스페이스별 허용 / 차단 (핵심)

> 방향 개념: **ingress = 나한테 들어오는 트래픽 / egress = 내가 나가는 트래픽.**
> 같은 연결 하나가 부르는 쪽엔 egress, 받는 쪽엔 ingress — 그래서 양쪽 다 열어야 통한다.

### 4.1 app ns — frontend

| | 허용 ✅ | 차단 ⛔ |
|---|---|---|
| ingress | Gateway만 | 그 외 전부 |
| egress | **DNS만** | backend · data · 인터넷 **전부** |

> 프론트가 털려도 갈 곳이 DNS뿐 — 최고의 보안 진술. 브라우저는 백엔드를 Gateway로 직접 부르지, frontend 파드를 거치지 않는다(백엔드 호출 0).

### 4.2 app ns — backend ×11

`account` · `chat` · `mealplan` · `notify` · `ocr` · `operations` · `pantry` · `price` · `recipe` · `recipebook` · `video`

| | 허용 ✅ | 차단 ⛔ |
|---|---|---|
| ingress | Gateway · 같은 ns backend(서로 API 호출) · Prometheus `:15020` | 그 외 |
| egress | data 4스토어 · DNS · istiod `:15012` · (일부만 외부 FQDN, §5) | 다른 ns · 임의 인터넷 · kube-apiserver · FQDN 목록 밖 |

> STRICT mTLS라 Prometheus는 평문 `:9090` 직스크레이프가 막혀 **사이드카 merged `:15020`**로만 긁는다.
> 외부 API를 쓰는 파드는 **account·ocr·chat·video** 뿐 → 이들만 FQDN egress 허용.

### 4.3 data ns — 스토어 4종 (tier-3, 스토어별 default-deny)

| 스토어 | ingress 허용 ✅ (지정 포트) | egress 허용 ✅ |
|---|---|---|
| **Redis** (+Sentinel) | backend·pipeline `:6379/:26379` · intra 복제·Sentinel · operator · Prom `:9121` · node(probe) | DNS · intra |
| **Elasticsearch** | backend·pipeline·PGSync `:9200` · intra `:9300` · ECK op · node | DNS · intra `:9300` |
| **PostgreSQL** | pooler·backend·pipeline·PGSync `:5432` · cnpg-op `:8000` · Prom `:9187` · node | DNS · intra · **S3 백업 · kube-apiserver** (FQDN) |
| **Kafka** | `:9092` = `peers[app·pipeline·keda]`만 · broker `:9090/:9091`·op `:8443`(Strimzi 자동) | — |

**차단 ⛔** (중요):
- **스토어끼리도 차단** — Redis가 뚫려도 PG로 못 간다.
- data → app ns 차단 · data → 인터넷 차단 (**PG→S3 백업만 예외**).
- 지정 출처가 아니면 어떤 스토어에도 접속 불가.

### 4.4 pipeline ns — 수집·가공 (tier-4)

컨슈머(refiner) · 크롤러(kurly·oasis·10000recipe) · AI배치(bedrock·chat-insights) · pruner/배치

| | 허용 ✅ | 차단 ⛔ |
|---|---|---|
| ingress | **Prometheus만** (metrics) | **그 외 전부** (probe·Service 없음, KEDA는 Kafka lag polling) |
| egress | DNS · Kafka · PG(pg-rw) · ES · Redis · (크롤·AI만 외부 FQDN, §5) | **app ns · kube-apiserver · 임의 인터넷** |

> 크롤러 = 외부 HTML/브라우저를 다루는 **최고위험 파드**. 털려도 Kafka·PG·지정 사이트 외엔 못 나가고, app·apiserver로 **측면 이동 불가**.
> **2-class 설계**: 전 워크로드가 동일 이미지·동일 시크릿이라 pod별 스토어 격리는 의미 없음 → 경계는 **"pipeline ↔ 데이터플레인 밖"**.

---

## 5. 외부 egress — 나가는 곳도 화이트리스트 (Cilium FQDN)

표준 NetworkPolicy는 IP/CIDR만 다룬다. 외부 API·백업 대상은 CDN/anycast 뒤라 IP가 계속 바뀌어 **"IP 목록으로 허용"이 불가능** → Cilium `toFQDNs`가 **DNS 응답을 학습**해 그 IP만 TTL 동안 허용.

| 출발 (ns / 파드) | 허용 FQDN | 용도 |
|---|---|---|
| app / **account** | kauth.kakao.com · kapi.kakao.com · oauth2.googleapis.com · openidconnect.googleapis.com | 소셜 로그인 (카카오·구글 OAuth) |
| app / **ocr** | generativelanguage · aiplatform · oauth2 `.googleapis.com` | 영수증 OCR (Gemini/Vertex) |
| app / **chat** | generativelanguage.googleapis.com | 챗봇 (Gemini) |
| app / **video** | aiplatform · oauth2 · generativelanguage `.googleapis.com` · www.youtube.com | 영상 레시피 추출 (Vertex + oembed) |
| data / **pg** | s3.ap-northeast-2.amazonaws.com · kube-apiserver(toEntities) | PG 백업(barman WAL) · 인스턴스매니저 |
| pipeline / **poller-kurly** | `*.kurly.com` | 마켓컬리 크롤(Playwright, CDN 서브도메인 포함) |
| pipeline / **oasis** ×4 | www.oasis.co.kr | 오아시스 크롤 |
| pipeline / **recipe·review** | www.10000recipe.com | 만개의레시피 크롤 |
| pipeline / **sentiment·summarize** | bedrock-runtime.ap-northeast-2.amazonaws.com | AWS Bedrock(리뷰 감정·요약) |
| pipeline / **chat-insights** | generativelanguage.googleapis.com | 대화 리포트(Gemini) |

- 🔴 각 FQDN 정책엔 **DNS L7 가시성 규칙**이 동봉돼야 학습 성립.
- ⚠️ 파드가 클러스터 DNS를 **우회**(예: chromium DoH)하면 학습할 게 없어 차단 — 컬리 크롤 감시 포인트.
- **왜 실질적인가**: Gemini·Bedrock은 유료 API → 키 유출 시 실제 과금. 크롤 FQDN은 크롤러 탈취 시 **지정 사이트 외 exfil 차단**.

---

## 6. "실제로 막은 것" — 숨어있는 deny (⭐ 발표 핵심 슬라이드)

허용 화살표만 보면 널널해 보이지만, **그리지 않은 것이 전부 차단**이다. 대표 차단 경로:

| 막힌 경로 | 뚫리면 벌어질 일 → 우리가 막음 |
|---|---|
| frontend ⇏ 모든 backend | 프론트 탈취 → API 남용 **(불가, egress DNS뿐)** |
| backend ⇏ pipeline·apiserver·임의 인터넷 | 백엔드 측면 이동·데이터 유출 **(차단)** |
| **스토어 ⇏ 스토어** (Redis⇏PG 등) | 캐시 탈취 → DB 직행 **(차단)** |
| pipeline ⇏ app ns·apiserver | 크롤러(최고위험) 탈취 → 내부 장악 **(격리)** |
| 미허용 출처 ⇏ data·pipeline | 스토어·파이프라인은 지정된 자만 접속 |
| 인터넷 ⇏ 파드 직접 | 정문(Gateway) 우회 진입 **(불가)** |

> **한 줄**: "거의 다 막고, 그린 화살표(허용)만 예외로 뚫었다."

---

## 7. 롤아웃 순서 + 운영 게이트

| 티어 | 범위 | 방식 |
|---|---|---|
| **tier-1** | app ns STRICT mTLS + 공통 default-deny 예외(DNS·istiod·probe) | PeerAuthentication |
| **tier-2** | app backend 11 + 외부 FQDN(account·ocr·chat·video) | 서비스별 netpol |
| **tier-3** | data 스토어 4 (Redis→ES→PG→Kafka 순, 하나씩) | 스토어별 default-deny |
| **tier-4** | pipeline (ingress 봉쇄 → egress + FQDN) | ns 전체 |
| **tier-5** | observability (ingress default-deny + 게이트웨이 개방 + 엔티티) | ns 전체 (2026-08-03) |

- **GitOps**: mealplanning-config → ArgoCD.
- 🔴 **data·pipeline·observability 정책 앱은 수동 sync** — default-deny는 복제·크롤·컨슈머를 **조용히** 끊을 수 있어 "머지=강제 적용"이 위험. → sync 후 **`cilium monitor --type drop`으로 예상 밖 드롭 0 확인**하는 게이트를 두고 다음 단계로.

### 7.1 🔴 tier-5 에서 실제로 밟은 함정 — `ipBlock` 은 생각한 그것이 아니다 (2026-08-03)

observability 1차 적용이 **내부 도구 7종을 통째로 끊었다**(argo·grafana·minio·loki·harbor·jenkins·sonarqube 전부 무응답). 원인은 규칙 누락이 아니라 **전제 오류**였다.

```
10.244.3.143 (world) <> observability/mp-gw-internal-istio:443  Policy denied DROPPED (SYN)
```

**Cilium 은 패킷을 IP 가 아니라 신원(identity)으로 판정한다.** 그래서 표준 netpol 의 `ipBlock` 은
사실상 **cluster-external(`world`) 트래픽에만** 걸린다. MetalLB L2 로 들어온 LoadBalancer 트래픽은
Cilium 이 노드의 라우터 IP(`cilium_host`, **파드 CIDR 대역**)로 SNAT 해서 넘기므로
`ipBlock: 192.168.0.0/24` 에 **절대 매칭되지 않는다.**

같은 착오가 두 곳을 더 덮고 있었다 — 둘 다 `ipBlock` 으로는 못 연다:

| 소스 | 실제 신원 | 막히면 |
|---|---|---|
| kubelet probe | `host` | probe 실패 → 파드가 안 뜬다 |
| kube-apiserver → prometheus-operator webhook | `kube-apiserver` | **ServiceMonitor·PrometheusRule 생성 전면 거부** |
| CNPG 인스턴스매니저 → apiserver | `kube-apiserver` | 같은 날 `pg-pooler` 가 이걸로 CrashLoop |

🔴 **왜 안 잡혔나** — 기존 `netpol-backend.yaml`(app ns)이 같은 `ipBlock` 관례로 잘 돌고 있었다.
그런데 거기서 통한 이유는 **kubelet probe 가 로컬 호스트에서 오고 Cilium 이 localhost 를 기본
허용**하기 때문이지, `ipBlock` 이 매칭돼서가 아니었다. **우연히 맞은 것을 근거로 삼은 것**이 뿌리다.

**교훈 3가지**
1. 인프라 계열 소스(`host`·`remote-node`·`kube-apiserver`)는 **CiliumNetworkPolicy 의 엔티티**로 연다.
   표준 netpol 로는 표현 자체가 안 된다. (EKS 이식 시 다시 써야 하는 부분 = `object_spec §10.4`)
2. **문 여는 정책을 default-deny 보다 먼저** 넣는다. 순서가 뒤집히면 그 순간 끊긴다.
3. `pg-pooler` 사례처럼 **기존 파드는 conntrack 으로 연명**한다 → 정책 결함이 무증상으로 잠복하다가
   **재생성 시점(드레인·롤아웃)에만** 터진다. "지금 멀쩡함"은 검증이 아니다.

---

## 8. 구현 기술

| 계층 | 도구 | 역할 |
|---|---|---|
| L3/L4 + FQDN egress | **Cilium** (NetworkPolicy + CiliumNetworkPolicy) | 파드 격리 · DNS 학습 기반 외부 허용 |
| mTLS (app ns) | **Istio** (STRICT PeerAuthentication) | 서비스 간 암호화·신원 |
| Kafka 접근제어 | **Strimzi** (`networkPolicyPeers`) | 9092를 app·pipeline·keda로 제한 |
| 관측 | **Prometheus** | app=`:15020` merged / data·pipeline=파드 포트 직접 |

---

## 9. 적용 범위 결정 — 어디까지 잠글 것인가 (2026-08-03)

### 9.1 질문

*"원칙대로면 전부 다 잠가야 하는 것 아닌가? 왜 워크로드 ns 만 했나?"*

**원칙적으로는 맞다.** 지금 상태는 의도적으로 부분 적용이고, 그 판단을 여기 기록한다.

### 9.2 왜 이렇게 됐나 — 솔직한 경위

롤아웃 계획(§7)이 **워크로드 티어** 축으로만 짜여 있었다(frontend → backend → data → pipeline).
플랫폼·오퍼레이터 ns 는 *"안 하기로 결정"* 한 게 아니라 **범위를 정한 적이 없었다.**

그 구멍의 증거가 `observability` 다 — 티어 계획에 없다가, MinIO 에 DB 덤프가 들어가기 시작한
2026-08-03 에야 "여긴 왜 정책이 0개지?" 로 발견됐다. **빠져 있던 건 정책이 아니라 범위 결정이다.**

### 9.3 현황 실측 (2026-08-03)

| | ns | 파드 |
|---|---|---:|
| ✅ 적용 | app · data · pipeline · observability · argocd | **77** |
| ⬜ 미적용 | 13개 (kube-system·istio-system·metallb-system·openebs·cost·argo-rollouts·cert-manager·external-secrets·keda·cnpg-system·elastic-system·redis-operator-system·strimzi-system) | **75** |

**단, 미적용 75개가 전부 통제 가능한 게 아니다:**

| ns | 파드 | hostNetwork | netpol 적용 가능 |
|---|---:|---:|---:|
| kube-system | 37 | **21** | 16 |
| metallb-system | 6 | **5** | 1 |
| 나머지 11개 | 32 | 0 | 32 |
| **합계** | **75** | **26** | **49** |

🔴 **hostNetwork 파드에는 NetworkPolicy 가 사실상 안 걸린다.** 파드 IP 가 아니라 노드의 네트워크
네임스페이스를 쓰므로 Cilium 이 `host` 신원으로 본다 — §7.1 에서 밟은 것과 같은 메커니즘이다.
cilium·cilium-envoy·node-exporter·metallb-speaker 가 여기 해당한다.
→ "kube-system 을 잠갔다"는 **37개 중 16개**를 잠갔다는 뜻이다. 체감보다 훨씬 적다.

### 9.4 결정

**플랫폼·오퍼레이터 ns 는 후순위로 둔다.** 근거 둘:

1. **실익이 낮다** — 미적용 75 중 26(35%)은 netpol 로 통제 자체가 안 되고, 그 대부분이 kube-system 이다.
2. **위험이 높다** — 오퍼레이터는 apiserver 를 클러스터 전역으로 watch 한다. 정책을 잘못 걸면
   **파드는 Running 인데 CR 이 반영 안 되는 상태**가 되고 알람도 안 울린다. 같은 날 `pg-pooler` 가
   정확히 그 형태였다(§7.1). 오늘만 두 번 밟은 함정이 더 촘촘한 구간이다.

### 9.5 다음 순서 (착수 시)

값어치 순이지 난이도 순이 아니다.

| 순위 | 대상 | 왜 |
|---|---|---|
| ~~**1**~~ | ~~**`app → data` 포트 제한**~~ | ✅ **완료·검증(2026-08-03) — config #138.** ns 전체 무제한 → **5포트**(5432·6379·26379·9200·9092). 포트는 트래픽이 아니라 **설정**에서 뽑았다(§10). 닫힌 것 = **9300 ES transport**(클러스터 합류 경로)·9091/9090/8443 Kafka 내부·9114/9121 익스포터·8000 CNPG failsafe |
| **2** | **서비스별 `app → data`** | 위가 닫는 건 *"어느 포트"* 뿐이다. *"어느 서비스가"* 는 그대로라 **침해된 recipe 가 여전히 PG:5432 에 닿는다** — 감사 §7.2-3 이 실제로 지적한 건 이것이고, 아직 안 됐다 |
| **3** | observability **egress** | 현재 MinIO 만 잠겨 있다. 관측 스택이 인터넷으로 나갈 수 있다 = 유출 경로. Prometheus 는 설계상 전 ns·전 노드를 긁어야 해서 까다롭다 |
| **4** | 오퍼레이터 ns (`cert-manager`·`cnpg-system`·`external-secrets` 등) | 아래 9.5.1 참조 — **값어치가 생각보다 낮다** |
| **최후/미실시** | `kube-system` | hostNetwork 비중 57%로 실익 최소, 위험 최대 |

#### 9.5.1 🔴 `external-secrets` 를 2위에서 내린 이유 (자기 정정)

처음엔 *"ESO 는 모든 비밀을 읽으니 값어치 1위"* 로 2위에 뒀다. **그 근거가 틀렸다.**

ESO 의 백엔드는 **K8s provider** 다(`provider: kubernetes` · `url: kubernetes.default` ·
`remoteNamespace: fb-secrets`). 즉 비밀을 **apiserver 에 자기 SA 토큰으로 요청해서** 읽는다.

- 공격자가 ESO 파드를 장악하면 → **SA 토큰으로 apiserver 호출**. 그 경로는 netpol 로 못 막는다
  (막으면 ESO 자체가 죽는다).
- 반대로 **바깥에서 ESO 에 접속해도 얻을 게 없다** — 노출 포트가 8080(메트릭)·8081(헬스)·
  10250(웹훅)뿐이고 비밀 값을 돌려주는 포트가 없다.

→ **netpol 은 이 위험에 거의 무관하다.** "모든 비밀을 읽을 수 있다"는 **RBAC 문제**이고,
실제 완화 수단은 ① ClusterSecretStore 를 `fb-secrets` 로 고정(**이미 적용됨**)
② ESO 파드에 `exec` 할 수 있는 사람 제한(RBAC Phase 2) ③ AuthorizationPolicy 다.

**교훈**: 순위를 *"뚫리면 얼마나 아픈가"* 로 매기면 틀린다. **"이 수단이 그 위험을 실제로 줄이는가"**
로 매겨야 한다. 값어치가 큰 자산이라고 해서 모든 통제 수단이 거기에 효과적인 건 아니다.

### 9.6 아직 안 한 것 (인지된 갭)

- **AuthorizationPolicy 0건** — mTLS STRICT 로 *누구인지*는 증명하는데 *허용되는지*는 아무도 안 본다.
  제로트러스트의 L7 절반이 비어 있다 (status §7.2-3).
- **observability egress** — MinIO 외 전 컴포넌트가 인터넷 포함 어디로든 나갈 수 있다.
- `cost`(kubecost) 는 우선순위에서 뺐다 — 털려도 비용 지표뿐이다.

> **발표 시 답변**: *"워크로드 계층은 파드 단위 default-deny 로 잠갔고, 플랫폼 ns 는 hostNetwork
> 비중과 오퍼레이터 리스크를 이유로 후순위로 뒀습니다. 다음은 app→data 포트 제한과
> external-secrets 입니다."* — **범위를 알고 남긴 것과 모르고 빠뜨린 것은 다르다.**

---

## 10. 🔴 netpol 검증 방법 — 관측 도구가 답을 왜곡한다 (2026-08-03)

하루에 **세 번** 같은 종류로 틀렸다. 정책을 잘못 쓴 게 아니라 **"확인했다"의 근거가 틀렸다.**
netpol 작업의 실패는 대부분 여기서 나온다.

### 10.1 오늘 밟은 세 가지

| # | 무엇을 했나 | 왜 틀렸나 |
|---|---|---|
| ① | 기존 `netpol-backend.yaml` 이 `ipBlock: 192.168.0.0/24` 로 **잘 돌고 있으니** 같은 패턴을 썼다 | 거기서 통한 이유는 **kubelet probe 가 로컬 호스트에서 오고 Cilium 이 localhost 를 기본 허용**해서지, `ipBlock` 이 매칭돼서가 **아니었다.** 우연히 맞은 것을 근거로 삼았다 → 내부 도구 7종 중단(§7.1) |
| ② | Hubble 로 `app → data` 흐름을 떠서 사용 포트를 뽑으려 했다 | **`6379` 하나만** 나왔다. PG·ES 연결은 **풀링돼 상주**하므로 60초 버퍼에 새 flow 가 안 잡힌다. 그대로 썼으면 **5432·9200 을 빠뜨려 전면 장애** |
| ③ | 파드 안에서 `socket.create_connection` 으로 차단 여부를 확인했다 | app ns 는 **Istio 사이드카**가 있다. iptables REDIRECT 로 **로컬 envoy(:15001)와 먼저 핸드셰이크**가 성립해 상류 도달과 무관하게 성공한다. → **허용도 차단도 전부 오판** |

### 10.2 질문별로 맞는 도구가 다르다

| 묻고 싶은 것 | ✅ 써야 하는 것 | ❌ 쓰면 안 되는 것 |
|---|---|---|
| **무엇을 열어줘야 하나** (정책 설계) | **설정 파일**(`common/app-common.yaml`·서비스 오버레이·오퍼레이터 CR). 여기가 정본이다 | 짧은 트래픽 관측 — 상주·간헐 연결을 통째로 놓친다 |
| 지금 실제로 뭐가 연결돼 있나 | **conntrack** `cilium-dbg bpf ct list global` — 풀링된 장수명 연결까지 들어 있다 | Hubble flow 버퍼(수십 초) |
| 이 정책이 **실제로** 무엇을 허용하나 | **BPF 정책맵** `cilium-dbg bpf policy get <endpoint-id>` — Cilium 이 계산한 최종 허용 목록 | ArgoCD `Synced` 표시 · 매니페스트 읽기 |
| 적용 후 뭔가 깨졌나 | **Hubble** `--verdict DROPPED` (여기선 짧은 버퍼가 오히려 맞다 — "지금 깨지는가"를 묻는 것) | 파드 `Running` 여부 — 연결 실패는 파드를 안 죽인다 |
| 메시 안에서 포트 도달성 | 정책맵 / Hubble | **파드 내부 소켓 테스트** — 사이드카가 가로챈다 |

### 10.3 그래서 검증은 최소 두 갈래로 교차한다

`app → data` 포트 제한(#138)을 실제로 이렇게 확인했다:

1. **설정**에서 허용 목록을 도출 → 5개
2. **conntrack** 으로 현재 연결 확인 → 목록 밖 포트 **0개**
3. 적용 후 **Hubble DROPPED** → 전 노드 **0건**
4. 적용 후 **conntrack 재확인** → 적용 전엔 없던 **9200·26379 가 새로 성립** = 정책 통과 실증
5. **BPF 정책맵** → data identity 전부 5포트만, **`ANY` 항목 0개**

> 🔴 **`Synced`·`Healthy` 는 검증이 아니다.** 카나리 때도 `ignoreDifferences` 가 미적용을 Synced 로
> 위장했다. **항상 실물**(정책맵·HTTPRoute backendRefs·라이브 매니페스트)을 본다.

### 10.4 그리고 "지금 멀쩡함"도 검증이 아니다

같은 날 `pg-pooler` 가 증명했다 — apiserver egress 가 빠져 있었는데 **기존 파드는 conntrack 이
연결을 유지해 줘서 무증상**이었고, ArgoCD 가 CR 을 patch 해 파드가 새로 뜨는 순간에야 CrashLoop 했다.

**정책 결함은 재생성 시점(드레인·롤아웃·재스케줄)에만 드러날 수 있다.**
→ netpol 을 건 뒤에는 **해당 워크로드를 한 번 재시작시켜 보는 것**이 진짜 검증이다.

---

## 부록 A. ingress / egress 방향 (헷갈릴 때)

```
backend  ──접속──▶  PostgreSQL
   ▲                    ▲
 backend의 egress     PG의 ingress
 (내가 나가서 붙음)    (얘가 나한테 들어옴)
```

**하나의 연결 = 부르는 쪽엔 egress, 받는 쪽엔 ingress.**
완전히 막으려면 양쪽을 각각 열어야 한다:
- PG쪽: `ingress ← backend·pipeline 허용` (tier-3)
- backend/pipeline쪽: `egress → PG 허용` (tier-2·tier-4)
→ 이게 "대칭 짝". 어느 한쪽만 열면 안 통한다.

## 부록 B. 발표 슬라이드 구성 제안

1. 표지 — "Zero-Trust NetworkPolicy 적용기"
2. 문제 — K8s 기본은 DEFAULT ALLOW (§1 대비표)
3. 목표 — 명시 허용만, 나머지 deny (§0 thesis)
4. 구조 — ns 3개 + 메시 경계 (§2)
5. 유입 경로 — 정문 하나 (§3)
6. app 계층 허용/차단 (§4.1·4.2)
7. data 계층 — 스토어별 잠금 + 스토어끼리도 차단 (§4.3)
8. pipeline 계층 — 크롤러 격리 (§4.4)
9. 외부 egress — FQDN 화이트리스트 (§5)
10. ⭐ **"실제로 막은 것"** (§6 — 임팩트 슬라이드)
11. 롤아웃·운영 게이트 (§7)
12. 구현 기술 스택 (§8)
13. 마무리 — data·pipeline 전 구간 zero-trust 달성

> 각 `##` 섹션 ≈ 슬라이드 1장. 토폴로지 다이어그램(SVG)은 4~9번 배경으로.
