# OCR 영수증 서비스 — 백엔드 연동 가이드 (INTEGRATION)

> **소유:** 건우(AI) · **상태:** 엔진·분류 완성/실측, 미커밋 · **설계 SoT:** `docs/ocr-nonfood-handling-proposal.md §7`
> 이 문서는 **백엔드가 가져다 붙일 접점**만 다룬다. 내부 분류 로직 근거는 §7 참조.

## 1. 무엇인가
독립 FastAPI 서비스(챗봇과 동형). 영수증 이미지 → Gemini Vision 추출 → **분류 캐스케이드**로 품목별
`category·storage·in_expense·needs_review·item_id`를 채워 반환한다. **확정(HITL)·저장·재고/지출 반영은 백엔드 구간.**

## 2. API 계약
| | |
|---|---|
| **POST** `/api/pantry/ocr` | multipart/form-data, 필드명 **`image`**(파일). → **202** `{job_id, status:"PENDING"}` |
| **GET** `/api/pantry/ocr/{job_id}` | → `OcrStatusResponse`(아래). 완료 전엔 `status:"PENDING"` |
| GET `/` | 데모 UI · GET `/health` → `{status,backend}` |

비동기(202 접수 → 폴링). ⚠️ **현재 job 저장 = 인메모리 `_JOBS`(스켈레톤).** 프로덕션은 백엔드가
**BackgroundTasks/큐 + `pantry.ocr_receipt` PENDING row**로 교체(main.py `_accept` TODO 주석).

### OcrStatusResponse
```
status: PENDING|DONE|FAILED,  store, purchased_at, total_amount, backend, reason,
items: [ OcrItemOut ]
```
### OcrItemOut — 필드 계약 (백엔드 라우팅 기준)
| 필드 | 의미 | 백엔드 처리 |
|---|---|---|
| `raw_text` | OCR 원문 라인(감사 추적, **불변**) | 표시·로그 |
| `name` | 정리된 품목명 | 표시·매칭 |
| `item_id` | item_master 표준코드(DB연결 시). 미매칭=`null` | pantry/집계 조인 |
| `quantity`,`price` | 수량, 금액(숫자) | `price`는 재정렬 반영값(§4) |
| `is_food` | OCR 1차 플래그(봉투/할인=false) | 참고용 |
| **`category`** | **식재료/가공식품/비식품/조정/null(미해결)** | **핵심 라우팅 키(§3)** |
| **`storage`** | FRIDGE/FREEZER/ROOM / null | pantry 칸 |
| **`in_expense`** | 식비 대상 여부(참고) | 식비는 §3.5 공식이 정본 |
| **`needs_review`** | 저신뢰·미해결·오정렬 의심 | **HITL 하이라이트("확인")** |
| `confirmed` | 항상 false(초안) | HITL 확정 시 백엔드가 true |

## 3. 품목 라우팅 (§7.3)
- **식재료** → `item_id` 매핑(없으면 **후보 제안 → Taylor 검토큐**, 무분별 insert 금지) + **pantry(storage)** + 식품.
- **가공식품** → 식품. pantry는 조리재료성만.
- **비식품 상품**(세제·봉투) → **식비 차감**, pantry X.
- **조정**(할인·쿠폰·포인트) → 품목 아님, **식비 차감 안 함**(total에 이미 반영).
- **미해결**(category=null) → 식품 취급 + `needs_review` → HITL에서 확인/상품명 입력.

### 3.5 식비 계산 (백엔드가 정본 구현) — **total 앵커**
```
식비 = total_amount − Σ(price where category == "비식품")
```
- 조정·식품 개별금액을 합치지 않는다(오정렬·할인에 취약). `total`(할인 반영 실지불액) 기준.
- **total 없음 / Σ라인 ≠ total → 자동 식비 대신 HITL.** 근거·약점 = §7.3.5.

## 4. 오정렬 4층 방어 (이미 서비스 내 처리)
① total 앵커 ② 부호-종류 불일치 → `needs_review` ③ **보수적 가격 재정렬**(`realign_prices`:
"조정-양수 1개 ∧ 비조정-음수 1개" 정확히 한 쌍일 때만 스왑) ④ HITL. → **백엔드는 `price`를 그대로
신뢰**하되(재정렬 반영됨), `needs_review` 줄은 HITL로.

## 5. 설정 — 전부 env override (백엔드가 배포 환경에 주입)
| env | 기본 | 비고 |
|---|---|---|
| `PORT` | 8010(Dockerfile) | **포트 SoT는 팀 결정** — `services/CONVENTIONS.md §5`에서 확정, 여기선 env로만 |
| `GEMINI_API_KEY` | — | **챗봇과 별도 키**(비용 격리, 유료). gitignore된 `.env` |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | 벤치마크 최적(§model-benchmark) |
| `OCR_BACKEND` | vision | 교체가능 계약 |
| `PG*` | — | **읽기 전용**(item_master 조회). 챗봇과 동일 fbapp. 아래 §6 |
| `DICT_ITEM_MASTER_PATH`·`SHELF_LIFE_PATH`·`EDGE_POLICY_PATH` | repo 기본 | 배포 시 패키징 경로로 |

## 6. DB 접점
- **읽기(구현됨)**: `item_master`/`item_alias` → item_id 해결. **가드레일**: read_only 트랜잭션·SELECT만·
  public 티어만·기동 시 단기 커넥션 1개·**DB 없으면 파일 폴백**(서비스 계속 동작). 위험분석 = §7 / 메모리.
- **쓰기(백엔드 구간)**: `pantry.ocr_receipt`·`ocr_receipt_item` 저장, HITL 확정 → `pantry.pantry_item`·
  expense 반영, 예산 차감(식비=§3.5). **스키마·트랜잭션·동의는 백엔드 소유.**

## 7. 실행
```bash
cd services/ocr && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PORT=8010 .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
```
Dockerfile은 `$PORT`(기본 8010) 사용. 데모 = `GET /`.

## 8. AI 후속 (병렬·비차단)
`item_id`가 nullable이라 백엔드는 **기다릴 필요 없음.** AI가 이후 채울 것:
- 3/4단계 `food_nutrition`·`oasis` 파생(미해결↓) · 7단계 미해결 **LLM 실시간 분류**(장당 <0.05원, DB화)
- 이미지 썸네일(§7.9, 별개 트랙)
계약(OcrItemOut)은 안정 — 필드 추가는 nullable로만.
