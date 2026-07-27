# Gemini → AWS Bedrock 전환 설계 (AI 모델 이관)

> **위치/관계**: 인프라 정본 [`docs/mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)를 보완하는 **AI 모델 이관 설계**. 정본은 수정하지 않는다 — 정합·협의 항목은 §10에 모아 이슈로 공유한다.
> **목적**: 개인 API키 기반 Gemini AI를 **AWS Bedrock(크레딧)** 으로 이관(k8s 환경). 단, **한계·성능저하가 없는 것만** 이관하고 블로커는 Gemini 유지(하이브리드).
> **검증**: 이 문서는 **두 번 교차검증**으로 작성 — ⓐ 현재 코드 상태(모든 Gemini 사용처·API 패턴·키·모델) ⓑ 인프라 이관 계획 정합(egress·인증·시크릿·리전·예산캡). 근거는 각 항목에 명시.

## 1. 전환 대상 판정 (검증①: 현재 코드 전수)
| 서비스 | Gemini 사용 | API 특징(근거) | Bedrock | 판정 |
|---|---|---|---|---|
| **챗 생성**(밥풀이) | 텍스트 생성 | `generator/gemini.py` `genai.Client`→`generate_content`, `GENERATOR_BACKEND` 팩토리 | Claude/Nova 텍스트 | ✅ **이관**(무열화, 품질 개선 여지) |
| **OCR vision** | 이미지→JSON | `backend/vision.py` `Part.from_bytes`(이미지)+`response_mime_type=json`+`thinking_config`, `OCR_BACKEND` 팩토리 | Claude vision + Converse tool-use | ✅ **이관** |
| **chat-insights**(리포트) | 오프라인 요약 | `ml/chat-insights/reports.py` `_gemini_narrative` (배치) | 텍스트 | ✅ 가능(**저우선**, 런타임 아님) |
| **ingredient-ner 사전** | 오프라인 1회성 | `ml/ingredient-ner/gemini_dict.py` ("런타임 없음") | 텍스트 | ✅ 가능(**저우선**) |
| 🔴 **video-recipe** | **유튜브 URL 직접분석** | `ml/video-recipe/extract.py` `file_data=FileData(file_uri=url)` | **불가** — URL 네이티브 fetch 없음 | ❌ **제외 = Gemini 유지** |

**전환 범위 결정**: **챗 생성·OCR vision**(런타임 핵심) + 오프라인 2건(후순위). **video-recipe만 Gemini 유지** → 최종 형태는 **하이브리드**.

## 2. 전환 방식 = 추가형 백엔드 (우리 서비스 구조에 맞춤)
두 서비스 모두 **교체가능 백엔드 팩토리 + 추상 인터페이스**가 이미 있어, Bedrock은 **새 구현체 추가**로 끝난다 — 파이프라인·프롬프트·캐싱 재사용, **env 토글로 즉시 롤백**.
| 서비스 | 인터페이스 | 추가 구현체 | 토글 | 롤백 |
|---|---|---|---|---|
| 챗 | `generator/base.py` `Generator` (`factory.py`: template\|gemini) | **`BedrockGenerator`** | `GENERATOR_BACKEND=bedrock` | env 되돌림 |
| OCR | `backend/base.py` `OcrBackend` (`factory.py`: vision\|mock) | **`BedrockVisionBackend`** | `OCR_BACKEND=vision_bedrock` | env 되돌림 |

→ **재작성 없음.** 카나리(일부 트래픽 env 전환) 후 검증, 문제 시 즉시 Gemini 복귀.

## 3. 인프라 정합 — 허점 차단 (검증②)

### 3.1 인증 — 🔴 온프렘 k8s는 IRSA 불가
- **온프렘(현 이관 대상)**: Bedrock 호출은 **AWS IAM access key/secret**로 인증 → **ESO Secret 주입**. 이는 **백업이 이미 AWS S3(ap-northeast-2)에 자격증명으로 접근하는 경로와 동일**(정본 §5.4·§6.3) → **신규 인증 메커니즘 아님, 기존 패턴 재사용**.
- **EKS 이관 시**: **IRSA로 전환** — 정본 §6.4 *"ESO 온프렘 백엔드 → AWS Secrets Manager + IRSA, CR은 보존"* 철학과 **정확히 일치**. `ExternalSecret` CR 그대로, 백엔드만 교체.
- **최소권한**: IAM 정책은 `bedrock:InvokeModel`(+`bedrock:InvokeModelWithResponseStream`)을 **특정 모델 ARN에만** 부여. 앱 SA에 백업 bucket 권한 안 주는 정본 §6.3 격리 원칙 준용.

### 3.2 Egress — 🔴 하이브리드 FQDN (video-recipe 붕괴 방지)
정본 §6.1 Cilium CNP FQDN egress(`chat·ocr·youtube → generativelanguage.googleapis.com`)를 **부분 변경**:
| 파드 | egress FQDN | 비고 |
|---|---|---|
| chat · ocr | **`bedrock-runtime.ap-northeast-2.amazonaws.com`** (신규) | Bedrock 데이터플레인 |
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

## 5. 모델 매핑 (PoC로 확정 — 열어둠)
| 용도 | Bedrock 후보 | 비고 |
|---|---|---|
| 챗 생성(현 flash-lite) | Claude Haiku(저비용) / Sonnet(품질) / Nova | PoC 품질·단가 비교 후 확정 |
| OCR vision(현 flash-lite) | Claude(vision) Haiku/Sonnet / Nova | 감열지 정확도 A/B |
- 정확한 모델·단가는 **PoC 후 확정**. 앱은 백엔드 뒤라 모델 교체가 설정값.

## 6. 전환 제외 근거 — video-recipe
`ml/video-recipe/extract.py`의 `types.Part(file_data=types.FileData(file_uri=url))` — **Gemini만 유튜브 URL을 직접 받아 영상을 분석**한다. Bedrock은 URL 네이티브 fetch가 없어 **영상 다운로드+프레임 업로드 파이프라인을 자체 구축**해야 하고, 그래도 품질·비용이 악화 = **성능저하 기능** → 이관 제외, **Gemini(`VIDEO_GEMINI_API_KEY`) 유지**. (상태성은 `video-recipe-ai.md §9` 참조)

## 7. 이관 순서 & 롤백
```
1) 백엔드 구현체 추가 (BedrockGenerator / BedrockVisionBackend) — 파이프라인 무변경
2) AWS 자격증명 ESO Secret 주입 + 최소권한 IAM + FQDN egress(bedrock) 추가(googleapis 유지)
3) 리전 모델 가용성 확인 → 모델 PoC(품질·단가)
4) env 카나리 전환(GENERATOR_BACKEND/OCR_BACKEND) → 검증 → 전면 전환
5) 오프라인(chat-insights·ner-dict) 후순위 전환
롤백: env 되돌림(즉시) — Gemini 경로 보존
```

## 8. 명시적 비대상
| 항목 | 처리 | 근거 |
|---|---|---|
| video-recipe Bedrock | 제외(Gemini 유지) | 유튜브 URL 블로커(§6) |
| 온프렘 IRSA | 불가 → access key(ESO) | IRSA는 EKS 전용(§3.1) |
| 파이프라인 재작성 | 안 함 | 추가형 백엔드로 충분(§2) |

## 9. 정본 반영 제안 (인프라 협의 — 정본 수정은 담당자 몫)
1. **§6.1 egress**: Gemini FQDN → **하이브리드**(chat·ocr=bedrock-runtime, youtube=googleapis 유지). "외부 LLM=Gemini" 서술을 "Bedrock(+video만 Gemini)"로.
2. **§6.4 Secret**: AWS Bedrock 자격증명(온프렘 access key)을 ESO로 주입, EKS서 IRSA — 이미 §6.4 철학과 일치.
3. **예산**: 앱 캡 단가 갱신 + AWS Budgets(크레딧).

## 10. 확인/협의 항목 (이슈로)
1. **서울 리전 Bedrock 모델 가용성 + inference profile**(cross-region 필요 여부).
2. **AWS 자격증명 경로** — 백업 S3 자격증명 재사용 vs Bedrock 전용 IAM 신규 발급(최소권한 권장).
3. **FQDN egress 하이브리드** 확정(bedrock 추가 + googleapis 유지).
4. **예산** — AWS Budgets 설정 + 앱 캡 단가(`*_cost_per_call_won`) Bedrock 값.
5. **video-recipe 제외** 확정.
