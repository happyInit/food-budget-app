# API 명세서

> 서비스별 REST 엔드포인트. design.md §5(서비스)·기능 정의에서 파생. Base: 클라이언트 → **API Gateway(nginx)**(`/api/*`, JWT 검증) → 각 서비스. `/internal/*`은 내부 전용.

> **구현 현황 = 2026-07-20 기준** — 실 백엔드 라우트(`services/*/app/routers.py`) + 프론트 실 호출(`frontend/src/lib`) 대조 + **라이브 재검증**(ocr·ranking 컨테이너 실행 확인). 상태는 **코드 존재·연동·실배포 기준**.

> 상태 범례: ✅ **구현·연동**(백엔드 라우트 + 프론트 실 호출) · 🔷 **백엔드만**(프론트 미연동) · 🟡 **프론트 mock**(화면만, 백엔드 미배선) · ⚪ **미착수** · ⏸ **보류**

> 인증: `O`=JWT 필요 · `-`=불필요 · `내부`=서비스 간.

## 서비스 구성 (실 배포 9 + ML서빙 + 게이트웨이)

| 서비스 | 소유 스키마/자원 | 담당 엔드포인트군 |
|---|---|---|
| **nginx** (Gateway) | — | 라우팅 · JWT 검증 · 정적서빙 |
| **account** (Auth+User) | `account` | `/api/auth/*` · `/api/users/*` |
| **pantry** | `pantry` | `/api/pantry/*` |
| **recipe** | `public.recipe`(읽기) + ES | `/api/recipes` · `/api/recipes/{id}` |
| **recipebook** | `recipebook` | `/api/recipes/book` · `/api/recipes/mine` · `/api/recipes/shared` |
| **price** | `price` + `public`(가격) + Redis | `/api/prices/*` |
| **mealplan** | `mealplan` + `activity`(노출로그) | `/api/mealplan/*` · `/api/expenses/*` |
| **notify** | `notify` | `/api/notifications/*` |
| **chat** | 읽기(`public`/ES/Redis) + Gemini | `/api/mealplan/assistant/chat` · `/chat` |
| **ocr** ✅(실배포·기동 중) | Gemini Vision | `/api/pantry/ocr` |
| **ML-serving** | CRF·XGBoost·LightGBM | `/internal/ml/*` |

---

## Gateway

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 1 | 공통 | `GET` | `/health` | 헬스체크 (서비스별) | - | P0 | ✅ (전 서비스) |

## Auth — `account`

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 2 | 인증 | `POST` | `/api/auth/signup` | 이메일 회원가입 (bcrypt 스레드 오프로드) | - | P0 | ✅ |
| 3 | 인증 | `POST` | `/api/auth/login` | 이메일 로그인 → JWT 발급 | - | P0 | ✅ |
| 4 | 인증 | `POST` | `/api/auth/kakao` | 카카오 OAuth (code+state) | - | P0 | 🟡 (백엔드 501 스텁·버튼만) |
| — | 인증 | `POST` | `/api/auth/google` | 구글 OAuth | - | P1 | ⚪ (미배선·버튼만) |
| 5 | 인증 | `POST` | `/api/auth/refresh` | 액세스 토큰 재발급 (30분 TTL·silent 재발급) | refresh | P0 | ✅ |
| 6 | 인증 | `POST` | `/api/auth/logout` | 로그아웃 (클라 토큰 폐기) | O | P0 | ✅ |

## User — `account`

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 7 | 프로필 | `GET` | `/api/users/me` | 내 프로필 조회 | O | P0 | ✅ |
| 8 | 프로필 | `PATCH` | `/api/users/me` | 프로필(닉네임) 수정 | O | P0 | ✅ |
| 48 | 탈퇴 | `DELETE` | `/api/users/me` | 회원 탈퇴 | O | P1 | ✅ |
| 9 | 예산 | `GET` | `/api/users/budget` | 월 예산 조회 | O | P0 | ✅ |
| 10 | 예산 | `PUT` | `/api/users/budget` | 월 예산 설정 | O | P0 | ✅ |
| 49 | 제외재료 | `GET` | `/api/users/excluded-items` | 회피(제외) 재료 목록 | O | P1 | ✅ |
| 50 | 제외재료 | `POST` | `/api/users/excluded-items` | 제외 재료 추가 | O | P1 | ✅ |
| 51 | 제외재료 | `DELETE` | `/api/users/excluded-items/{itemId}` | 제외 재료 해제 | O | P1 | ✅ |

## Pantry — `pantry`

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 11 | 재고 | `GET` | `/api/pantry/items` | 냉장고 재고 목록 | O | P0 | ✅ |
| 12 | 재고 | `POST` | `/api/pantry/items` | 재고 수동 추가 | O | P0 | ✅ |
| 13 | 재고 | `PATCH` | `/api/pantry/items/{id}` | 재고 수정 (DnD 이동 포함) | O | P0 | ✅ |
| 14 | 재고 | `DELETE` | `/api/pantry/items/{id}` | 재고 삭제 | O | P0 | ✅ |
| 15 | 소비기한 | `GET` | `/api/pantry/expiring` | 소비기한 임박 목록 | O | P0 | ✅ |
| 52 | 영수증 | `POST` | `/api/pantry/receipts` | 영수증 이미지 업로드 → HITL 재고 반영 | O | P0 | ✅ (프론트 HITL 연동) |
| 53 | 성과 | `GET` | `/api/pantry/stats` | 소비/폐기 통계 (안 버린 재료 = consumed) | O | P0 | ✅ |

## Recipe — `recipe`

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 18 | 검색 | `GET` | `/api/recipes` | 레시피 탐색·검색 (10K 소스·조리시간·난이도 필터) | O | P0 | ✅ **실연동** |
| 19 | 상세 | `GET` | `/api/recipes/{id}` | 레시피 상세 (재료·**영양**·현재가) | O | P0 | ✅ **실연동** |

## Recipebook — `recipebook` (레시피북 + 직접작성 + 공유)

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 20 | 스크랩 | `GET` | `/api/recipes/book` | 내 레시피북(스크랩) 목록 | O | P1 | ✅ |
| 21 | 스크랩 | `POST` | `/api/recipes/book` | 레시피 저장(스크랩) | O | P1 | ✅ |
| 22 | 스크랩 | `DELETE` | `/api/recipes/book/{bookmarkId}` | 레시피북에서 삭제 | O | P1 | ✅ |
| 54 | 직접작성 | `GET` | `/api/recipes/mine` | 내가 쓴 레시피 목록 | O | P1 | ✅ |
| 55 | 직접작성 | `GET` | `/api/recipes/mine/{id}` | 내 레시피 상세 (만개와 동치 UI) | O | P1 | ✅ |
| 56 | 직접작성 | `POST` | `/api/recipes/mine` | 레시피 직접 등록 (재료명 read-time 매칭) | O | P1 | ✅ |
| 57 | 직접작성 | `DELETE` | `/api/recipes/mine/{id}` | 내 레시피 삭제 | O | P1 | ✅ |
| 58 | 발행 | `POST`·`DELETE` | `/api/recipes/mine/{id}/publish` | 공유 카탈로그 발행/취소 | O | P1 | ✅ |
| 59 | 공유링크 | `POST`·`DELETE` | `/api/recipes/mine/{id}/share` | 공유 토큰 생성/폐기 | O | P1 | ✅ |
| 60 | 카탈로그 | `GET` | `/api/recipes/shared` | 발행된 공유 레시피 목록 | O | P1 | ✅ |
| 61 | 공개뷰 | `GET` | `/api/recipes/shared/{token}` | 공유 레시피 공개 조회 (`/shared/:token`) | - | P1 | ✅ (비인증 공개) |
| 24 | YouTube추출 | `POST` | `/api/recipes/extract` | YouTube URL 추출 접수 (Gemini) | O | P1 | ✅ 백엔드(video:8011) · 프론트 미배선 |
| 25 | YouTube추출 | `GET` | `/api/recipes/extract/{jobId}` | 추출 상태·결과 조회 (재료·스텝 + **재료비**) | O | P1 | ✅ 백엔드(video:8011) · 프론트 미배선 |

## Price — `price`

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 26 | 현재가 | `GET` | `/api/prices/{itemCode}` | 상품 현재가 (물질화 뷰 + Redis 캐시) | O | P0 | 🔷 백엔드만 |
| 27 | 이력 | `GET` | `/api/prices/{itemCode}/history` | 가격 이력 | O | P0 | 🔷 백엔드만 (그래프 ⏸) |
| 28 | 시세추천 | `GET` | `/api/prices/recommend` | 시세 추천 (지금 싼 재료) | O | P1 | ✅ **실연동** (홈) |
| 31 | 핫딜 | `GET` | `/api/prices/hotdeals` | 핫딜(마감세일·할인) 목록 | O | P1 | ✅ **실연동** |
| 62 | 품목검색 | `GET` | `/api/prices/items?q=` | 품목명 검색 (자동완성) | O | P1 | ✅ |
| 29 | 최저가관심 | `POST` | `/api/prices/watch` | 최저가 관심 등록 | O | P0 | ✅ |
| 30 | 최저가관심 | `DELETE` | `/api/prices/watch/{itemId}` | 최저가 관심 해제 | O | P0 | ✅ |
| 29b | 최저가관심 | `GET` | `/api/prices/watch` | 내 관심 목록 | O | P1 | ✅ 명세 추가(등록/해제 UI가 현재 상태를 보여주려면 필요) |

## MealPlan — `mealplan`

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 32 | 추천 | `POST` | `/api/mealplan/recommend` | 뭐 해먹지 (재고·예산 기반 랭킹) | O | P0 | ✅ |
| 33 | 장바구니 | `GET` | `/api/mealplan/cart` | 장바구니 (부족재료·현재가·예산 대비) | O | P0 | ✅ |
| 34 | 장바구니 | `POST` | `/api/mealplan/cart/items` | 레시피/재료 담기 | O | P0 | ✅ |
| 35 | 장바구니 | `DELETE` | `/api/mealplan/cart/items/{id}` | 장바구니 항목 제거 | O | P0 | ✅ |
| 36 | 장보기 | `POST` | `/api/mealplan/cart/checkout` | 장보기 목록 확정 | O | P0 | ✅ |

## Expense — `mealplan` (캘린더·식비추적)

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 38 | 캘린더 | `GET` | `/api/expenses/calendar` | 식비 캘린더 (월별) | O | P0 | ✅ |
| 39 | 기록 | `POST` | `/api/expenses` | 지출 기록 (외식비·영수증 연동) | O | P0 | ✅ |
| 40 | 성과 | `GET` | `/api/expenses/summary` | 성과지표 (누적/잔여·안 버린 재료) | O | P0 | ✅ |
| 63 | 내역 | `GET` | `/api/expenses/breakdown` | 지출 내역 분해 (카테고리별) | O | P0 | ✅ |

## Chat — `chat` (대화형 어시스턴트 · RAG)

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 37 | 어시스턴트 | `POST` | `/api/mealplan/assistant/chat` | 대화형 어시스턴트 (RAG 4소스 fan-out) | O | P1 | ✅ **실연동** |
| 64 | 챗 | `POST` | `/chat` | 챗 응답 (생성=Gemini prod, 개인화 스텁) | O | P1 | ✅ |

## Notification — `notify`

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 41 | 알림함 | `GET` | `/api/notifications?limit=` | 알림함 목록 (limit 상한) | O | P0 | ✅ |
| 42 | 알림함 | `PATCH` | `/api/notifications/{id}/read` | 알림 읽음 처리 | O | P0 | ✅ |
| 43 | 설정 | `GET` | `/api/notifications/settings` | 알림 설정 조회 | O | P1 | ⏸ 보류 |
| 44 | 설정 | `PUT` | `/api/notifications/settings` | 알림 설정 변경 | O | P1 | ⏸ 보류 |

## OCR — `ocr` ✅ (실배포·기동 중 · backend=Gemini Vision, 실호출은 pantry `/receipts`#52)

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 16 | OCR | `POST` | `/api/pantry/ocr` | 영수증 OCR 접수 (Gemini Vision-first) | O | P0 | ✅ (실배포·기동) |
| 17 | OCR | `GET` | `/api/pantry/ocr/{jobId}` | OCR 처리 상태·결과 조회 | O | P0 | ✅ (실배포·기동) |

## ML Serving — `ML-serving` (내부)

| # | 기능 | Method | Path | 설명 | 인증 | 우선 | 상태 |
|---|---|---|---|---|---|---|---|
| 45 | 내부 | `POST` | `/internal/ml/ner` | 재료 NER 추론 | 내부 | P0 | ⚪ (챗=gazetteer 규칙 대체) |
| 46 | 내부 | `POST` | `/internal/ml/anomaly` | 최저가 이상탐지 | 내부 | P0 | ⏸ 보류 |
| 47 | 내부 | `POST` | `/internal/ml/rank` | 레시피 랭킹 (LightGBM) | 내부 | P1 | 🔷 (serving 배포·실행 / mealplan `RANKING_ML_ENABLED=false`로 미호출) |

---

## 구현 현황 요약 (2026-07-20 · 라이브 재검증)

| 상태 | 개수 | 비고 |
|---|---|---|
| ✅ 구현·연동 | 54 | 앱 9서비스(account·pantry·recipe·recipebook·price·mealplan·notify·chat·**ocr**) 실배포 + 프론트 연동 |
| 🔷 백엔드만/미호출 | 5 | #26 현재가 · #27 이력(그래프 ⏸) · #47 랭킹(serving 실행·mealplan flag off) · **#24·#25 영상추출**(video 서비스 기동·프론트 미배선) |
| 🟡 프론트 mock | 1 | #4 카카오(501 스텁) |
| ⏸ 보류 | 2 | #43·44 알림설정 |
| ⚪ 미착수 | 1 | #45 NER(챗=gazetteer 규칙 대체) |

> **2026-07-15 → 07-19 델타**: Auth/User/Pantry/MealPlan/Expense/Notification가 mock→**실서비스 배포·연동**으로 전환. recipebook(직접작성·발행·공유), pantry 영수증/성과, price 품목검색, expenses breakdown, chat 독립서비스가 신규 추가.

### ⏸ 보류 목록 (2차/서비스 단계)
- ~~**OCR 서비스** #16·17~~ → **실배포·기동 완료**(backend=Gemini Vision). 실 영수증 플로우는 pantry `/receipts`(#52).
- ~~**최저가 관심·알림** #29·30 + 이상탐지 #46~~ → **구현 완료**(2026-07-29): price `/api/prices/watch` CRUD + 탐지 배치 `detect_price_anomaly.py --emit` + fan-out 컨슈머 `consume_price_anomaly.py`. 알림 생성은 관심 등록·알림설정 ON·7일 쿨다운을 모두 통과한 유저만(`ai-spec.md §2`).
- **알림 설정** #43·44 · **가격 이력 그래프**(#27 백엔드는 있음) · **google OAuth** · **NER 서빙**(#45) · **랭킹**(#47 serving 실행·mealplan flag off로 미호출)

---

## 개발 분담안 (초기 · 대부분 구현 완료)

> 2026-07-15 도메인 기준 분할안. 현재는 8개 백엔드 서비스가 배포되어 **대부분 완료**. 이력 참고용.

- **🅰 Dev A — 인증·냉장고**: Auth #2–6 · User/예산 #7–10 · Pantry #11–15 → ✅ 완료
- **🅱 Dev B — 장보기·식비·콘텐츠**: MealPlan #32 · Cart #33–36 · Expense #38–40 · Notification #41–42 · 레시피북 #20–22 · Price #26–27 → ✅ 대부분 완료
- **🤖 AI 담당 — 추출·ML**: OCR #16–17 · YouTube #24–25 · NER #45 · 랭킹 #47 → **OCR 실배포**·YouTube mock, ML 서빙(랭킹 serving 실행·flag off) P1
- **🔗 접점**: OCR 결과 저장 = pantry `/receipts`(#52) · YouTube 결과 저장 = recipebook `/mine`(#56)

---

## 응답 스키마 상세 — 데이터 티어 (실 DB 컬럼 기준)

> **적재 완료된 `foodbudget` DB 실 컬럼 기준.** 소스: [`docs/prd/schema-public-data.sql`](../prd/schema-public-data.sql) + DB introspection.

### 공통 규약
- **가격은 `numeric`(원 단위 정수)** — 표시 포맷은 클라이언트가 변환.
- `source` = `'kurly'` | `'oasis'` · `retail_price.deal_type` = `'general'` | `'closeSale'`
- `retail_product.storage`(오아시스) = `'냉장'` | `'신선'` · `cooking_time` = `'30분 이내'` 텍스트
- `item_id` 매칭률 ~89% — 미매칭 상품은 `item_id=null`(품목 축 조인서 제외)

### #18 `GET /api/recipes` → `recipes[]`  (table: `recipe`)
`id, source, name, category, cook_method, cooking_time, level_nm, kcal, serving, image_url`
※ 10K 소스는 `category·cook_method·kcal·image_url` 대체로 `null`. **서빙=10K만**. 필터 `?cooking_time=&level=` 지원.

### #19 `GET /api/recipes/{id}` → `recipe, ingredients[], steps[], nutrition?`
- `recipe`: #18 컬럼 + `carb_g, protein_g, fat_g, sodium_mg`
- `ingredients[]` (`recipe_ingredient`): `seq, ingredient_name, quantity, item_id, ner_status`
  - **재료 최저가**(`retail_item_price_compare`, `item_id` 조인): `lowest_source, lowest_krw_per_100g, kurly_krw_per_100g, oasis_krw_per_100g`
  - **재료 100g 영양**(`food_nutrition`, `item_id` 조인): `kcal_100g, protein_100g, carb_100g, fat_100g, sodium_100g`
- `steps[]` (`recipe_step`): `step_no, description, image_url`

### #26 `GET /api/prices/{itemCode}` → `price`
- 소매 최신 (**`retail_unit_price` 물질화 뷰** · 크롤 후 REFRESH + Redis 캐시): `source, price, deal_type, won_per_100g, won_per_piece, piece_unit, won_per_100ml, crawled_at`
- 시세 baseline (`price_online_daily`): `survey_date, price_min, price_med, price_max, obs_count`

### #28 `GET /api/prices/recommend` → `items[]`  (view: `retail_item_price_compare`)
`item_id, canonical_name, category, kurly_100g, oasis_100g, kurly_n, oasis_n, kurly_100ml, oasis_100ml`

### #31 `GET /api/prices/hotdeals` → `deals[]`  (`retail_product` + `retail_price`)
- 상품: `id, source, name, image_url, item_id, weight_g, storage, origin, expiry_text`
- 가격/딜: `price, original_price, discount_rate, deal_type, timedeal_end, unit_price, unit_basis, is_sold_out`

### #37 `POST /api/mealplan/assistant/chat` → `reply, basis[], actions[], unanswered`
- `reply`(문장) · `basis[]`(근거: `price_snapshot`/`nutrition`/`recipe_match`) · `actions[]`(`open_recipe`/`add_to_cart`) · `unanswered`(무근거 거절)
- 생성=Gemini(prod, cost-break 가드) · 추출=gazetteer 규칙 · 개인화(재고·예산)=account 연동.

### 참고 — 프론트 정렬
`frontend/src/lib/types.ts`에 위 컬럼 반영. 데이터 티어부(#18·19·26·28·31·37)는 실 컬럼명·값으로 연동 완료.
