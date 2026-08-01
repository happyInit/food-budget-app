# 소매 수집 스트림 파이프라인 (Kafka)

`design.md §7.1` 수집 파이프라인 구현. 주기 크롤 → Kafka → 컨슈머 전처리 → 현재 테이블(crawl_raw/retail_*).

```
[크롤러 CronJob]  oasis_crawler --kafka  (크롤하며 직접 produce, 일1~2회)
      │  key=source:product_id · value=원본JSON · header source
      ▼
  Kafka  retail.crawl.raw  (3 파티션)
      │  consume  (group retail-refiner, 수동커밋)
      ▼
[retail-refiner]  정규화(retail_norm) + 매칭(gazetteer) + 적재
      │           = load_retail.refine_record (배치와 동일 로직 재사용)
      ▼
  crawl_raw(원본 durable) + retail_product/retail_price(정제) + 단가 뷰
```

**Kafka의 역할** = 대량 스트리밍이 아니라 **이벤트-드리븐 디커플링 + 예측가능 버스트 흡수**(§8.1). 파싱은 Kafka가 아니라 **컨슈머**가 함. 저볼륨(~5k SKU/폴)이라 스루풋용 아님 — 크롤러⊥처리 분리 · 재처리(replay) · KEDA 오토스케일 시연.

## 파일
| 파일 | 역할 |
|---|---|
| `_kafka.py` | 브로커 설정(env `KAFKA_BOOTSTRAP`, 기본 192.168.0.8:9092) · 토픽 상수 · 프로듀서/컨슈머 팩토리 |
| `create_topics.py` | 토픽 생성(멱등). K8s에선 Strimzi KafkaTopic가 대체 |
| `produce_price_anomaly.py` | 최저가 급락 → `price.anomaly.detected` 발행. 미전달 시 `DeliveryIncomplete` |
| `consume_price_anomaly.py` | 위 토픽 → `notify.notification(LOW_PRICE)` fan-out(관심등록·설정ON·7일 쿨다운) |
| `produce_retail.py` | 리플레이/백필 — 크롤 결과 파일 → Kafka (평상시엔 크롤러 `--kafka`가 직접 produce) |
| `consume_retail.py` | retail-refiner — `retail.crawl.raw` → `stage_record`+`refine_record` → PG |
| `consume_deal.py` | deal-notifier — `retail.deal.raw` → PG(deal_type/timedeal_end) + Redis 핫딜 |
| `_redis.py` | Redis 핫딜 저장 — ZSET `retail:deals:active`(마감 score) + HASH 상세 |
| `prune_deals.py` | 만료 딜 정리 — 마감 지난 딜 제거(CronJob 10분 / `--loop`). PG는 이력 보존, Redis만 정리 |
| `produce_recipe.py` | 만개 레시피 Poller — CSV(build_recipe_records) → `recipe.crawl.raw` |
| `consume_recipe.py` | recipe-refiner — `recipe.crawl.raw` → `process_recipe`(재료 gazetteer 매칭) → PG |

전처리 로직은 `pipelines/ingest/load_retail.py`의 `refine_record()`(브로커 무관, 배치·스트림 공용) 재사용.

## 딜(핫딜) 경로 — §7.1 `딜 → PG + Redis`
크롤러가 `deal_type`(closeSale/timeSale) 레코드를 **`retail.deal.raw` 토픽으로 라우팅**(일반은 retail.crawl.raw).
`deal-notifier` 컨슈머가 PG(가격이력, deal_type/timedeal_end) **+ Redis 핫딜**(`retail:deals:active` ZSET, 마감 epoch score → API가 마감임박 조회·fan-out) 적재. Redis 없으면 PG만(graceful).
```bash
python crawler/oasis/oasis_crawler.py --deal closeSale --kafka   # 마감세일 17시 오픈
CONSUME_IDLE_EXIT=6 python pipelines/stream/consume_deal.py
```

## 레시피 경로 — §7.1 `만개(주1회) → Kafka → 매칭 → PG`
`build_recipe_records()`가 4 CSV를 **레시피별 중첩레코드**(재료·스텝)로 합쳐 `recipe.crawl.raw`로 발행.
`recipe-refiner` 컨슈머가 `process_recipe`(배치와 동일)로 재료 gazetteer 매칭 + recipe/step/ingredient 적재. 멱등 upsert. (NER=크롤러 사전분할+gazetteer, ES 색인은 후속.)
```bash
python pipelines/stream/produce_recipe.py --limit 20
CONSUME_IDLE_EXIT=6 python pipelines/stream/consume_recipe.py
```
K8s: `deploy/k8s/recipe-ingest.yaml` (KafkaTopic·recipe-poller CronJob 주1회·recipe-refiner·KEDA).

## 로컬 실행 (fb-data VM 브로커)
```bash
pip install -r pipelines/stream/requirements.txt
python pipelines/stream/create_topics.py
# 크롤러가 크롤하며 직접 Kafka produce (파일 중간단계 없음 — 평상시 경로).
# 오아시스·컬리 둘 다 같은 토픽으로 발행(header source=oasis|kurly) → 동일 컨슈머가 처리.
python crawler/oasis/oasis_crawler.py --categories 11,142,49 --kafka
python crawler/kurly/prototype.py --kafka        # Playwright 필요
# (대안) 파일 리플레이/백필
python pipelines/stream/produce_retail.py --source oasis --file crawler/oasis/output/oasis_products_20260713.jsonl
# 컨슈머: backlog 소진 후 종료(시연) / 미설정 시 상주
CONSUME_IDLE_EXIT=6 python pipelines/stream/consume_retail.py
```

**멱등성**: at-least-once + DB upsert(product `on conflict (source,product_id)`, price·crawl_raw `on conflict do nothing`) = 사실상 exactly-once at DB. 재처리·중복 안전.

## 배포 — Docker (현재 타깃)
Kafka/PG/Redis는 fb-data VM에 도커로 상주(외부). 파이프라인은 `Dockerfile`+`docker-compose.yml`.
```bash
docker compose build
docker compose run --rm create-topics          # 최초 1회 (tools 프로필)
docker compose up -d                            # 상주: retail-refiner·deal-notifier·recipe-refiner·deal-pruner
# 폴러(주기) = host cron으로 on-demand run:
docker compose run --rm poller-oasis            # 오아시스 가격 (일1~2회)
docker compose run --rm poller-deal-timesale    # 타임세일 (15시)
docker compose run --rm poller-deal-closesale   # 마감세일 (17시)
docker compose run --rm poller-recipe           # 만개 레시피 (주1회, RECIPE_CSV_HOST 마운트)
```
설정은 `.env`(KAFKA_BOOTSTRAP·PG*·REDIS_URL). 컨슈머 상주 1replica(오토스케일 X).

**Harbor 푸시** — 🔴 **수동 푸시는 하지 않는다 (2026-07-31 정리).**

빌드·push 정본은 **Jenkins**(레포 루트 `Jenkinsfile`)다. 종전의 `deploy/push.sh` 는 **삭제**했다 — 호출자가 없었고,
기본 좌표가 **존재하지 않는 프로젝트**(구 `food-budget/`)를 가리켰으며, 무엇보다 CI 밖에서 임의 태그를 밀 수 있어
**3태그 정책**(`:<sha>` + 릴리스 런에서만 `:X.Y.Z` + `:latest`)을 우회하는 통로였다.

현행 좌표 = `192.168.0.10/mealplanning/{mp-data-pipeline,mp-crawler-kurly}`. 로컬에서 이미지를 직접 만들어
띄워 볼 일이 있으면 push 하지 말고 build override 만 쓴다:
```bash
# self-signed HTTPS → /etc/docker/daemon.json 에 "insecure-registries":["192.168.0.10"] 후 docker 재시작
docker login 192.168.0.10        # pull 용
docker compose -f docker-compose.yml -f docker-compose.build.yml build
docker compose up -d
```
⚠️ `.env` 가 가리키던 데이터 티어 `192.168.0.8` 은 파괴됐다 — 엔드포인트를 직접 갈아끼워야 뜬다.
이미지 2개: `data-pipeline`(컨슈머·오아시스·레시피·pruner) · `crawler-kurly`(Playwright). 폴러=`poller-kurly` 서비스.

## K8s (후속 — design.md §8 토폴로지)
`deploy/k8s/*.yaml` — Strimzi KafkaTopic · Poller CronJob · Deployment · **KEDA ScaledObject**(lag 0↔N). 클러스터 도입 시. 지금은 Docker.
