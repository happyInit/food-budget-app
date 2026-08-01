# Zero-Trust NetworkPolicy — 트래픽 흐름 (발표용 정리)

> 월 식비 밀플래닝 K8s 인프라 · Cilium + Istio · tier-1~4 적용 완료(2026-08-01)
> 정본 스펙 = `docs/mp_k8s_infra_object_spec.md §10.3·§10.4` · 롤아웃 = mealplanning-config PR #74–79
> **이 문서는 발표용 서술 정리** — 정확한 규칙 정본은 위 object_spec.

---

## 0. 한 장 요약 (thesis)

> **클러스터의 모든 파드는 원래 서로 자유롭게 통신한다. 우리는 그걸 뒤집었다.**
> 명시적으로 허용한 출발지·포트만 통과하고 **나머지는 전부 차단(default-deny)**.
> data·pipeline 두 계층까지 잠가 **서비스 전 구간을 zero-trust**로 전환했다.

핵심 반전: **"막은 것"이 규칙이고 "뚫은 것"이 예외다.** 아래 허용 목록은 짧고, 차단은 그 나머지 전부다.

---

## 1. 개념 — DEFAULT ALLOW → ZERO TRUST

| | DEFAULT ALLOW (기존 K8s 기본) | ZERO TRUST (우리 적용) |
|---|---|---|
| 파드 간 통신 | **전부 허용** | 정책이 허용한 것만 |
| 한 곳 침해 시 | DB·타 서비스로 **측면 이동 자유** | 갈 수 있는 곳이 미리 정해져 격리 |
| 규칙의 성격 | 막을 것을 하나씩 blacklist | **허용할 것만 whitelist, 나머지 deny** |

> NetworkPolicy는 "화이트리스트 스위치"다 — **파드를 선택하는 정책이 하나라도 생기는 순간, 명시하지 않은 것은 전부 차단**된다. (`object_spec §10.1`)

---

## 2. 클러스터 구조 — 3개 네임스페이스 + 트러스트 경계

| ns | 역할 | 메시(Istio) | 경계 수단 |
|---|---|---|---|
| **app** | 서비스 계층 (frontend + backend ×11) | ✅ **STRICT mTLS** | PeerAuthentication + NetworkPolicy |
| **data** | 데이터 스토어 (Redis·ES·PG·Kafka) | ❌ 메시 밖 | **NetworkPolicy가 유일 경계** |
| **pipeline** | 수집·가공 (컨슈머·크롤러·배치) | ❌ 메시 밖 | **NetworkPolicy가 유일 경계** |

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

- **GitOps**: mealplanning-config → ArgoCD.
- 🔴 **data·pipeline 정책 앱은 수동 sync** — default-deny는 복제·크롤·컨슈머를 **조용히** 끊을 수 있어 "머지=강제 적용"이 위험. → sync 후 **`cilium monitor --type drop`으로 예상 밖 드롭 0 확인**하는 게이트를 두고 다음 단계로.

---

## 8. 구현 기술

| 계층 | 도구 | 역할 |
|---|---|---|
| L3/L4 + FQDN egress | **Cilium** (NetworkPolicy + CiliumNetworkPolicy) | 파드 격리 · DNS 학습 기반 외부 허용 |
| mTLS (app ns) | **Istio** (STRICT PeerAuthentication) | 서비스 간 암호화·신원 |
| Kafka 접근제어 | **Strimzi** (`networkPolicyPeers`) | 9092를 app·pipeline·keda로 제한 |
| 관측 | **Prometheus** | app=`:15020` merged / data·pipeline=파드 포트 직접 |

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
