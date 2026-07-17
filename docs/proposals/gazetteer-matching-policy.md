# gazetteer 매칭 정책 — 실측 기반 확립 (#130)

> **작성:** 태현 (데이터 오너) · **상태:** 제안·미확정(오너 결정 대기, 확정 시 반영). #130.
> **관련:** #54(육류 종/부위 가드 — 이 정책의 하위 케이스) · #57(품질 게이트 — 같은 정규화 레이어).
> **배경:** `docs/prd/ner-requirements-to-data.md` §1.3 정책 5항. NER은 스팬만 뽑고 표준코드 매핑은
> item_master/alias 몫 → NER 조인 정확도 상한이 이 정규화 계층 정확성에 걸린다.

## 방법 (실측)

`pipelines/ingest/gazetteer.py` `make_matcher`(exact→suffix→token→prefix 사다리)를 두 population에 전수 적용:
- **레시피**: `recipe_ingredient.ingredient_name`(매처가 실제 받는 '분리된 재료명') distinct **4,276**.
- **소매**: `retail_product.name` distinct **4,811** (retail 정규화 래퍼 `make_retail_matcher` 경유, 재료스코프 = `is_non_ingredient` 제외).

측정 스크립트는 현재 스크래치패드(throwaway) — 확정 시 `pipelines/ingest/`로 승격 예정(cf. `measure_coverage.py`).

## ③ prefix strip — 실측 결론: **"원칙 금지"는 과잉, 유지가 옳음**

### 분포 (레시피, row-weighted)
| method | distinct | rows | |
|---|---|---|---|
| exact | 698 | 42,603 | 볼륨 85% |
| suffix | 1,328 | 3,504 | |
| token | 1,185 | 1,428 | |
| **prefix** | **431** | **1,529** | 제거 시 미매칭될 전량 |
| none | 634 | 947 | |

### prefix 431종 분해 (remainder = 이름 − prefix alias)
- **420 benign** — 벗겨지는 꼬리가 가공접미(가루 536행·캔·통조림·물·즙·국물·나물·채·면·주스…) → base 정규화 **정당**.
- **11 suspect**(실질 9) — 전부 **잼/밥/떡 granularity**(딸기잼→딸기 등). **간장게장급 파국 0.**

### 소매 (retail)
- prefix 재료스코프 **204행 / 전체 매치의 ~5.5%**. 교차오분류 의심 **20종 전부 x1**.
  - ~14 = 잼 granularity(레몬잼·블루베리잼…), ~6 = 진짜 파국급: `참기름김`→참기름(실은 김)·`명란김`→명란젓·`불고기햄`→소고기·`강황쌀`→강황·`귀리쌀`→귀리.

### 진단 — 파국의 뿌리는 prefix가 아니라 **head-final 붕괴**
`참기름김`의 머리 `김`은 진짜 아이템인데 **1자라 `len≥2` 가드에 막혀 suffix 실패 → prefix로 낙하**해 앞의 `참기름`을 주움. 즉 한국어 '머리=뒤' 우선이 깨진 것.

### 권고 (미확정)
- **(A) prefix 삭제 = 기각** — 레시피 420 + 소매 204 benign(≈624종) 파괴. 문서의 "prefix 원칙 금지"는 실측상 과잉.
- **fix = head-preference 게이트** — `remainder(꼬리)가 비-prefix 사다리로 아이템에 해소되면 그 머리를 우선`. → ②(수식어/머리 정책) + ④(짧은 별칭)에서 흡수. prefix 독립 수정 불필요.

## ④ 짧은 별칭 (연결)
`len≥2` 가드가 1자 머리명사(김·쌀·잣)를 suffix에서 차단 → prefix 낙하·오분류를 **유발**. 323개 ≤2자 별칭 감사와 함께 1자 머리 허용 정책 재검토 필요(③ 파국의 실제 원인).

## ⑤ granularity — 반복 결정거리
**잼**(딸기잼·블루베리잼·레몬잼…)이 레시피·소매 양쪽에서 반복. "과일잼을 과일로 롤업 vs `잼` 아이템 분리"는 매처가 아니라 **item_master granularity 결정**(오너). 밥/떡도 동류.

## ② suffix 수식어 정책 — [진행중]
suffix가 워크호스(레시피 1,328 + 소매 2,139행). **접사를 의미보존(동물·품종·조리·종류) vs 무시가능(가공·형태·브랜드)로 가르는 정책**이 본체 — 양념치킨·볶음김치·대추방울토마토·소/돼지갈비(#54)가 여기. **#54 육류 가드를 전 클래스로 일반화.** 실측 예정(벗겨진 modifier가 의미보존 후보인 suffix 매치 규모·목록).

## ① exact/최장 우선
현재 exact 선행 + 각 칸 최장 우선 이미 존재. head-preference 게이트 도입 시 우선순위 재정의 여지만.
