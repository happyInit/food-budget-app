# `deploy/k8s/` — K8s 매니페스트 **제안본** (정본 아님)

> 🔴 **라이브 매니페스트 정본은 이 레포가 아니다.**
> 배포는 ArgoCD GitOps 이고 정본은 별도 레포 **`happyInit/mealplanning-config`** 에 있다
> (kustomize · `services/<svc>/overlays/onprem` · `pipelines/`).
> AI 파트는 그 레포 권한이 없어 직접 PR 할 수 없다 → **여기 있는 것은 인프라 담당이 복사해 넣을
> 수 있도록 준비한 제안본**이다. 인프라 요청 창구 = 이슈 **#381**.

---

## 파일 상태 (2026-07-30 기준)

| 파일 | 상태 | 비고 |
|---|---|---|
| `price-anomaly.yaml` | ✅ **라이브 검증** (3) | KafkaTopic + 탐지 CronJob + fan-out Deployment. #9 |
| `recipe-review.yaml` | ✅ **라이브 검증** (1) | 요리후기 수집 CronJob. #10 입력 |
| `review-pipeline.yaml` | ✅ **라이브 검증** (3) | 감정분류·요약·템플릿 CronJob. #10 — 🔴 AWS 자격증명 대기(2개 `suspend: true`) |
| `ocr-config-canary.yaml` | ✅ **라이브 검증** (1) | 모델 드리프트 주간 카나리. `app` ns · **ocr 이미지** |
| `video-route.yaml` | ✅ **라이브 검증** (4) | ExternalSecret + Deployment + Service + HTTPRoute. #11 |
| `gcp-sa-secret.yaml` | ✅ **라이브 검증** (1) | GCP SA 키 ExternalSecret. **단독 apply 가능** |
| `patch-mp-ocr-vertex.yaml` | ⚙️ **kustomize 패치** | mp-ocr Vertex 전환. 🔴 단독 apply 불가(의도적 — 부분 Deployment) |
| `recipe-ingest.yaml` | ⚠️ **낡음** | ns `kafka` · `<ECR>` 이미지 = 이전 전 추정 규약. 해당 워크로드는 이미 `pipeline` ns 에 다른 이름으로 살아 있다 |
| `retail-ingest.yaml` | ⚠️ **낡음** | 위와 같음 |
| `redis-ha.yaml` | ⚠️ **참고용** | 실제 Redis 는 opstree operator(`data/mp-redis`)로 떠 있다 |

**"라이브 검증"의 의미**: 값을 발명하지 않고 **라이브 클러스터에서 추출**한 뒤,
**서버사이드 dry-run 으로 API 서버가 실제로 수락하는지 확인**했다 — 경고 0 · 에러 0.

```bash
kubectl apply --dry-run=server -f deploy/k8s/<file>.yaml
```

---

## 이 디렉터리를 다시 쓰게 된 이유

이전 버전들은 **추정 규약**으로 작성돼 있어 그대로 적용하면 전부 실패했다. dry-run 이 잡아낸 실제 오류:

| 추정했던 값 | 라이브 실제 값 |
|---|---|
| `kafka.strimzi.io/v1beta2` | **`kafka.strimzi.io/v1`** (v1beta2 는 더 이상 served 되지 않음 → 적용 실패) |
| KafkaTopic ns `kafka` · cluster `mp-kafka` | ns **`data`** · cluster **`kafka`** |
| 워크로드 ns `app` | 파이프라인은 **`pipeline`** |
| envFrom `mp-kafka` · `mp-pg` | **`mp-pipeline-env`** + **`mp-pipeline-secrets`** |
| `<ECR>/food-budget-app:latest` | **`192.168.0.10/mealplanning/mp-data-pipeline:<sha>`** |
| partitions/replicas 1 | **3/3** (기존 토픽 관례) |
| UTC 스케줄 문자열 | **`timeZone: Asia/Seoul`** + KST 시각 |
| `priorityClassName` 없음 | **`pipeline-low`** |
| securityContext 없음 | PodSecurity: `pipeline`=enforce **baseline**/warn **restricted**, `app`=enforce **restricted** |

**교훈: 매니페스트는 추정으로 쓰면 안 된다.** 라이브에서 뽑고 dry-run 으로 확인해야 한다.

---

## 클러스터 지형 요약 (실측)

```
노드 4 · k8s v1.34.10
app       ns  Deployment 13(mp-*) · Istio 사이드카 · Gateway API HTTPRoute · enforce=restricted
pipeline  ns  CronJob 11 + 상주 컨슈머 4 · priorityClass pipeline-low · enforce=baseline
data      ns  CNPG pg(접속점 pg-rw.data.svc) · ECK es(green) · Strimzi kafka 4.3.0 · opstree mp-redis
시크릿    ESO ClusterSecretStore fb-kubernetes → 원본 fb-secrets/app-secrets
빌드      Jenkins(Jenkinsfile) → Harbor 192.168.0.10/mealplanning/mp-* : git SHA
배포      Jenkins CD 스테이지가 config 레포에 :sha 핀 → ArgoCD auto-sync
```

⚠️ **`auto.create.topics.enable=false`** — 토픽은 반드시 `KafkaTopic` 으로 사전 생성.

---

## 적용 순서 (의존관계)

1. `price-anomaly.yaml` 의 **KafkaTopic 먼저** — 토픽 없이 탐지를 돌리면 발행이 성립하지 않는다
   (조용히 유실되지는 않는다: 발행기가 `DeliveryIncomplete` 로 즉시 실패).
2. 그다음 CronJob·Deployment. **`mp-pipeline-consumers` PodMonitor 에 `price-anomaly-notifier`
   추가를 잊지 말 것** — 안 넣으면 메트릭이 조용히 수집되지 않는다.
3. `recipe-review.yaml`·`ocr-config-canary.yaml` 은 **코드 병합·이미지 빌드 후** 새 `:sha` 로 핀.
   현재 라이브 이미지에는 해당 스크립트가 아직 없다(실측 확인).
4. `video-route.yaml` — `Jenkinsfile` 카탈로그에 `video` 엔트리를 2026-07-30 에 추가했으므로
   병합·빌드 후 이미지가 생긴다. `fb-secrets/app-secrets` 에 `VIDEO_GEMINI_API_KEY` 추가가 선행.
5. `review-pipeline.yaml` — 🔴 **선행 블로커 2건**: ①`boto3` 가 이미지에 없다(requirements 에
   추가했으므로 재빌드로 해소) ②**클러스터에 AWS 자격증명이 없다**(인프라 요청 필요).
   그래서 Bedrock 쓰는 2개는 `suspend: true`, 자격증명 불필요한 템플릿 채움만 `false` 로 뒀다.
6. `gcp-sa-secret.yaml` → `patch-mp-ocr-vertex.yaml` 순서. 패치는 kustomize 로만 적용된다.

### 일회성이라 CronJob 을 두지 않은 것
`pipelines/ingest/backfill_ner_raw_ingredients.py`(#5 RAW 구조화)는 **일회성**이다.
`ner_status='RAW'` 1,143행이 전부 과거분(`max_id=93743`, 현재 id 는 150725까지)이고 신규 유입은
`CRAWLER` 로 들어온다(`consume_recipe.py` 는 CRF 를 쓰지 않는다 — 크롤러 사전분할+gazetteer).
멱등하므로(`_ALREADY` 로 기존 NER_PARSED 레시피 제외) 재발 시 수동 1회로 충분하다.
재발 감시 쿼리:
```sql
select ner_status, count(*), max(id) from recipe_ingredient group by 1;   -- RAW 의 max(id) 가 오르면 재발
```

관련 문서: `docs/k8s-migration-ai-verification.md` · `docs/ai-work-risk-review-2026-07-30.md`
