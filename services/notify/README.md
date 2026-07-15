# Notify Service

알림함(Notification) — 목록 조회 + 읽음 처리. api-spec **#41~42**. 포트 **8006**.
스키마 = `notify`(`notification`), `docs/prd/schema-production.sql`.
구조는 정본 레퍼런스 [`services/account/`](../account/)를 복제(주입 seam·`row_factory=dict_row`·conn 받는 쿼리).

## 신원 / 보안
- account가 발급한 **access JWT를 검증만** 한다(발급 X) → `security.verify_access`. `.env`의 `JWT_SECRET`은 account와 **동일**해야 함.
- `user_id`는 **JWT에서만**(요청 바디/쿼리 신뢰 X, A01). 모든 쿼리에 `where user_id = %s`(소유권, A01).
- SQL은 전부 `%s` 파라미터 바인딩(A05). `unread` 필터는 고정 SQL 조각을 bool로 붙일지 결정할 뿐(사용자 문자열 결합 없음).
- 입력 검증(A05): `type`은 `Literal`(LOW_PRICE/EXPIRING/HOTDEAL/BUDGET), path `{notification_id}`는 int.

## 엔드포인트 (전부 인증 O)

| # | Method | Path | 설명 | 응답 |
|---|---|---|---|---|
| 41 | `GET` | `/api/notifications?unread=<bool>` | 알림함 목록(최신순, `unread=true`면 안 읽은 것만) | `{notifications:[{id,type,title,body,payload,is_read,created_at}]}` |
| 42 | `PATCH` | `/api/notifications/{id}/read` | 읽음 처리(`is_read=true`, 소유자만) | `{id, is_read:true}` / 없거나 남의 알림 → `404` |

크로스서비스 seam 없음(알림 **발행**은 파이프라인/워커 몫, 이 서비스는 **읽기 API**만).

## 파일 맵 (account 구조 복제)

| 파일 | 역할 |
|---|---|
| `config.py` | Settings (전역 인스턴스 없음 — ctx에 담김. notify는 TTL 미사용) |
| `db.py` | `make_pg_pool(settings)` — settings 주입, `row_factory=dict_row` |
| `security.py` | 딥 모듈(account 복제): 여기선 `verify_access`만 사용, `tests/test_security.py` |
| `context.py` | AppCtx + 주입 seam(get_conn/get_current_user/get_security) |
| `models.py` | Pydantic 응답(NotificationOut·NotificationListOut·MarkReadOut) |
| `queries.py` | SQL — **conn 을 받음**, `notify.notification` |
| `routers.py` | 핸들러(#41~42), Depends 주입 |
| `main.py` | lifespan이 AppCtx 조립 + 라우터 등록 |

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env        # JWT_SECRET(account와 동일)·PGPASSWORD 채우기
uvicorn app.main:app --reload --port 8006
```

## 테스트 (DB 불요)

```bash
pytest
```
- `test_security.py` — 딥 모듈을 인터페이스로 검증(순수).
- `test_routes.py` — 주입 seam으로 핸들러 검증: SQL 매핑·`unread` 필터·401(미인증)·404(소유권)·WHERE user_id 파라미터.

## 포트

notify=**8006**. ⚠️ CONVENTIONS §5 대로 **포트/compose SoT는 팀 미정** — account=8003, price/recipe Dockerfile 8000 충돌 이슈와 함께 공용 `docker-compose`에 포트 SoT를 두는 것이 숙제. 여기 8006은 태스크 배정값(잠정).
