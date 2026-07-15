# Account Service (레퍼런스 패턴)

Auth(로그인·JWT 발급) + User(프로필·월 예산). api-spec #2~10. 포트 **8003**.
스키마 = `account`(app_user·user_budget), `docs/prd/schema-production.md` §1.

## ★ 왜 레퍼런스인가 — 주입 seam

price/recipe는 핸들러가 전역 `state[...]` dict + `settings` 싱글턴을 읽어서 **interface 너머를 substitute할 수 없다** → 테스트가 helper 레벨로 밀림(아키텍처 리뷰 후보 #3). 이 서비스는 그걸 고쳐 **두 명이 복사할 본보기**로 만든다:

- **`AppCtx`**(`app/context.py`) = pool·settings·security 를 담은 조립 결과 1개. lifespan이 만들어 `app.state.ctx`에.
- 핸들러는 `Depends(get_conn)`·`Depends(get_current_user)`·`Depends(get_security)`로 **의존성을 주입**받음 — 전역 안 읽음.
- 테스트는 `app.dependency_overrides[get_conn] = lambda: FakeConn([...])` 로 **DB·JWT 없이** 핸들러를 통째 검증(`tests/test_routes.py`).

## 파일 맵 (이 구조를 복사)

| 파일 | 역할 |
|---|---|
| `config.py` | Settings (전역 인스턴스 없음 — ctx에 담김) |
| `db.py` | `make_pg_pool(settings)` — settings 주입 |
| `security.py` | 딥 모듈: 비번 해시 + JWT (순수, `tests/test_security.py`로 완전 검증) |
| `context.py` | **AppCtx + 주입 seam**(get_conn/get_current_user/get_security) |
| `models.py` | Pydantic 요청/응답 |
| `queries.py` | SQL — **conn 을 받음**(트랜잭션 제어 = checkout 대비), `account.*` |
| `routers.py` | 핸들러(#2~10), Depends 주입 |
| `main.py` | lifespan이 AppCtx 조립 + 라우터 등록 |

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env        # JWT_SECRET·PGPASSWORD 채우기
uvicorn app.main:app --reload --port 8003
```

## 테스트 (DB 불요)

```bash
pytest
```
- `test_security.py` — 딥 모듈을 인터페이스로 검증(순수).
- `test_routes.py` — 주입 seam으로 핸들러 검증(fake conn/user).

## 새 서비스 만들 때 (두 명 공용 레시피)

1. 이 디렉터리 구조를 복사 → 스키마/테이블만 교체(예: `pantry`).
2. `context.py`의 AppCtx·get_conn·get_current_user는 **그대로**(신원은 account가 발급한 JWT를 신뢰).
3. `queries.py`는 conn을 받는 함수로 작성 → `test_routes.py`의 override 패턴으로 즉시 테스트.
4. 크로스서비스 데이터(예산·냉장고)는 DB 조인 말고 **해당 서비스 API 호출**(schema-production.md FK 정책).

## 포트

account=**8003**. ⚠️ 현재 price·recipe Dockerfile이 둘 다 8000이라 충돌 — 팀 공용 `docker-compose`에 포트 SoT를 두는 게 숙제(아키텍처 리뷰 "also seen").
