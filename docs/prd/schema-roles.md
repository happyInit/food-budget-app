# PG 서비스별 롤 격리 — 설계 · 적용 런북

> 이슈 [#546](https://github.com/happyInit/food-budget-app/issues/546) · AWS 이관 체크리스트 **0-13**(C-24 파드 신원 설계의 전제).
> 짝 파일 = **`docs/prd/schema-roles.sql`**(멱등 DDL). 이 문서 = 왜·어떤 순서로·어떻게 되돌리나.
> 스키마 정본은 계속 `docs/prd/schema-production.md` 다. 이 문서는 그 §0.3(롤 셋업)의 **실행 설계**이며,
> §0.3 과 다른 부분은 §2 에 전부 명시했다. 🔴 §0.3 자체는 아직 수정하지 않았다 — §7 결정 대기.

**상태: 설계만. 아직 아무것도 적용하지 않았다.** DDL 파일은 만들었지만 라이브 DB 에 돌리지 않았다.

---

## 1. 실측 (2026-08-09)

전부 `pg-1`(CNPG primary)에 읽기 전용 쿼리로 직접 확인했다.

### 1.1 롤 — 로그인 가능한 것 7개

| 롤 | OID | 속성 | 비밀번호 | 쓰는 곳 |
|---|---|---|---|---|
| `terraform` | **10** | **Superuser · CreateRole · CreateDB · Replication · BypassRLS** | scram | 🔴 아래 참조 |
| `postgres` | 37278 | Superuser | **없음**(`enableSuperuserAccess: false`) | local peer 전용 |
| `fbapp` | 16403 | 평범 | scram | **앱 11 + 파이프라인 22 전부** |
| `pgsync` | 17960 | Replication | scram | PGSync CDC |
| `streaming_replica` | — | Replication | scram | CNPG 복제 |
| `cnpg_pooler_pgbouncer` | — | 평범 | 없음(cert) | PgBouncer auth_query |
| `cnpg_metrics_exporter` | — | `pg_monitor` | 없음(peer) | 메트릭 |

🔴 **`terraform` 은 잔재가 아니다 — 이 클러스터의 initdb 부트스트랩 슈퍼유저다.**
이슈 #546 은 *"구 PG backend 잔재로 보임"* 이라고 적었는데 **틀렸다**. 근거 3가지:
① `oid = 10` (initdb 가 만드는 부트스트랩 롤의 고정 OID) ② `postgres`/`template0`/`template1` DB 의
owner 가 전부 `terraform` ③ `pg_stat_activity` 의 **logical replication launcher** 백그라운드 워커가
`terraform` 으로 뜬다. **DROP 하면 안 된다.**
다만 **scram 비밀번호가 살아 있고** `pg_hba` 가 `host all all all scram-sha-256` 이라
**네트워크에서 슈퍼유저로 로그인 가능**하다. → 별건 후속(§7-③).

### 1.2 스키마 — 9개 (`data` 는 **없다**)

`foodbudget` DB · owner 는 `public` 빼고 전부 `fbapp`.

```
account(3)  activity(4)  chat(1)  mealplan(2)  notify(2)
pantry(4)   price(1)     recipebook(5)         public(24)
```

🔴 **`data` 스키마는 실물에 존재하지 않는다.** `schema-production.md §0.3` 의 GRANT 예시는
전부 `data` 스키마 전제인데, 데이터 티어(크롤·공공데이터 24개 릴레이션)는 **`public` 에 있다**.
이건 이미 `schema-production.sql:4-5` 가 적어둔 사실이다 —
*"데이터 티어는 현재 `public`. 문서의 `data.*` 는 이전 목표"*. 이 설계는 실물을 따른다.

🔴 **`operations` 스키마도 없다.** `services/operations/app/queries.py` 는 `operations.anomalies`
`operations.incidents` `operations.alerts` 를 쓰지만 우리 DB 에 그 스키마가 없다.
이유 확인됨 — **mp-operations 는 우리 PG 를 안 쓴다.** config 레포
`services/operations/base/deployment.yaml` 이 `PGHOST`/`PGUSER`/`PGDATABASE` 를 통째로 덮어써
**외부 교육용 PostgreSQL(팀2)** 로 보낸다. 그래서 이 이슈의 롤 대상이 아니다.

### 1.3 접속 주체 — 33 워크로드가 `fbapp` 하나로

| 구분 | 개수 | 접속 경로 | 근거 |
|---|---|---|---|
| app ns · Pooler 경유 | **9** | `pg-pooler.data.svc` | `app-common` ConfigMap `PGUSER=fbapp` |
| app ns · **직결** | **2** | `pg-rw.data.svc` | `ocr` · `ranking-serving` 오버레이 `pg-direct.yaml`(의도적 제외) |
| app ns · 우리 DB 아님 | 1 | 외부 | `operations` |
| app ns · DB 없음 | 1 | — | `frontend`(nginx) |
| pipeline ns | **22** | `pg-rw.data.svc` 직결 | `mp-pipeline-env` `PGUSER=fbapp` |

즉 이슈 서술 *"앱 9종"* 은 **과소 계상**이다. 실제로 `fbapp` 자격증명을 쥔 파드는
**app 11 + pipeline 22 = 33**이고, 그중 22개는 `mp-pipeline-secrets` 를 `envFrom` 통째로 받는다
(체크리스트 0-14d 와 같은 오브젝트).

### 1.4 서비스 × 스키마 접근 매트릭스 (코드 실측)

`services/**/*.py` · `pipelines/**/*.py` · `ml/recipe-ranking/serve.py` 의 SQL 을 전수 확인했다.
`R`=SELECT · `W`=INSERT/UPDATE/DELETE.

| 워크로드 | 자기 스키마 | public(데이터 티어) | 남의 스키마 |
|---|---|---|---|
| account | `account` RW | — | — |
| recipebook | `recipebook` RW | R | — |
| pantry | `pantry` RW | — *(§0.3 은 R 을 준다 — 코드엔 0건)* | — |
| mealplan | `mealplan` RW | R | 🔴 `activity.recipe_impression` **W** |
| price | `price` RW | R | — |
| notify | `notify` RW | — | — |
| chat | `chat` RW | R | — |
| recipe | 없음 | R | — |
| video | 없음 | R | — |
| ocr | 없음 | R | — |
| ranking-serving | 없음 | R | `activity.*` R |
| **pipeline(22)** | — | **W** | `activity` W · `notify.notification` W · `pantry.pantry_item` U · 🔴 `chat.chat_message` **D** · 🔴 `account.app_user` **R** |

- 🔴 **크로스-스키마 쓰기 1건 실재** — mealplan 이 추천 노출을 `activity.recipe_impression` 에
  직접 INSERT 한다(`services/mealplan/app/queries.py:insert_impressions`, 코드 주석에
  *"mealplan 직접 write"* 로 명시). 설계 규칙(*크로스-서비스는 API 호출*)의 문서화된 예외다.
- chat 이 `account.user_excluded_item` 을 참조하는 곳은 **주석과 HTTP 클라이언트뿐**이다
  (`chat/app/pipeline/account_client.py`) — SQL 이 아니다. 즉 **지금도 chat 은 account 를 SQL 로 안 읽는다.**
  그런데 `fbapp` 이라서 **읽을 수 있다**. 이게 #546 이 지적한 바로 그 간극이다.
- 🔴 **파이프라인이 `account` 를 읽어야 한다** — `mp-user-data-pruner`(`pipelines/stream/prune_user_data.py`)가
  보존창 180일 청소와 **동의 철회 유저 정리**를 하면서 `chat.chat_message` 를 DELETE 하고
  `account.app_user.activity_consent` 를 SELECT 한다. 파이프라인을 account 에서 완전히 떼어낼 수 없다.
  → **컬럼 단위 GRANT** 로 좁혔다: `GRANT SELECT (id, activity_consent) ON account.app_user`.
  즉 파이프라인이 뚫려도 **email·password_hash 는 못 읽는다.**
- 서비스 코드에 **DDL 은 0건**이다(`CREATE`/`ALTER`/`TRUNCATE`/`REFRESH` 검색 0). → 서비스 롤에 CREATE 불요.
- 파이프라인의 `migrate_*.py`·`apply_schema.py` 는 **CronJob 이 아니다**(CronJob 17개 args 전수 확인) →
  DDL 은 계속 사람이 `fbapp`/`postgres` 로 돌린다. **`svc_pipeline` 에도 CREATE 불요.**
- 단 하나의 예외 = `mp-poller-price-matview` 의 **`REFRESH MATERIALIZED VIEW public.retail_unit_price`**.
  이건 **GRANT 로 줄 수 없고 소유자만** 할 수 있다 → 4단계에서 그 객체 하나만 소유권을 넘긴다.

### 1.5 PgBouncer — 인증은 안 바뀐다, **풀 산수는 바뀐다**

작업 지시에 *"pooler 인증 설정이 함께 바뀐다"* 고 돼 있었는데, **인증은 안 바뀐다.**
실측한 `pgbouncer.ini`:

```
auth_type    = hba          auth_hba_file = /controller/configs/pg_hba.conf   (host all all 0.0.0.0/0 md5)
auth_user    = cnpg_pooler_pgbouncer
auth_query   = SELECT usename, passwd FROM public.user_search($1)
auth_dbname  = postgres
pool_mode    = transaction
```

`public.user_search` 는 `postgres` DB 에 있는 **SECURITY DEFINER 함수**(owner=postgres,
EXECUTE=cnpg_pooler_pgbouncer)로 `pg_shadow` 를 조회한다 → **임의의 롤을 자동으로 해석한다.**
새 롤을 추가해도 Pooler 쪽 인증 설정은 **손댈 게 없다**. (hba 의 `md5` 는 pgbouncer 에서
"패스워드 방식"을 뜻하며 저장된 시크릿이 SCRAM 이면 SCRAM 으로 협상한다 — 지금 `fbapp` 이 scram 인데
동작하는 것이 그 증거다.)

🔴 **대신 커넥션 상한 산수가 바뀐다.** PgBouncer 는 **(유저, DB) 쌍마다 별도 풀**을 만든다.

| 항목 | 실측값 |
|---|---|
| PG `max_connections` | **100** |
| `superuser_reserved_connections` | 3 → 가용 **97** |
| 현재 실제 접속 | 12 (fbapp 2 · pgsync 8 · replica 1 · psql 1) |
| pgbouncer `default_pool_size` | **20** |
| pgbouncer `max_db_connections` / `max_user_connections` | **0 = 무제한** |
| pgbouncer `max_client_conn` | 100 (인스턴스당) |
| pooler 인스턴스 | **2** |
| 앱 쪽 psycopg 풀 | pod 당 `max_size=5` |

```
지금  : 풀 1개(fbapp@foodbudget) × 20 × 2 인스턴스 =  40  ≤ 97   ✅
전환후: 풀 9개(svc_*@foodbudget) × 20 × 2 인스턴스 = 360  ≫ 97   ❌ 커넥션 고갈
```

→ **Pooler 파라미터를 같이 바꾸지 않으면 롤 분리가 그대로 장애다.** 제안값:

```yaml
# config 레포 data/pooler.yaml  spec.pgbouncer.parameters
default_pool_size:  "5"    # 9풀 × 5 × 2 = 90 (요구치)
max_db_connections: "25"   # 인스턴스당 하드캡 → 2 × 25 = 50 이 실제 천장
```

```
전환후 실효: pooler 50 + pgsync 8 + 직결(ocr 2 · ranking 2 · pipeline ~10) + replica 1 + exporter 1
           ≈ 74  ≤ 97   ✅ (여유 23)
```

- `min_pool_size = 0` 이라 9개 풀이 동시에 최대로 벌어지는 건 실부하에서만 일어난다.
- 실측 참고: k6 부하에서 recipe 4 replica 일 때도 PG 커넥션은 **12/100** 이었다.
  즉 `max_db_connections=25` 는 관측 피크의 4배 여유다.
- ⚠️ CNPG 가 `spec.pgbouncer.parameters` 에서 이 두 키를 허용하는지는 **적용 전에 dry-run 으로 확인**할 것
  (CNPG 는 `auth_*`·`listen_*`·`admin_users` 등을 차단한다 — 이 둘은 차단 목록이 아니지만 실증 필요).

### 1.6 비밀 배선 — 이미 서비스별 트랙이 깔려 있다

```
fb-secrets/app-secrets  ──ExternalSecret(ClusterSecretStore fb-kubernetes)──▶  app/mp-<svc>-secrets
   property: PGPASSWORD                                                          key: PGPASSWORD
```

- app ns 에 `mp-<svc>-secrets` **14개**가 이미 있고, 그중 **12개가 `PGPASSWORD` 키를 갖는다.**
  → 서비스별 비밀번호를 넣을 자리는 **이미 존재한다.** ExternalSecret 의 `remoteRef.property` 만 바꾸면 된다.
- 🔴 다만 **`fb-secrets/app-secrets` 에 넣으면 안 된다.** 체크리스트 **0-11**(SSM Parameter Store
  standard 4,096 B 한도)과 충돌한다. 실측:

  | | 값 |
  |---|---|
  | `app-secrets` 키 개수 | 13 |
  | 값 합계(디코딩) | **2,995 B** (그중 `GCP_SA_KEY_JSON` 혼자 2,376 B) |
  | JSON 번들 추정 | **≈ 3.3 KB** (체크리스트 0-11 의 3,385 B 와 일치) |
  | 4,096 B 대비 여유 | **≈ 711 B** |
  | 서비스 롤 **12개** 추가 시 증가분 | 키 123 B + 값 12×32 B + JSON 12×6 B = **579 B** |

  ⚠️ **정정** — 579 < 711 이므로 *지금 당장은* 한도를 넘지 않는다. 넘는다고 쓸 뻔했다.
  하지만 넣으면 **4,096 B 의 96.8%** 가 되고(0-11 이 이미 82.6% 를 위험으로 잡았다) 남는 여유가 132 B 다.
  키 이름을 `PGPASSWORD_SVC_ACCOUNT` 류로 지으면 그 자리에서 초과한다.
  → **별도 시크릿 `fb-secrets/pg-roles`** 를 만든다. 0-11 의 폭발 반경이 줄고,
  PG 비밀번호만 따로 회전할 수 있게 되며, 0-11 의 CI 가드(3,600 B)도 그대로 유효하다.
- ⚠️ 현재 `fbapp` 비밀번호는 **8바이트**다(값은 적지 않는다). 전환은 자연스러운 **회전 기회**다 —
  새 롤은 32자 랜덤으로 만든다.
- `fb-secrets/app-secrets` 는 **ArgoCD 도 Ansible 도 관리하지 않는다**(managedFields = `kubectl-*` 뿐).
  `pg-roles` 도 같은 성격이 되므로, 이 사실을 런북에 남긴다(재구축 시 소멸 위험 — #521 과 같은 함정).

---

## 2. `schema-production.md §0.3` 과 달라지는 점 (5건)

§0.3 은 2026-07-15 에 쓰인 **초안**이고, 그 사이 실물이 달라졌다. 아래는 전부 **의도적 이탈**이다.

| # | §0.3 | 이 설계 | 이유 |
|---|---|---|---|
| ① | `GRANT ... ON SCHEMA data` | **`public`** | `data` 스키마가 실물에 없다(§1.2). `schema-production.sql:4-5` 도 같은 말 |
| ② | 롤 8개 (`svc_account`…`svc_activity`) | **서비스 12 + 그룹 2 = 14개** — `svc_recipe` `svc_video` `svc_ocr` `svc_ranking` 추가, **`svc_activity` 삭제** | 읽기 전용 서비스 4종이 §0.3 에 없다. `activity` 는 자기 서비스가 없고 mealplan·pipeline·ranking 이 나눠 쓴다 |
| ③ | `GRANT USAGE, **CREATE** ON SCHEMA <svc>` | **USAGE 만** | 서비스 코드에 DDL 0건 실측. CREATE 는 그 스키마에 임의 객체를 만들 수 있게 해 최소권한을 넘는다 |
| ④ | 롤마다 `CREATE ROLE ... LOGIN PASSWORD :'x_pw'` | **SQL 은 NOLOGIN 으로만 만들고**, LOGIN·비밀번호는 CNPG `spec.managed.roles` 가 준다 | 비밀번호가 파일·git 을 안 거친다. bootstrap-from-scratch 에서도 선언형으로 복원된다(#546 의 "IaC 밖" 지적) |
| ⑤ | (없음) | `svc_mealplan` 에 `activity.recipe_impression` **INSERT** 명시 | 크로스-스키마 쓰기가 실재한다(§1.4). §0.3 에 없어서 그대로 적용하면 추천 노출 로깅이 조용히 죽는다 |

---

## 3. 롤 설계

### 3.1 그룹 롤 (NOLOGIN — 권한 묶음)

| 롤 | 권한 |
|---|---|
| `mp_data_reader` | `public` USAGE + 전 테이블/뷰/matview SELECT + 시퀀스 SELECT (+ 미래 객체 default privileges) |
| `mp_data_writer` | `mp_data_reader` + `public` 전 테이블 INSERT/UPDATE/DELETE + 시퀀스 USAGE |

읽기 대상을 롤 하나로 묶으면 **테이블이 늘 때 고칠 곳이 한 군데**다. 지금 `public` 24개가
서비스 7종에 걸려 있어 개별 GRANT 면 조합이 폭발한다.

### 3.2 서비스 롤 12개

| 롤 | 자기 스키마 | 그룹 | 추가 |
|---|---|---|---|
| `svc_account` | `account` CRUD | — | — |
| `svc_recipebook` | `recipebook` CRUD | `mp_data_reader` | — |
| `svc_pantry` | `pantry` CRUD | — *(주석 처리 — §1.4)* | — |
| `svc_mealplan` | `mealplan` CRUD | `mp_data_reader` | `activity.recipe_impression` INSERT |
| `svc_price` | `price` CRUD | `mp_data_reader` | — |
| `svc_notify` | `notify` CRUD | — | — |
| `svc_chat` | `chat` CRUD | `mp_data_reader` | — |
| `svc_recipe` | — | `mp_data_reader` | — |
| `svc_video` | — | `mp_data_reader` | — |
| `svc_ocr` | — | `mp_data_reader` | — |
| `svc_ranking` | — | `mp_data_reader` | `activity` 3테이블 SELECT |
| `svc_pipeline` | — | `mp_data_writer` | `activity` CRUD · `notify.notification` INSERT · `pantry.pantry_item` UPDATE · `chat.chat_message` DELETE · `account.app_user` **컬럼 2개만** SELECT · matview 소유권 |

**소유권은 전부 `fbapp` 에 남긴다** (예외 = `public.retail_unit_price` matview 하나).
소유권 이관은 되돌리기가 비싸고, 이 이슈가 막으려는 것(= 옆 서비스 데이터 열람)은 GRANT 만으로 막힌다.

### 3.3 이 설계가 실제로 막는 것

전환 후 `chat` 서비스에 SQL 인젝션이 뚫려도:

```
SELECT email, password_hash FROM account.app_user   →  permission denied for schema account
UPDATE pantry.pantry_item SET ...                    →  permission denied for schema pantry
INSERT INTO public.retail_price ...                  →  permission denied for table retail_price
SELECT * FROM public.item_master                     →  OK (설계상 허용 — 데이터 티어는 공유 읽기)
SELECT * FROM chat.chat_message                      →  OK (자기 데이터)
```

지금은 위 5개가 **전부 OK** 다.

---

## 4. 비밀 주입 — CNPG 선언형 + ESO

### 4.1 왜 CNPG `spec.managed.roles` 인가

#546 의 부수 지적 = *"롤 정의가 어느 레포에도 없다 · bootstrap from scratch 하면 소멸한다"*.
CNPG 1.30 의 `spec.managed.roles` 는 **롤 존재·속성·비밀번호를 Cluster CR 로 선언**하고
오퍼레이터가 계속 reconcile 한다. 즉 **config 레포(ArgoCD) 안으로 들어온다.**

역할 분담:

| 무엇 | 어디가 정본 |
|---|---|
| 롤 존재 · LOGIN · **비밀번호** · connectionLimit · 그룹 멤버십 | **CNPG `Cluster.spec.managed.roles`** (config 레포) |
| 스키마·테이블 GRANT | **`docs/prd/schema-roles.sql`** (앱 레포, 사람이 psql 로 적용) |

GRANT 까지 선언형으로 가는 길(`postInitApplicationSQL`)은 **bootstrap 시점 1회만** 유효해서
이미 존재하는 클러스터에는 안 먹는다. 그래서 GRANT 는 SQL 파일 + 런북으로 남긴다.

### 4.2 🔴 함정 — `inRoles` 는 배타적이다

CNPG 는 `inRoles` 에 **적히지 않은 멤버십을 REVOKE 한다**. `schema-roles.sql` 의
`GRANT mp_data_reader TO svc_chat` 같은 줄은 전부 멤버십이므로, CNPG spec 에 같이 적지 않으면
**다음 reconcile 에서 조용히 회수돼 읽기가 죽는다.** 대조표:

| 롤 | `inRoles` |
|---|---|
| `svc_account` `svc_pantry` `svc_notify` | `[]` |
| `svc_recipebook` `svc_mealplan` `svc_price` `svc_chat` `svc_recipe` `svc_video` `svc_ocr` `svc_ranking` | `[mp_data_reader]` |
| `svc_pipeline` | `[mp_data_writer]` |
| `pgsync` | `[]` — 🔴 아래 |

🔴 **`pgsync` 는 서비스 롤이 아니다 — CDC(PG→ES) 전용이고 2026-08-14 에 편입됐다.**
`schema-roles.sql` 이 이 롤을 **몰랐던** 탓에, 빈 클러스터에 그 파일을 돌려도 PGSync 가 붙지
못했다(EKS A1 실측: `password authentication failed for user "pgsync"`). 온프렘엔 **손으로 만든**
롤이 이미 있어 드러나지 않았을 뿐이고, 같은 구멍이 **온프렘 DR 재구축에도 있었다.**

| | |
|---|---|
| 이 파일(`schema-roles.sql`)이 주는 것 | 롤 생성(NOLOGIN) · `USAGE` on `public`·`recipebook` · `SELECT, TRIGGER` on `public.recipe` · `public.recipe_ingredient` · `recipebook.shared_recipe` |
| CNPG `managed.roles` 가 주는 것 | `login` · **`replication: true`** · 비밀번호 · `connectionLimit: -1` |

- 🔴 **`TRIGGER` 를 빼면 안 된다** — PGSync 가 대상 테이블에 자기 트리거를 만든다. `SELECT` 만
  주면 부팅은 되고 **동기화만 조용히 안 된다.**
- 🔴 **`replication: true` 도 마찬가지다** — 논리 복제 슬롯을 만들지 못해 같은 모양으로 실패한다.
- 🔴 **비밀번호 출처가 다르다** — `pg-roles` 번들이 아니라 **`data-secrets/PGSYNC_PG_PASSWORD`** 다.
  PGSync 워크로드가 `mp-pgsync-secrets/PG_PASSWORD` 로 같은 값을 받으므로 한 곳에서 나와야 한다.
  편의로 `pg-roles` 로 옮기면 **양쪽이 조용히 어긋난다.**

### 4.3 매니페스트 (config 레포 — 이 PR 범위 밖, 복사해서 쓸 것)

**① `fb-secrets/pg-roles` (수동 · 값은 git 안 감)**

```bash
# 32자 랜덤 12개 생성 → 한 번에 적재. 🔴 값은 터미널에 찍지 말 것.
#
# 🔴🔴 이 작업 중 실제로 겪은 함정 (2026-08-09) — Secret 을 `kubectl apply` 로 만들면
#   `kubectl.kubernetes.io/last-applied-configuration` 어노테이션에 **base64 값 전체가 그대로 박힌다.**
#   그래서 `kubectl get secret -o jsonpath='{.metadata.annotations}'` 나 `kubectl describe secret` 만으로도
#   **모든 값이 평문(base64)으로 쏟아진다.** "키 이름만 보려면 describe/go-template" 이라는 기존 수칙은
#   **describe 에 대해서는 틀렸다** — 안전한 건 `-o go-template` 로 키만 뽑는 것뿐이다.
#   → 이 secret 은 `--dry-run=client -o yaml | kubectl apply -f -` 대신
#     `kubectl create secret ... --save-config=false` 또는 `kubectl replace` 로 만든다(어노테이션 미기록).
kubectl -n fb-secrets create secret generic pg-roles \
  --from-literal=svc_account="$(openssl rand -base64 24)" \
  ... (12개) ... \
  --dry-run=client -o yaml | kubectl apply -f -
```

**② `data` ns ExternalSecret — CNPG 는 `kubernetes.io/basic-auth` 타입을 요구한다**

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata: { name: mp-pg-role-chat, namespace: data }
spec:
  refreshInterval: 1h
  secretStoreRef: { kind: ClusterSecretStore, name: fb-kubernetes }
  target:
    name: mp-pg-role-chat
    creationPolicy: Owner
    template:
      type: kubernetes.io/basic-auth        # 🔴 CNPG 요구 타입
      data:
        username: svc_chat
        password: "{{ .password }}"
  data:
    - secretKey: password
      remoteRef: { key: pg-roles, property: svc_chat }
```

**③ `Cluster.spec.managed`**

```yaml
spec:
  managed:
    roles:
      - name: svc_chat
        ensure: present
        login: true
        connectionLimit: 20
        inRoles: [mp_data_reader]
        passwordSecret: { name: mp-pg-role-chat }
      # … 서비스 롤 12개. 🔴 그룹 롤(mp_data_reader/writer)은 여기 적지 않는다 —
      #    NOLOGIN 이라 CNPG 가 관리할 이유가 없고, spec 에 넣으면 inRoles 반영 대상이 되어 복잡해진다.
```

**④ 앱 오버레이 — `PGUSER` 를 서비스별로 덮어쓴다**

`app-common` ConfigMap 은 9종이 공유하므로 거기선 못 바꾼다. Kubernetes 는
**`env` 가 `envFrom` 을 이긴다** → 각 서비스 Deployment/Rollout 에 한 줄 추가로 끝난다.

```yaml
# services/chat/overlays/onprem/pguser.yaml
spec:
  template:
    spec:
      containers:
        - name: chat
          env:
            - name: PGUSER
              value: svc_chat
```

**⑤ ExternalSecret 의 `PGPASSWORD` 출처 교체**

```yaml
    - secretKey: PGPASSWORD
      remoteRef: { key: pg-roles, property: svc_chat }   # 기존: { key: app-secrets, property: PGPASSWORD }
```

---

## 5. 적용 순서 — 🔴 이 순서를 지켜야 무중단이다

원칙: **권한을 먼저 만들고, 자격증명을 나중에 바꾼다.** 역순이면 앱이 못 붙는다.

### Phase 0 — 사전 (변경 없음)

1. **PG 백업 확인** — `kubectl -n data get scheduledbackup mp-pg-daily` 최근 성공 확인.
2. 현재 권한 스냅샷 저장(롤백 대조용):
   ```
   psql -U postgres -d foodbudget -c "\du" > /tmp/before-du.txt
   psql -U postgres -d foodbudget -c "\dn+" > /tmp/before-dn.txt
   ```
3. **Pooler 파라미터 dry-run** — §1.5 의 두 키를 CNPG 가 받는지 먼저 확인.

### Phase 1 — 롤 생성 + GRANT (**앱 동작 불변 · 무위험**)

4. `psql -U postgres -d foodbudget -v ON_ERROR_STOP=1 -f docs/prd/schema-roles.sql`
   → 롤 14개(서비스 12 + 그룹 2)가 **NOLOGIN** 으로 생기고 GRANT 가 붙는다. `fbapp` 은 그대로 → **앱은 아무 영향 없다.**
5. 검증: `schema-roles.sql` 하단 검증 쿼리 ①②③.
   특히 `has_table_privilege('svc_chat','account.app_user','SELECT')` = **f** 확인.

### Phase 2 — 비밀 + CNPG 선언 (**아직 앱은 fbapp**)

6. `fb-secrets/pg-roles` 적재(§4.3①).
7. `data` ns ExternalSecret 12개 적용 → `kubectl -n data get externalsecret` 전부 `SecretSynced`.
8. `Cluster.spec.managed.roles` 적용 → CNPG 가 LOGIN + 비밀번호를 건다.
   검증: `SELECT rolname, rolcanlogin, rolconnlimit FROM pg_roles WHERE rolname LIKE 'svc\_%';`
9. **접속 실증** (앱 건드리기 전에):
   ```
   PGPASSWORD=… psql -h pg-pooler.data.svc -U svc_chat -d foodbudget -c "select 1"
   PGPASSWORD=… psql -h pg-pooler.data.svc -U svc_chat -d foodbudget -c "select count(*) from account.app_user"
   #   ↑ 두 번째는 permission denied 가 나와야 성공이다
   ```

### Phase 3 — Pooler 사이징 (**앱 전환 직전 · 이 단계 자체는 무해**)

10. `default_pool_size=5` · `max_db_connections=25` 적용 → pgbouncer 파드 롤링.
    검증: `SHOW CONFIG` · `SHOW POOLS` · `pg_stat_activity` 카운트.

### Phase 4 — 서비스 1개씩 전환 (**여기가 유일한 위험 구간**)

🔴 **순서 = 위험 낮은 것부터.** 읽기 전용 → 자기 스키마만 → 크로스 쓰기 → 로그인 경로.

```
① video    (읽기만 · Pooler · 트래픽 최저)
② ocr      (읽기만 · 직결)
③ ranking-serving (읽기만 · 직결 · activity R)
④ recipe   (읽기만 · Pooler · Argo Rollouts 아님)
⑤ notify → ⑥ price → ⑦ pantry → ⑧ recipebook → ⑨ chat
⑩ mealplan (activity 크로스 쓰기 — 실패해도 추천은 살아있다: best-effort savepoint)
⑪ account  (🔴 마지막. 로그인이 죽으면 전 서비스가 죽는다 · Argo Rollouts)
```

각 서비스마다:

```
a. config 레포 PR — 오버레이에 PGUSER + ExternalSecret property 교체
b. ArgoCD sync (앱 13종은 automated — 머지로 나간다)
c. 🔴 rollout restart  ← envFrom/env 는 파드 기동 시점 주입이라 sync 만으로는 안 바뀐다
d. 검증: 로그에 permission denied 0건 · /health 200 · 실제 기능 1개 왕복
e. pg_stat_activity 로 그 서비스가 새 롤로 붙었는지 확인:
   SELECT usename, count(*) FROM pg_stat_activity WHERE datname='foodbudget' GROUP BY 1;
```

🔴 **`mp-account` `mp-recipe` 는 Argo Rollouts(카나리)다.** 카나리 단계에서 신·구 파드가
**동시에** 존재한다 → 그 순간 `svc_*` 와 `fbapp` 이 둘 다 살아 있어야 한다.
Phase 1 에서 GRANT 를 먼저 했고 `fbapp` 을 안 건드렸으므로 이 조건은 이미 충족이다.
**Phase 5 를 앞당기면 카나리가 죽는다.**

### Phase 5 — 파이프라인 + `fbapp` 회수 (별건 · 별도 승인)

11. `svc_pipeline` 전환 — `mp-pipeline-env` `PGUSER` + `mp-pipeline-secrets` `PGPASSWORD`.
    🔴 CronJob 17개는 **다음 스케줄에 뜨는 파드부터** 새 값을 쓴다. Deployment 5개는 restart 필요.
12. `ALTER MATERIALIZED VIEW public.retail_unit_price OWNER TO svc_pipeline;`
    → `mp-poller-price-matview` **1회 성공 확인 필수**(실패하면 가격 비교가 낡는다).
13. 1~2주 관찰 후 `ALTER ROLE fbapp NOLOGIN;`
14. (선택) `REVOKE CONNECT ON DATABASE foodbudget FROM PUBLIC` — §5 하드닝 블록. 🔴 GRANT 를 같은 트랜잭션에.

---

## 6. 롤백

| 단계 | 증상 | 되돌리기 | 소요 |
|---|---|---|---|
| Phase 1 | (없음 — 부가만) | `DROP ROLE svc_*` (GRANT 는 함께 사라진다) | 즉시 |
| Phase 2 | ESO 미동기 | `spec.managed.roles` 제거 → CNPG 가 손 뗀다(롤은 남음) | 즉시 |
| Phase 3 | 커넥션 대기·타임아웃 | `default_pool_size` 20 복귀 → pgbouncer 롤링 | ~1분 |
| **Phase 4** | **`permission denied` 로그 · 5xx** | **오버레이의 `PGUSER` 줄 삭제 → `rollout restart`** ← `app-common` 의 `fbapp` 으로 복귀 | **~2분** |
| Phase 5 | matview 갱신 실패 | `ALTER MATERIALIZED VIEW ... OWNER TO fbapp;` | 즉시 |
| Phase 5 | 전면 접속 불가 | `ALTER ROLE fbapp LOGIN;` (비밀번호는 남아 있다) | 즉시 |

🔴 **Phase 4 롤백의 전제 = `fbapp` 이 살아 있을 것.** 그래서 `fbapp` 회수는 **맨 마지막·별도 승인**이다.
🔴 **롤을 지우기 전에 GRANT 를 지우지 말 것** — `DROP ROLE` 은 그 롤이 소유한 객체가 있으면 실패한다.
현재 설계는 서비스 롤이 아무것도 소유하지 않으므로(matview 하나 제외) 안전하다.

---

## 7. 남은 결정 (임의로 정하지 않았다)

1. **`schema-production.md §0.3` 을 이 설계로 갱신할까?**
   §2 의 5건이 전부 이탈이다. §0.3 을 그대로 두면 "정본이 둘"이 되지만, SSOT 수정은 승인 사항이다.
   → 이 PR 은 §0.3 을 **건드리지 않았고**, `schema-production.sql:6` 의 *"이 파일엔 없음"* 줄에
   새 파일 포인터만 추가했다.
2. **`svc_pantry` 에 `mp_data_reader` 를 줄까?**
   §0.3 은 준다(소비기한 조인). 코드엔 0건이라 최소권한으로 **안 줬다**(주석으로 남김).
   소비기한 계산을 서비스로 옮길 계획이 있으면 지금 주는 게 낫다.
3. **`terraform` 슈퍼유저 롤을 어떻게 할까?** (별건)
   DROP 은 불가(§1.1). 선택지 = ⓐ 그대로 ⓑ `ALTER ROLE terraform NOLOGIN`
   ⓒ 비밀번호만 회전. 🔴 initdb 롤이라 **ⓑ 의 부작용 범위를 먼저 확인**해야 한다.
4. **`fbapp` 비밀번호(8바이트) 회전 시점** — 전환과 함께 할지, 별도로 할지.
5. **CNPG `spec.managed.roles` 를 `data` CR 트랙(수동 sync)에 넣는 것** — `pg` Application 은
   **manual sync** 다. 머지만으로 안 나가므로 런북 Phase 2 에 수동 sync 명령이 필요하다.

---

## 8. 범위 밖 (이 PR 이 손대지 않은 것)

- `pgsync` 롤 — 트리거·복제슬롯 생성 권한이 특수하다(#546 명시 범위 밖).
- CNPG 시스템 롤(`streaming_replica` · `cnpg_*`).
- ES PoLP → #521 / 0-15.
- `mp-operations` — 우리 PG 를 안 쓴다(§1.2).
- `operations` 스키마 DDL(`services/operations/schema.sql`) 미적용 상태 — 별건.
- 정적 AWS 키(`mp-pipeline-secrets`) 분리 → 0-14d.
