# mp k6 Stage3 — 피크 몰림 × 바이럴 스파이크 (시나리오 정본)

> **문서 상태**: 시나리오 설계 확정 · **실행 전**(2026-08-01 작성). 실측값 칸은 실행 담당자가 채운다.
> **계보**: 정본 [`docs/mp_k6_부하테스트.md`](mp_k6_부하테스트.md) 의 후속. Stage1(서비스별 포화 스윕)·Stage2A(matview 경합)는 그 문서가 정본이고 **여기서 다시 쓰지 않는다.** 이 문서는 정본 §3.7 이 *"경계(미검증, 추정)"* 로 남긴 **recipebook·pantry·notify** 를 실측으로 채우고, 정본 §8.2 가 *"미정"* 으로 남긴 **유저 피크 도착률**을 숫자로 산출한다.
> **스크립트**: [`loadtest/stage3_peak_journey.js`](../loadtest/stage3_peak_journey.js) · [`loadtest/stage3_viral_spike.js`](../loadtest/stage3_viral_spike.js) · [`loadtest/cleanup_test_recipes.js`](../loadtest/cleanup_test_recipes.js)
> **이 테스트의 목적**: "DAU 500 이면 되나?" 를 확인하는 게 아니다(정본 §6.6 이 이미 *과잉 여유* 라고 답했다). 🔴 **"지금 인프라의 한계는 어디까지이고, 병목은 어디인가"의 실측값**을 뽑는 것이다. 그 값이 나와야 다음 규모(성장 가정)를 정할 수 있다.

---

## 1. 무엇을 이어받고 무엇을 새로 여는가

| | 정본 `mp_k6_부하테스트.md` | **이 문서(Stage3)** |
|---|---|---|
| 하네스 | Windows `k6.exe` + WSL interop · Gateway `.14` 직타 · `abortOnFail` | **그대로 승계**(§8) |
| 유입 모델 | Stage1 §3.3 은 **closed**(`ramping-vus`) | 🔴 **open**(`ramping-arrival-rate`) — 몰림은 서버가 느려져도 유입이 계속되므로 closed 는 붕괴를 숨긴다 |
| 측정 대상 | account · recipe · price · mealplan (4분류 완료) | 🔴 **recipebook · pantry · notify**(정본 §3.7 "경계(미검증, 추정)") |
| write | 없음(Stage2B 미실행 → 실제 `TEST-` write 0건) | 🔴 **진짜 write** — `POST /api/recipes/mine` + publish. `TEST-` 접두 + 멱등 cleanup |
| 규모 근거 | "DAU 500 기준 산출(미정)" (§8.2) | 🔴 **산출 완료**(§3) — 가정을 전부 명시한 λ=0.4 세션/s |
| 시나리오 | 딜 골든아워 = *파이프라인 × 유저* 간섭 | **유저 단독 두 패턴** — 식사시간 몰림 / 바이럴 핫키 |
| 가설 번호 | H1~H5 | **H6~H10**(이어서 매김) |
| SLO | 단순조회 p95<500ms · 검색/집계<1s · login<1s · 오류율<1% | **동일 승계** + write p95<1s(신설·잠정) |

**정본 H4 는 이 문서로 넘어오지 않는다.** 정본 H4("새 레시피가 PGSync 로 N초 내 검색 노출")는 **크롤 코퍼스(`public.recipe`) 인제스트 한정**이다. 유저 등록 레시피에는 그 경로가 **아예 없다**(§4.3). Stage3 는 대신 **H10** 으로 재정의해 다룬다.

---

## 2. 왜 이 시나리오인가 — 20-30대 1인가구 페르소나

### 2.1 페르소나 → 유입 패턴
서비스 이용자는 **20-30대 청년 1인가구**다. 이들의 앱 사용은 상시 분산이 아니라 **"오늘 뭐 먹지"를 결정하는 순간**에 붙는다. 그 순간이 하루 두 번(점심 직전 11–12시, 저녁 직전 17–18시) 온다 — 이건 멘토 피드백의 *"예측 가능한 트래픽 스파이크 = 일일 피크타임"* 과 같은 얘기다.

🔴 **시간대 자체는 모방하지 않는다.** 실행 시각을 11시/17시에 맞출 필요 없다. 재현 대상은 **유입의 모양**(평시 → 30분 전 완만 상승 → 직전 급상승 → 피크 고원 → 식사 시작 후 급감)이지 시계가 아니다.

### 2.2 페르소나 → 엔드포인트 믹스 근거
1인가구의 한 세션은 대체로 이 순서를 밟는다. 그래서 믹스를 이렇게 짰다:

| # | 유저의 생각 | 엔드포인트 | 서비스 | 태그 | 신규? |
|---|---|---|---|---|---|
| 0 | (앱 연다) | `POST /api/auth/login` | account | `login` | 기측정 |
| 1 | 오늘 뭐가 싸지 | `GET /api/prices/hotdeals?limit=20` | price | `hotdeals` | 기측정 |
| 2 | 뭐 사면 좋대 | `GET /api/prices/recommend?limit=20` | price | `recommend` | 기측정 |
| 3 | 이번 달 예산 얼마 남았지 | `GET /api/users/budget` | account | `budget` | 기측정 |
| 4 | 그걸로 뭐 해먹지 | `GET /api/recipes?q=<재료>` | recipe(ES) | `recipe_search` | 기측정 |
| 5 | 이거 어떻게 만들지 | `GET /api/recipes/{id}` | recipe(PG) | `recipe_detail` | 🔴 신규 |
| 6 | 맛있대? | `GET /api/recipes/{id}/reviews` | recipe(PG) | `recipe_reviews` | 🔴 신규 |
| 7 | 저번에 저장한 거 뭐였지 | `GET /api/recipes/book` | **recipebook** | `book_list` | 🔴 **신규** |
| 8 | 내가 올린 거 | `GET /api/recipes/mine` | **recipebook** | `mine_list` | 🔴 **신규** |
| 9 | 냉장고에 뭐 상해가지 | `GET /api/pantry/expiring?within_days=3` | **pantry** | `pantry_expiring` | 🔴 **신규** |
| 10 | 알림 왔나 | `GET /api/notifications?limit=20` | **notify** | `notifications` | 🔴 **신규** |

= **세션당 11 요청**(로그인 1 + 브라우징 10). 정본 §3.3 의 저니는 4개(login·search·hotdeals·budget)였다 — 여기서 **7개를 더 태운다**.

🔴 **제외**: `POST /api/recipes/extract`(video·Gemini) · `/api/chat/*` · `/api/ocr/*` — **Bedrock/Vertex/Gemini 실과금**이므로 절대 태우지 않는다(정본 §1.4 승계).

### 2.3 바이럴은 왜 "핫키"인가 — 스키마 제약
🔴 **팔로우/구독 개념이 스키마에 없다.** notify 서비스는 `GET /api/notifications` 와 `PATCH /api/notifications/{id}/read` **두 개뿐**이고(`services/notify/app/routers.py:18,29`), 푸시·구독·fan-out 경로가 **아예 없다.** 즉 "핫한 유저가 레시피를 올리면 팔로워 N명에게 알림이 터진다" 는 시나리오는 **이 서비스에서 재현 불가능하다** — 없는 기능을 부하로 만들 수는 없다.

그래서 "핫함"을 실재하는 두 경로로만 모델링한다:

1. **공유 링크 단일 핫키** — `POST /api/recipes/mine/{id}/share` 또는 `/publish` 가 `share_token` 을 발급하고, 그 링크가 외부 채널(카톡·커뮤니티)로 퍼진다. 그러면 **비인증 `GET /api/recipes/shared/{share_token}` 한 곳에 read 가 집중**된다. = 고전적 핫키.
2. **publish 후 검색 노출** — `POST /api/recipes/mine/{id}/publish` 가 `recipebook.shared_recipe` 에 스냅샷을 올리고, 비인증 `GET /api/recipes/shared?q=` 목록에 뜬다. 프론트(`frontend/src/pages/RecipeSearch.tsx:52`)가 이걸 카탈로그 검색과 **클라이언트에서 합쳐** 보여준다.

---

## 3. 🔴 DAU 500 → 피크 도착률 산출

### 3.1 가정 (전부 가정이다 — 확정 아님)
| # | 가정 | 값 | 성격 |
|---|---|---|---|
| A1 | DAU | **500** | 사용자 확정 baseline |
| A2 | 유저당 일 세션 수 | **1.6** | ⚠️ **가정** — 두 끼 결정 시점에 열지만 매일 두 번 다 열지는 않는다 |
| A3 | 일 세션 총량 | 500 × 1.6 = **800 세션/일** | A1 × A2 |
| A4 | 두 피크창이 흡수하는 세션 비율 | **60%** | ⚠️ **가정** — 멘토 피드백의 "일일 피크타임 11–12·17–18" 을 수치화. 나머지 40% 는 종일 분산 |
| A5 | 피크 세션 | 800 × 0.6 = **480**(창당 240) | A3 × A4 |
| A6 | 실질 압축창 | 창당 **30분**(합 3600s) | ⚠️ **가정** — "식사 직전"이라 1시간 전체가 아니라 절반으로 압축 |
| A7 | 창 내부 집중계수 *k* | **3.0** | ⚠️ **가정** — 30분 중 앞 10분에 절반이 들어오면 순간 도착률 = 평균의 3배 |
| A8 | 세션당 요청 수 | **11** | §2.2 믹스에서 역산(도출값) |
| A9 | 세션 체류시간 | **180초** | ⚠️ **가정** — 리틀의 법칙으로 동시 유저를 내기 위한 값 |

### 3.2 산출
```
λ_avg  = 480 세션 ÷ 3600s                       = 0.133 세션/s
λ_peak = λ_avg × k(3.0)                          = 0.40 세션/s   ★ baseline 목표 도착률
req/s  = λ_peak × 11                             = 4.4 req/s
login/s= λ_peak × 1                              = 0.40 logins/s
동시    = λ_peak × 180s (리틀의 법칙)             = 72 동시 유저
```

### 3.3 Stage1 실측 천장과 대조 — 왜 baseline 만으로는 아무것도 안 배우나
| 축 | **DAU 500 피크(산출)** | Stage1 실측(정본 §3.4) | 여유 |
|---|---|---|---|
| 로그인 | **0.40 logins/s** | knee ≈ 50 logins/s | **125×** |
| 동시 브라우징 | **72 동시** | ~700~800 동시(단일 pod recipe 기준) | **~10×** |
| 총 요청 | **4.4 req/s** | 저니 1000명서 738 req/s 관측 | **~170×** |

→ 정본 §6.6 *"DAU 500 엔 과잉 여유"* 를 숫자로 재확인. **baseline 런은 곡선 모양의 기준자(reference)로만 쓰고, 본체는 배수를 올려 knee 를 찾는 것이다.**

### 3.4 성장 배수(MULT) ↔ DAU 등가표 — 한계 탐색의 좌표계
스크립트는 `-e MULT=<배수>` 로 baseline 을 그대로 확대한다. 같은 곡선 모양, 진폭만 커진다.

| MULT | 피크 세션/s | req/s | logins/s | 동시(리틀) | **DAU 등가** |
|---|---|---|---|---|---|
| 1 | 0.4 | 4.4 | 0.4 | 72 | **500** |
| 10 | 4 | 44 | 4 | 720 | 5,000 |
| 25 | 10 | 110 | 10 | 1,800 | 12,500 |
| 50 | 20 | 220 | 20 | 3,600 | 25,000 |
| 100 | 40 | 440 | 40 | 7,200 | 50,000 |
| 125 | 50 | 550 | 50 | 9,000 | 62,500 |

**사전 예측(반증 가능하게 적어 둔다)**
- Stage1 로그인 knee 50/s = **MULT 125 ≈ DAU 62,500 등가**.
- Stage1 브라우징 천장 ~700~800 동시 = **MULT ~10 ≈ DAU 5,000 등가** — 단 그건 recipe 단일 pod 시절 값이고, 지금은 HPA(min2/max4)가 라이브라 **천장이 이미 위로 이동했다**(정본 §5.1 재검증에서 1000명 전부 통과). 그래서 브라우징 축은 **재측정 대상**이다.
- 🔴 **가장 유력한 새 천장은 둘 다 아니다.** §2.2 가 새로 태우는 recipebook·pantry·notify 는 셋 다 **replica 1 · cpu request 100m · HPA 없음 · 앱 PG 풀 max 5**(§4.2)다. 이 셋 중 하나가 먼저 물릴 가능성이 높다.

### 3.5 바이럴 규모는 왜 가정하지 않는가
"핫한 레시피 하나가 몇 명에게 퍼지는가"는 **근거로 삼을 데이터가 우리에게 없다**(DAU 500 서비스에 바이럴 이력 0건). 그래서 규모를 가정해 맞추는 대신 **역방향으로 간다**: 단일 `share_token` 에 대한 read 도착률을 5 → `HOT_PEAK` rps 로 램프해 **knee 를 찾고, 그 knee 를 "우리 인프라가 감당 가능한 바이럴 규모"로 보고**한다. 가정을 하나 줄이고 실측을 하나 늘리는 쪽이다.

---

## 4. 한계·병목 탐색 설계

### 4.1 knee 를 어떻게 찾나
- **모드 분리**: `-e MODE=peak`(식사시간 곡선 · baseline 검증용) / `-e MODE=knee`(단조 계단 램프 · 한계 탐색용).
- **계단 유지시간 45s 이상** — HPA 는 스케일 판단에 ~60s(메트릭 창 + 안정화)가 필요하다. 계단이 그보다 짧으면 **HPA 가 반응하기 전에 다음 계단으로 넘어가** knee 를 실제보다 낮게 잡는다.
- **한 번에 한 축만** 크게 움직인다. 정본 §6.2 *"병목은 하나씩 드러난다"* 그대로 — recipe 를 치우니 account 가 나왔듯, 이번에도 하나 해소하면 다음이 나온다. 그러니 **각 knee 마다 "이번 병목은 무엇인가"를 명시적으로 지목**하고 넘어간다.
- **abortOnFail 이 knee 마커다**: `p95>3s` 또는 `오류율>10%` 에서 k6 가 스스로 멈춘다 → 중단 직전 구간이 knee 근방이다(Stage1 §3.2 와 동일 기법).

### 4.2 무엇으로 병목을 지목하나 — 판별 매트릭스
🔴 **핵심**: p95 가 오르는 건 결과지 원인이 아니다. 아래 서명(signature)으로 원인을 가른다.

| 서명 | 관측 조합 | **병목** | 처방 |
|---|---|---|---|
| A | pod CPU 가 ~1 core 이상에서 plateau + HPA replica = max | **앱 CPU** (account bcrypt형 / recipe 검색형) | HPA max↑ · request 조정 · 쿼터 |
| B | p95 급등인데 **pod CPU 는 낮음(<0.3 core)** + PG active backend 도 평탄 | 🔴 **앱 커넥션 풀 고갈** (`pg_pool_max=5`) | pool_max↑ 또는 replica↑ |
| C | p95 급등 + PG active backend↑ + `cnpg_backends_waiting_total` > 0 | **PG / Pooler** | 쿼리 최적화(ILIKE 인덱스)·Pooler 풀 |
| D | p95 급등 + 노드 CPU > 80% | **노드** | 배치 원칙 재확인·노드 증설 |
| E | 5xx / 재시작 + `OOMKilled` | **메모리 limit** (recipebook·pantry·notify 전부 `limits.memory=256Mi`) | limit↑ |
| F | 파드 Pending + `exceeded quota` 이벤트 | **app ResourceQuota**(6 core / 6Gi) | 쿼터 재배분 |

**서명 B 를 특히 주목하는 이유** — recipebook 은 앱 풀이 `pg_pool_max = 5`(`services/recipebook/app/config.py`, 주석: *"Pooler 경유라 앱 풀은 작게 잡는다"*)이고 replica 는 1이다. 리틀의 법칙으로 **단일 replica 최대 처리량 ≈ 5 ÷ (PG 체류시간)**:

| PG 체류시간 | 이론 최대 rps (1 replica) |
|---|---|
| 10ms | ~500 |
| 30ms | ~167 |
| 50ms | ~100 |

핫키 read(`GET /api/recipes/shared/{token}`)는 **PG 왕복이 5회**다 — 토큰 조회 1회 + `enrich_ingredients` 4회(`services/recipebook/app/queries.py:24-75`: unnest 이름매칭 → `item_master` → `retail_item_price_compare` → `food_nutrition`). 그래서 **예측 knee ≈ 100~200 rps**. 이게 맞으면 CPU 는 한가한데 p95 만 치솟는 **서명 B** 가 나온다.

### 4.3 🔴 유저 등록 레시피는 ES 검색에 안 나온다 (코드 근거)
Stage3 설계의 전제이므로 근거를 남긴다. **추측이 아니라 코드·클러스터 실측이다.**

| 사실 | 근거 |
|---|---|
| `POST /api/recipes/mine` 은 `recipebook.user_recipe` 에 INSERT 한다 (`public.recipe` 아님) | `services/recipebook/app/queries.py:158` — `insert into recipebook.user_recipe` |
| PGSync 는 `public.recipe` + 자식 `public.recipe_ingredient` 만 동기화한다 | `deploy/pgsync/schema.json` — 라이브 ConfigMap `data/mp-pgsync-schema` 와 동일. `recipebook` 참조 0건 |
| recipe 서비스는 recipebook 을 모른다 | `grep -rn "recipebook\|user_recipe\|shared" services/recipe/app/` → **0건** |
| recipe 검색이 보는 인덱스 | 라이브 `deploy/mp-recipe` env `ES_INDEX=recipes_pgsync` (2026-08-01 실측) |
| ES 에 쓰는 코드는 하나뿐이고 `public.recipe` 만 넣는다 | `pipelines/ingest/index_recipes_es.py` |
| recipebook 서비스에 ES·Kafka 클라이언트가 없다 | `services/recipebook/app/` 에 해당 import 0건 |
| DB 트리거/룰도 없다 | `docs/prd/schema-*.sql` 에 `CREATE TRIGGER` 0건 |
| 실제 노출 경로 = **프론트 클라이언트 병합** | `frontend/src/pages/RecipeSearch.tsx:52` 가 `useRecipeSearch`(ES) 와 `useSharedRecipes`(PG) 를 따로 불러 화면에서 합침 |
| 게이트웨이 라우팅도 갈라져 있다 | `mp-recipe-route`: `/api/recipes` → `recipe:8001` / `mp-recipebook-route`: `/api/recipes/{book,mine,shared}` → `recipebook:8006` (PathPrefix, 더 구체적인 쪽이 이김) |

→ **"등록한 레시피를 `/api/recipes?q=` 로 검색해 찾는다"는 시나리오는 0건을 반환한다. 버그도 lag 도 아니고 설계다.** 그래서 신선도(H10)는 **`GET /api/recipes/shared?q=`(PG, 같은 트랜잭션 → lag 0 이어야 함)** 로 측정하고, ES 쪽은 **음성 대조군**(`catalog_es_hits == 0` 이 정상)으로만 찍는다.

### 4.4 두 번째 유력 병목 — 공개 목록 검색의 seq scan
`GET /api/recipes/shared?q=` 는 이렇게 돈다 (`services/recipebook/app/queries.py:312-330`):
```sql
where s.title ilike '%q%' or s.ingredients::text ilike '%q%'
order by s.published_at desc limit N
```
- 선행 와일드카드 `%q%` → **B-tree 못 탄다.**
- `s.ingredients::text` → **jsonb→text 캐스트를 행마다** 수행.
- `recipebook.shared_recipe` 의 인덱스는 `shared_recipe_published_idx (published_at DESC)` **하나뿐**(`docs/prd/schema-production.sql`).
→ **행 수에 선형으로 느려지는 seq scan.** P1 에서 `TEST-` 행을 수백 건 쌓은 뒤 P3 에서 이 엔드포인트를 때리면 그 선형성이 그대로 드러난다(H9).

---

## 5. 부하 프로파일

### 5.1 Stage3-A — 피크 몰림 (`stage3_peak_journey.js`)
두 시나리오를 **같은 시간축에 겹쳐** 돌린다. Stage1 §3.4 의 결론(*로그인 몰림 축과 브라우징 축은 서로 다른 천장을 가진다*)을 한 런에서 동시에 재현하기 위해서다.

| 시나리오 | executor | 단위 | exec |
|---|---|---|---|
| `peak_login` | `ramping-arrival-rate` | 세션/s (= logins/s) | `sessionLogin` |
| `peak_browse` | `ramping-arrival-rate` | 세션/s (× 10 req) | `sessionBrowse` |

**`MODE=peak` 곡선** (총 300s · 진폭 = `PEAK = 0.4 × MULT`)

| 구간 | 목표 | 지속 | 의미 |
|---|---|---|---|
| 1 | 0.25 × PEAK | 60s | 평시 |
| 2 | 0.60 × PEAK | 60s | 식사 30분 전 |
| 3 | 1.00 × PEAK | 45s | 식사 직전 급상승 |
| 4 | 1.00 × PEAK | 90s | **피크 고원 ★ 측정 구간** |
| 5 | 0.20 × PEAK | 45s | 식사 시작 → 급감 |

**`MODE=knee` 곡선** (총 240s) — 0.10 → 0.25 → 0.50 → 0.75 → 1.00 × PEAK, 각 45~60s 유지(§4.1).

### 5.2 Stage3-B — 바이럴 스파이크 (`stage3_viral_spike.js`)
🔴 **B-3 순차** — 세 단계를 `startTime` 으로 직렬화한다. 겹치면 어느 단계가 병목을 만들었는지 못 가른다.

```
t=0s     ├─ P1 등록 버스트 (진짜 write) ──────────┤ 90s
t=100s                                    ├─ P2 신선도 프로브 ──┤ 60s
t=175s                                                    ├─ P3 핫키 폭증 + 공개목록 검색 ──┤ 195s
```

| 단계 | 시나리오 | 무엇 | 도착률 |
|---|---|---|---|
| **P1** | `p1_register` | `POST /api/recipes/mine`(`TEST-` 접두) | 1 → `WRITE_PEAK`(기본 10)/s, 90s |
| **P2** | `p2_freshness` | 등록 → `publish` → `/api/recipes/shared?q=` 노출까지 폴링 + ES 음성 대조 | `FRESH_RATE`(기본 1)/s, 60s |
| **P3-a** | `p3_hotkey` | 🔴 **단일 `share_token`** `GET /api/recipes/shared/{token}`(비인증) | 5 → `HOT_PEAK`(기본 200)/s, 195s |
| **P3-b** | `p3_discovery` | `GET /api/recipes/shared?q=TEST-`(ILIKE seq scan) | `DISC_RATE`(기본 10)/s 고정 |

`setup()` 이 pool 유저 1번으로 "핫한" 레시피 1건을 등록·발행해 `share_token` 을 확보하고, `teardown()` 이 그 1건을 지운다. P1·P2 가 만든 것은 **`cleanup_test_recipes.js` 담당**이다.

🔴 **생성되는 행 수(기본값 기준)**: P1 ≈ **700건**(3→10/s 램프 × 90s) + P2 ≈ **60건**(1/s × 60s) = 런당 약 **760 `TEST-` 레시피**. 이 중 P2 의 60건은 `publish` 까지 하므로 `recipebook.shared_recipe` 에도 들어간다. **행이 쌓이는 것 자체가 H9(seq scan 선형 악화)의 재료**다 — 그래서 P3 의 `shared_search` p95 를 P2 구간과 비교한다. 다만 **런을 반복하면 누적**되므로, 런 사이에 cleanup 을 돌릴지(비교 조건 동일) 누적시킬지(행 수 효과 관찰)를 **의도적으로 정하고 기록**할 것. 소유는 pool 유저 1~`TOKENS`(기본 30)에 분산된다.

---

## 6. 가설 (H6~H10) 과 판정 기준

### 6.1 SLO (정본 §4.7 승계)
| 종류 | 기준 |
|---|---|
| 단순조회 | **p95 < 500ms** — hotdeals·recommend·budget·recipe_detail·recipe_reviews·book_list·mine_list·pantry_expiring·notifications·**shared_hotkey** |
| 검색/집계 | **p95 < 1s** — recipe_search·shared_search·catalog_search |
| 로그인 | **p95 < 1s** |
| 오류율 | **< 1%** |
| write *(Stage3 신설·⚠️ 잠정)* | **p95 < 1s** — recipe_create·recipe_publish. 근거: 단일 `INSERT … RETURNING` / 3문 1트랜잭션이라 읽기보다 크게 느릴 이유가 없다. **팀 합의 전 잠정값** |

이 SLO 는 스크립트의 태그별 threshold 로 박혀 있어 **런이 끝나면 k6 exit code 로 자동 판정**된다(비중단). 별도로 `오류율>10%` · `전체 p95>3s` 는 **abortOnFail 킬스위치**다(중단).

### 6.2 가설
| # | 가설 | 측정 | 깨지면 의미 |
|---|---|---|---|
| **H6** 평시 흡수 | `MULT=1`(DAU 500 baseline)에서 **전 엔드포인트 SLO 충족 + HPA 미기동**(account·recipe 둘 다 min 유지) | 태그별 p95 · `kubectl -n app get hpa` | 평시 용량 자체가 부족 → 튜닝이 아니라 증설 문제 |
| **H7** recipebook 분류 | recipebook 계열의 knee 는 CPU 가 아니라 **앱 PG 풀(max 5)** 에서 온다 → knee 부근에서 **pod CPU < 0.3 core 인데 p95 급등**(§4.2 서명 B) | pod CPU × p95 × `cnpg_backends_total` | CPU 포화가 먼저면 분류가 **HPA-CPU** 로 바뀐다 → 처방도 HPA 로 바뀜 |
| **H8** 핫키 천장 | 단일 `share_token` read 는 UNIQUE 인덱스 조회임에도 `enrich_ingredients` PG 왕복 4회 때문에 **~100~200 rps** 에서 무너진다 | `shared_hotkey` p95 vs 도착률 | 훨씬 높게 버티면 enrich 비용이 예상보다 싸다 → 핫키는 문제 아님 |
| **H9** seq scan | `GET /api/recipes/shared?q=` p95 가 **P1 이 행을 쌓은 뒤(P3) 유의하게 상승**한다 | `shared_search` p95 (P2 구간 vs P3 구간) | 데이터 규모가 아직 작아 안 드러난 것 — 행 수를 더 쌓아 재시도 |
| **H10** 신선도(재정의) | ① publish → `/api/recipes/shared?q=` 노출 **lag ≈ 0**(첫 폴에서 보임) ② `/api/recipes?q=`(ES) 에는 **영원히 안 나옴** → `catalog_es_hits == 0` | `freshness_shared_ms` · `freshness_polls` · `catalog_es_hits` | ①이 깨지면 커밋 가시성/Pooler 트랜잭션 이슈 · ②가 깨지면 **읽은 코드와 배포가 다르다** → 즉시 조사 |

⚠️ **정본 H4(PGSync 신선도)는 Stage3 검증 대상이 아니다.** §4.3 참조.

---

## 7. 관측 체크리스트

> 모든 명령은 **읽기 전용**이다. WSL 에서 `kubectl` 이 네이티브로 클러스터에 닿는다(2026-08-01 확인). 정본 §1.3 은 `kubectl.exe` interop 을 적고 있는데, 현 개발 PC 에서는 WSL 네이티브도 동작한다 — 둘 중 되는 쪽을 쓰면 된다.
> PromQL 은 Prometheus 에 포트포워드해서 확인한다:
> `kubectl -n observability port-forward svc/kube-prometheus-stack-prometheus 19090:9090` → `http://127.0.0.1:19090`

### 7.1 오토스케일 — HPA replica 추이
```bash
kubectl -n app get hpa -w
watch -n5 'kubectl -n app get hpa; kubectl -n app get deploy mp-recipebook mp-pantry mp-notify mp-recipe mp-account'
```
```promql
kube_horizontalpodautoscaler_status_current_replicas{namespace="app"}
kube_horizontalpodautoscaler_spec_max_replicas{namespace="app"}
```
🔴 **현재 HPA 는 `mp-account`·`mp-recipe` 둘뿐이다**(2026-08-01 실측). recipebook·pantry·notify 는 **고정 replica 1 · HPA 없음** — 즉 이 셋은 knee 를 넘어도 **스스로 늘지 않는다.** 그 자체가 Stage3 의 발견 대상이다.

### 7.2 파드별 CPU (병목 서명 A vs B 판별의 핵심)
```bash
watch -n6 'kubectl -n app top pods --containers | grep -v istio-proxy'
```
```promql
# 파드별 CPU (사이드카 제외)
sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="app", container!="", container!="POD", container!="istio-proxy"}[1m]))
# CFS 스로틀 (limit 이 지연을 악화시키는지)
sum by (pod) (rate(container_cpu_cfs_throttled_seconds_total{namespace="app", container!="istio-proxy"}[1m]))
```
판독: **p95 는 오르는데 위 값이 0.3 core 미만이면 CPU 병목이 아니다** → 서명 B/C 로 간다.

### 7.3 엔드포인트별 서버측 p95 (k6 클라이언트 수치와 교차검증)
```promql
histogram_quantile(0.95, sum by (service, handler, le) (
  rate(http_request_duration_highr_seconds_bucket{namespace="app",
       service=~"recipebook|recipe|account|price|pantry|notify"}[1m])))
```
```promql
# 서비스별 오류율(%)
100 * sum by (service) (rate(http_requests_total{namespace="app", status=~"5.."}[1m]))
    / sum by (service) (rate(http_requests_total{namespace="app"}[1m]))
```
✅ `service`·`handler`·`method` 라벨 존재 확인(2026-08-01 실측 — `service` 값 = account/chat/mealplan/notify/ocr/pantry/price/recipe/recipebook/video). `handler` 는 라우트 템플릿이라 `/api/recipes/shared/{share_token}` 이 하나로 집계된다 → **핫키 관측에 유리**.

### 7.4 app 쿼터 잔여
```bash
kubectl -n app describe resourcequota mp-app-quota
```
```promql
kube_resourcequota{namespace="app", resource=~"requests.cpu|requests.memory"}   # type=used vs hard
```
기준선(2026-08-01 실측): **used 3080m / hard 6 core · used 4032Mi / hard 6Gi**. 최악(account·recipe 둘 다 max 4) ≈ 4.7 core / 5.2Gi(84%) — 정본 §5.3. 🔴 **CPU 보다 메모리가 먼저 조인다.** 파드가 `Pending` 이면서 이벤트에 `exceeded quota` 가 뜨면 서명 F.

### 7.5 CNPG Pooler active / waiting
🔴 **실측 주의: Prometheus 에 PgBouncer 메트릭이 없다**(2026-08-01 확인 — `__name__` 목록에 `pgbouncer*` 0건). 그래서 두 경로로 본다.

**(a) PG 서버 쪽 — 메트릭 있음(권장)**
```promql
sum by (state) (cnpg_backends_total{namespace="data", datname="foodbudget"})
sum(cnpg_backends_waiting_total{namespace="data"})
max(cnpg_backends_max_tx_duration_seconds{namespace="data"})
```
P3 실증 기준선 = account 4 replica 에서도 **12/100**(정본 부록 A). 여기가 안 오르는데 앱 p95 만 오르면 → **앱 풀 병목(서명 B) 확정.**

**(b) PgBouncer 쪽 — ⚠️ 미확인**
```bash
kubectl -n data exec deploy/pg-pooler -- \
  psql "host=127.0.0.1 port=5432 dbname=pgbouncer user=pgbouncer" -c "SHOW POOLS;"
```
⚠️ **이 명령은 검증하지 못했다** — pooler 파드 안의 psql 경로·인증을 확인하지 않았다. 안 되면 (a) 로 대체한다.

### 7.6 ES 지연
🔴 **실측 주의: Prometheus 에 elasticsearch 메트릭이 없다**(exporter 미배포 — `elasticsearch*` 0건). 대체 관측:
- **앱 관점(권장)** — recipe 서비스의 검색 p95 가 곧 ES 왕복이다(§7.3 에서 `service="recipe", handler="/api/recipes"`).
- **ES 직접**(자격증명 필요 · admin):
```bash
kubectl -n data port-forward svc/es-es-http 9200:9200
curl -sk -u elastic:<PW> https://127.0.0.1:9200/_cat/indices/recipes_pgsync?v
curl -sk -u elastic:<PW> https://127.0.0.1:9200/_nodes/stats/thread_pool?pretty
```
⚠️ ES 는 **인증 켬 + HTTP TLS 끔** 설정이므로(CLAUDE.md) 스킴이 `http` 일 수 있다 — **미확인**. 실행자가 확인할 것.

### 7.7 PGSync lag
🔴 **Stage3 판정에는 쓰지 않는다**(§4.3 — 유저 레시피는 PGSync 대상이 아니다). 배경 소음 확인용만.
```bash
kubectl -n data logs deploy/mp-pgsync --tail=50 -f
```
```promql
# 논리 슬롯이 붙잡고 있는 WAL = 소비 지연 프록시
max by (slot_name) (cnpg_pg_replication_slots_pg_wal_lsn_diff{namespace="data"})
```
전용 lag 메트릭은 없다 — 존재하는 룰은 가용성 룰 2개(`MpPGSyncDown`·`MpPGSyncCrashLooping`)뿐이다.

### 7.8 Kafka lag
Stage3 는 Kafka 를 태우지 않는다 → **배경 확인용**(파이프라인이 동시에 돌면 대조가 오염되므로).
```promql
sum by (consumergroup, topic) (kafka_consumergroup_lag)
```
```bash
kubectl -n pipeline get hpa    # KEDA — 컨슈머가 0에서 깨어나면 CPU 를 나눠 쓴다
```

### 7.9 노드 CPU · 배치
```bash
kubectl top nodes
kubectl -n app get pods -o wide      # 배치 원칙 확인: PG·Redis primary=A / master·Prometheus·MinIO=B
```
```promql
instance:node_cpu:ratio                                              # 레코딩 룰(존재 확인)
1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[1m]))
```
클러스터 = **5노드**(master + worker a1/a2/b1/b2, 각 v1.34.10).

### 7.10 사고 신호 (즉시 중단 대상)
```bash
kubectl -n app get pods -w
kubectl -n app get events --sort-by=.lastTimestamp | tail -30
kubectl -n data get cluster pg          # CNPG 헬스 / primary 페일오버
```
```promql
increase(kube_pod_container_status_restarts_total{namespace="app", container!="istio-proxy"}[5m]) > 0
```
🔴 recipebook·pantry·notify 는 **`limits.memory = 256Mi`** 다(실측). OOMKill 이 나면 서명 E.

### 7.11 🔴 알림 소음 경고
`mp-app-sli` 룰이 라이브다: **`MpAppHighP95Latency`(p95 > 1s, for 2m, warning)** · **`MpAppHighErrorRate`(5xx > 5%, for 2m, critical)**. Stage3 는 **의도적으로 이 둘을 넘긴다** → **Slack 이 울린다.**
→ 실행 전 **팀 채널에 사전 공지**하거나 Alertmanager 에 silence 를 걸 것. 안 그러면 부하테스트가 인시던트로 오인된다.

---

## 8. 실행 절차

> 🔴 **전제: 하네스는 정본 §1 을 그대로 승계한다.** Windows `k6.exe` + WSL interop, Gateway VIP `.14` 직타, `hosts` 로 SNI/Host 오버라이드, `insecureSkipTLSVerify`, **Cloudflare 터널 우회**(공인 도메인으로 때리면 cloudflared 파드 1개가 병목이 된다).
> 🔴 **off-peak 에 돌린다** — 실제 유저 피크(17–18시)를 피한다. 공유·라이브 클러스터다.

### 8.1 절차
```bash
# ── 0. 사전 스냅샷 (되돌릴 기준점) ─────────────────────────────────────────
kubectl -n app get hpa,deploy,pods -o wide > /tmp/stage3_before.txt
kubectl -n app describe resourcequota mp-app-quota >> /tmp/stage3_before.txt
kubectl top nodes >> /tmp/stage3_before.txt

# ── 1. 알림 공지 / silence (§7.11) ────────────────────────────────────────

# ── 2. 유저 풀 시드 (멱등: 201 또는 409) ──────────────────────────────────
cp loadtest/seed_users.js /mnt/c/temp/
/mnt/c/temp/k6.exe run -e N=200 'C:\temp\seed_users.js'

# ── 3. 스모크 (하네스 도달 확인) ──────────────────────────────────────────
cp loadtest/smoke.js /mnt/c/temp/ && /mnt/c/temp/k6.exe run 'C:\temp\smoke.js'

# ── 4. Stage3-A baseline (DAU 500 · H6) ───────────────────────────────────
cp loadtest/stage3_peak_journey.js /mnt/c/temp/
/mnt/c/temp/k6.exe run -e NUSERS=200 -e MULT=1 'C:\temp\stage3_peak_journey.js'

# ── 5. Stage3-A knee 탐색 (단계적으로 올린다 — 한 번에 100 으로 가지 말 것) ─
/mnt/c/temp/k6.exe run -e NUSERS=200 -e MODE=knee -e MULT=10  'C:\temp\stage3_peak_journey.js'
/mnt/c/temp/k6.exe run -e NUSERS=200 -e MODE=knee -e MULT=25  'C:\temp\stage3_peak_journey.js'
/mnt/c/temp/k6.exe run -e NUSERS=200 -e MODE=knee -e MULT=50  'C:\temp\stage3_peak_journey.js'
#   → abortOnFail 로 끊긴 MULT 의 직전 단계가 knee 근방. 그 지점에서 §4.2 서명을 판정.

# ── 6. Stage3-B 바이럴 (write 포함 — 여기서부터 TEST- 데이터가 생긴다) ────
cp loadtest/stage3_viral_spike.js /mnt/c/temp/
/mnt/c/temp/k6.exe run -e NUSERS=200 -e WRITE_PEAK=10 -e HOT_PEAK=100 'C:\temp\stage3_viral_spike.js'
/mnt/c/temp/k6.exe run -e NUSERS=200 -e WRITE_PEAK=10 -e HOT_PEAK=200 'C:\temp\stage3_viral_spike.js'
/mnt/c/temp/k6.exe run -e NUSERS=200 -e WRITE_PEAK=10 -e HOT_PEAK=400 'C:\temp\stage3_viral_spike.js'

# ── 7. 🔴 정리 (필수) ────────────────────────────────────────────────────
cp loadtest/cleanup_test_recipes.js /mnt/c/temp/
/mnt/c/temp/k6.exe run -e NUSERS=200 -e DRYRUN=1 'C:\temp\cleanup_test_recipes.js'   # 먼저 세어 본다
/mnt/c/temp/k6.exe run -e NUSERS=200 'C:\temp\cleanup_test_recipes.js'                # 삭제
/mnt/c/temp/k6.exe run -e NUSERS=200 -e DRYRUN=1 'C:\temp\cleanup_test_recipes.js'   # matched=0 확인(멱등)

# ── 8. 사후 확인 ─────────────────────────────────────────────────────────
kubectl -n app get hpa            # replica 가 min 으로 복귀했는지(안정화 ~5분)
kubectl -n app describe resourcequota mp-app-quota
kubectl -n app get pods           # Restarts / OOMKilled 없는지
```

**런 사이에 3~5분 간격**을 둔다 — HPA 가 min 으로 되돌아오고 캐시가 식어야 다음 런이 같은 출발선에서 시작한다.

### 8.2 중단 기준
| 층 | 트리거 | 동작 |
|---|---|---|
| 자동(k6) | `http_req_failed rate ≥ 0.10` (15s 유예) | k6 즉시 중단 |
| 자동(k6) | 전체 `http_req_duration p95 ≥ 3s` (15s 유예) | k6 즉시 중단 |
| 🔴 사람 | app ns 파드 **OOMKilled / CrashLoopBackOff** | 즉시 `Ctrl-C` |
| 🔴 사람 | 파드 **Pending + `exceeded quota`** | 즉시 중단 — 쿼터를 넘기면 다른 서비스 배포까지 막힌다 |
| 🔴 사람 | **PG primary 페일오버** 또는 `cnpg_backends_waiting_total` 지속 상승 | 즉시 중단 |
| 🔴 사람 | 노드 **NotReady** | 즉시 중단 |
| 🔴 사람 | 실 유저 트래픽 유입 감지 | 즉시 중단(off-peak 아님) |

### 8.3 정리·롤백
- **데이터**: `cleanup_test_recipes.js` 가 `TEST-` 유저 레시피를 지운다. `recipebook.shared_recipe` 는 FK `ON DELETE CASCADE` 로 함께 사라지므로 **별도 unpublish 불필요**. `stage3_viral_spike.js` 의 `teardown()` 은 setup 이 만든 핫 레시피 1건만 책임진다.
- **셀렉터 안전장치**(오삭제 방지): ① `loadtest-pool-NNNN@mealbong.cloud` 계정으로만 로그인하고, `/api/recipes/mine` 은 JWT `user_id` 스코프라 **테스트 계정 소유 행 외에는 보이지도 않는다** ② 그 안에서 다시 `title.startsWith(PREFIX)` 인 것만 DELETE ③ `PREFIX` 가 4자 미만이면 스크립트가 **시작을 거부**한다.
- **멱등**: 두 번째 실행에서 `recipes_matched = 0` 이면 정리 완결.
- **테스트 유저**: 남겨도 무방(다음 런에 재사용). 지우려면 `cleanup_users.js -e N=200`.
- **수동 scale 을 했다면 원복**: `kubectl -n app scale deploy/mp-recipebook --replicas=1` (§9.1 통제 대조를 돌린 경우).
- **HPA**: 자동 축소(안정화 창)를 기다린다. 스크립트가 replica 를 건드리지 않으므로 별도 롤백 없음.

---

## 9. 선택 실험 (여유가 있으면)

### 9.1 recipebook 통제 대조 (정본 §3.6 기법 재사용)
정본 §3.6 은 `kubectl scale deploy/mp-recipe --replicas=4` 로 **recipe replica 만 바꾼 통제 대조**를 돌려 p95 를 59× 떨어뜨렸다. recipebook 에 같은 걸 한다:
```bash
kubectl -n app scale deploy/mp-recipebook --replicas=3   # ⚠️ admin 권한 필요 · 쿼터 여유 확인 후
# 같은 HOT_PEAK 로 stage3_viral_spike.js 재실행 → shared_hotkey p95 비교
kubectl -n app scale deploy/mp-recipebook --replicas=1   # 원복
```
- **replica 를 늘렸는데 p95 가 비례해 떨어진다** → 병목이 앱 풀(5/replica)이었다는 직접 증거(H7 지지) → 처방 = HPA 또는 `pg_pool_max` 상향.
- **안 떨어진다** → 병목이 PG 쪽(서명 C) → 처방 = 쿼리/인덱스.
⚠️ 쿼터 여유를 먼저 본다(§7.4). replica 3 = requests +200m/+256Mi.

### 9.2 `MpAppHighP95Latency` 가 실제로 우는지 확인
Stage3 는 의도적으로 p95 1s 를 넘긴다 → **알림 파이프라인(룰 → Alertmanager → Slack)의 end-to-end 검증 기회**다. 울리면 그 자체가 모니터링 컷오버(2026-07-30)의 사후 실증이 된다.

---

## 10. 미확정 입력값 (⚠️ 임의 확정 금지)

| 입력 | 현재 값 | 성격 |
|---|---|---|
| A2 유저당 일 세션 수 | 1.6 | ⚠️ **가정** — 실측 근거 없음(클릭스트림에서 산출 가능할 수 있음) |
| A4 피크창 흡수 비율 | 60% | ⚠️ **가정** — 멘토 피드백의 정성 서술을 수치화한 것 |
| A6 압축창 길이 | 창당 30분 | ⚠️ **가정** |
| A7 창 내부 집중계수 *k* | 3.0 | ⚠️ **가정** — 가장 임의적인 값. k 를 2 로 두면 λ=0.27, 5 면 λ=0.67 |
| A9 세션 체류시간 | 180s | ⚠️ **가정** — 동시 유저 환산에만 쓰임 |
| write SLO | p95 < 1s | ⚠️ **잠정** — 팀 합의 필요 |
| `HOT_PEAK` 상한 | 400 rps | ⚠️ **미정** — knee 를 못 찾으면 더 올려야 함 |
| 목표 성장 규모 | **미정** | 🔴 이 테스트의 산출물로 정할 것 — knee 가 나오면 "DAU 몇까지 안전"을 §3.4 표로 역산 |
| 알림 fan-out 시나리오 | **재현 불가** | 스키마에 팔로우/구독 없음(§2.3). 기능이 생기면 그때 별건 |

**🔴 클릭스트림으로 A2·A4·A6·A7 을 실측으로 대체할 수 있다.** 파이프라인이 라이브다(`mp-user-event-sink`, 2026-07-20 개통). 다만 DAU 500 미만 실서비스라 표본이 충분한지는 **미확인** — 확인 후 가정을 실측으로 갈아끼우면 이 문서의 §3 전체가 단단해진다.

---

## 부록 A. 실행 시 채울 결과 표 (템플릿)

### A.1 Stage3-A
| MULT | DAU 등가 | login p95 | search p95 | book/mine p95 | pantry p95 | notify p95 | 오류율 | HPA(account/recipe) | 병목 서명 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 500 | | | | | | | | |
| 10 | 5,000 | | | | | | | | |
| 25 | 12,500 | | | | | | | | |
| 50 | 25,000 | | | | | | | | |

### A.2 Stage3-B
| HOT_PEAK | hotkey p95 | shared_search p95 | create p95 | publish p95 | recipebook CPU | cnpg_backends(active/waiting) | 오류율 | 병목 서명 |
|---|---|---|---|---|---|---|---|---|
| 100 | | | | | | | | |
| 200 | | | | | | | | |
| 400 | | | | | | | | |

### A.3 신선도(H10)
| 지표 | 값 | 기대 |
|---|---|---|
| `freshness_shared_ms` p95 | | ~0 (같은 트랜잭션) |
| `freshness_polls` max | | 1 |
| `catalog_es_hits` | | **0** (0이 아니면 조사) |

---

## 부록 B. 클러스터 사실 (2026-08-01 읽기 전용 실측)

| 항목 | 값 |
|---|---|
| 노드 | 5 (`k8s-master` + worker `a1`·`a2`·`b1`·`b2`) · v1.34.10 |
| HPA | **`mp-account`(2/4) · `mp-recipe`(2/4) 둘뿐** — recipebook·pantry·notify 는 HPA 없음 |
| recipebook / pantry / notify | replica **1** · `requests.cpu 100m` · `requests.memory 128Mi` · **`limits.memory 256Mi`** · cpu limit 없음 |
| recipebook 앱 PG 풀 | **`pg_pool_max = 5`** (`services/recipebook/app/config.py`) |
| app ResourceQuota | `mp-app-quota` — used **3080m / 6 core** · **4032Mi / 6Gi** |
| PDB | `mp-account-pdb` · `mp-frontend-pdb` · `mp-recipe-pdb` (minAvailable 1) |
| recipe ES 인덱스 | `ES_INDEX=recipes_pgsync` (라이브 env) |
| PGSync 대상 | `public.recipe` + `public.recipe_ingredient` → `recipes_pgsync` (ConfigMap `data/mp-pgsync-schema`) |
| 게이트웨이 라우팅 | `/api/recipes` → `recipe:8001` · `/api/recipes/{book,mine,shared}` → `recipebook:8006` · `/api/recipes/extract` → `video`(🔴 LLM, 제외) |
| 게이트웨이 제한 | `mp-gw-request-body-limit` = 15MB. **rate-limit EnvoyFilter 없음** |
| 있는 메트릭 | `http_request*`(service/handler/method 라벨) · `cnpg_*` · `kafka_consumergroup_lag` · `keda_*` · `kube_*` · `container_*` · `node_*` |
| 🔴 **없는** 메트릭 | `pgbouncer_*` · `elasticsearch_*` · `pgsync` lag — §7.5·§7.6·§7.7 의 대체 경로를 쓸 것 |
| 라이브 알림 | `MpAppHighP95Latency`(p95>1s, for 2m) · `MpAppHighErrorRate`(5xx>5%, for 2m) → **Stage3 는 이걸 울린다**(§7.11) |
