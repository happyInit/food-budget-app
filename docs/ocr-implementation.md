# OCR 서비스 구현 설명 (내부 동작·기술선택·구현 방법)

> **작성:** 건우 (AI 담당) · 2026-07-16
> **대상 독자:** 리뷰어 · 백엔드 담당 · 포트폴리오
> **코드:** `services/ocr/` · **설계:** [`ocr-service-design.md`](ocr-service-design.md) · **방식선택:** [`ocr-method-comparison.md`](ocr-method-comparison.md)

이 문서는 "**무엇을**"(설계)·"**왜 이 방식을**"(비교) 문서와 달리, **실제 코드가 내부에서 어떻게 도는지 + 각 기술을 왜/어떻게 썼는지**를 설명한다.

---

## 1. 내부 동작 (요청 → 응답 종단)

```
POST /api/pantry/ocr (영수증 이미지)
  └─ main._accept: 크기 검증 → job_id 발급 → 인메모리 job=PENDING → 백그라운드 태스크 → 202 반환
        └─ process.process_image(image, backend)
              ├─ backend.parse(image)               # VisionBackend (아래 2·4)
              │     ├─ _mime(image)                 # PNG/JPEG 시그니처 판별
              │     ├─ Gemini 멀티모달 호출          # 이미지+시스템프롬프트 → JSON 텍스트
              │     └─ _to_receipt(json)            # 안전 파싱 → ParsedReceipt(dataclass)
              │           ├─ _dec: '12,400' → Decimal(12400)   # 금액 정밀
              │           └─ _dt : '2026-07-16 19:32:00' → datetime
              └─ 각 식품 item.name → _match_item_id # 재료 NER(현재 stub → None)
GET /api/pantry/ocr/{job_id} → OcrStatusResponse{status, store, total, items[], ...}
```

**실측(목 JSON 검증):** `'삼겹살500g 8,900'` → `name=삼겹살, price=Decimal(8900), is_food=True`; `'종량제봉투…'` → `is_food=False`(비재료 제외); `'판독불가라인'` → `name=None`(날조 없이 원문만). 금액은 `Decimal`, 시각은 `datetime`으로 타입 정규화됨.

## 2. 핵심 기술 선택과 이유 (구현 레벨)

| 기술 | 왜 이걸 썼나 |
|---|---|
| **Gemini Vision(멀티모달)** | 영수증 OCR = 탐지+인식+**레이아웃 파싱**(품목↔가격 2D 연결)인데, VLM은 이 4단계를 **한 호출**로 처리하고 **구조화 JSON**을 바로 준다 → 좌표 파서(Tesseract 시 1.5~2주)가 통째로 불필요. 감열지·한국어 정확도도 최상(비교문서 §2). 팀장 결정으로 단독 채택 |
| **`response_mime_type="application/json"` + 프롬프트 스키마** | 자유텍스트를 정규식으로 긁는 취약한 파싱 대신 **모델이 JSON을 강제 출력** → `json.loads` 한 번. temperature=0으로 결정성↑ |
| **교체가능 `OcrBackend` 프로토콜** | 챗봇 `EXTRACTOR_BACKEND` 패턴. 방식(Vision)이 바뀌어도 process·NER·HTTP 불변. PoC로 Tesseract/폴백 붙일 자리를 **무비용**으로 열어둠 |
| **FastAPI + async job(202+폴링)** | Vision은 네트워크 왕복 수초 → 동기 응답이면 타임아웃. 비동기 접수 후 상태 폴링(api-spec #16·17). 챗봇과 동형이라 백엔드가 **같은 방식으로 프록시** |
| **`Decimal`(금액)·`datetime`(시각)** | 돈은 float 반올림 오차 금물 → `Decimal`. 문자열 '12,400'을 `_dec`가 콤마 제거 후 변환 |
| **dataclass(내부) vs Pydantic(경계)** | 내부 도메인 모델 `ParsedReceipt`는 가벼운 dataclass, **API 경계**만 Pydantic(`models.py`)으로 검증·직렬화 → 관심사 분리 |
| **`item_id`는 백엔드가 아니라 파이프라인이 채움** | NER은 4소비처 공용 엔진(ai-spec §1). OCR 백엔드는 품목코드를 몰라도 되게 분리 — 방식 무관성 유지 |
| **챗봇과 별도 Gemini API 키** | 같은 키로도 되지만, OCR(비전·장당 과금)과 챗봇(refine) **비용을 서비스 단위로 명확히 구분·추적**하려 키 분리. 서비스별 `.env`라 코드 변경 없이 값만 다르게 → 사용량·청구 독립 모니터링·상한 관리, 유료예외 거버넌스(AGENTS.md)에 부합 |

## 3. 구현 과정 (결정과 순서)

1. **경계부터**: `OcrBackend.parse(image)->ParsedReceipt` 계약(`base.py`)을 먼저 확정 — 이게 AI↔백엔드 유일 접점.
2. **출력 형태 통일**: 백엔드가 raw text가 아니라 **구조화 품목(ParsedReceipt)**을 반환하게 설계. Vision은 JSON을 그대로 매핑, (향후) Tesseract는 좌표 파서를 **구현체 내부**에 두면 계약은 동일.
3. **VisionBackend 구현**: 시스템 프롬프트로 JSON 스키마 강제 + 안전 파서(`_to_receipt`/`_dec`/`_dt`) + mime 판별. 지연 import로 백엔드 미사용 시 google-genai 의존 불필요.
4. **공통 파이프라인**: `process_image`가 parse 후 식품 품목만 NER 매칭. NER은 **stub**(현재 None → HITL 수동) — 챗봇 gazetteer/CRF 재사용이 연동 지점.
5. **HTTP 껍데기**: 챗봇과 동형 FastAPI. job은 **인메모리 스켈레톤**(프로덕션은 `ocr_receipt` PG — 백엔드 담당).

## 4. 어떻게 구현했나 (코드 포인트)

- **프롬프트 설계**(`vision.py _SYSTEM`): 매장·일시·합계·품목(raw_text/name/quantity/price/is_food) JSON만 출력, **근거 없으면 null·날조 금지**, 판독불가 시 raw_text만. → 환각 억제 + 후처리 최소.
- **안전 타입 변환**: `_dec`(콤마 제거+Decimal, 실패 시 None), `_dt`(3가지 포맷 시도), `_mime`(PNG 시그니처로 판별). 모델이 이상값을 줘도 **None으로 흡수**(크래시 방지).
- **오류 처리**: JSON 파싱 실패→빈 dict, job 예외→`status=FAILED, reason`(서비스는 유지), 빈/과대 이미지→400/413.
- **비재료 필터**: `is_food=false`(봉투·할인·포인트)는 NER·재고에서 제외 대상으로 표시(스키마 `ocr_receipt_item.is_food`).
- **graceful degradation**: 판독 불가 라인도 버리지 않고 raw_text로 남겨 **HITL에서 사람이 보정**(자동수렴 불가 전제, design.md).

## 5. 검증 상태 / 한계

- ✅ 파싱 매핑·타입정규화·라우트 등록 유닛 검증(목 JSON).
- ⏳ **실물 영수증 PoC 미실행** — Gemini 프롬프트·모델(`gemini-flash-latest`)은 실물 감열지로 튜닝 필요(ai-spec §7).
- ⏳ NER 매칭 stub(item_id=None), job 인메모리(PG 미연동), 실패판정·폴백 보류.
- ⚠️ Vision = 유료 API → AGENTS.md 재승인 문서화 필요(팀장 구두 승인).
