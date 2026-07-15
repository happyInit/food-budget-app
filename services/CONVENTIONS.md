# 서비스 코드 컨벤션 (백엔드 공용)

> **대상: 백엔드 개발자(김봉수·윤태현).** 8개 서비스를 **같은 구조·같은 테스트 방식**으로 찍어내기 위한 정본.
> **정본 레퍼런스 = [`services/account/`](./account/)** — 새 서비스는 이 디렉터리를 복사해 시작한다. (아키텍처 리뷰 후보 #3 반영: `state[…]` 로케이터 → 주입 seam.)

---

## 0. 새 서비스 만드는 법 (5줄 레시피)
1. `services/account/` 구조를 복사 → 스키마/테이블명만 교체.
2. `context.py`의 **AppCtx·get_conn·get_current_user·get_security 는 그대로** 둔다.
3. `queries.py`는 **`conn`을 받는 async 함수**로 작성(`SELECT … account.app_user …`).
4. 핸들러는 `Depends(get_conn)`·`Depends(get_current_user)`로 의존성을 **주입**받는다.
5. `tests/test_routes.py`의 **override 패턴**을 복사 → DB 없이 즉시 테스트.

---

## 1. 절대 규칙 (통일성의 핵심)

| 규칙 | O (account 레퍼런스) | X (price/recipe 옛 패턴) |
|---|---|---|
| 의존성 | **AppCtx를 `Depends`로 주입** | ~~`state: dict` 전역 로케이터~~ |
| 설정 | Settings를 lifespan서 만들어 **ctx에 담음** | ~~모듈 전역 `settings` 를 함수 안서 읽음~~ |
| 풀 | `make_pg_pool(settings)` **파라미터** | ~~전역 읽는 `make_pg_pool()`~~ |
| 쿼리 | **`conn`을 받음**(트랜잭션 제어 = checkout 대비) | ~~`pool`을 받아 내부서 커넥션 열기~~ |
| 행 매핑 | 풀 **`row_factory=dict_row`** → `row["email"]` (컬럼=모델이면 `Model(**row)`) | ~~위치 언패킹 `row[0]`~~ |
| 에러 | psycopg 예외 → `HTTPException`로 **매핑**(예: UniqueViolation→409) | 미매핑 500 방치 X |
| 프론트 파생값 | 저장/반환 X (₩·D-day·% 는 프론트) | — |

## 2. 테스트 (DB 없이 태어날 때부터)
- **딥 모듈**(security 등)은 **인터페이스로 순수 검증** — `tests/test_security.py`.
- **핸들러**는 `app.dependency_overrides[get_conn] = lambda: FakeConn([...])` 로 fake 주입 — `tests/test_routes.py`, `tests/fakes.py`.
- 인증 필요 핸들러는 `dependency_overrides[get_current_user] = lambda: 7`.
- `pytest.ini`에 `pythonpath = .` + `testpaths = tests`. **`pytest` 하나로 DB·서버 없이 통과.**
- 무엇을 테스트하나: SQL 매핑·에러 코드·크로스서비스 합성·순수 로직. **뻔한 CRUD 패스스루는 스킵**(해커톤 비례).

## 3. 스키마 · 서비스 경계 (schema-production.md 정본)
- **스키마-퍼-서비스**: 각 서비스는 자기 스키마 소유(`account`·`pantry`·…). 데이터 티어(`public`)는 읽기 공용.
- **FK 정책**: 같은 스키마=진짜 FK / **크로스-서비스=논리 `bigint`값(FK 없음)** / data=진짜 FK.
- **크로스-서비스 데이터는 DB 조인 말고 API 호출.** 예: MealPlan의 예산 필요 → `account.user_budget` 직접 조인 X → **User API 호출**.
- **JWT는 account가 발급, 나머지는 신뢰(재검증 안 함).** `user_id`는 토큰에서 온 값.

## 4. 네이밍 · 도메인
- 유비쿼터스 언어 = [`CONTEXT.md`](../CONTEXT.md) (표준 품목·Gazetteer·소비기한·레시피북 등). 코드·API 이름을 여기에 맞춘다.

## 5. 포트 (SoT — 2026-07-15 확정)
서비스별 고정·무충돌. 각 서비스 `Dockerfile`(EXPOSE/`--port`) · `frontend/vite.config.ts` 프록시 · 크로스서비스 base_url 이 **이 표를 정본**으로 따른다.

| 포트 | 서비스 | | 포트 | 서비스 |
|---|---|---|---|---|
| 8001 | recipe | | 8005 | pantry |
| 8002 | price | | 8006 | recipebook |
| 8003 | chat | | 8007 | mealplan |
| 8004 | account | | 8008 | notify |

- 로컬 병렬 실행 = 위 포트로 각자 기동(무충돌). 필요 시 `VITE_<SVC>_ORIGIN` env 로 프록시 오버라이드.
- 크로스서비스 호출(예: mealplan→account/pantry)은 docker 네트워크 호스트명+포트(`http://account:8004`) — `.env` 주입.
- ⏭ 후속: 팀 공용 `docker-compose.yml`에 이 맵을 옮겨 단일 기동(현재는 각 Dockerfile/README가 정본).

---

## ⚠️ 팀이 정렬해야 할 것 (착수 전 합의)

1. ~~DB 접근 방식~~ → **결정(2026-07-15): raw psycopg + `row_factory=dict_row`.** ORM 미사용. 근거: 스키마 SSOT가 이미 SQL(`schema-production.sql`), 읽기 서비스는 어차피 생 SQL(뷰·LATERAL), 해커톤에 ORM 러닝커브 회피, `dict_row`로 매핑 fragility 해소. → `tech-stack.md`의 "SQLAlchemy+Alembic" 항목 정정함.
2. ~~마이그레이션 도구~~ → **결정: 멱등 DDL**(`schema-production.sql` + `apply_schema.py`/`migrate_*.py` 패턴). Alembic 미사용.
3. ~~포트/compose SoT~~ → **결정(2026-07-15): §5 포트 표**(recipe 8001 … notify 8008, 무충돌). Dockerfile·vite·크로스서비스 URL 일괄 정렬 완료. `docker-compose` 파일화는 후속.
