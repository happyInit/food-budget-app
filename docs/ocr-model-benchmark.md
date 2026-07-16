# OCR 모델·방식 실측 벤치마크 (flash-lite / flash-3.5 / pro / Tesseract)

> **작성:** 건우 (AI 담당) · 2026-07-16
> **목적:** OCR 방식·모델 선택을 **자체 실측 데이터**로 검증(팀 요구). 상단=요약·결론, 하단=전체 기록.
> **지표:** 성공률(합계정합=품목가격 합≈영수증 합계) · 소요시간 · 비용/장. 유료 티어.
> **관련:** `ocr-method-comparison.md`(방식 비교) · `ocr-devlog.md`(개발 로그)

---

# ■ 요약·결론 (상단)

## 최종 권고: **`gemini-flash-lite-latest` 채택** (현재 `flash-latest`=3.5에서 전환)

### 핵심 비교 — 실물 영수증 13장

| 방식 | 성공률(합계정합) | 평균 시간 | 평균 비용/장 | 총비용(13장) | 신뢰성 |
|---|---|---|---|---|---|
| **flash-lite** ⭐ | **12/13 (92%)** | **2.8s** | **0.45원** | **5.8원** | 🟢 에러 0 |
| flash-3.5 (thinking OFF) | 8/13 (61%) | 2.9s | 2.50원 | 22.5원 | 🔴 JSON 에러 4 |
| flash-3.5 (thinking ON) | 10/13 (76%) | 7.3s | 7.15원 | 78.6원 | 🔴 JSON 에러 2 |
| pro (thinking ON, 하드 5장) | 3/5 | 4~28s | **20.75원** | 103.7원(5장) | 🔴 JSON 에러 + 느림 |
| Tesseract (kor) | **0 (구조화 불가)** | 0.6s | 0원 | 0원 | 🔴 raw text만 |

### 왜 flash-lite가 "가장 합리적 지점"인가
1. **Pareto 지배** — 성공률·비용·속도·안정성 **모든 축에서 우위**. 트레이드오프가 아니라 **명백한 최적**(보통 "싼 모델=낮은 정확도"인데 여기선 반대).
2. **작업 성격** — 영수증 파싱은 **인식·추출**(추론 아님). pro의 추론 강점은 안 쓰이고 thinking 토큰이 **비용·지연만 폭증**(receipt_0002: 28.5s·74원 쓰고도 실패). 큰 모델일수록 JSON 스키마 이탈(파싱 에러) 경향, lite는 단순·일관 → 에러 0.
3. **실서비스 비용** — DAU 500×1영수증/일 월비용: **lite ~7천원 / flash-3.5 ~4만원 / pro ~30만원**. lite만 현실성.
4. **HITL 안전망** — 92% 자동 + 8% 사람 보정이면 충분. 100% 위해 46배(pro) 쓸 이유 없음.

### 부가 최적화 (모든 Vision 공통)
- **thinking OFF**(`thinking_budget=0`): 비용 63%↓·지연 16배↓·정확도 동일(합성 실측: 4.55→1.70원, 40→2.5s). ⚠️ 단 **pro는 thinking_budget=0 거부**(400 "Budget 0 invalid") → pro는 thinking 필수라 더 비쌈.
- 이미지 다운스케일(1600px)·503/429 재시도·타임아웃 60s.

### 정직한 한계
- **성공지표(합계정합)는 프록시** — 1~2품목 영수증은 쉽게 통과, `total=None`이면 품목 맞아도 실패 처리 → **절대% 는 물렁**. 단 **상대 순위(lite 에러0 vs 나머지 다수 에러)는 견고**.
- 13장 소표본 · 품목명/가격 개별 정오는 미검증.
- `receipt_0002`(17품목)는 **모든 모델이 총액 미추출**(총액이 이미지 밖/잘림 = 하드케이스, 모델 무관).
- Tesseract는 raw text 12/13 확보하나 **구조화(품목·가격) 불가** → 별도 파서(1.5~2주) 없이는 실사용 불가.

---

# ■ 전체 기록 (하단)

## T1. 합성 영수증 — Tesseract vs Vision (정답 12필드)
합성 이미지 2종([clean](assets/ocr/receipt_synth_clean.jpg)/[degraded](assets/ocr/receipt_synth_degraded.jpg), Noto Sans KR):

| 이미지 | Tesseract | Vision(thinking OFF) |
|---|---|---|
| 깨끗 | 10/12 · 0.2s · raw(구조X, GS25→"6525" 오탐) | 11/12 · 2.5s · 구조화 4품목 |
| 저품질 | **0/12 · 빈 출력** | 11/12 · 2.1s · 구조화 4품목 |

## T2. 합성 — Gemini 모델 비교 (thinking OFF, 정답 12필드)
| 모델 | 깨끗 | 저품질 | 지연 | 비용/장 |
|---|---|---|---|---|
| flash-lite-latest | 11/12 | 11/12 | 1.6s | 0.37원 |
| flash-latest(3.5) | 11/12 | 11/12 | 2.3s | 1.70원 |
| pro-latest | 11/12 | 11/12 | 4.1s | 6.87원 |
→ 합성은 너무 쉬워 **정확도 변별 안 됨**(전부 11/12) → 실물 필요(T4).
- (폐기 확인) `gemini-2.5-*` = 404 "신규 사용자 불가" → 현재세대(3.x)만 사용가능.

## T3. thinking 토큰 영향 (합성, 실토큰)
| 설정 | in / out / thoughts | 지연 | 비용 |
|---|---|---|---|
| thinking 기본 | 1311 / 334 / **828** | 24~41s | 4.55원 |
| thinking OFF | 1311 / 334 / 0 | 2.5s | 1.70원 |
→ thinking 토큰(출력요율 과금)이 비용·지연 주범. OCR엔 불필요 → OFF 채택.

## T4. 실물 13장 — 4방식 (thinking OFF, 성공=합계정합)
raw 로그(발췌):
```
receipt_0001 lite 2.2s 0.25원 items=1 total=2000 ok=True | flash-3.5 1.8s 1.04원 ok=True | pro ERR(budget0)
receipt_0002 lite 4.9s 0.92원 items=17 total=None ok=False | flash-3.5 5.4s 5.91원 items=17 total=None ok=False
receipt_0003 lite 2.8s 0.51원 items=6 total=10460 ok=True | flash-3.5 3.3s 2.63원 ok=True
receipt_0004 lite 3.4s 0.65원 items=12 total=27720 ok=True | flash-3.5 ERR(JSONDecode)
receipt_0005 lite 5.4s 0.53원 items=9 total=21900 ok=True | flash-3.5 3.2s 3.15원 ok=True
receipt_0006 lite 2.6s 0.47원 items=6 total=61700 ok=True | flash-3.5 2.7s 2.34원 ok=True
receipt_0007 lite 2.4s 0.40원 items=5 total=27900 ok=True | flash-3.5 2.9s 2.85원 items=10 ok=True
receipt_0008 lite 1.9s 0.29원 items=2 total=1800 ok=True | flash-3.5 ERR(JSONDecode)
receipt_0009 lite 2.8s 0.49원 items=6 total=16050 ok=True | flash-3.5 ERR(JSONDecode)
receipt_0010 lite 2.1s 0.43원 items=6 total=8560 ok=True | flash-3.5 ERR(JSONDecode)
receipt_0011 lite 2.2s 0.30원 items=2 total=80000 ok=True | flash-3.5 2.4s 1.31원 ok=True
receipt_0012 lite 1.8s 0.30원 items=2 total=8600 ok=True | flash-3.5 2.3s 2.16원 items=6 ok=True
receipt_0013 lite 1.7s 0.27원 items=1 total=4900 ok=True | flash-3.5 1.7s 1.08원 ok=True
집계: flash-lite 12/13(92%)·2.8s·0.45원·총5.8원·에러0 | flash-3.5 8/13(61%)·2.9s·2.50원·총22.5원·JSON에러4
pro: 0/13 — thinking_budget=0 거부(400 "Budget 0 invalid")=하네스 설정 문제 → T5 재측정 | tesseract: raw 12/13, 구조화 0
```

## T5. pro 재측정 (thinking ON, 하드 5장)
```
receipt_0002 pro 28.5s 73.99원 items=17 total=None thoughts=3626 ok=False   ← 74원 쓰고도 실패
receipt_0004 pro 10.6s 15.94원 items=12 total=27720 ok=True
receipt_0008 pro  4.4s  5.21원 items=2  total=1800  ok=True
receipt_0009 pro ERR(JSONDecode)                                            ← flash-3.5와 동일 실패
receipt_0010 pro  4.7s  8.59원 items=6  total=8560  ok=True
집계: pro 3/5 성공 · 총103.7원 · 장당 평균 20.75원
```
→ pro는 **46배 비싸면서(20.75 vs 0.45원) 더 정확하지도 않음**(하드케이스 동일 실패). 채택 근거 없음.

## T6. flash-3.5 thinking ON (13장)
가설 검증: thinking ON이 flash-3.5의 JSON 에러를 없애고 성공률을 lite 위로 올리는지.
```
receipt_0001 5.6s 4.50원 items=1 total=2000 thoughts=1012 ok=True
receipt_0002 13.3s 14.83원 items=17 total=None thoughts=2569 ok=False
receipt_0003 9.1s 8.67원 items=6 total=10460 thoughts=1833 ok=True
receipt_0004 10.0s 10.25원 items=12 total=27720 thoughts=1820 ok=True   ← (OFF에선 JSON에러였음 → ON에서 회복)
receipt_0005 ERR JSONDecodeError (Extra data)                          ← 여전히 에러
receipt_0006 7.8s 7.52원 ok=True | receipt_0007 6.0s 6.23원 ok=True
receipt_0008 4.6s 4.18원 ok=True | receipt_0009 6.9s 6.77원 ok=True
receipt_0010 8.0s 8.10원 ok=True | receipt_0011 3.7s 3.27원 ok=True
receipt_0012 ERR JSONDecodeError (Expecting ',')                        ← 여전히 에러
receipt_0013 4.8s 4.32원 ok=True
집계: 10/13(76%) · 평균 7.3s · 장당 7.15원 · 총 78.6원 · JSON에러 2 · thoughts 567~2626/장
```
**결론**: thinking ON이 성공률을 **61%→76%로 개선**(일부 JSON 에러 회복)하나 **여전히 lite(92%) 미달** + **비용 16배(7.15 vs 0.45원)·지연 2.6배**. → **thinking으로도 lite를 못 넘음 = lite 채택이 최적임을 재확인.**
