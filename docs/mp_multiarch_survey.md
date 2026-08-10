# 멀티 아키텍처 빌드 조사 (AWS 이관 선행작업 1-6)

조사일 **2026-08-10**. 이 문서는 **조사 결과**다 — 결정은 하나도 들어 있지 않다.
선택지가 있는 곳은 선택지와 근거만 적었고, 고르는 것은 별건이다.

## 0. 왜 필요한가

| | 아키텍처 | 근거 |
|---|---|---|
| AWS 프로덕션 | **arm64** | m7g.xlarge = Graviton |
| 온프렘 재해복구(standby) | **amd64** | i7-10700F. 노드 5/5 전부 amd64 (실측 — `k8s-master`·`worker-a1`·`a2`·`b1`·`b2`) |

페일오버가 성립하려면 두 사이트가 **같은 이미지 태그**를 가리켜야 한다.
그러려면 한 태그가 두 아키텍처를 다 담는 **매니페스트 리스트**여야 한다.

현재 buildx 사용 0건 → 지금 만든 이미지를 Graviton 노드에 올리면 `exec format error` 로 파드가 안 뜬다.

---

## A. 파이썬 패키지 aarch64 휠 전수 확인

### 결론 — **휠이 없는 패키지 0건. 전부 있음.**

19개 requirements 파일 + `deploy/pgsync` 의 인라인 `pip install` 까지 **전부** aarch64 로 해석된다.
더 강한 증거: **해석된 패키지·버전 집합이 amd64 와 완전히 동일하다**(106개, diff 0줄).
= arm64 라서 다른 버전으로 후퇴하는 패키지조차 없다.

### 확인 방법

`pip download --no-deps` 는 **직접 의존만** 본다 — 정작 위험한 건 전이 의존(grpcio·scipy·python-crfsuite·
uvloop·pydantic_core 처럼 requirements 에 이름이 안 적힌 네이티브 확장)이라 그대로 쓰면 놓친다.
그래서 **전체 의존 해석**으로 돌렸다:

```bash
pip install --dry-run --ignore-installed --only-binary=:all: \
    --python-version 312 --implementation cp --abi cp312 \
    --platform manylinux2014_aarch64 --platform manylinux_2_17_aarch64 \
    --platform manylinux_2_28_aarch64 --platform manylinux_2_31_aarch64 \
    --platform manylinux_2_34_aarch64 --platform manylinux_2_35_aarch64 \
    --platform manylinux_2_36_aarch64 --platform manylinux_2_39_aarch64 \
    --platform manylinux_2_41_aarch64 --platform linux_aarch64 \
    --target /tmp/dummy --report /tmp/rep.json -r <requirements.txt>
```

- `--only-binary=:all:` = 휠이 없으면 **에러로 죽는다**. 소스 컴파일로 조용히 넘어가지 않는다.
- glibc 상한 근거: 베이스 `python:3.12-slim` = **Debian 13 trixie, glibc 2.41**(실측 `ldd --version`).
  그래서 `manylinux_2_41` 까지 열어도 실제로 설치 가능하다.
- 같은 스크립트를 `x86_64` 로 한 번 더 돌려 **대조군**을 만들고 결과를 diff 했다.

대상 = `services/*/requirements.txt` 11 · `ml/*/requirements.txt` 4 · `pipelines/*/requirements.txt` 2 ·
`crawler/*/requirements.txt` 2 = **19개**. (`deploy/*/requirements*.txt` 는 **존재하지 않는다** —
pgsync 는 Dockerfile 안에서 `pip install pgsync==7.1.0` 로 직접 깐다. 그래서 따로 돌렸다.)

### 네이티브 확장 패키지 27종 — 전부 aarch64 휠 존재 (실측 파일명)

| 패키지 | 버전 | aarch64 휠 |
|---|---|---|
| aiohttp | 3.14.3 | manylinux2014 / 2_17 / 2_28 |
| bcrypt | 5.0.0 | manylinux2014 / 2_17 (cp39-abi3) |
| cffi | 2.1.1 | manylinux2014 / 2_17 |
| charset-normalizer | 3.4.9 | manylinux2014 / 2_17 / 2_28 |
| confluent-kafka | 2.15.0 | manylinux_2_28 |
| cryptography | 50.0.0 | manylinux2014 / 2_17 (cp311-abi3) |
| frozenlist | 1.8.0 | manylinux2014 / 2_17 / 2_28 |
| grpcio | 1.83.0 | manylinux2014 / 2_17 |
| httptools | 0.8.0 | manylinux2014 / 2_17 / 2_28 |
| **lightgbm** | 4.7.0 | manylinux2014 / 2_17 (py3-none-manylinux) |
| lxml | 6.1.1 | manylinux2014 / 2_17 |
| multidict | 6.7.1 | manylinux2014 / 2_17 / 2_28 |
| **numpy** | 2.5.2 | manylinux_2_27 / 2_28 |
| pillow | 12.3.0 | manylinux_2_27 / 2_28 |
| propcache | 0.5.2 | manylinux2014 / 2_17 / 2_28 |
| protobuf | 7.35.1 | manylinux2014 (cp310-abi3) |
| **psycopg-binary** | 3.3.4 | manylinux_2_27 / 2_28 |
| pydantic_core | 2.46.4 | manylinux_2_17 / manylinux2014 |
| **python-crfsuite** | 0.9.12 | manylinux_2_24 / 2_28 |
| pyyaml | 6.0.3 | manylinux2014 / 2_17 / 2_28 |
| **scikit-learn** | 1.9.0 | manylinux_2_27 / 2_28 |
| **scipy** | 1.18.0 | manylinux_2_27 / 2_28 |
| uvloop | 0.22.1 | manylinux2014 / 2_17 / 2_28 |
| watchfiles | 1.2.0 | manylinux_2_17 / manylinux2014 |
| websockets | 16.1.1 · 17.0.1 | manylinux2014 / 2_17 / 2_28 |
| wrapt | 2.3.0 | manylinux2014 / 2_17 / 2_28 |
| yarl | 1.24.5 | manylinux2014 / 2_17 / 2_28 |

**glibc 하한 최댓값 = `manylinux_2_28`** (numpy·pillow·scipy·scikit-learn·psycopg-binary·confluent-kafka).
베이스가 glibc 2.41 이라 여유가 크다. Debian 12(2.36)로 내려가도 안전하다.

굵게 표시한 6종이 사전에 가장 의심스러웠던 것들이다 — CRF NER(`python-crfsuite`, `sklearn-crfsuite` 의
전이 의존이라 requirements 에 이름이 없다) · 레시피 랭킹(`lightgbm`) · `scikit-learn`/`scipy`(numpy 스택) ·
`psycopg[binary]` · Kafka C 클라이언트. **전부 aarch64 휠이 있다.**

### pgsync 7.1.0 (deploy/pgsync)

38개 패키지 전부 해석됨. 네이티브 의존 = `psycopg2-binary` · `greenlet` · `SQLAlchemy` · `grpcio` ·
`protobuf` · `charset-normalizer` · `backports-datetime-fromisoformat` → 전부 aarch64 휠 존재.

### 🔴 이 결과의 유효기간 — 지금은 "전부 있음"이지만 고정된 사실이 아니다

requirements 상당수가 **범위 핀**(`fastapi>=0.110` · `numpy>=1.26` · `redis>=5` 등)이다.
위 결과는 **2026-08-10 시점 PyPI 최신 해석**이고, 내일 새 릴리스가 나오면 달라질 수 있다.
컷오버 직전에 같은 스크립트를 한 번 더 돌리거나, 아예 버전을 못박는 편이 안전하다(별건).

또 하나 — **휠 존재 ≠ arm 에서 정상 동작**이다. 이 조사는 "빌드가 에뮬레이션으로 새지 않는다"까지만
보장한다. 런타임 검증은 실제 arm64 이미지를 띄워봐야 한다.

---

## B. 아키텍처 하드코딩 수정 (이 PR 에 포함)

레포 전체 Dockerfile 을 `amd64|x86_64|aarch64|arm64|GOARCH|uname -m` 로 훑어 나온 곳은 **2곳뿐**이다.

### B-1. `infra/images/rollouts-gatewayapi-plugin/Dockerfile` — 수정함

```diff
-FROM golang:1.25.12-alpine AS build
+FROM --platform=$BUILDPLATFORM golang:1.25.12-alpine AS build
...
-RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOTOOLCHAIN=local \
+ARG TARGETARCH
+RUN if [ -z "${TARGETARCH}" ]; then \
+      echo "TARGETARCH 미주입 — BuildKit/buildx 로 빌드해야 한다" >&2; exit 1; \
+    fi \
+ && CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} GOTOOLCHAIN=local \
       go build -trimpath -o /out/gatewayapi-plugin . \
```

- `--platform=$BUILDPLATFORM` 이 **핵심**이다. 없으면 arm64 타깃일 때 golang 이미지까지 arm64 로
  당겨와 QEMU 위에서 컴파일한다. Go 는 크로스컴파일러라 `GOARCH` 만 바꾸면 되므로 그 에뮬레이션은
  순수 낭비(수분 → 수십분).
- `ARG TARGETARCH` 는 buildx 가 타깃마다 주입하는 predefined ARG 다. 값을 안 쓰면 재선언이 필요하다.
- assert 를 넣은 이유: **빈 값이면 go 가 빌더 호스트의 GOARCH 로 조용히 떨어진다.**
  그러면 arm64 매니페스트 안에 amd64 바이너리가 들어가고, 그 사고는 클러스터에서
  `exec format error` 로만 드러난다. 이 파일의 커밋 sha assert 와 같은 이유로 빌드를 죽인다.
  ⚠️ 관용구인 `${TARGETARCH:?msg}` 를 **쓰면 안 된다** — Dockerfile 파서는 `:-`/`:+` 만 알고
  `:?` 는 `unsupported modifier` 로 빌드를 거절한다. 그래서 평범한 셸 분기로 썼다.
- 런타임 스테이지 `FROM busybox:1.37.0` 은 그대로 둔다 — buildx 가 타깃 플랫폼용을 알아서 고른다
  (busybox 는 arm64/v8 제공, 실측).
**검증(호스트 C 실측, 2026-08-10)** — 멀티아키 빌드는 안 돌렸다(D-2 참조). 대신:
1. `docker buildx build --call=outline` 로 **Dockerfile 파싱 통과** 확인. (`:?` 를 썼다면 여기서 죽었다.)
2. 별도 프로브 이미지로 **plain `docker build` 도 `TARGETARCH=amd64` 를 주입**함을 확인
   (BuildKit 기본). → 현행 Jenkins 파이프라인은 buildx 로 안 바뀌어도 이 assert 에 걸리지 않는다.

- 🔴 이 이미지는 Argo Rollouts 컨트롤러의 **initContainer** 다(실측: `argo-rollouts/rollouts-argo-rollouts`
  의 initContainer `vendored-gatewayapi-plugin`). 이게 arm64 에서 안 뜨면 **컨트롤러가 기동하지 않고
  account·recipe 배포 게이트가 정지**한다 — AWS 쪽에서 가장 먼저 깨질 이미지다.

### B-2. `deploy/pgsync/Dockerfile` — 주석 수정함 (교체 여부는 결정 안 함)

구 주석: *"공식 toluaina1/pgsync 는 arm64 전용이라 x86_64(.8)에서 못 씀 → 자체 빌드"*

`.8` VM 은 P4(2026-07-31)에서 파괴됐고 AWS 는 arm64 라, 문장만 보면 전제가 뒤집힌 것처럼 읽힌다.
**실측하니 뒤집히지 않았다.**

Docker Hub 매니페스트 직접 조회(2026-08-10):

| 확인 항목 | 실측값 |
|---|---|
| `toluaina1/pgsync` 태그 총 개수 | **1개** (`latest` 뿐) |
| `latest` 매니페스트 타입 | OCI image index |
| 포함 플랫폼 | **`linux/arm64` 하나** (+ attestation `unknown/unknown`) |
| amd64 매니페스트 | **없음** |

→ ① 공식 이미지는 여전히 **arm64 단일 플랫폼**이다. 온프렘 노드 5/5 가 amd64 이므로 **DR 사이트에서
못 뜬다.** "한 태그로 양쪽" 요건을 구조적으로 못 채운다.
→ ② 태그가 `latest` 하나뿐이라 **버전 핀이 불가능**하다. 레포의 `:X.Y.Z`/`:sha` 핀 정책과 충돌하고
재현 가능한 롤백이 안 된다. 이건 아키텍처와 무관한 독립적인 문제다.

**선택지 (고르지 않음)**

| | 내용 | 장점 | 단점 |
|---|---|---|---|
| ① | 현행 유지 — `python:3.12-slim` + PyPI 자체 빌드를 멀티아키로 | 두 아키텍처 다 성립(§A 로 검증됨). 버전 핀 유지. 추가 작업 = buildx 로 돌리는 것뿐 | 업스트림 이미지의 런타임 설정을 우리가 계속 재현해야 함 |
| ② | AWS 는 공식 arm64 이미지, 온프렘은 자체 빌드 | 업스트림 그대로 | **태그가 갈린다 = 이 작업의 전제를 정면으로 깬다.** 게다가 `latest` 라 핀 불가 |
| ③ | 공식 이미지를 amd64 로 리빌드해 우리가 매니페스트 리스트 조립 | 업스트림 Dockerfile 재사용 | 업스트림이 Dockerfile 을 공개·유지하는지 별도 확인 필요. 사실상 ①과 같은 일 |

### 그 외 — 하드코딩은 없지만 짚어둘 것 (이 PR 범위 밖)

- **`frontend/Dockerfile` 의 node 빌드 스테이지**에 `--platform=$BUILDPLATFORM` 이 없다.
  하드코딩은 아니라 안 건드렸지만, arm64 빌드 시 vite/tsc 가 QEMU 위에서 돈다. 산출물(`/app/dist`)은
  정적 파일이라 아키텍처 무관 → B-1 과 같은 패턴으로 빌더 네이티브에 고정할 수 있다.
  참고: `package-lock.json` 에 **arm64 바이너리 바인딩이 전부 들어 있다**(실측 — esbuild·rollup·
  rolldown·oxlint·tailwindcss-oxide·lightningcss 각 linux-arm64-gnu/musl). 즉 에뮬레이션으로
  돌려도 `npm ci` 자체는 성공한다. 느릴 뿐이다.
- 베이스 이미지는 **전부 멀티아키**다(실측): `python:3.12-slim` · `nginx:1.27-alpine` ·
  `node:22-bookworm-slim` · `golang:1.25.12-alpine` · `busybox:1.37.0` ·
  `docker.elastic.co/elasticsearch/elasticsearch:8.19.19`(amd64+arm64) ·
  `mcr.microsoft.com/playwright/python:v1.61.0-jammy`(amd64+arm64).
  → **베이스 때문에 막히는 이미지는 하나도 없다.**

---

## C. 서비스별 목표 아키텍처

판단 기준 = **그 이미지가 어느 사이트에서 도는가**. AWS(arm64) / 온프렘 DR(amd64) / 양쪽.
아래 워크로드 매핑은 라이브 클러스터 실측이다(2026-08-10, 읽기 전용 조회).

### 앱 티어 — 양쪽 (**amd64 + arm64**)

프로덕션 트래픽을 받는 것들. 페일오버 대상 그 자체라 한 태그가 두 아키텍처를 담아야 한다.

| 이미지 | 워크로드 | 목표 |
|---|---|---|
| `mp-account-service` | app/`mp-account` (**Rollout** — 카나리) | 둘 다 |
| `mp-recipe-service` | app/`mp-recipe` (**Rollout** — 카나리) | 둘 다 |
| `mp-pantry-service` | app/`mp-pantry` | 둘 다 |
| `mp-price-service` | app/`mp-price` | 둘 다 |
| `mp-recipebook-service` | app/`mp-recipebook` | 둘 다 |
| `mp-mealplan-service` | app/`mp-mealplan` | 둘 다 |
| `mp-notify-service` | app/`mp-notify` | 둘 다 |
| `mp-ocr-service` | app/`mp-ocr` + CronJob `mp-ocr-config-canary` | 둘 다 |
| `mp-operations-service` | app/`mp-operations` | 둘 다 |
| `mp-chat-service` | app/`mp-chat` | 둘 다 |
| `mp-video-service` | app/`mp-video` | 둘 다 |
| `mp-frontend` | app/`mp-frontend` | 둘 다 |
| `mp-ranking-serving` | app/`mp-ranking-serving` (LightGBM 서빙) | 둘 다 |

= **13종**. (`services/` 백엔드 11 + frontend + ranking-serving)

### 플랫폼·데이터 이미지 — 양쪽 (**amd64 + arm64**)

| 이미지 | 워크로드 | 목표 | 근거 |
|---|---|---|---|
| `mp-rollouts-gatewayapi-plugin` | argo-rollouts 컨트롤러 initContainer | 둘 다 | 없으면 컨트롤러 미기동 → 배포 게이트 정지. 두 클러스터 다 Rollouts 를 쓴다 |
| `mp-pgsync` | data/`mp-pgsync` | 둘 다 | PG→ES CDC. ⚠️ 정확히는 **데이터 티어가 어디서 도는가**를 따라간다 — AWS 데이터 티어 형태(EKS 내 CNPG/ECK vs 매니지드)는 미정. 양쪽 다 만들어두면 그 결정과 무관해진다 |
| `mp-elasticsearch-nori` | data/`es-es-a`·`es-es-b` (ECK) | 둘 다 | 위와 동일. 베이스 ES 8.19.19 가 이미 멀티아키라 제약 없음 |
| `mp-data-pipeline` | pipeline ns Deployment 5 + CronJob 15 | 둘 다 | 정제기(`mp-recipe-refiner`·`mp-retail-refiner`·`mp-user-event-sink`)·알림(`mp-deal-notifier`·`mp-price-anomaly-notifier`)이 프로덕션 경로다 |

🔴 **`mp-data-pipeline` 주의** — 이 **한 이미지**가 두 역할을 겸한다: 정제기·알림(프로덕션, 양쪽 필요)과
오아시스 크롤 폴러(`mp-poller-oasis-dawn`·`-noon`·`mp-poller-deal-*`). 이미지가 하나라서
**arm64 빌드는 어차피 필요**하고, 크롤 CronJob 을 AWS 에서 돌릴지 말지는 **별개의 배치 결정**이다
(nodeSelector/스케줄로 가르는 문제이지 빌드 문제가 아니다).

### 온프렘 전용 — **amd64만**

| 이미지 | 워크로드 | 목표 | 근거 |
|---|---|---|---|
| `mp-crawler-kurly` | pipeline/CronJob `mp-poller-kurly` | **amd64만** | 마켓컬리 크롤 = 온프렘 전용. playwright 베이스라 이미지가 크고(브라우저 번들) 에뮬레이션 빌드 비용이 가장 비싸다 |

참고 사실: 베이스 `mcr.microsoft.com/playwright/python:v1.61.0-jammy` 는 **arm64 도 제공한다**(실측).
즉 "온프렘 전용"은 기술 제약이 아니라 **배치 결정**이다. 나중에 AWS 로 옮기기로 하면 arm64 빌드가 가능하다.

### 요약

| 목표 | 개수 | 이미지 |
|---|---|---|
| amd64 + arm64 | **17** | 앱 13종 + rollouts-plugin · pgsync · elasticsearch-nori · data-pipeline |
| amd64만 | **1** | crawler-kurly |
| arm64만 | **0** | — (온프렘 DR 이 amd64 인 이상 arm64 단독은 성립하지 않는다) |

= Jenkinsfile 카탈로그 **18개 전부** 커버.

### 범위 밖이지만 같은 문제를 겪는 것

우리가 빌드하지 않는 **플랫폼 이미지**(Cilium · Istio · CNPG · ECK · Strimzi · Redis 오퍼레이터 ·
ArgoCD · Argo Rollouts · kube-prometheus-stack · MinIO · cert-manager · ESO · KEDA · MetalLB ·
descheduler · kubecost)도 arm64 매니페스트가 있어야 AWS 클러스터가 선다. 대부분 멀티아키를 내지만
**전수 확인은 이 조사에 포함되지 않았다** — 별도 항목으로 남긴다.

---

## D. 사전 확인 (조사만)

### D-1. GitLab CE 의 arm64 지원 — **양쪽 배포형태 모두 arm64 있음**

**공식 도커 이미지 — 있음.** 레지스트리 매니페스트 직접 조회(2026-08-10):

| 이미지 | 매니페스트 타입 | 플랫폼 |
|---|---|---|
| `gitlab/gitlab-ce:latest` | OCI image index | `linux/amd64`, `linux/arm64` |
| `gitlab/gitlab-ce:18.4.0-ce.0` | Docker manifest list v2 | `linux/amd64`, `linux/arm64` |
| `gitlab/gitlab-ee:latest` | OCI image index | `linux/amd64`, `linux/arm64` |

버전 태그에도 arm64 가 들어 있다 = `latest` 만 되는 게 아니라 **핀한 버전으로도** 쓸 수 있다.

**Omnibus 리눅스 패키지 — 있음.** 공식 문서 기준 arm64/aarch64 패키지 제공 배포판:
Ubuntu 22.04·24.04 · Debian 11·12·13 · RHEL 8·9·10 · AlmaLinux 8·9·10 ·
Amazon Linux 2·2023 · openSUSE Leap 15.6.

**🔴 단, "지원"에 단서가 붙어 있다.** GitLab 공식 문서가 명시적으로
*"Known issues exist for running GitLab on ARM"* 이라 적고 별도 에픽(gitlab-org epic #2370)을 링크한다.
커뮤니티에는 arm64 도커에서 **Gitaly** 가 안 뜨는 이슈(gitaly#4661) 보고도 있다.

→ **사실 정리**: "arm64 가 없어서 CI 서버를 x86 인스턴스로 써야 한다"는 상황은 **아니다.**
다만 arm64 는 *알려진 이슈가 있는 지원 대상*이지 amd64 와 동급의 검증 트랙이 아니다.
CI 서버 인스턴스 타입 결정 시 이 온도차를 감안할 것 — **결정은 하지 않았다.**

### D-2. 호스트 C(192.168.0.10) buildx 가능성 + 디스크

**설치는 돼 있다.**

| 항목 | 실측값 |
|---|---|
| docker | 29.6.2 |
| buildx | v0.35.0 |
| 이미지 스토어 | containerd snapshotter (`overlayfs` / `io.containerd.snapshotter.v1`) |
| CPU / RAM | 4 vCPU / 11GB (available 7GB) |

containerd 이미지 스토어가 켜져 있는 건 좋은 소식이다 — 기본 `docker` 드라이버로도
**매니페스트 리스트를 로컬에서 다룰 수 있다**(구 docker 이미지 스토어는 불가능했다).

**🔴 그런데 지금 이대로는 멀티아키 빌드가 안 된다.**

```
$ docker buildx inspect default
Platforms:  linux/amd64, linux/amd64/v2     ← arm64 없음

$ ls /proc/sys/fs/binfmt_misc/
python3.12  register  status                ← qemu-aarch64 미등록
```

arm64 를 만들려면 아래 중 하나가 선행돼야 한다 (**고르지 않음**):

| | 방법 | 장점 | 단점 |
|---|---|---|---|
| ① | QEMU binfmt 설치 (`docker run --privileged tonistiigi/binfmt --install arm64`) + `docker-container` 드라이버 빌더 | 호스트 C 한 대로 끝. 추가 인프라 0 | **느리다.** 파이썬 이미지는 휠만 풀어서 그나마 낫지만, Go/npm 컴파일은 수배~수십배. 호스트 C 는 4 vCPU 라 더 아프다 |
| ② | 원격 arm64 빌더 노드 추가 (`docker buildx create --append --platform linux/arm64 ssh://...`) — 예: Graviton EC2 | **네이티브 속도.** 각 아키텍처가 자기 기계에서 빌드 | 기계가 하나 더 필요(비용·수명주기). AWS 계정 준비가 선행 |
| ③ | 아키텍처별로 따로 빌드 후 `docker buildx imagetools create` 로 매니페스트만 조립 | 기존 파이프라인 변경 최소 | 두 빌드의 원자성이 깨진다(한쪽만 올라간 태그 가능). 조립 단계 실패 처리 필요 |

**디스크 — 🔴 지금 막히지는 않지만 여유가 얇다.**

| 항목 | 값 |
|---|---|
| 파일시스템 | `/dev/sda2` **98G 단일** (전용 docker 디스크 없음) |
| 사용 / 여유 | 51G 사용 (55%) / **42G 여유** |
| `/var/lib/containerd` | **23G** ← docker 이미지 스토어 |
| `/var/lib/docker` | 12G ← 볼륨(JENKINS_HOME·SonarQube·Harbor DB 등) |
| `/data/registry` | **3.3G** ← Harbor 블롭 전량 |
| `/var/lib/snapd` | 3.0G |
| buildx 캐시 | 2.0G (전량 reclaimable) |

평가:

- **Harbor 저장량 자체는 문제가 아니다.** 전 레포·전 태그가 3.3G 뿐이라 두 벌이 돼도 **+3.3G** 수준이다.
  42G 여유 안에서 충분하다.
- **진짜 비용은 빌더 쪽이다.** arm64 레이어가 이미 23G 인 `/var/lib/containerd` 위에 추가로 쌓이고,
  QEMU 경로로 가면 중간 레이어·캐시가 더 커진다. 크롤러(playwright 브라우저 번들)와 ML 이미지
  (scikit-learn·scipy·lightgbm)가 특히 무겁다.
- 🔴 **이 파일시스템이 차면 Harbor 가 죽고 클러스터 배포가 전면 실패한다.** OS·Harbor 블롭·
  JENKINS_HOME·SonarQube 가 전부 한 디스크에 얹혀 있어서, 빌드 캐시 증가가 배포 장애로 직결된다.
  즉 "42G 남았으니 괜찮다"가 아니라 **"공유 디스크라 여유를 태우면 안 된다"** 가 맞는 프레이밍이다.

여유를 안 태우는 선택지 (**고르지 않음**): 첫 멀티아키 빌드 전에 Harbor GC + `docker buildx prune`
(2.0G 즉시 회수) · `--output type=registry` 로 빌더가 로컬 사본을 안 남기게 하기 ·
빌드를 원격/일회성 빌더(D-2 ②)로 옮기기.

---

## 남은 것 (이 작업 범위 밖)

- CI 파이프라인을 buildx 로 바꾸는 것 — **Jenkinsfile·`.gitlab-ci.yml` 은 손대지 않았다**(CI 구조 미결정).
- 실제 멀티아키 빌드 실행 — D-2 의 선행조건(QEMU 또는 원격 빌더)과 디스크 정리가 먼저다.
- 플랫폼(서드파티) 이미지 arm64 전수 확인 — §C 말미 참조.
- requirements 버전 핀 여부 — §A 말미 참조.
