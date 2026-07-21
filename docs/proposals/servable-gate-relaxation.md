# 제안: servable 게이트 완화 — 실재료 미매칭 허용치

**상태: 미결정 (팀 결정 대기).** 이 문서는 측정치와 선택지를 정리한 것이고, 아직 채택된 정책이 아니다.
정본 정책은 확정 후 `docs/design.md`에 반영한다.

- 측정일: **2026-07-21**, 10K(만개의레시피) 레시피 **6,547건** 기준 (프로덕션 PG 실측)
- 선행 변경: 비-재료 게이트 제외는 **별건으로 이미 적용**(아래 §1) — 이 문서는 **그 다음** 단계를 다룬다
- 관련: `pipelines/ingest/index_recipes_es.py`(배치 게이트) · `deploy/pgsync/plugins/recipe_servable.py`(CDC 게이트) · [gazetteer-matching-policy.md](gazetteer-matching-policy.md)

---

## 1. 배경 — 이미 처리한 것(정의 오류)과 남은 것(정책)

게이트는 "레시피의 모든 재료에 가격을 매길 수 있나"를 묻는다. 못 매기면 재료비가 틀리므로 검색에서 뺀다.

측정 결과 차단 **2,760건**의 원인은 두 종류로 갈렸다:

| 원인 | 건수 | 성격 |
|---|---:|---|
| 비-재료(물·얼음·이쑤시개…)만이 원인 | 1,769 (64%) | **정의 오류** — 별건으로 수정 완료 |
| 실재료 미매칭 1개 | 837 (30%) | **정책** — 이 문서의 주제 |
| 실재료 미매칭 2~3개 | 142 (5%) | 〃 |
| 실재료 미매칭 4개 이상 | 12 (0.4%) | 〃 |

앞의 1,769건은 `gazetteer.STOP` 품목(= "가정이 식비 재료로 사서 가격비교할 가치가 없는 이름", `CONTEXT.md` 비-재료)이 `item_id IS NULL`이라 매칭 실패로 세어진 것이었다. 가격을 **안 매기기로 한** 것들이라 실패로 세면 안 된다 — 완화가 아니라 버그였고, `recipe_ingredient.is_non_ingredient` 컬럼으로 분리해 수정했다. 단독 최대 차단 요인은 **'물' 1,520건**이었다.

그 결과 servable은 **3,787 → 5,556건(57.8% → 84.9%)**. 아래 논의의 기준선은 이 5,556이다.

## 2. 남은 선택지

| 옵션 | 정의 | servable | 노출률 | 기준선(B) 대비 |
|---|---|---:|---:|---:|
| **B (현행)** | 실재료 미매칭 0 | 5,556 | 84.9% | — |
| **C** | 실재료 미매칭 **≤1** 허용 | 6,393 | 97.6% | +837 |
| **D** | 실재료 **매칭률 ≥80%** | 6,380 | 97.4% | +824 |
| **E** | C ∪ D | 6,462 | 98.7% | +906 |

## 3. 트레이드오프 — 무엇을 잃나

완화하면 **재료비가 과소추정된 레시피가 검색에 노출된다.** 크기를 재보면:

- C 대상 837건은 평균 재료 **9.5개**, 그중 1개 미반영 → **평균 12.7%의 재료비가 빠진다**
- 단, 앱은 이미 이 상황을 숨기지 않는다 — `services/recipe/app/queries.py`가 재료별 `cost_basis`(`no_price`/`no_convert`/`excluded_liquid`/`capped`/`usage`)를 반환하고, 설계상 "정직한 과소추정"으로 문서화돼 있다(`recipe_cost.py` 주석). 즉 **새로운 거짓말을 만드는 건 아니고, 기존의 과소추정 노출 범위가 넓어지는 것**이다.
- D는 재료가 많은 레시피에 관대하다(20개 중 4개 미매칭 통과). C는 재료 수와 무관하게 절대 1개. 어느 쪽이 예산 신뢰도에 맞는지는 제품 판단.

## 4. 대안으로 검토한 것 — 사전 큐레이션(비추천 근거)

"게이트를 건드리지 말고 `item_master`를 채우자"는 대안은 **효율이 낮다.** 미매칭 실재료는 롱테일이다:

| 미매칭 실재료 | 차단 레시피 |
|---|---:|
| 호박 | 45 |
| 모닝빵 | 24 |
| 오레오 | 13 |
| 죽염 / 불닭소스 | 각 10 |
| 화이트 발사믹 / 간마늘 20g / 에스프레소 / 조청 / 김칫국물 | 각 8 |

상위 15개를 전부 매핑해도 회수는 **200건 남짓**이다(C의 837건 대비). 큐레이션은 계속 하되 **게이트 정책과는 분리해서** 판단하는 편이 낫다. 참고로 "간마늘 20g"처럼 수량이 이름에 붙어 들어온 파싱 잔재도 섞여 있어, 일부는 큐레이션이 아니라 크롤/정규화 개선 대상이다.

## 5. 결정이 필요한 것

1. B 유지 / C / D / E 중 무엇인가
2. (완화 시) 과소추정 레시피를 UI에서 표시할 것인가 — `cost_basis`가 이미 있으니 배지 하나로 가능
3. 재측정 주기 — 크롤·큐레이션이 진행되면 위 숫자는 계속 바뀐다

## 6. 구현 시 주의

게이트는 **두 곳에 중복 구현**돼 있다. 한쪽만 고치면 두 인덱스가 어긋난다.

| 위치 | 대상 인덱스 | 형태 |
|---|---|---|
| `pipelines/ingest/index_recipes_es.py` | `recipes` (배치 · DR 폴백) | SQL `HAVING` |
| `deploy/pgsync/plugins/recipe_servable.py` | `recipes_pgsync` (**CDC · 실제 서빙**) | Python |

앱이 실제로 읽는 것은 `recipes_pgsync`다(`.9` recipe 컨테이너 `ES_INDEX=recipes_pgsync`). 플러그인은 pgsync 컨테이너에서 돌아 `pipelines/ingest/gazetteer.py`를 import할 수 없으므로, 판정에 필요한 정보는 **적재 시점에 컬럼으로 남겨** 양쪽이 같은 값을 읽게 해야 한다(§1의 `is_non_ingredient`가 그 방식).

## 부록 — 재현 방법

```sql
with ing as (
  select r.id rid, ri.item_id, ri.is_non_ingredient
  from recipe r join recipe_ingredient ri on ri.recipe_id = r.id
  where r.source = '10K'
),
per as (
  select rid,
         count(*) filter (where not is_non_ingredient)                          tot_real,
         count(*) filter (where item_id is null and not is_non_ingredient)      unm_real
  from ing group by rid
)
select
  count(*) filter (where unm_real = 0)                                          as "B",
  count(*) filter (where unm_real <= 1)                                         as "C",
  count(*) filter (where tot_real > 0
                     and (tot_real - unm_real)::float / tot_real >= 0.8)        as "D"
from per where tot_real > 0;
```
