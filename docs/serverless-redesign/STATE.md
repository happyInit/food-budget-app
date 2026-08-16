# STATE.md — 진행 원장 (재설계 세션)

> 이 문서가 대체하거나 보완하는 기존 문서: 없음 (신규 — 세션 진행 원장)

## 0. 이번 세션 범위 선언 (사용자 지시, 2026-08-07)

1. **수행: A단계** = §3 근거원·문서·레포 지도 확보 + §3-2-3 현재 상태 실사(`FACTS/02_as_built.md`) + §3.5 즉시 신청 목록.
2. **수행하지 않음**: 진단서 판정(B — `10_오류_진단서.md`는 이번 세션에서 열지 않음), 7R·설계 축(C), 심사단(D).
3. 컨텍스트 규율: 메인 세션은 계획 문서 원문을 읽지 않는다(서브에이전트의 200행 인덱스만). 서브에이전트 반환 = 파일 경로 + 상위 5행 + 요약 3줄.
4. 기존 파일 수정 금지(`deploy/k8s/README.md`에 커밋되지 않은 수정 존재). 산출은 `docs/serverless-redesign/` 하위 `.md` 신규 생성만.

## 1. 근거원 가용성 (§3-1, 2026-08-07 실확인)

| 근거원 | 상태 | 근거 |
|---|---|---|
| WebFetch(웹 접근) | ✅ 가용 | docs.aws.amazon.com/bedrock/latest/userguide/model-access.html 실호출 1회 성공 [조회 2026-08-07] |
| aws CLI | ❌ 미설치 → ✅ **가용 (B단계 재확인 2026-08-07)** | A단계 시점 `aws: command not found` → 이후 사용자 설치. 재확인: v2.31.35 + 자격증명 유효(계정 `689192361171` · IAM user `geonu`, `sts get-caller-identity` 성공). `11_실측발견`의 기계 근거(`FACTS/bedrock-*.json`)가 이 CLI 산출물 |
| gcloud CLI | 미확인 | 실사 중 확인 예정 |
| 클러스터(kubectl) | 미확인 | 실사 중 확인 예정 |

## 2. 문서 확보 (§3-2 하드 게이트 — 통과)

| 문서 | 소재 | 비고 |
|---|---|---|
| 계획 문서 00~08·README·REVIEW_BRIEF (11종) | `docs/serverless-migration/` | ✅ 레포 내 |
| `10_오류_진단서.md` (357,879B) | `docs/serverless-migration/` | ✅ 존재 확인만 — **이번 세션 열지 않음** (사용자 지시) |
| `09_프롬프트_설계근거.md` (316,616B) | **레포 밖** `/mnt/d/dz_bravo/serverless-migration/` | ✅ 읽기 가능. 전문 읽기 금지(§3-3) — 목차 수준만 서브에이전트가 인덱싱 |
| 합계 | **13/13 접근 가능** | 게이트(≥8 + 10번 존재) 통과 |
| 목록 외 파일 | `/mnt/d/.../RUNBOOK_세션운영.md` (13,909B) · `PROMPT_fable5_설계세션.md` (124,083B) | §3-3 규칙에 따라 파일명·크기만 기록. 1MB 근접 파일 없음 |

### 2-1. 원본 근거 문서 (§3-2-1)

| 원본 | 소재 | 상태 |
|---|---|---|
| `인프라_통합_시방서(개인용).md` (29,900B) | `docs/serverless-migration/` (mtime 2026-08-07 08:57) | ✅ 확보 — 단 as-designed·미갱신 전제(모든 항목 `[설계]`에서 출발) |
| `AI실측기록_html/` 7종 | `docs/serverless-migration/AI실측기록_html/` | ✅ 확보. `docs/` 루트에 동명 `.md` 대응본 존재(ai-chat-mass-measurement.md 등) |

### 2-2. K8s 매니페스트 소재 (§3-2-2 — 해소, ⚠️ 2026-08-07 정정)

- ~~`deploy/k8s/`에 실재~~ → **정본 = `happyInit/mealplanning-config`**(ArgoCD Application 45개, automated sync — 실사 D-01). 이 레포 `deploy/k8s/`는 README 1개뿐. 초기 "config 레포 탐색 금지" 전제는 낡은 사전 정보였고 실사가 이긴다. `docs/design/`의 k8s-오브젝트-시방서 xlsx 3종은 참조 대상 유지.
- **정정 로그**: "deploy/k8s 에 실재·config 레포 탐색 금지" → "정본 = mealplanning-config, deploy/k8s 는 README 뿐"으로 변경 (근거 FACTS/02_as_built D-01, 컨펌본 §7 내부 모순 ①).

## 3. 진행 원장

| 단계 | 서브에이전트 ID | 소유 경로 glob | 금지 경로 glob | 산출 파일 경로 | 상태 | 핵심 결론 1줄 |
|---|---|---|---|---|---|---|
| §3-1 근거원 확인 | (메인) | — | — | STATE.md §1 | 완료 | 웹 ✅ / aws CLI ❌ 미설치 |
| §3-2 문서 확보 | (메인) | docs/serverless-migration/ (ls만) | 원문 읽기 | STATE.md §2 | 완료 | 13/13 접근 가능(09는 레포 밖) |
| §3.5 즉시 신청 목록 | (메인) | docs/serverless-redesign/06_열린질문.md | — | 06_열린질문.md §1 | 완료 | Anthropic FTU 폼=즉시 승인, 쿼터류=리드타임 [미확인] → 오늘 신청 권고 |
| §3-5 레포 인벤토리 | (메인) | 레포 전체 (읽기) | docs/serverless-migration/** 원문 | FACTS/01_repo_inventory.md | 완료 | 매니페스트=mealplanning-config 이관 [불일치]·클러스터 5노드 라이브·10종 진입점 추정 완료 |
| §3-4 명제 인덱스 | P | docs/serverless-migration/** + /mnt/d(09 목차만) | 레포 코드 · 10_오류_진단서.md | FACTS/00_plan_index.md (119행) | 완료 | 명제 62+시방서 14+09지적 28행. 최상위 검증가치 3건 = S3 이벤트 전제(02:49-67)·NER 동기 주장(01:20)·100% 일치 기준(01:309-337) — 셋 다 실사 결과와 충돌 |
| §3-2-3 실사 ①미디어 | A | services/ocr,video · ml/video-recipe · frontend 업로드부 | docs/** · 타 서비스 | FACTS/agent-A.md | 완료 | 확인35/반증1/미구현3/확인불가2 — 영수증=인프로세스 asyncio(이벤트 아님)·품목분류=로컬 규칙(Gemini 아님)·원본 미저장(F-20)·인증=개인 Gemini 키 기본 |
| §3-2-3 실사 ②동기AI | B | services/chat,recipe · ml/ingredient-ner,recipe-ranking,chat-insights | docs/** · 타 서비스 | FACTS/agent-B.md | 완료 | 챗=동기 단발 JSON·기본 template(LLM refine은 env opt)·멀티턴 Redis TTL3600 — F-01 반증: CRF는 배치 백필 전용(챗 동기경로=gazetteer rule)·랭킹은 동기 0.3s지만 기본 flag OFF |
| §3-2-3 실사 ③배치·이벤트 | C | pipelines/** · services/operations,notify,price,pantry | docs/** · 타 서비스 | FACTS/agent-C.md | 완료 | #4·#8·#10=수동 argparse 배치(증분·멱등) — F-03 반증(감정=배치)·F-07 판정(중복억제=PG 2중, Redis 아님)·"Kafka=Phase2 밖" 반증(토픽5·그룹5·DLQ 실가동) |
| §3-2-3 실사 ④설정·클러스터 | D | deploy/** · Jenkinsfile · infra/** · requirements/Dockerfile 전수 · kubectl(RO) · mealplanning-config(RO) · schema-production.sql · AI xlsx 2종 | 앱 로직 파일 · docs/** 그 외 | FACTS/agent-D.md | 완료 | config 레포=정본(45 App)·:sha 핀·CronJob 22 KST·ESO 31 — 반증: 자동 CD 가동·AI=Vertex·PGSync 다운·5노드·KEDA 4종. NEW 12건 |
| 실사 종합 | (메인) | FACTS/agent-*.md + kubectl 보충(chat-config 등) | 계획 문서 원문 | FACTS/02_as_built.md | 완료 | 불일치 19건(D-01~19)·NEW 12·미구현 6 — 챗 라이브=template(LLM 0)·랭킹 flag OFF·앱=pooler/파이프라인=pg-rw 직결 |

**서브에이전트 호출 누계: 9/25** (탐색 팬아웃 4/8 + 인덱서 1 + B단계 PF 판정 팬아웃 4).

### 3-1. B단계 부분 개시 (사용자 2차 지시, 2026-08-07)

범위 = **PF-01~PF-14만** 판정(다른 분류 금지). 기계 근거 = `docs/serverless-migration/11_실측발견_2026-08-07.md`(카드 전제와 어긋나면 `문서 낡음`). `10_오류_진단서.md`는 §0·§1·§2(+§4 요약표 형식)만 메인이 읽음 — 카드 본문은 행 구간 발췌로 서브에이전트 전달.

| 단계 | 서브에이전트 ID | 소유 경로 glob | 금지 경로 glob | 산출 파일 경로 | 상태 | 핵심 결론 1줄 |
|---|---|---|---|---|---|---|
| B: PF-02·03·14 (Bedrock 액세스·청구) | F | 진단서 L151-278·957-1020 + bedrock-*.json | 동일 | FACTS/agent-F.md | **완료** | PF-02 사실 · PF-03·14 부분적으로 사실 |
| B: PF-01·04·05·06·12 (메인 세션 순차 — ~~E/G/H 에이전트~~ 폐기) | (메인) | 진단서 해당 카드 구간 + webcache | 동일 | FACTS/agent-PF-resume.md | **완료** | PF-01·04 사실 · 05·06·12 부분적으로 사실 |
| B: PF-07·08·09·10·11·13 | — | — | — | 00_진단_판정표.md §1 | **보류** | 시간 제약으로 미판정 — 컨펌 후 재개 |
| B: 판정표 종합 | (메인) | 00_진단_판정표.md | — | 00_진단_판정표.md | **완료** | 판정 8(사실 3·부분 5)·미판정 6, 하드 게이트 통과 |

- **정정 로그**: 에이전트 E·G·H 행(상태 "진행", 산출 agent-E/G/H.md — 실제로는 미가동·파일 미생성) → 삭제하고 "메인 세션 순차 판정(agent-PF-resume.md), 판정 8 완료·6 보류"로 변경 (컨펌본 §7 내부 모순 ②).
- **정정 로그(분류)**: 이전 대상 분류 구판 "이전 4 · 제외 3(#5·#9·#10) · 재정의 3(#3·#6·#7)" → **"이전 6(전면 4 + 배치 한정 2: NER·가격 탐지) · 잔류 1(챗봇) · 제외 1(랭킹) · 내장 2(#9·#10)"**로 변경 — 1단계 정정(2026-08-07), 정본 = `01_이전대상_7R.md` + 컨펌본 §2 (컨펌본 §7 내부 모순 ③).

## 4. A단계 종료 선언 (2026-08-07)

1. A단계 산출물 7개 완성: STATE.md · 00_요약판정.md(§3 잠정 관찰 7건) · 06_열린질문.md(즉시 신청 v1+v1.1·콘솔 요청 6·Q-01·재개 지점) · FACTS/00_plan_index.md · 01_repo_inventory.md · 02_as_built.md · agent-{A,B,C,D}.md.
2. B단계(진단서 판정)·C단계(7R·설계 축)·D단계(심사단)는 이 세션에서 수행하지 않음(사용자 지시). 재개 절차는 06_열린질문.md §0.
