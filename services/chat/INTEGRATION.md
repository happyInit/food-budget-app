# Chat Service 통합 가이드 (백엔드 담당자용)

> 대상: 이 RAG 챗봇을 서비스에 연동·배포할 백엔드 담당자.
> 작성: 건우 (AI 담당) · 2026-07-15
> 로컬 개발 세팅은 [`README.md`](README.md), 설계 배경은 [`docs/chat-assistant-ai.md`](../../docs/chat-assistant-ai.md), 생성 백엔드 비용은 [`docs/chat-gemini-adoption.md`](../../docs/chat-gemini-adoption.md).

---

## 1. 이게 뭔가 · 아키텍처 위치

`design.md §5`의 **MealPlan 서비스 중 "대화형 어시스턴트"** 부분을 담당하는 독립 FastAPI 서비스다. 유저의 자연어 질문을 받아 **자체 DB(레시피·가격·영양)를 검색·조립해 답하는 RAG 파이프라인**이다.

```
유저 질문 → [Gateway] → Chat Service(:8003)
                          ① 질문분석 → ② DB 병렬검색(ES·PG) → ③ 컨텍스트 조립
                          → ④ 생성(template 기본 / gemini opt-in) → ⑤ 응답조립(근거+액션버튼)
```

**백엔드가 알아야 할 핵심**: 이 서비스는 상태를 안 가진다(stateless HTTP). fb-data(.8)의 PG·ES·Redis를 **읽기**로만 쓴다. 유저 데이터를 쓰지 않는다.

---

## 2. API 계약

### 엔드포인트

| 메서드·경로 | 용도 |
|---|---|
| `GET /` | **시연용 채팅 UI**(같은 오리진 HTML). 브라우저로 `http://<host>:8003/` 열면 실서비스와 대화 가능 |
| `GET /health` | 헬스체크 → `{"status":"ok"}` |
| `POST /chat` | 챗봇 질의(개발·직접호출용) |
| `POST /api/mealplan/assistant/chat` | **위와 동일 로직의 별칭** — `design/api-spec.md #37` 스펙과 정합. Gateway가 이 경로로 프록시하면 코드 변경 없이 연결됨 |

### 요청 (`ChatRequest`)

```json
{
  "message": "두부랑 대파로 뭐 해먹지",
  "user_id": "optional-문자열"
}
```

- `message`: 필수, 1~500자.
- `user_id`: 선택. **현재 검증하지 않음**(Gateway/JWT 부재) — 전달만 하며 향후 개인화·일일상한 스코핑 자리. 지금은 넣어도 무시된다.

### 응답 (`ChatResponse`)

```json
{
  "reply": "두부와 대파로 만들 수 있는 '대패대파구이', '소고기 대파 볶음'을 추천해요!",
  "basis": [
    {"type": "recipe_match", "item_id": null, "source": null, "crawled_at": null, "detail": "대패대파구이"}
  ],
  "actions": [
    {"label": "대패대파구이 레시피 보기", "action": "open_recipe", "recipe_id": 12345, "item_id": null},
    {"label": "장바구니 담기", "action": "add_to_cart", "recipe_id": null, "item_id": 9}
  ],
  "unanswered": false
}
```

**필드별 프론트/백엔드 사용법:**

| 필드 | 의미 | 사용 |
|---|---|---|
| `reply` | 유저에게 보여줄 답변 문장 | 채팅 버블에 그대로 출력 |
| `unanswered` | `true`면 "모르겠어요"(근거 없음/오프토픽) | `true`면 액션버튼·근거 UI 숨김 처리 권장 |
| `basis[]` | 답의 **근거 태그** (환각 아님을 보증) | `type`별로 "가격 스냅샷 시각"·"영양 출처" 등 근거 칩 렌더 |
| `actions[]` | 답에 붙는 액션 버튼 페이로드 | `open_recipe`(recipe_id로 레시피 상세)·`add_to_cart`(item_id로 장바구니) 버튼 |

`basis[].type` = `recipe_match`(레시피 추천) · `price_snapshot`(가격, `source`·`crawled_at` 포함) · `nutrition`(영양).
`actions[].action` = `open_recipe`(recipe_id) · `add_to_cart`(item_id).

### 응답 3패턴 예시

| 질문 유형 | reply 예 | basis | unanswered |
|---|---|---|---|
| 레시피 추천 | "…추천해요!" | `recipe_match`×N | false |
| 가격 | "kurly 5,490원 · oasis 9,900원" | `price_snapshot`×N | false |
| 오프토픽/무근거 | "모르겠어요 — 관련 레시피를 찾지 못했습니다." | `[]` | **true** |

---

## 3. 실행 · 배포

### Docker (권장 — 배포 대상: fb-app-ai `.9`)

빌드 컨텍스트가 **레포 루트**다(gazetteer를 `pipelines/ingest`에서 끌어옴):

```bash
# 레포 루트에서
docker build -f services/chat/Dockerfile -t chat-service .
docker run -p 8003:8003 --env-file services/chat/.env chat-service
```

`docker-compose.yml`에 붙일 때도 `build.context: .` / `dockerfile: services/chat/Dockerfile` 로 루트 컨텍스트 유지.

### 로컬 (Docker 없이)

[`README.md`](README.md) 참고 — venv + `.env`(레포 루트 `.env.example` 복사) + `uvicorn app.main:app --port 8003`.

---

## 4. 환경변수 (`.env`)

`services/chat/.env.example` 복사해서 채운다. `.env`는 gitignore — **커밋 금지**.

| 변수 | 기본 | 설명 |
|---|---|---|
| `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD` | .8 / 5432 / foodbudget / fbapp / — | 데이터 티어 PG (비번 필수) |
| `ESHOST/ESPORT` | .8 / 9200 | Elasticsearch(nori) |
| `REDISHOST/REDISPORT` | .8 / 6379 | Redis(캐시) |
| `GENERATOR_BACKEND` | `template` | `template`(무료·무승인 기본) \| `gemini`(opt-in) |
| `EXTRACTOR_BACKEND` | `rule` | `rule`(gazetteer) \| `ner`(CRF 완성 후) |

**생성 백엔드 정책**: 기본 `template`(외부 API 0원). `gemini`는 실험용 opt-in이며 **프로덕션 활성은 팀 재승인 필요**(`chat-gemini-adoption.md`). `gemini` 사용 시 `GEMINI_API_KEY` 등 추가 변수는 `.env.example` 주석 참고.

---

## 5. 의존성 (전제 조건)

배포 전 fb-data(.8)에 아래가 준비돼 있어야 한다:

- **PG `foodbudget`**: `recipe`·`recipe_ingredient`·`retail_product`·`retail_price`·`food_nutrition`·`item_master` 적재 완료 (데이터팀 담당, 현재 적재됨)
- **ES `recipes` 인덱스**: `pipelines/ingest/index_recipes_es.py` 실행 필요. **레시피 재적재 시 이 인덱서 수동 재실행** 필요(자동 훅 없음)
- **Redis**: gemini 백엔드의 다듬기 캐시용(없어도 동작, 캐시만 skip)

---

## 6. 통합 지점 (백엔드가 연결할 곳)

1. **Gateway 라우팅**: Gateway 생기면 `POST /api/mealplan/assistant/chat` → Chat Service(:8003)로 프록시. 경로가 이미 스펙(#37)과 일치해 코드 변경 불필요.
2. **인증**: 현재 user_id 미검증. Gateway/JWT 도입 시 Gateway가 검증한 user_id를 바디로 전달하면, 챗봇은 그걸 개인화·일일상한에 쓸 준비만 돼 있음(지금은 무시).
3. **프론트**: `frontend/src/pages/Assistant.tsx`가 이 엔드포인트를 호출하도록 연결. 응답의 `reply`·`actions`를 렌더.

### 6.1 ⚠️ CORS / 같은 오리진 — 프론트 연동 전 반드시 확인

**현재 이 서비스에는 CORS 미들웨어가 없다.** 그래서 프론트(예: dev `:5173`, 배포 nginx)가 **다른 오리진**에서 `:8003/chat`으로 직접 `fetch` 하면 **브라우저가 CORS로 차단**한다. (데모 UI `GET /`가 됐던 건 챗봇이 HTML+API를 **같은 오리진**에서 서빙했기 때문.)

> CORS는 물리 서버가 아니라 **`scheme://host:port`(오리진)** 로 판단한다 — 같은 VM에 다른 포트로 올려도 오리진이 다르면 여전히 막힌다.

**해결 (권장 순):**

1. **[권장·프로덕션] 리버스 프록시로 같은 오리진 묶기** — nginx(또는 Gateway)가 `앱주소/`는 프론트 정적파일, `앱주소/api/…`는 Chat Service(:8003)로 프록시. 브라우저는 **한 오리진**하고만 통신 → **CORS 불필요, 미들웨어 없이 그대로 동작**. 배포는 이 방식으로 진행한다(nginx:alpine 프론트 서빙 + `/api` 프록시). 프론트는 `POST /api/mealplan/assistant/chat` 상대경로로 호출하면 됨.
2. **[dev/임시] CORS 미들웨어 추가** — Gateway/프록시 없이 프론트가 직접 호출해야 하면, 서비스에 `CORSMiddleware`(허용 오리진 = 프론트 도메인)를 추가. ⚠️ 아직 미구현 — **필요 시 별도 작업**(허용 오리진은 보안 설정이라 dev=localhost / 배포=앱도메인으로 명시).
3. **[dev 대안] Vite 프록시** — `vite.config.ts`의 `server.proxy`로 `/api` → `http://localhost:8003` 라우팅(dev 한정).

**요약**: 배포는 **리버스 프록시(같은 오리진)** 로 가면 CORS가 필요 없다. 프록시 없이 브라우저에서 직접 붙일 때만 CORS 미들웨어(별도 작업)가 필요하다.

---

## 7. 지금 되는 것 / 아직 안 되는 것 (중요)

백엔드가 **기대하면 안 되는 것**을 명확히:

| 기능 | 상태 |
|---|---|
| 레시피 추천·가격·영양 답변 | ✅ 동작 (실데이터, 검증 100% — `validation/VALIDATION_LOG.md`) |
| 오프토픽/무근거 거절 | ✅ 동작 (근거 없으면 `unanswered=true`) |
| **개인화("내 냉장고에 두부 있으니…")** | ⛔ **스텁**(`StubPantryBudgetSource`, `available=False`) — Pantry/User 스키마·서비스 필요 |
| **NER 재료 정규화** | ⛔ 규칙(gazetteer)로 임시 동작. CRF NER 완성 후 `EXTRACTOR_BACKEND=ner` 전환 |
| **인증·user 스코핑** | ⛔ 없음. 현재 "누구나 호출 데모" |
| 멀티턴(후속질문) | ⛔ 미구현(단발 질의만) |

→ 즉 지금은 **"개인 상태를 모르는 공용 레시피·가격 어시스턴트"** 수준이다. 개인화(핵심 차별점)는 Pantry/User 서비스가 생겨야 열린다.

---

## 8. 헬스체크·검증

- `GET /health` → `{"status":"ok"}` (기동 시 PG·ES·Redis 연결 + gazetteer 로드 성공해야 200)
- 스모크: `curl -X POST localhost:8003/chat -H 'Content-Type: application/json' -d '{"message":"김치찌개 레시피 알려줘"}'`
- 회귀 검증: `python validation/runner.py --label "배포전점검" --note "..."` → `VALIDATION_LOG.md` 누적
- 유닛: `pytest tests/`
