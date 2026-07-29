# GCP Vertex AI 이전 계획서

> 작성: 건우(AI) · 2026-07-29
> 대상: **영수증 OCR · 영상→레시피** (Google AI API 키 → **Vertex AI**)
> 관련: [`ai-model-selection-final.md`](./ai-model-selection-final.md)(모델 선정 실측) · [`bedrock-migration-design.md`](./bedrock-migration-design.md)(AWS 이관) · [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)(인프라 정본)

---

## 0. 요약 — 무엇을·왜·언제

| 항목 | 내용 |
|---|---|
| **이전 대상** | OCR vision(`services/ocr`) · 영상→레시피(`services/video`) **2개 지점만** |
| **이전 내용** | 백엔드 전환 — Google AI API(개인 키) → **Vertex AI**(팀 GCP 프로젝트) |
| **모델 변경** | **없음**. 동일 `gemini-3.5-flash-lite` — 엔드포인트·인증만 바뀐다 |
| **실행 시점** | **Phase 2(EKS 이전, ~2026-08-26)** — 온프렘 단계에서 하지 않는다(§2) |
| **핵심 명분** | ① 개인 지출 제거 ② **키리스 크로스클라우드 인증**(학습·포트폴리오) ③ (선택)데이터 레지던시 |

> ⚠️ **비용 절감은 명분이 아니다.** Vertex 요율은 글로벌 엔드포인트에서 Google AI API와 **동일**하고,
> **리전 엔드포인트는 2026-07-01부터 약 10% 할증**이다. GCP 크레딧도 없다.
> 즉 이 이전의 가치는 **"싸진다"가 아니라 "누가 내느냐 + 어떻게 인증하느냐"** 다.

---

## 1. 왜 이 2개만인가 (범위 확정)

코드 전수 조사 결과 `genai.Client(api_key=…)` 사용처는 **6곳**이다.

| # | 위치 | 용도 | GCP 이전? | 근거 |
|---|---|---|---|---|
| 1 | `services/ocr/…/vision.py:149` | 영수증 이미지→JSON | ✅ **대상** | Bedrock 이관 불가(한글 판독 실패). 영수증=개인정보 → 레지던시 명분 |
| 2 | `ml/video-recipe/extract.py:55` | 유튜브 URL→레시피 | ✅ **대상** | Bedrock에 URL 입력 자체가 없음 |
| 3 | `services/chat/…/generator/gemini.py:23` | 챗 refine | ❌ 제외 | **Bedrock(nova-micro)로 이전 확정** — GCP로 보내면 결정과 충돌 |
| 4 | `ml/chat-insights/reports.py:57` | 리포트 서술 | ⬜ 보류 | 오프라인 배치·저빈도. 모델 미확정(실측 대기) |
| 5 | `ml/ingredient-ner/gemini_dict.py:60` | 사전 생성 | ⬜ 제외 | **오프라인 1회성** — 런타임 아님 |
| 6 | `services/chat/tools/build_alias.py:87` | 별칭 생성 | ⬜ 제외 | 동일(오프라인 도구) |

→ **런타임 상시 경로 중 Gemini가 남는 것은 1·2뿐**이고, 그 둘이 이전 대상이다.

---

## 2. 왜 지금(온프렘)이 아니라 EKS 이후인가 — 가장 중요한 판단

### 2.1 온프렘에서는 WIF가 **구조적으로 막힌다**

클러스터 실측(2026-07-29, `192.168.0.17`):

```
issuer   : https://kubernetes.default.svc.cluster.local   ← 클러스터 내부 전용 이름
jwks_uri : https://192.168.0.17:6443/openid/v1/jwks       ← 사설 IP
```

Workload Identity Federation은 **Google이 인터넷에서 issuer의 JWKS를 가져와 토큰 서명을 검증**한다.
지금 issuer는 내부 DNS·사설 IP라 **Google에서 도달 불가 → WIF 등록 자체가 실패**한다.

해결하려면 셋 중 하나인데 전부 클러스터 인증 근간을 건드린다:
1. `--service-account-issuer`를 공개 HTTPS로 변경 + JWKS 공개 게시 → **API 서버 재시작·기존 토큰 무효화 위험**
2. OIDC 프록시 외부 노출 → 공인 IP·도메인·TLS 필요
3. 서비스계정 **키 파일** 사용 → 간단하지만 **"키리스"라는 목적이 사라짐**

### 2.2 EKS에서는 **공짜로 해결된다**

EKS는 **공개 OIDC issuer**(`https://oidc.eks.ap-northeast-2.amazonaws.com/id/…`)를 AWS가 제공한다.
Google이 JWKS를 가져올 수 있으므로 **WIF가 그대로 동작**한다.

| 시점 | AWS 인증 | GCP 인증 |
|---|---|---|
| 온프렘 k8s(~8/5) | ESO 정적 키(**IRSA 불가** — EKS 전용) | **WIF 불가**(사설 issuer) |
| **EKS(~8/26)** | **IRSA** ✅ | **WIF** ✅ |

### 2.3 결론

온프렘에서 issuer를 바꾸는 작업은 **수명 3주짜리**이고, 8/26 EKS 이전 시 **통째로 버려진다**.
인프라 정본의 원칙 *"이식성 > 온프렘 최적화"*(§migration_plan L15)와 정면으로 어긋난다.

> **→ GCP 이전은 EKS 이전과 같은 단계에서 수행한다.** 그때 IRSA(AWS) + WIF(GCP)가 동시에 성립해
> **"정적 키 없는 크로스클라우드 인증"** 이라는 목표가 온전히 달성된다.

---

## 3. 코드 변경 — 생각보다 작다

`google-genai`는 **통합 SDK**로 두 백엔드를 모두 지원한다. 전환은 **클라이언트 생성 한 줄**이다.

```python
# 현재 (Google AI API · 개인 키)
client = genai.Client(api_key=KEY)

# Vertex AI (팀 GCP · ADC)
client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
```

`generate_content` · `types.Part` · `FileData` · 프롬프트는 **전부 그대로**다.

### 3.1 백엔드 토글 방식 (롤백 가능하게)

`OCR_BACKEND`·`GENERATOR_BACKEND`와 동일한 **팩토리 + env 토글** 패턴을 쓴다.
**현행 Google AI API 경로를 지우지 않는다** — 되돌아올 수 없는 마이그레이션을 만들지 않기 위해서다.

| 서비스 | 신규 env | 값 |
|---|---|---|
| OCR | `GEMINI_BACKEND` | `api_key`(기본) \| `vertex` |
| video | `VIDEO_GEMINI_BACKEND` | `api_key`(기본) \| `vertex` |
| 공통 | `GCP_PROJECT_ID` · `GCP_LOCATION` | Vertex 모드에서만 사용 |

### 3.2 호환성 확인이 필요한 파라미터 ⚠️

OCR은 아래를 쓴다(`vision.py:157`) — **Vertex에서 동일 동작인지 PoC로 확인해야 한다**:

| 파라미터 | 확인 포인트 |
|---|---|
| `response_mime_type="application/json"` | Vertex에서도 JSON 강제가 되는가 |
| `system_instruction` | 지원 형식 동일한가 |
| `thinking_config(thinking_budget)` | **가장 위험** — 이 인자 거부로 OCR이 전량 실패한 사고 이력이 있다(PR #272). Vertex에서 인자명·허용값이 다를 수 있음 |
| `temperature=0.0` | 동일 |

video는 `FileData(file_uri=youtube_url)`를 쓴다 — **Vertex도 YouTube URL을 지원**하나 제약이 있다(§4.2).

---

## 4. 제약·리스크 (빠짐없이)

### 4.1 비용 — 절감 없음, 오히려 증가 가능

| 구성 | 요율 |
|---|---|
| 현행 Google AI API | 기준 |
| Vertex **글로벌** 엔드포인트 | **동일** |
| Vertex **리전**(서울 등) | **약 +10%**(2026-07-01부터) |

- **GCP 크레딧 없음** → 팀 실비 결제
- OCR·video는 AI 비용의 **79.4%**(MAU 50만 기준 월 363만원) → 10% 할증이면 **월 +36만원**
- **→ 레지던시가 요구사항이 아니면 글로벌 엔드포인트를 쓴다**(할증 회피)

### 4.2 YouTube URL 제약 (video 전용)

Vertex 공식 제약:
- **공개 영상이거나 요청 계정 소유** — 비공개·연령제한 영상은 실패
- **요청당 YouTube URL 1개** — 현 파이프라인은 1건씩이라 무관
- 파일 크기·프레임 샘플링(1fps) 제약 존재

→ 현행 Google AI API와 유사하나, **거부 사유·에러 코드가 다를 수 있어** 폴백 문구 검증 필요.

### 4.3 서울 리전 quota/403 리스크

2026-05 기준 **Vertex 서울(`asia-northeast3`)에서 간헐적 403/quota-capacity 오류** 보고가 있고 미해결이다(유료 계정·정상 IAM에도 발생).
- 레지던시가 필요 없으면 **글로벌 엔드포인트**가 오히려 안정적(Google이 리전 용량을 내부 흡수)
- 레지던시가 필요하면 서울을 쓰되 **폴백 순서(서울 → 도쿄 → 글로벌)** 를 설계해야 함
- ⚠️ 도쿄 폴백은 **데이터가 일본으로 나간다** — 레지던시 명분과 자기모순이므로 팀 합의 필요

### 4.4 인증 경로가 하나 더 늘어난다

| 경로 | 온프렘 | EKS |
|---|---|---|
| AWS(Bedrock) | ESO 정적 키 | **IRSA** |
| **GCP(Vertex)** | (미실시) | **WIF** |

- ESO가 **멀티백엔드**(AWS Secrets Manager + GCP Secret Manager)가 되어 관리 대상이 늘어남
- Cilium FQDN egress에 **Vertex 엔드포인트 추가** 필요
  - 🔴 **`generativelanguage.googleapis.com`을 제거하면 안 된다** — 오프라인 도구(#5·#6)와 폴백 경로가 죽는다

### 4.5 3-클라우드 운영 부담

온프렘 + AWS + GCP. 청구·IAM·관측이 셋으로 갈린다.
**5인 캡스톤 기준으로는 실제 부담**이며, 이를 감수하는 근거는 **학습 가치**다(§0 명분 ②).

### 4.6 품질 재검증 필요

모델은 같지만 **엔드포인트가 다르면 동작이 미세하게 다를 수 있다**.
OCR은 실물 13장 벤치마크가 있으므로 **동일 세트로 재측정**해 회귀 여부를 확인한다(§5.2).

---

## 5. 실행 계획

### 5.1 선행 조건 (전부 충족돼야 시작)

| # | 조건 | 담당 | 상태 |
|---|---|---|---|
| 1 | GCP 프로젝트 생성 + 결제 계정 연결 | 팀장 | ⬜ |
| 2 | Vertex AI API 사용 설정 | 팀장 | ⬜ |
| 3 | EKS 이전 완료(공개 OIDC issuer 확보) | 인프라 | ⬜ (~8/26) |
| 4 | 레지던시 요구사항 확정(서울 vs 글로벌) | 팀 | ⬜ |

### 5.2 PoC (반나절 — 코드 변경 전)

**목적**: "동작한다"가 아니라 **"기존과 동등하다"**를 증명한다.

| # | 검증 | 합격 기준 |
|---|---|---|
| 1 | Vertex 인증·호출 성립 | `generate_content` 성공 |
| 2 | **OCR 실물 13장 재측정** | 합계정합 **12/13 유지**(현행 동등) |
| 3 | `thinking_config` 호환성 | 거부되지 않거나 폴백 경로 동작 |
| 4 | `response_mime_type` JSON 강제 | 파싱 실패 0 |
| 5 | video 유튜브 URL 1건 | 추출 성공 + 스키마 동일 |
| 6 | 리전 quota | 서울 403 발생 여부(§4.3) |
| 7 | 지연·단가 | 현행 대비 기록(할증 실측) |

**하나라도 미달이면 이전을 보류**하고 원인을 문서화한다.

### 5.3 구현 순서

```
1) GCP 프로젝트·Vertex 활성화 + 서비스계정(최소권한: aiplatform.user)
2) PoC(§5.2) — 통과 못 하면 여기서 중단
3) 코드: 백엔드 팩토리 + vertex 구현체 추가 (기존 api_key 경로 보존)
4) EKS에서 WIF 연동 — GCP 서비스계정 ↔ k8s ServiceAccount 연합
5) Cilium FQDN에 Vertex 엔드포인트 추가 (googleapis 유지)
6) env 카나리: 한 서비스(OCR)만 vertex로 → 관측 → 확대
7) 롤백: env 되돌림(즉시). api_key 경로는 계속 살려둔다
```

### 5.4 롤백 기준

| 신호 | 조치 |
|---|---|
| OCR 합계정합이 12/13 미만으로 하락 | 즉시 `api_key`로 롤백 |
| 403/quota 발생률 > 1% | 리전 변경 또는 롤백 |
| p95 지연이 현행 대비 2배 초과 | 롤백 후 원인 분석 |

---

## 6. 이전 후 최종 구도

```
온프렘/EKS 워크로드
├─ chat refine · 감정분류 · 구조화  → AWS Bedrock(nova-micro, 서울)   [IRSA]
├─ OCR vision · 영상→레시피        → GCP Vertex AI(Gemini)            [WIF]
├─ NER · 랭킹 · 최저가 이상탐지     → 자체 모델(온프렘)                 [LLM 없음]
└─ 저장/백업                       → AWS S3
```

**억지 하이브리드가 아닌 근거**: 각 모델이 **네이티브 클라우드**에 있다. Claude/Nova는 Bedrock에만,
Gemini는 Google에만 있다. 게다가 실측이 이를 뒷받침한다 — **Nova는 한글 OCR 실패, Gemini는 성공**.
비용이나 정치가 아니라 **모델 가용성이 자연히 가른 분할**이다.

---

## 7. 결정 대기 항목

| # | 질문 | 영향 |
|---|---|---|
| 1 | 영수증 데이터의 **국내 레지던시가 요구사항인가?** | 예 → 서울 리전(+10%, quota 리스크) / 아니오 → 글로벌(할증 없음) |
| 2 | GCP 실비 결제를 감수하는가? | 크레딧 없음 — 월 규모는 §4.1 |
| 3 | 3-클라우드 운영 부담을 학습 가치로 정당화하는가? | 이 계획의 근본 명분 |

> **1번이 이 계획의 성격을 가른다.** 요구사항이면 Vertex 전환은 **정당한 필수**이고,
> 아니면 **학습 목적의 선택**이다. 둘 다 유효하나 근거가 다르므로 팀에 명시해야 한다.
