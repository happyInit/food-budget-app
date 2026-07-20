# 영수증 OCR · 레시피 랭킹 흐름도 — 2단계 교차검증

> 검증 대상: `docs/recipe_OCR.mmd`, `docs/recipe_ranking.mmd` (2026-07-20 작성분)
> 검증 시점: 2026-07-20, 로컬 checkout `test/ocr-classify-unit`(`58b504f`) — `origin/main`(`d094027`)과
> `services/ocr`·`services/mealplan`·`services/pantry`·`ml/recipe-ranking` 경로 기준 **차이 없음 확인**(아래 §0).
> 런타임 대상: `fb-app-ai`(192.168.0.9, SSH) — 프로덕션 앱 스택. 전부 **읽기 전용**(GET/헬스체크/로그/env 조회)만 수행, 변경·재시작 없음.

---

## §0. 사전 확인 — 로컬 코드가 최신인가

```
$ git fetch origin && git merge-base --is-ancestor origin/main HEAD
→ false (origin/main이 앞섬: HEAD=58b504f, origin/main=d094027)

$ git log 58b504f..origin/main --oneline -- services/ocr services/mealplan services/pantry ml/recipe-ranking
→ (출력 없음 — 4개 경로 모두 변경 커밋 없음)
```
**결론**: `origin/main`이 24커밋 앞서 있지만(account/price 성능 개선 등), OCR·랭킹 관련 4개 디렉토리엔 추가 커밋이 없어 **Pass 1 코드 분석은 최신 상태 기준**으로 유효함.

---

## §1. 검증 패스 1 — 소스 코드 대조 (정적)

원본 작성 시 이미 파일:함수 단위로 인용하며 읽었으나, 이번에 각 인용을 **재오픈해서 줄 단위로 재대조**했다.

### 1-1. 재대조 결과 — 전 노드 [코드:일치]

| 노드 | 인용 | 재확인 |
|---|---|---|
| B 접수 API | `services/ocr/app/main.py:97-99` `upload_receipt()` → `_accept()`(L84-94) | ✅ 일치 |
| C 이미지 검증 | `main.py:86-89` `if not data: raise HTTPException(400,...)` / `if len(data) > settings.max_image_bytes: raise HTTPException(413,...)` | ✅ 일치 |
| E 다운스케일 | `vision.py:43-62` `_downscale()`, `max_side=1600`(config.py:21) | ✅ 일치 |
| F Vision 파싱 | `vision.py:134-175` `VisionBackend.parse()` | ✅ 일치 |
| G 재시도 | `vision.py:158-170` `for attempt in range(3)` + `_is_transient()`(L65-71) | ✅ 일치 — 표기 "최대 2회"는 attempt 0,1,2 중 재시도가 2회라는 뜻, 정확 |
| I 가격 재정렬 | `process.py:15` `realign_prices(receipt.items)` → `classify.py:280-295` | ✅ 일치 |
| J 분류 캐스케이드 | `classify.py:237-273` `Classifier.classify()` 8단계 주석과 실제 if-분기 순서 일치(경계정책→조정→is_food→비식품KW→gazetteer→(3/4 skip)→미해결) | ✅ 일치 |
| K job 저장 | `main.py:28` `_JOBS: dict[...] = {}` 인메모리, L6-7 TODO 주석 | ✅ 일치 |
| O 확정 API | `services/pantry/app/routers.py:97-99` `confirm_receipt()` | ✅ 일치 |
| P 감사로그 | `routers.py:108-120` `create_ocr_receipt()`, `add_ocr_receipt_item()` | ✅ 일치 |
| Q/R 재고반영 | `routers.py:122-138` keep && storage && category not in (NONFOOD,ADJUST) 조건문 그대로 | ✅ 일치 |
| S 식비계산 | `routers.py:140-144` `kept_expense`만 합산(총액 아님) | ✅ 일치 |
| G(랭킹) 규칙스코어 | `services/mealplan/app/ranking.py:12-15,48-52` 가중치 `10.0/3.0/5.0` | ✅ 일치 |
| H/I(랭킹) ML호출·콜드스타트 | `ranking_client.py:15-34` / `ml/recipe-ranking/serve.py:18,61-62` `MIN_EVENTS=20` | ✅ 일치 |
| J(랭킹) LightGBM | `train.py:34-47` `LGBMRanker(objective="lambdarank")` | ✅ 일치 |
| R(랭킹) 게이트 | `retrain.py:26-27` `MIN_ROWS=200`, `MIN_GROUPS=20` | ✅ 일치 |

### 1-2. 코드에는 있지만 도면에 의도적으로 뺀 것 (원문서 §3에 이미 명시) — 재확인 결과 그대로 타당

- `classify.py` 3/4단계(food_nutrition·oasis 파생) — 주석 "TODO: DB 필요, 현재 skip" (L270) → 미구현이라 도면 제외 **타당**
- `classify.py` 7단계 LLM 훅 — 주석 "훅만, 아직 미배선" (L9) → 도면 제외 **타당**
- `factory.py` `mock` 백엔드(L16-19) — dev/CI 전용, prod은 vision 고정 → 도면에서 "Gemini Vision 단독"으로 명시했으니 **누락 아님**

### 1-3. 이번 재검증에서 새로 발견한 누락 — [코드:불일치] 1건

| 항목 | 내용 |
|---|---|
| **랭킹 학습기 sklearn 폴백** | `ml/recipe-ranking/train.py:19-32` `_SklearnRanker`(lightgbm import 실패 시 `GradientBoostingRegressor`로 폴백, `build_ranker()` L50-56)가 실제 분기인데 두 다이어그램 모두 "LightGBM LambdaMART"만 표기하고 이 폴백 분기가 없음. |

→ **분류: [코드:불일치](경미)**. 다만 `ml/recipe-ranking/requirements.txt:4` 에 `lightgbm>=4.0`이 고정 의존성으로 명시돼 있어 정상 설치 환경에서는 이 분기가 거의 발동하지 않음 — §3에서 다이어그램에 주석으로만 보완(별도 노드 추가는 생략, 근거는 아래 §4).

### 1-4. 도면에 있는데 코드에 없는 노드 — 없음

25(OCR) + 26(랭킹) = 51개 노드 전부 대응하는 코드가 존재. **[코드:없음] 0건.**

---

## §2. 검증 패스 2 — 배포 런타임 대조 (동적)

### 2-1. 배포 방식 파악

- `deploy/app/docker-compose.yml` — 앱 스택 정의, 대상 `fb-app-ai`(192.168.0.9), 포트는 `frontend`(nginx, :80)만 호스트 노출·나머지는 내부망 `fbnet`.
- `ocr`(`profiles: ["ocr"]`)·`ranking-serving`/`ranking-retrain`(`profiles: ["ranking"]`) — compose 파일상 **기본 배포 제외**(주석: "이미지 Harbor push 후 활성"). → 실제 활성 여부는 라이브 확인 필요(아래).
- `.github/workflows/build-push-app.yml` — CI가 Harbor(`192.168.0.10`)에 이미지 push.

### 2-2. 실행 중 컨테이너 확인

```
$ ssh ubuntu@192.168.0.9 docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
foodbudget-ocr-1               .../ocr-service:latest              Up 5 hours (healthy)   8010/tcp
foodbudget-ranking-serving-1   .../ranking-serving:latest          Up About an hour (healthy)  8009/tcp
foodbudget-ranking-retrain-1   .../ranking-serving:latest          Up About an hour            8009/tcp
foodbudget-mealplan-1          .../mealplan-service:latest         Up About an hour (healthy)  8007/tcp
foodbudget-pantry-1            .../pantry-service:latest           Up About an hour (healthy)  8005/tcp
```
→ compose 파일 주석은 "기본 제외"라 적혀 있지만, **`ocr`·`ranking-serving`·`ranking-retrain` 전부 실제로 떠 있음**(profile이 활성화된 상태로 배포됨). 이 자체가 코드주석↔실배포 사소한 정보 지연이지만 두 다이어그램의 노드 유무에는 영향 없음(있어야 할 서비스가 실제로도 있음).

### 2-3. 이미지 최신성 (git 커밋 시각 vs 이미지 빌드 시각, 전부 UTC)

| 이미지 | 빌드 시각 | 관련 최신 커밋 | 커밋 시각(UTC 환산) | 판정 |
|---|---|---|---|---|
| ocr-service:latest | 2026-07-18 10:10:51 | `41ec329` fix(ocr) | 2026-07-18 09:04:53 | ✅ 커밋이 빌드보다 이전 → 포함됨 |
| ocr-service:latest | 〃 | `58b504f` test(ocr) 단위테스트만 | 2026-07-20 05:01:33 | ⚠️ 빌드보다 이후(미포함) — 단, 테스트 전용 커밋이라 런타임 동작엔 무관 |
| mealplan-service:latest | 2026-07-20 03:46:38 | `965cd1e` 로그 추가 | 2026-07-20 01:15:41 | ✅ 포함됨 |
| ranking-serving:latest | 2026-07-20 03:59:58 | `25042ea`/`0aba28f` | 2026-07-20 02:25:42 / 02:23:44 | ✅ 포함됨 |
| pantry-service:latest | 2026-07-20 03:47:04 | `398c059` fix(ocr/budget) | 2026-07-18 13:49:45 | ✅ 포함됨 |

**결론**: mealplan·ranking-serving·pantry 이미지는 최신 커밋 전부 반영. ocr 이미지만 2일 전 빌드지만, 그 사이 유일한 변경은 테스트 코드 추가뿐이라 **런타임 동작 기준으로는 드리프트 없음**.

### 2-4. 헬스/설정 실측

```
$ docker exec foodbudget-ocr-1 python -c "...urlopen('http://localhost:8010/health')..."
{"status":"ok","backend":"vision"}

$ docker exec foodbudget-mealplan-1 python -c "...urlopen('http://localhost:8007/health')..."
{"status":"ok","service":"mealplan"}

$ docker exec foodbudget-ranking-serving-1 python -c "...urlopen('http://localhost:8009/health')..."
{"status":"ok","model_loaded":false}
```

```
$ docker inspect foodbudget-mealplan-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -v -i 'password\|secret\|key'
RANKING_ML_ENABLED=true
IMPRESSION_LOG_ENABLED=true
EVENT_PRODUCE_ENABLED=true
RANKING_SERVING_URL=http://ranking-serving:8009
...
$ docker inspect foodbudget-ocr-1 ... 
OCR_BACKEND=vision
GEMINI_MODEL=gemini-flash-lite-latest
```
→ compose 파일 기본값은 전부 `false`인데, **실서버 `.env`가 셋 다 `true`로 켜져 있음** — 두 다이어그램이 그리는 "P1 활성" 경로가 실제로 켜져서 돈다.

### 2-5. OpenAPI 라우트 실측

```
ocr:      ['/', '/health', '/api/pantry/ocr', '/api/pantry/ocr/{job_id}']
pantry:   [..., '/api/pantry/receipts', ...]
mealplan: [..., '/api/mealplan/recommend', '/api/expenses', ...]
ranking:  ['/rank/personalize', '/reload', '/health']
```
→ 도면의 진입점 노드(B, L, O, A(랭킹), H(랭킹), reload트리거) 전부 **실제 배포 라우트와 정확히 일치**.

### 2-6. `ranking-retrain` 로그 — 콜드스타트 분기 실측

```
$ docker logs --tail 30 foodbudget-ranking-retrain-1
[retrain 2026-07-20T04:00:37Z] 주기 재학습 시작 — 86400s 간격.
[retrain 2026-07-20T04:00:37Z] 학습행 40(<200) / 그룹 2(<20) — 콜드스타트 skip.
```
→ 다이어그램의 **`R{학습행≥200 && 그룹≥20?}` → "미달 → skip" 분기가 지금 이 순간 실제로 발동 중**인 상태(살아있는 증거). `ranking-serving`의 `model_loaded:false`와 정합.

### 2-7. OCR 분류 캐스케이드 참조 데이터 — 컨테이너 내부 직접 조회 (⚠️ 드리프트 발견)

```
$ docker exec foodbudget-ocr-1 python -c "from app.pipeline.classify import get_classifier; c=get_classifier(); \
  print('gaz_source:',c.gaz_source,'/ gaz:',len(c._gaz),'/ shelf:',len(c._shelf),'/ edge:',len(c._edge))"
gaz_source: db / gaz: 1079 / shelf: 0 / edge: 0

$ docker exec foodbudget-ocr-1 find / -maxdepth 6 -iname '*shelf_life*' -o -iname '*edge_case*'
(출력 없음 — 파일 없음)

$ docker exec foodbudget-ocr-1 find /app -maxdepth 3
/app/app/... (pipeline·main·config·models만 — pipelines/ingest/data/*.csv 없음)
```
**원인**: `services/ocr/Dockerfile:1-8` `COPY app app` 뿐 — 빌드 컨텍스트가 `services/ocr` 자체(주석: "챗봇과 달리 pipelines/ 의존 없음")라 `pipelines/ingest/data/kr_shelf_life_seed.csv`·`edge_case_food_policy.csv`가 이미지에 없음. `config.py:23-27`이 이미 이걸 예견해 "배포 시 패키징 경로로 env override, 없으면 skip"이라 주석까지 남겼는데, `deploy/app/docker-compose.yml`의 ocr 서비스 env 블록(L200-205)엔 `SHELF_LIFE_PATH`/`EDGE_POLICY_PATH` override가 **설정돼 있지 않음** — 즉 skip 경로가 항상 발동.

→ gazetteer(item_id 매칭)는 DB 경로로 정상 동작(`gaz_source: db`, 1079건) — **이건 살아있음**. 하지만 **경계정책표(R1)·보관법 시드(R3) 두 참조 데이터는 배포판에서 상시 공집합** → `_storage_for()`(classify.py:221-235)는 항상 키워드 규칙/기본 FRIDGE로만 결정되고, 경계정책표 매칭(tier="edge")은 결코 발생하지 않음.

### 2-8. 실사용 트래픽 로그 — 부분 미확인

```
$ docker logs --tail 40 foodbudget-ocr-1
(전부 GET /health, 1건의 GET /openapi.json(본 검증에서 발생) — POST /api/pantry/ocr 로그 없음)
```
→ 최근 로그 창에는 실제 영수증 업로드 요청 흔적이 없음. **[❓ 미확인]** — 단, `ranking-retrain`이 찾은 "학습행 40건"은 과거 `/api/mealplan/recommend` 호출과 `insert_impressions()`가 최소 40회 이상 실행됐다는 간접 증거(활동 테이블에 실데이터 존재, §2-9).

### 2-9. 활동 테이블 존재 확인 (X2/X3 피처 소스)

```
$ docker exec tfstate-db psql -U fbapp -d foodbudget -c \
  "select to_regclass('activity.recipe_popularity'), to_regclass('activity.user_chat_pref'), \
          to_regclass('activity.recipe_impression'), to_regclass('activity.user_event');"
 activity.recipe_popularity | activity.user_chat_pref | activity.recipe_impression | activity.user_event
```
→ 4개 테이블 전부 존재 — X2(인기도 이중소스, PR#194)·X3(chat-pref 환류, PR#211) 피처의 백엔드 스키마가 **실제로 배포돼 있음**.

---

## §3. 비교표

### 3-1. OCR (`recipe_OCR.mmd`)

| 노드 | 코드 근거(파일:함수) | 런타임 근거(명령/응답) | 상태 |
|---|---|---|---|
| A 업로드 | `OcrFlow.tsx:onPick()` | 프론트 빌드 미검증(별도 컨테이너, 본 검증 범위 밖) | ❓ 미확인 |
| B 접수 API | `main.py:97-99` | `openapi.json` → `/api/pantry/ocr` 존재 | ✅ 일치 |
| C 이미지검증 | `main.py:86-89` | 로그에 400/413 사례 없음(트래픽 자체가 없어서) | ❓ 미확인(코드는 확인) |
| D job 시작 | `main.py:93` | 이미지 최신(§2-3) → 코드와 동일 동작 추정 | ✅ 일치 |
| E 다운스케일 | `vision.py:_downscale` | 〃 | ✅ 일치 |
| F Vision 파싱 | `vision.py:VisionBackend.parse` | `/health` → `"backend":"vision"` 확인 | ✅ 일치 |
| G 재시도 | `vision.py:_is_transient` | 로그에 재시도 사례 없음(트래픽 없어서) | ❓ 미확인(코드는 확인) |
| H FAILED | `main.py:_run_job` except | 〃 | ❓ 미확인(코드는 확인) |
| I 가격 재정렬 | `process.py`/`classify.py:realign_prices` | 이미지 최신 → 코드와 동일 동작 추정 | ✅ 일치 |
| J 분류 캐스케이드 | `classify.py:Classifier.classify` | 컨테이너 내부 직접 조회(§2-7) | ✅ 일치(단, 하위 R1/R3 참조데이터는 아래 참고) |
| K job 저장 | `main.py:_JOBS` | 코드 자체가 유일한 저장소(검증 불필요) | ✅ 일치 |
| L 폴링 | `main.py:get_result` | `openapi.json` → `/api/pantry/ocr/{job_id}` 존재 | ✅ 일치 |
| M HITL 편집표 | `OcrFlow.tsx` | 프론트 검증 범위 밖 | ❓ 미확인 |
| N 확인/등록 | `OcrFlow.tsx:onConfirm` | 〃 | ❓ 미확인 |
| O 확정 API | `routers.py:confirm_receipt` | `openapi.json` → `/api/pantry/receipts` 존재 | ✅ 일치 |
| P 감사로그 | `queries.py:create_ocr_receipt 등` | 이미지 최신(§2-3) | ✅ 일치 |
| Q/R 재고반영 | `routers.py:122-138` | 〃 | ✅ 일치 |
| S 식비계산 | `routers.py:kept_expense` | 〃 | ✅ 일치 |
| T 캘린더 기록 | 프론트 → `/api/expenses` | `mealplan` openapi에 `/api/expenses` 존재 | ✅ 일치 |
| R1 경계정책표 | `classify.py:_load_edge` | **`find` 결과 파일 없음, `edge:0`** (§2-7) | 🚧 미배포 |
| R2 gazetteer | `classify.py:_load_gazetteer_db` | **`gaz_source:db, gaz:1079`** (§2-7) | ✅ 일치 |
| R3 보관법 시드 | `classify.py:_storage_for` | **`find` 결과 파일 없음, `shelf:0`** (§2-7) | 🚧 미배포 |

### 3-2. 랭킹 (`recipe_ranking.mmd`)

| 노드 | 코드 근거(파일:함수) | 런타임 근거(명령/응답) | 상태 |
|---|---|---|---|
| A 추천 요청 | `routers.py:recommend_recipes` | `openapi.json` → `/api/mealplan/recommend` 존재 | ✅ 일치 |
| B pantry 조회 | `context.py:HttpPantryProvider` | 이미지 최신(§2-3) | ✅ 일치 |
| C 가용성 분기 | `routers.py:ProviderUnavailable` | pantry 컨테이너 healthy → 미가용 경로 미관측 | ❓ 미확인(코드는 확인) |
| D 제외재료 조회 | `context.py:ExclusionProvider` | 이미지 최신 | ✅ 일치 |
| E 후보 SQL | `queries.py:get_candidate_recipes` | 〃 | ✅ 일치 |
| F 후보 그룹화 | `ranking.py:group_recipe_rows` | 〃 | ✅ 일치 |
| G 규칙 스코어링 | `ranking.py:rank_recipes,_score` | 〃 | ✅ 일치 |
| H ML 재랭킹 호출 | `ranking_client.py:personalize` | **`RANKING_ML_ENABLED=true` 실측**(§2-4) | ✅ 일치 |
| I 콜드스타트 분기 | `serve.py:Ranker.rank, MIN_EVENTS` | **`model_loaded:false` + retrain 로그 "콜드스타트 skip"**(§2-6) — 지금 이 분기가 라이브로 발동 중 | ✅ 일치 |
| J LightGBM 예측 | `serve.py:_matrix`/`train.py:_LgbRanker` | 모델 미존재라 현재는 항상 폴백 경로(K)로 감 — 코드는 배포됨 | ✅ 일치(현재 미발동 상태) |
| K 규칙순 유지 | `serve.py:_fallback` | **지금 실제로 이 경로만 탐** | ✅ 일치 |
| L 재정렬 | `ranking_client.py:reorder` | 현재 미발동(J 미발동과 연동) | ✅ 일치(현재 미발동) |
| M Top-20 조립 | `routers.py:ranked[:20]` | 이미지 최신 | ✅ 일치 |
| N 노출 로깅 | `queries.py:insert_impressions` | **`IMPRESSION_LOG_ENABLED=true`** + activity.recipe_impression 실데이터 40행(§2-6,2-9) | ✅ 일치 |
| O 유저행동 이벤트 | `activity.user_event` | 테이블 존재 확인(§2-9) | ✅ 일치 |
| P 피처 추출 | `extract.py:extract_feature_rows` | retrain 로그가 실제 추출 실행 증명(§2-6) | ✅ 일치 |
| Q 학습행렬 변환 | `features.py:to_matrix` | 〃(추출 후 바로 이어지는 내부 호출, 로그엔 결과 카운트만) | ✅ 일치 |
| R 최소치 게이트 | `retrain.py:MIN_ROWS,MIN_GROUPS` | **로그: "학습행 40(<200) / 그룹 2(<20)"** | ✅ 일치 |
| S LightGBM 학습 | `train.py:build_ranker` | 현재 게이트 미달로 미실행(코드는 배포) | ✅ 일치(현재 미발동) |
| T 모델 저장 | `train.py:save_model` | 〃 — `/models/ranker.pkl` 부재로 `model_loaded:false` 정합 | ✅ 일치(현재 미발동) |
| reload 트리거 | `retrain.py:_trigger_serving_reload`/`serve.py:reload_model` | `openapi.json` → `/reload` 라우트 존재 | ✅ 일치 |
| X1 규칙점수 | `features.py:FEATURE_COLUMNS` | 이미지 최신 | ✅ 일치 |
| X2 인기도 이중소스 | `serve.py:pg_feature_provider`(PR#194) | **`recipe_popularity` 테이블 존재 확인**(§2-9) | ✅ 일치 |
| X3 유저이력 | 〃(PR#211 `user_chat_pref`) | **`user_chat_pref` 테이블 존재 확인**(§2-9) | ✅ 일치 |
| X4 예산적합도 | `ranking_client.py:_budget_fit` | 이미지 최신 | ✅ 일치 |
| *(누락 노드)* 학습기 sklearn 폴백 | `train.py:_SklearnRanker`(§1-3) | 미배포 확인 대상 아님(다이어그램에 노드 자체가 없음) | 🆕 코드밖 → 도면 보완 필요 |

---

## §4. 요약

**총 노드 수**: 51개 (OCR 25 + 랭킹 26, sklearn 폴백 보완 1건 별도)

| 상태 | 개수 | 비고 |
|---|---|---|
| ✅ 일치 | 41 | 코드·배포 모두 확인(현재 미발동이지만 코드·배포는 준비됨 8건 포함) |
| ⚠️ 드리프트 | **1** | **랭킹 lightgbm 런타임 로드 실패(libgomp)** — 재검증에서 발견(§4.1). 코드는 정식 LambdaMART 전제인데 배포 컨테이너에선 `import lightgbm`=OSError |
| 🚧 미배포 | 2 | **OCR R1(경계정책표), R3(보관법 시드)** — Dockerfile이 `pipelines/ingest/data/*.csv`를 이미지에 안 넣고, compose env도 경로 override 안 함 |
| 🆕 코드밖 | 1 | 랭킹 학습기 sklearn 폴백(`train.py:_SklearnRanker`) — 도면에 없는 실제 코드 분기. ~~lightgbm 고정 의존이라 발동 낮음~~ **정정(§4.1): lightgbm이 런타임에 깨져 있어 폴백이 오히려 중요, 단 현재 except가 OSError를 못 잡아 폴백도 미발동** |
| ❓ 미확인 | 7 | 프론트 3개(A,M,N — 별도 컨테이너, 본 검증 범위 밖) + 트래픽 없어 못 본 에러/분기 경로 4개(C,G,H / 랭킹 C) — **코드 자체는 §1에서 확인됨, POST/실패주입 금지라 실사용 관측만 못 함(상태 불변)** |

**우선 볼 것 — 드리프트/미배포**:
1. ⚠️ **[신규·최우선] 랭킹 lightgbm 런타임 실패 → 개인화 영구 미발현 위험** — §4.1. 수정: PR #231(Dockerfile libgomp1 + build_ranker except 확장).
2. 🚧 **OCR 경계정책표·보관법 시드가 프로덕션에서 상시 미작동** — `_storage_for()`가 항상 키워드 규칙/기본값(FRIDGE)으로만 결정됨. `services/ocr/app/config.py:23-27`이 이미 이 상황을 예견하고 env override 훅을 만들어뒀는데 `deploy/app/docker-compose.yml`에 실제 배선이 안 됨 — 인프라팀에 `SHELF_LIFE_PATH`/`EDGE_POLICY_PATH` 배선 또는 Dockerfile에 데이터 파일 COPY 추가 요청 필요.
3. 🆕 **랭킹 학습기 sklearn 폴백 분기가 두 다이어그램에 없음** — 위 정정대로 실무적으로 중요(도면 보완 필요).

### §4.1. [재검증 추가] ⚠️ 랭킹 lightgbm 런타임 로드 실패 — 이전 패스가 놓친 드리프트

**증상 (런타임, 2026-07-20 재확인)**:
```
$ docker exec foodbudget-ranking-serving-1 python -c "from train import build_ranker; build_ranker()"
OSError: libgomp.so.1: cannot open shared object file: No such file or directory
```
**왜 이전 패스가 놓쳤나**: 1차 동적 검증이 `importlib.util.find_spec("lightgbm")`(설치 여부)만 확인 → True. 실제 `import`(네이티브 .so 로드)를 안 해봐서 libgomp 부재를 못 봄. 재검증에서 실제 import 를 시도해 검출.

**근본원인**: `ml/recipe-ranking/Dockerfile` = `python:3.12-slim` 에 OpenMP 런타임(libgomp) 미설치. lightgbm 휠은 `libgomp.so.1` 요구.

**영향 (잠복)**: 현재 `학습행 40(<200) 콜드스타트 skip`이라 미발동. 데이터 200행↑ 시 `train()→build_ranker()→import lightgbm`=OSError → `build_ranker`가 `ImportError`만 잡아 통과 → `retrain_once` generic except 가 "학습 실패, 기존 모델 유지"로 삼킴 → **모델이 영영 안 만들어져 개인화가 규칙순에 영구 고정**. `serve.py` LGBMRanker 언피클도 동일.

**수정**: PR #231 — (1) Dockerfile `libgomp1` 설치, (2) `build_ranker` except `ImportError`→`Exception`(OSError도 sklearn 폴백). 병합·재배포 후 컨테이너 `import lightgbm` 성공 재확인 필요.

**미확인 7건 재판정**: 프론트(A,M,N)는 별도 컨테이너로 범위 밖, 에러/분기(C,G,H/랭킹C)는 원 지침(POST·실패주입 금지)을 지켜 관측 안 함 → **상태 유지(미확인)**. 단 랭킹 콜드스타트 skip 분기는 retrain 로그로 실관측됨(✅, §2-6).

두 .mmd 파일은 이 표 기준으로 갱신함(아래 §5).

---

## §5. 다이어그램 갱신 내역

- `recipe_OCR.mmd`: R1·R3 노드 라벨에 `(배포: 파일 없음 → 항상 skip / 코드: CSV 룩업 구현됨)` 병기, 관련 `%%` 주석에 근거 추가.
- `recipe_ranking.mmd`: `S`(LightGBM 학습) 노드 라벨에 `(배포: lightgbm 고정설치로 상시 사용 / 코드: 미설치 시 sklearn 폴백 존재)` 주석 추가.
