# API 명세서 (초안)

> **제안·검토용 초안.** 서비스별 REST 엔드포인트를 design.md §5(서비스)·기능 정의에서 파생. 정본 확정 시 요청/응답 스키마 상세화 필요.

> - Base: 클라이언트 → **API Gateway**(`/api/*`, JWT 검증) → 각 서비스. `/internal/*`은 내부 전용(외부 미노출).

> - 인증: `O`=JWT 필요, `-`=불필요, `내부`=서비스 간 내부 호출.


## Gateway

| # | 기능 | Method | Path | 설명 | 인증 | 요청(주요) | 응답(주요) | 우선순위 |
|---|---|---|---|---|---|---|---|---|
| 1 | 공통 | `GET` | `/health` | 헬스체크 (라이브니스) | - | - | 200 OK | P0 |

## Auth

| # | 기능 | Method | Path | 설명 | 인증 | 요청(주요) | 응답(주요) | 우선순위 |
|---|---|---|---|---|---|---|---|---|
| 2 | 인증 | `POST` | `/api/auth/signup` | 이메일 회원가입 | - | email, password, nickname | 201 · userId | P0 |
| 3 | 인증 | `POST` | `/api/auth/login` | 이메일 로그인 → JWT 발급 | - | email, password | 200 · accessToken, refreshToken | P0 |
| 4 | 인증 | `POST` | `/api/auth/kakao` | 카카오 OAuth 로그인/콜백 | - | code(state·PKCE) | 200 · accessToken, refreshToken | P0 |
| 5 | 인증 | `POST` | `/api/auth/refresh` | 액세스 토큰 재발급 | refresh | refreshToken | 200 · accessToken | P0 |
| 6 | 인증 | `POST` | `/api/auth/logout` | 로그아웃 (토큰 무효화) | O | - | 204 | P0 |

## User

| # | 기능 | Method | Path | 설명 | 인증 | 요청(주요) | 응답(주요) | 우선순위 |
|---|---|---|---|---|---|---|---|---|
| 7 | 프로필 | `GET` | `/api/users/me` | 내 프로필 조회 | O | - | 200 · user | P0 |
| 8 | 프로필 | `PATCH` | `/api/users/me` | 프로필 수정 | O | nickname, ... | 200 · user | P0 |
| 9 | 예산 | `GET` | `/api/users/budget` | 월 예산 조회 | O | - | 200 · amount, month | P0 |
| 10 | 예산 | `PUT` | `/api/users/budget` | 월 예산 설정 | O | amount | 200 · budget | P0 |

## Pantry

| # | 기능 | Method | Path | 설명 | 인증 | 요청(주요) | 응답(주요) | 우선순위 |
|---|---|---|---|---|---|---|---|---|
| 11 | 재고 | `GET` | `/api/pantry/items` | 냉장고 재고 목록 | O | ?loc= | 200 · items[] | P0 |
| 12 | 재고 | `POST` | `/api/pantry/items` | 재고 수동 추가 | O | name, qty, loc, expireAt? | 201 · item | P0 |
| 13 | 재고 | `PATCH` | `/api/pantry/items/{id}` | 재고 수정 | O | qty, loc, expireAt | 200 · item | P0 |
| 14 | 재고 | `DELETE` | `/api/pantry/items/{id}` | 재고 삭제 | O | - | 204 | P0 |
| 15 | 유통기한 | `GET` | `/api/pantry/expiring` | 유통기한 임박 목록 | O | ?days=2 | 200 · items[] | P0 |
| 16 | OCR | `POST` | `/api/pantry/ocr` | 영수증 이미지 업로드 (OCR 접수) | O | multipart image | 202 · jobId | P0 |
| 17 | OCR | `GET` | `/api/pantry/ocr/{jobId}` | OCR 처리 상태·결과 조회 | O | - | 200 · status, items[] | P0 |

## Recipe

| # | 기능 | Method | Path | 설명 | 인증 | 요청(주요) | 응답(주요) | 우선순위 |
|---|---|---|---|---|---|---|---|---|
| 18 | 검색 | `GET` | `/api/recipes` | 레시피 탐색·검색 (ES) | O | ?q=&tag=&page= | 200 · recipes[] | P0 |
| 19 | 상세 | `GET` | `/api/recipes/{id}` | 레시피 상세 (재료·영양·현재가) | O | - | 200 · recipe, ingredients[] | P0 |
| 20 | 레시피북 | `GET` | `/api/recipes/book` | 내 레시피북 목록 | O | - | 200 · books[] | P1 |
| 21 | 레시피북 | `POST` | `/api/recipes/book` | 레시피 저장(스크랩) | O | recipeId | 201 · item | P1 |
| 22 | 레시피북 | `DELETE` | `/api/recipes/book/{id}` | 레시피북에서 삭제 | O | - | 204 | P1 |
| 23 | 레시피북 | `POST` | `/api/recipes/book/{id}/share` | 레시피북 공유 | O | - | 200 · shareUrl | P1 |
| 24 | YouTube추출 | `POST` | `/api/recipes/extract` | YouTube URL 추출 접수 | O | url | 202 · jobId | P1 |
| 25 | YouTube추출 | `GET` | `/api/recipes/extract/{jobId}` | 추출 상태·결과 조회 | O | - | 200 · status, recipe | P1 |

## Price

| # | 기능 | Method | Path | 설명 | 인증 | 요청(주요) | 응답(주요) | 우선순위 |
|---|---|---|---|---|---|---|---|---|
| 26 | 현재가 | `GET` | `/api/prices/{itemCode}` | 상품 현재가 조회 | O | - | 200 · price | P0 |
| 27 | 이력 | `GET` | `/api/prices/{itemCode}/history` | 가격 이력 조회 | O | ?from=&to= | 200 · history[] | P0 |
| 28 | 시세추천 | `GET` | `/api/prices/recommend` | 시세 추천 (지금 싼 재료) | O | - | 200 · items[] | P1 |
| 29 | 최저가관심 | `POST` | `/api/prices/watch` | 최저가 관심 등록 | O | itemCode | 201 | P0 |
| 30 | 최저가관심 | `DELETE` | `/api/prices/watch/{itemCode}` | 최저가 관심 해제 | O | - | 204 | P0 |
| 31 | 핫딜 | `GET` | `/api/prices/hotdeals` | 오아시스 핫딜(타임/마감세일) 목록 | O | - | 200 · deals[] | P1 |

## MealPlan

| # | 기능 | Method | Path | 설명 | 인증 | 요청(주요) | 응답(주요) | 우선순위 |
|---|---|---|---|---|---|---|---|---|
| 32 | 추천 | `POST` | `/api/mealplan/recommend` | 추천 요청 (뭐 해먹지·재고·예산 기반) | O | budget?, prefer? | 200 · recipes[] | P0 |
| 33 | 장바구니 | `GET` | `/api/mealplan/cart` | 장바구니 조회 (부족재료·현재가·예산 대비) | O | - | 200 · cart, total, remain | P0 |
| 34 | 장바구니 | `POST` | `/api/mealplan/cart/items` | 레시피/재료 담기 | O | recipeId | itemCode, qty | 200 · cart | P0 |
| 35 | 장바구니 | `DELETE` | `/api/mealplan/cart/items/{id}` | 장바구니 항목 제거 | O | - | 200 · cart | P0 |
| 36 | 장보기 | `POST` | `/api/mealplan/cart/checkout` | 장보기 목록 확정 | O | - | 200 · order | P0 |
| 37 | 어시스턴트 | `POST` | `/api/mealplan/assistant/chat` | 대화형 어시스턴트 (RAG) | O | message | 200 · reply | P1 |

## Expense

| # | 기능 | Method | Path | 설명 | 인증 | 요청(주요) | 응답(주요) | 우선순위 |
|---|---|---|---|---|---|---|---|---|
| 38 | 캘린더 | `GET` | `/api/expenses/calendar` | 식비 캘린더 (월별) | O | ?month= | 200 · days[] | P0 |
| 39 | 기록 | `POST` | `/api/expenses` | 지출 기록 (외식비 수동/영수증 연동) | O | amount, type, date | 201 · expense | P0 |
| 40 | 성과 | `GET` | `/api/expenses/summary` | 성과지표 (누적/잔여·안 버린 재료) | O | ?month= | 200 · summary | P0 |

## Notification

| # | 기능 | Method | Path | 설명 | 인증 | 요청(주요) | 응답(주요) | 우선순위 |
|---|---|---|---|---|---|---|---|---|
| 41 | 알림함 | `GET` | `/api/notifications` | 알림함 목록 | O | ?unread= | 200 · notifications[] | P0 |
| 42 | 알림함 | `PATCH` | `/api/notifications/{id}/read` | 알림 읽음 처리 | O | - | 200 | P0 |
| 43 | 설정 | `GET` | `/api/notifications/settings` | 알림 설정 조회 | O | - | 200 · settings | P1 |
| 44 | 설정 | `PUT` | `/api/notifications/settings` | 알림 설정 변경 | O | lowPrice, expiry ... | 200 · settings | P1 |

## ML Serving

| # | 기능 | Method | Path | 설명 | 인증 | 요청(주요) | 응답(주요) | 우선순위 |
|---|---|---|---|---|---|---|---|---|
| 45 | 내부 | `POST` | `/internal/ml/ner` | 재료 NER 추론 (내부 호출) | 내부 | text | 200 · items[] | P0 |
| 46 | 내부 | `POST` | `/internal/ml/anomaly` | 최저가 이상탐지 (내부 호출) | 내부 | series | 200 · isAnomaly | P0 |
| 47 | 내부 | `POST` | `/internal/ml/rank` | 레시피 랭킹 (내부 호출) | 내부 | userId, candidates[] | 200 · ranked[] | P1 |

---

총 47개 엔드포인트 · 서비스 10개. 상세 스키마(필드 타입·검증·에러코드)는 확정 후 추가.

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
※ 10K 소스는 `category·cook_method·kcal·image_url` 대체로 `null`.

### #19 `GET /api/recipes/{id}` → `recipe, ingredients[], steps[], nutrition?`
- `recipe`: #18 컬럼 + `carb_g, protein_g, fat_g, sodium_mg`
- `ingredients[]` (`recipe_ingredient`): `seq, ingredient_name, quantity, ingredient_raw, ner_status, item_id`
- `steps[]` (`recipe_step`): `step_no, description, image_url`
- `nutrition` (`food_nutrition`, `item_id` 조인): `serving_g, kcal, carb_g, protein_g, fat_g, sugar_g, sodium_mg`
- 재료별 최저가 = `retail_item_price_compare`(`item_id` 조인) 파생

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

### 참고 — 프론트 정렬 상태
`frontend/src/lib/types.ts`에 위 컬럼을 그대로 반영한 행 타입 정의. `mock.ts` 데이터 티어부는 실 컬럼명·값 형태(numeric 가격 등)로 정렬 완료 → API 연동 시 그대로 매핑.
