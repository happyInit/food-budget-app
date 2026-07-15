# MealPlan Service

Cart(장바구니) + Expense(식비) + Recommend(추천). api-spec **#32~40**(Dev B 소비 흐름). 포트 **8007**.
스키마 = `mealplan`(cart_item·expense), `docs/prd/schema-production.sql` §mealplan.
레퍼런스 패턴 = [`services/account/`](../account/) — 구조·주입 seam·테스트 방식 복제.

## 구조 (account 복제)

| 파일 | 역할 |
|---|---|
| `config.py` | Settings (전역 인스턴스 없음 — ctx에 담김) + 크로스서비스 base URL |
| `db.py` | `make_pg_pool(settings)` — settings 주입, `row_factory=dict_row` |
| `security.py` | JWT 딥 모듈(account 발급 토큰을 `verify_access` 검증만) |
| `context.py` | **AppCtx + 주입 seam** + **크로스서비스 provider seam**(budget/pantry) |
| `models.py` | Pydantic 요청/응답 (타입·길이·범위·Literal 검증 = A05) |
| `queries.py` | SQL — **conn 을 받음**(checkout 트랜잭션 제어), `mealplan.*` + public 읽기 조인 |
| `ranking.py` | **순수 레시피 랭킹**(#32) — DB 무관, `tests/test_ranking.py`로 완전 검증 |
| `routers.py` | 핸들러 3라우터(cart·expense·recommend), Depends 주입 |
| `main.py` | lifespan이 AppCtx 조립(+ HTTP provider 어댑터) + 3라우터 등록 |

## 엔드포인트 (전부 인증 O — Bearer access token)

| # | 메서드 | 경로 | 설명 | 구현 |
|---|---|---|---|---|
| 33 | GET | `/api/mealplan/cart` | 장바구니 + 품목별 더 싼 소스가(least(kurly,oasis)) | 실 + budget seam |
| 34 | POST | `/api/mealplan/cart/items` | 재료/레시피 담기 → `{id}` (201) | 실 |
| 35 | DELETE | `/api/mealplan/cart/items/{id}` | 항목 제거(소유권 WHERE user_id, 없으면 404) → 204 | 실 |
| 36 | POST | `/api/mealplan/cart/checkout` | 합계 → 지출(GROCERY/CART) 기록 → 장바구니 비우기 | 실(한 트랜잭션) |
| 38 | GET | `/api/expenses/calendar?month=YYYY-MM` | 일자별 지출 합 | 실 |
| 39 | POST | `/api/expenses` | 지출 기록 → `{id}` (201) | 실 |
| 40 | GET | `/api/expenses/summary?month=YYYY-MM` | `spent`(실) + `budget/remain/saved_ingredients`(seam) | 실 + seam |
| 32 | POST | `/api/mealplan/recommend` | 재고·임박·예산 기반 레시피 랭킹 | 순수랭킹 + pantry seam |

- `month` 는 Pydantic(`^\d{4}-\d{2}$` + 실월 검증) 후 **해당 월 1일 `date`로 파라미터 바인딩**(A05).
- 합계(subtotal/checkout amount) = Σ(품목 더 싼 100g 단가 × 수량), 단가 미상 품목 제외(정본=`_cart_subtotal`).

## 크로스서비스 seam (schema-per-service: DB 조인 금지 → API 호출)

`account.user_budget`·`pantry.pantry_item` **직접 조인 금지**. `context.py`에 Protocol + 주입:

- **BudgetProvider** (`get_budget`) = account User API(#9). #33 예산·#40 remain 에 사용.
- **PantryProvider** (`get_pantry`, `saved_ingredients`) = pantry API. #32 재고·#40 안버린재료.
- 실제 HTTP 어댑터(`HttpBudgetProvider`/`HttpPantryProvider`)는 **TODO** — 미배선/실패 시
  `ProviderUnavailable` → 핸들러가 **degrade**(예산·seam 필드 `null`, #32 는 빈 목록 + `note`).
- 테스트는 `dependency_overrides[get_budget_provider/get_pantry_provider]` 로 fake 주입.

**self-contained(#34·35·36·38·39·cart 조회·월 합계)는 완전 실구현.** seam 붙은 부분만 어댑터.

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env        # PGPASSWORD·JWT_SECRET(account와 동일값) 채우기
uvicorn app.main:app --reload --port 8007
```

## 테스트 (DB·서버·크로스서비스 불요)

```bash
pytest
```
- `test_ranking.py` — 순수 랭킹(커버리지·임박 보너스·예산 페널티·그룹핑) 단위테스트.
- `test_routes.py` — 주입 seam으로 핸들러 검증: SQL 매핑·에러코드(400/404/422)·인증없이 401·소유권(WHERE user_id).
- `test_security.py` — JWT 딥 모듈 계약.

## 포트

mealplan=**8007**. 포트 SoT = **CONVENTIONS §5**(서비스별 고정·무충돌). 크로스서비스 호출은 account `:8004`·pantry `:8005`(`.env`의 `*_BASE_URL`). compose 파일화는 후속.
