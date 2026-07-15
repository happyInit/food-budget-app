# RecipeBook Service

레시피 북마크(스크랩). api-spec **#20~22**. 포트 **8006**.
스키마 = `recipebook`(테이블 `bookmark`만 소유), `docs/prd/schema-production.sql` §recipebook.
데이터 티어 `public.recipe` 는 읽기 조인(진짜 FK: `bookmark.recipe_id → public.recipe(id)`).

> `recipebook.user_recipe`·`extract_job` 은 **AI 담당(#24~25) 몫** → 이 서비스가 만들지 않는다.

## 패턴 (account 레퍼런스 복제)

`config`·`db`·`context`·`security` 는 [`services/account/`](../account/)에서 **그대로 복사**. 핸들러는 전역 `state[...]` 대신 **`AppCtx`를 `Depends`로 주입**받는다(`app/context.py`). 로그인/회원가입이 없어 Security는 **`verify_access`(JWT 검증)만** 사용한다 — account가 발급한 access 토큰을 신뢰(재검증 안 함). 그래서 `.env`의 `JWT_SECRET`/`JWT_ALG`는 account와 **동일**해야 한다.

## 엔드포인트 (전부 인증 O — `Authorization: Bearer <access>`)

| # | 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|---|
| 20 | `GET` | `/api/recipes/book` | 내 북마크 목록(최신순) | `200 {books:[{id, recipe_id, name, image_url, cooking_time, level_nm}]}` |
| 21 | `POST` | `/api/recipes/book` | 레시피 저장 · body `{recipe_id:int}` | `201 {id}` / 중복 `409` / 없는 레시피 `404` |
| 22 | `DELETE` | `/api/recipes/book/{id}` | 북마크 삭제 | `204` / 내 소유 아님·없음 `404` |

### 보안 (OWASP 준수사항)
- **A01 접근제어**: `user_id`는 **JWT에서만**(`Depends(get_current_user)`) — 바디/쿼리의 user_id 불신뢰. 목록/삭제 SQL에 `WHERE user_id = %s` 강제 → 남의 행 접근 시 **404**.
- **A05 인젝션/검증**: 모든 입력 **파라미터 바인딩(%s)**, `recipe_id`는 Pydantic `int, ge=1` 검증.
- 예외 매핑: `UniqueViolation → 409`, `ForeignKeyViolation → 404`.

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env        # PGPASSWORD·JWT_SECRET(account와 동일) 채우기
uvicorn app.main:app --reload --port 8006
```

## 테스트 (DB 불요)

```bash
pytest
```
- `test_routes.py` — 주입 seam으로 핸들러 검증: SQL 매핑·응답, 409/404 에러코드, **인증 없이 401**, **소유권(WHERE user_id 바인딩·남의 행 404)**.
- `test_security.py` — JWT 검증 계약(verify_access) 순수 검증.

## 크로스서비스 seam
없음. 전부 자체 스키마(`recipebook.bookmark`) + 데이터 티어(`public.recipe`) 읽기 조인으로 완결.

## 포트 (SoT — CONVENTIONS §5)
이 서비스 = **8006**. 서비스별 고정·무충돌(recipe 8001 … notify 8008), Dockerfile `--port`·vite 프록시와 일치. compose 파일화는 후속.
