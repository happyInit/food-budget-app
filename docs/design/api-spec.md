# API 명세서 (초안)

> **제안·검토용 초안.** 서비스별 REST 엔드포인트를 design.md §5(서비스)·기능 정의에서 파생. 정본 확정 시 요청/응답 스키마 상세화 필요.

> - Base: 클라이언트 → **API Gateway**(`/api/*`, JWT 검증) → 각 서비스. `/internal/*`은 내부 전용(외부 미노출).

> - 인증: `O`=JWT 필요, `-`=불필요, `내부`=서비스 간 내부 호출.

> **구현 현황 = 2026-07-15 기준** (실 코드·프론트 대조). 상태 범례:
> - ✅ **구현·실연동** — 백엔드 동작 + 프론트 실 API 연동 완료
> - 🔷 **백엔드만** — 백엔드 구현됨, 프론트 미연동
> - 🟡 **프론트 mock** — 프론트 화면 있음, 백엔드 미구현(목업으로 동작)
> - ⚪ **미착수** — 프론트도 껍데기/없음 + 백엔드 없음
> - ⏸ **보류** — 이번 단계 제외(2차/서비스 단계 또는 드롭)


## Gateway

| # | 기능 | Method | Path | 설명 | 인증 | 우선순위 | 상태 |
|---|---|---|---|---|---|---|---|
| 1 | 공통 | `GET` | `/health` | 헬스체크 (라이브니스) | - | P0 | ✅ (recipe·price·chat 3서비스) |

## Auth

| # | 기능 | Method | Path | 설명 | 인증 | 우선순위 | 상태 |
|---|---|---|---|---|---|---|---|
| 2 | 인증 | `POST` | `/api/auth/signup` | 이메일 회원가입 | - | P0 | ⚪ (로그인 UI만) |
| 3 | 인증 | `POST` | `/api/auth/login` | 이메일 로그인 → JWT 발급 | - | P0 | ⚪ |
| 4 | 인증 | `POST` | `/api/auth/kakao` | 카카오 OAuth 로그인/콜백 | - | P0 | ⚪ |
| 5 | 인증 | `POST` | `/api/auth/refresh` | 액세스 토큰 재발급 | refresh | P0 | ⚪ |
| 6 | 인증 | `POST` | `/api/auth/logout` | 로그아웃 (토큰 무효화) | O | P0 | ⚪ |

## User

| # | 기능 | Method | Path | 설명 | 인증 | 우선순위 | 상태 |
|---|---|---|---|---|---|---|---|
| 7 | 프로필 | `GET` | `/api/users/me` | 내 프로필 조회 | O | P0 | ⚪ (My mock) |
| 8 | 프로필 | `PATCH` | `/api/users/me` | 프로필 수정 | O | P0 | ⚪ |
| 9 | 예산 | `GET` | `/api/users/budget` | 월 예산 조회 | O | P0 | ⚪ (BudgetSetup UI만) |
| 10 | 예산 | `PUT` | `/api/users/budget` | 월 예산 설정 | O | P0 | ⚪ |

## Pantry

| # | 기능 | Method | Path | 설명 | 인증 | 우선순위 | 상태 |
|---|---|---|---|---|---|---|---|
| 11 | 재고 | `GET` | `/api/pantry/items` | 냉장고 재고 목록 | O | P0 | 🟡 (Fridge mock) |
| 12 | 재고 | `POST` | `/api/pantry/items` | 재고 수동 추가 | O | P0 | 🟡 (FridgeAdd mock) |
| 13 | 재고 | `PATCH` | `/api/pantry/items/{id}` | 재고 수정 | O | P0 | 🟡 (DnD 이동 mock) |
| 14 | 재고 | `DELETE` | `/api/pantry/items/{id}` | 재고 삭제 | O | P0 | 🟡 |
| 15 | 소비기한 | `GET` | `/api/pantry/expiring` | 소비기한 임박 목록 | O | P0 | 🟡 |
| 16 | OCR | `POST` | `/api/pantry/ocr` | 영수증 이미지 업로드 (OCR 접수) | O | P0 | 🟡 (OcrUpload mock) |
| 17 | OCR | `GET` | `/api/pantry/ocr/{jobId}` | OCR 처리 상태·결과 조회 | O | P0 | 🟡 (가짜 결과) |

## Recipe

| # | 기능 | Method | Path | 설명 | 인증 | 우선순위 | 상태 |
|---|---|---|---|---|---|---|---|
| 18 | 검색 | `GET` | `/api/recipes` | 레시피 탐색·검색 (10K 소스) | O | P0 | ✅ **실연동** (조리시간·난이도 필터) |
| 19 | 상세 | `GET` | `/api/recipes/{id}` | 레시피 상세 (재료·**영양**·현재가) | O | P0 | ✅ **실연동** (재료별 100g 영양·컬리/오아시스가) |
| 20 | 레시피북 | `GET` | `/api/recipes/book` | 내 레시피북 목록 | O | P1 | 🟡 (Recipebook mock) |
| 21 | 레시피북 | `POST` | `/api/recipes/book` | 레시피 저장(스크랩) | O | P1 | 🟡 (저장 버튼 mock) |
| 22 | 레시피북 | `DELETE` | `/api/recipes/book/{id}` | 레시피북에서 삭제 | O | P1 | 🟡 |
| 23 | 레시피북 | `POST` | `/api/recipes/book/{id}/share` | 레시피북 컬렉션 공유 | O | P1 | ⏸ 보류 (개별 레시피 공유 버튼만 존재) |
| 24 | YouTube추출 | `POST` | `/api/recipes/extract` | YouTube URL 추출 접수 | O | P1 | 🟡 (YoutubeExtract mock) |
| 25 | YouTube추출 | `GET` | `/api/recipes/extract/{jobId}` | 추출 상태·결과 조회 | O | P1 | 🟡 |

## Price

| # | 기능 | Method | Path | 설명 | 인증 | 우선순위 | 상태 |
|---|---|---|---|---|---|---|---|
| 26 | 현재가 | `GET` | `/api/prices/{itemCode}` | 상품 현재가 조회 | O | P0 | 🔷 백엔드만 (프론트 미연동) |
| 27 | 이력 | `GET` | `/api/prices/{itemCode}/history` | 가격 이력 조회 | O | P0 | 🔷 백엔드만 (그래프 표시 ⏸보류) |
| 28 | 시세추천 | `GET` | `/api/prices/recommend` | 시세 추천 (지금 싼 재료) | O | P1 | ✅ **실연동** (홈) |
| 29 | 최저가관심 | `POST` | `/api/prices/watch` | 최저가 관심 등록 | O | P0 | ⏸ 보류 (등록 UI 없음·명세 Price도 저점알림 드롭/보류) |
| 30 | 최저가관심 | `DELETE` | `/api/prices/watch/{itemCode}` | 최저가 관심 해제 | O | P0 | ⏸ 보류 |
| 31 | 핫딜 | `GET` | `/api/prices/hotdeals` | 핫딜(마감세일·할인) 목록 | O | P1 | ✅ **실연동** (핫딜) |

## MealPlan

| # | 기능 | Method | Path | 설명 | 인증 | 우선순위 | 상태 |
|---|---|---|---|---|---|---|---|
| 32 | 추천 | `POST` | `/api/mealplan/recommend` | 추천 요청 (뭐 해먹지·재고·예산 기반) | O | P0 | 🟡 (MealPlan mock, `platePlan`) |
| 33 | 장바구니 | `GET` | `/api/mealplan/cart` | 장바구니 조회 (부족재료·현재가·예산 대비) | O | P0 | 🟡 (Cart mock) |
| 34 | 장바구니 | `POST` | `/api/mealplan/cart/items` | 레시피/재료 담기 | O | P0 | 🟡 (담기모달 UI만) |
| 35 | 장바구니 | `DELETE` | `/api/mealplan/cart/items/{id}` | 장바구니 항목 제거 | O | P0 | 🟡 |
| 36 | 장보기 | `POST` | `/api/mealplan/cart/checkout` | 장보기 목록 확정 | O | P0 | 🟡 |
| 37 | 어시스턴트 | `POST` | `/api/mealplan/assistant/chat` | 대화형 어시스턴트 (RAG) | O | P1 | ✅ **실연동** (챗 위젯·어시스턴트, 개인화만 스텁) |

## Expense

| # | 기능 | Method | Path | 설명 | 인증 | 우선순위 | 상태 |
|---|---|---|---|---|---|---|---|
| 38 | 캘린더 | `GET` | `/api/expenses/calendar` | 식비 캘린더 (월별) | O | P0 | 🟡 (Expense mock) |
| 39 | 기록 | `POST` | `/api/expenses` | 지출 기록 (외식비 수동/영수증 연동) | O | P0 | 🟡 (ExpenseAdd mock) |
| 40 | 성과 | `GET` | `/api/expenses/summary` | 성과지표 (누적/잔여·안 버린 재료) | O | P0 | 🟡 (Performance mock) |

## Notification

| # | 기능 | Method | Path | 설명 | 인증 | 우선순위 | 상태 |
|---|---|---|---|---|---|---|---|
| 41 | 알림함 | `GET` | `/api/notifications` | 알림함 목록 | O | P0 | 🟡 (canned) |
| 42 | 알림함 | `PATCH` | `/api/notifications/{id}/read` | 알림 읽음 처리 | O | P0 | ⚪ (읽음 배선 없음) |
| 43 | 설정 | `GET` | `/api/notifications/settings` | 알림 설정 조회 | O | P1 | ⏸ 보류 |
| 44 | 설정 | `PUT` | `/api/notifications/settings` | 알림 설정 변경 | O | P1 | ⏸ 보류 |

## ML Serving

| # | 기능 | Method | Path | 설명 | 인증 | 우선순위 | 상태 |
|---|---|---|---|---|---|---|---|
| 45 | 내부 | `POST` | `/internal/ml/ner` | 재료 NER 추론 (내부 호출) | 내부 | P0 | ⚪ (챗=gazetteer 규칙 대체, CRF 미완) |
| 46 | 내부 | `POST` | `/internal/ml/anomaly` | 최저가 이상탐지 (내부 호출) | 내부 | P0 | ⏸ 보류 (최저가 알림과 함께) |
| 47 | 내부 | `POST` | `/internal/ml/rank` | 레시피 랭킹 (내부 호출) | 내부 | P1 | ⚪ (개인화 P1, 미착수) |

---

총 47개 엔드포인트 · 서비스 10개. 상세 스키마(필드 타입·검증·에러코드)는 확정 후 추가.

---

## 구현 현황 요약 (2026-07-15)

| 상태 | 개수 | 엔드포인트 |
|---|---|---|
| ✅ 구현·실연동 | 6 | #1(health) · #18 · #19 · #28 · #31 · #37 |
| 🔷 백엔드만 | 2 | #26 · #27 |
| 🟡 프론트 mock | 21 | #11–17 · #20–22 · #24–25 · #32–36 · #38–40 · #41 |
| ⚪ 미착수 | 12 | #2–10 · #42 · #45 · #47 |
| ⏸ 보류 | 6 | #23 · #29 · #30 · #43 · #44 · #46 |

**핵심**: 데이터 티어(크롤링 DB 읽기·무상태 = recipe·price·chat)만 실동작. 나머지는 **User/Auth + 유저 OLTP 스키마 부재**로 프론트 목업 상태.

### ⏸ 보류 목록 (이번 분담 제외 — 2차/서비스 단계)
- **최저가 관심·알림** #29·#30 + 이상탐지 #46 (명세 Price에서도 "저점 알림=드롭/보류")
- **알림 설정** #43·#44 (수신여부·기간 선택 UI 포함)
- **레시피북 컬렉션 공유** #23 (개별 레시피 공유는 상세에 있음)
- **가격 이력 그래프** (#27 백엔드는 있음, 표시 화면만 보류)
- **개인화 랭킹 고도화** #47 (P1 LightGBM), **바코드 스캔** 재고등록

---

## 개발 분담안 (2인 · 제안) — AI 추출·ML 제외 후 반띵 (14 : 15)

> 역할분담은 팀 결정 사항 → 아래는 **도메인 기준 균형 분할 제안**이며 스왑 가능.
> ✅ 완료 · ⏸ 보류 · **AI 담당(추출·ML) 몫**을 뺀 나머지 **활성 개발분 29개**를 2인이 나눔.

### 🅰 Dev A — 인증·냉장고 (유저 상태 코어) · **14개**
- **Auth** #2–6 (JWT·카카오)
- **User/예산** #7–10
- **Pantry 재고** #11–15
- 성격: 인증 + 유저 OLTP 뼈대 + 냉장고 재고. **모두가 의존하는 auth를 먼저 깖.** 프론트 Fridge·My·BudgetSetup 실연동.

### 🅱 Dev B — 장보기·식비·콘텐츠 (소비 흐름) · **15개**
- **MealPlan 추천** #32 (재고+임박+예산 규칙 랭킹)
- **Cart 장바구니·체크아웃** #33–36
- **Expense 식비** #38–40
- **Notification 알림함** #41–42
- **레시피북** #20–22
- **Price 프론트연동** #26–27
- 성격: 추천→장바구니→식비 **소비 흐름** + 알림 + 레시피북 + 가격 프론트. 프론트 MealPlan·Cart·Expense·Recipebook 실연동.

### 🤖 AI 담당 (건우) — 추출·ML (2인 분담서 제외)
- **OCR** #16–17 (영수증 → OCR → 재료 NER → 재고 저장)
- **YouTube 추출** #24–25 (Gemini 멀티모달 → NER → ES 매핑)
- **NER** #45 · **레시피 랭킹** #47 · (이상탐지 #46 보류)
- → 이유: 핵심 가치가 전부 AI(OCR·Gemini·NER). ML 서빙(#45·47)과 한 사람이 소유.

### 🔗 접점 (오펀 방지)
- OCR 결과 저장 = Dev A `POST /pantry/items`(#12) · YouTube 결과 저장 = Dev B `POST /recipes/book`(#21)
- → AI는 추출만, 저장은 위 2인 API를 호출. **추가 엔드포인트 없음.**

### 🤝 공통 선결 (초반 페어)
1. **유저 OLTP 스키마** — `docs/prd/schema-production.sql`(6서비스 DDL, PR #61 확정)·`schema-app-oltp.md` 위에 얹음.
2. **Gateway + JWT** — 이후 모든 `인증 O` 엔드포인트의 전제.
→ Dev A가 Auth 스켈레톤을 먼저 세우면 B가 그 위에 얹는 순서. 초반 며칠 A의 auth가 B의 blocker라 페어 권장.

---

## 응답 스키마 상세 — 데이터 티어 (실 DB 컬럼 기준)

> **적재 완료된 `foodbudget` DB 실 컬럼으로 확정 (2026-07-14 확인).** 소스: [`docs/prd/schema-public-data.sql`](../prd/schema-public-data.sql) + DB introspection.
> 유저 OLTP 대응 엔드포인트(#2~17·20~25·29~30·32~44)의 응답 스키마는 [`docs/prd/schema-app-oltp.md`](../prd/schema-app-oltp.md) 확정 후 추가.

### 공통 규약
- **가격은 `numeric`(원 단위 정수)** — `₩`/천단위 포맷 없음. 표시는 클라이언트가 변환.
- `source` = `'kurly'` | `'oasis'` · `retail_price.deal_type` = `'general'` | `'closeSale'` (⚠️ 타임세일 미수집)
- `retail_product.storage`(오아시스) = `'냉장'` | `'신선'` · `cooking_time` = `'30분 이내'` 같은 **텍스트**
- `item_id` 매칭률 ~89% — 미매칭 상품은 `item_id=null`(품목 축 조인서 제외)

### #18 `GET /api/recipes` → `recipes[]`  (table: `recipe`)
`id, source, name, category, cook_method, cooking_time, level_nm, kcal, serving, image_url`
※ 10K 소스는 `category·cook_method·kcal·image_url` 대체로 `null`. **서빙=10K만**(`config.serve_source`). 필터 `?cooking_time=&level=` 지원(실데이터).

### #19 `GET /api/recipes/{id}` → `recipe, ingredients[], steps[], nutrition?`
- `recipe`: #18 컬럼 + `carb_g, protein_g, fat_g, sodium_mg` (10K는 null)
- `ingredients[]` (`recipe_ingredient`): `seq, ingredient_name, quantity, item_id, ner_status`
  - **재료 최저가**(`retail_item_price_compare`, `item_id` 조인): `lowest_source, lowest_krw_per_100g, kurly_krw_per_100g, oasis_krw_per_100g`
  - **재료 100g 영양**(`food_nutrition`, `item_id` 조인): `kcal_100g, protein_100g, carb_100g, fat_100g, sodium_100g` — ✅ 구현. ⚠️ 100g 기준(레시피 총합은 수량 비표준화로 미제공)
- `steps[]` (`recipe_step`): `step_no, description, image_url`

### #26 `GET /api/prices/{itemCode}` → `price`
- 소매 최신 (`retail_unit_price` 뷰): `source, price, deal_type, won_per_100g, won_per_piece, piece_unit, won_per_100ml, crawled_at`
- 시세 baseline (`price_online_daily`): `survey_date, price_min, price_med, price_max, obs_count`

### #27 `GET /api/prices/{itemCode}/history` → `history[]`  (table: `retail_price`)
`crawled_at, price, original_price, discount_rate, deal_type` (상품별 시계열 스냅샷)

### #28 `GET /api/prices/recommend` (지금 싼 재료) → `items[]`  (view: `retail_item_price_compare`)
`item_id, canonical_name, category, kurly_100g, oasis_100g, kurly_n, oasis_n, kurly_100ml, oasis_100ml`
※ 더 싼 소스·가격 = `min(kurly_100g, oasis_100g)`.

### #31 `GET /api/prices/hotdeals` → `deals[]`  (`retail_product` + `retail_price`)
- 상품: `id, source, name, image_url, item_id, weight_g, storage, origin, expiry_text`
- 가격/딜: `price, original_price, discount_rate, deal_type, timedeal_end, unit_price, unit_basis, is_sold_out`
- ⚠️ 현재 `deal_type='closeSale'`(오아시스 마감세일)·`'general'`(컬리 할인)만 존재.

### #37 `POST /api/mealplan/assistant/chat` → `reply, basis[], actions[], unanswered`
- `reply`(문장) · `basis[]`(근거: `price_snapshot`/`nutrition`/`recipe_match`) · `actions[]`(`open_recipe`/`add_to_cart`) · `unanswered`(무근거 거절)
- 생성=템플릿(무료·환각불가), 추출=gazetteer 규칙. 개인화(재고·예산)는 스텁(유저 OLTP 대기).

### 참고 — 프론트 정렬 상태
`frontend/src/lib/types.ts`에 위 컬럼을 그대로 반영한 행 타입 정의. 데이터 티어부(#18·19·26·27·28·31·37)는 실 컬럼명·값 형태로 프론트 연동 완료.
