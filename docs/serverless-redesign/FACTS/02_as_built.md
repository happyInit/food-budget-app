# FACTS/02_as_built.md — 현재 상태 실사 종합 (§3-2-3, 2026-08-07)

> 이 문서가 대체하거나 보완하는 기존 문서: 계획 문서·시방서의 "현행 인프라/기능 성격" 서술 전부를 **실물 기준으로 대체**한다. 이후 모든 설계·판정은 이 문서의 값을 쓴다.
> 근거 원장: `FACTS/agent-A.md`(ocr·video) · `agent-B.md`(chat·NER·랭킹) · `agent-C.md`(파이프라인·알림·재고) · `agent-D.md`(설정·클러스터·config 레포) + 메인 세션 kubectl 추가 확인(chat-config·app-common·mealplan-config·mp-pipeline-env, 2026-08-07).

## 0. [불일치] 총람 — 문서 ≠ 실물 (실물 채택, 좌측 번호로 이후 인용)

| # | 문서/브리핑 주장 | 실물 (근거) | 
|---|---|---|
| D-01 | K8s 매니페스트는 이 레포 `deploy/k8s/`에 있다 | README 1개뿐 — 정본은 `happyInit/mealplanning-config`(ArgoCD Application 45개, automated sync). [deploy/k8s/README.md:3-13, agent-D 카드 28-29] |
| D-02 | AI 인증 — 계획 "Vertex SA 키" vs 2026-07-28 기록 "개인 Gemini API 키" | **라이브 = Vertex**(ocr `GENAI_BACKEND=vertex`, video `VIDEO_GENAI_BACKEND=vertex` + `mp-gcp-sa` SA JSON 마운트, GCP 프로젝트 `mealplanning-503911`). 단 **코드 기본값 = api_key**(env 토글) — 7/28 기록은 당시 사실, 이후 Vertex 배선(현 브랜치명 feat/ai-vertex-k8s-wiring)으로 전환됨. [agent-A 5-1~5-4 · agent-D 21] |
| D-03 | 영수증 인식 = 비동기/이벤트 | HTTP `POST /api/pantry/ocr` 202+폴링, **인프로세스 asyncio 태스크** — 큐·이벤트버스 없음(TODO 주석 실재). [agent-A 1-1~1-3] |
| D-04 | 품목 분류 = Gemini 내부 처리 | Gemini는 `is_food` 불린만 — category/storage 분류는 **로컬 규칙+gazetteer 캐스케이드**, LLM 분류 티어는 훅만(미구현). [agent-A 9-1·9-2] |
| D-05 | 구조화 추출 = Nova 내부 처리 | 독립 실체 없음 — OCR·영상의 **단일 Gemini 호출에 JSON 스키마 강제로 내장**. Nova 구조화는 소비기한 초안 배치(`draft_shelf_life.py`)뿐. [agent-A 10-1·10-2 · agent-C 20] |
| D-06 | 재료명 NER(CRF) = "최대 난관 🔴 동기 저지연" | **동기 경로에 CRF 없음** — 챗 추출 기본 rule(gazetteer), 코드가 챗 사용 금지 명시, 배포 이미지에 모델·sklearn-crfsuite 부재. CRF 실사용 = **배치 백필 전용**. 별도 NER API 미구현. [agent-B F-01 행 전부] |
| D-07 | 챗봇 = Bedrock nova-micro 동기 저지연 | 라이브 `GENERATOR_BACKEND=template` — **프로덕션 챗봇은 현재 LLM을 호출하지 않는다.** nova-micro(`apac.amazon.nova-micro-v1:0`)·gemini는 refine용 env 선택지. 폴백은 항상 template. [메인 kubectl chat-config · agent-B factory.py 행] |
| D-08 | 리뷰 감정 분류 = 스트림 | **argparse 배치**(CronJob 07:00 KST) — Kafka 컨슈머 아님. 증분+`ON CONFLICT DO NOTHING` 멱등. [agent-C 7·9·10 · agent-D 12] |
| D-09 | "Kafka는 Phase 2 범위 밖" | 토픽 5종(RF=3)+컨슈머 그룹 5종+DLQ+KEDA ScaledObject 4종이 **실가동** — 가격 알림·클릭스트림·수집이 전부 Kafka 경유. [agent-C 21-27 · agent-D 14·34] |
| D-10 | "P2 전 자동 CD 없음(수동 반영)" | Jenkins main 빌드 → config 레포 `kustomize edit set image :<sha>` 자동 커밋/푸시 → ArgoCD auto-sync — **자동 CD 체인 가동 중**. [Jenkinsfile:214-285, agent-D 30] |
| D-11 | 영수증 원본 = MinIO/S3 업로드 (S3 이벤트 트리거 전제) | **원본은 어디에도 저장 안 됨** — 프론트 multipart → OCR 서비스 메모리 처리, 오브젝트 스토리지 참조 0건. S3/MinIO 이벤트 트리거 전제는 실물에 대응물 없음. [agent-A 1-5·20-1~20-3] |
| D-12 | 시방서 xlsx: ns=`mp-ai-ns`/`mp-data-ns` · OCR=Bedrock Claude vision · chat HPA 2–6 · ES 8.15.3 | 실물 ns=`app`/`data`/`pipeline` · OCR=vertex(Gemini) · chat replicas 1·HPA 없음(HPA는 account·recipe Rollout 2–4뿐) · ES 8.19.19. [agent-D 42-45] |
| D-13 | PGSync 상시 연결 프로세스 | **현재 크래시루프(0/1)** — 복제 슬롯 `foodbudget_recipes_live` invalidated(max reserved size 초과). 슬롯명이 fb 시절 명명. [agent-D 36] |
| D-14 | 5노드는 P4 예정 | **이미 5노드 가동**(master + a1·a2·b1·b2). control-plane 1개 SPOF는 유지. [agent-D 48] |
| D-15 | KEDA scale-to-zero 컨슈머 3종 | **4종**(deal-notifier·recipe-refiner·retail-refiner·user-event-sink). price-anomaly-notifier는 KEDA 밖 상시 1. [agent-D 14-15] |
| D-16 | 백엔드 AWS 자격증명 = IRSA/IAM 역할 지향 | 온프렘 실물 = **정적 AWS 키**(ESO `mp-pipeline-secrets`의 AWS_ACCESS_KEY_ID/SECRET). 루트에 gitignored `geonu_accessKeys.csv`(평문 키 1쌍) 존재. [agent-D 20·22·23] |
| D-17 | 배치=KST(맞음)에서 유추되는 "런타임도 KST" | CronJob 22개 전부 `timeZone: Asia/Seoul` **확인** — 그러나 **컨테이너 프로세스 TZ = UTC**(Dockerfile·env TZ 설정 0건). 날짜 로직은 KST 명시(가격탐지)·프로세스 로컬(pantry)·DB 세션 의존이 **혼재**. [agent-D 9-11 · agent-C 35] |
| D-18 | 냉장고 추천(LightGBM) = 동기 가동 | 배선은 동기 HTTP 0.3s(mealplan→ranking-serving)이고 서빙 Deployment 라이브 가동 중이나, **`RANKING_ML_ENABLED=false`** — 호출 안 됨(규칙순 폴백이 실사용). [메인 kubectl mealplan-config · agent-B F-02 행] |
| D-19 | 계획 "리뷰 요약=sonnet-3.5" 표기 | 실물 모델 ID = `apac.anthropic.claude-3-5-sonnet-20241022-v2:0`, 감정/소비기한 = `apac.amazon.nova-micro-v1:0` — **둘 다 `apac.` 크로스리전 추론 프로파일 ID**(B-03 판정 입력). [agent-C 2·8·20] |

## 1. 실사 표 — 12개 확인 대상

| 확인 대상 | 태그 | 실물 요약 (근거) |
|---|---|---|
| AI 10종 진입점 | [확인됨] | §2 표 참조 — 10종 전부 프로덕션 진입점 `파일:라인` 확보 (미구현 판정 0, 단 #9·#10은 독립 실체 아님) |
| 외부 LLM 인증 방식 | [확인됨·불일치 D-02] | 라이브=Vertex SA(파일 마운트·ADC), 코드 기본=api_key 토글, chat엔 GEMINI_API_KEY 주입되나 template 모드라 미사용. Bedrock=정적 IAM 키(ESO) |
| 호출 모델 식별자 | [확인됨] | Gemini: `gemini-3.5-flash-lite`(ocr·video·chat 기본), `gemini-3.5-flash`(video 상위 재분석). Bedrock: `apac.anthropic.claude-3-5-sonnet-20241022-v2:0`(요약)·`apac.amazon.nova-micro-v1:0`(감정·소비기한·챗 옵션). 리전: `ap-northeast-2` 하드코딩(파이프라인)·`GCP_LOCATION` env 전용(기본값 의도적 부재) |
| 자체 모델 3종 | [확인됨] | CRF `crf_ingredient.pkl` 343,657B·git 미추적·배치 전용 / LightGBM `ranker.pkl` named volume(레포·이미지에 없음, retrain이 생성·`/reload` 핫스왑) / z-score 모델 파일 없음(매 실행 PG 30일 윈도우 재계산). 로딩: CRF=기동 1회(ner 백엔드 시만)·ranker=import 전역 1회 |
| 런타임·프레임워크 | [확인됨] | 전부 `python:3.12-slim`+FastAPI+uvicorn(프론트 node22/nginx). `==` 완전핀은 1건뿐, ocr·account는 무핀 다수, lock 파일 부재 — 재현 빌드 보장 없음(F-09) |
| 배치 작업 | [확인됨] | CronJob 22개 전부 KST·Forbid·backoffLimit 0·activeDeadline 없음. AI 배치: 감정 07:00 매일→요약 08:00 일/수, 가격탐지 04:40, 크롤 03:30/04:10/13:10, 딜 15:05/17:05, chat-insights 06:00, OCR 카나리 월 05:15 |
| 큐·이벤트 | [확인됨] | Kafka(Strimzi) 토픽 5종 RF=3 + `.dlq`. confluent-kafka, 프로듀서 idempotence+acks=all, 컨슈머 수동 커밋(PG 커밋 후 오프셋)·cooperative-sticky. KEDA 4종 0-스케일(lag 10). 클릭스트림 발행 헬퍼는 services 실호출 0건(발행 주체 미배선) |
| 데이터 계층 접속 | [확인됨] | 앱: `pg-pooler.data.svc`(CNPG transaction pooler)+`prepare_threshold=None`+AsyncPool / **파이프라인: `pg-rw.data.svc` 직결(pooler 미경유)**·sync 단일 커넥션. Redis: Sentinel-aware(센티널 3·quorum 2). ES: `recipes`(수동 전량)+`recipes_pgsync`(CDC) 이중 인덱스 |
| 스토리지 | [확인됨] | 영수증 원본 미저장(D-11). 모델: CRF=로컬(미추적)·ranker=PVC. MinIO는 앱 경로에 없음(LGTM·PG 온사이트 덤프용). user_recipe 이미지=data URI로 PG text 컬럼 |
| 시크릿 | [확인됨] | ESO 31개(ClusterSecretStore `fb-kubernetes`→fb-secrets ns). 소스 하드코딩 키 0건(grep AKIA/AIza). 루트 `geonu_accessKeys.csv`(gitignored 평문 AWS 키) 존재 — 클러스터 키와 동일 개체 여부 [미확인] |
| 매니페스트 소재 | [확인됨·불일치 D-01] | mealplanning-config 정본, ArgoCD 45 App, 이미지 전부 Harbor `:40-hex sha` 핀·:latest 0건. eks overlays(ECR PLACEHOLDER) 초안 상주 |
| 관측 | [확인됨] | app ns Istio native sidecar 주입(pipeline ns 미주입). ServiceMonitor 22. 로깅: ocr·chat·stream=구조화 JSON(+chat OTel trace) / video=비구조화 / **ingest 배치=print뿐·메트릭 0**(LLM 배치 관측 stdout 의존) |

## 2. AI 10종 as-built 판정표

| # | 기능 | 프로덕션 진입점 | 실물 성격 | 실물 모델 | 판정 |
|---|---|---|---|---|---|
| 1 | 영수증 인식 | `POST /api/pantry/ocr` [services/ocr/app/main.py:123-125] | 202+1s 폴링, 인프로세스 asyncio, 원본 미저장, Gemini 1회+로컬 캐스케이드 | gemini-3.5-flash-lite (vertex) | 확인됨 (D-03·D-11) |
| 2 | 영상→레시피 | `POST /api/recipes/extract` [services/video/app/main.py:173-197] | 202+2s 폴링, BackgroundTasks, 전체 120s 상한, Redis 30일 교차유저 캐시·단일비행 락, 하드실패 시 상위모델 1회 | flash-lite→flash (vertex) | 확인됨 |
| 3 | 챗봇 | `POST /chat` [services/chat/app/main.py:569-577] | 동기 단발 JSON(스트리밍 없음), 멀티턴 ON(Redis 8턴·TTL 3600s), **생성=template(LLM 미호출)**, 가드=순수 Python | (옵션: nova-micro·flash-lite) | 확인됨 (D-07) |
| 4 | 리뷰 요약 | CronJob `mp-summarize-reviews` 08:00 일/수 [pipelines/ingest/summarize_reviews.py:223-234] | 배치·증분(NULL/template만)·UPDATE 승격·건별 skip 재포착 | apac.anthropic.claude-3-5-sonnet-20241022-v2:0 | 확인됨 |
| 5 | 냉장고 추천 | `POST /rank/personalize` [ml/recipe-ranking/serve.py:174-176] ← mealplan 0.3s | 동기 HTTP 배선·서빙 가동 중이나 **flag OFF(미호출)**. 챗 냉장고 추천은 별개(pantry 주입+ES) | LightGBM ranker.pkl | 확인됨 (D-18) |
| 6 | 가격 급등·핫딜 | CronJob 04:40 [pipelines/ingest/detect_price_anomaly.py] → Kafka → 상시 컨슈머 [pipelines/stream/consume_price_anomaly.py] | 탐지=무상태 재계산 / 발행·억제=PG 상태 3종(baseline·anomaly·7일 쿨다운+PK). 핫딜=별도 KEDA 컨슈머(알림 fan-out 없음, API 조회면) | z-score(통계) | 확인됨 |
| 7 | 재료명 NER | 배치 `pipelines/ingest/backfill_ner_raw_ingredients.py:1-25` (동기 API 미구현) | **배치 백필 전용** — 챗 동기 경로=rule(gazetteer), 배포 이미지에 모델 부재 | CRF 343KB pickle | 확인됨 (D-06) |
| 8 | 리뷰 감정 분류 | CronJob `mp-score-review-sentiment` 07:00 [pipelines/ingest/score_review_sentiment.py:39] | 배치·증분·20건/호출·ON CONFLICT 멱등·배치별 커밋 | apac.amazon.nova-micro-v1:0 | 확인됨 (D-08) |
| 9 | 영수증 품목 분류 | #1 내부 [services/ocr/app/pipeline/classify.py:273-309] | 독립 호출 아님 — Gemini `is_food`+로컬 규칙 캐스케이드, LLM 티어 미구현 | (LLM 없음) | 확인됨 (D-04) |
| 10 | 구조화 추출 | (a) #1·#2 내장 (b) CronJob 없음·수동 `draft_shelf_life.py:37-57` | (a) 단일 Gemini 호출 JSON 스키마 강제 (b) 소비기한 초안 nova-micro·AI_DRAFT·dry-run 기본 | (a) gemini (b) nova-micro | 확인됨 (D-05) |

**미구현 목록(프로덕션 경로 없음):** 별도 NER 동기 API · OCR LLM 분류 티어(훅만) · video refine 단계 · OCR 내 합계 정합 검증 · notify 푸시 발송(FCM/웹푸시 0건 — 인앱 알림함만) · 클릭스트림 발행의 백엔드 배선(`produce_user_event` 실호출 0건).

## 3. NEW- 문서 밖 신규 구성요소 (agent-D + 메인 관찰)

NEW-01 mp-ingress ns(20h): Cloudflare Tunnel(`app.mealbong.cloud`→mp-gw-public `.14`) — 공개 유입 재편. **H축(하이브리드 경로) 설계 입력** · NEW-02 Argo Rollouts: account·recipe 카나리+AnalysisTemplate+HPA 2–4 · NEW-03 mp-ranking-serving 라이브(model PVC) · NEW-04 eks overlays(ECR PLACEHOLDER) 초안 · NEW-05 kubecost+IBM finops agent(cost ns) · NEW-06 mp-users ns=팀원 5인 SA(신원 전용) · NEW-07 OCR 설정 카나리 CronJob(월 05:15) · NEW-08 PG 온사이트 덤프 CronJob(04:00, MinIO)+barman scheduledbackup · NEW-09 kube-system CronJob 3종(descheduler·bitrot-canary) · NEW-10 price.anomaly.detected 토픽+상시 컨슈머 · NEW-11 video Vertex 전환(mp-gcp-sa, 프로젝트 mealplanning-503911) · NEW-12 자체 재패키징 ES 이미지(mp-elasticsearch-nori 8.19.19).

## 4. 잔여 [미확인] (확정 방법 포함)

| 항목 | 확정 방법 |
|---|---|
| DB 세션 timezone 실값(pantry `current_date`·`date_trunc` 의존) | `kubectl get cluster pg -n data -o yaml \| grep -i timezone` 또는 운영자 `psql -c 'show timezone'` |
| geonu_accessKeys.csv ↔ 클러스터 pipeline-secrets AWS 키 동일성 | AWS IAM 콘솔 → 사용자 → Access key ID 대조(값 비교 아님, 키 ID만) |
| 리뷰 요약·감정 테이블 DDL(UNIQUE·덮어쓰기 구조) — 코드층은 확인됨(UPDATE만/ON CONFLICT) | `docs/prd/schema-public-data.sql`에서 `recipe_review_summary`·`recipe_review_sentiment` grep |
| "챗 456ms"·"가드 20/20"·"12/13"의 원 측정 조건 | `docs/serverless-migration/AI실측기록_html/` 7종 + `docs/ai-model-selection-final.md` 대조 — **B단계 과업**(§3-2-1 용법 1) |
| 클릭스트림 실발행 주체(백엔드 미배선인데 user-event-sink 가동) | `kubectl exec` 금지 유지 — Kafka lag: `kubectl get scaledobject mp-user-event-sink -n pipeline -o yaml` + 프론트/크롤러에서 `events.user.activity` grep |

## 5. F-01~F-20 1차 스냅샷 (정식 판정 대장은 B단계 `01_사실검증_및_가정대장.md`)

F-01 반증(CRF=배치 전용) · F-02 확인(동기 배선·flag OFF) · F-03 반증(감정=배치) · F-04 확인(멀티턴 ON·Redis TTL 3600) · F-05 부분(코드 실측 주석 p50 410/p95 554ms — 456ms 측정 지점은 실측기록 대조 필요) · F-06 확인(단발 JSON) · F-07 반증(중복 억제=PG 2중, Redis 아님; 단 video 캐시·챗 세션·비용 카운터는 Redis) · F-08 확인(343KB·PVC·로딩 시점 확정) · F-09 확인(사실상 무핀 — lock 부재) · F-10 확인(명시 버전 핀 + `apac.` 프로파일 ID) · F-11 부분(app ns sidecar 확인 — 의존 강제 여부는 B단계) · F-12 확인(탐지 무상태·발행 상태 PG) · F-13 확인(전 품목 저장+needs_review·합계 검증 미구현) · F-14 부분(CRF 데이터 git 미추적 로컬 — 백업 소재 [미확인]) · F-15 확인(순수 Python 가드) · F-16 확인(전수 목록 §1) · F-17 부분(CronJob KST·프로세스 UTC 혼재·DB TZ 미확인) · F-18 확인(dev/staging 없음 — 단일 프로덕션) · F-19 확인(프롬프트=코드 하드코딩) · F-20 확인(원본 미저장 — S3 이벤트 전제 무효).
