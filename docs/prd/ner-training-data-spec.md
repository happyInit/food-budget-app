# NER 학습 데이터 — 적재 스펙

> 작성: 건우 (AI 담당) · 2026-07-13 · 갱신 2026-07-14(`feat/oasis-retail-coverage`·`feat/deploy-ci-pollers` 병합분 대조 — §0 미해결 재확인, §5 갱신, §7 신설)
> 대상 독자: 데이터 파이프라인 담당(태현)
> 스코프: **CRF 재료 NER**(`ai-spec.md` §1, `design.md` §4.1) 학습·적용을 위해 `pipelines/ingest/`·`pipelines/stream/` 적재가 지켜야 할 구조적 제약.
> 모델 설계 자체는 다루지 않음 — 그건 `ai-spec.md` §1 소관.

---

## 0. 🔴 미해결 이슈 — 자유텍스트 학습 코퍼스 부재 (결정 필요)

현재 코드(`pipelines/ingest/load_recipe.py`, `load_10k_recipe.py`, `docs/prd/schema-public-data.sql`)를 실측한 결과, CRF가 학습할 **자유텍스트(문장) 예제가 0건**입니다.

| 소스 | 상태 | 왜 학습에 못 쓰나 |
|---|---|---|
| EPIS (`ner_status='LABELED'`) | 구조화 gold (`IRDNT_NM`+`IRDNT_CPCTY`) | 애초에 자연어 원문이 없음(`ingredient_raw=null`) — "재료명이 문장 어디 있는지" 라벨링 자체가 불가능 |
| COOKRCP01 (자유텍스트) | **드롭 확정** (`design.md` §3.3, `load_10k_recipe.py`가 `delete ... source in ('10K','COOKRCP01')`로 제거) | 소스 자체가 없음 |
| 10K/만개의레시피 (`ner_status='CRAWLER'`) | `ingredient_raw` 보존됨, 재료명/수량은 **크롤러 정규식**이 이미 분리 | `ai-spec.md` §1: robots `ai-train=no`(TDM 옵트아웃) — 텍스트를 **학습 코퍼스로 쓰는 것 자체가 금지** |

**즉 지금 파이프라인 그대로 실데이터를 넣기 시작하면, NER 모델은 학습할 문장이 없습니다.** 이건 적재 방식을 좀 고친다고 풀리는 문제가 아니라 **데이터 소스를 하나 정해야 하는 문제**라 아래 옵션 중 하나를 팀이 골라야 합니다.

| 옵션 | 내용 | 트레이드오프 |
|---|---|---|
| A | COOKRCP01을 `recipe`(앱 표시/검색용)와 **분리된 학습 전용 테이블**로 별도 유지 (앱 레시피 DB는 10K 그대로, 학습만 COOKRCP01 부활) | 스키마·로더 소폭 추가, 법적 이슈 없음(COOKRCP01은 공공API) |
| B | EPIS 구조화 필드(`이름+용량`)로 합성 문장 생성 후 라벨 자동 부여 | 구현 쉬움, 그러나 실제 자유텍스트 패턴과 괴리 → 일반화 품질 낮을 가능성 |
| C | 유저 영수증 텍스트 축적 후 그걸로 학습 | 법적으로 가장 깨끗, 그러나 시점이 한참 뒤(유저 데이터가 쌓여야 함) — 지금 당장은 불가 |

**AI 쪽 의견**: A안 권장(공수 적고 즉시 가능, 법적 문제 없음). 다만 최종 채택은 팀 결정 사항 — 이 문서는 결정을 대신하지 않음.

> **2026-07-14 재확인**: 하루 지난 시점에 다시 대조해봤는데, 이 이슈는 **여전히 그대로**입니다 — `EPIS_API_KEY`는 아직 `.env.example`에 항목조차 없고(`FOODSAFETY_API_KEY`도 미발급 상태), `load_10k_recipe.py`는 오히려 "COOKRCP01 교체 완료"라는 주석까지 붙어서 COOKRCP01이 10K에 확정적으로 덮여쓰이는 쪽으로 더 굳어졌습니다. 이 문서 자체도 지금까지 PR이 없어서 안 보이고 있었던 게 원인으로 보입니다 — 이번에 PR을 냅니다.

---

## 1. 원문(raw text) 보존 원칙

- `ingredient_raw`는 소스 원본 그대로, **정규화·축약·동의어 치환 없이** 저장. (10K는 현재 이 원칙을 지키고 있음 — `재료원문` 컬럼 그대로 적재 확인됨. 계속 유지 요청.)
- 이유: CRF는 "원문 문자열 안에서 재료명이 어디 있는지"(문자 오프셋)로 라벨을 자동 정렬합니다. 적재 단계에서 미리 다듬으면 학습 라벨과 실사용 입력의 분포가 어긋납니다.
- (§0에서 A안 채택 시) COOKRCP01 학습 테이블도 동일 원칙 적용.

## 2. TDM 옵트아웃 소스의 물리적 격리 (하드 제약)

- 10K(만개의레시피) 소스의 `ingredient_raw`는 **저장은 되지만 학습에 쓰면 안 됩니다.** `recipe.source` 값으로 구분되는 것은 확인했는데, 학습 데이터를 뽑는 쿼리/뷰 자체가 이 소스를 구조적으로 제외하도록 걸어주세요(예: 학습용 뷰에서 `WHERE source != '10K'` 고정, 혹은 §0-A안 테이블처럼 물리적으로 다른 테이블에 둬서 애초에 섞일 수 없게).
- 근거: `data-validation.md` §2.2 — robots.txt `Content-Signal: ai-train=no` 명시적 권리유보.

## 3. 재료명은 원문의 부분 문자열이어야 함

- `ingredient_name`은 원문에서 그대로 뽑은 substring 유지(동의어 정규화는 `item_master`/`gazetteer.py` 매핑 단계에서 처리 — 원재료 텍스트 단계에서 건드리지 말 것).
- 10K는 크롤러가 이미 이 방식대로 분리해줌(양호, 확인됨). EPIS는 원문 자체가 없어 해당 없음.

## 4. train/test 분할 키 고정

- (§0에서 확보되는) 학습 코퍼스에 대해 `recipe_id` 기준 결정적 분할(예: `recipe_id % 10 < 8` → train) 지금 합의 필요.
- 이유: 데이터가 계속 늘어날 예정이라, 분할 기준이 안 정해지면 데이터 추가될 때마다 평가셋이 흔들려서 모델 성능 비교 자체가 불가능해집니다.

## 5. 증분 적재 시 `ner_status` 보존

- ✅ **10K 소스는 해소됨(2026-07-14 확인)**: `load_10k_recipe.py`가 `process_recipe()`로 리팩터되면서 전체 삭제(`delete from recipe where source in (...)`) 방식에서 **레시피 단위 upsert**(`on conflict (source, src_recipe_id) do update` + `recipe_id` 스코프 `delete/insert`)로 바뀌었습니다. `ner_status='CRAWLER'` 행은 매번 gazetteer로 `item_id`를 재계산해서 다시 넣는 구조라, 재적재해도 유실될 "저장된 학습 라벨"이 애초에 없어 이 우려는 10K에 한해 해소됐습니다.
- ⚠️ **다만 §0-A안(COOKRCP01 학습 전용 테이블) 채택 시엔 이 문제가 새로 생깁니다.** 그 테이블은 10K 파이프라인과 별개로 관리될 거라, **같은 방식(레시피 단위 upsert)을 처음부터 적용**해야 합니다 — 특히 사람이 수작업으로 라벨링/검수한 행이 있다면(향후 HITL 도입 시) 재크롤 시 그 라벨이 지워지지 않게 별도 컬럼(예: `labeled_at`, `labeled_by`)으로 보호하는 걸 권장합니다.

## 6. `ner_status` 값 정리 (현재 스키마 기준)

| 값 | 의미 | CRF와의 관계 |
|---|---|---|
| `CRAWLER` | 크롤러가 재료명/수량 이미 분리(10K) | NER 미적용 — gazetteer로 `item_id`만 해소 |
| `LABELED` | 정형 gold(EPIS) | 학습 라벨 후보지만 자유텍스트 없음(§0) |
| `RAW` | 자유텍스트, NER 미적용 | **현재 이 상태의 행이 없음**(§0) |
| `NER_PARSED` | CRF 적용 완료 | 목표 상태 — §0 해결 후에나 도달 가능 |

## 7. Kafka 스트리밍 경로 — 별도 요구사항 불필요 (2026-07-14 신설)

`feat/deploy-ci-pollers` 병합으로 배치 적재 외에 **Kafka 스트리밍 경로**(`pipelines/stream/consume_recipe.py`, recipe-refiner 컨슈머)가 새로 생겼습니다. 확인해보니:

- `consume_recipe.py`는 `load_10k_recipe.py`의 **`process_recipe()`를 그대로 재사용**합니다(배치·스트리밍 공용 함수).
- 즉 위 §1(원문 보존)·§3(재료명 substring)·§5(ner_status 보존) 요구사항이 **이미 스트리밍 경로에도 자동으로 적용되고 있습니다** — 별도로 요청할 게 없습니다.
- 확인만 부탁드리는 것: 앞으로 `process_recipe()` 로직을 바꿀 일이 있으면(배치·컨슈머 양쪽에 영향) 이 문서 §1/§3/§5 원칙이 계속 유지되는지만 봐주시면 됩니다.

---

## 참고 문서
`ai-spec.md` §1(NER 모델 설계) · `data-validation.md` §2.2(만개의레시피 TDM 이슈) · `design.md` §3.3(COOKRCP01 드롭 결정) · `prd/schema-public-data.sql`(`recipe_ingredient` 정의) · `pipelines/ingest/load_10k_recipe.py`·`load_recipe.py`(현재 로더 구현) · `pipelines/stream/consume_recipe.py`(Kafka 스트리밍 경로, §7)
