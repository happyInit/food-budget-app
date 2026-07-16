# OCR 서비스 (영수증 인식)

> 독립 FastAPI 서비스 — 챗봇(`services/chat`)과 **동형 구조**. 설계: [`docs/ocr-service-design.md`](../../docs/ocr-service-design.md) · 방식 비교: [`docs/ocr-method-comparison.md`](../../docs/ocr-method-comparison.md)

영수증 이미지 → **Gemini Vision**(팀장 결정)으로 구조화 품목 추출 → 재료 NER로 item_master 매칭.
F5 냉장고 재고 + F17 식비 기록의 입구(`ai-spec.md §7`).

## 백엔드 담당: 붙이는 법 (챗봇과 동일)

**OCR 로직을 재구현할 필요 없다.** 이 서비스를 그대로 띄우고 Gateway/프록시로 라우팅만 하면 됨:

```
프론트 OcrUpload(007) → [Gateway] → OCR Service
  POST /api/pantry/ocr        (multipart image)     → 202 {job_id, status}
  GET  /api/pantry/ocr/{jobId}                       → 200 {status, items[], ...}
프론트 OcrResult(008): status 폴링 → 유저 검토·수정·확정(HITL)
확정 시(백엔드): ocr_receipt_item → pantry_item(재고) + expense(지출)
```

- API 경로가 `design/api-spec.md #16·17`과 일치 → **코드 변경 없이 프록시**(챗봇 `INTEGRATION.md`와 같은 패턴).
- 교체점은 `OcrBackend.parse(image)->ParsedReceipt` 하나 — 방식(Vision) 내부는 몰라도 됨.

## 담당 경계

| 구간 | 담당 |
|---|---|
| 엔드포인트·이미지 수신·job·OCR 백엔드·NER 매칭 | **이 서비스(AI)** |
| ⚠️ job 영속화(`ocr_receipt(_item)` PG) | **백엔드** — 현재 인메모리, `main.py` TODO 지점 교체 |
| HITL 확정 → `pantry_item`·`expense` 반영 | **백엔드** |
| 프론트 업로드/결과 화면 | 프론트(이미 존재) |

## 구조

```
app/
  main.py                       FastAPI: POST/GET /api/pantry/ocr (+ 인메모리 job)
  config.py                     OCR_BACKEND·GEMINI_*·PG*
  models.py                     API 스키마
  pipeline/
    process.py                  parse → 재료 NER 매칭(공통, 방식 무관)
    backend/
      base.py                   OcrBackend 계약 + ParsedReceipt/ParsedItem
      vision.py                 VisionBackend (Gemini Vision 단독)
      factory.py                OCR_BACKEND 선택
```

## 실행

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# .env: GEMINI_API_KEY=... (유료예외 — AGENTS.md 재승인 문서화 대상)
uvicorn app.main:app --port 8002        # 챗봇 8001과 구분
curl -F 'image=@receipt.jpg' localhost:8002/api/pantry/ocr
```

## 실측 검증 (2026-07-16 · Gemini Vision 실호출)

⚠️ **합성 영수증**으로 검증(실물 감열지 아님) — 파이프라인·추출 정상 확인용. 이미지 = Noto Sans KR로 렌더한 GS25 5품목 영수증(데모 API 종단 실측).

| 항목 | 결과 |
|---|---|
| 매장/일시/합계 | `GS25 역삼점` / `2026-07-16 19:32` / `16,300원` ✅ |
| 품목 추출 | 삼겹살(500g·8,900)·대파(1단·2,400)·두부(1모·1,500) **식재료** / 종량제봉투(20L·3,500) **비식품** ✅ |
| item_id | `None` (NER 미연동 stub — 설계상) |
| 지연 | 실측 ~18~41초 (flash-latest 비전) |
| 모델 | `gemini-flash-lite-latest` (실물 13장 벤치마크 최적 — `docs/ocr-model-benchmark.md`) |

**실측으로 발견·수정한 문제(“이렇게 실패하면 안돼”):**
- 🐛 타임아웃 20→**60초** — 비전 실측 ~40s라 20s가 "분석 실패"의 실제 원인이었음
- 🐛 빈 `reason` 버그 — `TimeoutError`는 `str()`이 빈값→"알 수 없음" → **타입명/친근메시지 + traceback 로깅**
- 🛡️ 일시 **503/429 과부하 자동 재시도**(최대 2회) — 단발 과부하로 통째 실패 방지
- ⚡ 큰 사진 **다운스케일**(Pillow, 최장 1600px) — 속도·비용↓
- 🐛 `is_food` 문자열 방어(`"false"`→True 오판 방지)

**남은 한계**: 합성 검증이라 **실물 감열지 정확도는 후속 PoC**(`ai-spec §7`). item_id는 NER 연동 후.

## 미완 / TODO
- `process._match_item_id`: 재료 NER 연동(챗봇 gazetteer matcher·CRF 재사용) — 현재 None(HITL 수동).
- `main.py` job 저장 인메모리 → `ocr_receipt(_item)` PG(백엔드).
- Vision 프롬프트·모델 실물 영수증 PoC 튜닝(`ai-spec §7`).
- 실패판정(`docs §4`: 파싱0건·합계불일치·NER매칭률·confidence) 및 폴백(보류).
