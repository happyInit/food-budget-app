# FACTS/01_repo_inventory.md — 레포 지도 (§3-5, 2026-08-07)

> 이 문서가 대체하거나 보완하는 기존 문서: 없음 (신규 — 팬아웃 전 필수 인벤토리)

## 1. 최상위 디렉터리별 파일 수 (`git ls-files`)

| 디렉터리 | 파일 수 | 성격 |
|---|---|---|
| services/ | 277 | 백엔드 12서비스: account·chat·mealplan·notify·ocr·operations·pantry·price·recipe·recipebook·video (+CONVENTIONS.md) |
| infra/ | 182 | Terraform(Proxmox) + Ansible(노드·K8s 플랫폼 롤) |
| docs/ | 121+ | 설계·실측기록(.md/.html) — 계획 문서는 docs/serverless-migration/ |
| frontend/ | 87 | React/Vite/PWA |
| pipelines/ | 78 | ingest(배치 40+스크립트)·stream |
| ml/ | 51 | ingredient-ner·recipe-ranking·video-recipe·chat-insights |
| crawler/ | 20 | 크롤러 |
| deploy/ | 15 | app(docker-compose)·k8s(README만 — 매니페스트 이관됨, §4) |
| 루트 | Jenkinsfile·Dockerfile·docker-compose*.yml·`geonu_accessKeys.csv`(⚠️ gitignored 평문 AWS 키) | |

## 2. 언어·프레임워크

1. 백엔드·ML·파이프라인 = **Python 단일**(로컬 인터프리터 3.14.4 — 서비스별 런타임 버전은 실사 대상), FastAPI(CONVENTIONS 기준), raw psycopg3.
2. 프론트 = React/Vite(TSX). IaC = Terraform+Ansible. CI = 루트 `Jenkinsfile`.

## 3. AI 키워드 → 파일 경로 (rg, docs 제외)

| 키워드 | 주요 경로 |
|---|---|
| gemini/genai | services/ocr/app/pipeline/backend/{genai_client,vision,factory}.py · services/chat/app/pipeline/generator/gemini.py · ml/video-recipe/{pipeline,extract,models}.py · services/video |
| bedrock/boto3 | services/chat/app/pipeline/generator/bedrock.py · pipelines/ingest/{summarize_reviews,score_review_sentiment,draft_shelf_life}.py · services/video/app/{main,config}.py |
| nova | services/chat/app/config.py · pipelines/ingest 3종(위) |
| vertex | services/ocr/{.env.example,app/config.py,app/config_canary.py,app/pipeline/backend/*} · services/video/app/main.py · ml/video-recipe |
| crf | services/chat/app/pipeline/span_extractor/{ner,rule_based}.py · ml/ingredient-ner/{train_crf,self_train,…}.py · pipelines/ingest/backfill_ner_raw_ingredients.py |
| lightgbm/ranker | ml/recipe-ranking/{serve,train,retrain,features}.py·Dockerfile·SERVING.md |
| z_score | pipelines/ingest/detect_price_anomaly.py · pipelines/stream/produce_price_anomaly.py · services/operations/app/anomaly_analyzer.py(⚠️ 인프라 이상탐지와 혼동 주의 — 소유 판정 필요) |
| pgsync | infra/ansible 롤 · pipelines/ingest/index_recipes_es.py (+ live: data ns `mp-pgsync` 0/1) |
| minio | infra/ansible k8s 롤(lgtm·minio) · frontend/src/lib/image.ts(⚠️ 프론트가 MinIO URL 직접? — F-20 관련) |

## 4. AI 10종 → 추정 진입점 (팬아웃 배정용 — 확정은 FACTS/02)

| # | 기능 | 추정 진입점 1~3개 | 담당 |
|---|---|---|---|
| 1 | 영수증 인식 | services/ocr/app/pipeline/backend/{genai_client,vision}.py · factory.py | A |
| 2 | 영상→레시피 | services/video/app/main.py · ml/video-recipe/pipeline.py | A |
| 3 | 챗봇 | services/chat/app/pipeline/generator/{bedrock,gemini}.py | B |
| 4 | 리뷰 요약 | pipelines/ingest/summarize_reviews.py · fill_summary_template.py | C |
| 5 | 냉장고 추천 | ml/recipe-ranking/serve.py (live: app/mp-ranking-serving) | B |
| 6 | 가격 급등·핫딜 | pipelines/ingest/detect_price_anomaly.py · pipelines/stream/produce_price_anomaly.py (live: pipeline/mp-price-anomaly-notifier·mp-deal-notifier) | C |
| 7 | 재료명 NER(CRF) | services/chat/app/pipeline/span_extractor/ner.py · ml/ingredient-ner/ | B(+A: ocr 체인 여부) |
| 8 | 리뷰 감정 분류 | pipelines/ingest/score_review_sentiment.py | C |
| 9 | 영수증 품목 분류 | services/ocr 내부 단계(확정 필요) | A |
| 10 | 구조화 추출 | 후보: pipelines/ingest/draft_shelf_life.py(Nova) / ocr·video 내부 | C(+A) |

## 5. 매니페스트 소재 판정 (§3-2-2)

1. **[불일치]** 사전 브리핑 "매니페스트는 deploy/k8s/" ↔ 실물: `deploy/k8s/`엔 README.md 1개뿐, [deploy/k8s/README.md:3-13] "정본 레포 `happyInit/mealplanning-config` PR #66로 이관(2026-07-31)". 커밋 c3cb195 동일 서술.
2. 따라서 실사 정본 = **살아 있는 클러스터(kubectl 가용 확인, 5노드 Ready)** + (접근되면) mealplanning-config 레포. 매니페스트-의존 판정 항목(ArgoCD 제외 대상·StorageClass·NetworkPolicy·ESO·KEDA·CronJob 스케줄)은 kubectl 실측으로 대체 가능 — `[미확인]` 아님.
3. 앱 코드만으로 판정 가능: F-01~F-16·F-19·F-20 대부분. 매니페스트/클러스터 필요: F-17(TZ)·F-18(환경 분리)·ESO 목록·스케줄.

## 6. 라이브 클러스터 1차 관찰 (kubectl, 2026-08-07 — 상세 실사는 agent-D)

1. 노드 5대 Ready(master·a1·a2·b1·b2) — 계획 문서 "물리 2대, master×1 SPOF" 서술과 대조 필요.
2. app ns 11 Deployment(mp-chat·mp-ocr·mp-video·mp-ranking-serving 등). **mp-account·mp-recipe 부재** — argo-rollouts ns(3d23h) 존재 → Rollout 전환 여부 확인 필요.
3. pipeline ns: mp-deal-notifier(0/0)·mp-recipe-refiner(0/0)·mp-retail-refiner(0/0 — KEDA scale-to-zero 추정)·mp-price-anomaly-notifier(1/1)·mp-user-event-sink(1/1).
4. data ns: **mp-pgsync 0/1(Available 0 — 라이브 장애 or 의도적?)**·mp-redis-pgsync·pg-pooler 2/2·ES 2 STS·mp-redis.
5. 문서 밖 신규(NEW- 후보): **mp-ingress ns(20h): mp-cloudflared-app(Cloudflare 터널)+mp-gw-public-istio** · cost ns(kubecost) · mp-users ns(5d22h) · argo-rollouts.
