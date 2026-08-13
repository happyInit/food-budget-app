# mp_ai_pre_migration_plan.md — AI 트랙 이관 전 정비 계획

> 작성 2026-08-13 · 담당 = AI·알림 파트
> 대상 이슈 = **#608 · #616 · #617** + 실측으로 드러난 결함 1건(클릭스트림 조인 단절)
> 근거 = 레포 전수 조회 · **클러스터 읽기전용 실측** · 로컬 테스트 99건 통과
> 관련 정본 = `docs/mp_aws_prep_checklist.md` (**C-83 신설** · C-14 · C-20 · C-30 · C-44 · C-68 · C-72 · C-77 · `1-14` · `1-15` · `1-21`)

---

## 0. 요약 — 리뷰어가 먼저 볼 것

**무엇을 하려는가**
AWS 이관 **전에** AI 트랙의 코드 결함을 없앤다. 이관 후에 발견하면 되돌리기가 비싸거나 아예 불가능한 것들이다.

**왜 지금인가 (3줄)**
1. **클릭스트림이 켜져 있는데 학습 라벨이 0건이다** — 프론트가 조인 키를 안 보내서 3주간 아무도 몰랐다. 데이터 축적은 **시간이 드는 유일한 항목**이라 이관 후로 미루면 그만큼 잃는다.
2. **`video` 의 Redis 재시도 부재**는 정본이 🔴🔴 *"선택 아님"* 으로 못박은 **C-14(ElastiCache) 선행**이다.
3. **Kafka 가 사라지면(C-44) 지금 도는 클릭스트림이 조용히 멈춘다** — 코드가 fail-open 이라 아무 신호도 안 난다.

**이 계획이 인프라를 바꾸는가 → 아니다**
Terraform 리소스 추가 **0** · IRSA 주체 추가 **0** · 노드 사이징 **불변**. 오히려 워크로드 2종(**−100m / −256Mi**)과 KEDA ScaledObject 1개가 **줄어든다**. 상세 = §6.

**무엇을 안 하는가**
온프렘 오브젝트 소거 · Kafka 경로 제거 · retrain 워크로드 신설 — **전부 이관 시점 이후**다(C-72). 상세 = §8.

---

## 1. 배경 — 세 이슈는 따로가 아니다

이슈 3건이 각각 올라왔지만, 실측해보니 **#608 과 #616 은 같은 데이터 흐름의 양 끝**이었다.

```
#608  클릭스트림을 무엇으로 나를 것인가
        └→ activity.user_event · activity.recipe_impression 에 데이터가 쌓인다
              └→ #616  그 데이터로 ranker.pkl 을 재학습할 것인가
                        └→ 재학습 빈도가 모델 패키징 방식(C-20)을 정한다

#617  video Redis 재시도 — 독립. C-14 선행이라 별개 트랙으로 진행 가능
```

그래서 **#608 을 먼저 풀면 #616 이 따라 풀린다.** 이 계획도 그 순서를 따른다.

---

## 2. 실측 결과 — 기존 문서 4건이 사실과 달랐다

클러스터 조회는 **읽기 전용만** 수행했다(`kubectl get` · `psql SELECT`). 변경한 것은 없다.

| 항목 | 문서가 말하던 것 | 실측 (2026-08-13) |
|---|---|---|
| 클릭스트림 플래그 | 꺼져 있다 · 클러스터 override 0건 | ✅ **`EVENT_PRODUCE_ENABLED = true`** (`app/mealplan-config`) |
| 발행량 | 0 msgs/24h | ✅ **실제로 흐른다** — `mp-user-event-sink` KEDA **ACTIVE 1/1** |
| `activity` 스키마 | 라이브 DB 미마이그레이션 | ✅ **4개 테이블 전부 실재** — `activity_ready()` 통과 |
| 클릭스트림 배선 | 미배선 · 실호출 0건 | ✅ **배선돼 있다** — `services/mealplan/app/events.py` 자체 경로 |

**실제 적재량**

```
activity.user_event         44 행   전부 ADD_CART   최신 2026-08-13 01:01
activity.recipe_impression 320 행                   최신 2026-07-22 03:24  ← 정지
activity.recipe_popularity   0 행
```

**부수 확인**

- `mp-poller-price-anomaly` CronJob 이 **`--emit` 을 달고** 매일 04:40 KST 에 실행 중 → `price.anomaly.detected` 는 **실제로 흐르는 이벤트**
- `ranker.pkl` 702,418 B 실재 · `GET /health` → `{"status":"ok","model_loaded":true}` — **정상 로드 중**
- `ranking-retrain` 워크로드 **부재** — `mp-ranking-serving` 1/1 만 존재
- DB 로그인 롤 = `fbapp` **단일** (서비스별 격리 롤 없음 — `schema-production.sql:6` 이 말한 *"별도 보안 단계"* 미이행)

---

## 3. 🔴 근본 결함 — 노출과 행동이 연결되지 않는다

### 3.1 증상

```
relevance = 0                →  320행 전부
양성 라벨을 가진 그룹         →  0
```

랭킹 학습(LambdaMART)은 **그룹 안의 상대 순서**를 배운다. 한 화면(추천 1회)에서 *"유저가 14위 항목을 골랐다"* 는 비교가 학습 재료인데, **모든 라벨이 0이면 비교할 쌍이 없다.**

### 3.2 원인

```
activity.user_event.session_id   →  44건 전부 NULL
activity.recipe_impression       →  16개 session (서버가 발급한 uuid4)
교집합                            →  0
```

학습 SQL(`ml/recipe-ranking/features.py` `EXTRACT_SQL`)이 `e.session_id = i.session_id` 로 조인하는데 **한쪽이 NULL 이라 영원히 매칭되지 않는다.**

**근본 원인 = 프론트엔드가 `session_id` 를 보내지 않는다.**

| | 백엔드 계약 | 프론트엔드 실제 |
|---|---|---|
| 추천 `POST /api/mealplan/recommend` | `RecommendReq.session_id` 존재 (`models.py:123`) | `api.ts:441` `body = { budget?, prefer? }` — **없음** |
| 담기 `POST /api/mealplan/cart/items` | `CartItemCreate.session_id` 존재 (`models.py:26`) | `api.ts:386-393` 타입에 **필드 자체가 없음** |

프론트 전체에서 `session_id` 를 쓰는 곳은 **채팅 위젯 하나뿐**이고(`ChatWidget.tsx:32`), 그건 멀티턴 대화용이라 별개다.

### 3.3 🔴 왜 3주간 아무도 몰랐나 — 이번 계획의 설계 원칙이 된 지점

양쪽 주석이 **결과를 이미 예고**하고 있었다:

- 추천: *"없거나 형식오류면 서버가 발급(**비링크**)"* (`queries.py:191`)
- 담기: *"없으면 이벤트 session 없이 발행"* (`events.py` 계약)

즉 **설계자는 알고 있었고, 조용히 메우도록 만들었다.** 그래서 프론트가 안 보낸다는 사실이 **로그 어디에도 남지 않았다.**

> **교훈 — 조용히 메우는 것은 유지해도 되지만, 메웠다는 사실은 반드시 세어야 한다.**
> 이 원칙이 §5.4 의 관측 설계 근거다. 같은 계열의 결함이 `1-21`(랭킹 모델 로드 실패가 조용하다)에도 있다.

### 3.4 형식 제약

`session_id` 는 **양쪽 테이블 다 `uuid` 타입**이다.

```
activity.recipe_impression.session_id  |  uuid
activity.user_event.session_id         |  uuid
```

⇒ 프론트는 **유효한 UUID** 를 보내야 한다(`crypto.randomUUID()`). 임의 문자열이면 추천 쪽은 **조용히 uuid4() 로 대체**되고(= 현재와 같은 실패), 담기 쪽은 `InvalidTextRepresentation` 으로 DLQ 격리되어 **데이터가 버려진다**.

---

## 4. 결정

### 4.1 #608 — ✅ 확정 · 정본 기록 완료 (C-83)

**결정: 안 "가" — 앱·배치가 PG 에 직접 쓴다.** 열린항목 ④ 를 닫고 종전 기본값 *"무응답 시 SQS 경유(보수적)"* 를 폐기한다.

**종전 기본값의 근거가 무효로 확인됐다.** 그 근거는 *"노출 로그를 켜면 볼륨이 수십~수백 배"* 였는데, **노출 로그(`impression_log`)는 애초에 Kafka 를 타지 않는다** — `queries.py:186` 주석 그대로 *"mealplan 직접 write"* 다. 그 볼륨은 이 두 토픽과 무관하다.

**실측 근거 4가지**

1. **소비자가 양쪽 다 1개** — `price.anomaly` 의 fan-out 은 구독자 팬아웃이 아니라 `INSERT ... SELECT` 한 문장 안의 **데이터 팬아웃**이라 EventBridge 규칙을 걸 대상이 없다
2. **유실 ≠ 미발송** — `price_anomaly` 행이 발행 **전에** 영속되고 `mark_published()` 가 전달 확인 후에만 `published_at` 을 찍는다 (`detect_price_anomaly.py:250`)
3. **리플레이 = 배치 재실행** — `price_alert_sent` PK + 7일 쿨다운 이중 멱등 (`consume_price_anomaly.py:65-69`)
4. 🔴 **볼륨 위계** — impression 이 추천당 **20행**을 이미 PG 직접 write 하는데(`routers.py:208·218`), ADD_CART(담기당 1건)를 큐로 빼는 것은 앞뒤가 안 맞는다

#### 🔴 GRANT — 현재는 무쟁점이지만 `0-13` 과 조정이 필요하다

**현재 상태**: 로그인 롤이 `fbapp` 단일이고(앱 11 + 파이프라인 22 = **33 워크로드가 공유**), 그 롤이 이미 `activity.user_event` 에 쓰고 있다 → **지금 당장은 권한 문제가 없다.**

🔴 **그러나 `0-13`(서비스별 PG 롤 격리)이 이관 전 선행으로 잡혀 있고**, 그 설계(`docs/prd/schema-roles.md` · `schema-roles.sql`, **DDL 머지 완료 · DB 미적용**)는 `svc_mealplan` 에 **`activity.recipe_impression` INSERT 만** 준다:

```sql
-- docs/prd/schema-roles.sql:131-132
GRANT USAGE  ON SCHEMA activity TO svc_mealplan;
GRANT INSERT ON activity.recipe_impression TO svc_mealplan;

-- 같은 파일 :256 — 검증문
SELECT has_table_privilege('svc_mealplan','activity.user_event','SELECT');  -- 기대 f
```

⇒ **롤 격리가 적용되면 이 계획의 PG 직접 쓰기가 권한 거부로 막힌다.**

**필요한 조정 — 한 줄 추가**

```sql
GRANT INSERT ON activity.user_event TO svc_mealplan;
```

🟢 **격리 의도는 보존된다.** 위 검증문은 **`SELECT`** 를 대상으로 하고 우리가 필요한 것은 **`INSERT` 뿐**이다(mealplan 은 `user_event` 를 읽지 않는다). 즉 *"mealplan 이 남의 이벤트를 읽지 못한다"* 는 원래 설계 의도가 그대로 유지되며 **`:256` 검증문도 여전히 통과**한다.

🔴 **이건 인프라 담당 소관이다** — `schema-roles.sql` 은 이 계획의 범위 밖이므로 **별도 조정 요청**으로 올린다(§9 ③).

### 4.2 #617 — ✅ 확정

**결정: 잡 상태 경로에만 재시도 + `health_check_interval` 추가.** 재시도 대상 예외는 **연결 계열만**(`ConnectionError`·`TimeoutError`).

**이슈 전제 정정** — *"Redis 호출이 실패하면 그대로 터진다"* 는 **1/3만 맞다.** `services/video/app/store.py` 는 이미 3층으로 갈려 있다:

| 경로 | 현재 | 판정 |
|---|---|---|
| `put_job`/`get_job` | `try/except` 없음 = **의도된 fail-loud** (`store.py:7`) | 🔴 **여기만 비어 있다** |
| `get_cached`/`set_cached` | 이미 best-effort | ✅ 이미 완료 |
| `acquire`/`release` | 이미 best-effort | ✅ 이미 완료 |

**전 경로 일괄 재시도는 하지 않는다.** 캐시·락은 *"빨리 포기하고 재분석"* 이 정답인데 재시도를 얹으면 **기다리게 만들어 오히려 후퇴**한다. 이 판단 기준은 `pipelines/stream/_dlq.py` 가 이미 쓰는 원칙과 같다 — *"영구라고 **아는** 것만 격리하고, 모르는 예외는 raise"*.

**실제로 비어 있는 것**

| 항목 | 현재 | ElastiCache 전환 시 |
|---|---|---|
| 재시도·백오프 | 🔴 0건 | 페일오버 순간 커넥션 끊김이 **그대로 사용자 오류** |
| `health_check_interval` | 🔴 미설정 | 페일오버 후 **죽은 커넥션 재사용** 가능 |
| connect 타임아웃 | ✅ 있음 (`store.py:24-25`, 3s) | 무한 대기는 안 한다 |
| 클라이언트 재사용 | ✅ 이미 됨 (`main.py:47` lifespan 1회) | #458 처방 중 이 항목은 충족 |

**함께 처리 권고 — `1-15`** (`chat`·`price` Redis 소켓 타임아웃 미설정). 같은 계열·같은 사유(*"사이트 간 지연이 생기는 AWS 구성에서 무한 대기"*)라 한 PR 로 묶는다.

**이슈 체크박스 3번**(Sentinel-aware 코드 제거)은 `video` 에 한해 **해당 없음** — `store.py` 는 단순 `Redis(host, port)` 직결이라 제거할 Sentinel 코드가 없다.

### 4.3 #616 — 🟡 조건부 확정

**결정: C-20(이미지에 굽기) 유지.** S3 + initContainer 로 바꾸지 않는다.

**근거 순서**

1. **C-20** — 팀 정본. 애초에 굽기로 확정돼 있었다
2. **클러스터 실측** — 양성 라벨 0 · retrain 워크로드 부재 ⇒ **자동화할 대상이 아직 없다**
3. 재학습 현실 — 8~9주 프로젝트에 데이터가 이제 막 쌓이기 시작한다. **발표 전 수동 1~2회**가 현실적이다

**재검토 트리거**: 재학습이 **주기화되는 시점**. 그때는 S3 + initContainer 가 맞다.

**선행 1건 — 아티팩트 확보.** 굽기를 하려면 빌드 시점에 파일을 가질 수 있어야 하는데, 지금 `ranker.pkl` 은 **PVC 단 한 곳**에만 있다(git ❌ gitignored · 이미지 ❌). **PVC 가 날아가면 모델이 소멸한다.**

정본이 이미 같은 지시를 하고 있다 — `1-21`: *"C-20(PVC 제거)을 실행하면서 **모델 사본 정책을 같이 정해야 한다** — 안 그러면 이미지/S3 배선이 틀려도 드러나지 않는다."*

**함께 처리 권고 — `1-21`** (랭킹 모델 로드 실패가 조용하다). `serve.py:157-169` 가 파일 부재·pickle 실패를 **로그 없이** 삼키고 `model=None` 으로 기동하며, `/health` 는 `status: ok` 를 반환해 readiness·liveness 를 둘 다 통과한다. 알림 규칙 0건. **굽기로 전환할 때 배선이 틀려도 드러나지 않는 구조**라 같이 고쳐야 한다.

---

## 5. 설계 — `EVENT_SINK` 선택자

### 5.1 원칙 4개 (제약에서 도출)

| | 원칙 | 출처 |
|---|---|---|
| ① | 온프렘 동작은 **한 글자도 안 바뀐다** | C-72 ① |
| ② | dual-write 는 **구조적으로 불가능**해야 한다 | C-72 (상시 병행 미채택) |
| ③ | 담기를 막으면 안 된다 | `events.py:23` 기존 원칙 |
| ④ | 실패가 **조용하면 안 된다** | §3.3 |

### 5.2 스위치 — 기존 플래그는 두고 목적지 선택자를 더한다

```
현행   EVENT_PRODUCE_ENABLED   발행할까 말까              ← 그대로 둔다
신설   EVENT_SINK              어디로 (kafka / pg)        기본값 = "kafka"
```

**이 기본값이 원칙 ①을 지킨다.** 온프렘 ConfigMap 에 `EVENT_SINK` 를 **넣지 않으면** 기본 `kafka` 라 지금과 완전히 동일하게 동작한다 — **온프렘 오브젝트 변경 0**.

그리고 **선택자가 하나라 dual-write 가 불가능**하다(원칙 ②). 불린 두 개면 실수로 둘 다 켜질 수 있지만 단일 선택자는 배타적이다. **C-72 준수가 코드 구조로 보장된다.**

### 5.3 쓰기 지점 — 같은 커넥션 + savepoint

`get_conn` 은 **요청 전체를 한 트랜잭션**으로 묶고 psycopg_pool 이 성공 시 커밋한다(`context.py:214-219`). 따라서 이벤트 INSERT 를 그냥 얹으면 **실패 시 담기까지 롤백**된다(원칙 ③ 위반).

```
async with conn.transaction():     # savepoint — 실패해도 바깥 트랜잭션 보존
    INSERT INTO activity.user_event (...)
    ON CONFLICT (event_id) DO NOTHING
```

**선례가 이미 있다** — `insert_impressions` 가 정확히 이 구조다(`queries.py:212`). 같은 서비스·같은 스키마·같은 best-effort 라 패턴을 그대로 따른다.

**부수 이득**: 이벤트 행이 장바구니 행과 **같은 트랜잭션에서 커밋**된다. Kafka 경로보다 정합성이 좋다.

### 5.4 계약 재사용 · 관측

`build_add_cart_event()` 는 **이미 Kafka 무관한 순수 함수**이고(`events.py:38`), 만들어내는 dict 의 키가 `consume_user_event.to_params()` 가 기대하는 것과 1:1로 같다. **메시지 계약을 새로 만들 필요가 없다.**

```
build_add_cart_event()          ← 공통 · 변경 없음
    ├─ sink=kafka →  producer.produce(...)      ← 기존 코드 그대로
    └─ sink=pg    →  INSERT ... ON CONFLICT     ← 신설
```

멱등도 확보돼 있다 — `event_id` UNIQUE + `ON CONFLICT DO NOTHING`.

**조용한 실패 제거**(원칙 ④) — fail-open 은 유지하되 말은 하게 만든다:

| 지점 | 지금 | 계획 |
|---|---|---|
| 발행 실패 | Kafka 는 `_on_delivery` warning 있음 · PG 경로는 신설 | 양쪽 다 **실패 카운터 + warning** |
| `session_id` 부재·형식오류 | 🔴 조용히 uuid4() 로 대체 | 대체는 유지하되 **카운터로 노출** |
| "켜놨는데 0건" | 🔴 아무 신호 없음 | `activity.user_event` **최신 시각 알림** |

### 5.5 `price.anomaly` 대응물

같은 문제·같은 해법이라 같은 모양으로 간다.

```
detect_price_anomaly.py
  --emit          → Kafka 발행        ← 기존 · 그대로
  --emit-direct   → fanout SQL 직접   ← 신설 (별도 인자)
```

여기는 검증이 **더 안전하다** — `price_alert_sent` PK + 7일 쿨다운이 중복 알림을 **구조적으로** 막아서, 기존 CronJob·컨슈머를 그대로 둔 채 사본 CronJob(`suspend: true` + 수동 트리거)으로 1회 돌려볼 수 있다. **C-72 ② 를 문자 그대로 적용할 수 있는 케이스다.**

### 5.6 이관 시점 전환

```
overlays/onprem/   EVENT_SINK 없음      → kafka    🔒 불변
overlays/eks/      EVENT_SINK: "pg"     → PG 직접   신설
```

**C-77 과 정합** — `overlays/eks/` 만 새로 쓰고 `overlays/onprem/` 은 건드리지 않는다. 전환은 **오버레이 한 줄**이다.

---

## 6. 인프라 영향 검증 — AWS 설계안을 바꾸는 지점이 있나

**결론: 없다.**

| AWS 결정 | 영향 |
|---|---|
| **C-20** 모델을 이미지에 굽기 | 🟢 **유지** — 뒤집지 않는다 |
| **C-14** Redis → ElastiCache | 🟢 #617 이 선행(`1-14`)을 **이행**. 결정을 강화한다 |
| **C-16** PVC 총량 | 🟢 ranker PVC 소거는 이슈 #616 이 이미 계산에 반영 |
| **C-30** 파드 신원 = IRSA | 🟢 **새 IAM 주체 0** — mealplan 은 PG 만 쓴다 |
| **C-42** PG 인스턴스 2 | 🟢 **커넥션 증가 0** — 기존 요청 커넥션 재사용 |
| **C-44** Kafka 전면 제거 | 🟢 이 계획이 **그걸 실현하는 수단** |
| **C-56** SQS VPC 엔드포인트 | 🟢 크롤 경로 때문에 그대로 필요 — 변경 0 |
| **C-45 · C-64** 노드 사이징 | 🟢 자원이 **주는** 방향 (아래) |
| **C-70** 온프렘 = 크롤 단독 | 🟢 앱 워크로드가 주는 방향이라 **정합** |
| **C-72** 온프렘 동결 | 🟢 기본값 `kafka` 라 **ConfigMap 변경 0** |
| **C-77** `aws-platform/` Terraform | 🟢 **Terraform 리소스 추가 0** |
| **C-2** GitLab CI | 🟡 CI 잡이 모델을 가져와야 함 — **잡 변경이지 인프라 결정 변경 아님** |
| **C-68** S3 버킷 인벤토리 | 🟡 **유일한 접점** — §9 ② |

**자원 실측 — 소거 대상**

```
mp-user-event-sink          50m / 128Mi
mp-price-anomaly-notifier   50m / 128Mi
────────────────────────────────────────
합계                      −100m / −256Mi     ← C-45 재집계 8.19 vCPU 대비 1.2%
```

미미하지만 **방향이 여유 증가**라 노드 2대 결정을 흔들지 않는다.

> **안 건드리게 된 이유는 설계 한 수다** — 목적지 선택자의 **기본값을 현행(`kafka`)으로 둔 것**. 그것 하나로 온프렘 ConfigMap 변경이 0이 되고, 따라서 C-72 도 사이징도 안 건드리게 됐다. 플래그를 *갈아끼우는* 방식이었다면 온프렘 오브젝트를 수정해야 했고 C-72 에 걸렸을 것이다.

### 인프라 정본 대조 (2026-08-13 수행)

인프라 담당(`bongsu`) 작성 문서와 직접 대조했다.

| 정본 | 대조 결과 |
|---|---|
| `docs/prd/schema-roles.md` · `.sql` (2026-08-10) | 🔴 **충돌 1건 발견 → §4.1 · §9 ③ 에 조정 요청으로 반영.** `svc_mealplan` 이 `activity.user_event` 에 접근 권한이 없다 |
| `docs/mp_k8s_infra_status.md` (현행 SSOT) | 🟢 충돌 없음 — 이 계획은 K8s 오브젝트를 **신설·소거하지 않는다**(전환 PR 이전까지) |
| `docs/mp_data_pipeline_design.md` | 🟡 **현행 서술**이라 충돌은 아니나, 컨슈머 2종 서술이 **전환 시점에 stale** 이 된다 → §8 에 갱신 대상으로 명시 |
| `docs/mp_netpol_zerotrust_flow.md` | 🟢 충돌 없음 — mealplan 은 **이미 PG 로 쓰고 있어**(cart · impression) 새 egress 가 필요 없다 |
| `docs/mp_k8s_infra_object_spec.md` | 🟢 충돌 없음 — `1386` 의 initContainer 패턴은 **S3 안을 택했을 때만** 관련. 굽기(C-20)에는 무관 |
| `docs/mp_aws_prep_checklist.md` (이관 정본) | 🟢 §6 표 참조 — **C-번호 변경 0** |

**대조에서 정정된 것 2건**

1. **C-68 버킷 수** — 초안이 *"인벤토리 5개"* 라고 썼으나 C-68 은 **신설 3개**를 확정한 행이고, 전량은 **6개**(C-79 · `1-44`)다 → §9 ② 정정
2. **GRANT 무쟁점** — *현재* 는 맞으나(단일 `fbapp`) **`0-13` 적용 후에는 막힌다** → §4.1 에 조정 요청 추가

---

## 7. 작업 계획

### 7.1 PR 분리 (C-72 선례 — PR #593 방식)

| PR | 내용 | 시점 | 위험 |
|---|---|---|---|
| **A** | `EVENT_SINK` 선택자 + PG 쓰기 경로 + 테스트 + 카운터 | 지금 | 🟢 **기본값이 현행이라 머지해도 동작 변화 0** |
| **B** | 프론트 `session_id` 발급·전송 (추천+담기 동일 UUID) | 지금 | 🟢 순수 덧셈 |
| **C** | `IMPRESSION_LOG_ENABLED=true` (config 레포) | 지금 | 🟡 `rollout restart` 동반 |
| **D** | #617 + `1-15` Redis 재시도·타임아웃 | 지금 | 🟢 코드만 |
| **E** | `1-21` 모델 로드 실패 노출 + 아티팩트 확보 | 지금 | 🟢 관측 추가 |
| **F** | `overlays/eks` 에 `EVENT_SINK=pg` · #616 굽기 · 워크로드 소거 | **이관 시점** | 🔴 C-72 |

### 7.2 순서와 이유

```
1  D  #617 + 1-15          독립 · C-14 를 막고 있다 · 정본이 "선택 아님"으로 요구
2  B  프론트 session_id     ⏰ 축적에 시간이 드는 유일한 항목
3  C  IMPRESSION_LOG        노출 로깅 재개 (2026-07-22 정지)
4  E  1-21 + 아티팩트 확보  백업 리스크도 함께 해소
   ───────────────────────────────────────────
5     라벨 관측             relevance > 0 행이 나오는지
6     retrain 수동 1회      규칙 baseline 을 이기는지
   ───────────────────────────────────────────
7  A  EVENT_SINK 신설       (순서 무관 — 언제 넣어도 동작 변화 0)
8  F  전환                  이관 시점
```

**1~4 는 지금 할 수 있고, 5~6 의 결과가 8 의 근거가 된다.**

### 7.3 검증 방법

C-72 ②의 *"사본 + `suspend: true` + 수동 트리거"* 는 CronJob 용 절차다. 상시 서비스에는 등가물을 쓴다:

```
① 로컬 DB-free 테스트    정본 컨벤션(services/CONVENTIONS.md · AppCtx 주입 seam).
                         기존 test_emit_add_cart_noop_when_disabled 옆에 pg 경로 추가
② 스테이징 1건 왕복       EVENT_SINK=pg 로 두고 담기 1회 → 행 확인 → 되돌림
③ 온프렘 기본값은 끝까지 kafka   ← 롤백 경로 보존
```

**플래그가 곧 `suspend` 역할**을 한다 — 코드는 들어가 있지만 켜지 않으면 한 줄도 안 돈다.

`price.anomaly` 는 §5.5 대로 **사본 CronJob** 으로 C-72 ② 를 문자 그대로 적용한다.

---

## 8. 범위 밖 — 이 계획이 **하지 않는** 것

| 안 하는 것 | 이유 |
|---|---|
| 온프렘 워크로드 소거 (`mp-user-event-sink` · `mp-price-anomaly-notifier`) | **C-72 ①** — 되돌릴 원본이 사라진다. 이관 시점 |
| `pipelines/stream/` 15모듈 삭제 | C-72 가 *"처분 판정"* 에서 **"삭제 금지·방치"** 로 성격 변경 |
| Kafka 경로 제거 (`--kafka` 인자 등) | 같음. 이관 후 |
| retrain 워크로드(CronJob/Lambda) 신설 | **자동화할 대상이 아직 없다**(라벨 0). 수동 1회로 먼저 확인 |
| `ranker.pkl` 재학습 자동화 | §4.3 재검토 트리거 도달 전까지 |
| PVC `mp-ranking-model` 삭제 | 굽기와 한 세트라 이관 시점 |
| 서비스별 DB 롤 격리(`0-13`) 실행 | 인프라 담당 소관. 이 계획은 **조정 요청 1줄만** 낸다(§9 ③) |
| `docs/mp_data_pipeline_design.md` 갱신 | 컨슈머 2종 서술이 전환 시점에 stale 이 된다 — **전환 PR(F)과 한 세트** |
| config 레포 netpol 정리 | 파이프라인 워크로드 소거와 한 세트. 전환 시점 |
| `VIEW`·`NOTIF_CLICK` 이벤트 배선 | 생산자가 없다. ADD_CART 로 먼저 라벨이 붙는지 확인 후 판단 |

---

## 9. 열린 항목 — 팀 판단 필요

### ① 랭킹 서빙 정지(Retire) 여부

랭킹 서빙을 **유지할 것인가**. 정지로 결정되면 **#616 자체가 소멸**한다(구울 대상 서빙이 없어진다).

참고 — 정지 후보로 올라간 근거는 *"`RANKING_ML_ENABLED=false` · 호출 0"* 이었는데, **클릭스트림 활성화 결정으로 그 전제는 이미 무너졌다.**

### ② C-68 에 모델 아티팩트 버킷 등재

§4.3 의 아티팩트 확보에는 저장소가 필요하다. 현행 버킷은 **6개**이고(C-79 · `1-44` 의 전량 표 기준: `mp-backup-ap2` · `mp-cloudtrail-ap2` · `mp-pg-dump-ap2` · `mp-source-backup-ap2` · `mp-crawl-ap2` · `mp-observability-ap2`), **모델 아티팩트 자리는 없다.**

후보는 둘이다 — ⓐ 신규 버킷 등재(C-68 개정) ⓑ 기존 버킷 prefix 재사용(C-68 이 `mp-source-backup-ap2` 에 `source/`·`gitlab/` 로 쓴 방식). ⓑ 를 택하면 **C-79 의 라이프사이클 표에 prefix 행 추가**가 함께 필요하다.

⚠️ **런타임 의존이 아니라 빌드타임 저장소**라 돌아가는 컴포넌트는 늘지 않는다.

### ③ `schema-roles.sql` 에 `svc_mealplan` INSERT 추가

§4.1 참조. `GRANT INSERT ON activity.user_event TO svc_mealplan;` **한 줄**이 `0-13` 적용 전에 들어가야 한다. 🟢 기존 검증문(`:256`, SELECT 대상)은 그대로 통과하므로 **격리 설계를 훼손하지 않는다.**

🔴 **적용 순서 주의** — `0-13`(롤 격리 DDL 실행)이 이 계획의 PR-A 보다 **먼저** 적용되면, 그 사이에 `EVENT_SINK=pg` 를 켤 경우 권한 거부가 난다. 다만 PR-A 는 **기본값이 `kafka`** 라 켜지 않는 한 무해하다.

---

## 10. 미검증 항목

| 항목 | 상태 |
|---|---|
| 현재 `ranker.pkl` 의 출처 | 라벨된 학습행이 0인데 모델이 존재한다. `synth.py`(합성데이터) 학습본으로 **추정**. 🟢 로드 자체는 정상(`model_loaded: true`)이라 굽기 대상 파일로는 문제없다 |
| 세션 수명 정의 | 추천 1회 = 1세션인지, 화면 체류 = 1세션인지. **학습 관점에선 "추천 1회 = 1그룹"이 자연스럽다** — 그래야 *"이 화면에서 뭘 골랐나"* 가 한 그룹이 된다 |

---

## 부록 — 검증 재현 방법

```bash
# 라벨 상태 (읽기 전용)
kubectl -n data exec pg-1 -c postgres -- psql -U postgres -d foodbudget -c "
  SELECT count(*) FILTER (WHERE session_id IS NULL) AS null_session, count(*)
    FROM activity.user_event;"

# 노출 그룹 수
kubectl -n data exec pg-1 -c postgres -- psql -U postgres -d foodbudget -c "
  SELECT count(*) FROM (SELECT DISTINCT user_id, session_id
                          FROM activity.recipe_impression) g;"

# 모델 적재 여부
kubectl -n app exec deploy/mp-ranking-serving -- \
  python3 -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8009/health').read().decode())"

# 로컬 테스트
python3 -m pytest pipelines/stream/tests pipelines/ingest/tests services/mealplan/tests -q
```
