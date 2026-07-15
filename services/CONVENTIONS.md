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

## 5. 포트
- account=8003. **⚠️ price·recipe Dockerfile이 둘 다 8000이라 충돌** — 두 명이 로컬 병렬 실행하려면 **팀 공용 `docker-compose`에 포트 SoT**를 두어야 함(현재 없음, 각 Dockerfile/README도 불일치). **먼저 정할 것.**

---

## ⚠️ 팀이 정렬해야 할 것 (착수 전 합의)

1. **DB 접근 방식 — raw psycopg vs SQLAlchemy.**
   `tech-stack.md`엔 **SQLAlchemy + Alembic**로 적혀 있으나, **실제 서비스(price·recipe·chat)와 이 레퍼런스는 raw psycopg + 생 SQL**을 쓴다. 둘을 섞으면 통일성이 깨짐.
   - 제안: **raw psycopg 유지**(현 3서비스·스키마 SoT `schema-production.sql`과 일관, ORM 러닝커브 없음). 그러면 `tech-stack.md`의 SQLAlchemy 항목을 정정.
   - ORM으로 갈 거면: 레퍼런스를 SQLAlchemy로 다시 잡고 `schema-production.sql` ↔ 모델 매핑 규약을 정해야 함.
   - **어느 쪽이든 하나로.** (이 문서와 레퍼런스는 raw psycopg 기준.)
2. **마이그레이션 적용 도구** — `apply_schema.py`(멱등 DDL) vs Alembic. 위 1과 연동.
3. **포트/compose SoT** (§5).
