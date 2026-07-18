# 개인화 레시피 랭킹 — LightGBM 학습 파이프라인 (스캐폴드)

> 개인화 레시피 랭킹(`ai-spec.md §3`)의 **2단계(P1, ML) 학습 파이프라인 준비본**. AI 담당(건우) 소유.
> **prep-ahead**: 클릭스트림 **데이터·동의(#131)가 풀리면 즉시 학습**되도록 미리 깐 것. 지금은
> **합성 데이터로 end-to-end 검증**만(실모델 학습은 데이터 대기). 저장 정책은 NER과 동일 —
> 스냅샷·모델은 AI-side 아티팩트(git→추후 S3), PG는 오프라인 1회 스냅샷만 읽는다.

---

## 왜 지금 (블로커와 무관한 준비)

- **실학습 블록**: 클릭스트림 데이터 축적 + 수집 동의 승인(#131) 대기.
- **하지만** 스키마(`activity.user_event`·`activity.recipe_impression`, #145/#146 머지)는 이미 확정 →
  그 위의 **피처 추출·학습·평가 파이프라인은 지금 완결**할 수 있다. 데이터가 흐르는 순간
  `EXTRACT_SQL`만 실행하면 학습으로 직행 → **P1 크리티컬 패스 단축.**
- 비용·지연 리스크 없음: 자체 모델(호출당 0원), 추론 ~1ms(`ai-spec §3`). Gemini와 정반대.

## 데이터 = 정석 learning-to-rank (implicit feedback)

스키마가 LTR에 그대로 맞는다:

- **노출 로그** `activity.recipe_impression` — 랭커가 보여준 것 + **규칙점수 분해 3종**
  (`score_stock`·`score_expiry`·`score_cost`)이 이미 P1 피처로 로깅됨 + `rank`.
- **상호작용** `activity.user_event`(VIEW·ADD_CART) — **암묵 라벨**(관련도).
- 노출 ↔ 이벤트를 `(user_id, session_id, recipe_id)` + 시간창으로 조인 → **라벨된 학습 예시**.
- **그룹(쿼리)** = `(user_id, session_id)` 노출 요청 1건 = LambdaMART 그룹.

### 라벨 (관련도)

| event | relevance | 근거 |
|---|---|---|
| 노출만(이벤트 없음) | 0 | 무관심 |
| VIEW | 1 | 약한 관심 |
| ADD_CART | 2 | 강한 관심(**주 라벨**, `user-behavior-data-request.md`) |

## 피처 명세 (`features.py:FEATURE_COLUMNS`)

| 그룹 | 피처 | 정의 | 출처 |
|---|---|---|---|
| 규칙점수 | `score_stock` | 재고 활용률 | recipe_impression(로깅됨) |
| 규칙점수 | `score_expiry` | 임박재료 사용 | recipe_impression |
| 규칙점수 | `score_cost` | 저비용 적합 | recipe_impression |
| 규칙점수 | `rule_score` | 규칙 종합점수(현행 baseline) | recipe_impression |
| 인기도 | `pop_view` | 레시피 전역 조회수(정규화) | user_event 집계 |
| 인기도 | `pop_cart` | 전역 담기수(정규화) | user_event 집계 |
| 인기도 | `pop_ctr` | 담기/노출 비율 | user_event÷impression |
| 유저이력 | `user_activity` | 유저 총 상호작용(활동성) | user_event 집계 |
| 유저이력 | `user_recipe_affinity` | 이 레시피와 과거 상호작용 유무 | user_event |
| 유저이력 | `user_ing_affinity` | 유저가 담은 레시피들과 재료 겹침도 | user_event⋈recipe_ingredient |
| 맥락 | `budget_fit` | 예산잔여 대비 재료비 적합 | recipe_impression.request_ctx |

> 규칙점수는 mealplan `ranking.py`(bongsu, P0)가 산출해 impression에 로깅한 값을 **재사용** —
> ML은 그 위에 유저행동·인기도를 얹어 개인화한다. **규칙만 쓰는 것이 baseline.**

## 파이프라인

```
[PG 스냅샷] activity.user_event + recipe_impression + recipe_ingredient
   → features.py  (EXTRACT_SQL → 라벨·피처·그룹)
   → train.py     (LightGBM LGBMRanker, objective=lambdarank / 그룹별)
   → evaluate.py  (NDCG@k·MAP·MRR, 규칙 baseline 대비)
   → 모델 아티팩트(→ ML Serving, NER과 동일 인프라)
```

- **train.py**는 LightGBM(LambdaMART)이 정식. **미설치 환경에선 sklearn 폴백**(pointwise)으로도
  파이프라인이 돌아 end-to-end를 증명한다(스캐폴드 목적). 프로덕션은 LightGBM.
- **synth.py**: 신호를 심은 합성 노출/이벤트 생성 → 데이터 0이어도 학습·평가 검증.

## 실행

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt            # lightgbm 포함(선택). numpy/sklearn만으로도 폴백 동작
python -m pytest test_ranking_ml.py -q     # 합성 end-to-end(피처·학습·평가·baseline대비)
# 데이터 흐른 뒤(실학습):
#   python features.py --extract  → python train.py  → python evaluate.py
```

## 서빙 통합 (2단계 블렌딩)

`SERVING.md` — 학습된 모델을 실제 추천에 붙이는 설계. 규칙 랭킹(P0, mealplan)을 바닥으로 두고
그 위에 ML 재랭킹을 얹음(콜드스타트=규칙, 데이터有=ML, 장애=규칙 폴백). mealplan(bongsu)과의
계약·담당경계 포함 — **수신: bongsu**.

## 실 추출 (extract.py)

`EXTRACT_SQL`을 psycopg로 실배선(레포 `.env` 접속, NER과 동일 오프라인 1회 읽기). 변환
`raw_to_feature_rows`(파생피처 pop_ctr·결측 처리)까지 검증됨.
⚠️ **activity 스키마가 라이브 DB에 미마이그레이션** → `extract.py`가 조기 감지·안내 후 중단.
스키마 적용(schema-production.sql의 activity, 데이터/인프라 몫) + 데이터 축적 후 재실행하면
학습행 산출. 코드는 준비 완료.

## 서빙 엔드포인트 (serve.py)

`SERVING.md §2` 계약을 실제 FastAPI로 구현 — `POST /rank/personalize`(후보+규칙점수 → 개인화 재정렬).
콜드스타트(이력<`RANKING_MIN_EVENTS`)·모델부재·피처장애 → `personalized=false`(mealplan 규칙순 유지).
모델·feature_provider 주입형이라 **합성 모델로 지금 검증 완료**. 데이터·학습 되면 모델만 교체.

## 상태 / 다음

- ✅ 피처 명세(user_ing_affinity 포함) · EXTRACT_SQL·extract.py · 학습·평가 · 서빙 설계(SERVING.md) **+ 서빙 엔드포인트(serve.py)** · 합성 end-to-end
- ✅ 수집 배선: 노출 로그(#160) · user_event 컨슈머(#161)
- ⏸ **activity 스키마 마이그레이션**(데이터/인프라) — 물리적 선행
- ⏸ Kafka 토픽 배포·produce 배선(백엔드) · 실학습(데이터 축적) · 서빙 배포(인프라)
- ⏸ mealplan ML 호출 배선 — bongsu seam(`SERVING.md §3`)
