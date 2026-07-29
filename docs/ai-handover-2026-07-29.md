# AI 파트 인수인계 — 최저가 이상탐지 · 영상 재료비 (2026-07-29)

> **이 문서의 목적**: 각 담당자가 이 파일을 그대로 Claude Code에 전달하면, **무엇이 왜 바뀌었고
> 자기 쪽에서 무엇을 해야 하는지**를 추가 질문 없이 파악·작업할 수 있게 한다.
>
> 작성: AI 파트(건우) · 대상 브랜치 `docs/ai-model-selection-benchmark` · 관련 PR #333

---

## 0. 한눈에

이번 작업으로 **AI 로드맵 11개 중 9개가 구현 완료**가 됐다. 이번 회차에서 끝난 것은 두 개다.

| # | 기능 | 상태 | 핵심 산출물 |
|---|---|---|---|
| 9 | 가격 이상치 탐지 | 🟢 **완료** | 탐지 배치(A) + Kafka 발행(B) + 알림 fan-out(C) |
| 11 | 유튜브 영상분석 = **재료비 산출** | 🟢 **완료** | `services/video/app/cost.py` |
| 10 | 리뷰 감정분석 | 🔴 **데이터 없음으로 중단** | 모델은 실측으로 확정, 리뷰 수집 자체가 없음 |

**함께 해소된 것**
- `notify.notification` 에 **행을 넣는 주체가 지금까지 하나도 없었다** — 알림 목록 API(`GET /api/notifications`)는
  있는데 알림을 만드는 코드가 없어 목록이 항상 비어 있었다. 이번 fan-out 컨슈머가 **첫 writer**다.
- api-spec **#29·#30(최저가 관심 등록/해제)의 "⏸ 보류"** 를 풀었다.
- api-spec **#24·#25(영상 추출)** 의 경로 불일치를 잡았다 — 서비스는 `/api/recipes/video` 로 내고 있었는데
  계약은 `/api/recipes/extract` 였다. **프론트가 붙는 순간 404가 날 자리**였다.

---

## 1. 담당자별 할 일 (요약)

| 담당 | 해야 할 일 | 안 하면 생기는 일 | 상세 |
|---|---|---|---|
| **데이터** | `migrate_lowprice_cooldown_idx.py` 운영 1회 실행 | 알림이 쌓일수록 쿨다운 조회가 순차 스캔 → fan-out 지연 | [§2](#2-데이터-담당) |
| **데이터** | `item_unit_weight` 낱개 무게 커버리지 확인 | 영상 재료비에서 "낱개 무게 미등록"으로 산출 실패 | [§2](#2-데이터-담당) |
| **파이프라인** | 새 컨슈머 `price-anomaly-notifier` 기동 · 탐지 배치 스케줄 | 급락을 탐지해도 알림이 안 나감 | [§3](#3-파이프라인-담당) |
| **백엔드** | price 서비스에 **`JWT_SECRET` 주입** + 이미지 재빌드(PyJWT) | 관심 등록 API가 전부 401 | [§4](#4-백엔드-담당) |
| **프론트** | `/api/recipes/extract` 배선 · 관심 등록 UI | 백엔드는 준비됐는데 화면이 없음 | [§5](#5-프론트-담당) |
| **인프라** | `deploy/k8s/price-anomaly.yaml` 적용 · **KafkaTopic 필수** | 토픽 없으면 **알림이 통째로 유실**된다(실측) | [§6](#6-인프라-담당) |

---

## 2. 데이터 담당

### 2.1 반드시 해야 할 것 — 쿨다운 인덱스 운영 적용

```bash
python pipelines/ingest/migrate_lowprice_cooldown_idx.py    # 멱등: 이미 있으면 skipped
```

**왜 필요한가.** fan-out 컨슈머는 이벤트마다 "이 유저에게 이 품목을 최근 7일 안에 보냈나"를 확인한다.
이 조건이 `payload->>'item_id'` **표현식**이라 기존 인덱스(`notification_user_created_idx` 등)로는 탈 수 없다.
알림이 쌓일수록 매 이벤트가 `notify.notification` 순차 스캔이 된다.

- 정본 DDL은 `docs/prd/schema-production.sql` 에 이미 추가돼 있고, 스크립트가 **거기서 추출**한다(정본 1곳 유지).
- `apply_schema.py` 는 DROP CASCADE라 운영 재적용 금지 — 이 멱등 스크립트를 쓴다(기존 `migrate_user_chat_pref.py` 와 동일 패턴).

```sql
CREATE INDEX IF NOT EXISTS notification_lowprice_cooldown_idx
  ON notify.notification (user_id, ((payload->>'item_id')), created_at DESC)
  WHERE type = 'LOW_PRICE';
```

### 2.2 확인만 하면 되는 것 — `price.price_watch`

**조치 불필요.** 운영 DB에 이미 존재함을 확인했다(`price.price_watch`, `notify.notification`,
`notify.notification_setting`, `public.item_master` 전부 존재). 스키마 변경 없음.

### 2.3 확인 요청 — 낱개 무게(`item_unit_weight`) 커버리지

영상 재료비 산출은 분량 텍스트를 그램으로 바꿔야 값이 나온다. 변환 경로는 4가지다:
무게(`200g`) · 부피(`500ml`×밀도) · 계량(`2큰술`×밀도) · **낱개(`대파 1대` → `item_unit_weight`)**.

낱개 무게가 등록돼 있지 않으면 그 재료는 `"낱개 무게 미등록"` 사유로 **합산에서 빠진다**(총액 과소추정).
실측(돼지고기 김치찌개)에서는 10개 중 1개가 `"가격 미수집"`(청양고추)으로 빠졌다.

> 커버리지를 넓히려면 기존 `pipelines/ingest/mine_unit_weight.py` · `load_quantity_seed.py` 경로를 그대로 쓰면 된다.
> **AI 파트에서 스키마를 바꾼 것은 없다** — 데이터가 늘수록 산출률만 올라간다.

### 2.4 결정 필요 — 리뷰 데이터 (#10 리뷰 감정분석)

**현재 상태: 리뷰 데이터가 존재하지 않는다.** 운영 DB에 `review`·`comment` 계열 테이블이 하나도 없고,
`crawler/10k_recipe/` 크롤러에도 리뷰·평점 수집 코드가 없다.

- 모델은 이미 실측으로 확정돼 있다 — 감정 분류는 `apac.amazon.nova-micro-v1:0`(24/25 정확·351ms·0.0095원/건).
  즉 **데이터만 있으면 바로 구현 가능**한 상태다.
- 필요한 것: ① 리뷰 수집(크롤러 확장) ② 리뷰 스키마 ③ 감정분석 파이프라인.
- ①은 만개의레시피 리뷰 페이지를 새로 크롤하는 일이라 **수집 범위·주기·ToS 판단이 필요**하다.
  AI 파트 단독으로 정할 사안이 아니라 여기서 멈췄다.

---

## 3. 파이프라인 담당

### 3.1 새 토픽 — `price.anomaly.detected`

```python
# pipelines/stream/_topics.py
TOPIC_PRICE_ANOMALY = os.environ.get("KAFKA_TOPIC_PRICE_ANOMALY", "price.anomaly.detected")
```

- 파티션 **1개**(하루 최대 20건 · 컨슈머가 DB 쓰기에 묶여 병렬 이득 없음), retention 7d, key=`item_id`.
- `create_topics.py` 에 등록 완료. **운영 브로커(192.168.0.8:9092)에는 이미 생성해 뒀다**(검증 과정에서 생성).

> ⚠️ **브로커는 `auto.create.topics.enable=false`** 다. 토픽 없이 배치를 돌리면 `produce()` 는 성공한 것처럼
> 보이고 `flush()` 만 타임아웃해서 **알림이 조용히 전량 유실**된다. 실측으로 재현했고,
> 이제 발행기가 `DeliveryIncomplete` 예외로 즉시 실패한다.

### 3.2 새 컨슈머 — `price-anomaly-notifier`

```yaml
# docker-compose.yml (등록 완료, METRICS_PORT 9407)
price-anomaly-notifier:
  <<: *app
  command: python pipelines/stream/consume_price_anomaly.py
```

`price.anomaly.detected` → `notify.notification(type='LOW_PRICE')`.
기존 `consume_deal.py` 와 **같은 골격**이다(수동 커밋 · `COMMIT_EVERY=100` · SIGTERM graceful · `_metrics`/`_observability`).

**수신자는 3조건을 모두 통과한 유저뿐이며, `INSERT ... SELECT` 한 방으로 처리한다**(조회·삽입 사이 경쟁 제거):

1. `price.price_watch` 에 관심 등록
2. `notify.notification_setting.low_price` 가 ON (행이 없으면 기본 수신 — DDL 기본값과 동일)
3. 7일 쿨다운 경과

> **쿨다운이 멱등성도 겸한다.** 배치를 재실행하거나 컨슈머 오프셋을 되감아 같은 메시지를 다시 읽어도,
> 7일 안에 보낸 알림이 있으면 건너뛴다(at-least-once 전제에서 중복 발송 방지).

### 3.3 탐지 배치 스케줄

```bash
python pipelines/ingest/detect_price_anomaly.py            # dry-run (발행 없음)
python pipelines/ingest/detect_price_anomaly.py --emit     # 실제 발행
```

**기본이 dry-run인 이유**: 알림은 되돌릴 수 없다(유저에게 이미 나감). 명시적 `--emit` 없이는 발행하지 않는다.
k8s CronJob은 **KST 18:00**(UTC 09:00)로 잡았다 — 일 2회 크롤이 모두 반영된 뒤. `concurrencyPolicy: Forbid`.

### 3.4 ⚠️ 공유 모듈 변경 — `_kafka.py` → `_topics.py` 분리

**무엇을**: 토픽·브로커 상수를 드라이버 의존 없는 `pipelines/stream/_topics.py` 로 옮기고,
`_kafka.py` 가 그대로 **재수출**한다.

**왜 해야 했나**: `_kafka.py` 는 최상단에서 `confluent_kafka` 를 임포트한다. 그래서 **토픽 이름만 필요한
코드조차 Kafka 드라이버가 설치돼 있어야** 임포트됐고, 알림 발행 계약을 테스트할 수 없었다.

**기존 코드 영향 없음 (검증 완료)** — `from _kafka import TOPIC_*` 는 전부 그대로 동작한다.
운영 컨테이너에서 기존 컨슈머 4종(`consume_retail`·`consume_deal`·`consume_recipe`·`consume_user_event`)
임포트와 `create_topics.py` 멱등 재실행까지 확인한 뒤 원상복구했다.

---

## 4. 백엔드 담당

### 4.1 ⚠️ 필수 — price 서비스에 `JWT_SECRET` 주입

price 서비스에 **인증이 처음 생겼다**. 관심 등록/해제는 유저 귀속 데이터라 `user_id` 를 **JWT에서만** 받는다(A01).

```env
# price 서비스 환경변수 — account 서비스와 "같은 값"이어야 한다
JWT_SECRET=<account와 동일>
JWT_ALG=HS256
```

- 안 넣으면 코드 기본값(`dev-insecure-change-me`)으로 뜨고 **모든 관심 등록 요청이 401** 이 된다.
- `requirements.txt` 에 `PyJWT>=2.8` 추가 → **이미지 재빌드 필요**.
- 검증 전용 모듈(`app/security.py`)이며 **발급·bcrypt 없음**. notify·recipebook·mealplan·pantry가
  쓰는 것과 동일한 패턴의 복사본이다(검증 규약이 갈리면 account 토큰과 호환이 깨진다).
- **기존 조회 API(현재가·이력·핫딜·품목검색)는 그대로 공개**다. 인증은 관심 등록 라우트에만 붙였다.

### 4.2 새 엔드포인트 (api-spec #29·#30)

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/prices/watch` | 관심 등록. body `{"item_id": int}`. **멱등** — 중복 등록은 409가 아니라 `created:false` |
| `DELETE` | `/api/prices/watch/{item_id}` | 관심 해제. 없으면 404 |
| `GET` | `/api/prices/watch` | 내 관심 목록 (**api-spec 미기재 — 추가 명세 필요**) |

> `GET` 은 명세에 없지만, 등록/해제 UI가 현재 상태를 보여주려면 필요해서 추가했다.
> api-spec에 `29b` 로 기재해 뒀으니 **명세 담당이 확인 후 확정**해 주면 된다.

> ⚠️ **라우트 순서**: `/api/prices/watch` 는 `/api/prices/{item_id}` 보다 **먼저** 선언해야 한다.
> 뒤에 두면 `item_id="watch"` 로 잡혀 422가 난다. 회귀 테스트로 고정해 뒀다.

### 4.3 notify 서비스 — 코드 변경 없음, 동작만 달라짐

`notify` 코드는 **건드리지 않았다.** 다만 지금까지 비어 있던 `notify.notification` 에
실제로 행이 쌓이기 시작한다. `GET /api/notifications` 가 이제 결과를 돌려준다.

- 알림 `payload` 에 `item_id`·`drop_pct`·`is_record_low`·`anomaly_id` 가 들어간다 → 프론트가 품목 상세로 딥링크 가능.
- `notification_setting.low_price` 가 **실제로 존중된다** — 끈 유저에게는 생성되지 않는다.

### 4.4 video 서비스 — 경로 변경 (⚠️ 파괴적 변경)

```
POST /api/recipes/video        →  POST /api/recipes/extract
GET  /api/recipes/video/{id}   →  GET  /api/recipes/extract/{id}
```

**왜**: api-spec #24·#25 계약이 `/api/recipes/extract` 인데 서비스가 다른 경로로 내고 있었다.
프론트가 붙는 순간 404가 날 자리라 **계약 쪽으로 맞췄다**. 아직 프론트 미배선이라 실사용 영향은 없다.
게이트웨이(`frontend/nginx.conf`)에 `location /api/recipes/extract → video:8011` 추가 완료.

---

## 5. 프론트 담당

### 5.1 영상 추출 (#24·#25) — 백엔드 준비 완료

```
POST /api/recipes/extract        {"url": "https://youtu.be/..."}  → 202 {job_id, status, from_cache}
GET  /api/recipes/extract/{jobId}                                  → {status, ingredients, steps, cost, ...}
```

목업(`YoutubeExtract.tsx`)에 그려둔 **파이프라인 5단계 중 ①~④가 실제로 동작한다**
(①사전필터·캐시 ②Gemini 추출 ③NER 정규화 **④가격 산출**). ⑤레시피북 저장만 남았다.

### 5.2 ⚠️ 재료비 표기 규칙 — 총액만 보여주면 안 된다

응답의 `cost` 는 **항상 과소추정**이다. 모르는 값을 지어내지 않기 때문이다.

```jsonc
"cost": {
  "total_krw": 1138,          // 산출된 재료만 합산
  "per_serving_krw": null,    // 인분 미상이면 null
  "priced_count": 2,          // 실제로 값이 나온 재료 수
  "total_count": 10,          // 전체 재료 수
  "excluded_count": 7,        // 상비 양념·물/육수 — 뺀 것이지 실패가 아니다
  "lines": [ { "name": "대파", "matched_name": "대파", "krw": 148, "grams": 46.7, "basis": "piece" },
             { "name": "청양고추", "krw": null, "reason": "가격 미수집" } ]
}
```

- **`priced_count/total_count` 를 총액과 함께 반드시 노출**한다(예: "10개 중 2개 기준 · 1,138원~").
  총액만 보여주면 유저가 실제보다 싸다고 오해한다.
- `krw: null` 인 항목은 사유(`분량 표현이 모호` · `낱개 무게 미등록` · `가격 미수집` · `품목 매칭 실패`)를 그대로 보여주면 된다.
- `excluded_count` 는 **실패가 아니다** — 소금·간장·물처럼 집에 있다고 보는 재료다. "상비 재료 제외" 라고 안내한다.
- `servings_known: false` 면 인분을 모르는 것이다 → **1인분 단가를 만들어 보여주지 말고** 직접 입력을 유도한다.

### 5.3 관심 등록 UI (#29·#30)

`POST/GET /api/prices/watch`, `DELETE /api/prices/watch/{item_id}` (§4.2). **Authorization 헤더 필수.**
등록해 두면 급락 시 알림 탭에 `LOW_PRICE` 알림이 뜬다(같은 품목은 7일에 한 번).

---

## 6. 인프라 담당

### 6.1 새 매니페스트 — `deploy/k8s/price-anomaly.yaml`

세 오브젝트: **KafkaTopic**(Strimzi) · **CronJob**(탐지 배치) · **Deployment**(fan-out 컨슈머).

> ⚠️ **KafkaTopic 은 선택이 아니다.** 브로커가 `auto.create.topics.enable=false` 라 토픽이 없으면
> 발행이 전량 미전달로 끝난다(실측 재현). 이제 배치가 `DeliveryIncomplete` 로 실패하므로 조용히 넘어가진 않는다.

### 6.2 ⚠️ 네이밍 규약 불일치 — 정합화 필요

이 파일은 **클러스터 실제 규약**(`app` 네임스페이스 · `mp-` 프리픽스 · PodSecurity restricted)으로 작성했다.
반면 같은 디렉터리의 **`retail-ingest.yaml`·`recipe-ingest.yaml` 은 구 규약(`fb-app` ns · `fb-kafka`/`fb-pg`)** 이다.

- 이전 단계에서 **레포 전체를 한 번에 정합화**해야 한다. 새 파일만 신규 규약이라 지금은 섞여 있다.
- ConfigMap/Secret 이름도 `mp-kafka`·`mp-pg` 로 가정했다 — 실제 이름과 다르면 맞춰 주면 된다.
- 이미지는 `<ECR>/food-budget-app:latest` placeholder.

### 6.3 컨슈머 스케일 방침

`replicas: 1` 고정이다(KEDA 대상 아님). 하루 한 번 최대 20건이라 스케일할 물량이 아니다.
다중 인스턴스여도 fan-out이 `INSERT ... SELECT` 한 방이라 중복은 나지 않는다(경쟁 안전).

### 6.4 video 서비스

포트 **8011**, 이미지 `192.168.0.10/food-budget/video-service`, compose profile `video`.
게이트웨이에 `/api/recipes/extract → video:8011` 라우팅 추가됨. k8s 매니페스트는 이전 단계에서 함께 작성.

---

## 7. 검증 기록 (실물)

전부 **실 Kafka·실 운영 PG**로 확인했고, DB 변경은 롤백해 **운영 무변경**이다.

| 대상 | 방법 | 결과 |
|---|---|---|
| Kafka 왕복 | 실 토픽에 발행 → 소비 | key=42 · 한글 보존 · 메시지 완전 일치 **PASS** |
| 유실 감지 | 없는 토픽으로 발행 | `DeliveryIncomplete` 즉시 발생 **PASS** |
| fan-out 수신자 | 운영 PG에 임시 유저 4명 | 등록·설정ON·쿨다운밖만 수신, 나머지 3명 제외 **PASS** |
| 쿨다운 만료 | 기존 알림을 8일 전으로 | 재수신됨 **PASS** |
| 롤백 | 트랜잭션 롤백 후 조회 | 잔여 0건 **PASS** |
| 공유모듈 회귀 | 기존 컨슈머 4종 임포트 + `create_topics.py` | 전부 정상 **PASS** |
| 영상 재료비 | 실 영상 `youtu.be/qWbHSOplcvY` | item_id 9/10 매칭 · 상비 7건 제외 · 총 1,138원 **PASS** |
| 상비 목록 일치 | chat vs video 세트 비교 | 57개 **완전 일치** |
| 테스트 | pipelines 23 · price 6 · video 22 | **51 passed** |

### 실측에서 잡은 결함 3건 (모두 회귀 테스트로 고정)

1. **토픽 미생성 시 알림 전량 유실이 조용했다** — `flush()` 반환값을 버려서 배치가 "발행 완료"를 찍고 끝났다.
   → 반환값 검사 후 `DeliveryIncomplete`.
2. **토픽 이름을 알려면 Kafka 드라이버가 필요했다** — 알림 계약을 테스트할 수 없었다. → `_topics.py` 분리.
3. **상비 재료 판정이 원문 재료명 기준이었다** — "신 김치"가 상비 목록(`김치`)에 걸리지 않아
   김치찌개 총액의 **84%(8,700원)** 가 오염됐다. → 챗과 동일하게 **표준명 기준**으로 판정.

---

## 8. 남은 것

| 항목 | 상태 | 필요한 결정/작업 |
|---|---|---|
| #10 리뷰 감정분석 | 🔴 중단 | **리뷰 수집 여부·범위 결정**(§2.4). 모델은 확정돼 있어 데이터만 있으면 바로 구현 |
| #8 이상징후 대시보드 | ⬜ 예정 | 인프라/클라우드 담당 트랙 |
| 이미지·YAML 일괄 준비 | ⬜ 다음 단계 | 기능 구현 마무리 후 착수 (구·신 네이밍 규약 정합화 포함, §6.2) |
| 프론트 배선 | ⬜ | #24·#25 영상추출 · #29·#30 관심등록 |

---

## 부록. 이번 회차 변경 파일

**신규**
```
pipelines/stream/produce_price_anomaly.py     최저가 급락 → Kafka 발행
pipelines/stream/consume_price_anomaly.py     → notify.notification fan-out
pipelines/stream/_topics.py                   토픽 상수(드라이버 비의존)
pipelines/ingest/migrate_lowprice_cooldown_idx.py   쿨다운 인덱스 멱등 마이그레이션
pipelines/ingest/tests/test_consume_price_anomaly.py
services/price/app/security.py                JWT 검증(발급 없음)
services/video/app/cost.py                    재료비 산출
services/video/app/vendor/quantity.py         분량→그램 정본 컨버터(챗·레시피와 동일)
services/video/tests/test_cost.py
deploy/k8s/price-anomaly.yaml                 KafkaTopic + CronJob + Deployment
```

**수정**
```
pipelines/stream/_kafka.py                    상수 → _topics 재수출(호환 유지)
pipelines/stream/create_topics.py             price.anomaly.detected 등록
pipelines/ingest/detect_price_anomaly.py      --emit 플래그(기본 dry-run)
services/price/app/{main,models,queries,config}.py   관심 등록 CRUD + 인증
services/price/requirements.txt               PyJWT 추가 → 이미지 재빌드 필요
services/video/app/{main,models}.py           재료비 배선 + 경로 정렬
docker-compose.yml                            price-anomaly-notifier(9407)
frontend/nginx.conf                           /api/recipes/extract → video:8011
docs/prd/schema-production.sql                쿨다운 부분 인덱스
docs/{ai-spec,ai-features-roadmap,design/api-spec}.md
```
