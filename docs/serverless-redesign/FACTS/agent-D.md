# Agent D — as-built 실사 (설정축·데이터계약축·라이브 클러스터)

실사일: 2026-08-07 · 대상: food-budget-app 레포(설정·계약 파일) + 라이브 K8s 클러스터(읽기 전용) + happyInit/mealplanning-config(GET)

## ① 사실카드

| 주장 | 판정 | 근거(파일:라인 또는 명령→출력요약) | 확인불가 시 확정 방법 | 뒤집는 기존 주장 |
|---|---|---|---|---|
| F-17a: 서비스 Dockerfile 에 TZ/LANG/tzdata 설정 존재 | 미구현 | 전 Dockerfile(services/* 11종·루트·crawler/kurly·ml/recipe-ranking·deploy/pgsync·frontend) grep → TZ/LANG/locale/tzdata 매치 0. 전부 `FROM python:3.12-slim`(frontend=node22/nginx, kurly=playwright jammy) | — | 컨테이너 KST 라는 인상 — 실제 프로세스 TZ 는 UTC |
| F-17b: 클러스터 워크로드에 TZ env 주입 | 미구현 | `kubectl get deploy -n app -o jsonpath(env)` → TZ 없음(OTEL_SERVICE_NAME·PGHOST 등만). rollout mp-account/mp-recipe 동일 | — | — |
| F-17c: CronJob 은 spec.timeZone=Asia/Seoul | 확인됨 | `kubectl get cronjob -A -o wide` → 전 22개(TIMEZONE 열) Asia/Seoul. config repo pipelines/pollers.yaml:12 `timeZone: Asia/Seoul` | — | — |
| 배치 실물 스케줄: pipeline 17 + app 1 + data 1 + kube-system 3 = CronJob 22개, 전부 최근 실행 정상 | 확인됨 | `kubectl get cronjob -A -o wide` → kurly 03:30·oasis 04:10/13:10·딜 15:05/17:05·price-anomaly 04:40·matview 매시 20분·recipe 05:00 일/수·review 06:00→sentiment 07:00→summarize 08:00 일/수·chat-insights 06:00·deal-pruner 10분·user-data-pruner 04:30·invariants 월 06:00·pantry-expire 일 05:30. LAST SCHEDULE 전부 주기 내 | — | — |
| 배치 정책: Forbid·startingDeadline 600s·backoffLimit 0·activeDeadline 미설정 | 확인됨 | `kubectl get cronjob mp-summarize-reviews/-poller-price-anomaly/-score-review-sentiment -o jsonpath` → concurrency=Forbid, startingDeadline=600, backoffLimit=0, activeDeadline=(빈값). 리소스 req 50m/128Mi limit 512Mi 공통(kurly 만 1Gi→2Gi) | — | — |
| KEDA scale-to-zero 컨슈머 = 3종 | 반증됨(4종) | `kubectl get scaledobjects -A` → 4개: mp-deal-notifier(0–2)·mp-recipe-refiner(0–3)·mp-retail-refiner(0–3)·mp-user-event-sink(0–3), 전부 kafka lagThreshold 10 | — | CLAUDE.md "컨슈머 3종 min 0" — user-event-sink 포함 4종 |
| price-anomaly 알림 컨슈머는 KEDA 대상 | 반증됨 | pipeline ns Deployment mp-price-anomaly-notifier 존재하나 ScaledObject 없음(상시 1) | — | "컨슈머 전부 KEDA" 인상 |
| F-18: dev/staging 분리 환경 존재 | 미구현 | `kubectl get ns` → dev/staging 없음. config repo overlays = onprem(라이브)+eks 뿐. eks 는 `newName: PLACEHOLDER.dkr.ecr...newTag:"1.1.9"`(services/account/overlays/eks/kustomization.yaml) — 이식용 초안, 미가동 | — | — |
| mp-users ns(5d) 정체 | 확인됨(팀원 신원) | `kubectl get all,sa -n mp-users` → 워크로드 0, ServiceAccount 5개(bongsu·geonu·jungeun·junghyun·taehyun) | — | 별도 환경/서비스 아님 |
| cost ns(6d) 정체 | 확인됨(kubecost) | `kubectl get deploy,sts -n cost` → kubecost frontend/cost-model 3.2.0 + icr.io/ibm-finops/agent v1.0.19 | — | — |
| ExternalSecrets 사용 | 확인됨(31개 전수) | `kubectl get externalsecrets -A` → app 14·data 7·pipeline 2·mp-ingress 3·observability 2·argocd 1·argo-rollouts 1, 전부 ClusterSecretStore `fb-kubernetes`(K8s provider, remoteNamespace=fb-secrets, SA eso-reader) READY=True | — | — |
| AI 시크릿 주입 경로 | 확인됨 | mp-ocr-secrets={PGPASSWORD,JWT_SECRET,GEMINI_API_KEY,GCP_SA_KEY_JSON} · mp-chat-secrets={…,GEMINI_API_KEY,ES_PASSWORD} · mp-video-secrets={PGPASSWORD}+**mp-gcp-sa(gcp-sa.json 파일 마운트)** · mp-pipeline-secrets={…,REPORT_GEMINI_API_KEY,AWS_ACCESS_KEY_ID,AWS_SECRET_ACCESS_KEY}(config repo pipelines/externalsecret.yaml, remoteRef key=pipeline-secrets) | — | — |
| AI 백엔드 = Gemini API Key 직결 | 반증됨(Vertex 전환) | `kubectl get deploy mp-video/mp-ocr -n app -o jsonpath(env)` → video: VIDEO_GENAI_BACKEND=vertex·GOOGLE_APPLICATION_CREDENTIALS=/etc/gcp/gcp-sa.json·모델 gemini-3.5-flash-lite/flash / ocr: OCR_BACKEND=vision·GENAI_BACKEND=vertex. GCP_PROJECT_ID=mealplanning-503911·location=global | — | 시방서 xlsx(LLM 시트)의 "Gemini=API Key·generativelanguage.googleapis.com" |
| Bedrock 사용처·자격증명 | 확인됨(정적 IAM 키) | policies-pipeline/netpol-pipeline-fqdn-ai.yaml → bedrock-runtime.ap-northeast-2 FQDN egress 허용 대상 = score-review-sentiment·summarize-reviews. 자격증명 = mp-pipeline-secrets 의 AWS_ACCESS_KEY_ID/SECRET(정적 키, IRSA 아님). pipelines/ingest/requirements.txt:5-6 "감정분류=nova-micro·요약=claude-3-5-sonnet" | — | 시방서 "IAM(ESO→IRSA)" — IRSA 는 EKS 전제, 온프렘 실물은 정적 키 |
| 루트 geonu_accessKeys.csv 존재 | 확인됨 | `head -1` → 헤더 `Access key ID,Secret access key`, 총 2행(데이터 1행). `.gitignore:15-16` 매치·git untracked·check-ignore=IGNORED | — | — |
| 소스에 하드코딩된 AKIA/AIza 키 | 반증됨(없음) | grep -rlE "AKIA[0-9A-Z]{16}\|AIza" (docs·.git·venv 제외, 소스 확장자) → 1st-party 매치 0 (services/*/.venv 라이브러리 예제·mp-archi.png 바이너리만) | — | — |
| .env.example 자격증명 패턴 | 확인됨(placeholder 만) | 루트·deploy/app·frontend·서비스 9종 = 12개 파일. 키명만(PGPASSWORD·JWT_SECRET·CHAT_GEMINI_API_KEY·DATA_GO_KR_SERVICE_KEY 등)·실값 없음. docker-compose.yml:14 `env_file: .env`(gitignored) 패턴 | — | — |
| 이미지 :sha 핀·:latest 금지 | 확인됨 | `kubectl get deploy,sts -n app,data,pipeline(image)` → 자체 이미지 전부 `192.168.0.10/mealplanning/<img>:<40-hex sha>`. :latest 0건. 예외=서드파티 버전태그(cloudflared:2026.7.3, opstree v7.2.3 등) | — | — |
| 레지스트리 = Harbor 192.168.0.10 | 확인됨 | 상동 + Jenkinsfile:76 `REGISTRY='192.168.0.10'`·77 `PROJECT='mealplanning'`. ECR 푸시 없음 | — | — |
| K8s 매니페스트는 food-budget-app deploy/k8s 에 있다 | 반증됨 | deploy/k8s/ → README.md 1개뿐. deploy/k8s/README.md:3-8 "정본 레포로 이관(2026-07-31), mealplanning-config PR #66" | — | 구 주장 그대로 반증 |
| ArgoCD 는 별도 config 레포를 본다 | 확인됨 | `kubectl get applications -n argocd` → 45개 Application, source = git@github.com:happyInit/mealplanning-config.git(path: services/*/overlays/onprem·pipelines·platform/*·monitoring·ingress) 또는 Helm 차트. syncPolicy=automated(prune=false·selfHeal=false) | — | — |
| Jenkins 는 배포하지 않는다(자동 CD 없음) | 반증됨(자동 CD 체인 가동) | Jenkinsfile:214-285 — main 빌드 후 config 레포 clone → `kustomize edit set image <img>:<sha>` → commit/push → "ArgoCD 자동 배포". branch 'main' 가드·PR 제외 | — | CLAUDE.md "P2 전 자동 CD 없음(수동 반영)" — 현행은 sha 핀 자동 커밋→auto-sync |
| Jenkins 빌드 대상에 AI 파이프라인 포함 | 확인됨 | Jenkinsfile:19-55 CATALOG 17종 = 앱 13(video·ranking-serving 포함) + data-pipeline(pipelines/·crawler/·ml/chat-insights/·schema SQL) + crawler-kurly + pgsync + elasticsearch-nori. 태깅 = :sha+:latest(+릴리스시 :X.Y.Z, Jenkinsfile:190-199) | — | — |
| F-09 핀 수준(파이썬·핵심 의존성) | 확인됨(대부분 범위핀·일부 무핀) | 하단 핀 표 참조. `==` 완전핀은 prometheus-fastapi-instrumentator==8.0.2 뿐. ocr 의 fastapi·google-genai 는 **무핀**(services/ocr/requirements.txt:1,5) | — | — |
| CNPG: 인스턴스 수·pooler | 확인됨(2 인스턴스) | `kubectl get cluster,pooler -n data -o wide` → cluster `pg` INSTANCES=2 READY=2 primary pg-1. pooler `pg-pooler` type=rw·poolMode=transaction·instances=2 | — | "전 컴포넌트 HA" 는 2노드 HA(3 아님) |
| Kafka 토픽·파티션·RF | 확인됨 | `kubectl get kafkatopic -n data` → 5쌍+DLQ: events.user.activity·price.anomaly.detected·recipe.crawl.raw·retail.crawl.raw(각 3파티션)·retail.deal.raw(2파티션), 전부 RF=3 | — | — |
| ES·Redis 실물 | 확인됨 | elasticsearch `es` green·3노드·8.19.19(커스텀 mp-elasticsearch-nori 이미지, sts es-es-a/es-es-b). redisreplication mp-redis clusterSize=2 master=mp-redis-0 + sentinel 3(quorum 2) | — | — |
| PGSync 상시 연결 | 반증됨(현재 다운) | `kubectl describe deploy mp-pgsync -n data` → 0/1 unavailable. `logs --tail=30` → `ObjectNotInPrerequisiteState: can no longer get changes from replication slot "foodbudget_recipes_live" … invalidated because it exceeded the maximum reserved size` | — | "PGSync 상시 연결" — 슬롯 invalidate 로 크래시루프. 슬롯명이 fb 시절 `foodbudget_*` |
| Redis 영속성 비활성 | 확인됨 | cm mp-redis-config → `maxmemory 150mb`·`maxmemory-policy volatile-lru`·`save ""`. appendonly 미설정(기본 no)·RedisReplication spec 에 storage/PVC 없음 | — | — |
| mp-ingress(20h): 외부 유입 경로 변경 | 확인됨(Cloudflare Tunnel 경유) | cm mp-app-tunnel-config → `tunnel: 4c7d83d9-…` · `hostname: app.mealbong.cloud → service: https://mp-gw-public-istio.mp-ingress.svc:443`. `kubectl get gateway -A` → mp-gw-public(mp-ingress, istio, **192.168.0.14**, 20h) + mp-gw-internal(observability, .15, 7d). app ns HTTPRoute 12종 유지 | — | "MetalLB .14 직접 유입" 단독 전제 — 공개 유입은 cloudflared 터널→신설 mp-ingress ns 게이트웨이 |
| DB 계약: 이벤트 멱등키 | 확인됨 | docs/prd/schema-production.sql:261 `event_id uuid NOT NULL UNIQUE`(user_event)·:278 `impression_id uuid NOT NULL UNIQUE`(recipe_impression) — "ON CONFLICT DO NOTHING dedup" 주석(:258) | — | — |
| DB 계약: 영수증·알림 멱등 제약 | 미구현(제약 없음) | schema-production.sql:143-166 pantry.ocr_receipt/_item = bigserial PK 만, UNIQUE 없음. :205-224 notify.notification 도 UNIQUE 없음 — LOW_PRICE 쿨다운(7일)은 partial index(:232-234)+조회 로직, 제약 아님. 재처리 시 중복행 삽입 가능 | — | — |
| DB 계약: 리뷰 요약 테이블 덮어쓰기 구조 | 확인불가 | schema-production.sql 에 review 테이블 0건(`grep review` 무매치) — 리뷰 요약은 공공 data 계층(schema-public-data.sql, 본 에이전트 읽기 비허용) | schema-public-data.sql 또는 pipelines/ingest/summarize_reviews.py 열람 권한 있는 에이전트로 확정 | — |
| 시방서 대조① OCR: Bedrock Claude vision | 반증됨 | xlsx(LLM 시트) "mp-ocr Bedrock Claude vision" vs 라이브 env OCR_BACKEND=vision·GENAI_BACKEND=vertex(+GEMINI_API_KEY 시크릿) — provider 자체가 다름 | — | 시방서 xlsx |
| 시방서 대조② NS: mp-ai-ns·mp-data-ns | 반증됨 | xlsx(Workload 시트) NS=mp-ai-ns/mp-data-ns vs 라이브 = app·data·pipeline (mp-ai-ns 부재) | — | 시방서 xlsx |
| 시방서 대조③ ES: 8.15.3-nori·3노드·5Gi | 부분일치 | xlsx "es:8.15.3+nori·3(a:1·b:2)" vs 라이브 8.19.19 nori 3노드(es-es-a 1·es-es-b 2) — 구성 일치·버전 불일치 | — | — |
| 시방서 대조④ chat HPA 2–6·replicas 2 | 반증됨 | xlsx(HPA 시트) mp-chat-hpa 2–6 vs `kubectl get hpa -A` → HPA 는 mp-account·mp-recipe(Rollout, 2–4·cpu70%)뿐, mp-chat replicas 1·HPA 없음 | — | 시방서 xlsx |
| Istio sidecar 주입(app ns) | 확인됨(native sidecar) | app ns 라벨 istio-injection=enabled. `kubectl get pod -n app -o jsonpath(initContainers)` → 전 파드 `istio-validation istio-proxy`(1.34 native sidecar → spec.containers 는 1개로 보임). pipeline ns 는 미주입(init 0) | — | — |
| 관측 스크레이프 | 확인됨 | ServiceMonitor 22개(`kubectl get servicemonitor -A \| wc -l`) — app/mp-app-services·data/mp-redis·mp-elasticsearch-exporter 등. ArgoCD Application 에 loki·tempo·alloy·monitoring(대시보드 14종+rules 6종) | — | — |
| 물리 2대·master 1 SPOF·(문서상 P4에 5노드) | 부분반증 | `kubectl get nodes -o wide` → **5노드 이미 가동**: k8s-master(.17)+worker-a1(.20)·a2(.21, 6d22h)·b1(.18)·b2(.19). control-plane 1개 = SPOF 유지 | — | "worker-a2 는 P4 예정" — 이미 조인됨 |
| PG 백업 실물 | 확인됨 | data ns CronJob mp-pg-onsite-dump(04:00 KST, minio/mc 이미지, Forbid) + config repo platform/pg/{scheduledbackup,objectstore,onsite-backup}.yaml(barman plugin) | — | — |

### F-09 핀 표 (python = 전부 3.12-slim / frontend node:22)

| 컴포넌트 | numpy | scipy | lightgbm | sklearn-crfsuite | boto3 | google-genai | 기타 |
|---|---|---|---|---|---|---|---|
| ml/recipe-ranking | `>=1.26` | 없음 | `>=4.0`(선택) | — | — | — | scikit-learn `>=1.3` |
| ml/ingredient-ner | — | — | — | `>=0.5,<1` | — | — | psycopg `>=3.2,<4` |
| ml/chat-insights | — | — | — | — | — | 주석처리(선택) | scikit-learn `>=1.3` |
| ml/video-recipe | — | — | — | — | — | 주석처리(선택) | pydantic `>=2`(하한만) |
| services/chat | — | — | — | — | `>=1.35,<2` | `>=1.0,<2` | 범위핀 일관 |
| services/video | — | — | — | — | — | `>=1.0,<2` | 범위핀 일관 |
| services/ocr | — | — | — | — | — | **무핀** | fastapi·uvicorn **무핀** |
| services/account | — | — | — | — | — | — | fastapi·psycopg 등 **무핀** 다수 |
| pipelines(ingest/stream) | — | — | — | — | `>=1.35`(상한 없음) | — | confluent-kafka `>=2.5`, elasticsearch `>=8.15,<9` |

`==` 완전핀은 전 레포에서 prometheus-fastapi-instrumentator==8.0.2 뿐 — 재현 빌드 보장 없음(lock 파일 부재).

## ② as-built 요약

- [확인됨] GitOps 정본 = happyInit/mealplanning-config(45 ArgoCD Application·automated sync) · 이미지 전부 Harbor `:sha` 핀 · CronJob 22개 전부 Asia/Seoul · ESO 31개(fb-kubernetes K8s provider) · KEDA 0-스케일 4종 · Redis 무영속(save "") · CNPG 2인스턴스+transaction pooler · Kafka RF=3 · 스키마 멱등키는 activity 계열만.
- [불일치] Jenkins→config 레포 :sha 자동 커밋 = 자동 CD 가동(문서 "자동 CD 없음" 폐기) · AI 백엔드 = Vertex SA(시방서의 Bedrock-OCR·Gemini-APIKey 구도와 상이) · 시방서 ns(mp-ai-ns)·chat HPA·ES 버전 불일치 · 5노드 이미 가동(P4 대기 문서와 상이) · KEDA 컨슈머 3종→4종 · PGSync 다운(슬롯 `foodbudget_recipes_live` invalidated — 상시 연결 주장 반증).
- [미확인] 리뷰 요약 결과 테이블의 upsert/덮어쓰기 구조(schema-public-data.sql 열람 비허용 — 해당 파일 또는 summarize_reviews.py 열람으로 확정) · geonu_accessKeys.csv 의 키가 클러스터 pipeline-secrets 의 AWS 키와 동일 개체인지(fb-secrets 값 열람 불가·비교 불가 — IAM 콘솔/키ID 대조 필요).

### NEW- (기존 문서에 없을 법한 신규 구성요소)

- NEW-mp-ingress ns: Cloudflare Tunnel(mp-cloudflared-app, 터널 4c7d83d9…) → mp-gw-public Gateway(.14) — 공개 유입 경로가 app.mealbong.cloud 터널 경유로 재편(20h 전).
- NEW-argo-rollouts: mp-account·mp-recipe 가 Deployment 아닌 **Argo Rollout**(카나리 + AnalysisTemplate + service-canary + HPA 2–4).
- NEW-mp-ranking-serving: P1 랭킹 서빙이 라이브 Deployment 로 존재(model PVC + pg-direct 오버레이).
- NEW-eks overlays: 전 서비스에 `overlays/eks`(ECR PLACEHOLDER) — EKS 이식 초안 상주.
- NEW-cost ns: kubecost 3.2.0 + IBM finops agent.
- NEW-mp-users ns: 팀원 5인 ServiceAccount(RBAC 신원 전용).
- NEW-mp-ocr-config-canary: app ns 주1회(월 05:15) OCR 설정 카나리 CronJob.
- NEW-mp-pg-onsite-dump: data ns 일1회(04:00) MinIO 온사이트 덤프 CronJob(+barman scheduledbackup).
- NEW-kube-system CronJob 3종: mp-descheduler·mp-bitrot-canary-b1/b2(30분 주기).
- NEW-price.anomaly.detected 토픽 + mp-price-anomaly-notifier 상시 컨슈머(KEDA 밖).
- NEW-video Vertex 전환: mp-gcp-sa(gcp-sa.json) 마운트 + gemini-3.5-flash-lite/flash, GCP 프로젝트 mealplanning-503911.
- NEW-mp-elasticsearch-nori: 자체 재패키징 ES 이미지(8.19.19)를 Harbor 에서 서빙.
