# Pantry Service — 냉장고 재고 (api-spec #11~15)

월 식비 밀플래닝 앱의 **냉장고 재고** 서비스. 유저별 재고 CRUD + 소비기한 임박 조회.
`services/account/` **레퍼런스 패턴을 복제**했다(주입 seam · raw psycopg `row_factory=dict_row` · DB-free 테스트).
스키마 정본 = [`docs/prd/schema-production.md`](../../docs/prd/schema-production.md) §pantry.

## 엔드포인트
| # | 메서드·경로 | 동작 | 인증 |
|---|---|---|---|
| 11 | `GET /api/pantry/items` | 내 ACTIVE 재고 목록(소비기한 임박순) | O |
| 12 | `POST /api/pantry/items` | 수동 추가. `expire_at` 미입력 시 shelf_life_ref로 추정 | O |
| 13 | `PATCH /api/pantry/items/{id}` | 부분수정 + status 전이(CONSUMED/DISCARDED→closed_at) | O |
| 14 | `DELETE /api/pantry/items/{id}` | 하드삭제(오입력 정정 전용) | O |
| 15 | `GET /api/pantry/expiring?within_days=3` | 소비기한 임박 목록(기본 3일·상한 30) | O |

- **소모/폐기 ≠ 삭제**: "다 먹음/버림"은 **#13 status 전이**(`closed_at` 기록 → 성과지표 '안 버린 재료 %'용 이력 보존). **#14 DELETE는 오입력 정정 하드삭제 전용.**
- **파생값 미반환**: D-day·신선도는 프론트가 계산(신선도 `fresh`는 P1 AI 소관, Dev A 범위 밖).

## 소비기한 추정 (`app/estimate.py`)
`expire_at` 미입력 + 표준품목(`item_id`) 있으면 `public.shelf_life_ref`를 `(item_id, storage)`로 조인 →
**담은날 + `days_max`**(소비기한 상한; `days_max` null이면 `days_min` 폴백, 둘 다 null이면 추정 불가→null)를 계산해 `date`로 저장. 임박 조기화는 저장값이 아니라 `#15`의 `within_days` 창이 담당.
- ⚠️ `shelf_life_ref`는 **문서상 `data.*`이나 현재 물리 위치는 `public.*`**(public→data 이전 시 일괄 치환).
- ⚠️ `item_id` 앵커는 **CURATED 153품목만** 커버 → 미앵커 재료는 조회 실패 → `expire_at` null(유저입력 대기).

## 보안 ([MP K8s 보안 설계·준수사항](../../docs/design/mp_k8s_security_design.md))
- **A01 접근제어**: 모든 쿼리 `WHERE user_id = <JWT uid>`. 요청 바디의 user_id 안 믿음. 타유저 PATCH/DELETE는 **존재도 노출 없이 404**. → 미인증·타유저 테스트(`test_*_requires_auth`, `*_other_user_*_404`).
- **A05 인젝션**: 입력=Pydantic(타입·길이·범위) → 위반 422. SQL=전부 `%s` 파라미터 바인딩(컬럼명만 고정 화이트리스트 상수).
- **A07 인증**: account 발급 JWT를 로컬 서명·만료·타입 검증(`app/security.py`). 위조/만료/refresh-혼용 거부(`tests/test_security.py`).
- **A04**: 시크릿은 `.env` 주입(`.env.example` 참고), 코드/로그/이미지 미포함(`.dockerignore`).
- **A03**: `requirements.txt` 버전 고정, bcrypt 미포함(토큰 소비자).

## 실행 / 테스트
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # PGPASSWORD·JWT_SECRET(account와 동일) 채우기
pytest                  # DB·서버 없이 33 tests 통과 (주입 seam + FakeConn)
uvicorn app.main:app --host 0.0.0.0 --port 8005
```
Docker: `docker build -t fb-pantry . && docker run --env-file .env -p 8005:8005 fb-pantry`
(비루트 uid 10001 실행 — `docker run --rm fb-pantry id`로 확인).

## 미정·후속 (팀 정렬 필요)
- **포트 SoT(확정, CONVENTIONS §5)** — pantry=**8005**. 서비스별 고정·무충돌(recipe 8001 … notify 8008), Dockerfile `--port`·vite 일치. compose 파일화는 후속.
- **크로스서비스**: OCR 영수증 저장(#16~17)은 **AI팀**이 같은 `POST /pantry/items`로 저장(Dev A 범위 밖). 예산·지출 연동은 DB 조인 말고 API 호출(MealPlan/User).
- **role/GRANT 미적용**(전부 `fbapp` 소유) · **public→data 스키마 이전** — 적용 시 `public.shelf_life_ref`·`public.item_master` 참조 일괄 치환.
- Docker 이미지 **Trivy 스캔(§A03)** = CI 후속. 이 환경엔 docker 없어 빌드/run 검증 미실시(코드는 pytest로 검증).
