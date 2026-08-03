# 데이터 파이프라인 설계 (pipeline ns) — 워크로드·데이터플로우 정리

> **목적**: AI 파트 설계도 마무리용 참조. K8s `pipeline` ns 의 수집·가공 워크로드 전체를 데이터플로우 기준으로 정리한다.
> **출처(SSOT)**: 매니페스트 = config 레포 `mealplanning-config/pipelines/` · 인프라 = `docs/mp_k8s_infra_object_spec.md`·`docs/mp_k8s_infra_status.md` · 네트워크 경계 = `docs/mp_netpol_zerotrust_flow.md`(pipeline=메시 밖, netpol이 유일 경계).
> **이미지**: 컨슈머·배치 = `mp-data-pipeline` / 컬리 크롤 = `mp-crawler-kurly`(Playwright 포함, 별도 이미지). WORKDIR=`/app`.

---

## 0. 한눈에

파이프라인의 일 = **레시피·상품(신선+가공)·딜·유저이벤트를 수집 → Kafka 로 흘려 → refiner 가 정규화·표준화 → PG/ES/Redis 에 적재**. 서빙(앱)은 이 적재물을 읽는다.

- **수집(크롤·유저)** → **Kafka 5토픽** → **상주 컨슈머 5**(KEDA 오토스케일) → **PG/ES/Redis**
- **배치(CronJob)** = 크롤 트리거 · 물질화뷰 갱신 · ES 재색인 · AI 배치(이상탐지·리뷰 감정/요약·대화리포트) · 정리
- **AI/ML** 은 파이프라인(재료 NER·가격 이상탐지·리뷰 감정/요약·대화 인사이트)과 앱(랭킹·챗봇·OCR·영상)에 나뉘어 있다 → **§8**.

---

## 1. 백본 아키텍처

```
[수집 소스]              [Kafka 토픽]                [상주 컨슈머]              [스토어]
마켓컬리 ─poller-kurly──┐
오아시스 ─poller-oasis──┼──▶ retail.crawl.raw ──▶ retail-refiner ──▶ PG(가격이력·retail_unit_price)
        └poller-deal────┼──▶ retail.deal.raw  ──▶ deal-notifier  ──▶ PG(deal_type) + Redis(핫딜 ZSET)
만개레시피 ─poller-recipe──▶ recipe.crawl.raw ──▶ recipe-refiner ──▶ PG(recipe/step/ingredient)
                                                    │ gazetteer 재료매칭(NER 런타임)
유저 앱 ──────────────────▶ events.user.activity ─▶ user-event-sink ─▶ PG(activity.user_event)
가격 이상탐지 배치 ─────────▶ price.anomaly.detected ─▶ price-anomaly-notifier ─▶ PG(+알림)

[Kafka 미경유 · 배치 직결]
PG ──refresh_price_matview (매시)──▶ PG matview 갱신 + Redis 가격캐시 flush
PG ──index_recipes_es (주2회)─────▶ ES (DR 폴백 색인)
PG public.recipe ──PGSync(CDC, 별도)──▶ ES (서빙 색인 recipes_pgsync)
만개 리뷰 ─review_crawler─▶ PG ─score_sentiment(Bedrock)─▶ PG ─summarize(Bedrock)─▶ PG
PG(chat) ──chat-insights (Gemini)──▶ PVC 리포트
```

> **핵심 계약 2개**: ① 크롤은 **Kafka produce 만** 하고 정규화는 refiner 가 전담(크롤러≠적재). ② `auto.create.topics.enable=false` — 토픽 생성 유일 경로 = `topics.yaml`(KafkaTopic). 사고이력(1파티션 자동생성) 기반 필수 규칙.

---

## 2. Kafka 토픽 (5)

| 토픽 | 파티션 | producer | consumer |
|---|---:|---|---|
| `retail.crawl.raw` | 3 | poller-kurly · poller-oasis | **retail-refiner** |
| `retail.deal.raw` | 2 | poller-deal-timesale/closesale | **deal-notifier** |
| `recipe.crawl.raw` | 3 | poller-recipe | **recipe-refiner** |
| `events.user.activity` | 3 | 앱(유저 클릭스트림) | **user-event-sink** |
| `price.anomaly.detected` | 3 | poller-price-anomaly (`--emit`) | **price-anomaly-notifier** |

> maxReplica 는 파티션 수를 넘지 않는다(초과 컨슈머는 논다). RF=3·min.insync.replicas=2.

---

## 3. 상주 컨슈머 (Deployment ×5 · KEDA 오토스케일)

| 컨슈머 | 명령 | 소스 → 싱크 | KEDA (min/max) | metrics |
|---|---|---|---|---|
| **retail-refiner** | `consume_retail.py` | retail.crawl.raw → PG(가격이력·단가뷰) | **0 / 3** | :9401 |
| **deal-notifier** | `consume_deal.py` | retail.deal.raw → PG(deal_type)+Redis(핫딜) | **0 / 2** | :9402 |
| **recipe-refiner** | `consume_recipe.py` | recipe.crawl.raw → PG(recipe/step/ingredient) | **1 / 3** | :9403 |
| **user-event-sink** | `consume_user_event.py` | events.user.activity → PG(user_event) | **0 / 3** | :9405 |
| **price-anomaly-notifier** | `consume_price_anomaly.py` | price.anomaly.detected → PG(+알림)·DLQ | 고정 **1** | :9407 |

- KEDA 트리거 = **Kafka lag, lagThreshold 10**(파티션당 10건 밀리면 +1). 컨슈머 3종 **scale-to-zero**(min 0), recipe-refiner 만 min 1.
- recipe-refiner 의 **gazetteer 매칭** = 재료 표준화(사전분할 NER 의 런타임 경로) + 종세분화 가드(meat canon).

---

## 4. 폴러·배치 (CronJob · KST · `concurrencyPolicy: Forbid` · `backoffLimit: 0`)

| CronJob | 스케줄(KST) | 명령 | 소스 → 싱크 | AI |
|---|---|---|---|:--:|
| poller-kurly | 03:30 | `crawler/kurly/prototype.py --kafka` | 컬리 크롤 → retail.crawl.raw | |
| poller-oasis-dawn | 04:10 | `crawler/oasis/oasis_crawler.py --categories … --kafka` | 오아시스 가격 → retail.crawl.raw | |
| poller-oasis-noon | 13:10 | 〃 | 〃 | |
| poller-deal-timesale | 15:05 | `oasis_crawler.py --deal timeSale --kafka` | 타임세일 → retail.deal.raw | |
| poller-deal-closesale | 17:05 | `oasis_crawler.py --deal closeSale --kafka` | 마감세일 → retail.deal.raw | |
| poller-recipe | 일·수 05:00 | `10k_recipe_crawler.py --kafka --order date` | 만개 크롤 → recipe.crawl.raw (PVC 상태) | |
| poller-price-matview | 매시 :20 | `refresh_price_matview.py` | PG matview 갱신 + Redis 캐시 flush | |
| poller-es-recipes | 일·수 06:30 | `index_recipes_es.py` | PG → ES 재색인(DR 폴백) | |
| **poller-price-anomaly** | 04:40 | `detect_price_anomaly.py --emit` | PG → price.anomaly.detected | ✅ 통계 이상탐지 |
| poller-recipe-review | 일·수 06:00 | `review_crawler.py` | 만개 리뷰 크롤 → **PG 직결** | |
| **score-review-sentiment** | 일·수 07:00 | `score_review_sentiment.py` | PG 리뷰 → **Bedrock nova-micro** → PG | ✅ 감정분류 |
| **summarize-reviews** | 일·수 08:00 | `summarize_reviews.py` | PG 리뷰 → **Bedrock claude-3-5-sonnet** → PG | ✅ 요약 |
| pantry-expire-recompute | 일 05:30 | `recompute_pantry_expire.py --apply` | PG 재고 소비기한 재계산 | |
| data-invariants | 월 06:00 | `data_invariants.py` | PG 데이터 불변식 주간 점검 | |

> ⚠️ `poller-recipe-review` 는 **Kafka 아니라 PG 직결**(refiner 미경유). 피크(11-12·17-18시) 회피 스태거는 원 설계 유지.

---

## 5. 프루너·정리 (CronJob)

| CronJob | 스케줄(KST) | 명령 | 대상 |
|---|---|---|---|
| deal-pruner | */10분 | `prune_deals.py` | Redis 만료 딜 ZSET 정리 |
| user-data-pruner | 04:30 | `prune_user_data.py` | PG activity/chat 원문 180일 보존정리 |
| **chat-insights** | 06:00 | `ml/chat-insights/run.py` | PG(chat) 읽기 → **Gemini** 리포트 → PVC | 

---

## 6. 데이터 스토어 접점

| 스토어 | 좌표(DNS) | 쓰는 워크로드 |
|---|---|---|
| **PostgreSQL** | `pg-rw.data.svc:5432` (**pooler 미경유·primary 직결**) | 거의 전부 |
| **Elasticsearch** | `es-es-http.data.svc:9200` | poller-es-recipes(재색인) · (서빙 색인은 PGSync 별도) |
| **Redis** | Sentinel `mp-redis-s-*.data.svc:26379` (+ master `:6379`) | deal-notifier(핫딜) · deal-pruner · price-matview(캐시) · price-anomaly |
| **Kafka** | `kafka-kafka-bootstrap.data.svc:9092` | 크롤·refiner·anomaly |

- **PGSync**(app=pgsync, 별도 워크로드) = PG `public.recipe` → ES **서빙 색인**(CDC). poller-es-recipes 의 재색인은 DR 폴백용.
- PG 접근은 **psycopg3 + `row_factory=dict_row`**, ORM/Alembic 미사용. 스키마 = `docs/prd/schema-production.sql`.

---

## 7. 외부 의존 (크롤·AI API)

| 워크로드 | 외부 대상 | 비고 |
|---|---|---|
| poller-kurly | `*.kurly.com` | Playwright(chromium), CDN 서브도메인 당김. 1~2Gi 메모리 |
| poller-oasis · deal | `www.oasis.co.kr` | requests JSON API |
| poller-recipe · review | `www.10000recipe.com` | requests HTML |
| score-review-sentiment · summarize | `bedrock-runtime.ap-northeast-2.amazonaws.com` | boto3, 정적 AWS 키 |
| chat-insights | `generativelanguage.googleapis.com` | Gemini(REPORT_GEMINI_API_KEY) |

> netpol tier-4 로 pipeline egress 는 **DNS·data 4스토어 + 위 FQDN** 만 허용, 나머지 인터넷·app ns·apiserver 는 차단(zero-trust). 상세 = `mp_netpol_zerotrust_flow.md`.

---

## 8. ⭐ AI/ML 컴포넌트 — 어디서 도나 (AI 파트 핵심)

> CLAUDE.md 커스텀 AI 로드맵 + 실제 배포 위치 매핑. **AI 는 전부 CPU**(GTX 1060 3GB → GPU 학습 불가), 예외 = 유튜브·리뷰(외부 API).

| 컴포넌트 | 종류 | 위치 | 실행 형태 | 상태 |
|---|---|---|---|---|
| **한식 재료 NER** | CRF + gazetteer | `ml/ingredient-ner` · **pipeline(recipe-refiner)** | 런타임 gazetteer 매칭 + 백필(`backfill_ner_raw_ingredients.py`) | P0 |
| **가격 이상탐지(최저가 알림)** | 통계 이상탐지 | **pipeline** | 배치 `detect_price_anomaly --emit` → Kafka → `consume_price_anomaly` | P0 · ⚠️ baseline 4주→오탐↑ |
| **리뷰 감정분류** | Bedrock nova-micro | **pipeline** | 배치 `score_review_sentiment`(주2회) | #10 |
| **리뷰 종합요약** | Bedrock claude-3-5-sonnet | **pipeline** | 배치 `summarize_reviews`(주2회) | #10 |
| **대화 인사이트** | Gemini | **pipeline** | 배치 `chat-insights`(일1회) → PVC 리포트 | — |
| 레시피 랭킹 | LightGBM | `ml/recipe-ranking` · **앱(ranking-serving)** | 서빙=앱 백엔드 / 재학습=배치(`retrain.py`) | P1 |
| 챗봇 | 의도분류+템플릿 | **앱(chat)** | 서빙=앱 백엔드 + 검색(ES/PG) | P2 |
| 영상 레시피 추출 | Gemini(Vertex) | `ml/video-recipe` · **앱(video)** | 온디맨드(유저 URL) → CRF NER | — |
| 영수증 OCR | Gemini | **앱(ocr)** | 온디맨드 | — |
| 영양소 분석 | — | 앱 | **DB 룩업(AI 아님)** | — |
| ~~할인주기 예측~~ | ~~LightGBM~~ | — | **드롭**(8주로 사이클 부족) | ❌ |

> **정리**: 파이프라인이 소유하는 AI = **재료 NER · 가격 이상탐지 · 리뷰 감정/요약 · 대화 인사이트**. 앱이 소유 = 랭킹·챗봇·영상·OCR. 신선도 예측(XGBoost, P1)은 설계상 존재하나 현 크론에는 미배치(소비기한 재계산=`pantry-expire-recompute`는 룰 기반).

---

## 9. 스케일링 모델

| 유형 | 대상 | 방식 |
|---|---|---|
| **KEDA(Kafka lag)** | 컨슈머 4 (retail·deal·recipe·user-event) | lag 10/파티션, 3종 scale-to-zero |
| **고정 replica** | price-anomaly-notifier | 1 (저빈도 토픽) |
| **CronJob** | 폴러·배치·프루너 15+ | KST 스케줄, Forbid, backoffLimit 0 |
| **수평확장 금지** | 크롤러 | 크롤 예의·중복방지 → 단일 실행(CronJob) |

- 🔴 scale-to-zero 사각지대(“lag>0인데 replica 0”) 감시 알람 = `MpConsumerIdleWithBacklog`·`MpConsumerBacklogStuck`·`MpKedaScalerErrors` (kafka-exporter 기반). 상세 = `mp_k8s_infra_status.md §5.2`.
- ⚠️ **미검증**: KEDA 콜드스타트 지연(딜 버스트 → 0→1 시간, H2/H5)은 부하테스트에서 **미실행**(`mp_k6_부하테스트.md §4.6`).

---

## 10. 설정·비밀

**ConfigMap `mp-pipeline-env`** (좌표 = 서비스 DNS):
`KAFKA_BOOTSTRAP` · `PGHOST=pg-rw.data.svc`(직결) · `PGDATABASE=foodbudget` · `PGUSER=fbapp` · `ESHOST/ESPORT` · `ES_USER=elastic` · `REDIS_SENTINELS`(Sentinel-aware) · `REDIS_MASTER_GROUP=mymaster`.

**Secret `mp-pipeline-secrets`** (ESO ← fb-secrets/pipeline-secrets):
`PGPASSWORD` · `ES_PASSWORD` · `DATA_GO_KR_SERVICE_KEY` · `REPORT_GEMINI_API_KEY` · `AWS_ACCESS_KEY_ID` · `AWS_SECRET_ACCESS_KEY`(Bedrock).

---

## 11. 운영 원칙

- **피크 회피 스태거**: 크롤·배치는 11-12·17-18시 유저피크를 피해 심야/오프피크 배치(design §8.4).
- **PriorityClass** `pipeline-low`(1000) < `app-normal` < `data-critical` → 자원 압박 시 파이프라인이 먼저 밀림(유저 보호).
- **재시도 안 함**(backoffLimit 0) — 실패는 다음 주기에 맡긴다(재시도가 크롤 소스에 연타 방지).
- **PodSecurity**: pipeline ns = enforce baseline. 신규 배치는 `runAsNonRoot`+seccomp 명시(구 이미지 root 부채는 이미지 USER 도입 후 전면 전환 예정).

---

## 부록. 소스 경로 (repo `food-budget-app`)

| 영역 | 경로 |
|---|---|
| 컨슈머(stream) | `pipelines/stream/consume_*.py` · `prune_*.py` · `_kafka.py` · `_redis.py` |
| 배치(ingest) | `pipelines/ingest/*.py` (refresh_price_matview · index_recipes_es · detect_price_anomaly · score_review_sentiment · summarize_reviews · recompute_pantry_expire · data_invariants) |
| 크롤러 | `crawler/kurly/` · `crawler/oasis/` · `crawler/10k_recipe/` |
| ML | `ml/ingredient-ner/` · `ml/recipe-ranking/` · `ml/chat-insights/` · `ml/video-recipe/` |
| 매니페스트 | config 레포 `pipelines/{consumers,pollers,pruners,scaledobjects,configmap,externalsecret}.yaml` · `platform/kafka/topics.yaml` |
