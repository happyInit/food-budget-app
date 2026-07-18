# 클릭스트림 컨슈머·보존배치 설계 (Track 1 데이터 파이프라인 prep)

> **작성:** 태현 (데이터 오너) · **상태:** 설계 prep(구현 前 — 동의 승인·토픽 스키마·produce 계약 대기).
> **관련:** `user-behavior-data-request.md` §3·§6 · `chat-conversation-data-plan.md` §8 · #131(동의 게이트).
> **전제(머지됨):** `activity.user_event`·`activity.recipe_impression` · `chat.chat_message` · `account.app_user.activity_consent` 스키마 준비 완료.

## 0. 범위 & 의존성

**데이터 오너 몫 2개:** (1) Kafka 컨슈머(`events.user.activity` → PG), (2) 보존·익명화 배치(D-3/D-4).
**선행 의존(이게 있어야 실속):** ① 동의 승인(#131, 팀) · ② 토픽 스키마 결정(JSON/Avro) · ③ produce 계약(백엔드 이벤트·mealplan 랭커 노출). → 지금은 **설계만**, 배포는 위 3개 후.

## 1. 재사용할 기존 패턴 (`pipelines/stream/`)

| 관심사 | 파일 | 패턴 |
|---|---|---|
| 컨슈머 | `consume_recipe.py` | `_kafka.consumer(group)`(수동커밋·at-least-once) → poll 루프 → `json.loads` → PG write → **`conn.commit()` 후 `c.commit()`**(오프셋). 관측성 `_metrics`·`_observability`. `COMMIT_EVERY` 배치·`IDLE_EXIT`·SIGTERM. |
| Kafka 설정 | `_kafka.py` | `BOOTSTRAP`(env) · 토픽 상수 · 멱등 producer(acks=all) · consumer(group, earliest, manual commit, cooperative-sticky). |
| 토픽 | `create_topics.py` | 멱등 `NewTopic`(파티션·retention). K8s=Strimzi `deploy/k8s/kafka-topics.yaml`. |
| 보존 배치 | `prune_deals.py` | `prune_once()` + `--loop`(상주)/CronJob(주기) + metrics. |

## 2. 컨슈머 설계 — `pipelines/stream/consume_user_event.py`

- **토픽:** `events.user.activity` (→ `_kafka.py`에 `TOPIC_USER_ACTIVITY` 상수 추가). **key = `user_id`**(파티션 분산 + 유저별 순서).
- **group:** `user-event-sink`.
- **메시지 계약(제안):** `{event_id(uuid), user_id, session_id, event_type∈(VIEW/ADD_CART/NOTIF_CLICK), recipe_id?, item_id?, occurred_at(UTC), context?}`.
- **처리:** `json.loads` → 검증(`event_type` CHECK) → `INSERT INTO activity.user_event (...) ON CONFLICT (event_id) DO NOTHING` → `conn.commit()` → `c.commit()`. (consume_recipe와 동일 흐름.)
- **관측성:** `RECORDS`·`SINK_WRITES`·`LAST_SUCCESS`·`PROCESSING_SECONDS`(그대로).

### ⚠️ 설계 중 발견한 갭 — 멱등키 부재
컨슈머는 **at-least-once**(수동커밋)라 리밸런스·재시작 시 **재전달=중복**. 근데 `activity.user_event`엔 **자연 유니크키가 없다** → 중복 이벤트가 그대로 적재돼 **분석 편향**(특히 `ADD_CART` 주 라벨 중복 → 랭킹 라벨 왜곡).
→ **스키마 보강 필요: `event_id uuid` + `UNIQUE`** (producer가 발급, 컨슈머 `ON CONFLICT DO NOTHING`). consume_recipe가 `src_recipe_id` 유니크로 멱등인 것과 동형. `recipe_impression`도 동일(`impression_id`).
→ *대안:* dup 허용(분석 관용) — 근데 라벨 중복은 비추. **event_id 권장.**

## 3. 노출 로그(recipe_impression) 경로

`services/mealplan/app/ranking.py`(P0 규칙 랭커)가 추천을 낼 때 **emit**(문서 §6 "produce=랭커, 저장=데이터"). 두 안:
- **ⓐ 랭커 직접 PG write** — mealplan이 이미 DB 접근. 노출 시 `recipe_impression`에 바로 insert. 단순·저지연. **권장**(별도 토픽 불필요).
- **ⓑ 토픽 경유** — `events.user.activity`(또는 별 토픽)에 produce → 컨슈머. 결합도↓·볼륨 스파이크 흡수, 근데 인프라 1겹.
→ MVP는 **ⓐ**(랭커 직접), 볼륨 커지면 ⓑ. 어느 쪽이든 **`impression_id` 멱등키** 권장.

## 4. 보존·익명화 배치 설계 — `pipelines/stream/prune_user_data.py` (D-3/D-4)

`prune_deals` 패턴(Redis→**PG판**). 일일 CronJob or `--loop`. `retention_days` config(90~180, §7 미결).

1. **집계 승격(원문 삭제 前):** 보존창 지난 데이터를 집계로 올림 —
   - `user_event` → **인기도 집계**(`recipe_id → ADD_CART/VIEW count`, §2.3) + 유저별 행동 피처 집계.
   - `chat_message` → 요약/통계(의도분포·미응답율·품목빈도).
2. **원문 삭제/익명화:** 보존창 지난 **원문 DELETE**(집계본은 영속). `chat_message.text`는 익명화(PII·민감어 마스킹) 후 삭제.
3. **민감정보(D-4):** 알레르기·예산·건강 — 외부(Gemini) 전송은 AI 리포트(건우) 몫이나, **배치가 집계/익명화본을 미리 만들어 원문 외부전송 0**.
4. **삭제권(D-3):** 유저 철회(`activity_consent=false`)/탈퇴 → 해당 `user_id` **전량 DELETE**(`user_event`·`recipe_impression`·`chat_message`). 이벤트 트리거가 정석이나, 배치가 **미동의 유저 잔여 데이터 청소**(방어망).
- 멱등·관측성 = `prune_deals` 동일.

## 5. 집계 테이블(선택, §2.3)

`recipe_popularity(recipe_id, add_cart_cnt, view_cnt, updated_at)` — 서빙 시 실시간 집계 회피. 보존배치가 원문 삭제 前 승격·갱신. (MV vs 테이블은 규모 보고.)

## 6. 동의 처리 흐름 (게이트 위치)

- **produce(백엔드/프론트):** 미동의 유저 이벤트 **produce 안 함** — 1차 게이트.
- **컨슈머:** produce 신뢰(단순). *방어 재확인 옵션:* `account.app_user.activity_consent` 조회(크로스서비스 읽기) — 기본 off(produce가 이미 게이트), 필요시 on.
- **철회:** §4-4 배치가 청소.

## 7. 열린 결정 (선행 협의 — #131 승인과 함께)

- 토픽 스키마 **JSON vs Avro** · **`event_id`/`impression_id` 멱등키 추가**(스키마 보강) · `retention_days`(90/180) · 노출로그 **랭커 직접 write(ⓐ) vs 토픽(ⓑ)** · 컨슈머 동의 재확인 여부 · 집계 테이블 스키마.

## 8. 구현 순서

동의 승인(#131) → 토픽 스키마·produce 계약 확정 → **`event_id` 스키마 보강** → 컨슈머(`consume_user_event.py`)·토픽(`create_topics.py`+Strimzi) → 보존배치(`prune_user_data.py`) → 집계 테이블. (전부 `pipelines/stream/` 기존 패턴 복제.)
