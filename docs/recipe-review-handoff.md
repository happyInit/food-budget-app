# AI 데이터 설계 핸드오프 — 리뷰 수집 + 가격 이상탐지·알림

> **범위** — AI 기능이 필요로 하는 **DB 스키마 · 파이프라인 변동**. 모델·프롬프트 구현은 범위 밖이다.
> 상위 정의 = [`ai-features-roadmap.md`](./ai-features-roadmap.md) · 모델 결정 =
> [`ai-model-selection-final.md`](./ai-model-selection-final.md). **여기서 그 내용을 복제하지 않는다.**
> 작성 2026-07-29 · 상태: **코드·DDL 완료 · DB 미검증**
>
> **수신자별 읽는 곳** — 데이터 담당자 = §4(DB·Kafka·Docker 변동) + §9(고정 판정) · AI 담당자 =
> §1~3(결정 근거) + §10(설계 커버리지)

---

## 0. 한 줄 결론

크롤·파싱은 **실물로 검증됐고**(레시피 1건 → 리뷰 187건 추출), **DB 연결만 미검증**이다.

> 🔴 **이 설계는 DB 에 접속하지 못한 채 스키마 파일만 보고 만들어졌다.** 실 DB 가 다를 수 있으므로
> **DDL 적용 전에 반드시 프리플라이트(§8)를 먼저 실행**한다. 통과하면 그대로 고정해도 된다.

---

## 0.5 옮길 파일 — 매니페스트

**전제**: 수신 PC 에 팀 레포(`food-budget-app`)가 이미 클론돼 있다. 아래를 **같은 경로에 덮어쓰면**
문서의 상대 링크·`sys.path` 가 전부 그대로 동작한다.

| 파일 | 상태 | 없으면 |
|---|---|---|
| `docs/recipe-review-handoff.md` | 신규 | 이 문서 |
| `docs/prd/migrations/2026-07-29_preflight.sql` | 신규 | **안전장치 없이 DDL 적용** |
| `docs/prd/migrations/2026-07-29_recipe_review.sql` | 신규 | 리뷰 테이블 4종 없음 |
| `docs/prd/migrations/2026-07-29_price_anomaly.sql` | 신규 | 가격 테이블 3종 없음 |
| `docs/prd/migrations/2026-07-29_extract_job_link.sql` | 신규 | 영상추출 추적성 보완 누락 |
| `docs/prd/schema-production.sql` | **수정**(+7줄) | `extract_job` 변경이 정본에 미반영 |
| `docs/prd/schema-public-data.sql` | **수정**(+48줄 §G) | 정본 스키마에 리뷰 미반영 |
| `crawler/10k_recipe/review_crawler.py` | 신규 | 크롤러 없음 |
| `recipe_review_crawler.py` (레포 루트) | 원본 유지 | — **참고용. 실행하지 말 것**(CSV 방식·닉네임 저장) |

⚠️ **레포 전체를 덮어쓰지 말 것.** 팀 레포는 이 세션 중에도 계속 진행돼(36커밋) 최신이 다르다.
위 6개만 얹는다.

### 실행 위치 — 어디서 돌려도 된다

크롤러는 `Path(__file__).resolve().parents[2]` 로 레포 루트를 찾으므로 **cwd 무관**이다.
다만 `.env` 는 반드시 **레포 루트**에 있어야 한다(`pipelines/ingest/_db.py` 가 거기서 읽는다).

```
food-budget-app/
├── .env                    ← 여기. PGPASSWORD 포함
├── crawler/10k_recipe/review_crawler.py
└── pipelines/ingest/_db.py ← .env 를 parents[2] 로 찾음
```

---

## 1. 왜 CSV → DB 로 바꿨나

기존 `recipe_review_crawler.py`(레포 루트, 원본 보존)는 `공식_레시피.csv`·`일반_검증완료_레시피.csv`
두 파일을 읽었다. 세 가지 문제가 있었다.

| 문제 | 내용 |
|---|---|
| **입력 파일 부재** | 두 CSV 모두 레포에 없다 — 현 상태로는 실행 자체가 불가능 |
| **조인 키 고립** | CSV 의 `레시피ID` 는 `recipe.src_recipe_id` 이고 PK 인 `recipe.id` 가 아니다. 나중에 수동 매핑이 한 단계 더 붙는다 |
| **재실행 중복** | CSV append 라 두 번 돌리면 리뷰가 두 배가 된다 |

**대상을 DB 에서 직접 뽑는 선례가 이미 있다** — [`reparse_buy_link_backfill.py`](../crawler/10k_recipe/reparse_buy_link_backfill.py)
가 `select ... from recipe where source='10K'` 로 재크롤 대상을 고른다. 같은 방식을 따랐다.

---

## 2. 왜 MongoDB 가 아니라 PostgreSQL 인가

리뷰가 문서형처럼 보이지만 실제 데이터는 **스키마가 고정**이다(레시피ID·순번·본문). 가변 필드도
중첩 구조도 없다.

- `recipe(id)` 와 **FK 1:N 조인**이 본래 목적이다 — 관계형의 본령
- 스택은 이미 확정 — **PG + ES + Redis** (ClickHouse 도 드롭했다, CLAUDE.md). 저장소를 하나 더
  늘리면 5인·9주 캡스톤에서 운영 부담만 순증한다
- 리뷰 **원문 검색**이 필요해지면 그때 ES 에 색인하면 된다 — 레시피 검색용으로 이미 돌고 있어
  추가 인프라가 0

---

## 3. 왜 원문을 저장하는가 (요약만 저장하지 않는 이유)

"감정분석을 바로 돌리고 집계·요약만 저장" 이 매력적으로 보였으나, **저장소 문서 세 곳이 원문
보관을 요구**한다.

1. **기능이 둘인데 주기가 다르다** — 출력은 `긍정 비율(%)` + `2~3문장 요약`([roadmap §10](./ai-features-roadmap.md)).
   분류는 **리뷰 건당 1회**, 요약은 **레시피당 1회**다. 원문이 없으면 한쪽만 재실행할 수 없다.
2. **요약 모델이 아직 미확정** — [`ai-model-selection-final.md §5`](./ai-model-selection-final.md) 는
   요약을 **"구현 후 실측 필요 · 보류"** 로 두고, *"근거 대조 대상이 없는 자유 서술이라 가드레일로
   품질을 기계 검증할 수 없다 — 사람 확인(샘플 리뷰)이 필요하다"* 고 못 박았다. **그 사람 확인의
   대상이 원문이다.**
3. **프롬프트 개선 > 모델 교체** — 1,750건 실측의 최대 발견이다. 프롬프트를 고치면 재실행해야
   하는데, 원문이 없으면 **재크롤**뿐이다. 크롤이 이 파이프라인에서 가장 느리고 깨지기 쉽다
   (레시피당 0.6~1.2초 딜레이).

> 크롤은 비싸고 텍스트 저장은 싸다. 10K 레시피 × 리뷰 50건 × 300B ≈ **150MB** — PG 에서 신경 쓸
> 규모가 아니다.

### 닉네임을 저장하지 않는 이유

감정분류도 요약도 **본문만** 먹는다. 파이프라인 어디서도 닉네임을 쓰지 않으므로 수집 단계에서
버린다. 필요해지면 나중에 컬럼을 추가하는 편이 반대보다 쉽다.
⚠️ 닉네임 **파싱 로직은 남겨뒀다** — 후기 카드를 식별하는 데 쓰이기 때문이다. 저장만 하지 않는다.

---

## 3.5 변경 총괄 — 데이터 · 파이프라인

**이 표가 데이터 담당자에게 전달되는 변경의 전부다.** 상세 근거는 각 §참조.

### DB — 신규 테이블 7 · 기존 변경 1

| 대상 | 종류 | 근거 |
|---|---|---|
| `recipe_review` | 신규 | 원문 보관 — 요약 모델 미확정이라 재실행 필요 (§3) |
| `recipe_review_crawl` | 신규 | 시도 결과 — 재실행 시 반복 요청 차단 (§4.1) |
| `recipe_review_sentiment` | 신규 | 건당 라벨 + `model` = 재실행 대상 특정 (§4.1) |
| `recipe_review_summary` | 신규 | 레시피당 집계 + 요약 (표시용) |
| `price_baseline` | 신규 | 30일 μ·σ·표본수 — 알림 근거 재현 + 오탐 게이트 (§9.2) |
| `price_anomaly` | 신규 | 급락 이벤트 + 근거 스냅샷 — 합성금액 금지 원칙 (§9.2) |
| `price_alert_sent` | 신규 | 팬아웃 멱등 — KEDA at-least-once 방어 (§9.3) |
| **`recipebook.extract_job`** | **기존 변경** | `user_recipe_id` 1컬럼 추가 — 조용한 실패 탐지 (§10) |

⚠️ **기존 테이블 변경은 `extract_job` 하나뿐**이다. nullable + `IF NOT EXISTS` + DEFAULT 없음이라
테이블 재작성이 없다(잠금 순간).

### 파이프라인

| 대상 | 변동 | 근거 |
|---|---|---|
| Kafka — 리뷰 | **없음** | 후처리가 전혀 없어 컨슈머 불필요 → 직접 insert (§4.2) |
| Kafka — 가격 | **토픽 1개 추가** `events.price.anomaly` | CLAUDE.md "수집 + fan-out 2곳만" 의 fan-out (§9.3) |
| Docker | 폴러 2개 + 컨슈머 1개 | §4.3 · §9.4 |
| 크론 | 3줄 추가 | 리뷰 1 · 가격탐지 2 (§4.3 · §9.4) |
| Redis | **스키마 변동 없음** | 영상→레시피가 캐시(TTL 30일)·SETNX 락에 의존 — **용량·가용성만 인지** |
| ES | **없음** | 리뷰 원문 검색이 필요해지면 그때 (§2) |

### 이 변경이 **건드리지 않는 것**

`recipe` · `recipe_ingredient` · `recipe_step` · `retail_*` · `item_master` · `notify.*` ·
`price.price_watch` · `account.*` · `activity.*` — **전부 무변경.** 참조만 한다.

---

## 4. 데이터 담당자 전달사항

### 4.1 DB 변동 — 신규 테이블 4개 (기존 테이블 변경 없음)

적용 파일: [`docs/prd/migrations/2026-07-29_recipe_review.sql`](./prd/migrations/2026-07-29_recipe_review.sql)
(전부 `IF NOT EXISTS` — 여러 번 돌려도 안전). 정본 스키마는 [`schema-public-data.sql §G`](./prd/schema-public-data.sql).

| 테이블 | 역할 | 멱등 키 |
|---|---|---|
| `recipe_review` | 원문 (`recipe_id`, `seq`, `body`) | `UNIQUE(recipe_id, seq)` |
| `recipe_review_crawl` | 시도 결과 `ok`\|`no_review`\|`fail` — 재실행 시 반복 요청 차단 | `PK(recipe_id)` |
| `recipe_review_sentiment` | 파생① 건당 라벨 + `model` | `PK(review_id)` |
| `recipe_review_summary` | 파생② 레시피당 긍정비율 + 요약 | `PK(recipe_id)` |

**`model` 컬럼이 핵심이다.** 모델 교체 시 재실행 대상을 쿼리 한 줄로 특정한다:
```sql
select review_id from recipe_review_sentiment where model <> '<신규모델>';
```

**기존 테이블·컬럼 변경 0건.** `recipe` 를 FK 로 참조만 한다(`ON DELETE CASCADE`).

### 4.2 Kafka 변동 — **없음**

기존 크롤러(`10k_recipe_crawler.py`)는 `recipe.crawl.raw` 로 produce 하고 컨슈머가 upsert·재료
재삽입·gazetteer 매칭까지 한다. **리뷰는 그 경로를 타지 않는다.**

- 리뷰는 후처리(정규화·매칭·enrichment)가 **전혀 없다** — 크롤 결과가 곧 최종 형태다
- 컨슈머를 새로 만들 이유가 없어 **크롤러가 PG 에 직접 insert** 한다
- 토픽 추가·컨슈머 변경·스키마 등록 **전부 불필요**

> Kafka 경로로 바꿔야 할 사정이 생기면 `save_reviews()` 한 함수만 교체하면 된다.

### 4.3 Docker 변동 — 폴러 1개 추가

기존 `poller-recipe` 와 **같은 이미지·같은 패턴**이다. 볼륨은 필요 없다(상태를 DB 가 들고 있음).

```yaml
  poller-recipe-review:        # 만개 요리후기 수집 → PG 직접 적재(Kafka 미경유)
    <<: *app
    restart: "no"
    profiles: ["poller"]
    command: python /app/crawler/10k_recipe/review_crawler.py
```

크론은 [`deploy/crontab.fb-pollers`](../deploy/crontab.fb-pollers) 에 한 줄. `poller-recipe`(일·수
05:00 KST 신규 레시피 포착) **이후**에 돌아야 새 레시피의 후기를 잡는다:

```
0 21 * * 2,6   __RUN__ poller-recipe-review   # = 일·수 06:00 KST — poller-recipe(05:00) 뒤
```

⚠️ `poller-es-recipes` 가 06:30 KST 라 그 앞 30분 창에 넣었다. **전량 첫 수집은 몇 시간이 걸리므로
크론 등록 전에 수동 1회 완주**를 권한다.

`FB_POLLER_RECORDS <n>` 을 출력하므로 [`deploy/run-poller.sh`](../deploy/run-poller.sh) 의 집계가
그대로 동작한다(수집 리뷰 건수).

---

## 5. 검증 상태 — 어디까지 믿어도 되나

| 항목 | 상태 | 방법 |
|---|---|---|
| 모듈 import | ✅ | venv 에 의존성 설치 후 실제 `exec_module` |
| 필수 심볼 7개 | ✅ | AST 확인 |
| **실제 페이지 파싱** | ⚠️ | 레시피 `6778614` → **리뷰 187건 추출 성공. 단 n=1** — 3단 파서(CSS·헤딩·평문)가 있다는 건 레이아웃이 여럿이라는 뜻이라, 다른 레이아웃은 미검증 |
| 크롤 설정 보존 | ✅ | 워커 3 · 딜레이 0.6~1.2s · 타임아웃 15s (원본 그대로) |
| 닉네임 제외 | ✅ | 적재 튜플이 `(recipe_id, seq, body)` 3개뿐 |
| SQL 생성 로직 | ✅ | 두 모드 문자열 생성 확인 |
| **DB 연결** | ❌ | **미검증** |
| **DDL 적용** | ❌ | **미검증** |
| **SQL 실제 실행** | ❌ | **미검증** — 컬럼·FK·`ON CONFLICT` 문법 |
| 커넥션 폭주 | ❌ | 레시피당 커넥션 2개. 3시간 크롤에서 롱리브 커넥션이 끊기는 것보다 안전하다고 판단했으나 **실측 안 함** |

> ⚠️ **`py_compile` 통과는 동작을 뜻하지 않는다.** 실제로 이 PC 에서는 의존성이 없어 import 조차
> 실패했다(`ModuleNotFoundError: dotenv`). venv 를 만들어 다시 확인한 것이 위 표다.
>
> ⚠️ **파싱 검증은 표본 1건이다.** `--limit 50` 단계에서 `recipe_review_crawl` 의 `no_review` 비율을
> 반드시 확인할 것 — 비정상적으로 높으면 파서가 못 잡는 레이아웃이 있다는 신호다.

### 알려진 한계 — 동적 로딩

만개는 일부 후기를 **스크롤/더보기로 추가 로딩**한다. 이 크롤러는 상세 페이지 HTML 에 **처음
실린 후기까지만** 수집한다(원본 설계 그대로 — 헤드리스 브라우저를 쓰지 않는다).
표본 1건에서는 187건이 나와 실사용에 충분해 보이지만, **레시피당 실제 후기 수보다 적을 수 있다**.
긍정 비율(%)은 표본 비율이므로 이 절단이 편향을 만들지는 확인되지 않았다 — 감정분석 착수 전에
몇 건을 육안 대조하는 편이 안전하다.

### 잡은 버그 2건 (수정 완료)

1. **`--retry-failed` 가 전량 재크롤을 유발** — LEFT JOIN 의 `ON` 절에 상태 조건을 넣으면 매칭만
   실패할 뿐 행이 남아 **10K 레시피 전체**가 대상이 됐다. `WHERE` 로 옮겨 수정.
2. **죽은 코드** — `append_csv_row`·`REVIEW_COLUMNS`·`normalize_recipe_url` 등 CSV 잔재 제거
   (881 → 794 줄), 미사용 import 3개(`csv`·`os`·`urljoin`) 정리.

---

## 6. 실행 순서 (접속 가능한 환경)

```bash
pip install "psycopg[binary]" python-dotenv requests beautifulsoup4 urllib3

# .env — .env.example 은 PG 키가 전부 주석 처리돼 있다. 주석을 풀고 PGPASSWORD 를 채운다
#        (비번은 infra/ansible/secrets.yml)

# ⓪ 🔴 프리플라이트 — 읽기 전용. 실패하면 여기서 멈춘다 (§8)
psql -h 192.168.0.8 -U fbapp -d foodbudget \
     -f docs/prd/migrations/2026-07-29_preflight.sql

# ① DDL 적용 (⓪ PASS 후에만)
psql -h 192.168.0.8 -U fbapp -d foodbudget \
     -f docs/prd/migrations/2026-07-29_recipe_review.sql
psql -h 192.168.0.8 -U fbapp -d foodbudget \
     -f docs/prd/migrations/2026-07-29_price_anomaly.sql
psql -h 192.168.0.8 -U fbapp -d foodbudget \
     -f docs/prd/migrations/2026-07-29_extract_job_link.sql   # 기존 테이블 변경 1건

# ② 🔴 첫 관문 — 아무것도 쓰지 않는다. 여기서 반드시 끊고 확인
python crawler/10k_recipe/review_crawler.py --dry-run --limit 20

# ③ 시범 수집 (DB 쓰기 첫 발생)
python crawler/10k_recipe/review_crawler.py --limit 50

# ④ 전량
python crawler/10k_recipe/review_crawler.py
```

**②에서 URL 20개가 뜨면 DB 연결·쿼리·DDL 이 전부 정상이다.** 미검증 항목이 여기서 한 번에 해소된다.
③ 이후 확인:

```sql
select count(*) from recipe_review;
select status, count(*) from recipe_review_crawl group by status;
```

---

## 7. 남은 일

| 순서 | 할 일 | 참조 |
|---|---|---|
| 1 | DDL 적용 + `--dry-run` 통과 | §6 |
| 2 | 전량 수집 1회 완주 후 크론 등록 | §4.3 |
| 3 | 감정분류 구현 — `apac.amazon.nova-micro-v1:0`(서울) **확정** | [selection-final §4](./ai-model-selection-final.md) |
| 4 | 요약 구현 — 모델 **미확정**, 구현 후 사람 확인 필요 | [selection-final §5](./ai-model-selection-final.md) |
| 5 | 가격 이상탐지 배치 `detect_price_anomaly.py` 구현 | §9 · ai-spec §2 |
| 6 | 팬아웃 컨슈머 구현(`events.price.anomaly` → `notify.notification`) | §9.3 |


---

## 7.5 산출물 요구 — 적용 결과 리포트

적용을 마친 뒤 **결과 리포트를 남긴다.** 이 핸드오프는 *"무엇을 왜 바꾸려는가"* 이고,
리포트는 *"실제로 무엇이 바뀌었는가"* 다. 둘은 다르다 — 프리플라이트에서 설계가 수정될 수 있고,
G2·G3 에서 실측치(리뷰 건수·소요시간·오탐률)가 나온다.

### 형식 — `.md` + `.html` 쌍

레포 관례상 **보고용 리포트만 `.html` 쌍을 갖는다**(현재 5건: `ai-model-selection-final` ·
`ai-model-migration-benchmark` · `ai-model-quality-uplift` · `hybrid-cloud-federation-plan`).
핸드오프 6건은 전부 `.md` 단독이다. 이 문서도 `.md` 단독이고, **리포트는 쌍으로 만든다.**

```
docs/recipe-review-apply-report.md
docs/recipe-review-apply-report.html
```

### 담을 내용

| 항목 | 왜 |
|---|---|
| 프리플라이트 결과 전문 | PASS/FAIL·경고. 특히 **B3 관측일수**·**C2 LOW_PRICE CHECK** 실측치 |
| 적용된 DDL 목록 + 실행 시각 | 어느 마이그레이션이 언제 반영됐는지 |
| **설계에서 바뀐 것** | 프리플라이트가 잡아낸 불일치와 그 대응. **없으면 "없음"이라고 쓴다** |
| G0~G3 판정 결과 | §11 기준표 그대로 ✅/❌ |
| 실측치 | 크롤 대상 건수 · 수집 리뷰 수 · 소요시간 · `no_review` 비율 |
| 파이프라인 반영 | 토픽 생성 여부 · compose·크론 반영 여부 |
| 미결·후속 | 남은 항목과 담당 |

> `no_review` 비율은 특히 중요하다 — §5 의 "파싱 표본 1건" 한계를 검증하는 유일한 실측 지표다.

---

## 8. 🔴 프리플라이트 — 적용 전 안전장치

파일: [`docs/prd/migrations/2026-07-29_preflight.sql`](./prd/migrations/2026-07-29_preflight.sql)
**읽기 전용**이다 — 아무것도 생성·변경하지 않는다.

### 왜 필요한가

이 설계는 **작업 PC 가 DB 에 닿지 않는 상태**에서 만들어졌다(§12). 근거는 전부 레포의 스키마
파일이지, 실 DB 를 본 것이 아니다. 둘이 어긋날 수 있는 경로는 실재한다 — 수동 변경, 마이그레이션
누락, 다른 DB 접속. **어긋난 채 DDL 을 적용하면 FK 가 깨지거나 배치가 조용히 틀린 값을 낸다.**

### 무엇을 검사하나 (실패 15 · 경고 4)

| 구분 | 검사 |
|---|---|
| **A 리뷰** | `recipe` 존재 + `id`·`source`·`src_recipe_id` 컬럼 · **`source='10K'` 대상 건수** |
| **B 가격** | `item_master`(FK) · `retail_price.crawled_at`(윈도우) · `retail_product.weight_g`(정규화) · **최근 30일 관측 일수** |
| **C 알림** | `price.price_watch` · `notify.notification` + **`type` CHECK 에 `LOW_PRICE` 가 실제로 있는지** |
| **D 충돌** | 신규 테이블이 이미 있는지 · **기존 `recipe_review` 에 `nickname` 컬럼이 있으면 즉시 실패**(설계 불일치) |

핵심은 **B3 와 C2** 다.

- **B3** — 관측이 28일 미만이면 경고한다. ai-spec §4.1 의 *"baseline 4주 미만 오탐↑"* 을 배포 전에
  숫자로 알려준다. 몰랐다면 오탐이 쏟아진 뒤에야 알게 된다.
- **C2** — `notify.notification.type` 의 CHECK 에 `LOW_PRICE` 가 없으면 알림 insert 가 **런타임에**
  실패한다. 스키마 파일엔 있지만 실 DB 에 반영됐는지는 별개다.

### 실행

```bash
psql -h 192.168.0.8 -U fbapp -d foodbudget \
     -f docs/prd/migrations/2026-07-29_preflight.sql
```

| 결과 | 의미 | 다음 |
|---|---|---|
| `PREFLIGHT PASS` + 종료코드 0 | 전제 성립 | §9 DDL 적용으로 진행 |
| `PREFLIGHT FAIL` + EXCEPTION | 전제 어긋남 | **DDL 적용 금지.** 메시지가 지목한 항목을 확인하고 **설계를 먼저 고친다** |
| 경고만 출력 후 PASS | 진행 가능하나 인지 필요 | 특히 B3(기준선 미성숙)은 탐지 게이트로 흡수 |

> ⚠️ **이 프리플라이트 자체도 실행 검증되지 않았다** — PG 에 붙지 못했다. 문법 오류로 죽으면
> 그것은 프리플라이트의 문제이지 DB 의 문제가 아니다. 그 경우 검사 내용을 수동으로 확인하면 된다.

---

## 9. 가격 이상탐지(#9) · 최저가 알림(#6) — DB·파이프라인

적용 파일: [`docs/prd/migrations/2026-07-29_price_anomaly.sql`](./prd/migrations/2026-07-29_price_anomaly.sql)

### 9.1 기존 자산 재사용 — 신규 생성하지 않는 것

설계 착수 전 확인한 결과 **알림 도메인은 이미 완비돼 있다.** 새로 만들면 중복이다.

| 이미 있는 것 | 그대로 쓰는 이유 |
|---|---|
| `price.price_watch(user_id, item_id)` | ai-spec §2 "관심 등록 = ⓐ 명시 등록" 확정분이 이미 스키마로 존재 |
| `notify.notification` | `type` CHECK 에 **`'LOW_PRICE'` 가 이미 있다** — 알림 본문·읽음처리·payload 전부 준비됨 |
| `notify.notification_setting.low_price` | 유저별 수신 거부가 이미 있다 |
| `retail_price` × `retail_product` | 시계열 원천. 크롤이 이미 적재 중 |

### 9.2 신규 테이블 3개

| 테이블 | 역할 | 멱등 키 |
|---|---|---|
| `price_baseline` | 품목별 30일 μ·σ·표본수 (배치 산출) | `PK(item_id, as_of)` |
| `price_anomaly` | 급락 이벤트 + 근거 스냅샷 | `UNIQUE(item_id, detected_on, source)` |
| `price_alert_sent` | 팬아웃 발송 이력(중복 차단) | `PK(anomaly_id, user_id)` |

**설계 판단 3가지 — 근거와 함께:**

1. **`retail_unit_price`(물질화 뷰)를 쓸 수 없다.** `rn=1` 로 **최신 스냅샷만** 남기는 뷰라
   이동평균의 입력이 못 된다. 기준선은 `retail_price`(시계열) × `retail_product.weight_g` 로
   직접 계산한다. ← 이 점을 놓치면 배치가 조용히 잘못된 값을 낸다.

2. **단가는 `won_per_100g` 로 정규화한다.** 컬리·오아시스는 팩 크기가 달라 raw price 를 섞으면
   σ 가 팩 크기 아티팩트로 부풀고 진짜 급락이 묻힌다. 정규화해야 ai-spec §2 의 *"2축이라
   baseline 이 2배 속도로 축적"* 이 성립한다(같은 축에 쌓임).

3. **`obs_count` 가 오탐 게이트다.** ai-spec §4.1 이 경고한 *"baseline 4주 미만 구간 오탐↑"* 을
   코드 상수가 아니라 **데이터로** 판정한다 — 표본수가 임계 미만이면 탐지를 건너뛴다.

`price_anomaly` 가 `retail_product_id` + `crawled_at` 으로 **실제 상품 스냅샷**을 가리키는 것은
roadmap §6 의 *"합성금액 금지 — 화면엔 실상품+실가격+용량+시점"* 원칙을 스키마 수준에서
강제하기 위해서다.

### 9.3 Kafka 변동 — **토픽 1개 추가**

리뷰와 달리 **여기는 Kafka 를 쓴다.** CLAUDE.md 의 *"Kafka 는 수집 + fan-out 2곳만"* 원칙에서
**fan-out 이 정확히 이 경우**다(ai-spec §2 · §7.1 · §8.2).

| 항목 | 값 |
|---|---|
| 토픽 | `events.price.anomaly` — **자동 생성 아님. 두 곳에 선언한다**: [`pipelines/stream/create_topics.py`](../pipelines/stream/create_topics.py)(`NewTopic`) + `deploy/k8s/kafka-topics.yaml`(Strimzi `KafkaTopic`) |
| producer | 탐지 배치 (`price_anomaly` insert 후 발행, `published_at` 기록) |
| consumer | 팬아웃 — `price_watch` 조회 → `notify.notification` insert → `price_alert_sent` 기록 |
| 스케일 | **KEDA**(컨슈머 랙 기반). at-least-once 라 `price_alert_sent` PK 가 중복 발송의 유일한 방어선 |

### 9.4 Docker 변동 — 폴러 1개 + 컨슈머 1개

```yaml
  poller-price-anomaly:        # 기준선 산출 + 급락 판정 → Kafka events.price.anomaly
    <<: *app
    restart: "no"
    profiles: ["poller"]
    command: python pipelines/ingest/detect_price_anomaly.py --kafka
```

크론은 **가격 크롤 직후**여야 한다. 현행 크롤은 오아시스 04:10·13:10 KST, 컬리 03:30 KST 이므로:

```
40 19 * * *   __RUN__ poller-price-anomaly   # = 04:40 KST — 오아시스(04:10) 직후
40 4  * * *   __RUN__ poller-price-anomaly   # = 13:40 KST — 오아시스(13:10) 직후
```

팬아웃 컨슈머는 상시 기동이라 폴러가 아니라 **일반 서비스**로 올라간다(기존 refiner 컨슈머와 동일 패턴).

> ⚠️ **탐지 배치·컨슈머 코드는 아직 없다.** 이 문서는 **스키마와 배선만** 확정한다. 구현은 §7 참조.

---

## 10. 설계 커버리지 — AI 기능 11개 기준

| # | 기능 | 상태 | DB 설계 |
|---|---|---|---|
| 1 | RAG 챗봇 | 🟢 운영 | ✅ 기존 (`chat.chat_message`) |
| 2 | 영수증 OCR | 🟢 운영 | ✅ 기존 (`pantry.ocr_receipt*`) |
| 3 | 개인화 랭킹 | 🟢 운영 | ✅ 기존 (`activity.*`) |
| 4 | 대화분석 | 🟢 운영 | ✅ 기존 |
| 5 | 재료 NER | 🟡 미서빙 | **해당 없음** — *"오프라인 학습 아티팩트, PG 는 1회 스냅샷만"* 이 확정 결정 |
| 6 | 최저가 알림 | 🔵 미구현 | ✅ **§9** (신규 3 + 기존 재사용) |
| **7 · 11** | **영상→레시피 = 유튜브 영상분석** | 🟠 착수 | ✅ **기존 설계 존재** + 본 문서 보완 |
| 8 | 이상징후 대시보드 | ⬜ 예정 | **범위 밖** — 인프라/클라우드 담당, Prometheus 계열 |
| 9 | 가격 이상치 | ⬜ 예정 | ✅ **§9** |
| 10 | 리뷰 감정분석 | ⬜ 예정 | ✅ **§4** |

**9/11 설계 완료.** 5는 설계 대상이 아니고 8은 소유자가 다르므로, **AI 기능의 DB 설계에 미설계로
남는 것은 없다.**

### 7·11 은 같은 기능이고, 스키마가 이미 있었다

*"유튜브 URL → 유효성 확인 → 재료·스텝 추출 → 우리 서비스 레시피처럼 조리법 생성"* 이 요구사항이다.
이는 **전역 카탈로그(`recipe`)가 아니라 유저 레시피북**에 들어간다 —
[`video-recipe-ai.md`](./video-recipe-ai.md) 의 파이프라인 마지막 단계도 *"→ 레시피북 저장"* 이다.

```sql
recipebook.extract_job      -- URL 제출 → 작업 추적
  url · status CHECK('PENDING','DONE','FAILED') · result jsonb
recipebook.user_recipe      -- 추출 결과 = 레시피
  origin CHECK('MANUAL','YOUTUBE')   ← YOUTUBE 가 이미 있다
  source_url · ingredients jsonb · steps jsonb
  cooking_time · serving · level_nm  ← 주석: "만개 레시피와 동일 메타(칩)"
```

`cooking_time`·`serving`·`level_nm` 주석의 *"만개 레시피와 동일 메타"* 가 곧 *"우리 서비스
레시피처럼"* 이다. **설계 의도가 이미 반영돼 있었다.**

**보완 1건** — [`2026-07-29_extract_job_link.sql`](./prd/migrations/2026-07-29_extract_job_link.sql):
`extract_job.user_recipe_id` 를 추가한다. 역방향(레시피→영상)은 `source_url` 로 되지만 순방향이
비어 있어 ①`status='DONE'` 인데 산출물이 없는 **조용한 실패를 감지할 수 없고** ②재처리가 갱신인지
신규 생성인지 판단할 수 없었다. `ON DELETE SET NULL` 인 이유는 레시피가 지워져도 **추출 시도
기록은 남아야** 하기 때문이다(`shared_recipe` 는 CASCADE — 정책이 다르다).

---

## 10.5 앞으로 데이터측 재접근이 필요한 시점

**"이제 데이터쪽은 안 건드려도 되나"에 대한 정직한 답이다.** 스키마는 사실상 끝났지만,
파이프라인 작업은 남아 있다.

### ✅ 재접근 불필요 — 이 설계가 흡수한다

| 상황 | 이유 |
|---|---|
| 감정분석 모델 교체 | `model` 컬럼으로 재실행 대상만 쿼리 |
| 요약 프롬프트 개선 후 재생성 | 원문이 DB 에 있어 재크롤 불필요 |
| 리뷰 재수집·중단 후 재개 | `recipe_review_crawl` 이 상태 보유 |
| 가격 이상탐지 임계 조정 | `price_anomaly` 에 z·μ·σ 가 남아 사후 분석 가능 |
| 최저가 알림 발송 | `notify.notification` 재사용 — 알림 도메인 무변경 |
| 영상→레시피 구현 | `extract_job` + `user_recipe` 로 충분 |

### ⏳ 아직 남은 작업 — 스키마가 아니라 **구현·배포**

| 항목 | 성격 | 문서 |
|---|---|---|
| DDL 적용 · 토픽 생성 · compose · 크론 | **적용** (설계는 끝, 반영이 안 됨) | §6 · §9.3 · §9.4 |
| 탐지 배치 `detect_price_anomaly.py` | **코드 미작성** | §9 |
| 팬아웃 컨슈머 | **코드 미작성** | §9.3 |
| 감정분류·요약 배치 | **코드 미작성** | §7 |

### ⚠️ 예측 불가 — 구현 중 나올 수 있는 것

- **배치 재개 상태·재시도 카운터** 등 운영 컬럼이 필요해질 수 있다(구현해봐야 안다)
- **리뷰 원문 ES 색인** — 검색이 필요해지면 (§2에서 "그때" 로 유보)
- **P2 데이터 이전** — PG 가 in-cluster 로 가면 이 테이블들도 함께 이동한다.
  [`mp_k8s_p2_data_runbook.md`](./mp_k8s_p2_data_runbook.md) 트랙과 조율 필요
- **Redis 용량** — 영상→레시피가 캐시(TTL 30일)·SETNX 락에 의존한다. 스키마는 없지만
  [`mp_k8s_redis_ha_handoff.md`](./mp_k8s_redis_ha_handoff.md) 트랙과 무관하지 않다

---

## 11. 🔴 고정 판정 기준 — 무엇이 통과하면 이대로 확정인가

아래가 **전부** 통과하면 스키마·파이프라인을 고정한다. 하나라도 실패하면 그 항목만 수정한다.

### G0. 프리플라이트 (데이터 담당자) — **최우선**

```bash
psql -h 192.168.0.8 -U fbapp -d foodbudget -f docs/prd/migrations/2026-07-29_preflight.sql
```

| 통과 조건 | 확인 |
|---|---|
| `PREFLIGHT PASS` 출력 | 종료코드 0 |
| 실패 0건 | ❌ 표시가 하나도 없음 |
| 경고 인지 | ⚠️ 항목은 §8 표로 대응 판단 |

🔴 **G0 실패 시 G1 이하를 진행하지 않는다.** 설계 전제가 실 DB 와 다르다는 뜻이므로,
DDL 이 아니라 **설계를 먼저 고쳐야 한다**.

### G1. DDL 적용 (데이터 담당자)

```bash
psql -h 192.168.0.8 -U fbapp -d foodbudget -f docs/prd/migrations/2026-07-29_recipe_review.sql
psql -h 192.168.0.8 -U fbapp -d foodbudget -f docs/prd/migrations/2026-07-29_price_anomaly.sql
```

| 통과 조건 | 확인 |
|---|---|
| 두 파일 모두 에러 없이 COMMIT | 종료코드 0 |
| 테이블 7개 생성 | `\dt recipe_review*` 4개 · `\dt price_*` 3개 |
| FK 가 실제로 걸림 | `\d recipe_review` 에 `recipe(id)` 참조 표시 |
| 재실행 안전 | **같은 파일을 한 번 더 실행** → 에러 0 (`IF NOT EXISTS`) |

### G2. 크롤러 실동작 (AI 담당자)

| 통과 조건 | 명령 | 기대 |
|---|---|---|
| 대상 조회 | `review_crawler.py --dry-run --limit 20` | URL 20개 출력, 쓰기 0 |
| 적재 | `--limit 50` | `recipe_review` 행 증가 · `recipe_review_crawl` 에 50행 |
| **멱등** | **같은 명령 재실행** | `recipe_review` 건수 **불변**, 중복 0 |
| 재개 | 다시 `--limit 50` | 이전 50건은 건너뛰고 **새 50건**만 |

```sql
select count(*) from recipe_review;
select status, count(*) from recipe_review_crawl group by status;
select recipe_id, seq, count(*) from recipe_review group by 1,2 having count(*) > 1;  -- 0행이어야 함
```

### G3. 파이프라인 정합 (데이터 담당자)

| 통과 조건 | 확인 |
|---|---|
| Kafka 토픽 영향 | 리뷰 = **변동 0** · 가격 = `events.price.anomaly` 1개 추가만 |
| 기존 컨슈머 무영향 | `recipe.crawl.raw` 컨슈머 코드 **변경 0** |
| 폴러 등록 | compose 에 `poller-recipe-review` 추가 후 `--dry-run` 이 컨테이너 안에서 동작 |
| 집계 연동 | `run-poller.sh` 로그에 `FB_POLLER_RECORDS <n>` 파싱됨 |

### G4. 고정 선언

G1~G3 전부 ✅ → **이 스키마·파이프라인을 고정한다.** 이후 변경은 새 마이그레이션 파일로만 한다
(기존 파일 수정 금지 — 이미 적용된 환경과 어긋난다).

⚠️ **미충족 시 되돌리기**: 각 마이그레이션 파일 하단의 롤백 SQL 참조. 기존 테이블은 건드리지
않으므로 신규분만 DROP 하면 원상복구된다.

---

## 12. 접근 제약 (이 작업이 여기서 끝난 이유)

작업 PC 가 인프라와 **다른 네트워크 세그먼트**에 있어 `192.168.0.8` 에 닿지 않는다. 대역이
`192.168.0.0/24` 로 같아 보이지만 ARP 상 `.17`(문서상 `k8s-master`)이 **랜덤 MAC**(개인 단말)로
잡힌다 — 같은 건물의 일반 Wi-Fi 이고 인프라는 별도 세그먼트다. 자격증명 문제가 아니라 경로 문제라
비밀번호를 받아도 해결되지 않는다.
