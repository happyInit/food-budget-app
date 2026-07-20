# NER 학습 데이터 — 현황 브리핑 + 확인 요청 (건우 → 태현)

> 작성: 건우 (AI 담당) · 2026-07-14 · **갱신 2026-07-20 (§1-5 신설 — DB 실조회로 질문 0·0-1·2 확정)**
> 상태: **브리핑 문서 — 미병합 초안.** `ner-training-data-spec.md`(PR #27, 병합됨)의 후속 확인 내용을 정리한 것으로, 이 문서 자체는 아직 팀 확정 아님.
> 대상 독자: **태현의 Claude Code** (또는 태현 본인) — 아래 "확인된 사실"은 전부 코드/커밋을 직접 읽고 검증한 내용이라, 그대로 신뢰하고 답변에 활용해도 됨. "권장(미확정)"으로 표시된 부분만 별도 승인 필요.
> 목적: 인프라 서버 접근 문제와 별개로, NER 학습 데이터 준비에 **선행 결정이 필요한 지점**을 코드 레벨로 검증해서 전달.

---

## 0. 한 줄 요약

**(2026-07-20 갱신 — DB 실조회로 확정)** `recipe` 테이블 실조회 결과 **COOKRCP01 1,146건·EPIS 537건이 10K(6,446건)와 같은 테이블에 이미 섞여 적재**돼 있다(§1-5). 이로써:
- **질문 0·0-1·2가 답이 났다** — 실키로 적재됨(5건 sample 아님), **API 키 신청(§3 Q2) 불필요**.
- **§1-2 우려가 "미래 위험"이 아니라 이미 벌어진 상황으로 확정** — `design.md` L92에서 "드롭 확정"된 COOKRCP01이 실제로는 `recipe`에 살아 있어 `source` 필터 없는 쿼리엔 앱에 노출된다.

→ 지금 진짜 결정할 것은 **(1) COOKRCP01·EPIS를 앱 서비스에서 어떻게 격리할지(또는 서비스 정책을 명문화할지)** + **(2) 학습 전용 보존 방식(§2 분리안 채택 여부)**. "적재/실키" 이슈는 종료.

---

## 1. 확인된 사실 (코드로 검증 완료)

### 1-1. COOKRCP01과 EPIS는 서로 다른 레시피 소스라 자동으로 안 이어짐

`pipelines/ingest/load_recipe.py`(커밋 `2d55e74`, 2026-07-13) 확인 결과:

- `load_cookrcp01()`(L44-65) — `source='COOKRCP01'`, `src_recipe_id`=`RCP_SEQ`(식품안전나라 자체 ID)
- `load_epis()`(L93-120) — `source='EPIS'`, `src_recipe_id`=`RECIPE_ID`(농교원 자체 ID)
- 두 함수는 완전히 독립적으로 실행되고, 서로의 `src_recipe_id`를 참조/조인하는 코드가 **없음**
- `recipe` 테이블 스키마(`docs/prd/schema-public-data.sql` L79) — `UNIQUE (source, src_recipe_id)`로 소스별 독립 키

→ EPIS는 자기 레시피의 **정형 재료(gold label)**만 주고, COOKRCP01은 별개 레시피의 **자유텍스트**만 준다. "EPIS+COOKRCP01 적재 = 라벨링된 학습셋"이 아니다 — 적재 후 건우 쪽에서 **EPIS 재료명을 사전(gazetteer)으로 삼아 COOKRCP01 텍스트에 매칭시키는 약지도(weak supervision) 라벨링**을 별도로 해야 한다(이건 태현 작업 아님, AI 쪽에서 진행).

### 1-2. COOKRCP01이 앱 서비스 데이터에서는 이미 드롭 확정, 그런데 학습용으로도 안전한 상태는 아님

- `docs/design.md` L92 — "식약처 COOKRCP01 | 레시피 API 드롭 (만개의레시피로 대체)" — **앱 서비스용 레시피 소스**로는 COOKRCP01 대신 10K(만개의레시피)를 쓰기로 확정됨.
- `pipelines/ingest/load_10k_recipe.py`(커밋 `a28a52e`) 확인 결과, 실제 코드는 `source='10K'`로 upsert하고(L71-79), delete는 `recipe_id=%s`로 **그 10K 레코드 자신의 id에만 스코프**돼 있음(L81-82) — **`source='COOKRCP01'` 행을 직접 지우는 코드는 현재 없음**. 단, 파일 docstring(L1, L9)에 "COOKRCP01 교체(완료)"라고 적혀 있어서, **의도/방향성 상 COOKRCP01을 없는 셈 치는 쪽으로 굳어지고 있다는 신호**임 (`ner-training-data-spec.md` §0의 2026-07-14 재확인 항목에서 건우가 이미 이 우려를 제기함).

→ 지금 당장 COOKRCP01 행이 삭제되는 건 아니지만, **"COOKRCP01은 안 쓴다"는 팀 컨센서스가 굳어지면 다음 리팩터에서 진짜로 정리될 위험**이 있다. NER 학습엔 COOKRCP01의 자유텍스트가 꼭 필요하므로(10K는 TDM 옵트아웃이라 학습 코퍼스로 사용 금지 — `data-validation.md` §2.2), **명시적으로 "COOKRCP01 = 앱 서비스에서는 드롭, 학습 전용으로는 별도 보존"이라는 예외를 문서화**해둘 필요가 있음.

### 1-3. API 실키 미발급 — 지금 상태로는 5건짜리 sample만 나옴

`.env.example` 확인:
```
DATA_GO_KR_SERVICE_KEY=            # 온라인가격용, 이것과 별개
# FOODSAFETY_API_KEY=              # COOKRCP01용 — 주석 처리, 미발급
```
`EPIS_API_KEY` 항목은 `.env.example`에 **아예 없음**. `load_recipe.py` L18-19를 보면 두 키 모두 없으면 `"sample"`로 폴백되고, `load_cookrcp01()`의 페이징 루프(L38-49) 주석에 "sample키는 5건서 break" 명시됨.

→ 서버(`fb-data` `.8`) 접근이 복구되어 `load_recipe.py`를 실행해도, **실키가 없으면 COOKRCP01·EPIS 각 5건씩만 들어옴.** CRF 학습에 필요한 최소 볼륨(수백 건 단위)에 한참 못 미침. **이게 서버 접근보다 먼저 풀어야 할 진짜 블로커.** (단, 아래 §1-4 참고 — 이 전제 자체를 재확인해야 함.)

### 1-4. (신규, 2026-07-14) `foodbudget` DB가 이미 적재된 상태로 확인됨 — §1-3 전제 재확인 필요

`docs/design/api-spec.md`(PR #33, 봉수, 2026-07-14 병합)에 이런 문구가 새로 추가됨:

> "적재 완료된 `foodbudget` DB 실 컬럼으로 확정 (2026-07-14 확인). 소스: `schema-public-data.sql` + **DB introspection**."

이 문서의 `#18 GET /api/recipes`·`#19 GET /api/recipes/{id}` 섹션은 `recipe`/`recipe_ingredient`/`food_nutrition` 테이블에 **실제 값이 들어있다는 전제로** 컬럼을 설명하고(예: "10K 소스는 `category`·`cook_method`·`kcal`·`image_url` 대체로 `null`" — 이건 실제 로우를 봐야 알 수 있는 내용), `#28`(재료별 최저가)·`#31`(핫딜)도 `item_master` 매칭률 ~89%까지 구체 수치로 제시함. 즉 **최소한 10K·소매(컬리/오아시스)·item_master는 이미 서버에 로드돼 있고, 누군가(추정: 태현 또는 봉수) 최근에 실제로 DB에 접속해서 확인했다.**

**근데 이 문서는 COOKRCP01·EPIS가 로드됐는지는 언급이 없음** — `#18`이 10K의 null 패턴만 콕 집어 설명하고 COOKRCP01/EPIS는 언급을 안 한 게, ⓐ 아직 안 실었거나 ⓑ 실었는데 이 문서에서 굳이 안 다뤘거나 둘 다 가능. **§1-1·§1-2·§1-3의 우려(비조인·격리 필요·실키 필요)는 여전히 유효한 질문이지만, "지금 상태가 어떤지"부터 다시 확인해야 정확한 다음 액션이 나옴.** → **§1-5에서 실조회로 확정함.**

### 1-5. (신규, 2026-07-20) `recipe` 실조회 결과 — COOKRCP01·EPIS 이미 적재 확정

`foodbudget` DB에 직접 접속해 소스별 건수를 조회함(§1-4의 질문 #0을 실측으로 해소):

```sql
SELECT source, count(*) FROM recipe GROUP BY source;
```
| source | 건수 |
|---|---|
| 10K | 6,446 |
| **COOKRCP01** | **1,146** |
| **EPIS** | **537** |
| **합계** | **8,129** |

`recipe_ingredient` 총 **65,083건**.

**확정 사실:**
1. **COOKRCP01·EPIS 모두 `recipe`에 이미 적재됨** — 10K와 **같은 테이블에 혼재**. → `source` 필터를 빠뜨린 쿼리는 "드롭됐어야 할" COOKRCP01을 앱에 노출한다(§1-2 우려 = 현실).
2. **실키로 적재됨** — COOKRCP01 1,146·EPIS 537건은 `sample`(각 5건)을 훨씬 초과. → §1-3 "실키 없어 5건만" 전제는 **이미 해소됨**. **API 키 신청(§3 Q2) 불필요.**
3. NER 학습 원문(COOKRCP01 자유텍스트 1,146건)이 **이미 서버에 존재** — 별도 재적재 없이 학습 코퍼스 확보 가능. 남은 건 격리·보존 방식 결정뿐.

*조회: data-pipeline 컨테이너 env(`PGDATABASE=foodbudget`, fbapp)로 `SELECT`. 읽기 전용.*

---

## 2. 권장 분리 방식 (미확정 — 태현 검토·승인 필요)

`ner-training-data-spec.md` §0에서는 "A안(COOKRCP01 학습 전용 테이블 분리)"만 방향으로 제시하고 구체 스키마는 태현 판단으로 남겨뒀는데, 논의를 빠르게 진행하기 위해 건우 쪽에서 구체안을 하나 만들어봄. **아래는 권장안이지 확정이 아님 — 그대로 써도 되고, 태현 판단으로 바꿔도 됨.**

### 왜 `recipe`/`recipe_ingredient` 재사용이 아니라 신규 테이블을 권장하는가

1. `design.md` L92에서 COOKRCP01은 **앱 서비스 레시피 소스에서 이미 드롭 확정**임. 같은 `recipe` 테이블에 `source='COOKRCP01'`로 계속 넣어두면, 누군가 `source` 필터를 빠뜨린 쿼리를 짤 때마다 "드롭됐어야 할 데이터"가 앱에 다시 노출될 구조적 위험이 있음 — 격리를 테이블 레벨에서 강제하는 게 안전.
2. `recipe_ingredient.ner_status`(스키마 L89-91)는 이미 4가지 값(`CRAWLER`/`LABELED`/`RAW`/`NER_PARSED`)이 소스별로 의미가 고정돼 있어서, 여기에 "학습 전용" 의미를 얹으면 나중에 헷갈림.
3. 마이그레이션 비용은 테이블 1개 추가뿐이라 작음.

### 권장 DDL

```sql
-- ner_train_corpus — CRF 재료 NER 학습 전용 원문 코퍼스 (COOKRCP01). 앱 서비스 미노출.
CREATE TABLE ner_train_corpus (
  id              bigserial PRIMARY KEY,
  source          text NOT NULL DEFAULT 'COOKRCP01',  -- 향후 다른 학습전용 소스 추가 대비, 지금은 고정값
  src_recipe_id   text NOT NULL,                        -- COOKRCP01 RCP_SEQ
  recipe_name     text,                                 -- 참고용(선택) — 학습 자체엔 불필요
  ingredient_raw  text NOT NULL,                         -- RCP_PARTS_DTLS 원문 그대로, 정규화 금지 (원칙 §1)
  ner_status      text NOT NULL DEFAULT 'RAW'
                    CHECK (ner_status IN ('RAW','NER_PARSED')),
  item_id         bigint REFERENCES item_master(item_id), -- 선택 — 있으면 학습데이터 품질 점검에 편함(§0)
  labeled_at      timestamptz,                            -- HITL 도입 시 라벨 보호용(§5 대비, 지금은 null)
  labeled_by      text,
  fetched_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source, src_recipe_id)
);
CREATE INDEX ON ner_train_corpus (src_recipe_id);
```

- **적재 로직**: `load_recipe.py`의 `load_cookrcp01()`을 이 테이블 대상으로 포크하거나 파라미터화 — 기존 `recipe` insert 대신 `ner_train_corpus` upsert로. 컬럼 매핑은 기존 코드의 `RCP_PARTS_DTLS` → `ingredient_raw` 그대로.
- **train/test 분할**: 별도 컬럼 불필요 — `id`(또는 `src_recipe_id`)를 해시/모듈로 연산해서 결정적으로 분할(§4 원칙 1 그대로 적용 가능).
- **재적재 안전성**: `UNIQUE (source, src_recipe_id)` + upsert 방식이면 10K와 동일하게 재적재해도 안전(§5 해소 패턴 재사용).

---

## 3. 확인/결정 요청 (우선순위 순)

| # | 요청 | 필요한 답 | 상태 |
|---|---|---|---|
| ~~0~~ | `SELECT source, count(*) FROM recipe GROUP BY source;` | 10K 6,446 · COOKRCP01 1,146 · EPIS 537 | ✅ **§1-5에서 실측 완료** |
| ~~0-1~~ | 실키였는지 sample(5건)이었는지 | 건수가 5 초과 → **실키** | ✅ **해소** |
| **1 (최우선)** | **COOKRCP01·EPIS가 앱에 노출되는 현 상태**(§1-5) 어떻게 할지 — 서비스 정책 명문화 or 격리 | 결정 필요 | ⬜ 대기 |
| 2 | 위 §2 학습전용 분리안 채택할지 | Yes / No(대안) | ⬜ 대기 |
| ~~3~~ | FOODSAFETY/EPIS API 키 신청 | 이미 실키 적재됨 | ✅ **불필요(스킵)** |
| 4 | §2 테이블 적재 스크립트 — 태현이 짤지 건우 초안 리뷰받을지 | 선호 방식 | ⬜ 대기 |

**이제 최우선은 1번** — COOKRCP01·EPIS가 이미 앱 서빙 `recipe`에 살아있어(`source` 필터 누락 시 노출), "드롭 확정"(design.md L92)과 실제 상태가 어긋난다. 서비스 정책을 확정하거나 격리해야 함.

---

## 참고 문서
`ner-training-data-spec.md`(§0·§5·§6·§8·§9, 원본 스펙) · `design.md` L92(COOKRCP01 드롭 결정) · `data-validation.md` §2.2(10K TDM 옵트아웃) · `schema-public-data.sql` L62-96(`recipe`/`recipe_ingredient`) · `pipelines/ingest/load_recipe.py`(커밋 `2d55e74`) · `pipelines/ingest/load_10k_recipe.py`(커밋 `a28a52e`) · `design/api-spec.md`(PR #33, §1-4 근거) · `.env.example`

*§1-5 실조회: 2026-07-20, foodbudget DB 직접 SELECT(읽기 전용).*
