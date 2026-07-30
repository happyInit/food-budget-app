# Gemini → AWS Bedrock 전환 설계 (AI 모델 이관)

> **위치/관계**: 인프라 정본 [`docs/mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)를 보완하는 **AI 모델 이관 설계**. 정본은 수정하지 않는다 — 정합·협의 항목은 §10에 모아 이슈로 공유한다.
> **목적**: 개인 API키 기반 Gemini AI를 **AWS Bedrock(크레딧)** 으로 이관(k8s 환경). 단, **한계·성능저하가 없는 것만** 이관하고 블로커는 Gemini 유지(하이브리드).
> **검증**: 이 문서는 **두 번 교차검증**으로 작성 — ⓐ 현재 코드 상태(모든 Gemini 사용처·API 패턴·키·모델) ⓑ 인프라 이관 계획 정합(egress·인증·시크릿·리전·예산캡). 근거는 각 항목에 명시.

## 1. 전환 대상 판정 (검증①: 현재 코드 전수)
| 서비스 | Gemini 사용 | API 특징(근거) | Bedrock | 판정 |
|---|---|---|---|---|
| **챗 생성**(밥풀이) | 텍스트 생성 | `generator/gemini.py` `genai.Client`→`generate_content`, `GENERATOR_BACKEND` 팩토리 | **Nova micro(서울)** | ✅ **이전 확정**(§1.1) |
| **OCR vision** | 이미지→JSON | `backend/vision.py` `Part.from_bytes`(이미지)+`response_mime_type=json`+`thinking_config`, `OCR_BACKEND` 팩토리 | Claude vision + Converse tool-use | ❌ **제외**(실측 미달 — §1.1) |
| **chat-insights**(리포트) | 오프라인 요약 | `ml/chat-insights/reports.py` `_gemini_narrative` (배치) | 텍스트 | ✅ 가능(**저우선**, 런타임 아님) |
| **ingredient-ner 사전** | 오프라인 1회성 | `ml/ingredient-ner/gemini_dict.py` ("런타임 없음") | 텍스트 | ✅ 가능(**저우선**) |
| 🔴 **video-recipe** | **유튜브 URL 직접분석** | `ml/video-recipe/extract.py` `file_data=FileData(file_uri=url)` | **불가** — URL 네이티브 fetch 없음 | ❌ **제외 = Gemini 유지** |

> ⚠️ **2026-07-28 실측으로 위 판정이 두 번 뒤집혔다**(OCR ✅→❌, 챗 ✅→⏸️→✅). 최초 설계는 "코드 구조상 이관 가능"만 본 것이고, 실제 품질 측정 결과 챗·OCR 모두 현행을 넘지 못했다. 아래 §1.1이 **현재 유효한 판정**이다.

### 1.1 실측 기반 판정 (2026-07-28 · 근거: [`ai-model-migration-benchmark.md`](./ai-model-migration-benchmark.md))

**측정 규모**: 11모델 × 50케이스 = **550건**(에러 0) + OCR 실물 13장 + 분류/감정 50케이스 × 4모델.

| 기능 | 실측 결과 | 판정 | 근거 |
|---|---|---|---|
| **OCR vision** | Gemini 12/13 · Nova 정합 1/13(한글 통짜 환각) · claude-3-haiku 정합 2/15(글자 오독: 맥도날드→"매도바드") | ❌ **제외 — Gemini 유지** | 품목명이 틀리면 NER→item_master 매칭 실패 |
| **챗 refine** | HARD-25에서 **숫자보존 프롬프트** 적용 시 nova-micro 12→**23/25**. 남은 실패 2건은 **프로덕션이 refine하지 않는 경로**(영양·가격) → **실제 서비스 경로 20/20 = Gemini 20/20 동률** | ✅ **이전 확정** | 안전(환각) 25/25 동일 · **40% 저렴 · 2배 빠름(456ms) · 서울 레지던시 · 크레딧 결제**. 근거 [`ai-model-selection-final.md`](./ai-model-selection-final.md) 실험 G |
| **구조화 추출**(텍스트→JSON) | nova-micro **품목 100%·합계 25/25** · 0.031원/콜 · 469ms | ✅ **채택**(신규) | 상위 9모델 포화 → 최저가·최속 선택이 합리적 |
| **리뷰 감정분석** | nova-micro **24/25** vs Gemini 25/25 · **351ms(2.2× 빠름)** · 0.0095원 | ✅ **신규는 Bedrock으로** | 실질 동급(오답 1건은 "레시피 잘 봤습니다" 경계 케이스) |
| **OCR 티어7 품목분류** | nova-micro 18/25(카테고리 22·보관법 20) vs Gemini 25/25 | ❌ **제외** | 보관법·가공식품 경계 판단에서 미달 |
| video-recipe | — | ❌ 제외(§6) | 유튜브 URL 입력 자체가 없음 |

**핵심 규칙 (실측에서 도출)**: Bedrock Nova는 **한글 "생성·판독"에 약하고**(OCR 환각, 텍스트 구조화에서도 "대파"→"냠파"), **"텍스트 입력 → 라벨·구조 출력"에는 포화 품질**이다. → **이관 기준은 서비스가 아니라 태스크 유형**으로 판단한다.

**전환 범위 결정(개정 → 🔴 2026-07-28 재개정)**: **챗 refine = Bedrock `apac.amazon.nova-micro-v1:0`(서울) 이전 확정**(실험 G — 프로덕션 경로 20/20 = Gemini 동률, 정본 `ai-model-selection-final.md`). **OCR·영상 = Gemini 유지**(모델 유지 · 호스팅은 GCP Vertex AI로 이전, `gcp-migration-plan.md`). Bedrock은 **챗 refine + 신규 분류·구조화**(감정분석·구조화 추출)에 적용 + 오프라인 2건(후순위). **최종 형태는 하이브리드**(Bedrock: 챗·분류·구조화 / Vertex: OCR·영상).

> 🔓 **재평가 조건**: `claude-haiku-4-5` / `claude-sonnet-4-5`는 **마켓플레이스 액세스 미개통으로 미측정**(2026-07-28 재확인 시에도 `AccessDeniedException` 지속). 단 **`apac.anthropic.claude-3-5-sonnet-20241022-v2:0`는 호출 가능**하여 저빈도 생성 태스크의 대안 후보로 둔다. 열리면 동일 50케이스 + OCR 13장으로 재측정하여 챗·OCR 판정을 갱신한다.

## 2. 전환 방식 = 추가형 백엔드 (우리 서비스 구조에 맞춤)
두 서비스 모두 **교체가능 백엔드 팩토리 + 추상 인터페이스**가 이미 있어, Bedrock은 **새 구현체 추가**로 끝난다 — 파이프라인·프롬프트·캐싱 재사용, **env 토글로 즉시 롤백**.
| 서비스 | 인터페이스 | 추가 구현체 | 토글 | 롤백 |
|---|---|---|---|---|
| 챗 | `generator/base.py` `Generator` (`factory.py`: template\|gemini) | **`BedrockGenerator`** | `GENERATOR_BACKEND=bedrock` | env 되돌림 |
| OCR | `backend/base.py` `OcrBackend` (`factory.py`: vision\|mock) | ~~`BedrockVisionBackend`~~ **미채택** | — | **OCR=Gemini 유지 확정**(§1.1 — 실측서 Nova 한글 환각·claude-3-haiku 오독) |

→ **재작성 없음.** 카나리(일부 트래픽 env 전환) 후 검증, 문제 시 즉시 Gemini 복귀.

## 3. 인프라 정합 — 허점 차단 (검증②)

### 3.1 인증 — 🔴 온프렘 k8s는 IRSA 불가
- **온프렘(현 이관 대상)**: Bedrock 호출은 **AWS IAM access key/secret**로 인증 → **ESO Secret 주입**. 이는 **백업이 이미 AWS S3(ap-northeast-2)에 자격증명으로 접근하는 경로와 동일**(정본 §5.4·§6.3) → **신규 인증 메커니즘 아님, 기존 패턴 재사용**.
- **EKS 이관 시**: **IRSA로 전환** — 정본 §6.4 *"ESO 온프렘 백엔드 → AWS Secrets Manager + IRSA, CR은 보존"* 철학과 **정확히 일치**. `ExternalSecret` CR 그대로, 백엔드만 교체.
- **최소권한**: IAM 정책은 `bedrock:InvokeModel`(+`bedrock:InvokeModelWithResponseStream`)을 **확정 모델의 inference profile ARN에만** 부여(`apac.amazon.nova-micro-v1:0`). 세부 정책 문구는 구현 시 확정. 앱 SA에 백업 bucket 권한 안 주는 정본 §6.3 격리 원칙 준용.

### 3.2 Egress — 🔴 하이브리드 FQDN (video-recipe 붕괴 방지)
정본 §6.1 Cilium CNP FQDN egress(`chat·ocr·youtube → generativelanguage.googleapis.com`)를 **부분 변경**(⚠️ **chat만** Bedrock — OCR은 이관 판정으로 Gemini 유지):
| 파드 | egress FQDN | 비고 |
|---|---|---|
| chat | **`bedrock-runtime.ap-northeast-2.amazonaws.com`** (신규) | Bedrock 데이터플레인(nova-micro) |
| **ocr** | **`generativelanguage.googleapis.com` 유지** | 🔴 OCR=Gemini 유지 확정(§1.1) — bedrock으로 바꾸면 OCR 붕괴 |
| **youtube(video-recipe)** | **`generativelanguage.googleapis.com` 유지** | Bedrock 제외(§1) |
- 🔴 **허점 경고**: FQDN allowlist를 전역으로 bedrock만 두고 googleapis를 제거하면 **video-recipe가 조용히 붕괴**한다. **하이브리드 유지 필수**.
- CoreDNS(53) egress 예외는 그대로(정본 §6.1 함정 방지).

### 3.3 리전
- Bedrock = **ap-northeast-2(서울)** — 백업 S3와 **동일 리전**, 데이터 인-리전(챗·영수증이 리전 밖으로 안 나감 = Gemini 대비 소폭 개선).
- ⚠️ **확인 항목**: 서울 리전의 Claude/Nova **모델 가용성** — 최신 모델은 **cross-region inference profile**(apac)이 필요할 수 있음 → PoC 전 확인(§10).

### 3.4 예산·비용 격리 (앱 캡 유지)
- **앱 층 월캡 유지** — `MONTHLY_CAP_ENABLED`+Redis 카운터(`guardrails.py`: count×`gemini_cost_per_call_won`≥`monthly_budget_won`)는 **provider 무관**하게 동작. 단 **단가값을 Bedrock으로 갱신**(설정명 provider 중립화 권장: `llm_cost_per_call_won`).
- **Google 청구캡(8,000원) → AWS Budgets + 크레딧**으로 대체.
- **키 분리(비용 격리) → 서비스별 IAM 역할/inference profile + 비용 태그**로 대체.
- 정본 §6.1 **이중 방어(앱 캡 + FQDN egress)** 그대로 — egress만 bedrock로 교체.

## 4. API 패턴 매핑 (기능 손실 없이)
| Gemini(현재) | Bedrock | 비고 |
|---|---|---|
| `google.genai` Client | **boto3 `bedrock-runtime` (Converse API)** | requirements 교체 |
| `generate_content(...)` | `converse(...)` | 통일 인터페이스 |
| `response_mime_type="application/json"`(OCR) | **Converse tool-use**(구조화 강제) 또는 JSON 프롬프트 | Claude JSON 신뢰도 높음 → 무열화 |
| `Part.from_bytes(image)`(OCR) | Converse **image content block** | 이미지 지원 동일 |
| `thinking_config(thinking_budget)`(OCR) | Claude **extended thinking**(OCR은 최소 → **off**) | Gemini 특유 **400-fallback 로직 불요** |
| 응답 sha1 캐싱(챗) | **유지** | provider 무관 |

## 5. 모델 매핑 (실측 확정 — 2026-07-28)
| 용도 | 확정 모델 | 리전/프로필 | 근거 |
|---|---|---|---|
| **신규 분류·감정분석** | **`apac.amazon.nova-micro-v1:0`** | 서울 | 감정 24/25(Gemini 25/25 동급)·**351ms**·0.0095원 |
| **신규 구조화 추출** | **`apac.amazon.nova-micro-v1:0`** | 서울 | 품목 100%·합계 25/25·최저가 0.031원·최속 |
| 챗 생성 | ✅ **`apac.amazon.nova-micro-v1:0`**(서울) | 서울 | 프로덕션 경로 20/20 동률·2배 속도·40% 절감. 전환 전 **가드수정 + 숫자보존 프롬프트 + temp 0.0 선적용 필수** |
| OCR vision | (제외) `gemini-3.5-flash-lite` 유지 | — | Bedrock 대안 전부 한글 판독 미달 |
| 미측정 후보 | `claude-haiku-4-5-20251001-v1:0`·`claude-sonnet-4-5-20250929-v1:0` | 서울 `global.` | **액세스 개통 시 재평가** |

**호출 규약(실측 확인)**: 서울은 on-demand 직접 호출 불가 → **cross-region inference profile 필수**. Claude=`global.` / Nova=`apac.` 프리픽스.

## 6. 전환 제외 근거 — video-recipe
`ml/video-recipe/extract.py`의 `types.Part(file_data=types.FileData(file_uri=url))` — **Gemini만 유튜브 URL을 직접 받아 영상을 분석**한다. Bedrock은 URL 네이티브 fetch가 없어 **영상 다운로드+프레임 업로드 파이프라인을 자체 구축**해야 하고, 그래도 품질·비용이 악화 = **성능저하 기능** → 이관 제외, **Gemini(`VIDEO_GEMINI_API_KEY`) 유지**. (상태성은 `video-recipe-ai.md §9` 참조)

## 7. 이관 순서 & 롤백
```
[개정 2026-07-28 — 실측 반영]
1) AWS 자격증명 ESO Secret 주입 + 최소권한 IAM + FQDN egress(bedrock) 추가(googleapis 유지)
2) ✅ 완료: 리전 모델 가용성 + inference profile 규약 확인(Claude=global./Nova=apac.)
3) ✅ 완료: 모델 PoC(품질·단가) — 550건 실측 → 판정 §1.1
4) **신규 기능부터 Bedrock 적용**: 리뷰 감정분석·구조화 추출 = `nova-micro`(서울)
5) **품질 개선 3종 선적용**(가드레일 질문합산 · 프롬프트 few-shot · temp 0.0) — 모델 무관 즉시 이득
6) 챗 refine **이전**(nova-micro 서울) — 카나리 후 확대. OCR·영상은 **Gemini 유지**(이미지 판독·URL 입력은 프롬프트로 해결 불가)
7) 오프라인(chat-insights·ner-dict) 후순위 전환
롤백: env 되돌림(즉시) — Gemini 경로 보존
```

### 7.1 카나리 방식·롤백 임계치 — **계측 확보 후 결정 (2026-07-28 보류)**

**현 상태**: `services/chat/app/observability.py`는 **구조화 로그만** 제공하고 **Prometheus 메트릭이 정의돼 있지 않다.**
`generator/gemini.py`의 fallback 지점 4곳(거절 skip · recommend-only skip · 타임아웃/API오류 · 근거대조 실패)은
코드에 존재하나 **계측되지 않아 비율을 측정할 수 없다.**

→ 따라서 **카나리 트래픽 비율과 롤백 임계치는 지금 확정하지 않는다.** 측정 수단 없이 정한 임계치는
근거 없는 숫자가 되고, 실제로는 판정도 불가능하기 때문이다.

**선행 조건 (이전 PR의 전제 작업)** — 최소 계측 3종을 먼저 추가한다:

| 지표 | 용도 |
|---|---|
| `chat_refine_total{backend}` | 시도 수(분모) |
| `chat_refine_fallback_total{backend,reason}` | `reason=timeout\|api_error\|ungrounded` — 품질 회귀 탐지 |
| `chat_refine_latency_seconds{backend}` | p50/p95 — 지연 회귀 탐지 |

기존 fallback 분기에 라벨만 붙이면 되므로 파이프라인 구조 변경은 없다.

**결정 절차**: 계측 배포 → **현행 Gemini 백엔드로 기준선(baseline) 수집** → 그 실데이터를 근거로
① 카나리 방식(전량 전환 vs 가중치 분할) ② 롤백 임계치를 확정한다.

**그때까지의 안전망**(이미 동작 중이므로 계측 부재가 위험으로 직결되지 않음):
- **template 자동 강등** — 타임아웃·API오류·근거대조 실패 시 template 출력으로 fallback → 사용자에게 오류가 노출되지 않음
- **env 즉시 롤백** — `GENERATOR_BACKEND` 되돌림(초 단위), Gemini 경로 보존
- **cost-break(#155)** — 월 예산 초과 시 template 자동 강등

> 참고(비확정): 캡스톤 트래픽은 DAU 500 × 6 refine/월 ≈ **하루 100건** 수준이라, 가중치 카나리(예 10%)는
> 하루 10건으로 **통계적 판단이 어려울 가능성**이 있다. 이 역시 기준선 수집 후 실데이터로 검증할 사항이다.

## 8. 명시적 비대상
| 항목 | 처리 | 근거 |
|---|---|---|
| video-recipe Bedrock | 제외(Gemini 유지) | 유튜브 URL 블로커(§6) |
| 온프렘 IRSA | 불가 → access key(ESO) | IRSA는 EKS 전용(§3.1) |
| 파이프라인 재작성 | 안 함 | 추가형 백엔드로 충분(§2) |

## 9. 정본 반영 제안 (인프라 협의 — 정본 수정은 담당자 몫)
1. **§6.1 egress**: Gemini FQDN → **하이브리드**(chat=bedrock-runtime, **ocr·youtube=googleapis 유지**). "외부 LLM=Gemini" 서술을 "chat=Bedrock · OCR·video=Gemini"로.
2. **§6.4 Secret**: AWS Bedrock 자격증명(온프렘 access key)을 ESO로 주입, EKS서 IRSA — 이미 §6.4 철학과 일치.
3. **예산**: 앱 캡 단가 갱신 + AWS Budgets(크레딧).

## 10. 확인/협의 항목 (이슈로)
1. **서울 리전 Bedrock 모델 가용성 + inference profile**(cross-region 필요 여부).
2. **AWS 자격증명 경로** — 백업 S3 자격증명 재사용 vs Bedrock 전용 IAM 신규 발급(최소권한 권장).
3. **FQDN egress 하이브리드** 확정(bedrock 추가 + googleapis 유지).
4. **예산** — AWS Budgets 설정 + 앱 캡 단가(`*_cost_per_call_won`) Bedrock 값.
5. **video-recipe 제외** 확정.
