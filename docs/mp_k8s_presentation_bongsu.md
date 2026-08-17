# 발표 노트 — 봉수 파트 (0~8번)

> 캡스톤 발표용. "핵심만 탁탁." 각 섹션 = 슬라이드 헤드라인 1줄 + 탁탁 메시지 + 근거.
> **전체 through-line = 0번(EKS 이식성).** 다른 섹션에서 결정이 나올 때마다 0번으로 콜백한다.
> 작성 2026-08-03 · 라이브 대조본.

목차: 0 이전목적 · 1 tech stack · 2 설계도 · 3 CI/CD · 4 git branch · 5 백업 · 6 보안 · 7 부하 · 8 배포전략

---

## 0. K8s 이전 목적 — "AWS(EKS) 이전 전 온프렘 리허설"

### 헤드라인 (한 줄)
> **"코드는 한 벌(base). 환경 차이는 overlay 한 곳에 격리. → 온프렘→EKS 이전 = 파일 교체가 아니라 overlay 스왑."**

### 🎯 주인공 — kustomize base + overlay

```
services/account/
├── base/                    ← 환경 무관. 앱의 "진짜" 스펙
│   ├── deployment.yaml         (컨테이너·포트·probe·리소스)
│   ├── service.yaml
│   ├── hpa.yaml
│   └── kustomization.yaml
└── overlays/
    ├── onprem/              ← 온프렘 값만
    │   └── image: 192.168.0.10/mealplanning/mp-account-service:<sha>   (Harbor)
    └── eks/                 ← EKS 값만
        └── image: <ECR>.dkr.ecr.ap-northeast-2.amazonaws.com/...       (ECR)
```

**세일즈 포인트 3가지 (탁탁):**
1. **환경 차이가 overlay 한 곳에 다 모여 있다** → 나머지(base) 전부가 "환경 독립적"임이 **파일 구조로 증명**된다. 말이 아니라 디렉터리가 증거.
2. **이전할 때 건드리는 게 overlay 디렉터리뿐** → diff가 작다 = **리스크가 작다.** `kustomize build overlays/eks` 로 끝, base 무수정.
3. **ArgoCD가 overlay를 가리킨다** → 이전이 "선언적 GitOps 한 줄"이지 손수 배포가 아니다.

**핵심 멘트:** *"환경 종속성을 overlay라는 한 서랍에 몰아넣었기 때문에, 나머지 코드는 온프렘인지 EKS인지 모릅니다. 그래서 이전이 서랍만 바꿔 끼우는 일이 됩니다."*

### 🌿 나머지는 "곁다리" — overlay가 얇게 유지되도록 받쳐준 조건들

| 받쳐준 결정 | 없었으면 overlay에 뭐가 샜을까 |
|---|---|
| **오퍼레이터(매니지드 안 씀)** | RDS/MSK 콘솔 설정이 overlay로 새어듦 → base가 환경 종속됨 |
| **RWX 금지 · PVC 추상화** | storageClass가 EBS와 안 맞아 base 재작성 |
| **Harbor→ECR** | (이미 overlay가 처리 — 레지스트리 한 줄) |
| **MetalLB · OpenEBS** | 온프렘 구현이지만 Service/PVC 추상화 뒤에 숨어 base엔 안 보임 |
| **S3 백업** | 애초에 AWS 네이티브라 공통 |

곁다리 멘트: *"오퍼레이터·PVC 추상화·Gateway API 같은 선택들은 전부 base를 환경 독립적으로 유지하려고 한 겁니다 — overlay를 얇게 만드는 게 목적이었어요."*

### ⚠️ 정직 안전판 (멘토 반례 대비)
- 앱 계층은 overlay 실재(Harbor↔ECR 실제로 갈림). **데이터 계층 storageClass(openebs-lvm)는 아직 base에 박혀 있어 overlay화가 남은 숙제** — 오퍼레이터 CR 자체는 이식되고 storageClass 한 줄만 빼면 됨.
- EKS overlay의 ECR은 아직 **PLACEHOLDER** = 구조는 완성, 실배포는 미실증. → *"메커니즘은 증명됐고, 실배포는 다음 단계"* 로 말하면 안전.

### 결정 분류 (다른 섹션 콜백용 태그)
- ✅ **이식성 때문에**: 오퍼레이터 · S3 · RWX금지 · kustomize · ESO · Gateway API · GitOps · HPA/KEDA/Rollouts
- 🟡 **구현만 스왑**: OpenEBS→EBS · MetalLB→NLB (추상화는 이식, 온프렘 구현만 교체)
- 🔵 **온프렘 세금, EKS서 사라짐**: kubeadm · etcd 관리 · 컨트롤플레인 하드닝 · Host C(CI)
- ⚪ **다른 이유 + EKS서도 됨**: Cilium(eBPF 성능) · Istio(mTLS) — "진짜 이유 먼저 + EKS서도 동작"

### 🎤 라이브 코드 워크스루 대본 (실 repo `account` kustomization 4슬라이드)

> 스크린샷 순서 = ① `account/` = base+overlays → ② `base/` 8파일 → ③ `overlays/` = eks+onprem → ④ kustomization.yaml 좌우(eks/onprem) 비교.
> 페이싱: ①~③은 각 8~10초로 빠르게, **④에서 멈춰** 레지스트리 한 줄을 손가락으로 짚는 게 클라이맥스.

**여는 한 문장 (화면 없이):**
> "저희가 온프렘에 K8s를 올린 진짜 목적은 **AWS EKS 이전 전 리허설**이었습니다. 그래서 처음부터 **'나중에 EKS로 옮길 때 뭘 최소한만 바꾸게 만들까'**를 기준으로 설계했고, 그 답이 지금 보여드릴 **kustomize base/overlay** 구조입니다."

**① `account/` = base + overlays 두 폴더:**
> "실제 config 레포의 `account` 서비스입니다. 폴더가 딱 둘 — **base**(앱의 '진짜 스펙')와 **overlays**('환경마다 다른 값'). 이 둘을 물리적으로 분리한 게 핵심입니다."

**② `base/` 8파일:**
> "base 안입니다. rollout·service·hpa·pdb·probe… 앱을 **어떻게 굴릴지**가 전부 여기 있죠. **그런데 여기 어디에도 '온프렘'·'EKS'라는 단어가 없습니다.** 레지스트리 주소도, 스토리지 종류도 안 박혀 있어요. 즉 base는 **자기가 어디서 도는지 모릅니다.** 이게 이식성의 출발점 — 말이 아니라 **파일 구조가 증거**입니다."

**③ `overlays/` = eks + onprem:**
> "환경 차이는 어디 갔냐 — **overlays 한 곳에 다 모여 있습니다.** onprem 서랍, eks 서랍 딱 둘. 나머지 base 전부가 환경 독립적이라는 걸, **'차이는 여기밖에 없다'**는 이 두 폴더가 반대로 증명합니다."

**④ kustomization.yaml 좌우 비교 (하이라이트):**
> *(화면 뜨자마자, kustomize가 뭔지 먼저)* "kustomize가 뭘 하냐면 — **base는 복사·수정하는 게 아니라 그대로 두고, overlay의 '다른 값만 덧발라(patch)' 최종 매니페스트를 찍어내는 도구**입니다. `kustomize build overlays/onprem` 하면 base + Harbor 한 줄이 합쳐진 완성본이 나오고, ArgoCD가 그걸 클러스터에 적용합니다. → 그래서 온프렘·EKS가 base를 **공유**하면서 레지스트리 줄만 갈립니다."
> *(이어서 diff를 짚으며)* "왼쪽 EKS, 오른쪽 온프렘 overlay인데 — **둘 다 `../../base`를 그대로 가져오고, 실질적으로 다른 건 이미지 레지스트리 한 줄뿐**입니다. 온프렘은 `192.168.0.10`(우리 Harbor), EKS는 `...dkr.ecr...`(AWS ECR). **이게 이전의 전부입니다.** base는 한 글자도 안 바뀌고 이 줄만 갈아끼우면 EKS로 넘어갑니다. diff가 작다 = **이전 리스크가 작다.**"

**핵심 멘트 (한 박자 쉬고):**
> **"환경 종속성을 overlay라는 한 서랍에 몰아넣었기 때문에, 나머지 코드는 온프렘인지 EKS인지 모릅니다. 그래서 이전이 코드 재작성이 아니라 서랍만 바꿔 끼우는 일이 됩니다."**

**⚠️ Helm 비교 질문 대비 — "템플릿 아니라 patch":**
> **"kustomize는 템플릿 엔진이 아니라 patch 병합기입니다.** Helm처럼 `{{ .Values }}` 변수 자리를 채우는 게 아니라, base는 그 자체로 **완결된 유효한 YAML**이고 overlay는 '이 필드만 덮어써'라고 **선언**할 뿐 → kustomize가 둘을 merge. 그래서 base는 변수 구멍 없이 **혼자서도 배포 가능**합니다."

**⚠️ 정직 안전판 (멘토 반례 대비):**
- **EKS overlay의 ECR은 아직 `PLACEHOLDER`** → *"구조·메커니즘은 완성, 실배포는 다음 단계"*. "EKS 돌려봤다"고 하면 반례.
- 왼쪽 tag `1.1.9`(고정) vs 오른쪽 `:sha` 이유 → **온프렘은 Jenkins가 CD로 `:sha`를 계속 커밋**하는 라이브 트랙, EKS는 아직 CI 미연결 placeholder. (*"온프렘은 GitOps 실가동, EKS는 뼈대만"*)
- **데이터 계층 storageClass(`openebs-lvm`)는 아직 base에 박혀 있음** = 앱 계층은 overlay 실재, 데이터 overlay화는 남은 숙제. (*"오퍼레이터 CR은 이식되고 storageClass 한 줄만 빼면 됨"*)

---

## 1. Tech stack (tool chain) — "Docker 스택 → K8s 도구체인"

### 발표 방식 = 옛 Docker 스택 그림을 "before"로 깔고, 바뀐 박스에만 화살표
청중이 아는 그림에서 출발해 **변화만** 짚는다. 6박스 중 **3박스만** 진짜 toolchain화됨 → 거기만 시간 쓴다.

### 헤드라인 (한 줄)
> **"매니지드 0개 — 전부 CNCF 표준으로 셀프호스트. Docker로 손수 굴리던 3계층이 도구체인이 됐다."**

### Before → After (6박스, 🔴=바뀜 / ⚪=그대로)

| 박스 | Before (Docker) | After (K8s) | 변화 |
|---|---|---|---|
| **CI/CD** 🔴 | 아이콘 1개 = **GH Actions self-hosted**(`fb-ci` 러너, 2026-07-27 은퇴) | **Jenkins → Trivy → Harbor → ArgoCD** | 막연한 상자 → **연결된 체인** |
| **DATA** 🔴 | 생 PG·Patroni · 생 Redis · 생 ES | **CNPG · Redis-operator+Sentinel · ECK · +Strimzi · +KEDA** | 손 HA → **오퍼레이터 선언** |
| **INFRA** 🔴 | Docker · Traefik | **kubeadm · Cilium · Istio · MetalLB · Gateway API** | 컨테이너 → **표준 오케스트레이션** |
| OBSERVABILITY ⚪ | Grafana·Prom·Loki·Tempo·Alert | kube-prometheus-stack + LGTM(ArgoCD 관리) | 거의 유지 (선언화만) |
| REPO ⚪ | git · GitHub | GitHub(앱) + **config 레포**(GitOps desired state) | 레포 2개 분리 |
| APP/AI ⚪ | FastAPI·pytest·LightGBM·Gemini·CRF·XGBoost | 그대로 | **안 바뀜 = 앱은 이식성 증거** |

→ 곁다리(⚪) 3박스는 "거의 그대로"로 한마디로 넘긴다.

### 🎯 탁탁 3메시지
1. **CI/CD = 문자 그대로 "tool chain"이 됐다.** Before는 러너 하나에 얹은 GH Actions. After는 **push 한 번 → Jenkins 빌드 → Trivy 스캔 게이트 → Harbor → ArgoCD 배포**가 한 줄로 꿰인 체인. ← "tool chain" 단어의 주인공
2. **DATA = 손으로 짜던 HA가 오퍼레이터로.** Patroni로 PG 이중화하던 걸 **CNPG**가, 생 Redis/ES를 **Sentinel/ECK**가 선언적으로 대신. ← **0번 이식성의 뿌리**
3. **INFRA = Docker/Traefik → K8s 표준.** 리버스프록시(Traefik) 하나로 라우팅하던 걸 **Gateway API + Istio + MetalLB** 표준 계층으로.

### 콜백 멘트 (0번 잇기 — DATA 박스가 다리)
> *"DATA 박스가 핵심입니다. Patroni·생 Redis를 **오퍼레이터로 바꾼 순간** 이게 K8s 오브젝트가 됐고, 그래서 0번의 'EKS서 그대로'가 성립합니다. 반대로 APP/AI 박스는 **하나도 안 바뀌었다** — 앱은 원래부터 환경 독립적이었다는 증거죠."*

### 발표 팁
- **화살표 애니메이션**: 6박스 띄우고 → 🔴 3박스에만 Before→After 화살표. 나머지는 흐리게.
- **"안 바뀐 박스(APP/AI)"를 오히려 강조** — 이식성 설계의 산 증거 → 0번 콜백 소재.
- 다음 섹션 연결: *"이 도구들이 실제로 어떻게 배치돼 도는지는 2번 설계도에서."*

### ⚠️ 정직 안전판
- 언어는 **Python 단일**(API·ML·파이프라인) + 프론트 React/Vite — ML은 CPU-only 제약이라 CRF/XGBoost/LightGBM.
- Cilium/Istio는 **EKS 때문에 고른 게 아니다**(eBPF 성능·mTLS가 진짜 이유). "그 이유 먼저 + EKS서도 됨"으로.

---

## 2. K8s 설계도 — "요청 스파인 하나만"

설계도는 읽으면 죽는다. **딱 한 흐름 = 요청 스파인**만 손가락으로 따라간다. (나머지 흐름은 보류)

### ⭐ 요청 스파인 — 요청 경로와 DB 커넥션은 **별개의 두 다리**

```
[다리 1: 요청이 들어옴]                        [다리 2: 앱이 DB로 나감]
Gateway(.14) → HTTPRoute → account Svc → account 파드 ──→ pg-pooler → pgbouncer → pg-rw(primary)
   [진입]       [라우팅]      [ ]          (앱)        앱이 DB 접속을
                                                        "새로" 엶(풀 재사용)
```
- 🔴 **앱 파드가 경첩.** 요청은 account 파드에서 **끝나고**, 파드가 DB 필요 시 **별도로** pg-pooler로 커넥션을 연다. "Service → pooler"가 아님.
- **MetalLB** = `.14`를 물고 있는(ARP 응답) 노드가 트래픽 받아 Istio 게이트웨이 파드로 넘김.
- **라우팅 주체 = HTTPRoute**(오브젝트), Istio는 실행 엔진.
- **응답은 이 경로를 역방향**으로. (DB 커넥션은 요청마다 새로 뚫는 게 아니라 풀에서 재사용)

### Gateway API 3층 (진입부 = 0번 대표 사례)
```
GatewayClass(구현체=Istio) → Gateway(리스너·MetalLB .14) → HTTPRoute(라우팅·카나리 weight) → Service
```
> **0번 콜백:** *"Gateway API는 벤더 중립 표준. EKS 가도 HTTPRoute·Gateway는 그대로 두고 **GatewayClass만** Istio→AWS로 바꾼다 — 라우팅 규칙 재작성 없음. 옛 스택 Traefik에 묶였던 걸 표준 오브젝트로 뽑아낸 부분."*

### 압축 대본 (30초)
> *"요청이 흐르는 선 하나만 보겠습니다. Gateway로 들어와 HTTPRoute가 앱으로 보내고, 요청은 **앱 파드에서 처리**됩니다. 앱이 DB가 필요하면 **커넥션 풀**을 거쳐 PG primary로 접속하고, 응답은 역방향으로 나갑니다. **전부 표준 오브젝트라 EKS서 그대로** 돕니다."*

---

## 3. CI/CD — 초점: **무거운 CI를 클러스터 밖으로 분리 → 이식** (deck §04, git branch 통합)

### 🧵 관통 논지 (오프닝)
> **"브랜치 전략이 CI/CD 구조를 결정했다. GitHub Flow로 필요할 때마다 목적별 브랜치를 따서 쓰다 보니 항상 여러 브랜치가 동시에 살아있고(멀티 브랜치), 그걸 자동 처리하려고 Jenkins Multibranch 파이프라인을 이렇게 구성했다."**

### 🎤 실 장표 대본 — 8슬라이드 (이건 뭐다 → 다음으로 연결)

**[1] Git branch — GitHub Flow**
- 이건 뭐다: main 하나 중심, 필요할 때 **목적별 브랜치**를 따서 PR로 합침 = 멀티 브랜치
- 대본: GitHub Flow(트렁크 기반) · 브랜치 이름=목적(`feat/`·`fix/`·`docs/`·`chore/`) · PR+pytest 통과해야 머지 → **main 항상 green**
- → 연결: "여러 브랜치가 동시에 살아있으니, 자동 처리할 파이프라인이 필요했다"

**[2] CI/CD 아키텍처 — Multibranch**
- 이건 뭐다: 멀티 브랜치 자동 처리 — push 한 번이 검증→배포
- 대본: **Multibranch=브랜치마다 자동 감지·빌드** · Push→웹훅→Jenkins(호스트 C, **클러스터 밖**)→pytest→SonarQube(main만)→build→Trivy→image push · **[PR]**=pr-merge 체크 / **[main]**=config `:sha` 커밋→ArgoCD watch→apply
- 탁 3: ① CI 무거워 클러스터 밖(EKS면 CI EC2) ② Jenkins는 커밋만·배포는 ArgoCD ③ **PR은 배포 안 함**

**[3] PR #529 — 사람 게이트**: 코드 통과로 끝 아님, **리뷰 1명 Approve 필수**(기계+눈)
**[4] PR #529 — out-of-date**: 리뷰✅·체크✅인데도 막힘 → **main이 그새 바뀌어** Update branch 최신화 요구
**[5] PR #529 — 재검증**: main 합친 **최신 코드로 체크 다시**(=슬라이드2 Jenkins 재실행). **여기선 CD 안 일어남**(config 커밋은 main만)
**[6] PR #529 — 전부 통과**: 리뷰+체크+최신화 3개 초록 → Squash merge. **머지 순간 [main] 경로 발동**
**[7] ArgoCD — CD**: config 커밋에 **Synced·Healthy·auto-sync** · 파드 초록 구동 = git 커밋이 곧 클러스터 상태(GitOps)
**[8] 이미지 태그 — loop 닫기**: ArgoCD 매니페스트 `image:…:X` = config `newTag: X`(mealbong-ci 커밋), **같은 sha** = CI 이미지가 클러스터까지 완결

### 🔑 [5] 재검증을 "왜" 다시 하나 (semantic conflict)
- **각 브랜치 혼자선 통과해도 합치면 깨질 수** 있음. git 머지는 **텍스트 충돌만** 잡지 **의미 충돌**은 못 잡음.
- 예: main에 PR-A가 `get_user()→fetch_user()` rename 머지됨 / 내 PR-B는 `get_user()` 호출 추가 → 각자 통과, 합치면 main 깨짐(텍스트 충돌 없음). Update branch로 A 반영 후 재검증 → pytest 실패로 **머지 전 포착** → **main green 유지**.
- GitHub 설정 = **"Require branches to be up to date before merging"**.

### 🔴 [5]↔[6] CD 트리거 시점 (헷갈림 주의)
- **[5] PR 재검증 = 배포 없음** (PR 빌드, config 안 건드림). image push/sha 갱신/CD 감지는 **[6] 머지 후 main 빌드**에서. **CD 트리거하는 `:sha` 커밋은 오직 main에서만.**

### 📸 CD 캡처 가이드 (deck [7][8])
- **[7]** = ArgoCD `mp-account` 상세: 상단 Healthy·Synced·auto-sync + 트리 초록 파드. (Sync Revision은 **config 레포 공용 커밋**이라 서비스별 구분은 이미지 태그로)
- **[8]** = Rollout MANIFEST의 `image:…:X` ↔ config `overlays/onprem/kustomization.yaml`의 `newTag: X` 나란히. ⚠️ 크롤러는 **CronJob이라 라이브 파드 없음** → CD 캡처는 **account/recipe(Deployment/Rollout)**로.

---

### 헤드라인
> **"CI 스택은 무겁다(Jenkins·SonarQube·Harbor·Trivy). 그래서 앱 클러스터 밖(Host C)에 통째로 뒀다. EKS 가면 이 박스를 CI EC2로 옮기면 끝."**

### 플로우 (경계 + 파이프라인 한 장)
```
────────── 클러스터 밖  [온프렘 Host C  →  EKS: CI EC2] ──────────
 GitHub push / PR
   │ 웹훅 (cloudflared — 이 경로만 노출)
   ▼
 Jenkins  Multibranch ···· 브랜치·PR마다 파이프라인 자동 생성
   ├ 변경 감지 ········· 바뀐 서비스만
   ├ pytest 게이트 ✋ ··· 실패 = 중단
   ├ SonarQube ········ 측정만(비차단)
   ├ docker build
   ├ Trivy 게이트  ✋ ··· CRITICAL = 차단
   ├ Harbor push ······ mp-account:<sha>
   └ config 레포 커밋 ──┐   ← main일 때만! (PR이면 여기서 끝=배포 안 함)
─────────────────────────┼──────────────────────────────────────
                          ▼
────────── 클러스터 안  [온프렘 = EKS 동일] ──────────
 ArgoCD ── config 레포 watch ── sync ──▶ 앱 배포
```
경계선 위(밖) = **무거운 CI = 이식 대상**, 아래(안) = **CD = 온프렘·EKS 동일**.

### 왜 밖으로 뺐나 (설계 포인트 2)
1. **리소스 격리** — 빌드·스캔 스파이크가 앱 파드와 자원 다투면 서비스가 느려짐(noisy neighbor). 밖으로 빼면 앱 클러스터가 안 받음.
2. **⭐ 순환 의존 회피** — Harbor는 **클러스터 부팅 시 이미지를 당겨오는 전제**. 안에 두면 "클러스터를 켜려면 Harbor 필요한데 Harbor가 그 안에" 순환 → 레지스트리는 **반드시 밖**.

### 이식이 쉬운 이유
> *"클러스터엔 **결과물(이미지+git 커밋)만** 전달. Jenkins는 클러스터를 안 만짐 → CI가 어디 있든 무관. Host C를 **CI EC2로 lift-and-shift**하거나, **Harbor→ECR·Jenkins→CodeBuild** 매니지드화. **데이터는 락인 때문에 매니지드를 피했지만 CI는 앱이 아니라 빌드 인프라라 매니지드 OK.** 어느 쪽이든 앱 클러스터는 안 건드림."*

### Multibranch = 한 줄만 (깊은 "왜"는 4번)
> *"Jenkins Multibranch가 브랜치·PR마다 파이프라인을 자동으로 돌리고, main일 때만 배포로 넘어간다."*

### ⚠️ 정직 안전판
- lift-and-shift는 **설계상 깔끔하나 실제 CI EC2를 세워본 건 아님**(계획).
- Host C는 단일 100GB 디스크(여유 27.9GB) → 실제 제약은 디스크(질문 오면 "그래서 EKS선 ECR로 분리").

---

## 4. Git branch 전략 (⚠️ deck에선 §3 CI/CD로 통합됨 — 아래는 설계 근거·질문 대비 레퍼런스)

> 🔴 발표 덱 04에서 **git branch를 CI/CD와 한 슬라이드 흐름으로 합쳤다** — 실 대본은 **§3 "실 장표 대본 [1]"**. 아래는 상세 근거(브랜치 모델·보호 규칙·커밋 컨벤션)로 질문 대비용.

### 3번에서 잇는 한 줄
> *"3번의 Multibranch가 PR마다 파이프라인을 돌린다고 했죠. **그걸 강제하는 규칙이 브랜치 전략**입니다."*

### 헤드라인
> **"main 하나만 신성하게. 모든 변경은 PR로, CI 통과 + 리뷰 1을 못 넘으면 main에 못 들어온다."**

### ① 브랜치 모델 = GitHub Flow (단일 트렁크)
```
main  ──●────●────────●────●──▶   항상 배포 가능 (머지 = 배포)
         \    \        /    /
          feat/mp-…   fix/mp-…      ← 짧게 살고 사라지는 타입 브랜치
```
- **`develop`·`release` 상설 브랜치 없음** (Git Flow의 복잡함 안 짊). `release/pipeline-*`만 버전 릴리스 때 잠깐.
- 브랜치 = **`<type>/mp-<slug>`**: feat·fix·docs·refactor·chore. (인프라·신규는 `mp-` 접두사)

### ② PR 게이트 = main 보호 (실측)
| 규칙 | 값 |
|---|---|
| required status check | **`jenkins/pr-merge`** (Multibranch 생성) |
| required 리뷰 | **1명** |

> *"둘이 main의 문지기. CI 빨간불이면 머지 버튼이 잠기고, 리뷰 1 없이도 잠김 → 깨진/안 본 코드가 main에 못 들어옴."*

**📸 발표용 스크린샷 (말보다 셈):**
- **① PR 하단 머지 박스** — 막힌 PR(빨강 `✗ jenkins/pr-merge` + "Merging is blocked" + 회색 버튼) ↔ 통과 PR(초록) **대비**로. (게이트가 실제로 막는 장면)
- **② 브랜치 보호 설정** (`Settings→Branches→main`) — Require status checks에 `jenkins/pr-merge`, Require approvals 1. (정책 그 자체)
- 팁: **깨끗한 대표 PR**로 (git fetch 플레이크로 빨간 PR은 피하기 — 딴 질문 유발). 최근 #513·#514가 깔끔.
- 이해: **"매번" = PR에 push할 때마다 재검사**, 머지는 (체크 초록 AND 리뷰 1) **둘 다** 만족해야 열림.

### ③ 커밋 = Conventional Commits
```
fix(config): 파괴된 VM 기본값 제거 (SonarQube S1313) (#518)
└type┘└scope┘ └──── 무엇을·왜 ────┘                    └PR┘
```
→ 히스토리가 그대로 changelog. type/scope로 자동 릴리스노트 가능.

### 🔗 콜백 (0번/3번)
> *"이 워크플로는 **인프라 위 계층**이라 온프렘이든 EKS든 **안 바뀜.** 사람이 일하는 방식은 클라우드를 안 탄다. 배포 경로만 밑에서 바뀔 뿐."*

### ⚠️ 정직 안전판 (질문 오면)
- `enforce_admins: false` — 관리자 우회 가능(긴급 핫픽스용). "정책상 우회 안 하되 문은 열어둠".
- 리뷰어 1명 = 5인 팀 규모에 맞춘 값.

---

## 5. 백업 전략

### 헤드라인
> **"4가지를 백업한다 — PG·etcd·소스·이미지. 기준은 '재생성 불가하거나, 재생성이 느린 것.'"**

### 🔤 약어 (반드시 설명 가능해야)
- **RPO** = **Recovery Point Objective** (복구 **시점** 목표) → *"데이터를 얼마나 잃을 수 있나."* RPO 5분 = 최악의 경우 최근 5분치 유실.
- **RTO** = **Recovery Time Objective** (복구 **시간** 목표) → *"복구까지 얼마나 걸리나."* RTO 10분 = 10분 안에 복귀.
- **PITR** = **Point-In-Time Recovery** (특정 **시점** 복구) → *"임의의 과거 순간(예: 실수로 DELETE 1분 전)으로 되돌리는 능력."* WAL 아카이빙이 가능케 함.
- **DR** = **Disaster Recovery** (재해 복구) → *"장애·손실 후 복구하는 것 전반. RPO/RTO는 그 목표치."*
- 외우기: **RP**O=**P**oint(얼마나 잃나) / **RT**O=**T**ime(얼마나 걸리나).

### ① 무엇을 백업하나 = 3단 판단 (진짜 원칙)
| 티어 | 대상 | 왜 |
|---|---|---|
| 재생성 절대 불가 → **반드시** | **PG** | 사용자 생성 데이터 (회원·예산·지출·식단) |
| 재생성 되지만 느리거나 외부 의존 → **DR 가속** | **etcd**·**소스**·**이미지** | etcd=재구축 느림 / 소스=GitHub 죽으면 / 이미지=재빌드 느림 |
| 재생성 빠름 → **안 함** | ES·Redis·Kafka | ES는 PG에서 **7초** 재색인, Redis=캐시, Kafka=재수집 |

### ② 무엇을·어떻게 백업하나 (보존 정책 포함)

**개요**
| 대상 | 방식 → 목적지 | 주기 | 보존(폐기) | 성격 (RPO/RTO) |
|---|---|---|---|---|
| **PG (오프사이트)** | barman base+WAL → **S3** | base 03:00 · WAL ~5분 | **30일** | 재난+시점복구(PITR) · **RPO~5분/RTO<10분** |
| **PG (온사이트)** | pg_dump → **MinIO**(인클러스터) | 매일 04:00 | **7일** | 빠른 로컬·테이블 단위 · **⚠️DR 아님** |
| **etcd** | snapshot → **S3** | 매일 02:00 | **14일** | 상태(+Secret) 재구축 · RPO≤24h/RTO~30분 |
| **소스** | `git clone --mirror`→tar.gz → **S3** | 매월 1일 | **400일(~13개월)** | GitHub 장애·상실 대비 |
| **이미지** | `docker save` → **S3** | 릴리스마다 | **S3 lifecycle** | 재빌드 대비(best-effort) |

> 온사이트 로컬은 최근 2~3개만 유지.

**PG 물리백업 상세 — base/WAL 원리 (⭐ RPO~5분 근거)**
| 구성 | 무엇 | 주기·위치 |
|---|---|---|
| **base 백업** | DB 전체 통째 스냅샷 = 복구 출발점 | 매일 03:00 → S3 |
| **WAL 기록** | 모든 변경을 WAL에 연속 기록 | 매 변경 · **로컬** |
| **WAL 아카이빙** | 세그먼트(16MB) 차거나 archive_timeout마다 S3로 | **~5분** · S3 |
| **복구(PITR)** | 최신 base 복원 → 이후 WAL 재생 → 원하는 시점 | RPO~5분/RTO<10분 |

> 🔑 **RPO~5분 = WAL 아카이빙 간격.** 로컬엔 연속, S3로는 최대 5분마다. (발표 전 실제 `archive_timeout`=5분 확인 권장)
> 🎮 base=세이브 파일 통째 / WAL=이후 조작 로그 → 복구=세이브 로드+로그 재생.

**두 PG 백업 역할 분담**
| | 오프사이트(S3) | 온사이트(MinIO) |
|---|---|---|
| 종류 | 물리(barman) | 논리(pg_dump) |
| 커버 | 재난+시점복구(PITR) | 논리오류+테이블 단위 |
| 사이트 손실 | ✅ 살아남음 | ❌ b2 단독=호스트B와 운명공유 |

> 💡 secrets 방어: K8s Secret은 etcd 안에 있어 etcd 백업에 포함. 단 etcd 암호화 키만은 순환이라 별도 묶음.

### ③ PG PITR 메커니즘 (심장이니 이것만)
```
WAL(로컬 연속 기록) → ~5분마다 S3 아카이빙  +  정기 base(매일, "전체 저장본")
      └── 복구 = 최신 base + 이후 WAL 재생 ──┘   RPO~5분 / RTO<10분
```
파드·노드 장애는 CNPG **자동 페일오버 초~1분** (백업 복구 불필요).

### ④ 페일오버 데모 (📸 캡처 4컷 — HA층 실증, 백업복구와 구별)
복원력 2층: **HA(흔한 장애·초 단위·데모 가능)** + **백업(드문 재난·논리오류·분 단위)**. 데모는 HA층.
🔴 표현 정확히: "slave에 붙는다"❌ → **"standby가 primary로 승격되고 `pg-rw`가 새 primary를 가리킴. 앱은 접속 문자열 안 바꿈 = 투명하게 따라감"**⭕ (2번 요청 스파인 재활용)

```bash
# ① 평소               kubectl cnpg status pg -n data          → Primary: pg-1
# ② 창A(서비스 연속성)  while true; do date +%T; curl -s -o /dev/null -w "%{http_code}\n" https://app.mealbong.cloud/<db-endpoint>; sleep 1; done
#    창B(장애 주입)      kubectl delete pod pg-1 -n data
# ③ 승격 확인           kubectl cnpg status pg -n data          → Primary: pg-2 (스왑!)
# ④ (보너스)            kubectl get endpoints pg-rw -n data     → 뒤 IP가 pg-1→pg-2
```
슬라이드: **①↔③ 좌우 대비(역할 스왑) + 하단 ② 200 연속 로그(무중단)**. ⚠️ 승격 수 초~30초 블립 → 창A에 재시도 있어야 예쁨. 피크(11-12,17-18) 피해 녹화.

### ⑤ 우리 서비스에서 정말 중요한 것
**논리 오류 복구 = 백업의 진짜 이유** — *"하드웨어 장애는 HA가 초 단위로 막고, 백업이 진짜 필요한 순간은 **사람 실수**(잘못된 배포·버그가 지출 테이블 손상). PITR로 '그 배포 1분 전'으로 되감거나 온사이트 덤프로 그 테이블만 복원."*
**user-generated vs crawled** — *"사용자가 만든 것(예산·지출·식단)은 재생성 불가 → 1순위. 크롤링한 것(가격·레시피)은 다시 크롤 가능. 검색 인덱스(ES)는 PG에서 재색인하니 안 지킴."*

### RTO/RPO를 왜 이 값으로? (서비스 근거)
> *"우리는 은행이 아니라 밀플래닝/예산 앱. **RPO 0(실시간 복제)은 과하고 비쌈** — 최악이 '방금 입력한 지출 몇 건'이고 재입력 가능 → 5분 충분. 하지만 **몇 달치 예산 이력은 개인 데이터라 전체 유실 불가** → 연속 WAL로 5분에 묶음. **RTO 10분** — 시간 임계 거래가 아니고 트래픽도 식사시간에 몰려 그 외 영향 작음. 게다가 흔한 장애는 HA가 초 단위로 먼저 막아 이 10분은 드문 재난에만 적용."*

### "백업했다" ≠ "복원된다" (성숙함)
- 왕복 복원 증명(barman promote 4초·재구축 116초) · pg_dump 목차 검증 · **자기 감사로 이미지 백업 구멍 발견(2026-08-03)** → 고치고 **신선도 감시+알림 9종**.

### 🔗 0번 콜백
> *"목적지가 **전부 S3**라 EKS 이전에 손 안 댐. PG 백업은 **CNPG 기능**이라 동일. **etcd 백업만 온프렘 몫**인데 EKS선 AWS가 etcd를 멀티멤버로 관리해서 이 24h RPO 자체가 사라짐."*

### ⚠️ 정직 안전판
- 이미지 = 최초 강제 1회 미완(보류) · Harbor/Jenkins config = 코드완료·적용 보류 · etcd 단일 멤버 → RPO≤24h(EKS서 해소).

---

## 6. 보안 전략 (netpol/RBAC 등)

> 구성: **6.0 계층 표(첫 페이지 = 전체 지도) → 6.1~6.5 계층별 드릴다운.**
> 백업→보안 연결어: *"데이터를 '잃지 않게'(백업) → '뺏기지 않게'(보안)."* + *"백업에서 etcd·비밀을 암호화했는데, 그게 보안의 시작."*
> 🔴 probe·PDB·QoS·priorityClass는 **보안 아니라 안정성** → 7·8번에서. 6번엔 podSecurity만.

### 6.0 defense-in-depth 표 (첫 페이지)
```
┌──────────────────────── 클러스터 전체 ────────────────────────┐
바닥    │ Cilium WireGuard — 노드 간 모든 파드 트래픽 암호화 (투명)        │
        ├──────────┬────────────┬────────────┬──────────────────┤
축1 트래픽│ app      │ data        │ pipeline    │ observability     │
        │ netpol   │ netpol      │ netpol      │ netpol            │
        │ +mTLS    │ (ingress·   │ (egress     │ (MinIO 잠금)       │
        │ (신원·L7)│  5포트)      │  FQDN)      │                   │
        ├──────────┴────────────┴────────────┴──────────────────┤
축2 admission│ PSS enforce: app=restricted / 그 외=baseline (warn=restricted)│
축3 API권한 │ RBAC: 개인 SA + 티어(admin/app-dev/observability/data-dev)     │
축4 저장   │ etcd at-rest: aescbc 암호화 (137/137 검증)                     │
축5 인증서  │ TLS: cert-manager(내부CA) · Istio(mTLS) · Cloudflare(엣지) — 전부 자동 │
        └───────────────────────────────────────────────────────┘
```
> 오프닝 대본: *"보안은 한 겹이 아니라 여러 겹입니다. 바닥엔 노드 간 전부 암호화, 그 위에 트래픽 통제·파드 규격·사람 권한·저장 암호화·인증서 자동관리. 이 중 **세 개는 실제로 쳐서** 보여드립니다 — netpol 드롭, RBAC can-i, etcd 암호문."*

### 6.1 netpol — zero-trust (축1)
**thesis**: *"클러스터의 모든 파드는 원래 자유 통신. 우리는 뒤집었다 — 허용한 것만, 나머지 default-deny."* 워크로드 4 ns(app·data·pipeline·observability) 잠금.
```
              인터넷  (✗ 파드 직접 진입)
          ┌────────┴────────┐
     [ Gateway .14 ]   [ 내부 Gateway .15 ]
          │ mTLS            │ (팀원 대시보드)
    ┌─────▼──────┐   ┌──────▼──────────────┐
    │  app ns    │   │ observability ns    │
    │ front/back │   │ Grafana·MinIO 🔒     │
    └─────┬──────┘   └──────▲──────────────┘
          │ 5포트            │ pg_dump(←5번 백업)
    ┌─────▼──────┐          │
    │  data ns   │──────────┘  🔒 스토어끼리 차단(Redis⇏PG)
    └────────────┘
   [ pipeline ns ]  크롤러 ✗ app·인터넷 (격리)
  ⬛ 안 그린 경로 = 전부 차단
```
**5포트**: 5432(PG)·6379(Redis)·26379(Sentinel)·9200(ES)·9092(Kafka). 관리포트(9300·9090/9091·익스포터)는 닫음. Sentinel(26379)=앱이 "지금 primary 누구냐" 물어보는 포트(5번 페일오버와 동일 원리).
**YAML 2장 (극적)**: ① frontend egress=DNS·istiod뿐("털려도 갈 곳 DNS뿐") ② pipeline `podSelector:{}`+ingress=Prometheus만("텅 빈 게 규칙").
**라이브 증명**: `hubble observe --namespace data --verdict DROPPED` (실제 드롭 로그) + `cilium-dbg bpf policy get <ep>` (data=5포트만).
⚠️ 정직: **워크로드 계층만**(플랫폼 ns 후순위 — hostNetwork·오퍼레이터 리스크) · **AuthorizationPolicy 0건**(L7 절반 갭).

### 6.2 RBAC — 사람 최소권한 (축3)
비유: **권한="카드"(K8s 기본 view/edit/admin 재사용) + 바인딩="어디서 쓸지"**(전역=ClusterRoleBinding / ns=RoleBinding).
문제→해결: 전원 공유 admin.conf=cluster-admin, **취소 불가**(유출=CA교체뿐) → 개인 SA + 즉시 취소.

| 사람 | 역할 | 티어 | ✅ 할 수 있는 것 | ⛔ 못 하는 것 |
|---|---|---|---|---|
| 봉수·태현 | 인프라 | **admin** | 전역 전권 | — (버스팩터 2명) |
| 건우 | AI 기능 | **app-dev** | 전체 읽기 + app·pipeline 쓰기 | data 쓰기·fb-secrets·전역 쓰기 |
| 정현 | 모니터링 | **observability** | 전체 읽기 + observability 쓰기 + 알림룰 | data 알림룰·app 배포 |
| 정은 | 파이프라인·finops | **data-dev** | 전체 읽기 + pipeline 쓰기 | data 쓰기·fb-secrets |

공통 방어선: ① 자기 ns 밖은 읽기전용 ② `view`는 **Secret 값 제외**(전체 읽기 줘도 비밀 안 샘) ③ `fb-secrets`는 admin만.
**라이브 증명 (건우로 3개)**: `auth can-i create deployments -n app --as=…:geonu`=yes / `-n data`=no / `get secrets -n fb-secrets`=no. (20/20 검증)

### 6.3 PSS + securityContext 하드닝 (축2)
app=**restricted 강제** / 그 외=baseline(warn=restricted로 관찰). PSS가 파드 하드닝을 강제:
```yaml
securityContext:
  runAsNonRoot: true               # root 금지
  allowPrivilegeEscalation: false  # 권한 상승 차단
  readOnlyRootFilesystem: true     # FS 쓰기 불가
  capabilities: { drop: ["ALL"] }  # 리눅스 권한 전부 버림
  seccompProfile: { type: RuntimeDefault }
```
> *"root로 뜨거나 위험 권한 가진 파드는 app ns에서 **스케줄 자체가 거부**됩니다. 털려도 할 수 있는 게 최소."*
**라이브 증명**: `kubectl -n app run bad --image=nginx --privileged --dry-run=server` → 거부(violates "restricted").

### 6.4 etcd at-rest 암호화 (축4)
aescbc, 137/137 암호문 검증(평문 0). 키 유실 시 스냅샷 복호 불가라 분리 보관.
**라이브 증명 (제일 극적)**:
```bash
sudo ETCDCTL_API=3 etcdctl --cacert /etc/kubernetes/pki/etcd/ca.crt \
  --cert /etc/kubernetes/pki/etcd/server.crt --key /etc/kubernetes/pki/etcd/server.key \
  get /registry/secrets/<ns>/<name> | hexdump -C | head        # → k8s:enc:aescbc:… 암호문
```
> *"etcd 스냅샷을 통째로 훔쳐도 키 없이는 쓸모없습니다."* + kube-bench(CIS) 감사로 13 FAIL→10 해소.

### 6.5 TLS 인증서 (축5) — "사람이 안 만진다"
| 계층 | 도구 | 로테이트 |
|---|---|---|
| 워크로드 간 mTLS | Istio | ~24h 자동(SPIFFE) |
| 내부 도구(*.mealbong.cloud) | cert-manager(내부 CA) | 만료 전 자동 갱신 |
| 공개 엣지(app.mealbong.cloud) | Cloudflare | 관리·자동 |
> *"인증서를 사람이 안 만집니다 — 전부 자동 발급·로테이트. '만료돼 장애'가 구조적으로 안 남."*

### 표 밖 요소 (물으면 답)
- **비밀=ESO**(git에 없음, SecretStore 주입) · **공급망=Trivy**(3번 CI 게이트, CRITICAL 차단) · **감사 로그**(누가·뭘·언제) · **정문 하나=Cloudflare Tunnel**(노출 포트 0) · **점검=kube-bench(CIS)**.

### 🔗 0번 콜백
> *"netpol·RBAC·mTLS·PSS는 **표준 K8s라 EKS 동일**. **etcd 암호화·CIS 컨트롤플레인 하드닝만 온프렘 몫**인데 EKS선 AWS가 관리해 사라짐. 단 Cilium 엔티티 규칙(host·apiserver)은 EKS가 다른 CNI면 다시 쓰는 유일한 부분."*

---

## 7. 부하테스트 (k6)

### 헤드라인
> **"부하테스트를 'HPA·리소스 값 산출 + 한계·병목 실측' 도구로 썼다. '병목마다 처방이 다르다'를 숫자로 증명."**

### ① 방법 = 3-스테이지
Stage1 서비스별 포화스윕(→HPA 4분류) · Stage2 딜 골든아워 경합(Δp95) · Stage3 피크몰림×바이럴(한계·병목 실측).
환경: Windows k6.exe → Gateway `.14` 직타(CF터널 우회) · off-peak · LLM 제외 · abortOnFail.

### ② 킬러 대비 — HPA "통하는 병목" vs "안 통하는 병목" ⭐⭐
| | recipe(Stage1) | recipebook 핫키(Stage3) |
|---|---|---|
| replica | 1→4 | 1→3(통제) |
| p95 | **2.7s→46ms (59×)** | **3.08s→3.08s (불변)** |
| 병목 | pod CPU (스케일 해결) | 다운스트림 PG enrich 5왕복 (스케일 무효) |
> *"같은 증상, 다른 뿌리. **HPA는 만능이 아니다**를 실측으로 갈랐다."*

### ③ HPA 4분류
account·recipe=**HPA-CPU** / price=**고정** / mealplan=**HPA-무용**(다운스트림 대기). *"실측 근거 있는 것만 HPA."*

### ④ Stage2 경합 격리
matview refresh × price → 유저 **Δp95 +6ms**(SLO 한참 아래). PriorityClass·Pooler가 유저 사수.

### ⑤ Stage3 한계 좌표 + 부산물 (정량 — 멘토 피드백 직답)
DAU 500→λ 0.4세션/s→**MULT DAU 등가표**: 브라우징 **DAU 12,500 여유** / 바이럴 핫키 **knee ~300rps**.
부산물: **seq scan 발견**(52ms→2.77s→pg_trgm) · **버그 #477**(publish 404) · 신선도 실측(ES 미노출 설계 확인).

### ⑥ 적용 (라이브 — config PR #81·#82)
recipe HPA(70%·min2/max4)+PDB · request 튜닝(account 250→**500m**·price 100→**300m**). 재검증=자동 2→4=수동과 동일.

### ⑦ CPU limit = Docker→K8s 스토리텔링 (1번 콜백)
```
① Docker 부하테스트: account가 cpus:0.75 limit에 막힘 → 2.0으로 해결 (CFS quota 스로틀)
② 교훈 §13.7: K8s limits.cpu도 CFS로 똑같이 스로틀 → cpu limit 생략 (특히 bcrypt 버스트)
③ K8s 측정: account가 bcrypt로 여러 코어까지 버스트 → limit이면 잘렸을 workload 확인
```
- **CFS quota 스로틀** = cpu limit 걸면 100ms period당 quota(limit×100ms) 초과 시 **유휴 CPU 있어도 강제 정지**. 버스트(bcrypt) workload엔 독.
- **bcrypt CPU는 버그 아니라 기능** (느린 해싱=무차별대입 방어). 막으면 안 되는 CPU 사용.
- 🔴 **정직**: "스로틀 없이 버스트"는 동어반복(limit 안 걸었으니 당연). 실증한 건 **"account가 버스트 여력이 있다"는 측정**이고, "limit이 아프다"의 인과는 **Docker A/B(0.75→2.0)** 가 근거.
- limit 제거 = 끝 아님 → 병목이 **HPA max로 이동** → 남은 레버 = 앱 레벨 rate-limit(별건).

### ⑧ 클러스터 전체 QoS·자원 정책 (🔴 실물 기준 — §13.7 의도와 다름)
```
request = 예약·보장 floor(스케줄 기준·경합 시 비례배분)  /  limit = 최대 상한(CPU 스로틀·메모리 OOM)

모든 파드 = Burstable  (app·data·pipeline 전부 — cpu limit 어디에도 없음)
  ├ requests 있음        → BestEffort(축출1순위) 회피  (pg-pooler PR#127 사례)
  └ cpu limit 없음        → Guaranteed 대신 버스트 허용 (⑦)

티어 차등 = cpu limit이 아니라:
  · PriorityClass  data-critical(1M) > app-normal(100K) > pipeline-low(1K)  → 축출 순서
  · 분리 requests 쿼터  app 6core/6Gi  vs  pipeline 3core/3Gi  → CPU 경합 시 app이 2:1로 우선
메모리 = app/data는 req==limit(과커밋 방지·OOM 예측성) · pipeline은 req≠limit(chromium 버스트 의도)
```
- 🔴 **§13.7은 "pipeline은 limits 있어야 한다"지만 실물은 cpu limit 없음(Burstable)** — 쿼터가 requests에 걸려 강제 안 됨. **문서-실물 gap = 화해 필요.** 발표선 **"전부 Burstable + priority/분리쿼터로 차등"**(실물)으로 말할 것.
- **합리성**: cpu limit 없음은 베스트프랙티스(Tim Hockin류) — CPU는 request 비례로 공정, 격리는 priority+분리쿼터로. limit은 이득 없이 스로틀만. ⚠️ 단 극한 노드 고갈 축출은 **메커니즘 근거지 실측 아님**.
- **DB가 Guaranteed 아니어도 되는 이유**: 축출은 QoS 라벨이 아니라 (메모리 req==limit + priority)가 정함. cpu는 축출요인 아님(스로틀만). 유일한 차이(cpu limit)는 축출과 무관.

### ⑨ 쿼터 예산 → 8번 다리
app 6core/6Gi · 최악(account·recipe 둘 다 max4) **메모리 84%**(CPU보다 먼저 조임). → *"이 baseline이 확정돼야 배포전략(8번)을 고른다 — 블루그린 2배는 RAM 부족."*

### 🎬 라이브 시연 (캡처)
- **HPA**: `kubectl -n app get hpa -w` → recipe 2→4 · `describe hpa` Events "SuccessfulRescale"
- **KEDA**: `kubectl -n pipeline get deploy` → 컨슈머 **0/0**(scale-to-zero)
- (선택) **cpu limit A/B**: `set resources deploy/mp-account --limits=cpu=1` → cfs_throttled 스파이크+p95악화 → 제거→회복

### 🔗 0번 콜백 / ⚠️ 정직
표준 K8s라 EKS 동일(노드 오토스케일로 천장↑) · Stage2B(KEDA 콜드스타트) 미실행 · DAU 500엔 과잉여유 · account rate-limit·recipebook enrich·pg_trgm=앱/데이터 후속

---

## 8. 배포 전략 (ADR-0001 · 라이브 완료)

### 헤드라인 (7번에서 이어짐)
> **"부하테스트가 6core/6Gi 예산을 확정 → 그 예산으로 배포전략을 **고를 수 있게** 됐고, 핵심 서비스만 카나리로 골랐다."**

### ① 세 옵션 비교 → 예산이 하나를 탈락시킴
| | A. 롤링(현행) | **B. 카나리** | C. 블루그린 |
|---|---|---|---|
| 점진/게이트 | ❌ 즉시 100% | ✅ 20→50→100·자동분석·자동롤백 | ⚠️ 원샷 |
| 메모리 | 여유 | 부분 surge(관리가능) | **2배 → 6Gi 초과 ✗** |
| 롤백 | 수동 | **자동**(분석 실패 시) | 즉시 스위치백 |
> *"블루그린은 **부하테스트 때문에 탈락** — 최악 메모리 84%인데 2벌이면 RAM 2배라 워커가 못 버팀. 예산이 선택지를 좁혔다."*

### ② 왜 카나리(B)
- **자동 분석·자동 롤백**(에러율 나쁘면 사람 없이 이전 버전).
- **선행조건 이미 라이브**: Istio(트래픽분할)+Prometheus(분석) → 하드 의존성 2개 이미 있음.
- **캡스톤 발표가치**(ADR이 정당한 결정 동인으로 명시).

### ③ 왜 account·recipe만 (← 부하테스트 직결) ⭐
- 이 둘 = 부하테스트의 **HPA 대상·트래픽 핵심**(로그인·검색). 배포 위험 급소.
- 나머지 9개 = Deployment 롤링(maxSurge 25%) — 트래픽 적고 과잉여유.
- 일관성: Stage3에서 recipebook은 **HPA 반증**(스케일 무효) → HPA도 카나리도 대상 아님이 자연스러움.

### ④ `kind: Deployment` → `kind: Rollout` (카나리를 켠다는 것의 실체)
카나리 = 워크로드 종류를 **Deployment → Argo Rollouts의 Rollout**으로 교체. Rollout은 Deployment **상위호환** — 파드(template) 그대로, 전략만 얹음.
```yaml
# 나머지 9개                          # account·recipe
apiVersion: apps/v1                   apiVersion: argoproj.io/v1alpha1
kind: Deployment          ─────▶      kind: Rollout          # ← 이것만 바뀜
spec:                                 spec:
  replicas: 2                           replicas: 2          # 동일
  template: {...파드...}                template: {...파드...}   # ← 그대로!
                                        strategy:
                                          canary:            # ← 추가
                                            steps: [setWeight 20, pause 30s, analysis,
                                                    setWeight 50, pause 30s, analysis, →100]
                                            trafficRouting: { Gateway API(HTTPRoute weight) }
```
- **파드는 안 바뀐다** — kind+strategy만. → **0번 콜백**: 앱은 그대로, 배포 wrapper만 교체.
- **HPA·HTTPRoute가 Rollout을 가리킴**(`scaleTargetRef: kind: Rollout`, weight는 HTTPRoute).
- `kubectl get rollout -n app` = account·recipe **딱 둘** / `get deploy` = 나머지 9. **kind가 곧 "이 둘만 특별대우"의 증거.**
- 🔴 컷오버 함정: 전환 시 **구 Deployment 수동 삭제**(안 지우면 Deployment+Rollout이 파드 중복). 라이브 전환 때 밟음(무중단 처리).

### ⑤ 카나리 동작 (account 기준)
```
setWeight 20% → pause 30s → analysis → 50% → pause 30s → analysis → 100%
                                │ AnalysisTemplate이 에러율 검사 → 나쁘면 자동 abort(즉시 이전 버전)
```
weight 조정 = **Gateway API HTTPRoute backendRefs weight**(2번 요청 스파인의 그 HTTPRoute).

### ⑥ 라이브 실증 (2026-08-03 완료)
recipe **0→20→50→100 자동 promote 실증** · account 전환 · 구 Deployment 삭제 **무중단**. config PR #104·#106·#108·#109.

### ⑦ 성숙함 (질문 방어)
- **플러그인 vendoring 소스빌드**: 릴리스 바이너리 Trivy CRITICAL 2건 → golang1.25.12+grpc 소스빌드 **0건**(공급망=3번 연결).
- **분석 NaN 오탐 방어**: 무트래픽 시 메트릭 []→NaN → `(expr>=0) or vector(0)`.
- **함정**: `ignoreDifferences`가 미적용을 Synced로 위장 → **HTTPRoute 실물 backendRefs로 검증**(6번 "Synced≠검증"과 동일 교훈).

### 🔗 0번 콜백 (through-line 완결) / ⚠️ 정직
> *"Argo Rollouts·Gateway API weight·Istio·Prometheus — 전부 표준 K8s라 **EKS서 그대로**. 온프렘에서 카나리를 완성해뒀으니 EKS로 가도 배포 방식 불변."*
정직: 카나리는 **account·recipe 2개만**(나머지 롤링) · ADR = 팀장 소관 결정.

---

## 시연 영상 — CI/CD → 카나리 (3번 + 8번 한 편)

> 목표: **"push 한 번이 카나리 배포까지"** 를 2~3분에. 편집 전제(빌드=타임랩스, 카나리=실시간).
> 대상 = **recipe**(카나리 대상·GET이라 curl 쉬움). 눈에 보이는 변경 = 응답에 `ver: v1→v2`.
> 킬러 장면 = 카나리 중 응답의 **v1/v2 비율이 20→50→100%로 실제로 바뀜**.

**사전 준비**: 변경 준비(미push) · 창 5개(A 코드·git / B Jenkins / C ArgoCD / D rollout watch / E curl 루프) · off-peak · 알림 silence.

**컷 리스트**
| # | 창 | 내용 | 처리 | 자막 |
|---|---|---|---|---|
| ① push | A | `git commit -am "demo: recipe ver v2" && git push` | 실시간 | "코드 한 줄 바꾸고 push" |
| ② Jenkins | B | 웹훅→Multibranch: 변경감지→pytest→Trivy→Harbor push→config 커밋 | **타임랩스** | "빌드·Trivy·Harbor → config 태그 커밋" |
| ③ ArgoCD | C | mp-recipe OutOfSync→Synced, Rollout 갱신 | 실시간 | "ArgoCD 감지→반영" |
| ③.5 kind | D | `kubectl get rollout -n app`(account·recipe) vs `get deploy`(나머지 9) | 실시간 ~8s | "카나리 대상은 Deployment가 아니라 **Rollout** — 이 둘만" |
| ④ 카나리 | D+E | D:`kubectl argo rollouts get rollout mp-recipe -n app --watch`(20→50→100) / E: curl 루프→v1/v2 비율 상승 | **실시간**(길면 1.5x) | "20→50→100%. v2 비율이 실제로 오른다" |
| ⑤ 완료 | E | curl 전부 v2 · Rollout Healthy | 실시간 | "무중단 완료. push 한 번이 카나리까지" |

**E 창 curl 루프**: `while true; do curl -sk https://app.mealbong.cloud/<recipe-ver-endpoint> | grep -o 'v[12]'; sleep 0.5; done`
→ 이 트래픽이 AnalysisTemplate 분석 입력도 됨(에러 0→자동 승격).

**(선택) 자동 롤백 클립 (임팩트 최고)**: 깨진 v3(500) 배포 → 카나리 20%서 에러율↑ → AnalysisTemplate 자동 abort → *"나쁜 버전은 20%에서 자동 롤백, 사람 개입 0."*

**오프닝/클로징 자막**: (오프닝) "push 한 번이 카나리까지 — Jenkins→Harbor→ArgoCD→Argo Rollouts" / (클로징) "모두 표준 K8s. EKS로 가도 이 파이프라인은 그대로." (0번 콜백)
