# FACTS — Agent B (chat · ingredient-ner · recipe-ranking · chat-insights · recipe/mealplan 연동)

읽기 전용 as-built 실사. 근거는 전부 `파일:라인`(레포 루트 상대). 실행 명령 = `ls -la`, `grep` 읽기 전용만.

| 주장 | 판정 | 근거 파일:라인 | 확인불가 시 확정 방법 | 뒤집는 기존 주장 |
|---|---|---|---|---|
| **F-01** 챗 동기 경로의 재료추출 기본 = rule(gazetteer n-gram), CRF 아님 | 확인됨 | `services/chat/app/config.py:40` (`extractor_backend: str = "rule"`), `deploy/app/docker-compose.yml:174`, `deploy/app/.env.example:24` | — | "NER=최대 난관 🔴 동기 저지연" — 동기 챗 경로에 CRF 없음 |
| F-01 CrfSpanExtractor는 in-process 옵션으로 존재하나 코드가 "채팅에 쓰지 말 것" 명시 | 확인됨 | `services/chat/app/pipeline/span_extractor/ner.py:7-11` ("현재 모델을 채팅 EXTRACTOR_BACKEND로 쓰지 말 것(=rule 유지)…대화 문장에 넣으면 조사·동사째 과다추출") | — | 동상 |
| F-01 별도 동기 NER API(마이크로서비스) | 미구현 | `ner.py:15` — "B안(/ner 마이크로서비스) 전환 시"라는 언급만, 라우트·서비스 없음. `services/` 밑에 ner 서비스 디렉토리 없음 | — | "NER 동기 저지연 API" |
| F-01 CRF 실사용 = 배치 백필(RAW 재료덩어리→구조화, dry-run 기본·`--apply`) | 확인됨 | `pipelines/ingest/backfill_ner_raw_ingredients.py:1-25` (특히 12-16: "이 배치가 CRF의 정당한 용도") | — | "NER=동기" |
| F-01 services/recipe 는 `ner_status` 컬럼 읽기·필터만(CRF 호출 없음) | 확인됨 | `services/recipe/app/queries.py:149-163` (RAW 빈이름 행 조회 제외), `:241` (`ner_status=ner` 응답 필드) | — | — |
| F-01 배포된 chat 컨테이너에서 EXTRACTOR_BACKEND=ner 는 사실상 불가(모델 미동봉+의존성 부재) | 확인됨 | `services/chat/Dockerfile:14-17` (ml/ COPY 없음), `services/chat/requirements.txt:1-23` (sklearn-crfsuite 없음 — unpickle 불가), `ml/ingredient-ner/.gitignore:3` (`data/*` 미커밋) | — | — |
| **F-02** 랭킹 = 동기 HTTP 서빙(FastAPI `POST /rank/personalize`), 사전계산 아님 | 확인됨 | `ml/recipe-ranking/serve.py:174-176` | — | — |
| F-02 호출자 = **mealplan**(frontend·recipe 아님), httpx 동기 호출 | 확인됨 | `services/mealplan/app/ranking_client.py:25-28`, `services/mealplan/app/routers.py:194-196` | — | — |
| F-02 mealplan 측 타임아웃 0.3s·실패/`personalized=false` → 규칙순 폴백 | 확인됨 | `services/mealplan/app/config.py:46-48` (`ranking_serving_timeout_s: float = 0.3`), `ranking_client.py:30-34` | — | — |
| F-02 콜드스타트: 유저 이벤트 < 20 → 비개인화(규칙순) | 확인됨 | `serve.py:18` (`RANKING_MIN_EVENTS` 기본 20), `:61-62` | — | — |
| F-02 랭킹 결과 캐시 없음(요청마다 PG 피처조회+추론) | 확인됨 | `serve.py:94-142` (pg_feature_provider, 캐시 코드 부재), `ranking_client.py` 전문(캐시 없음) | — | — |
| F-02 as-built 기본 상태 = **비활성**: compose `profiles:["ranking"]`(기본 배포 제외) + mealplan `RANKING_ML_ENABLED` 기본 false | 확인됨 | `deploy/app/docker-compose.yml:289-293`, `deploy/app/.env.example:88`, `services/mealplan/app/config.py:46` | — | "냉장고 추천=동기" — 배선은 동기지만 기본 OFF(규칙순) |
| F-02 챗의 "냉장고 추천"은 별개 경로: pantry API 재고 주입→ES 레시피 검색(LightGBM 무관) | 확인됨 | `services/chat/app/main.py:409-421`, `config.py:104-105`; compose 기본 `CHAT_PANTRY_ENABLED=true`(`docker-compose.yml:194`) | — | "냉장고 추천(LightGBM)"과 챗 냉장고 추천은 다른 시스템 |
| **F-04** 멀티턴 구현됨, opt-in(코드·compose 기본 OFF) | 확인됨 | `config.py:87` (`multiturn_enabled: bool = False`), `docker-compose.yml:188`, `.env.example:34` | — | — |
| F-04 대화 상태 = **Redis**: `chat:sess:{id}` 리스트(최근 8턴 LTRIM·TTL 3600s) + `:recipes`/`:dislikes`/`:shown`/`:focus` 키 | 확인됨 | `services/chat/app/pipeline/session.py:14-15,55-58`, `config.py:88-89`; 장애 시 무맥락 degrade `session.py:5` | — | "무상태" 계열 주장 |
| F-04 영속 대화 로그 = PG `chat.chat_message`(flag `CHAT_PERSIST_ENABLED`+인증 유저만, best-effort) | 확인됨 | `services/chat/app/pipeline/chat_log.py:14-33`, `docker-compose.yml:191` (기본 false) | — | — |
| F-04 파이프라인 = ①extract(스팬+gazetteer+키워드 intent) ②병렬검색(ES+PG, asyncio.gather) ③context 조립 ④생성(template 바닥→refine) ⑤응답 조립 | 확인됨 | `main.py:1,295-296,423-424,445-446,483-492`, `search.py:1,217` | — | — |
| F-04 intent = 키워드 규칙 1차, ML 보강은 flag 기본 OFF(모델파일 필요) | 확인됨 | `extract.py:28-38,68-83`, `config.py:42-43` (`intent_ml_enabled: bool = False`), `intent_ml.py:61-69` | — | — |
| **F-06** 응답 = 단발 JSON(`POST /chat`→`ChatResponse`) — SSE/WebSocket/StreamingResponse 0건 | 확인됨 | `main.py:569-577`, `models.py:38-44`; `grep -rn "StreamingResponse\|text/event-stream\|websocket" services/chat/app` = 0건 | — | — |
| F-06 프론트 계약 = 단일 POST(`postJson`), 스트리밍 소비 없음 | 확인됨 | `frontend/src/lib/api.ts:234` (`postJson<ChatResponseT>('/api/mealplan/assistant/chat', …)`) | — | — |
| **F-05** 하위 저장소 상한: ES 3.0s·PG statement_timeout 8000ms | 확인됨 | `config.py:22-23`, `db.py:17,36-38` | — | — |
| F-05 LLM 상한: gemini 3.0s / bedrock SDK 3.0s·앱 상한 ×1.5=4.5s / bedrock 재시도 max 3(adaptive) | 확인됨 | `config.py:57,71-72`, `bedrock.py:32-49` (`Config(retries={"max_attempts":…, "mode":"adaptive"}, connect_timeout, read_timeout)`) | — | — |
| F-05 내부 서비스 호출(account·pantry) httpx 2.0s, 실패=무동작 폴백 | 확인됨 | `account_client.py:27,49,62`, `pantry_client.py:40` | — | — |
| F-05 LLM 타임아웃·오류·근거대조 실패 = 전부 template fallback(요청 실패 없음) | 확인됨 | `refine_base.py:63-68,77-78` | — | — |
| F-05 "챗 456ms" 수치 | 확인불가(코드에 없음) | 코드 내 실측 주석은 bedrock p50 ~410ms·p95 ~554ms(`config.py:64,71`, `bedrock.py:8`) | `grep -rn "456" docs/ services/chat/validation/` (validation/runs.json 포함) | "챗 456ms" — 코드 근거는 410/554ms만 |
| **F-15** 입력 가드 = 순수 Python(길이 200 + 인젝션 denylist 문자열 매칭), LLM 경유 아님 | 확인됨 | `guardrails.py:14-20,37-43`, `config.py:74` (`max_message_len: int = 200`) | — | — |
| F-15 출력 가드 = Python 근거대조(출력 숫자⊆근거 숫자 + 재료 item_id ⊆ 근거) → 실패 시 template 폴백 | 확인됨 | `guardrails.py:82-111`, `refine_base.py:76-78` | — | — |
| F-15 비용 가드 = 일일 cap(Redis INCR 200/일·fail-open) + 월예산 cap(호출수×0.06원 ≥ 7,200원→강등), 기본 둘 다 OFF | 확인됨 | `guardrails.py:114-158`, `config.py:75-84`, `main.py:469-481` | — | — |
| F-15 "가드 20/20 유지" 수치 | 확인불가(코드 주석 인용만) | `bedrock.py:7-8`·`config.py:63-64` "프로덕션 refine 경로 20/20으로 Gemini와 동률" — 산출 근거 파일은 docs | `grep -rn "20/20" docs/ai-model-selection-final.md docs/ai-chat-mass-measurement.md` | — |
| **F-08** CRF 모델 = `ml/ingredient-ner/data/model/crf_ingredient.pkl` **343,657B** pickle(`sklearn_crfsuite.CRF`), 기동 시 1회 로드(ner 백엔드일 때만) | 확인됨(`ls -la` 실행) | `ner.py:78-81,93-94` (기본경로·`pickle.load`), git 미추적(`ml/ingredient-ner/.gitignore:3`) — 로컬 파일, MinIO/이미지 동봉 아님 | — | — |
| F-08 gazetteer = 파일 아님 — **PG item_master에서 기동 시 동기 로드**(+`app/data/aliases.json` 1,810B) | 확인됨 | `main.py:51-64` (`_load_matcher`, psycopg 동기 connect), `config.py:44` | — | — |
| F-08 ranker = `/models/ranker.pkl`(compose named volume `ranking-model`, retrain이 저장·serve가 로드) — 레포·이미지에 파일 없음, import 시 전역 1회 로드 + `/reload` 핫스왑 | 확인됨 | `serve.py:156-171,179-195`, `docker-compose.yml:299-302,321,326-327`, `ml/recipe-ranking/Dockerfile:19-22`, `.gitignore`(`*.pkl`); `ls ml/recipe-ranking/data/` = 없음 | — | — |
| **F-09** chat: `python:3.12-slim`, fastapi/psycopg/redis/ES 범위핀, **numpy·scipy·sklearn-crfsuite·lightgbm 없음** | 확인됨 | `services/chat/Dockerfile:4`, `requirements.txt:2-12` 원문: `fastapi>=0.115,<1`·`psycopg[binary]>=3.2,<4`·`redis>=5.0,<6`·`google-genai>=1.0,<2`·`boto3>=1.35,<2` | — | — |
| F-09 ranking: `numpy>=1.26`·`scikit-learn>=1.3`·`lightgbm>=4.0`(하한만, 상한핀 없음), `python:3.12-slim`+libgomp1 | 확인됨 | `ml/recipe-ranking/requirements.txt:2-8`, `Dockerfile:4,13` | — | — |
| F-09 ingredient-ner: `sklearn-crfsuite>=0.5,<1`·`psycopg[binary]>=3.2,<4` (numpy 직접핀 없음) | 확인됨 | `ml/ingredient-ner/requirements.txt:2-4` | — | — |
| 모델 식별자 전수(chat 범위): gemini=`gemini-3.5-flash-lite`(버전핀, `-latest` 금지 주석) · bedrock=`apac.amazon.nova-micro-v1:0`(cross-region profile ID)·리전 `ap-northeast-2` · build_alias도 `gemini-3.5-flash-lite` | 확인됨 | `config.py:50-52,67-68`, `tools/build_alias.py:88`, `docker-compose.yml:178` | — | — |
| `tools/build_alias.py` 정체 = 오프라인 1회 alias 후보 채굴 CLI(item_master 스냅샷→`alias_review.tsv`, 사람이 검토→aliases.json). 런타임 호출 없음 | 확인됨 | `build_alias.py:1-19` ("오프라인 1회성. 런타임(챗봇) 호출 없음") | — | — |
| generator 가 bedrock/gemini 둘인 이유 = **선택 설정**(`GENERATOR_BACKEND=template\|gemini\|bedrock`), 상호 폴백 아님(폴백 대상은 항상 template). **프로덕션 기본 = template**(compose·.env.example), 로컬 dev `.env`만 gemini | 확인됨 | `factory.py:11-27`, `docker-compose.yml:173`, `deploy/app/.env.example:23`, `services/chat/.env:31`(`GENERATOR_BACKEND=gemini`, 로컬) | — | "챗봇=동기 저지연 nova-micro" — nova-micro는 3옵션 중 하나·기본 아님(AWS 이전 후 대비, `config.py:39`) |
| ml/chat-insights 정체 = **배치 분석 스크립트**(run.py 1회/`--loop`), 이 레포 배포 배선 없음(compose에 서비스 미존재·deploy/k8s는 README만). prep-ahead: 데이터 없으면 전부 skip | 확인됨(레포 내 프로덕션 상주 경로 아님) | `ml/chat-insights/run.py:1-14,39-47`, `README.md:23-35`; `grep insight deploy/app/docker-compose.yml` = 0건 | K8s CronJob 존재 여부는 config 레포에서 `grep -rn "chat-insights" <mealplanning-config>/` | — |
| Redis·Kafka·PG 용도(chat·ranking): Redis=멀티턴 세션·비선호·shown·focus·refine 캐시(30일)·rate/월비용 카운터 / PG=gazetteer·가격·영양 검색·recipe_cost·chat_message·(ranking)activity 피처 / ES=레시피 검색 / **Kafka 사용 0건** | 확인됨 | `session.py` 전문, `refine_base.py:83-101`, `guardrails.py:122,133`, `main.py:58-59,378,460`, `serve.py:94-142`; `grep -rni kafka services/chat/app ml/recipe-ranking/*.py` = 0건 | — | — |
| 챗 로깅 = 구조화 JSON 1줄(allowlist 필드만 + OTel trace_id/span_id 자동 첨부), uvicorn access log off + OTel 스팬(chat.request/extract/search/generate) + Prometheus | 확인됨 | `observability.py:62-108`, `main.py:42-46,155-171,249,295,423,483` | — | — |

## As-built 요약

- [확인됨] **챗봇 = 동기 단발 JSON**(POST→ChatResponse, 스트리밍 없음). 생성 기본값은 **template(무료)** 이고 gemini/bedrock(nova-micro)은 env 선택 백엔드 — LLM은 recommend 응답의 "다듬기(refine)"에만 쓰이고 타임아웃(3~4.5s)·근거대조 실패 시 template 폴백. → "챗봇=동기 저지연 nova-micro"는 [불일치](nova-micro는 기본 아님).
- [불일치] **NER(CRF)은 챗 동기 경로에 없다** — 챗은 rule(gazetteer) 추출이 기본이고 코드가 CRF의 챗 사용을 명시 금지, CRF의 실사용은 배치 백필(`backfill_ner_raw_ingredients.py`) 뿐이며 배포 이미지에는 모델·의존성 자체가 없다. "냉장고 추천"도 이중 구조: 챗의 pantry 주입(동기, ES)은 ON 기본, LightGBM 재랭킹(mealplan→ranking-serving 동기 HTTP 0.3s)은 **compose 프로필 제외+flag OFF가 기본**.
- [미확인] "챗 456ms"·"가드 20/20"은 코드에서 산출 불가(코드 주석의 실측은 bedrock p50 ~410ms·p95 ~554ms, 20/20은 docs 인용) — `docs/ai-model-selection-final.md`·`validation/runs.json` 대조 필요. chat-insights의 K8s CronJob 배선 여부는 config 레포 확인 필요.
