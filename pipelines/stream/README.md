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
| `produce_retail.py` | 리플레이/백필 — 크롤 결과 파일 → Kafka (평상시엔 크롤러 `--kafka`가 직접 produce) |
| `consume_retail.py` | retail-refiner — Kafka → `stage_record`+`refine_record` → PG |

전처리 로직은 `pipelines/ingest/load_retail.py`의 `refine_record()`(브로커 무관, 배치·스트림 공용) 재사용.

## 로컬 실행 (fb-data VM 브로커)
```bash
pip install -r pipelines/stream/requirements.txt
python pipelines/stream/create_topics.py
# 크롤러가 크롤하며 직접 Kafka produce (파일 중간단계 없음 — 평상시 경로)
python crawler/oasis/oasis_crawler.py --categories 11,142,49 --kafka
# (대안) 파일 리플레이/백필
python pipelines/stream/produce_retail.py --source oasis --file crawler/oasis/output/oasis_products_20260713.jsonl
# 컨슈머: backlog 소진 후 종료(시연) / 미설정 시 상주
CONSUME_IDLE_EXIT=6 python pipelines/stream/consume_retail.py
```

**멱등성**: at-least-once + DB upsert(product `on conflict (source,product_id)`, price·crawl_raw `on conflict do nothing`) = 사실상 exactly-once at DB. 재처리·중복 안전.

## K8s (design.md §8 토폴로지)
`deploy/k8s/retail-ingest.yaml` — Strimzi KafkaTopic · Poller CronJob(주기) · retail-refiner Deployment · **KEDA ScaledObject**(컨슈머 lag으로 0↔3 스케일). Kafka=K8s 내부, PG=외부(Service+Endpoints).
