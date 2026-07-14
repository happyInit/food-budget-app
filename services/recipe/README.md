# Recipe Service

레시피 탐색·상세 (데이터 티어 읽기). `docs/design/api-spec.md` #18·#19 대응.

## 엔드포인트
| Method | Path | 설명 |
|---|---|---|
| GET | `/health` | 헬스체크 |
| GET | `/api/recipes?q=&tag=&page=&size=` | 레시피 탐색·검색 (#18) |
| GET | `/api/recipes/{id}` | 레시피 상세 — 재료·조리순서·영양·재료 최저단가 (#19) |

- 소스: `recipe`·`recipe_ingredient`·`recipe_step` + 재료 최저단가는 `retail_item_price_compare` 뷰 조인.
- 검색 백엔드: 기본 **PG(ILIKE + 재료조인)**. `index_recipes_es.py`로 ES `recipes` 인덱스 적재 후 `SEARCH_BACKEND=es` 로 전환(nori 형태소).
- JWT 미검증 (Gateway/Auth 서비스 도입 시 추가). chat 서비스와 동일 방침.

## 로컬 실행
```bash
cp .env.example .env   # PGPASSWORD 등 채우기 (커밋 금지)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
# curl 'http://localhost:8001/api/recipes?q=김치&size=5'
# curl 'http://localhost:8001/api/recipes/7'
```

## 환경변수 (.env)
```
PGHOST=192.168.0.8
PGPORT=5432
PGDATABASE=foodbudget
PGUSER=fbapp
PGPASSWORD=***
SEARCH_BACKEND=pg
```
