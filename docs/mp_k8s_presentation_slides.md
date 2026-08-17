# 발표 슬라이드 아웃라인 — 봉수 (0~8 + 시연)

> 복붙용. 각 슬라이드 = **제목 · 헤드라인(상단 큰 글씨) · 시각 본문(표/그림) · 🎤발표노트 · 🖼️비주얼 제안**.
> 원칙: **슬라이드엔 글씨 최소**(헤드라인+표), 디테일은 발표노트로. 상세 근거는 `docs/mp_k8s_presentation_bongsu.md`.
> 총 15장. through-line = **0번 EKS 이식성**(매 장 콜백).

---

## Slide 1 — 표지
**제목**: 온프렘 Kubernetes 구축 — **AWS(EKS) 이전을 염두에 둔 설계**
- 밀플래닝 인프라 · 발표자 봉수
- 🖼️ 비주얼: 클러스터 토폴로지 실루엣 or 3노드+데이터티어 아이콘

---

## Slide 2 — [0] K8s 이전 목적 = kustomize (관통선)
**헤드라인**: 코드는 한 벌(base). 환경 차이는 overlay 한 곳에. → **이전 = 파일 교체가 아니라 overlay 스왑**

```
services/account/
├── base/            ← 환경 무관 (앱의 진짜 스펙)
└── overlays/
    ├── onprem/  → image: Harbor(192.168.0.10)/…:sha
    └── eks/     → image: <ECR>.amazonaws.com/…
```
| 결정 분류 | 예 |
|---|---|
| ✅ 이식성 때문에 | 오퍼레이터·S3·RWX금지·GitOps·ESO |
| 🟡 구현만 스왑 | OpenEBS→EBS · MetalLB→NLB |
| 🔵 온프렘 세금(EKS서 사라짐) | kubeadm·etcd·Host C |

🎤 **노트**: "환경 종속성을 overlay 한 서랍에 몰아넣어서, 나머지 코드는 온프렘인지 EKS인지 모릅니다. 그래서 이전이 서랍만 바꿔 끼우는 일이 됩니다. 이 발표 전체가 이 한 문장으로 수렴합니다."
🖼️ **비주얼**: base/overlay 트리 + 3분류 배지. 안전판: "앱 계층은 실재, 데이터 storageClass overlay화는 숙제(정직)."

---

## Slide 3 — [1] Tech stack = Docker→K8s 도구체인
**헤드라인**: 매니지드 0개, 전부 CNCF 표준. **Docker로 굴리던 3계층이 도구체인이 됐다**

| 박스 | Before(Docker) | After(K8s) |
|---|---|---|
| **CI/CD** 🔴 | GH Actions self-hosted | **Jenkins→Trivy→Harbor→ArgoCD** |
| **DATA** 🔴 | Patroni·생 Redis·생 ES | **CNPG·Sentinel·ECK·Strimzi·KEDA** |
| **INFRA** 🔴 | Docker·Traefik | **kubeadm·Cilium·Istio·Gateway API** |
| OBS/REPO/APP ⚪ | (거의 그대로) | 유지 |

🎤 **노트**: "6박스 중 3개(🔴)만 진짜 toolchain화됐습니다. DATA가 핵심 — Patroni·생 Redis를 오퍼레이터로 바꾼 순간 K8s 오브젝트가 됐고, 그래서 0번의 'EKS서 그대로'가 성립합니다. 반대로 APP/AI는 하나도 안 바뀌었다 = 앱은 원래 환경 독립적이었다는 증거."
🖼️ **비주얼**: 옛 Docker 스택 그림(before) + 🔴 3박스에 화살표 애니메이션. ⚪ 박스는 흐리게.

---

## Slide 4 — [2] 설계도 = 요청 스파인
**헤드라인**: 설계도 전체 대신 **요청이 흐르는 선 하나** — 전부 표준 오브젝트라 EKS 그대로

```
[다리1: 요청 유입]                          [다리2: 앱이 DB로]
Gateway(.14) → HTTPRoute → account Svc → account 파드 ──→ pg-pooler → pg-rw(primary)
  MetalLB      (Gateway API)                 (앱)      앱이 DB 접속을 새로 엶
                                                        응답은 역방향
```
- MetalLB가 `.14` 물어 게이트웨이로 · **HTTPRoute**가 라우팅 · **앱 파드가 경첩**
- Gateway API = 벤더중립 → EKS선 GatewayClass만 Istio→AWS

🎤 **노트**: "요청은 Gateway로 들어와 HTTPRoute가 앱으로 보내고, 요청은 앱 파드에서 처리됩니다. 앱이 DB가 필요하면 커넥션 풀을 거쳐 PG primary로 접속하죠. 화살표가 전부 표준 K8s라 EKS서 그대로 돕니다 — Gateway만 NLB로 이름이 바뀔 뿐."
🖼️ **비주얼**: 스파인 다이어그램(2 다리 색 구분). 앱 파드를 '경첩'으로 강조.

---

## Slide 5 — [3] CI/CD = 무거운 CI를 클러스터 밖으로
**헤드라인**: CI는 무겁다 → 통째로 클러스터 밖(Host C). **EKS 가면 CI EC2로 옮기면 끝**

```
── 클러스터 밖 [Host C → EKS: CI EC2] ──
 push →(웹훅)→ Jenkins Multibranch
   ├ pytest 게이트 ✋   ├ Trivy 게이트 ✋(CRITICAL 차단)
   ├ Harbor push       └ config 레포 커밋 ──┐  (main만)
──────────────────────────────────────────┼──
── 클러스터 안 [온프렘=EKS 동일] ──         ▼
 ArgoCD ── config watch ── sync ──▶ 배포
```
- **Jenkins는 클러스터를 안 만짐 = git 커밋만** → CI 위치 자유
- Harbor는 부팅 전제(순환의존) → **반드시 밖**

🎤 **노트**: "CI 스택이 무겁고 버스티라 앱 클러스터 밖에 뒀습니다. 특히 Harbor는 클러스터 부팅의 전제라 안에 두면 순환의존이 생겨 반드시 밖이어야 하죠. 클러스터엔 이미지·git 커밋만 넘기고 배포는 ArgoCD가. 그래서 EKS 가면 이 박스를 EC2로 옮기면 끝입니다."
🖼️ **비주얼**: 밖/안 경계 박스 + 파이프라인 스테이지. 인계점(config 커밋) 강조.

---

## Slide 6 — [4] Git branch = main 보호
**헤드라인**: main 하나만 신성하게. **CI 통과 + 리뷰 1** 못 넘으면 못 들어옴

| main 보호 (실측) | 값 |
|---|---|
| required check | `jenkins/pr-merge` (Multibranch 생성) |
| required 리뷰 | **1명** |

- 모델 = **GitHub Flow**(단일 트렁크, develop 없음)
- 브랜치 `feat/mp-…` · 커밋 = Conventional Commits

🎤 **노트**: "main + PR 방식이고 PR은 머지 전 반드시 CI를 통과해야 합니다. Multibranch가 PR마다 파이프라인을 돌리고, 브랜치 보호에 그 체크를 required로 걸어 깨진 코드가 main에 못 들어옵니다."
🖼️ **비주얼**: ⭐ **GitHub PR 머지 게이트 스크린샷** — 막힌 PR(빨강)↔통과(초록) 대비 + 브랜치 보호 설정.

---

## Slide 7 — [5] 백업 = 4대상 + 계층 복구
**헤드라인**: 4가지 백업 — **재생성 불가하거나, 재생성이 느린 것**

| 대상 | 방식→목적지 | RPO/RTO |
|---|---|---|
| **PG** | barman WAL+base → **S3** | **RPO~5분 / RTO<10분** |
| **etcd** | snapshot → S3 | RPO≤24h / RTO~30분 |
| **소스** | git mirror → S3 | GitHub 상실 DR |
| **이미지** | docker save → S3 | 재빌드 대비 |

- ES·Redis·Kafka = **재생성**(ES 7초 재색인) → 백업 안 함
- 약어: **RPO**=얼마나 잃나 / **RTO**=얼마나 걸리나 / **PITR**=임의 시점 복구

🎤 **노트**: "원칙은 하나 — 사용자 원본만 지키고 재생성 가능한 건 안 지킵니다. PG는 연속 WAL로 RPO 5분·RTO 10분. 은행이 아니라 예산앱이라 RPO 0은 과하고, 개인 데이터라 전체 유실은 안 되니 5분이 딱 맞는 중간값이죠. 중요한 건 복원을 실제로 해봤다는 거고, 목적지가 S3라 EKS로 그대로 갑니다."
🖼️ **비주얼**: ⭐ **PG 페일오버 4컷 캡처**(cnpg status pg-1→pg-2 + 200 연속 로그). WAL/base = "매 문장 로그 + 전체 저장본" 비유.

---

## Slide 8 — [6] 보안 = defense-in-depth (전체 지도)
**헤드라인**: 한 겹이 아니라 여러 겹. 기본값은 '전부 금지, 허용한 것만'

```
바닥   Cilium WireGuard — 노드 간 모든 파드 암호화
축1 트래픽  app: netpol+mTLS │ data·pipeline·obs: netpol
축2 admission  PSS: app=restricted / 그외=baseline
축3 API권한  RBAC: 개인 SA + 티어
축4 저장  etcd at-rest aescbc
축5 인증서  cert-manager·Istio·Cloudflare (전부 자동)
```

🎤 **노트**: "보안은 여러 겹입니다 — 바닥에 노드 간 전부 암호화, 그 위에 트래픽 통제·파드 규격·사람 권한·저장 암호화·인증서 자동관리. 이 중 세 개는 실제로 쳐서 보여드리겠습니다."
🖼️ **비주얼**: 6층 스택 다이어그램(바닥→위). 각 층 아이콘.

---

## Slide 9 — [6] 보안 라이브 시연 (3종)
**헤드라인**: 말 대신 **master에서 직접 증명**

| 층 | 명령 | 화면 |
|---|---|---|
| netpol | `hubble observe --verdict DROPPED` | 막힌 경로 DROP 로그 |
| RBAC | `auth can-i … --as=…:geonu` | app=**yes** / data·비밀=**no** |
| etcd 암호화 | `etcdctl get … \| hexdump` | `k8s:enc:aescbc…` 암호문 |

- netpol 범위 = **워크로드 4 ns**(플랫폼 ns 후순위 — 정직)

🎤 **노트**: "netpol은 일부러 막힌 경로를 시도해 DROP을 관측하고, RBAC은 건우 계정으로 자기 ns는 yes·남의 ns·비밀은 no가 화면에 바로 뜹니다. etcd는 저장소를 직접 읽어도 암호문이라, 스냅샷을 훔쳐도 키 없이는 못 읽습니다."
🖼️ **비주얼**: ⭐ 3개 터미널 캡처 나란히. RBAC yes/no가 제일 셈.

---

## Slide 10 — [7] 부하테스트 ① 무엇을 어떻게 쟀나
> 🖼️ **실제 장표 반영본** (2026-08-04). 3장 구성 = 시나리오 → 병목·조치 → 자원 정책.

| 단계 | 시나리오 | 결과 |
|---|---|---|
| Stage1 | 서비스별 포화 지점 + 실사용 시나리오 | HPA 기준값 · 최대 replica |
| Stage2 | 유저 조회 중에 가격 갱신 배치 동시 실행 | 응답 +6ms · 영향 없음 |
| Stage3 | 피크 몰림 · 인기 레시피 쏠림 | 한계치 · 병목 지점 |

🎤 **발표문**
> "부하테스트를 왜 했는지부터 말씀드리겠습니다. **잘 버티는지 확인하려던 게 아니라, 설정값을 뽑는 도구로 썼습니다.** HPA를 몇 대로 걸지 감으로 정하면 근거가 없으니까요.
>
> 3단계로 나눴습니다. **1단계**는 서비스를 하나씩 잡고 한계까지 부하를 올려서, 언제 늘려야 하는지와 최대 몇 대가 필요한지를 뽑았습니다.
>
> **2단계**는 간섭 실험입니다. 가격표를 매시 20분마다 새로 만드는 작업이 있는데, 딜이 쏟아지는 시간엔 유저도 몰립니다. 둘이 같은 DB를 쓰니 서로 느리게 만들 수 있어서 **일부러 겹쳐봤습니다.** 결과는 응답이 6밀리초 느려지는 데 그쳤습니다.
>
> **3단계**는 한계 탐색입니다. 사람이 한꺼번에 몰릴 때와, 인기 레시피 하나에 쏠릴 때를 나눠서 어디까지 버티고 어디가 막히는지를 봤습니다."

❓ **예상 질문**
- *"왜 6ms면 괜찮은 건가?"* → SLO 한참 아래. 갱신을 `REFRESH MATERIALIZED VIEW CONCURRENTLY` 로 해서 읽기를 안 막기 때문.
- *"실시간 갱신인가?"* → 아니다. `20 * * * *`(KST) 정시 배치. 겹침은 우연이고, 그 우연을 재현한 것.
- *"3단계 결과는?"* → 브라우징은 **DAU 12,500 등가에도 knee 없음**. 병목은 바이럴 축(핫키 knee ≈250~350rps)에만 나왔다.

🖼️ **비주얼**: 3단계 파이프 + 각 단계 아래 "뽑는 값" 라벨.

---

## Slide 11 — [7] 부하테스트 ② 병목과 조치
**헤드라인**: 증상은 같아도 **원인이 다르면 처방이 다르다**

| 병목 | 진단 | 조치 |
|---|---|---|
| `recipe` 검색 p95 **2.7s** | 단일 pod CPU 포화 | **HPA min2/max4·target 70%** → p95 **46ms** |
| `account` 로그인 p95 **4.2s** | HPA max=4 상한 · CPU request 과소 | **request 250→500m** |

🎤 **발표문**
> "여기서 나온 병목 두 개와 조치입니다.
>
> **첫째, 레시피 검색.** 동시 천 명에서 p95가 2.7초까지 갔습니다. 원인은 서버 한 대의 CPU가 1.2코어에서 더 안 올라가는 거였고, **replica만 4대로 늘리는 통제 실험**을 하니 46밀리초로 떨어졌습니다. **59배**입니다. 스케일로 풀리는 병목이라는 게 확인돼서 HPA를 걸었습니다. 최소 2, 최대 4, CPU 70% 기준입니다.
>
> **둘째, 로그인.** 2천 명이 30초 안에 몰리자 p95가 4.2초까지 갔습니다. 여기는 **HPA 최대치인 4대가 상한**이었고, 게다가 CPU request가 250m인데 실제로는 pod당 4.9코어까지 쓰고 있어서 **사용률이 1500%로 찍혔습니다.** 기준값 자체가 무의미했던 거죠. request를 500m으로 올려 정상화했고, 남은 건 서버를 더 늘리는 게 아니라 **로그인 자체에 rate limit을 거는 앱 작업**으로 넘겼습니다.
>
> 그래서 **HPA는 이 둘에만** 걸었습니다. 늘려서 해결되는 게 실측으로 확인된 것만요."

❓ **예상 질문**
- *"나머지 서비스는?"* → `price` 는 캐시 덕에 CPU 여유(고정), `mealplan` 은 자체 연산이 없는 중계라 부하를 걸어도 CPU가 안 올라감(HPA-무용).
- *"HPA로 안 풀리는 병목도 있었나?"* → 있었다. `recipebook` 핫키는 replica 1→3 으로 늘려도 p95 3.08초 **불변**이었고 pod CPU는 오히려 여유였다. 병목이 pod 가 아니라 **다운스트림 PG**(enrich 5회 순차 왕복). 처방은 쿼리 배칭·캐시·read replica 라우팅으로 **앱/데이터 트랙**.
- *"HPA 걸고 재검증했나?"* → 했다. 자동 HPA 가 2→4 로 늘며 수동 scale 과 같은 수치(72ms)를 냈고 k6 exit 0.

🖼️ **비주얼**: 59× 급락 그래프 + `kubectl get hpa -w` 2→4 캡처.

---

## Slide 12 — [7] 부하테스트 ③ 자원 정책 = 전부 Burstable
**헤드라인**: cpu limit을 어디에도 안 걸었다 — Docker에서 배운 교훈

```
① Docker: account가 cpus:0.75 limit에 막힘 → 2.0으로 해결 (CFS 스로틀)
② 교훈: K8s limits.cpu도 CFS로 똑같이 스로틀 → cpu limit 생략
③ 전 파드 Burstable · 티어 차등 = PriorityClass + 분리 쿼터
```
| 축 | 정책 | 실측 |
|---|---|---|
| **CPU** | limit 없음 · request 비례 배분 | 19/19 컨테이너 cpu limit 없음 |
| **QoS** | 전 파드 Burstable | Guaranteed 0개 |
| **우선순위** | 자원 부족 시 밀려나는 순서 | `data-critical` > `app-normal` > `pipeline-low` |
| **쿼터** | 티어별 자원 상한 분리 | app 6core/6Gi · pipeline 3core/3Gi |

🎤 **발표문**
> "자원 정책은 한 문장으로 요약됩니다. **CPU limit을 어디에도 안 걸었습니다.**
>
> 이유는 Docker 시절 경험입니다. `account` 가 0.75코어 limit에 막히는 걸 겪었고 2.0으로 올려서 풀었는데, **K8s 의 cpu limit도 똑같은 CFS 방식**입니다. 한도를 넘으면 **놀고 있는 CPU가 있어도 강제로 멈춥니다.** 로그인 해싱은 느린 게 보안 기능이라, 그 CPU를 막으면 안 되는 거였고요.
>
> 그래서 19개 컨테이너 **전부 cpu limit이 없고**, QoS는 전부 Burstable, Guaranteed는 0개입니다.
>
> 대신 격리는 다른 두 가지로 합니다. **자원이 부족할 때 밀려나는 순서**는 PriorityClass가 정합니다 — 데이터 티어가 가장 높고, 앱, 파이프라인 순입니다. 그리고 **티어별 자원 상한**은 네임스페이스 쿼터로 나눠뒀습니다. 앱이 6코어 6기가, 파이프라인이 3코어 3기가입니다.
>
> 그리고 **이 6기가가 다음 장 배포전략을 정했습니다.** 최악의 경우 메모리를 84%까지 쓰기 때문에, 두 배가 필요한 블루그린은 애초에 불가능했습니다."

❓ **예상 질문**
- *"DB가 Guaranteed 가 아니어도 되나?"* → 축출은 QoS 라벨이 아니라 **우선순위와 메모리 사용량**이 정한다. `data-critical` 이 가장 높아 마지막에 밀린다. CPU는 축출 요인이 아니라 스로틀만 한다.
- *"cpu limit 없으면 노이즈 네이버는?"* → request 비례 배분 + PriorityClass + 분리 쿼터로 관리. limit 은 스로틀만 유발하고 격리 이득은 없다.
- 🔴 *"data 쿼터는?"* → **없다.** 쿼터는 app·pipeline 두 곳뿐. 이 질문이 나오면 범위를 좁혀 답할 것(아래 정직 항목).

🖼️ **비주얼**: Docker→K8s 3단 화살표. CFS 스로틀 = "빈 도로에도 빨간불" 비유 아이콘.

### 🔴 이 장에서 말하면 안 되는 것 (라이브 실측 2026-08-04)
| 하면 안 되는 말 | 실물 | 근거 |
|---|---|---|
| "메모리는 `requests==limits`" | **app ns 19/19 전부 `req≠limit`**(약 2배) | `account` 256Mi→512Mi · `recipe` 128Mi→256Mi |
| "메모리 req==limit 로 축출을 막는다" | 2배까지 버스트하므로 **축출 후보가 된다** | 축출 보호는 **PriorityClass 만** 실재 |
| "티어 차등 = 분리 쿼터" (전체로 확대) | **`data` ns 엔 쿼터·LimitRange 자체가 없음** | 쿼터는 `app`·`pipeline` 둘뿐. `data` 는 `BestEffort` 파드 3개 존재 |

> `docs/mp_k8s_presentation_bongsu.md §7-⑧` 및 `object_spec §13.7` 과 실물이 어긋난다. **발표는 실물 기준**으로.

---

## Slide 13 — [8] 배포전략 = 카나리 (Deployment→Rollout)
**헤드라인**: 부하테스트가 예산을 확정 → **핵심 2개만 카나리**

| | 롤링(9개) | **카나리(account·recipe)** | 블루그린 |
|---|---|---|---|
| kind | Deployment | **Rollout** | — |
| 배포 | 즉시 100% | 20→50→100·자동롤백 | **RAM 2배 ✗** |

```
kind: Deployment  ──▶  kind: Rollout   (파드 template은 그대로, strategy만 얹음)
kubectl get rollout → account·recipe 딱 둘 / get deploy → 나머지 9
```

🎤 **노트**: "블루그린은 부하테스트 때문에 탈락 — 메모리 최악 84%라 2벌은 RAM이 부족합니다. 카나리를 골랐고, 켠다는 건 워크로드를 Deployment에서 Rollout으로 바꾸는 구체적 작업이에요. 파드는 그대로 두고 전략만 얹은 거라 get rollout으로 이 둘만 종류가 다른 게 바로 보입니다. 20→50→100으로 흐르고 나쁘면 자동 롤백."
🖼️ **비주얼**: Deployment→Rollout kind 교체 다이어그램 + `get rollout` vs `get deploy` 캡처.

---

## Slide 14 — [시연] CI/CD → 카나리 (영상)
**헤드라인**: push 한 번이 카나리 배포까지

```
① push → ② Jenkins(빌드·Trivy·Harbor·config커밋) → ③ ArgoCD sync
→ ③.5 get rollout(account·recipe만) → ④ 카나리 20→50→100 (v1/v2 비율 상승) → ⑤ 완료
```
- 킬러 장면 = curl 응답의 **v1/v2 비율이 20→50→100%로 실제로 바뀜**
- (선택) 깨진 버전 → **20%서 자동 롤백**

🎤 **노트**: "코드 한 줄 바꿔 push하면 Jenkins가 빌드·스캔해 config에 커밋하고, ArgoCD가 카나리를 시작합니다. curl로 때려보면 v2 응답 비율이 20%에서 50%, 100%로 실제로 올라가는 게 보이죠. 나쁜 버전은 20%에서 자동 롤백됩니다."
🖼️ **비주얼**: ⭐ **영상** (rollout watch + curl v1/v2 분할 화면). 2~3분, 빌드는 타임랩스.

---

## Slide 15 — 마무리 (through-line 완결)
**헤드라인**: 전부 표준 K8s. **온프렘에서 완성해뒀으니, EKS로 가도 방식은 안 바뀐다**

| 그대로 이식 | 구현만 스왑 | EKS서 사라짐 |
|---|---|---|
| 오퍼레이터·GitOps·HPA·카나리·보안 | OpenEBS→EBS·MetalLB→NLB | kubeadm·etcd·Host C |

- 0번(kustomize)이 8개 섹션을 관통

🎤 **노트**: "처음에 말한 overlay 스왑으로 돌아옵니다. 오퍼레이터도, GitOps도, 카나리도, 보안도 전부 표준 K8s라 EKS서 그대로 돕니다. 온프렘 특유의 것(스토리지·LB)은 추상화 뒤에서 이름만 바뀌고, 컨트롤플레인 부담은 AWS가 대신 져서 오히려 사라지죠. 저희는 이식 표면을 정확히 알고 설계했습니다."
🖼️ **비주얼**: 3분류 요약 표 + "온프렘 = EKS 리허설" 한 줄.

---

## 부록 — 내일 준비물 (캡처 체크리스트)
- [ ] **4** GitHub PR 게이트(막힌/통과 + 보호설정)
- [ ] **5** PG 페일오버 4컷(cnpg status + 200 로그)
- [ ] **6** netpol DROP · RBAC can-i · etcd hexdump
- [ ] **7** HPA `get hpa -w`(2→4) · KEDA `get deploy`(0/0)
- [ ] **8/시연** CI/CD→카나리 영상(v1/v2 비율)
