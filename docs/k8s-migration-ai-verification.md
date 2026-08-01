# K8s 이전 — AI 파트 관점 전수 검증 (2026-07-30)

> **왜 이 문서가 있나.** 2026-07-28 인프라 이전으로 실행 기반이 전부 옮겨갔다(`.9` VM compose →
> K8s `app`/`pipeline`/`data` ns). AI 파트가 배선해 둔 것들이 **어느 것은 살아 있고 어느 것은
> 죽은 경로를 가리키는지** 실측으로 가른 기록이다.
>
> 방식: 추측 금지. 라이브 클러스터·Harbor·운영 PG 에 직접 질의한 값만 적는다.
> 확인 못 한 것은 "확인 못 함"으로 남긴다.
>
> 작성 2026-07-30 · AI 파트 · 조회 경로 `k8s-master(192.168.0.17)`

---

## 0. 한 줄 결론

**코드는 대체로 준비됐고 막힌 건 배선이다.** #9(가격 이상탐지)는 이미지에 코드가 들어가 있는데
**Kafka 토픽과 스케줄이 없어** 한 건도 못 나가고, #11(영상)은 **이미지가 존재하지 않는다.**
둘 다 AI 파트가 단독으로 풀 수 없고 config 레포 권한이 필요하다.

---

## 1. 새 인프라 지형 (실측)

| 계층 | 실체 |
|---|---|
| 노드 | 4개 전부 Ready · k8s **v1.34.10** (master + worker-a1/b1/b2) |
| 앱 | `app` ns · **13 Deployment** (`mp-*`) · 게이트웨이 Istio + Gateway API HTTPRoute |
| 파이프라인 | `pipeline` ns · **CronJob 11 + 상주 컨슈머 4** |
| PG | `data` ns **CloudNativePG** `pg` (인스턴스 2, primary `pg-1`) · 접속점 **`pg-rw.data.svc`** |
| ES | ECK `es` · **green** · 3노드 · 8.19.19 |
| Kafka | Strimzi `kafka` · 4.3.0 · combined 3대 |
| Redis | opstree `mp-redis` (master/replica) + `redis-pgsync` 별도 |
| 시크릿 | **ESO**(external-secrets) · `ClusterSecretStore fb-kubernetes` → 원본 `fb-secrets/app-secrets` |
| 배포 | **ArgoCD GitOps** · 매니페스트 정본 = **별도 레포 `happyInit/mealplanning-config`** (kustomize `services/<svc>/overlays/onprem`) |
| 빌드 | **Jenkins**(`Jenkinsfile`) → Harbor `192.168.0.10/mealplanning/mp-*` · 태그 = git SHA |

**옛 경로는 죽었다**: `.9` VM 정지(인벤토리 제거·`No route to host`) · `.8` PG 는 앱이 더 이상
바라보지 않는다(`app-common.PGHOST = pg-rw.data.svc`) · GitHub Actions `build-push-app.yml` 은
**은퇴**(러너 소멸, `workflow_dispatch` 만 남음, `PROJECT: food-budget` 로 네이밍도 옛것).

---

## 2. 🔴 막힌 것 — AI 기능이 실제로 동작하지 못하는 원인

### 2.1 `price.anomaly.detected` 토픽이 없다 (#9 전면 차단)

```
존재 토픽: events.user.activity · recipe.crawl.raw · retail.crawl.raw · retail.deal.raw
브로커:    auto.create.topics.enable = false
```

**토픽이 없으면 발행이 성립하지 않는다.** 다행히 `produce_price_anomaly.py` 는 flush 후
미전달분이 있으면 `DeliveryIncomplete` 를 던지므로 **조용히 유실되지는 않는다** — 그러나
알림은 0건이다.

- 필요: `KafkaTopic` 매니페스트 1개(partitions 3 · replication 3 — 기존 토픽 관례).

### 2.2 #9 스케줄·컨슈머가 배포돼 있지 않다

`pipeline` ns 에 다음이 **없다**:

| 누락 | 코드 상태 | 근거 |
|---|---|---|
| `mp-poller-price-anomaly` (탐지·발행) | ✅ **배포 이미지에 있음** | `mp-data-pipeline` 파드에서 `detect_price_anomaly.py`·`produce_price_anomaly.py`·`_topics.py` 존재 확인 |
| fan-out 컨슈머 (`consume_price_anomaly`) | ✅ **배포 이미지에 있음** | 동일 |
| `mp-poller-recipe-review` (#10 수집) | ⬜ 미커밋 | 이미지에 `review_crawler.py` 없음 |
| `ocr-config-canary` (드리프트 감시) | ⬜ 미커밋 | 이미지에 `genai_config_canary.py` 없음 |

즉 **#9 은 코드가 이미 서버에 있고 스케줄만 없다.** 성숙도 게이트(2026-08-18)보다 이게 먼저 블로커다.

### 2.3 영상 서비스 — 이미지가 존재하지 않는다 (#11 전면 차단)

```
Harbor registry v2:
  ✅ mealplanning/mp-ocr-service    (대조군)
  ✅ mealplanning/mp-chat-service   (대조군)
  ❌ mealplanning/mp-video-service  → NOT_FOUND
```

원인은 **Jenkinsfile 카탈로그에 `video` 엔트리가 없었던 것**이다(GitHub Actions 쪽이 아니다 —
그 워크플로는 은퇴했다). **2026-07-30 추가 완료**:

```groovy
[name:'video', src:'services/video', srcs:['services/video/','ml/video-recipe/'],
               context:'.', dockerfile:'services/video/Dockerfile',
               image:'mp-video-service', test:true],
```

- `context:'.'` — chat·recipe 와 같은 이유(`ml/video-recipe` 로직 원본을 COPY, 이중화 금지).
- `srcs` 에 `ml/video-recipe/` 포함 — 로직만 고치면 `services/video/` 는 그대로인데 이미지는
  갱신돼야 한다(`data-pipeline` 의 *"SQL만 바뀌면 영원히 리빌드 안 됨"* 과 같은 함정).
- `TRACKS.app` 에도 추가(릴리스 완전세트 누락 방지).
- 검증: 변경감지 시뮬레이션 5케이스 통과(두 경로 발동 · 무관한 변경 미발동) · CATALOG 구조 정합.

### 2.4 🔴 `/api/recipes/extract` 는 라우팅부터 막혀 있다 (2.3 을 풀어도 남는다)

게이트웨이 HTTPRoute 실측:

```
mp-recipe-route      /api/recipes                                   -> recipe:8001
mp-recipebook-route  /api/recipes/book /api/recipes/mine /...shared -> recipebook:8006
```

`/api/recipes` 프리픽스가 `recipe:8001` 로 잡혀 있어 **`mp-video` 를 배포해도 `/api/recipes/extract`
요청은 recipe 서비스로 간다**(그 서비스에는 `/api/recipes`·`/api/recipes/{id}`·`/health` 3개만 있다).

→ **HTTPRoute 분리가 필수**다. `mp-recipebook-route` 가 이미 같은 방식으로 하위 경로를 떼내고
있으므로 새 패턴이 아니다(Gateway API 는 더 구체적인 경로가 우선).

**이걸 놓치면 이미지를 만들고 배포까지 해도 프론트는 계속 404 를 받는다.**

---

## 3. ✅ 살아 있는 것 (검증됨)

| 항목 | 근거 |
|---|---|
| OCR 서비스 | `mp-ocr` Running · `/api/pantry/ocr` → `ocr:8010` 라우팅 존재 |
| OCR 모델 핀 | `GEMINI_MODEL` env **미설정 → 코드 기본값 `gemini-3.5-flash-lite`** · `thinking_budget=1` — **`-latest` 별칭 아님**(파드에 직접 질의) |
| 챗 모델 핀 | `chat-config` ConfigMap `GEMINI_MODEL=gemini-3.5-flash-lite` · `GENERATOR_BACKEND=template` |
| 관심품목 API | `/api/prices/watch` GET·POST + `/{item_id}` DELETE **라이브 OpenAPI 에 존재** → 프론트 배선 3개와 정확히 일치 |
| Vertex egress | 라이브 `mp-ocr` 파드에서 `aiplatform.googleapis.com`·`oauth2.googleapis.com`·`generativelanguage.googleapis.com` **3개 모두 도달**(`app` ns 에 NetworkPolicy 없음 = 미제한) |
| 상주 컨슈머 4종 | `mp-{deal-notifier,recipe-refiner,retail-refiner,user-event-sink}` 전부 READY 1 |
| 데이터 티어 | ES **green** · Kafka READY · CNPG healthy(인스턴스 2) · PVC 전부 Bound |
| 크롤 수집 | 컬리·오아시스 일 3.3k/3.9k 행 유입 지속(최근 9일) |

---

## 4. ⚠️ 위험 — 확인했으나 AI 파트가 풀 수 없는 것

### 4.1 앱 11개 전부 `OutOfSync` + `selfHeal: false`

```
mp-account · mp-chat · mp-frontend · mp-mealplan · mp-notify · mp-ocr
mp-pantry · mp-price · mp-ranking-serving · mp-recipe · mp-recipebook   → 전부 OutOfSync (Healthy)
mp-ocr 상세: Service Synced · ExternalSecret Synced · **Deployment OutOfSync**
syncPolicy.automated = {prune:false, selfHeal:false}
```

`selfHeal:false` 라 라이브 드리프트를 되돌리지 않는다. Jenkins 는 **빌드·푸시만** 하고 배포하지
않으므로(Jenkinsfile 에 kubectl·argocd 단계 없음), 라이브 Deployment 는 **git 밖에서 갱신된
상태**다. 즉 git 매니페스트와 라이브가 어긋나 있다.

🔴 **#381 에 직접 영향**: 인프라가 Vertex env 를 git 에 커밋하고 `mp-ocr` 을 동기화하면
**Deployment 전체가 git 상태로 맞춰지며 라이브 이미지 태그도 함께 되돌아갈 수 있다.**
Vertex 코드는 **새 이미지에만** 있으므로, 순서가 어긋나면 env 는 들어가고 코드는 사라진다.

- **미확인**: 어느 필드가 다른지. config 레포 권한이 없어(404) 실제 diff 를 못 봤다.
- **권고**: 동기화 전에 `argocd app diff mp-ocr` 로 image 필드 차이를 먼저 확인.

### 4.2 인프라 컴포넌트 재시작 누적

`cilium-operator` 19·10회 · `cert-manager-cainjector` 8회 · `alloy`/`cilium`/`istio-cni` 4회.
AI 워크로드는 아니지만 **네트워크·인증서 계층**이라 간헐 장애의 배경이 될 수 있다. 인프라 판단 영역.

---

## 5. 이 검증에서 고친 것

### 5.1 `mp-chat-insights` 가 매일 가짜 실패를 남기고 있었다

파드가 `Error` 인데 로그는 `최근 대화 0건 — skip(데이터 축적 대기)` 였다. `run.py` 가 스킵에
**`return 2`** 를 쓰는데 **K8s CronJob 은 0 이 아니면 전부 Failed** 로 본다. 호스트 크론
시절에는 문제가 없던 값이 이전 후 매일 Error 파드를 만들었다.

**실제 비용**: 발견 당시 `pipeline` ns 의 Error 파드 2개 중 **하나가 이 가짜였고 다른 하나가
진짜 장애**였다. 가짜가 섞이면 사람은 Error 를 무시하기 시작하고 **진짜가 가려진다.**

→ 스킵은 `return 0`(로그로 스킵 사실 명시). **스키마 부재·DB 장애(`messages is None`)는 `return 2`
유지** — 그건 진짜 문제라 실패로 드러나야 한다. 두 경우를 구분한 것이 요점이다.

### 5.2 컬리 폴러 장애는 **이미 main 에 수정이 있었다** (내 오진 정정)

`mp-poller-kurly` 가 `ModuleNotFoundError: No module named '_topics'` 로 실패한 것을 발견하고
원인을 내 리팩터(`_topics.py` 분리)로 특정했다. 최소 이미지로 **양방향 재현**까지 했다:

```
COPY 목록에 _topics.py 포함 → OK import _kafka -> retail.crawl.raw
COPY 목록에서 제거          → ModuleNotFoundError: No module named '_topics'   (운영과 동일)
```

**그러나 main 에는 이미 수정이 있었다** — `4509f0c fix(crawler/kurly): 이미지에 _topics.py COPY
누락 — 03:30 폴러 ModuleNotFoundError`. 현재 CronJob 이미지에도 `_topics.py` 가 들어 있다(실측).
실패한 파드는 수정 **전** 이미지로 돈 것이다.

→ 내가 중복으로 넣은 Dockerfile 수정은 되돌렸다(main 버전이 임포트 드리프트 조기경보까지
포함해 더 낫다).

🔴 **여기서 더 중요한 걸 알게 됐다: 작업 브랜치가 main 보다 44 커밋 뒤처져 있다**
(`docs/ai-model-selection-benchmark` · 앞선 커밋 0). 오늘의 미커밋 작업이 전부 낡은 베이스 위에
있으므로, **머지 시 main 의 수정을 되돌리지 않도록 주의가 필요하다.**
(오늘 변경 11건은 main 에 없는 신규임을 개별 대조로 확인했다 — kurly Dockerfile 만 중복이었다.)

### 5.3 컬리 수집 공백의 실제 모양

```
07-28 18 UTC (03:00 KST 07-29)  3,390
07-29 18 UTC (03:00 KST 07-30)      0   ← 스케줄 실행 실패
07-30 00 UTC (09:00 KST 07-30)  3,412   ← 스케줄에 없는 시각(수정본으로 재실행된 것으로 보임)
```

하루치 공백이 생겼다가 메워졌다. **기준선은 소스별 28일 창을 쓰므로 1일 결손은 치명적이지
않지만**, `obs_count` 가 하루 줄어 성숙도 도달이 그만큼 늦어진다.

---

## 6. 남은 확인 (권한·의존으로 못 한 것)

| 항목 | 막힌 이유 |
|---|---|
| ArgoCD 실제 diff | `mealplanning-config` 레포 권한 없음(404) |
| `mp-video` 배포 후 동작 | 이미지 자체가 없음 → 빌드 선행 |
| #9 엔드투엔드(탐지→Kafka→알림) | 토픽·스케줄 부재 (§2.1·2.2) |
| 리뷰 16건 재처리(백로그 §1.1) | Bedrock 자격증명 + 파이프라인 이미지 재빌드 |
| 프론트 브라우저 UX | 엔드포인트는 검증됨 · 실제 클릭 미확인 |

---

## 6-B. ✅ 2026-07-30 추가 구현 — 복사만 하면 되는 매니페스트를 만들었다

"인프라에 말로 요청" 대신 **적용 가능한 매니페스트**로 바꿨다. 값은 발명하지 않고 라이브에서
추출한 뒤 **서버사이드 dry-run 으로 API 서버가 실제 수락하는지 확인**했다(경고 0 · 에러 0).

| 파일 | 리소스 | 검증 |
|---|---|---|
| `deploy/k8s/price-anomaly.yaml` | KafkaTopic + CronJob `mp-poller-price-anomaly` + Deployment `mp-price-anomaly-notifier` | ✅ dry-run 3/3 |
| `deploy/k8s/recipe-review.yaml` | CronJob `mp-poller-recipe-review` | ✅ dry-run 1/1 |
| `deploy/k8s/ocr-config-canary.yaml` | CronJob `mp-ocr-config-canary` (`app` ns · ocr 이미지) | ✅ dry-run 1/1 |
| `deploy/k8s/video-route.yaml` | Service `video` + HTTPRoute `mp-video-route` | ✅ dry-run 2/2 |

**dry-run 이 실제로 잡아낸 오류 2건** (추정으로 썼다면 그대로 실패했을 것):

1. 🔴 `KafkaTopic` apiVersion — `kafka.strimzi.io/v1beta2` 로 썼는데 **CRD 가 `v1` 만 served** 한다
   (`v1beta2` 는 더 이상 제공되지 않음) → `no matches for kind "KafkaTopic"` 로 적용 실패.
2. 🟡 PodSecurity — `pipeline` ns 는 `warn/audit=restricted`(enforce=baseline)인데 라이브 워크로드들이
   `securityContext: {}` 라 경고가 난다. 그걸 그대로 베껴 왔다가 목표 수준으로 올렸다
   (`runAsNonRoot`·uid 10001·seccomp RuntimeDefault·`readOnlyRootFilesystem`·caps drop ALL).
   `app` ns 는 **enforce=restricted** 라 카나리는 처음부터 완전 하드닝이 필요했다.

### 🔴 카나리 위치를 고쳤다 — 그 자리로는 운영에서 실행이 불가능했다

`pipelines/monitor/genai_config_canary.py` 에 뒀는데, **`mp-data-pipeline` 이미지에는 `services/` 가
없다**(라이브 파드 실측: `/app/services` 부재 — 루트 Dockerfile 이 `pipelines/`·`crawler/`·
`ml/chat-insights/` 만 COPY). 카나리는 `app.config`·`app.pipeline.backend.vision` 을 임포트한다.

→ **`services/ocr/app/config_canary.py` 로 이관**(ocr 이미지에 함께 실림). 검사 대상과 같은
이미지에 있는 것이 맞기도 하다 — 운영이 쓰는 그 코드로 검사해야 의미가 있다.
새 위치에서 재검증: 정상 `exit 0` · 드리프트 모사 `exit 1`. 단위테스트 3건 추가.
파이프라인 compose·호스트 crontab 에서 카나리 항목은 제거했다(그 이미지로는 실행 불가).

---

## 7. 인프라에 넘긴 요청

**#381** — OCR·영상 Vertex 전환 인프라 배선. 이 문서의 §2.1(Kafka 토픽) · §2.4(HTTPRoute 분리) ·
§4.1(동기화 순서 위험)을 코멘트로 보탰다. §2.3 은 우리 과제로 회수(Jenkinsfile 수정 완료).
