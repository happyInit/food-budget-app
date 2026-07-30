# AI 서비스 배포 시방서 (k8s) — 전체 AI 기능

> **위치/관계**: 인프라 정본 [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)를 보완하는 **AI 파트 배포 시방서**. 정본 미수정. ES는 별도 [`es-spec.md`](./es-spec.md).
> **경계(중복 방지)**: 이 문서는 **배포 관점**(워크로드·자원·의존·Secret·egress·상태성)만 SoT다. **기능 정의 = [`ai-spec.md`](./ai-spec.md) · 기능 현황/상태 = [`ai-features-roadmap.md`](./ai-features-roadmap.md)**가 SoT이며, 아래 §0·각 절의 `역할`·`상태` 표기는 **편의 스냅샷**(충돌 시 그 두 문서가 우선, 여기서 재정의하지 않음).
> **범위**: 운영/구축 중 4종(chat·ocr·ranking·video-recipe) + 로드맵 확정 4종(최저가 이상탐지·리뷰 감정분석·이상징후 탐지 대시보드·유튜브 영상분석).
> **주의**: 포트=앱 개발자 지정(80xx), IP/DNS·MetalLB=인프라(§2.3). k8s 이관 후 앱은 서비스 DNS로 연결(IP 미사용). 자원값=**기준선(부하테스트 후 확정)**.

## 0. 전체 AI 기능 목록
| # | 기능 | 역할 | 배포 형태 | LLM | 상태 |
|---|---|---|---|---|---|
| 1 | **chat**(밥풀이) | RAG 대화 추천 | «Deploy»+HPA | **Bedrock**(`nova-micro` 서울) | 운영 |
| 2 | **ocr** | 영수증 인식 | «Deploy»(rs:1) | **Gemini**(`3.5-flash-lite` 핀) | 구현(profile) |
| 3 | **ranking** | 개인화 추천 | serving «Deploy» / retrain «Job» | 없음(ML) | 구현(profile) |
| 4 | **video-recipe** | 영상→레시피 | «Deploy»+HPA | **Gemini**(영상·API Key) | 라이브러리→서비스화 예정 |
| 5 | **최저가 이상탐지** | 가격 이상치·최저가 알림 | «Deploy»(Kafka consumer·KEDA) | 없음(z-score 통계) | 검증완료·발행 미구현 |
| 6 | **리뷰 감정분석** | 긍정% + 2~3문장 요약 | «CronJob»(배치) | 분류=**Bedrock**(`nova-micro`) / 요약=**Bedrock 후보**(`nova-micro`, 대안 `claude-3-5-sonnet-v2`) | 로드맵 |
| 7 | **이상징후 탐지** | 인프라 이상 감지 대시보드 | «Deploy»/«CronJob» + Grafana | 자체 통계/ML(요약 선택) | 로드맵(인프라용) |
| 8 | **유튜브 영상분석** | 영상 콘텐츠 분석 | «Deploy»+HPA | **Gemini**(영상·API Key) | 로드맵(video-recipe 연계) |

> NER(재료 인식)·의도분류는 **chat 내부 컴포넌트**(런타임 rule 기반)라 별도 서비스 아님.

## 1. 공통 배포 정책
| 항목 | 내용 | 근거 |
|---|---|---|
| 네임스페이스 | 🔴 **`ai` ns**(AI 파트 소유 — serving·video-recipe·ner-serving·배치) · **chat·ocr·frontend·FastAPI = `app` ns** · 데이터 = `data` ns · ai-ns는 mesh ON(배치 Job은 `inject:false`) | 설계도·`hybrid-cloud-federation-plan.md` 기준 **ai-ns 확정**(2026-07-30). ⚠️ 인프라 `mp_k8s_infra_object_spec.md §1`(현재 app-ns 서술)엔 **반영 요청**(교차팀 정합 대기) |
| 메시 | Istio sidecar(envoy) 주입 (data ns는 메시 밖) | 정본 §4 |
| 배포/CD | ArgoCD(GitOps) · 이미지 Harbor→ECR · overlays onprem/eks | 정본 §7·§8 |
| **외부 LLM egress** | **하이브리드** — Bedrock: `bedrock-runtime.ap-northeast-2`(chat·분류·구조화) / Gemini: `generativelanguage.googleapis.com`(현행 OCR·video) 🔴 **→ 전환 중 `*-aiplatform.googleapis.com`(GCP Vertex AI) + `sts.googleapis.com`(연동)** | PR #300 · Vertex 전환 `gcp-migration-plan.md`·PR #387 |
| egress 통제 | Cilium CNP FQDN + CoreDNS(53) 예외 | 정본 §6.1 |
| Bedrock 인증 | 온프렘=AWS access key(ESO) → EKS=IRSA · IAM `bedrock:InvokeModel` | PR #300 |
| Gemini/Vertex 인증 | 현행 `VIDEO_GEMINI_API_KEY`(ESO) 🔴 **→ 전환 후 키리스**(k8s SA OIDC → GCP Workload Identity Federation, 정적키 0) | OCR·video·유튜브분석 · `hybrid-cloud-federation-plan.md` |
| Secret | External Secrets Operator(ESO) | 정본 §6.4 |
| 자원 원칙 | 메모리 request=limit · 값=기준선(측정 후 확정) | — |

**LLM 매핑 요약(2026-07-28 실측 확정)**: **Bedrock(`apac.amazon.nova-micro-v1:0`, 서울)** = chat refine·리뷰 감정분류·구조화 추출 / **Gemini(`3.5-flash-lite` 핀)** = **OCR**·video-recipe·유튜브분석·OCR 티어7 분류 / 자체 통계·ML = ranking·최저가·이상징후.

> ⚠️ **정정(2026-07-28)**: 이전 판은 "Bedrock(Claude) = chat·ocr"이었으나 실측으로 뒤집혔다 — **OCR은 Bedrock 이관 불가**(Nova 한글 통짜 환각, claude-3-haiku 글자 오독), **chat은 Claude가 아니라 Nova micro**(Claude 4.5는 marketplace 액세스 미개통으로 미측정). 근거: [`ai-model-selection-final.md`](./ai-model-selection-final.md)

---

## 2. chat (밥풀이 RAG 챗봇) — 운영
| 항목 | 값 |
|---|---|
| Workload / Replicas | «Deploy» / 2 (HA, 무상태) · HPA min2/max6 CPU70% |
| Image / Port | harbor/…/chat:{tag} · **8003** (ClusterIP) |
| 자원(기준선) | req 250m/512Mi · limit 1/1Gi |
| 프로브 | readiness·liveness GET /health:8003 |
| 의존 | ES(9200 레시피검색·nori) · Redis(6379 멀티턴 세션) · PG(5432 개인화) · **Bedrock**(refine `apac.amazon.nova-micro-v1:0` 서울) |
| Secret(ESO) | AWS creds · DB creds |
| 상태성 | 무상태(세션=Redis) → replica·HPA 자유 |

## 3. ocr (영수증 인식) — 구현(profile 배포)
| 항목 | 값 |
|---|---|
| Workload / Replicas | «Deploy» / **1 고정** (⚠ 잡상태 인메모리 → Redis 이관 前) |
| Image / Port | harbor/…/ocr:{tag} · **8010** |
| 자원(기준선) | req 250m/512Mi · limit 1/1.5Gi(vision) |
| 의존 | **Gemini**(`3.5-flash-lite` vision 이미지→JSON · API Key) · Redis(잡 상태 동기화) · PG(ocr_receipt 결과) |
| HPA | 없음 → Redis 이관 후 확장+HPA 가능 |
| 상태성 | `_JOBS` 인메모리 → Redis 외부화가 replica 확장 선행조건 (#296/#297) |

## 4. ranking (개인화 추천) — 구현(profile)
| 항목 | serving | retrain |
|---|---|---|
| Workload | «Deploy» / 1 | «Job»/«CronJob» (배치) |
| Port | **8009** (mealplan이 호출) | — |
| 자원(기준선) | req 250m/512Mi·limit 1/1Gi | req 500m/1Gi·limit 2/2Gi |
| 의존 | PG(피처) · MinIO(모델 /reload 다운로드) | PG(activity 학습데이터) · MinIO(모델 업로드) |
| 특이사항 | **모델 아티팩트 RWX 제거 → MinIO(S3 API)** (정본 §5.5) | |

## 5. video-recipe (영상→레시피) — 라이브러리 → 서비스화 예정
| 항목 | 값 |
|---|---|
| 현황 | ⚠ 현재 `ml/video-recipe` 라이브러리(Dockerfile·FastAPI 없음) → 서비스화 후 배포 |
| Workload / Replicas | «Deploy»(예정) / N + HPA (상태 이미 Redis → 확장 자유) |
| 의존 | **Gemini**(영상 URL 분석·API Key·Bedrock 미경유) · Redis(교차유저 캐시·단일비행락) · PG(레시피북) |
| Secret(ESO) | `VIDEO_GEMINI_API_KEY` · DB creds |
| 상태성 | replica-safe by design (#298) |
| Bedrock 제외 이유 | 유튜브 URL 직접분석은 Gemini만 가능(Bedrock URL fetch 불가) |

---

## 6. 최저가 이상탐지 (가격 이상치·최저가 알림) — 검증완료·발행 미구현
| 항목 | 값 |
|---|---|
| 역할 | 소매 가격 이상치(z-score) 감지 → 관심 등록 유저에게 최저가 알림 fan-out |
| Workload | «Deploy» (Kafka **이상탐지 컨슈머**, 목표 **KEDA** lag 스케일) |
| LLM | **없음** — 자체 통계 모델(z-score, ai-spec §2) |
| 의존 | PG `price.price_watch`(관심 등록·fan-out 소스) · `data.retail_item_price_compare`(실시간 최저가) · Kafka(**LOW_PRICE 발행**) · notify(알림) |
| 상태 | 실DB 실현가능성 검증 완료(overlap 63.7%·고빈도원물 92%) · `price_watch` 스키마 존재 · **CRUD + LOW_PRICE 발행 미구현** |
| 게이트 | RAG·개인화·OCR 100% 완료 후 착수 [[anomaly-detection-gated]] |

## 7. 리뷰 감정분석 — 로드맵
| 항목 | 값 |
|---|---|
| 역할 | 만개의레시피 리뷰데이터 분석 → **긍정 % 표시 + 2~3문장 종합 요약** |
| Workload | «CronJob» (배치 처리) |
| LLM | 감정 **분류**=**Bedrock** `apac.amazon.nova-micro-v1:0`(서울, 24/25≈Gemini 25/25 — 확정) · **요약**=**Bedrock 후보** 1순위 `apac.amazon.nova-micro-v1:0` / 2순위 `apac.anthropic.claude-3-5-sonnet-20241022-v2:0` — ⚠️ **자유 요약은 미실측이라 구현 후 실측으로 확정** |
| 의존 | PG(리뷰 원본 + 감정·요약 결과 저장) · Bedrock(분류) |
| 상태 | 로드맵(미착수) |

## 8. 이상징후 탐지 대시보드 — 로드맵 (인프라/클라우드 담당자용)
| 항목 | 값 |
|---|---|
| 역할 | AI+모니터링으로 **인프라 이상 감지**(부하·읽기폭주·DROPPED flow·DNS 이상 등) |
| Workload | «Deploy»/«CronJob» (메트릭 구독) + Grafana 대시보드/알람 |
| LLM | 자체 통계/ML(이상탐지 코어) · 요약은 Bedrock 선택 |
| 의존 | Prometheus/**Mimir**(메트릭 시계열) · Hubble/Istio 텔레메트리 · Grafana · Alertmanager |
| 연계 | 최저가 이상탐지의 통계 기법 재사용(정본 §9 "AI↔인프라 다리") · 부하테스트와 병행 |
| 상태 | 로드맵(미착수) |

## 9. 유튜브 영상분석 — 로드맵 (video-recipe 연계)
| 항목 | 값 |
|---|---|
| 역할 | 유튜브 영상 콘텐츠 분석(영상→레시피 확장) |
| Workload | «Deploy» + HPA |
| LLM | **Gemini**(영상·API Key·Bedrock 미경유, video-recipe와 동일 이유) |
| 의존 | Gemini · Redis(캐시) · PG |
| 상태 | 로드맵(미착수) |

---

## 10. 상태·LLM 한눈 요약
| 배포 대상 | 지금 | LLM egress |
|---|---|---|
| chat · ocr · ranking(serving) | 서비스 운영/구현 | chat=**Bedrock(nova-micro)** / ocr=**Gemini** / ranking=없음 |
| ranking(retrain) | 배치 구현 | 없음 |
| video-recipe | 라이브러리→서비스화 | **Gemini** |
| 최저가 이상탐지 | 검증완료·발행 미구현 | 없음(z-score) |
| 리뷰 감정분석 · 이상징후 · 유튜브분석 | 로드맵(미착수) | 리뷰 분류=Bedrock(확정)·요약=Bedrock 후보(구현 후 실측) / 유튜브=Gemini / 이상징후=자체 |

**Bedrock(AWS 크레딧·서울)**: chat refine·리뷰 감정분류·구조화 추출 · **Gemini(API Key)**: **OCR**·video-recipe·유튜브분석·OCR 티어7 분류 · **LLM 없음**: ranking·최저가·이상징후(코어).
