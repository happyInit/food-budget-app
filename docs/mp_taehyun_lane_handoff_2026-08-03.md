# 태현 레인 인계 문서 — 2026-08-03 (월)

> **이 문서만 읽고 착수할 수 있게 썼다.** 다른 대화 맥락·이전 세션 기억 없이 진입하는 에이전트/사람을 대상으로 한다.
>
> **출처와 시각 범위**
>
> - `docs/mp_today_worksplit_2026-08-03.md` = 원 작업분배(01:50 UTC 기준).
> - **2026-08-03 11:10~11:25 KST** = T-3 실행 전 읽기 전용 baseline 대조 4건. 이 시각대는
>   T-3 커밋·mutation·사후 라이브 검증의 근거가 아니다.
> - **2026-08-03 15:16:05~16:26:09 KST** = config 레포의 기존 T-3 관련 커밋 시각
>   (`git show --format=%aI`, §5.3). 사후 라이브 결과는 별도 실행 에이전트 완료 보고에서 왔으며,
>   최종 close용 재검증 시각·수치는 config ops SSOT merge 뒤 새로 기록한다(§5.4·§5.8).
>
> 🔴 **원 분배 문서는 여러 곳이 라이브와 어긋난다.** 이 문서가 그 위에 덮어쓰는 정정본이다. 충돌하면 **이 문서를 따른다.**
>
> ⛔ 원 분배 문서 `mp_today_worksplit_2026-08-03.md`는 당시 기록으로 보존하되 맨 위에
> **HISTORICAL / SUPERSEDED 실행 금지 배너**를 붙였다. 아래 정정은 그 역사 본문을 다시 쓰는 대신
> 이 인계 문서와 config 레포의 tracked runbook에 반영한다(§10).
>
> ✅ **2026-08-03 사후 갱신** — T-0·T-2 완료와 T-3 실행 에이전트의 중간 검증 보고를 반영했다.
> T-3 방향은 최초 계획의 물리 인덱스 직접 배선이 아니라 **앱 읽기와 PGSync 쓰기를 모두 안정 alias
> `recipes_live`로 고정**하는 방식이다. 다만 config ops SSOT가 아직 먼저 merge돼야 하므로 T-3 최종 완료와
> 최종 라이브 수치로 읽지 않는다. 현재 gate는 §5.3·§5.8·§13이 정본이다.

---

## 0. 30초 요약 — 결론만

| 원 계획 | 실측 후 판정 |
|---|---|
| T-2 PGSync 감시 = 🔴**오늘 최우선**, 1h30 | ✅ **완료·라이브 검증.** 기존 retained-WAL 알람을 1GiB/critical로 조이고 강제 발화 후 복구까지 확인. daemon 프로브/소비정지 직접 감시는 별도 부채 |
| T-1 ArgoCD 복구 = 🔴필수, 40분 | 🟢 **이 머신에서 실행 불가**(secrets 결손) + descheduler CronJob 은 **정상 가동 중**. → **봉수 이관** |
| T-3 ES nori = 🟠권장, 3h30 | ⏳ **중간 기능 검증 보고 있음·최종 close 대기.** `recipes_live → recipes_v2`, nori/API/CRUD CDC 결과는 config ops SSOT merge 뒤 재검증해야 한다. 구 slot·Secret·`_view` metadata와 재현성 gate는 §5.8 |
| T-0 alias 생성 = 2분 | ✅ **완료.** `recipes_live`는 현재 `recipes_v2`를 가리키는 앱 읽기+CDC 쓰기 alias |
| #9 ES rep 1 = 5분 | ✅ **완료·재생성 설정까지 고정.** `recipes` = green · pri 1 · rep 1 · docs 5,900 |
| #11 폴백 정합 = 30분 | ✅ **문구 교정 완료.** ES→PG degrade와 `recipes` DR 폴백을 분리하고 category 원천 NULL을 명시 |

**현재 순서**: config ops SSOT merge(`PENDING_AFTER_CONFIG_MERGE`, §5.3) → app 문서/복제 schema 반영 →
T-3 최종 라이브 close 검증(§5.8) → 여력 시 T-4. **T-1 은 태현이 하지 않는다.**

---

## 1. 환경 — 접속·도구 (전부 실측으로 검증된 커맨드)

### 1.1 kubectl

```bash
export PATH="$HOME/.local/bin:$PATH"     # kubectl 이 여기 있다
kubectl config current-context           # → mp-k8s
```

클러스터 = kubeadm 1.34.10 + Cilium 1.19.6, 5노드(`k8s-master`·`k8s-worker-a1`·`k8s-worker-a2`·`k8s-worker-b1`·`k8s-worker-b2`).
운영 정본 = `docs/mp_k8s_infra_status.md` (§4.0 접속 · §4.1 호스트 C · §2.x 데이터 티어).

### 1.2 Elasticsearch — 포트포워딩 불필요

ES CR = `data/es` (ECK **8.19.19**, green, **3노드**). Service `es-es-http:9200`. **인증 켬 · HTTP TLS 끔.**

```bash
PW=$(kubectl -n data get secret es-es-elastic-user -o jsonpath='{.data.elastic}' | base64 -d)   # 24자

# 파드 안에서 직접 curl — 가장 안정적
ES()  { kubectl -n data exec es-es-a-0 -c elasticsearch -- \
          curl -s -u "elastic:$PW" "http://localhost:9200$1"; }

ESG() { kubectl -n data exec es-es-a-0 -c elasticsearch -- \
          curl -s -u "elastic:$PW" -H 'Content-Type: application/json' \
          -X GET "http://localhost:9200$1" -d "$2"; }

# 쓰기용(재색인·alias 등)은 -X PUT/POST 로 바꿔 쓴다
ESW() { kubectl -n data exec es-es-a-0 -c elasticsearch -- \
          curl -s -u "elastic:$PW" -H 'Content-Type: application/json' \
          -X "$1" "http://localhost:9200$2" -d "$3"; }
```

### 1.3 PostgreSQL (CNPG)

primary = `data/pg-1`. PodMonitor `data/mp-pg` 가 `:9187` 에서 메트릭 수집.

```bash
kubectl -n data exec -it pg-1 -c postgres -- psql -U postgres -d foodbudget
```

볼륨 2개 — **WAL 이 별도 PVC 다**:
```
pg-1      (data)  19.5 GiB 중 19.24 여유
pg-1-wal  (WAL)    9.75 GiB 중  8.65 여유    ← WAL 고갈 논의는 이쪽
```

### 1.4 레포 2개 — 🔴 착수 전 필수 조치

| 레포 | 로컬 경로 | 담는 것 |
|---|---|---|
| `happyInit/food-budget-app` | `/home/team6/food-budget-app` | 앱 소스 · `Jenkinsfile` · `infra/`(Terraform·Ansible) · `pipelines/` · `docs/` |
| `happyInit/mealplanning-config` | `/home/team6/mealplanning-config` | K8s 매니페스트만(desired state). ArgoCD 가 watch |

🔴 **config 로컬 클론이 낡았다 — 이걸 안 하면 뒤가 전부 어긋난다:**

```bash
cd /home/team6/mealplanning-config
git status              # 현재: 브랜치 fix/mp-app-priorityclass (2bcfb64), main 은 origin/main 대비 14커밋 뒤
git checkout main && git pull
```

**실제로 사고를 냈다**: 검증 중 한 에이전트가 `ES_INDEX` 위치를 `services/recipe/base/deployment.yaml:126` 으로 보고했는데, `origin/main` 실측은 `rollout.yaml:101` 이고 **`deployment.yaml` 은 존재하지 않는다**(카나리 전환으로 삭제됨). 낡은 체크아웃을 읽어서 나온 오답이다. 사람도 똑같이 당한다.

앱 레포는 `origin/main` 대비 **1커밋 뒤**(#487 문서)이고 미커밋은 `infra/ansible/roles/team_ssh_keys/files/junghyun.pub` **하나뿐**이다 — 무해.

### 1.5 🔴 시각 표기 함정

- 원 분배 문서의 시각(`00:13`·`00:33`·`01:20`·`01:43`·`01:50`)은 전부 **UTC** 다. git 커밋은 KST(+0900).
  예) PR #488 = `402e872` = git 상 `2026-08-03 10:43:48 +0900` = 문서의 `01:43`.
- 🔴 **원 문서 제목 `2026-08-03 (일)` 은 오타 — 실제 월요일**이다(8/2 가 일요일). 재색인 크론이 `0,3`(일·수)이라 "오늘 돈다"로 오독할 수 있다. **다음 실행은 8/5(수) 06:30 KST.**
- 알려진 함정: 하이퍼바이저 `.12` 는 KST, 게스트 VM 은 UTC — 장애 타임라인이 9시간 어긋난다.

---

## 2. 태현 레인의 경계 — 뭘 건드리고 뭘 안 건드리나

```
┌─ 태현 소유 ────────────────────────────────────────────┐
│ config: platform/pgsync/**                             │
│ config: monitoring/rules-data-tier.yaml   (이 파일만)  │
│ app:    infra/ansible/**                               │
│ app:    pipelines/ingest/index_recipes_es.py           │
│ 클러스터: argocd · data ns · Elasticsearch             │
└────────────────────────────────────────────────────────┘
```

**건드리지 않는 것 (혼동 주의)**

| 대상 | 소유자 | 이유 |
|---|---|---|
| `services/recipe/**` (`rollout.yaml` 포함) | **카나리 세션(봉수, 별도 세션)** | 같은 사람이라도 세션이 둘이면 같은 파일에서 충돌. `ES_INDEX`·`priorityClassName` 두 줄 다 그쪽 몫 |
| `services/**` 나머지 · `frontend/**` | 봉수 계획 레인 | |
| `monitoring/kustomization.yaml` | 아무도 (config#107 로 선등록 완료) | 둘 다 고치면 충돌 |
| `monitoring/rules-app-symptom.yaml` | 봉수 | |
| GitHub 토큰(`github_runner_pat`·`DEPLOY_SSH_KEY`) | 봉수(오너 권한) | |

✅ **충돌 위험 실측 결과 = 0건.** 08-01 이후 태현 표면(`platform/pgsync/`·`monitoring/`·`infra/ansible/`·`pipelines/ingest/`)을 다른 사람이 건드린 것은 `2ed9a84`(#107, 선처리) 하나뿐이고, **미머지 브랜치 중 이 디렉토리를 건드리는 것도 0건**이다.

⚠️ **단, §6 원 문서의 "겹치는 것 0" 표는 공유자원 하나를 빠뜨렸다 — `app` ns ResourceQuota**(§8.3). 태현 작업엔 영향 없지만(`data` ns 에 쿼터 없음) 팀에 통보 대상이다.

---

## 3. T-0 — ES alias `recipes_live` 선생성 · ✅ 완료 (HISTORICAL)

> ⛔ **DO NOT RERUN. 이 절은 실행 전 기록일 뿐이다.** 현재 alias는 이미
> `recipes_live → recipes_v2`이며 앱 읽기와 CDC 쓰기가 모두 사용한다. 과거의 `add`를 다시 실행하면
> alias가 여러 backing index를 가리킬 수 있다. 아래 guard가 alias 존재를 확인하면 즉시 중단한다.

### 당시 이유

Recipe 배선을 alias로 먼저 바꾸기 위해 `recipes_live`를 선생성해야 했다. 당시 앱은 아직
`ES_INDEX=recipes_pgsync`를 직접 보고 있어 alias 생성 자체는 서빙 경로를 바꾸지 않았다.

### 당시 전제

| 항목 | T-0 직전 실측 | 현재 |
|---|---|---|
| `recipes_live` alias | 없음(404) | **존재: `recipes_v2` backing** |
| `recipes_v2` index | 없음 | **존재: 현행 nori generation** |
| ES health | green | green |

### 현재 guard — 읽기 전용

```bash
# curl은 HTTP 404에도 exit 0일 수 있으므로 body를 확인한다. 어느 갈래든 이 역사 문서에서는 중단한다.
ALIAS_JSON="$(ES /_alias/recipes_live)"
if printf '%s' "$ALIAS_JSON" | rg -q '"recipes_live"'; then
  echo 'ABORT: recipes_live already exists; historical T-0 must not be rerun' >&2
  exit 1
fi
echo 'ABORT: alias missing/unexpected; use the tracked stable-alias runbook' >&2
exit 1

# HISTORICAL ONLY — 실행 금지:
# ESW POST /_aliases '{"actions":[{"add":{"index":"recipes_pgsync","alias":"recipes_live"}}]}'
```

alias를 새로 만들거나 backing을 바꾸는 실행 절차는 이 역사 문서에서 조합하지 않는다. config 레포
`ops/pgsync-stable-alias/README.md`가 먼저 merge돼 `PENDING_AFTER_CONFIG_MERGE`가 실제 SHA로 바뀐 뒤에만
그 revision의 런북을 따른다. 그 전에는 실행하지 않는다.

---
## 4. T-2 — PGSync 감시 · ✅ 수정안 완료·발화 검증

> §4.3~§4.6의 `foodbudget_recipes_pgsync` 수치·checkpoint 경로는 T-3 이전 조사 증거다. 현행 slot은
> `foodbudget_recipes_live`이며, 구 slot은 T-3 close 대상으로만 남아 있다. 결론인
> retained-WAL 1GiB/critical 알람과 `active=f` 오탐 금지는 그대로 유효하다.

> **원 계획**: ① `platform/pgsync/pgsync.yaml` 에 프로브 추가 ② `monitoring/rules-data-tier.yaml` 에 슬롯 알람 2종(`슬롯 active == 0`, `슬롯 lag 증가 추세`) ③ 적용·확인. **1시간 30분, 오늘의 최우선.**
>
> 🔴 **①②가 둘 다 실측과 어긋난다.** 아래가 정정본이다.

### 4.1 원 위험 시나리오 — 방향은 맞다

```
PGSync 정지 → 슬롯이 WAL 을 잡은 채 진행 안 함
            → max_slot_wal_keep_size = -1 (무제한, 실측 확인 ✅)
            → PG 가 WAL 을 무한 보존
            → pg-1-wal PVC(8.65GiB 여유) 고갈 → PG 쓰기 전면 중단
```

이 사슬 자체는 **실재한다.** 오늘 항목 중 유일하게 OLTP 를 세울 수 있는 건이라는 판단도 맞다.

### 4.2 🔴 정정 ① — 시급성이 과장됐다 (시간 단위가 아니라 **일** 단위)

| 항목 | 실측값 |
|---|---|
| retained WAL 평시 | **16.0 MiB 고정** (6시간 내내 변동 없음) |
| 4일 min / max | 13.5 KB / 72 MB |
| WAL 생성률 평균(6h) | **7.3 MiB/h** |
| WAL 생성률 피크(4d 내 1h rate 최대) | **71.4 MiB/h** |
| **PGSync 정지 시 8.65GiB 소진까지** | 평시 **~50일** / 피크가 계속 유지돼도 **~5일** |

→ "오늘 안 하면 손해 누적"은 맞지만 **오늘의 최우선일 이유는 없다.** `for:` 를 넉넉히 잡아도 안전하다.

### 4.3 🔴 정정 ② — `슬롯 active == 0` 알람은 **넣으면 안 된다** (영구 오탐)

PGSync 는 지금 **정상 가동 중**이다:
```
pod  data/mp-pgsync-5d7dddf5b5-dc5cl   Running 1/1
재시작 3회 — 전부 4일 전 기동 시점 (이후 안정)
0.5초 주기 폴링, 슬롯 LSN 실제 전진: confirmed_flush 5/9C003EE8 → 5/9D0070F8 (5분간)
```

그런데 슬롯은 **줄곧 `active=f`** 다:
```
02:11:21 ~ 02:13:10   active=false   27회 연속 샘플 전부 false
4일치 시계열          91/91 시간별 샘플 = 0
```

**이유**: PGSync 는 walsender 상주 연결이 아니라 **SQL 함수 폴링**(`pg_logical_slot_get_changes`) 모델이다. 슬롯은 함수 호출 순간에만 잠깐 active 가 되고, 스크레이프가 그 순간을 거의 못 맞춘다(4d raw `max_over_time` 은 1 이 잡힌다).

> 🔴 **정상 상태가 `active=f` 다.** 이 규칙을 넣으면 즉시 영구 발화한다. 하필 `rules-data-tier.yaml` 헤더 주석이 경계한 *"오탐이 나면 방치되고 알람 신뢰가 깎인다"* 를 규칙 자신이 저지르는 꼴이 된다.

**→ `MpPGSyncSlotInactive` 는 폐기한다.**

### 4.4 🔴 정정 ③ — 문서가 쓴 메트릭 이름 **둘 다 존재하지 않는다**

원 문서: `pg_replication_slots_active` · `pg_replication_slot_lag_bytes` → **Prometheus 에 없다.**
CNPG 는 `cnpg_` 접두사판을 낸다. **실측 그대로**:

```
cnpg_pg_replication_slots_active{container="postgres", database="foodbudget",
  endpoint="metrics", instance="10.244.3.176:9187", job="data/mp-pg",
  namespace="data", pod="pg-1", slot_name="foodbudget_recipes_pgsync",
  slot_type="logical"}  0

cnpg_pg_replication_slots_pg_wal_lsn_diff{container="postgres", database="foodbudget",
  endpoint="metrics", instance="10.244.3.176:9187", job="data/mp-pg",
  namespace="data", pod="pg-1", slot_name="foodbudget_recipes_pgsync",
  slot_type="logical"}  16785776
```

- `..._pg_wal_lsn_diff` = `pg_current_wal_lsn() - restart_lsn`. 검산 일치(16,785,776 B ≈ 16 MiB).
- 🔴 **물리 슬롯 `_cnpg_pg_2` 도 같은 두 메트릭을 내는데 `database` 라벨이 없다** → `slot_name=` 또는 `slot_type="logical"` 로 **반드시 좁힐 것**.
- 노출은 **primary(`pg-1`)만**. 수집 = PodMonitor `data/mp-pg` (job `data/mp-pg`).

**→ 쓸 수 있는 지표는 사실상 `cnpg_pg_replication_slots_pg_wal_lsn_diff` 하나다.**

### 4.5 🔴 정정 ④ — 등가 알람이 **이미 로드돼 있다**

`PrometheusRule data/mp-pg` 안에 존재하고 Prometheus 에서 `health=ok / state=inactive` 로 정상 평가 중:

```yaml
- alert: MpPGReplicationSlotRetainedWALHigh
  expr: max by(slot_name) (cnpg_pg_replication_slots_pg_wal_lsn_diff{namespace="data"}) > 5 * 1024 * 1024 * 1024
  for: 15m
  labels:
    service: data-tier
    severity: warning
```

원 계획의 `MpPGSyncSlotLagHigh` 는 **이것과 같은 지표·같은 대상**이다. 새로 만들면 한 사건에 알람이 2개 뜬다.

**문제는 임계가 느슨하다는 것**: 5 GiB 는 WAL 볼륨 9.75 GiB 의 **51%**, 평시 16 MiB 의 **320배**. severity 도 `warning`(묻힌다).

### 4.6 🔴 정정 ⑤ — 프로브를 걸 표면이 **사실상 없다**

현재 프로브 = `livenessProbe`/`readinessProbe`/`startupProbe` **3종 전부 없음**(`describe` 에 해당 줄 자체가 없음).

PGSync 7.1.0 조사 결과:

| 후보 | 실측 |
|---|---|
| HTTP 헬스 엔드포인트 | ❌ 없음. 컨테이너 `/proc/net/tcp{,6}` 에 **LISTEN 소켓 0개**(전부 ESTABLISHED 아웃바운드) |
| `pgsync` CLI `status`/`health` 서브커맨드 | ❌ 없음 (`--help` 전량 확인 — 동기화 옵션뿐) |
| exec 프로브용 도구 | ❌ `psql`·`redis-cli`·`curl`·`wget` **전부 미설치**<br>✅ `python3` + `psycopg2`·`redis`·`elasticsearch` 라이브러리는 있음 |
| 체크포인트 파일 | `/app/checkpoint/.foodbudget_recipes_pgsync` (**점 접두사** — glob 에 안 걸림), 8바이트, 내용 `2630287`(txid/xmin) |

🔴 **체크포인트 mtime 은 생존 신호로 못 쓴다** — 실측 mtime `2026-08-01 20:10 UTC`, 즉 **CDC 가 건강한데도 30시간 정체**돼 있다. 실제 행 변경이 있을 때만 갱신되기 때문이다.

🔴 **`checkpoint` 볼륨이 `emptyDir` 다 → 재시작 = 전량 재동기화.** 프로브 `failureThreshold` 를 조이면 재동기화 루프에 빠진다. **원 문서의 경고가 정확하다.**

**판단**: 프로브로 잡을 고장과 알람으로 잡을 고장이 다르다. 프로세스가 멈추면 어차피 파드가 죽고 기존 `MpPGSyncDown`(`replicas_available < 1`)이 잡는다. **"파드는 살아있는데 CDC 만 정체"는 프로세스 내부 상태라 exec 프로브로 신뢰성 있게 판정할 수 없다.** retained-WAL 알람이 이 국면의 **유일하게 견고한 감지 수단**이다.

**→ 프로브는 빼는 것을 권한다.** 굳이 넣는다면 `python3 -c "..."` 로 직접 짜야 하고, `failureThreshold` 를 아주 넉넉하게(예: 10 이상 · `periodSeconds` 60) 잡아야 한다.

### 4.7 ⛔ HISTORICAL / DO NOT RERUN — 당시 정정 실행 계획

> 이 절은 T-2 실행 전 계획을 보존한 기록이다. T-2 알람 수정·발화·resolve 검증은 이미 끝났다.
> 아래 순서를 현재 작업 지시로 다시 실행하거나 현행 revision에 대입하지 않는다.

**핵심 = 신규 추가가 아니라 기존 알람 편집.**

```
① 기존 MpPGReplicationSlotRetainedWALHigh 의 임계를 조이고 severity 를 올린다
     5 GiB → 1 GiB   (평시 16 MiB 의 64배. 피크 71.4 MiB/h 로도 4일 이상 여유)
     severity: warning → critical
     for: 15m 유지 (또는 30m — 어차피 일 단위 여유)
② 프로브: 하지 않음 (§4.6). 하려면 python3 exec + 느슨한 threshold
③ 적용 → Prometheus 에서 규칙 로드 확인 → 임계를 뒤집어 실제 발화 확인(§9)
```

**파일 소유권 선택지 2가지**

| 안 | 방법 | 주의 |
|---|---|---|
| **A (권장)** | `platform/pg/` 의 `PrometheusRule data/mp-pg` 안에서 **그 자리 편집** | 태현 표면(`monitoring/rules-data-tier.yaml`)이 아니지만, 알람 공백이 없다 |
| B | `rules-data-tier.yaml` 로 **옮기고** `mp-pg` 에서 제거 | 🔴 `platform/pg` 와 `monitoring` **두 Application 을 동시에 sync** 해야 하고, 그 사이 **알람 공백**이 생긴다 |

A 를 택하면 `platform/pg` 를 건드리게 되므로, 봉수/카나리 세션과 겹치지 않는지만 확인하면 된다(실측상 08-01 이후 변경 0건).

### 4.8 ⛔ HISTORICAL / DO NOT RERUN — 당시 `monitoring` sync 메모

> 아래 `OutOfSync` 상태와 revision은 **11:10~11:25 KST baseline 당시 값**이다. 특히
> `revision:"HEAD"` sync는 지금 실행하면 T-2와 무관한 최신 변경까지 함께 배포할 수 있다. 현재 상태를
> 확인하지 않은 채 복사·실행하지 말고, 향후 변경은 리뷰된 정확한 config commit을 대상으로 별도 런북을 따른다.

```
ArgoCD Application `monitoring` : automated 없음(manual) · 현재 OutOfSync · revision d33dc3f
OutOfSync 대상 = PrometheusRule mp-app-symptom + PrometheusRule mp-data-tier  (딱 이 둘)
kubectl get prometheusrule -A  →  두 CR 모두 클러스터에 아직 없음
```

현재 `app` ns 에 로드된 규칙은 `mp-app-sli` · `mp-container-memory` · `mp-descheduler` · `mp-physical-layer` · `mp-tempo` · `mp-workload-spread` 6종뿐이다.

**당시 메모 — 실행 금지:**

```bash
# HISTORICAL ONLY / DO NOT RERUN
# kubectl patch application -n argocd monitoring --type merge \
#   -p '{"operation":{"sync":{"revision":"HEAD"}}}'
```

---

## 5. T-3 — 안정 write alias `recipes_live` · ⏳ config ops SSOT merge·최종 close 검증 대기

### 5.1 최종 구조

두 근인을 분리해 고쳤다.

1. **nori/매핑 부재** — 플러그인은 설치돼 있었지만 index settings/mapping을 만드는 tracked 경로가
   없었고, PGSync가 `recipes_pgsync`를 동적 매핑으로 먼저 생성했다.
2. **세대교체 충돌** — 물리 인덱스명을 PGSync logical index로 써 slot 이름까지 결합됐다.
   `recipes_v2`로 직접 바꾸면 새 slot/bootstrap 권한 충돌이 반복된다.

그래서 canonical mapping은 config 레포 `ops/pgsync-stable-alias/recipes-index.json`이 소유하고, 앱 읽기와 PGSync 쓰기는
모두 **변하지 않는 논리 이름 `recipes_live`**로 고정해 physical generation과 slot identity를 분리했다.

```
PG recipe / recipe_ingredient
        │
        │ PGSync CDC (slot: foodbudget_recipes_live)
        ▼
recipes_live  ──alias──▶  recipes_v2
        ▲                   ├─ nori korean analyzer
        │                   ├─ keyword/boolean 명시 매핑
mp-recipe ES_INDEX          └─ primary 1 + replica 1
```

정본 배선:

- config `platform/pgsync/schema-configmap.yaml`: `index: recipes_live`
- app `deploy/pgsync/schema.json`: `index: recipes_live`
- config `services/recipe/base/rollout.yaml`: `ES_INDEX=recipes_live`

물리 이름 `recipes_v2`는 alias 뒤에서만 보인다. 다음 세대도 앱/PGSync 설정과 slot 이름은 바꾸지 않는다.
호출자가 없던 앱 레포 `deploy/pgsync/recipes_pgsync.index.json`은 삭제했고 mapping 사본을 다시 만들지 않는다.

### 5.2 왜 우회가 아니라 근본해법인가

초기 restart는 `foodbudget_recipes_live` slot이 없어 CrashLoopBackOff가 됐다. 첫 bootstrap도
두 이유로 실패했다.

1. bootstrap Job label이 ES NetworkPolicy 허용 selector와 달라 ES 9200에 닿지 못했다.
2. runtime `pgsync` role은 `fbapp` 소유 table의 기존 trigger를 DROP할 owner 권한이 없었다.

최종안은 NetworkPolicy를 넓히거나 table owner를 바꾸지 않았다. CNPG
`DatabaseRole/mp-pgsync-bootstrap`을 **비슈퍼유저 일회성 migration identity**로 만들고, 활성 시
`fbapp`·`pgsync` membership을 상속하면서 `REPLICATION`을 갖게 했다. stock PGSync full bootstrap을
이 한 identity로 실행해 stable slot + `_view.indices` + trigger를 한 작업에서 생성했다.
즉 slot만 손으로 만들어 event-mode 일관성을 우회한 방식이 아니다.

bootstrap 후 table owner는 계속 `fbapp`이고, DB role은 `NOLOGIN`·`NOREPLICATION`·membership 없음·
**DB password NULL**로 park됐다. 이 사실은 별도 K8s basic-auth Secret의 부재를 뜻하지 않으며 Secret은
close 조건에서 따로 확인한다. 영구 NetworkPolicy 확대도 없다.

### 5.3 기존 config 변경과 선행 merge gate

아래 5건의 시각은 대화 추정이 아니라 config 레포 로컬 Git 객체의 author/committer ISO 시각을
`git show -s --format='%H%n%aI%n%cI%n%s'`로 확인한 값이다.

| PR / commit | commit 시각 (KST) | 역할 |
|---|---|---|
| #115 / `397cd2f` | 15:16:05 | `mp-pgsync-bootstrap` DatabaseRole 도입 |
| #117 / `7bb9df6` | 15:32:53 | Recipe 앱 읽기를 `recipes_live`로 전환 |
| #119 / `2f03036` | 15:42:43 | PGSync 쓰기를 `recipes_live`로 전환 |
| #120 / `fd670c4` | 15:49:41 | bootstrap SQLAlchemy pool에 맞춰 활성 시 connectionLimit 10 |
| #124 / `a9339c3` | 16:26:09 | bootstrap role park |
| `PENDING_AFTER_CONFIG_MERGE` | `PENDING_AFTER_CONFIG_MERGE` | `ops/pgsync-stable-alias/` lifecycle·검증 SSOT와 fail-safe hardening |

완료 요약이 말한 4건 외에 **#117도 T-3 필수 변경**이다. 그러나 위 기존 커밋만으로는 새
config ops SSOT의 merge를 증명하지 않는다. 아직 정해지지 않은 그 PR 번호·commit SHA는 추측해서
채우지 않고 **`PENDING_AFTER_CONFIG_MERGE`**로 둔다.

merge 순서는 다음 gate를 지킨다.

1. config 레포의 `ops/pgsync-stable-alias/` SSOT·validator·Job hardening을 먼저 리뷰·merge한다.
2. merge된 config commit SHA를 위 pending 행에 기록하고 config `main`에서 검증을 다시 통과시킨다.
3. 그 다음에만 이 app 레포의 문서와 `deploy/pgsync/schema.json` 복제 사본 변경을 merge한다.
4. 정확한 config revision으로 적용·검증한 뒤 §5.8과 §13의 T-3 완료 여부·최종 수치를 갱신한다.

### 5.4 실행 에이전트의 중간 라이브 검증 보고 — 최종 close 증거 아님

> **provenance**: 아래 표는 11:10~11:25 KST 읽기 전용 baseline에서 나온 값이 아니다. 기존 config
> 커밋과 bootstrap 실행 뒤 작업 에이전트가 전달한 완료 보고를 옮긴 것이다. 표에 park 결과가 있으므로
> #124(`16:26:09 KST`) 이후 상태를 보고한 것으로는 추론할 수 있지만, 캡처된 원문에는 정확한 라이브
> 조회 시각이 없다. 따라서 config ops SSOT merge 뒤 동일 검증을 새 timestamp와 함께 다시 기록하기 전까지
> 이 수치를 최종값이나 T-3 완료 판정에 사용하지 않는다(`PENDING_AFTER_CONFIG_MERGE`).

| 검증 | 결과 |
|---|---|
| ArgoCD | `pg`·`pgsync`·`mp-recipe` 모두 Synced/Healthy |
| 워크로드 | PGSync 1/1, Recipe 2/2, restart 0 |
| ES | 3노드 green; `recipes_live`가 `recipes_v2` 한 곳을 가리키고 alias 쓰기 성공 |
| DR 폴백 | `recipes`: green · pri 1 · rep 1 · docs 5,900 (#9 완료) |
| 정합 | PG 8,963행 = ES 8,963문서 |
| nori | `김치찌개 → ['김치찌개','김치','찌개']` |
| 실제 API | `김치찌개` 13건 · `김치` 275건 |
| CDC | 테스트 ID INSERT→UPDATE→DELETE가 ES에 실시간 반영; 최종 잔재 없음 |
| PG 권한 | table owner=`fbapp`; superuser/소유권 변경 없음; trigger enabled |
| park | `mp-pgsync-bootstrap`: NOLOGIN/NOREPLICATION, membership 없음, password NULL |

카테고리 exact 매핑은 `keyword`로 고쳤지만, 실제 서빙 대상 `source='10K'`의 category 원천값이
전부 NULL인 문제는 그대로다. `국&찌개 103건`은 T-3 검증기준이 아니며 크롤러/정제 파이프라인 별건이다.

### 5.5 정상 세대교체와 disaster bootstrap을 구분한다

**정상적인 다음 물리 인덱스 세대교체에는 bootstrap role을 다시 켜지 않는다.** stable slot, `_view`,
trigger와 양쪽 alias 배선을 그대로 둔다. 새 물리 인덱스 생성·명시 매핑·초기 동기화 뒤, alias swap 직전에
**final-sync/LSN barrier로 전환 중 변경분이 모두 들어갔음을 증명**해야 한다. 그 다음에만 alias를
원자적으로 옮긴다. 이 barrier가 없는 "reindex 후 바로 swap"은 누락 위험이 있어 실행 금지다.

bootstrap role 재활성화는 preflight가 stable slot/`_view`/trigger 재생성이 필요하다고 판정한
DR·artifact/schema-trigger 재구축에만 사용한다. 정상 generation swap에는 사용하지 않는다.
이때 CNPG CRD 제약 때문에 `passwordSecret`을 넣기 전에 `disablePassword: true`를 **제거하거나
false로 변경**해야 한다. 활성 상태는 아래를 한 묶음으로 만들고 full bootstrap 뒤 즉시 되돌린다.

```
login=true · replication=true · inherit=true · connectionLimit=10
inRoles=[fbapp, pgsync] · disablePassword=false · 임시 passwordSecret
→ stock full bootstrap 1회
→ count/ACL/trigger/CRUD 검증
→ NOLOGIN/NOREPLICATION/inRoles=[]/disablePassword=true 로 park
→ K8s 임시 Secret 삭제와 DB role password NULL을 각각 확인
```

### 5.6 rollback 설계 스케치 — ⛔ tracked runbook 전에는 실행 금지

전환 뒤 구 `recipes_pgsync` 인덱스는 CDC를 소비하지 않아 즉시 stale해진다. 따라서 alias만
`recipes_pgsync`로 돌리면 검색 결과가 전환 시점으로 되감긴다.

- **구 slot 보존 window 안의 설계**: 구 consumer manifest를 명시적으로 복구하고 retained WAL을
  catch-up한 뒤 LSN final barrier, PG/ES count, 최신 canary를 통과해야 alias 변경을 고려할 수 있다.
- **구 slot 폐기 뒤의 설계**: PG 원천에서 rollback용 물리 인덱스를 전량 재구축·검증한 뒤 alias를 옮긴다.

현재는 구 consumer manifest와 LSN barrier 실행기가 없으므로 위 항목은 **실행 절차가 아니다**.
config 레포 `ops/pgsync-stable-alias/README.md`·`ops.sh`에 exact-confirmation·final barrier·사후 검증이
구현되고 리뷰·merge된 SHA가 기록되기 전에는 현장에서 조합해 실행하지 않는다. 현재 merge provenance는
`PENDING_AFTER_CONFIG_MERGE`다. 구 인덱스/slot도 영구 보존하지 않고 RPO와 종료시각을 붙인다.

### 5.7 role·slot 현재 lifecycle

| 자원 | 현재 역할 | 종료 상태 |
|---|---|---|
| `foodbudget_recipes_live` slot | 현행 CDC | 유지·소비 진전 감시 |
| `mp-pgsync-bootstrap` role | disaster bootstrap 전용 | park 유지 |
| `recipes_live → recipes_v2` | 앱 읽기 + CDC 쓰기 | 현행 유지 |
| `foodbudget_recipes_pgsync` slot | 단기 rollback | window 종료 후 삭제 |
| `public._view`의 정확히 두 행(`recipe`, `recipe_ingredient`) 각각의 `indices` 배열 속 `recipes_pgsync` 값 | 구 consumer metadata | 두 행 자체와 `recipes_live`는 보존하고, 두 배열에서 legacy 값만 한 원자적 교체로 함께 제거 |
| `mp-pgsync-bootstrap-db` Secret | bootstrap 임시 자격증명 | 즉시 삭제 |
| `recipes_pgsync` index | bounded rollback용 구 세대 | 정책 만료 뒤 삭제/재생성 가능 |

### 5.8 🔴 T-3 close 조건

실행 에이전트의 중간 보고에서는 기능 목표를 얻었지만, 다음 항목과 post-merge 재검증 전에는
운영적으로 T-3를 닫거나 완료 체크하지 않는다.

- [ ] 구 `foodbudget_recipes_pgsync` slot의 rollback 종료시각 확정 후 삭제
- [ ] `public._view`가 정확히 `recipe`·`recipe_ingredient` 두 행인지 먼저 확인하고, **두 행 각각의
      `indices` 배열**에서 구 `recipes_pgsync` 값만 한 원자적 교체로 함께 제거
- [ ] 교체 뒤에도 두 행이 정확히 한 개씩 존재하고 두 배열이 각각 `recipes_live`만 갖는지 재검증
- [ ] orphan `data/mp-pgsync-bootstrap-db` Secret 삭제
- [ ] 위 cleanup 뒤 stable slot lag·WAL·CRUD CDC·count 재검증
- [ ] bootstrap/preflight/final-sync/park 절차의 tracked runbook 또는 GitOps Job을 config 레포에 선행 merge
- [x] config의 `schema.json`은 `recipes_live`로 맞춤(#119)
- [ ] app의 `deploy/pgsync/schema.json` 변경은 config ops SSOT merge 뒤 merge
- [x] 단순 alias rollback 문구를 stale/catch-up 조건이 있는 절차로 교정

라이브 삭제는 rollback 가능성에 영향을 주므로 config ops SSOT merge와 부모 검증 세션의 cleanup 확인
전에는 위 live cleanup 항목을 체크하지 않는다.

## 6. #9 — ES DR 폴백 replica · ✅ 완료

원 문서의 파일 경로는 틀렸지만 두 조치는 모두 이행됐다.

- 정본 코드: `pipelines/ingest/index_recipes_es.py`
- commit `47a3484` (#494): `number_of_replicas: 0 → 1`과 단일노드 전제 주석 교정
- 라이브 즉시 설정도 반영
- 최종 실측: `recipes` = **green · pri 1 · rep 1 · docs 5,900**

이 스크립트는 매 실행 index를 drop→recreate하므로 live `_settings`만 바꾸면 다음 CronJob에서
replica 0으로 회귀한다. 코드와 live를 함께 고쳐 재발 경로까지 닫았다.

다음 정기 `mp-poller-es-recipes` 완료 뒤에도 `rep 1 · green`인지 확인하면 재생성 내구성까지 증명된다.
이는 사후 관찰 항목이지 #9 미완료 사유는 아니다.

---
## 7. #11 — 폴백 정합 · ✅ 문구 교정 완료

원 문서: *"폴백 = 축소 모드, 카테고리 필터 무효"*.
코드상 **폴백이 두 종류**인데, 그 서술은 한쪽에만 맞다.

### (A) ES → PG degrade — 카테고리 필터 **정상 동작한다**
```
services/recipe/app/main.py:85-93      ES 예외 → search_pg 로 degrade
services/recipe/app/queries.py:50-52   if tag: where += " AND r.category = %(tag)s"
```
PG 폴백은 `tag`·`cooking_time`·`level` 을 **전부 SQL WHERE 로 정상 처리**한다. **"카테고리 필터 무효" 는 이 경로엔 거짓이다.**

### (B) `ES_INDEX` 를 DR 폴백 인덱스 `recipes` 로 돌리는 경우 — 여기가 진짜 #11
```
services/recipe/app/queries.py:94-95        filters.append({"term": {"category": tag}})   ← 맨 term
pipelines/ingest/index_recipes_es.py:47     "category": {"type":"keyword"}                ← term 자체는 동작
pipelines/ingest/index_recipes_es.py:83     where r.source = '10K'   (+ strict HAVING 게이트 :66-76)
services/recipe/app/config.py:26            es_index: str = "recipes"   ← 기본값이 폴백 인덱스
```
`recipes` 는 **만개레시피(10K)만** 색인하고 그 원천의 category가 전량 NULL이므로 카테고리 검색은
**0건**이다. current `recipes_live → recipes_v2`도 같은 PG 원천을 서빙하므로 이 데이터 부채를 공유한다.

### (C) T-3가 매핑을 고쳤지만 원천 데이터 문제는 남았다

구 `recipes_pgsync`의 동적 `text` 매핑은 T-3의 `recipes_v2` 명시 `keyword` 매핑으로 해소됐다.
하지만 `source='10K'`의 category 원천값이 NULL이라 앱 결과는 여전히 0건이다. 매핑 회귀와 데이터 결손을
같은 문제로 취급하지 말 것.

### ✅ 권고 문구 (막히면 문서 명시만 해도 됨)

> ~~"폴백 = 축소 모드, 카테고리 필터 무효"~~
> → **"`ES_INDEX` 를 DR 폴백 `recipes` 로 돌리면 색인 집합이 10K-strict 로 축소돼 카테고리 값이 달라진다(무손실 대체가 아니다). ES→PG degrade 경로는 카테고리 필터가 정상 동작한다."**

---

## 8. T-1 — ArgoCD sourceRepos 복구 · 🔴 **태현이 하지 않는다 · 봉수 이관**

> 원 계획: `defaults/main.yml` 에 descheduler URL 추가 → `--check --diff` → `ansible-playbook k8s.yml --tags argocd` → 확인. 40분, 🔴필수.

### 8.1 🔴 이관 사유 ① — 이 머신에서 실행이 **불가능**하다

`--tags argocd` 실행 순서:
```
k8s.yml:85                      { role: k8s_argocd, tags: [platform, argocd] }
                                (롤 내부에 태스크별 태그가 없어 롤 전체가 돈다)
tasks/main.yml:70-82            helm upgrade argo/argo-cd 10.2.1   ← 실행됨 (rev 24 → 25)
tasks/main.yml:116-128 (:119)   assert — 웹훅 변수 3개 요구        ← 🔴 여기서 중단
tasks/main.yml:184              platform AppProject apply           ← 도달 못 함
```

`group_vars/k8s_nodes.yml:80` 이 `argocd_webhook_enabled: true` 로 덮어쓰는데, assert 가 요구하는 3개 중 2개가 **로컬 `secrets.yml` 에 없다**:

| 변수 | 상태 |
|---|---|
| `argocd_webhook_tunnel_id` | ✅ `k8s_nodes.yml:81` |
| `argocd_webhook_github_secret` | 🔴 **없음** |
| `argocd_webhook_tunnel_credentials` | 🔴 **없음** |

로컬 `infra/ansible/secrets.yml` 보유 11키:
`harbor_admin_password` · `harbor_db_password` · `tfstate_db_password` · `github_runner_pat` · `app_db_password` · `pgsync_db_password` · `minio_root_password` · `grafana_admin_password` · `argocd_repo_ssh_key` · `streaming_replica_password` · `slack_webhook_url`

`secrets.yml.example` 대비 **결손 5개**: 위 웹훅 2개 + `sonarqube_db_password` · `cloudflared_tunnel_credentials` · `etcd_encryption_key`

> 🔴 **결과 = 최악의 조합.** helm upgrade 리스크만 지고 descheduler 는 안 고쳐진다.
> 01:19(UTC) 실행은 성공했으므로 그 실행자는 완전한 `secrets.yml` 을 가진 다른 머신 — 커밋 author `bongsu <kbs48631@gmail.com>`.

**부수**: `--check --diff` 도 안 돌 가능성이 높다(미실행 · 예측). 롤이 `ansible.builtin.command` 결과를 register 해 `.rc` 로 분기하는데(`tasks/main.yml:36-47`·`:56-68`·`:175-185`), command 모듈은 check 모드에서 스킵돼 `.rc` 가 없다 → `when: k8s_argocd_secret_check.rc != 0`(`:47`)에서 undefined attribute 로 터질 것으로 본다.

### 8.2 🔴 이관 사유 ② — 등급이 과장됐다. **기능은 안 깨졌다**

원 문서: *"descheduler 가 죽은 채로 계속 있음. topologySpread 위반이 교정 안 됨"* → **틀렸다.**

```
CronJob  kube-system/mp-descheduler   */30  Asia/Seoul   age 36h
최근 Job 2건  Complete  (42분 전 · 12분 전)
로그: "already balanced",  totalEvicted=0
```

**CronJob 은 멀쩡히 돌고 있다.** 깨진 건 ArgoCD 의 **관리**(selfHeal · prune · 버전 업데이트)지 **기능이 아니다.** → "필수 = 이미 깨져 있음" 등급은 🟢 로 내려도 된다.

### 8.3 🔴 원 문서의 "빠진 것 3개" 는 stale — 실제는 **1개**

| 항목 | 원 문서 | 라이브 실측 |
|---|---|---|
| descheduler URL | git 에도 없음 | 🔴 **git 에 있다** — `infra/ansible/roles/k8s_argocd/defaults/main.yml:52` (PR #488 = `402e872`) |
| `argoproj.github.io/argo-helm` | 라이브 미적용 | 🔴 **이미 적용됨** (라이브 sourceRepos 7번째) |
| `argo-rollouts` ns in destinations | 라이브 미적용 | 🔴 **이미 적용됨** (라이브 destinations 9번째) |

01:19 실행이 뒤 두 개를 이미 반영했다. **git ↔ 라이브 차이는 descheduler URL 딱 1줄**이고, *"한 번에 3개 동시 복구"* 는 실제로는 **1개 복구**다.

원 문서의 "빠진 것" 블록은 **01:19 실행 전 스냅샷**이다. 그 아래 01:50 갱신 노트가 rollouts 복구는 반영했지만 블록 본문은 안 고쳤다.

### 8.4 라이브 실측 전수 (인계용)

**Application**
```
descheduler  Unknown / Unknown
  message: "application repo https://kubernetes-sigs.github.io/descheduler/
            is not permitted in project 'platform'"
  lastTransition: 2026-08-03T00:33:21Z
rollouts     Synced / Healthy   revision 2.41.1   conditions 없음
  → argo-rollouts ns 에 컨트롤러 2 + 대시보드 1 파드 Running
```

**AppProject `platform`** (generation 7) — sourceRepos **8개**:
`grafana` · `cloudnative-pg` · `helm.elastic.co` · `strimzi` · `ot-container-kit` · `kedacore` · **`argoproj.github.io/argo-helm` ✅** · `git@github.com:happyInit/mealplanning-config.git`
❌ 없는 것 = `https://kubernetes-sigs.github.io/descheduler/` — **이것뿐**

destinations **9개**: `observability` · `kube-system` · `data` · `cnpg-system` · `elastic-system` · `strimzi-system` · `redis-operator-system` · `keda` · **`argo-rollouts` ✅**

**다른 AppProject**: `mealplanning`(config 레포 / `app`·`data`·`pipeline`) · `mealplanning-root`·`platform-root`(config 레포 / `argocd`) · `default`(`*`/`*`, 차트 생성 — 롤이 안 건드림)

**git desired state**
```
infra/ansible/roles/k8s_argocd/defaults/main.yml:34-55   argocd_platform_source_repos (9개)
                                             :44           argo-helm
                                             :52           descheduler
infra/ansible/roles/k8s_argocd/defaults/main.yml:56-59   argocd_platform_namespaces (3개)
infra/ansible/group_vars/k8s_nodes.yml:63-69             k8s_operator_namespaces (6개)
                                      :69                  argo-rollouts
infra/ansible/roles/k8s_argocd/templates/argocd-platform-project.yaml.j2:16-24  두 리스트 합쳐 렌더
```
→ sourceRepos: git **9** vs 라이브 **8** (1건 차이) · destinations: git **9** vs 라이브 **9** (완전 일치)

### 8.5 ✅ 좋은 소식 — 손 patch 흔적 **0건**

```
AppProject platform  managedFields 매니저 = 딱 1개
  kubectl-client-side-apply @ 2026-08-03T01:19:09Z
last-applied-configuration 어노테이션 내용 = 라이브 spec 과 완전 일치
마스터 /etc/kubernetes/fb/argocd-platform-project.yaml  mtime = Aug 3 01:19
```
**→ playbook 재실행으로 지워질 항목은 없다.** (과거 손 patch 는 01:19 실행이 이미 지웠고, 그게 이번 사고다.)
나머지 3개 프로젝트도 매니저 1개씩(`07-28T04:30`·`07-28T04:45`·`07-29T00:42`)으로 템플릿과 일치.

**`argocd-secret` 방어책도 코드·라이브 양쪽에 살아 있다** (2026-07-30 helm upgrade 사고 대비):
```
argocd-values-secret.yaml.j2:17-19    configs.secret.createSecret: false
라이브 argocd-secret                   helm.sh/resource-policy: keep  어노테이션 존재 ✅
                                       키 4종 온전: admin.password · admin.passwordMtime
                                                    · server.secretkey · webhook.github.secret
라이브 replicas                        values 와 일치(전 컴포넌트 1) — 드리프트 없음
```

**범위 확인**: `k8s_platform_apps` 는 `k8s.yml:87` `tags: [platform, platform_apps]` → **`--tags argocd` 에 미포함** ✅

### 8.6 봉수에게 넘길 때 전달할 것

```
1. 실제 changed 는 descheduler URL 한 줄뿐이다 (argo-helm·argo-rollouts ns 는 이미 반영됨)
2. 손 patch 흔적 0건 — 재실행이 남의 작업을 지울 위험은 지금 없다
3. --check --diff 는 command 모듈 .rc 문제로 터질 수 있다 (tasks/main.yml:47)
4. helm upgrade 는 rev 24 → 25. argocd-secret 방어책(createSecret:false + resource-policy:keep) 확인됨
5. 급하지 않다 — mp-descheduler CronJob 은 30분마다 정상 완료 중
```

---

## 9. 공통 함정 — 이 프로젝트에서 반복적으로 사람을 잡은 것들

| # | 함정 | 대응 |
|---|---|---|
| 1 | 🔴 **`envFrom.configMapRef` 는 파드 기동 시점에 주입된다** | ConfigMap 을 바꾸고 ArgoCD sync 해도 도는 파드는 **옛 값**을 쓴다 → `rollout restart` 별도 필요. 체크섬 어노테이션이 없어 자동으로 안 굴러간다 |
| 2 | 🔴 **ArgoCD auto-sync 가 앱마다 다르다** (automated 26 / **manual 15**) | manual 15 = `app-common`·`gateway`·`gateway-internal`·**`monitoring`**·`mp-cloudflared`·`pipelines`·`mp-policies{,-data,-pipeline}`·데이터 CR 6종(**`pg`**·`pooler`·`es`·`kafka`·`redis`·**`pgsync`**). **오늘 태현이 건드리는 것 대부분이 manual 이다** |
| 3 | 🔴 **"적용됨" ≠ "동작함"** | Complete/Healthy/Synced 를 성공 증거로 믿지 말 것. **실패 조건을 강제로 만들어 복구까지 실측**하고, 알람은 **임계를 뒤집어** 실제 발화를 본다 |
| 4 | 🔴 **팀원이 같은 영역을 동시에 작업한다** | 지우기 전 `git log --since/-S` 확인. "내가 삭제 vs 상대 수정" 은 **복원이 기본값**. 미머지 브랜치도 볼 것 |
| 5 | 🔴 **낡은 체크아웃** | §1.4. 브랜치·behind 확인 없이 파일을 읽으면 존재하지 않는 파일을 보고하게 된다 |
| 6 | **UTC/KST 9시간 축** | §1.5 |
| 7 | **`grep -E` 거짓음성** | 패턴 매칭으로 "없다"를 결론짓기 전에 다른 방법으로 교차 확인 |
| 8 | **`gh pr edit` 은 Projects(classic) GraphQL 에러로 미반영** | `gh api -X PATCH .../pulls/N --input` 로 우회 |
| 9 | **DNS `.local` search 하이재킹** | 파드 search 에 DHCP 유래 `local` + ndots:5 → 4-dot FQDN 이 공인 IP 로 감. 짧은 `.svc` 는 안전. 🔴 CoreDNS `local:53` 차단은 **클러스터 DNS 전면 장애**를 낸다 |

### 검증 원칙 (사용자 지시 · 2026-08-01)

> 4연속으로 "조용한 실패"가 있었다. **알람을 만들면 임계를 뒤집어 실제로 울리는지 본다. 롤아웃은 2회 반복한다. 실패 조건을 강제로 만들어 복구까지 실측한다.**

오늘 항목별 적용:
- **T-2 알람** → 임계를 일시적으로 `1KB` 등으로 낮춰 발화 확인 후 되돌린다
- **T-3 재색인** → 실행 에이전트가 신 인덱스 직접 쿼리 + 앱 API + CRUD CDC 중간 검증을 보고했다.
  config ops SSOT merge 뒤 새 timestamp로 같은 검증을 반복해야 최종 증거가 된다(§5.4·§5.8)
- **#9** → live rep 1·green과 create 설정 rep 1을 확인했다. 다음 정기 크론 뒤 재확인은 사후 내구성 증명

---

## 10. 원 분배 문서에서 발견한 정정 — 현행 문서로 이관 완료

`docs/mp_today_worksplit_2026-08-03.md`는 당시 판단과 명령을 재현하는 역사 기록이라 본문을
부분 교정하지 않는다. 대신 맨 위에 **HISTORICAL / SUPERSEDED — 실행 금지** 배너와 현행 정본 링크를
추가했다. 아래 정정은 이 인계 문서에 반영했고 config 레포
`ops/pgsync-stable-alias/README.md` 변경은 선행 merge 대기 중이다(`PENDING_AFTER_CONFIG_MERGE`).
config SHA가 기록되기 전에는 원문 표·명령과 미머지 런북 모두 실행 정본으로 쓰지 않는다.

| 위치 | 정정 |
|---|---|
| 제목 | `2026-08-03 (일)` → **(월)** |
| §1 필수표 `#2` | "이미 깨져 있음" → **CronJob 정상 가동 중. ArgoCD 관리만 깨짐** (🔴→🟢) |
| §4 T-1 | "3개 동시 복구" → **1개**. "git 에도 없음" → **git 에 있다**(#488). + secrets 결손으로 이 머신 실행 불가 → 봉수 이관 |
| §4 T-2 | 지표 이름 2개 교체 · `active==0` 규칙 폐기 · 등가 알람 기존재 · 프로브 표면 없음 · 1h30 → ~20분 |
| §4 T-3 | 물리 이름 직접 배선 → **앱·PGSync 모두 안정 alias `recipes_live`**. 검증기준은 형태소 리콜+CRUD CDC, 카테고리는 별건 분리 |
| §4 T-3 여력 #9 | `scripts/index_recipes_es.py` → **`pipelines/ingest/index_recipes_es.py`**. 현재 #494·live rep 1로 완료 |
| §4 T-3 여력 #11 | 문구 교체 (§7) |
| §5-② | "✅ 완료" → **git 상으로만 완료. 클러스터엔 아직 없음(manual sync 필요)** |
| §6 표 | **`app` ns ResourceQuota 를 공유자원으로 추가** (현재 여유 1,088Mi < 배치2 서지 1,344Mi) |
| 전반 | 시각 표기가 UTC 임을 명시 |

---

## 11. 태현 밖으로 넘겨야 할 것 3건

### ① T-1 → 봉수
완전한 `secrets.yml` 보유자만 실행 가능. 전달 사항 = §8.6.

### ② 카테고리 필터 → 별건 분리 (크롤러/파이프라인 이슈)
서빙 대상 `source='10K'` 7,280건의 PG `category` 가 **전량 NULL**. **ES 작업으로 안 풀린다.**
만개레시피 크롤러가 category 를 채우도록 고치는 것이 진짜 처방.

### ③ `app` ns 쿼터 → 봉수 · 카나리 세션에 통보
```
mp-app-quota   requests.cpu     4170m  / 6
               requests.memory  5056Mi / 6144Mi     →  여유 1,088Mi
배치2 서지 = 1,344Mi   →  🔴 지금 실행하면 쿼터에 막힐 수 있다
```
**원인은 산수로 정확히 떨어진다:**
- account 파드 1개 = `account 256Mi` + `istio-proxy 96Mi`(네이티브 사이드카) = **352Mi**
- account 카나리가 지금 **4파드**(정상 2 + 여분 2) = **+704Mi**
- `1,088 + 704 = 1,792Mi` ← **원 문서의 1,792Mi 는 카나리 여분 파드가 없던 정지 상태 실측치**

숫자 자체는 틀리지 않았지만 **전제(정지 상태)가 지금 성립하지 않는다.**

**카나리가 정상이 아니다** (통보 대상):
```
NAME         DESIRED CURRENT UP-TO-DATE AVAILABLE
mp-account   2       2       2          1          ← 파드는 4개
mp-recipe    2       2       2          2

Warning TrafficRoutingError rollout/mp-recipe  (20m)  failed to set weight via plugin
Warning TrafficRoutingError rollout/mp-account (2m)   backendRef was not found in httpRoute
```
→ 배치2 는 **카나리가 수렴한 뒤**에 하거나, 서지 도중 `FailedCreate` 를 각오해야 한다.
CPU 는 여유 1,830m 으로 문제없음.

---

## 12. 참고 — 부수 실측 (인계 시 알아두면 좋은 것)

### 12.1 PriorityClass — 태현 워크로드에 영향 없음 ✅
```
NAME                              VALUE       GLOBALDEFAULT
app-normal                        100000      <none>
data-critical                     1000000     <none>
pipeline-low                      1000        <none>
lvm-localpv-*-controller-critical 900000000   <none>
lvm-localpv-*-node-critical       900001000   <none>
system-cluster-critical           2000000000  <none>
system-node-critical              2000001000  <none>
```
**어떤 PC 에도 `globalDefault` 가 없다** → 명시 안 하면 priority 0.

`data` ns 는 이미 다 붙어 있다: `mp-pgsync`·`mp-pgsync-bootstrap`·`mp-redis-pgsync` → `app-normal` / `pg-*`·`es-*`·`kafka-*`·`mp-redis-*` → `data-critical`.
미부여 = `kafka-entity-operator`·`kafka-kafka-exporter` 2개뿐(오늘 범위 밖).

### 12.2 ns 별 ResourceQuota
```
app       mp-app-quota       cpu 4170m/6 · mem 5056Mi/6144Mi     ← §11-③
data      쿼터 없음 ✅                                            ← T-2·T-3 제약 없음
pipeline  mp-pipeline-quota  cpu 50m/3 · mem 128Mi/3Gi           ← 여유 압도적, 무관
```

### 12.3 config#107 선처리 실측
```
2ed9a84 chore(monitoring): 규칙 파일 소유권 분리 (#107)   bongsu  Aug 3 10:45 KST
  monitoring/rules-app-symptom.yaml   71줄   mp-app-symptom,  rules: []
  monitoring/rules-data-tier.yaml     96줄   mp-data-tier,    4그룹(mp-pgsync/mp-es/mp-kafka/mp-minio) 전부 rules: []
  monitoring/kustomization.yaml       두 파일 등재 ✅
```
⚠️ 원 문서는 "빈 파일 2개"라 했지만 **실제로는 주석 뼈대 + 알람 스켈레톤 + 판단근거**가 이미 들어 있었다.
그중 "ES yellow는 #9 적용 후" 전제는 #9 완료로 충족됐다.

### 12.4 카나리 세션 진행도 (참고용, 태현 소유 아님)

> 아래 코드 블록은 인계 작성 시점 스냅샷이다. 현재는 #117 뒤 `ES_INDEX=recipes_live`,
> `priorityClassName=app-normal`로 모두 반영·검증됐다.
```
services/recipe/base/  =  analysistemplate.yaml · externalsecret.yaml · hpa.yaml
                          kustomization.yaml · pdb.yaml · rollout.yaml
                          service-canary.yaml · service.yaml
                          (deployment.yaml 없음 — 카나리 전환으로 삭제)

rollout.yaml:101-102   - name: ES_INDEX / value: "recipes_pgsync"   (총 134줄)
priorityClassName      미존재 (카나리 세션 몫으로 남아 있음)

커밋: d33dc3f (#109 account 카나리 · ADR-0001 7단계)
      a44ef88 (#108 recipe 카나리 · 4·5단계)
      2ed9a84 (#107 규칙 파일 소유권 분리)
      58b5c68 (#106 Gateway API 플러그인 + httproutes RBAC · 2·3단계)
      883763b (#104 Argo Rollouts 컨트롤러 설치 · 1단계)
카나리 브랜치 3개(feat/mp-recipe-canary · feat/mp-account-canary
                 · feat/mp-rollouts-gatewayapi-plugin) 전부 머지 완료
```

### 12.5 라이브 잡음 (오탐 주의)
- 02:06(UTC) 스냅샷에서 Application ~30개가 `Unknown`(`ComparisonError: GenerateManifest ... DeadlineExceeded`) 이었으나 02:10 재조회에서 절반 이상 `Synced` 로 회복. repo-server 로그 정상(kustomize build 수십 ms). **일시적 refresh 폭주로 판단** — 지속적 Unknown 은 `descheduler` 뿐이다.
- `mp-account` = `OutOfSync / Progressing` — 카나리 세션 작업 중(§11-③).

---

## 13. 완료 체크리스트

```
[x] 기존 config PR #115/#117/#119/#120/#124 merge
[ ] config ops SSOT 선행 merge — PR/commit: PENDING_AFTER_CONFIG_MERGE
[ ] 위 config SHA 기록·검증 뒤 app 문서/schema 변경 merge

[x] T-0  alias recipes_live 생성
[x] T-2  MpPGReplicationSlotRetainedWALHigh 1GiB · severity critical
[x]      monitoring / platform-pg Application sync
[x]      임계를 뒤집어 실제 발화 → resolve 확인 후 원복
[ ] T-3  최종 close — 아래 항목을 config ops SSOT merge 뒤 새 timestamp로 재검증
[ ]      recipes_v2 nori + exact/boolean mapping · replica 1 (중간 보고 있음)
[ ]      recipes_live가 정확히 한 backing recipes_v2를 가리키고 explicit write index임을 확인
[ ]      앱 읽기 + PGSync 쓰기 모두 recipes_live 고정
[ ]      stable slot foodbudget_recipes_live + 정확히 4개 trigger + _view 정확히 2행 확인
[ ]      role NOLOGIN/NOREPLICATION/inRoles=[]/password NULL park 확인
[ ]      PG/ES count·nori/API 검색 수치를 최종 조회 시각과 함께 기록 (기존 8,963/13/275는 중간 보고)
[ ]      INSERT→UPDATE→DELETE CDC와 테스트 잔재 없음 재확인
[ ] T-3  구 foodbudget_recipes_pgsync slot bounded rollback 종료 후 삭제
[ ]      _view의 recipe·recipe_ingredient 두 행 각각에서 recipes_pgsync를 원자적으로 함께 제거
[ ]      _view 두 행이 각각 recipes_live-only인지 재검증
[ ]      orphan data/mp-pgsync-bootstrap-db Secret 삭제
[ ]      cleanup 뒤 stable slot lag/WAL/count/CRUD CDC 재검증
[ ]      bootstrap/preflight/final-sync/park tracked runbook/GitOps Job 선행 merge 확인
[x] #9   `recipes` live rep 1 + index_recipes_es.py create 설정 rep 1 (#494)
[x] #11  폴백/카테고리 문구 교정 — §7
[ ] T-4  (여력) rules-data-tier.yaml 에 ES→Kafka→MinIO 알람

넘길 것
[ ] T-1 → 봉수 (§8.6 전달사항 포함)
[ ] 카테고리 데이터 이슈 → 크롤러 별건 등록
[ ] app ns 쿼터 여유 부족 → 봉수·카나리 세션 통보
```

---

## 부록 — 이 문서의 근거

근거는 시각과 생성 주체에 따라 분리한다. 서로 다른 행을 한 번의 검증으로 합쳐 읽지 않는다.

| 근거 | 시각 (KST) | provenance / 사용 범위 |
|---|---|---|
| 실행 전 baseline | 2026-08-03 11:10~11:25 | 아래 읽기 전용 에이전트 4대의 병렬 대조. 변경 작업 0건. T-3 사후 상태의 근거로 사용 금지 |
| 기존 T-3 config 커밋 | 2026-08-03 15:16:05~16:26:09 | config 로컬 Git 객체의 author/committer ISO 시각. PR·SHA별 값은 §5.3 |
| T-3 중간 라이브 결과 | 정확한 조회 시각 미기록 | 실행 에이전트 완료 보고. §5.4 표에만 보존하며 최종 close 증거가 아님 |
| config ops SSOT merge·최종 라이브 검증 | `PENDING_AFTER_CONFIG_MERGE` | merge된 config PR/SHA와 새 조회 시각·수치를 이후 기록. 현재 추측 금지 |

11:10~11:25 KST baseline의 세부 범위:

| 에이전트 | 범위 |
|---|---|
| ArgoCD | Application·AppProject 전수 · ansible desired state · `--tags argocd` 경로 · managedFields |
| Elasticsearch | 인덱스·alias·매핑·nori·토크나이즈·리콜·디스크·CDC 배선 |
| PGSync/PG | 슬롯·WAL·메트릭 실명·기존 알람·프로브 표면·체크포인트 |
| 레포/전제 | config#107 · 카나리 진행도 · #9/#11 코드 근거 · PriorityClass · 쿼터 · 팀원 활동 |

**원 분배 문서** = `docs/mp_today_worksplit_2026-08-03.md`
**인프라 SSOT** = `docs/mp_k8s_infra_status.md`
**설계 정본** = `docs/design.md` (인프라 §8.4 는 superseded)
