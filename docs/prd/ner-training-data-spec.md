# NER 학습 데이터 — 적재 스펙·매칭 정책·현황·데이터 요구 (통합)

> 작성: 건우 (AI 담당) · 2026-07-13 · **통합 2026-07-27** (`ner-data-handoff-briefing`·`ner-requirements-to-data` 흡수 — 건우→태현 핸드오프 일원화)
> 대상 독자: 데이터 파이프라인 담당(태현)
> 스코프: **CRF 재료 NER**(`ai-spec.md §1`, `design.md §4.1`) 학습·적용을 위한 ① 적재 제약 ② item_master 매칭 정책 요구 ③ 현황 ④ 데이터 합의. 모델 설계 자체는 `ai-spec.md §1` 소관.

---

## 0. 현황 요약 (2026-07-20 DB 실조회 확정)

`foodbudget` DB 직접 `SELECT source, count(*) FROM recipe GROUP BY source;`(읽기 전용, data-pipeline 컨테이너 env):

| source | 건수 |
|---|---|
| 10K | 6,446 |
| **COOKRCP01** | **1,146** |
| **EPIS** | **537** |
| 합계 | 8,129 |

`recipe_ingredient` 총 **65,083건**(`RAW` 1,143 / `LABELED` 5,933 / 나머지 `CRAWLER`).

**확정 사실:**
1. **COOKRCP01·EPIS 모두 이미 적재됨** — 10K와 **같은 `recipe` 테이블에 혼재**. → `source` 필터 누락 쿼리는 "드롭됐어야 할" COOKRCP01을 앱에 노출(§5 남은 결정).
2. **실키로 적재됨**(각 5건 `sample` 초과) → API 키 신청 **불필요**(과거 블로커 해소).
3. NER 학습 원문(COOKRCP01 자유텍스트 1,146건)이 **서버에 존재** → 재적재 없이 코퍼스 확보 가능. 남은 건 격리·보존 방식뿐.

---

## 1. 확정 결정 — 라벨·모델 저장 = 모델 X (AI-side 아티팩트)

> **결정(2026-07-15) — "학습전용 테이블 분리"안 철회, 모델 X 채택.** COOKRCP01/EPIS가 적재됐고 서빙이 이미 `source='10K'`만 격리(#46)하므로, 코퍼스는 **읽기만** 하면 된다.

- 약지도 라벨 코퍼스 + 학습된 CRF 모델을 **AI-side 아티팩트**로 둔다 — 1차 **git 버전관리**(CRF 모델 KB~MB·코퍼스 수 MB로 소형), AWS 이전 시 **S3/MLflow** 승격(`ai-spec.md §1`). **공유 PG에 라벨을 쓰지 않는다.**
- **읽기 = 1회 스냅샷 export → 오프라인 학습**(§3.1 #4). 학습이 OLTP에 라이브 반복 쿼리를 안 날려 **DB 부하 우려 없음**(태현 지적 대응). ⚠️ 같은 PG에 학습전용 테이블을 둬도 워크로드 격리는 안 됨(같은 인스턴스) — 부하 관점에선 X+스냅샷이 오히려 유리.
- **근거**: ① 서빙 성능 무관(서빙은 학습된 모델+gazetteer만 읽음) ② 앱 OLTP 결합·재적재 위험 회피 ③ Docker→k8s→AWS 이전 안전(포터블 저장소; 컨테이너 로컬파일만 금지) ④ 태현 의존 0.
- **함의**: 태현은 학습용 **새 테이블·스키마 변경 불필요** — §2·§3.1만 지키면 됨.

## 2. 적재 파이프라인 제약 (지켜야 할 것)

### 2.1 원문(raw text) 보존
- `ingredient_raw`는 소스 원본 그대로, **정규화·축약·동의어 치환 없이** 저장(10K는 `재료원문` 컬럼 그대로 적재 확인 — 유지 요청). CRF가 문자 오프셋으로 라벨을 정렬하므로 다듬으면 학습 라벨과 실사용 입력 분포가 어긋남.

### 2.2 TDM 옵트아웃 소스의 물리적 격리 (하드 제약)
- 10K(만개의레시피) `ingredient_raw`는 **저장은 되지만 학습에 쓰면 안 됨.** 학습 추출 쿼리/뷰가 이 소스를 구조적으로 제외하도록 **`WHERE source != '10K'` 고정.**
- 근거: `data-validation.md §2.2` — robots.txt `Content-Signal: ai-train=no` 명시적 권리유보.

### 2.3 재료명은 원문의 부분 문자열
- `ingredient_name`은 원문 substring 유지(동의어 정규화는 `item_master`/`gazetteer.py` 매핑 단계에서 — 원재료 텍스트 단계에서 건드리지 말 것). 10K는 크롤러가 이미 이 방식대로 분리(확인됨), EPIS는 원문 없어 해당 없음.

### 2.4 train/test 분할 (원칙만, 값은 데이터 볼륨 보고 확정)
- **원칙 1 — 결정적**: 랜덤 셔플 금지. `recipe_id` 같은 불변 키를 해시/모듈로 연산해 항상 같은 레시피가 같은 쪽(train/test)에 떨어지게 고정(모델 개선 비교 기준 유지).
- **원칙 2 — 비율보다 test 절대 건수**: 볼륨 작을 때 8:2가 test를 너무 작게 만들면 평가 불안정 → "test 최소 N건 고정" 같은 절대값 기준도 고려.

### 2.5 증분 적재 시 `ner_status` 보존
- ✅ **10K 해소**: `load_10k_recipe.py`가 `process_recipe()`로 **레시피 단위 upsert**(`on conflict (source, src_recipe_id) do update` + `recipe_id` 스코프 delete/insert)라, `CRAWLER` 행은 매번 gazetteer로 `item_id` 재계산 → 재적재해도 유실될 라벨 없음.
- ⚠️ 향후 사람 검수 라벨(HITL) 도입 시 재크롤에 지워지지 않게 `labeled_at`·`labeled_by` 컬럼으로 보호 권장.

### 2.6 `ner_status` 값
| 값 | 의미 | CRF와의 관계 |
|---|---|---|
| `CRAWLER` | 크롤러가 재료명/수량 분리(10K) | NER 미적용 — gazetteer로 `item_id`만 해소 |
| `LABELED` | 정형 gold(EPIS) | 학습 라벨 후보지만 자유텍스트 없음 |
| `RAW` | 자유텍스트(COOKRCP01) | NER 미적용 → 약지도 라벨 대상 |
| `NER_PARSED` | CRF 적용 완료 | 목표 상태 |

### 2.7 Kafka 스트리밍 경로 — 별도 요구 불필요
- `pipelines/stream/consume_recipe.py`(recipe-refiner)가 `load_10k_recipe.py`의 `process_recipe()`를 그대로 재사용 → §2.1·2.3·2.5 요구가 스트리밍에도 자동 적용. 확인만: `process_recipe()` 로직 변경 시 이 원칙들이 유지되는지.

## 3. NER 학습 데이터 합의 항목 (건우→태현)

### 3.1 합의 필요 (확약 요청)
| # | 항목 | 요청 | 결정 |
|---|---|---|---|
| 1 | **원문 보존** | `recipe_ingredient.ingredient_raw`(COOKRCP01 자유텍스트)를 정규화·축약 없이 원형 유지 | 유지 확약 |
| 2 | **삭제·덮어쓰기 금지** | COOKRCP01·EPIS 행을 재적재/정리 시 삭제 안 함(서빙이 이미 격리 → 앱 영향 없음) | 유지 확약 |
| 3 | **재적재 안전성** | `ner_status='RAW'/'LABELED'` 행 유실 방지 레시피 단위 upsert. 검수 라벨 보호 컬럼(`labeled_at`,`labeled_by`) 여지 | 방식 합의 |
| 4 | **읽기 = 스냅샷 export 확정** | 학습은 **1회 벌크 export**(CSV/JSONL, `source != '10K'`) → 오프라인 학습. PG 반복 쿼리 안 함(수 MB 1회). 재현성 위해 export 시점 타임스탬프 포함 | **ⓑ 확정** |

> 최소 1·2·4만 확약돼도 NER 착수 가능(데이터 이미 적재됨).

### 3.2 건우 몫 (태현 작업 아님 — 공유용)
- EPIS와 COOKRCP01은 **서로 다른 소스라 `RECIPE_ID`로 조인 안 됨**(EPIS=정형 gold, COOKRCP01=자유텍스트, 별개 레시피). → 건우가 **EPIS 재료명을 사전으로 COOKRCP01 텍스트에 문자열 매칭해 약지도(weak supervision) BIO 라벨 자동 생성**(AI 쪽 진행).
- 10K 텍스트는 학습 코퍼스 사용 금지(`ai-train=no`, `data-validation §2.2`) — `source != '10K'` 고정.

## 4. item_master / gazetteer 매칭 정책 요구 (Part 1)

> ⚠️ **핵심: "육류 버그" 하나가 아니라 매칭 메커니즘·granularity 정책 문제.** 개별 케이스만 고치면 무한 땜빵 → **정책 확립** 요청.

### 4.1 문제 — 체계적 오분류 (실측)
gazetteer(`make_matcher`)는 별칭 **1,055개**(그중 **1~2자 짧은 별칭 323개**)에 exact/prefix/suffix 매칭 → strip 매칭이 수식어를 무차별로 벗겨 오분류:
| 클래스 | 예 | 결과 | 심각도 |
|---|---|---|---|
| **prefix 오매칭** | 간장게장 → 간장(prefix) | 게장이 간장으로 완전 오분류 | 🔴 |
| 동물·부위(**#54에서 처리**) | 소갈비 → 갈비 / 돼지갈비 → 돼지고기 | 육류 뭉갬·경로 불일치 | 🔴 |
| 조리형태 | 양념치킨 → 닭고기(suffix) | 조리 정보 손실 | ⚠️ |
| 품종/원산지 | 대추방울토마토 → 방울토마토 | 품종 손실 | ⚠️ |
| 종류 | 볶음김치·열무김치 → 김치 | 종류 손실 | ⚠️ |
| 짧은 별칭(≤2자) | 밥·김·무·파·란 등 323개 | 부분매칭 오탐 표면 | ⚠️ |

### 4.2 근본 원인
1. **수식어 정책 부재** — 보존해야 할 수식어(동물·품종·조리·종류) vs 무시 가능(가공·브랜드)를 strip이 구분 없이 다 벗김.
2. **granularity 일관성 부재** — 복합어를 별도 품목 vs base 뭉갬 기준 없음.
3. **짧은 별칭 오매칭** — ≤2자 323개.
4. **prefix 매칭 위험** — 앞부분만 잡아 완전 오분류(간장게장).

### 4.3 요구 — 정책 확립
1. **매칭 정책 정의·문서화**: ① exact/최장 별칭 우선(strip보다) ② **보존 수식어 클래스 목록**(동물·품종·조리·종류) 접두/접미 안 벗기게 ③ **prefix strip 원칙 금지**(오분류 위험) 재검토.
2. **짧은 별칭(≤2자) 감사**: 323개 검토 → 독립 토큰일 때만 매칭 or 위험한 것 제거.
3. **granularity 기준**: 복합어 별도 품목 vs base 뭉갬 일관 규칙.
4. **육류(동물·부위)는 #54([`gazetteer-meat-granularity.md`](../proposals/gazetteer-meat-granularity.md))에서 처리 중** — `proto_meat_guard.py` 수식어 가드 프로토타입 진행. **이 문서는 육류를 중복 요청하지 않음.** 위 정책(1~3)이 육류 포함 전 클래스의 상위 규칙, #54의 육류 결정(종 세분화·remap)은 그 정책과 정합.

> NER은 스팬만 뽑고 **표준코드 매핑은 item_master/alias 몫**이라, NER 조인 정확도 상한이 이 정규화 계층 정확성에 걸린다(`design.md §6.3`). 위 정책이 서면 NER·챗봇·조인이 함께 좋아진다.

## 5. 남은 결정 · 우선순위

| 순위 | 항목 | 상태 |
|---|---|---|
| 1 (최우선) | **COOKRCP01·EPIS 앱 노출 격리** — 이미 서빙 `recipe`에 살아있어(`source` 필터 누락 시 노출) "드롭 확정"(`design.md` L92)과 실상태 불일치. 서비스 정책 명문화 or 격리 | ⬜ 대기 |
| 2 | §4.3 item_master 매칭 정책(①~④) 방향 회신 — NER 조인 정확도 상한 결정 | ⬜ 대기 |
| 3 | §3.1 #1·2·4 확약 (원문 보존·삭제금지·스냅샷) | ⬜ 대기 |

**회신 오면 건우가 약지도 라벨링 → CRF 학습 착수.** (EPIS API 실키 신청은 §0에서 해소 — 스킵.)

---

## 부록. 히스토리 (해소·철회 — 참고용)

- **§0 A/B/C 옵션 논의**(학습 코퍼스 부재 → 학습전용 테이블 vs 합성문장 vs 영수증) — **철회.** 데이터 적재 확정 + 모델 X로 무의미(§1).
- **`ner_train_corpus` 학습전용 테이블 DDL**(구 briefing §2 권장안) — **철회.** 모델 X(§1)로 대체, 새 테이블 안 만듦. (DDL은 git 이력에 보존.)
- **API 키 신청**(FOODSAFETY/EPIS_API_KEY) — 실키 적재 확인(§0)으로 **불필요**.
- **인계 인터페이스**(실시간 쿼리 vs 스냅샷) — **스냅샷 export 확정**(§3.1 #4).
- 근거 커밋: `load_recipe.py`(`2d55e74`) · `load_10k_recipe.py`(`a28a52e`) · `design/api-spec.md`(PR #33) · 실조회 2026-07-20.

## 참고 문서
`ai-spec.md §1`(NER 모델 설계) · `data-validation.md §2.2`(10K TDM 옵트아웃) · `design.md §3.3`(COOKRCP01 드롭)·`§6.3`(품목 마스터 조인 허브)·`L92` · `schema-public-data.sql`(`recipe_ingredient` NER seam) · `pipelines/ingest/{load_recipe,load_10k_recipe,gazetteer,index_recipes_es}.py` · `pipelines/stream/consume_recipe.py`(§2.7) · `proposals/gazetteer-meat-granularity.md`(육류 #54)
