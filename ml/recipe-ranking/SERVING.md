# 개인화 랭킹 — 서빙 통합 · 2단계 블렌딩 설계 (mealplan seam)

> 학습된 LightGBM 랭커(#158)를 **실제 추천에 붙이는** 설계. AI 담당(건우) 제안 · **수신: bongsu(mealplan)**.
> 핵심: 규칙 랭킹(P0, `mealplan/ranking.py`)을 **버리지 않고** 그 위에 ML 재랭킹을 얹는 2단계 —
> 콜드스타트는 규칙, 데이터 있는 유저는 ML. ML 장애·데이터부족은 **규칙으로 안전 폴백**.

---

## 0. 한눈 요약

```
[mealplan] 후보조회 → ① 규칙 랭킹(rank_recipes, 현행) ──┬─ 콜드스타트/폴백 → 규칙순 그대로
                                                        └─ 데이터有 → ② ML 재랭킹(serving) → 재정렬
        → 응답 + ③ recipe_impression 로깅(규칙점수 3종 = 학습데이터)
```

- **① 규칙 랭킹은 그대로** — bongsu 코드 무변경. 산출 `Ranked.score`·`coverage`·`expiring_used`·예산적합이 곧 ML 피처.
- **② ML 재랭킹은 별도 서빙**(디커플드) — mealplan은 lightgbm 의존 없이 HTTP로 점수만 받음.
- **③ 노출 로깅**이 학습 데이터를 만든다 — 이게 있어야 ②가 언젠가 학습된다(순환 완성).

## 1. 왜 2단계 (블렌딩)

| 상황 | 랭킹 | 이유 |
|------|------|------|
| 신규 유저 / 이력 부족(<N 이벤트) | **규칙(P0)** | 개인화할 데이터가 없음(콜드스타트) |
| 이력 충분 유저 | **ML(P1)** | 규칙점수 + 유저행동 + 인기도로 개인화 |
| ML 서빙 장애·타임아웃 | **규칙(폴백)** | 추천이 죽지 않게(가용성 우선) |

→ 규칙은 **바닥(floor)**, ML은 그 위 개인화 층. 챗봇의 template↔Gemini 관계와 동일 사상.

## 2. 계약 (mealplan ↔ ML serving)

**요청** `POST /rank/personalize` (ML serving):
```json
{
  "user_id": 123,
  "candidates": [
    {"recipe_id": 10, "score_stock": 0.8, "score_expiry": 2, "score_cost": 0.9, "rule_score": 8.6},
    ...
  ]
}
```
- `score_stock`=coverage, `score_expiry`=expiring_used, `score_cost`=예산적합(0~1), `rule_score`=규칙 종합.
  **전부 mealplan `rank_recipes()`가 이미 산출** → 추가 계산 없음(어댑터만).

**응답**:
```json
{ "personalized": true, "order": [{"recipe_id": 12, "ml_score": 0.94}, {"recipe_id": 10, "ml_score": 0.71}, ...] }
```
- `personalized=false` → 데이터부족/모델미학습/장애. mealplan은 **규칙순 유지**.
- `personalized=true` → `order`대로 재정렬(원 Ranked 메타는 mealplan이 recipe_id로 매핑).

**유저·인기도 피처는 serving이 자체 조회**(activity 스키마) — mealplan은 규칙점수만 넘기면 됨(경계 최소화).

## 3. mealplan이 해야 할 것 (seam, bongsu)

- [ ] **① 규칙 랭킹 후 ML 재랭킹 호출**(플래그 `RANKING_ML_ENABLED`, 기본 OFF). OFF·장애·`personalized=false`면 규칙순 그대로 → **현행 무변경**.
- [ ] **③ `recipe_impression` 로깅** — 노출한 레시피마다 `rule_score`·`score_stock`·`score_expiry`·`score_cost`·`rank`·`user_id`·`session_id` 기록. **이게 P1 학습데이터** — 로깅 없으면 ML은 영원히 학습 못 함.
  - 스키마는 이미 존재(`activity.recipe_impression`, #145/#146). 컬럼이 `Ranked` 필드와 1:1.
- [ ] `user_event`(VIEW·ADD_CART)는 프론트/백엔드가 발행(라벨) — mealplan 밖.

## 4. ML serving이 소유 (AI, ml/recipe-ranking)

- 모델 로드(LightGBM 아티팩트, NER과 동일 인프라)
- 유저 이력·인기도 피처 조회(activity 스키마, `features.EXTRACT`류)
- 콜드스타트 판정(유저 이벤트 수 < 임계 → `personalized=false`)
- 스코어링 + 정렬 반환
- 서빙 형태: **ML Serving 엔드포인트**(ai-spec §3, NER 인프라 재사용) 권장. 인프로세스도 가능하나 mealplan에 lightgbm 의존이 붙어 비권장.

## 4.1 재학습 자동화 (retrain.py)

데이터가 쌓이면 **사람 개입 없이** 주기적으로 모델을 갱신한다(무인 파이프라인).

```
activity 클릭스트림 → extract(피처행) → to_matrix → train → save_model
                                                              │
                          ranking-model 공유볼륨(/models/ranker.pkl)
                                                              │
                                          ranking-serving 이 기동/재로드 시 로드
```

- **실행**: `retrain.py --loop 86400`(compose `ranking-retrain` 서비스, 기본 일 1회) 또는 `python retrain.py`(1회, cron).
- **공유 볼륨**: `ranking-retrain`(저장) ↔ `ranking-serving`(로드)이 `ranking-model` 볼륨의 `/models/ranker.pkl` 공유 → 재학습 결과가 서빙에 반영되는 통로.
- **원자적 저장**: `save_model`이 tmp→rename → 서빙이 반쯤 쓰인 파일을 읽지 않음.
- **안전 skip(전부 비치명, 기존 모델·서빙 무손상)**:
  - activity 미마이그레이션 → skip(코드는 준비됨, 데이터 트랙 대기).
  - 학습행 < `RETRAIN_MIN_ROWS`(200) 또는 그룹 < `RETRAIN_MIN_GROUPS`(20) → 콜드스타트 skip.
  - 학습/저장 예외 → 로깅 후 skip.
- **모델 반영**: 저장 후 서빙은 다음 기동 시 새 모델을 로드(무중단 핫리로드는 후속 — SIGHUP 재로드 훅 여지). 데이터 부족 단계에선 파일이 없어 서빙이 규칙순 폴백(무해).

> 남는 인적 게이트(자동화 대상 아님, 정책): **모델 자동배포 승인** — 재학습 모델을 프로덕션 노출로 올릴 때 §6 섀도우→카나리 품질 게이트를 사람이 확인.

## 5. 콜드스타트·폴백 정책

- **콜드스타트 임계**: 유저 누적 이벤트 < `MIN_EVENTS`(예 20) → `personalized=false`(규칙).
- **모델 부재/미학습**: 아티팩트 없으면 항상 `personalized=false`.
- **타임아웃**: serving 응답 지연(예 >50ms) → mealplan이 규칙순 사용(추론 자체는 ~1ms라 여유, 네트워크·피처조회 상한).
- **일관성**: 폴백은 **차단이 아니라 규칙순** — 유저는 항상 추천을 받음.

## 6. 롤아웃 (안전 단계)

1. **로깅만 먼저** — mealplan `recipe_impression` 로깅 ON(③). 데이터 축적 시작(ML은 아직 OFF).
2. **학습** — 데이터 쌓이면 EXTRACT→학습→평가(#158). 오프라인 NDCG가 규칙 baseline 상회 확인(합성서 +49.8% 검증됨).
3. **섀도우** — `personalized`를 계산만 하고 노출은 규칙순(로그로 실온라인 비교).
4. **카나리 → 전면** — 일부 유저 ML 노출 → 지표(담기율·NDCG) 개선 확인 후 확대.

## 7. 지표

- 오프라인: NDCG@k·MAP·MRR (규칙 baseline 대비 lift, `evaluate.py`).
- 온라인: **ADD_CART율**(주 지표)·VIEW율·재고활용률. 규칙 대비 A/B.

## 8. 담당 경계

| 항목 | 담당 |
|------|------|
| 규칙 랭킹(P0)·`recipe_impression` 로깅·ML 호출 배선(플래그) | **mealplan(bongsu)** |
| ML 모델·피처조회·서빙 엔드포인트·콜드스타트 판정 | **AI(건우)** |
| `user_event` 발행(VIEW·ADD_CART) | 프론트/백엔드 |
| ML Serving·Argo·MLflow 인프라 | 인프라(NER 재사용) |

## 9. 지금 상태 / 대기

- ✅ 본 설계 · 학습·평가 파이프라인(#158, 합성 검증)
- ✅ 서빙(serve.py)·mealplan 로깅·ADD_CART 발행·ML 호출 배선(#160·166·170·171·172)
- ✅ **재학습 자동화**(retrain.py + `ranking-retrain` 서비스·공유볼륨 — §4.1)
- ⏸ 실학습 — 데이터 축적(로깅 ON + 스키마 적용 후 자동 학습)
- ⏸ 이미지 빌드·배포(CI matrix에 ranking-serving/retrain) — 인프라
