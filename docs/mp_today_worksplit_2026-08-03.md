# 오늘 작업 분배 — 2026-08-03 (일) · **완전 병렬**

> **전제**: 오늘까지 처리하고 **내일부터 당분간 인프라 미터치**.
> **분배 원칙**: 항목을 **통째로** 한 사람에게 준다. 대신 **파일·디렉토리가 안 겹치게** 묶는다.
> → 서로 기다리지 않는다. 접점은 짧은 것 **3개**뿐이고 그중 하나는 이미 해소됐다(§5).
>
> 🔴 **2026-08-03 01:50 갱신** — ADR-0001 **카나리 작업이 별도 세션에서 진행 중**임이 확인돼
> 두 곳을 고쳤다:
>   ① `services/recipe/**` 를 계획 레인에서 빼고 **카나리 세션 단독 소유**로(§2).
>      recipe 가 `Deployment` → `Rollout` 으로 바뀌어 파일 자체가 달라졌고,
>      같은 사람이어도 **세션이 둘이면 같은 파일에서 충돌**한다.
>   ② 태현 T-3 의 config 의존을 **머리에서 꼬리로** 옮겼다(§4 T-3).
>      원안은 `ES_INDEX` PR 을 기다리느라 처음부터 막혔는데, 재색인·검증(전체의 ~80%)은
>      config 와 무관하다. 이제 실질 대기는 마지막 스왑 직전뿐이다.
>
> 그리고 **T-1 은 재실행이다** — 01:20 경 playbook 이 이미 한 번 돌았으나
> descheduler 줄(PR #488)이 01:43 머지라 그 실행에는 없었다.

---

## 1. 오늘 해야 하는 것 — "안 하면 깨진다" 기준 재도출

태현 정리 36건을 **"오늘 안 하면 무슨 일이 벌어지나"** 로 다시 걸렀다.
"중요한가"가 아니라 **"방치가 손해를 만드는가"** 가 기준이다.

### 🔴 필수 6건 — 방치 = 손해 누적

| # | 오늘 안 하면 | 성격 |
|---|---|---|
| **2** | descheduler·rollouts 가 **죽은 채로 계속 있음**. topologySpread 위반이 교정 안 됨 | **이미 깨져 있음** |
| **13** | 외부 PG 로 가는 트래픽이 **매 요청 평문 노출** | **진행형** |
| **§8** | revoke 안 된 PAT·배포키가 **계속 유효** | **진행형** |
| **4** | 슬롯 정지 시 WAL 무한 보존 → **PG 디스크 고갈 → 쓰기 중단** | **악화형** |
| **§7** | 사용자가 지출 입력할 때마다 **기록이 조용히 유실** | **진행형·복구 불가** |
| **24** | `user_event` 가 계속 37행. **발표 때도 실측 데이터 없음** | **시간이 값을 만듦** |

### 🟠 오늘 하면 좋음 2건 — 이미 깨졌지만 악화는 안 함

| # | 상태 |
|---|---|
| **8** | 한글 검색이 **이미 파손**. 방치해도 더 나빠지진 않음 |
| **1** | 압박 국면에서만 발현. **지금은 무증상** |

### 🟢 여력 되면 4건 — 오늘 안 해도 안 깨짐

`#9`(DR 폴백 사본) · `#3`(데이터 티어 알람) · `#21↓`(유저경로 알람) · `#11`(폴백 정합)

> **판단**: 필수 6 + 권장 2 = **8건이 오늘의 실질 목표**. 나머지 4건은 레인에 여유가 생기면 흡수한다.

---

## 2. 무충돌 설계 — 표면 소유권

```
┌─ 봉수 레인 ────────────────────────┐  ┌─ 태현 레인 ───────────────────────┐
│ config: services/**                │  │ config: platform/pgsync/**        │
│         (recipe 제외 → 13개 서비스)│  │ config: monitoring/rules-data-*.yaml│
│ config: monitoring/rules-app-*.yaml│  │ app:    infra/ansible/**           │
│ app:    frontend/**                │  │ app:    scripts/index_recipes_es.py│
│ GitHub: 오너 권한(토큰·시크릿)     │  │ 클러스터: argocd · data ns · ES     │
│ 클러스터: app ns 워크로드           │  │                                    │
└────────────────────────────────────┘  └───────────────────────────────────┘

        ┌─ 🔴 카나리 세션 (봉수, 별도 세션) ─────────────────────┐
        │ config: services/recipe/**   ← rollout.yaml 실시간 편집 │
        │ ADR-0001 배포전략. 오늘 목록과 **별개 트랙**            │
        └────────────────────────────────────────────────────────┘

        겹치는 파일 0개 · 겹치는 ns 0개
```

### 🔴 `services/recipe/**` 를 왜 빼는가 (2026-08-03 조정)

같은 사람(봉수)이라도 **세션이 둘이면 충돌한다.** 카나리 세션이 `rollout.yaml` 을 열어
편집하는 사이, 이 계획 레인이 같은 파일에 `priorityClassName`·`ES_INDEX` 를 넣으면
한쪽이 낡은 버전 위에서 작업하게 되어 **머지 충돌 또는 작업 유실**이 난다.

또 recipe 는 `Deployment` → `Rollout` 으로 전환돼 **파일 자체가 바뀌었다**:

```
services/recipe/base/
  ❌ deployment.yaml                    ← 없어짐
  ✅ rollout.yaml                       ← ES_INDEX 가 여기 :101
  + analysistemplate.yaml · service-canary.yaml · pdb.yaml · hpa.yaml
```

→ **recipe 몫 두 줄**(`priorityClassName` · `ES_INDEX`)은 **카나리 세션이 함께 처리**한다.
   그 세션이 어차피 이 파일을 열고 있으므로 추가 비용이 사실상 없다.

### 🔴 사전 정리 — Claude 가 지금 한 PR 로 처리 (충돌 원천 제거)

`monitoring/rules.yaml` 이 **단일 파일**이라 둘이 같이 쓰면 충돌한다. 미리 가른다:

| 조치 | 내용 |
|---|---|
| 빈 파일 2개 생성 | `monitoring/rules-app-symptom.yaml` (봉수) · `monitoring/rules-data-tier.yaml` (태현) |
| `monitoring/kustomization.yaml` | **두 파일 모두 미리 등록** ← 이걸 미리 안 하면 둘 다 이 파일을 고쳐서 충돌 |

이 PR 하나만 먼저 머지되면, 이후 둘은 **자기 파일만** 건드린다.

---

## 3. 봉수 레인 — 3시간

> **표면**: `services/**` · `frontend/**` · GitHub 오너 · app ns
> **성격**: 전부 되돌리기 쉬움. PPT 와 번갈아 해도 안전.

### B-1. GitHub 토큰 정리 · 5분 · [필수 §8]

**왜**: 러너 롤·`cd_deploy_key` 롤은 삭제됐지만 **토큰 자체는 GitHub 에 살아 있다.** 파일 삭제 ≠ 무효화.

```
① github.com → Settings → Developer settings → Personal access tokens
   → `github_runner_pat` 찾아 Revoke
② 레포 happyInit/food-budget-app → Settings → Secrets and variables → Actions
   → DEPLOY_SSH_KEY 삭제
```

🔴 **`argocd_repo_ssh_key` 는 건드리지 말 것** — 이름이 비슷하지만 **완전히 별개**이고, 지우면 CD 가 죽는다.

---

### B-2. 프론트 지출 유실 · 40분 · [필수 §7]

**왜**: `queries.ts:430-439` 의 `catch {}` 가 예외를 통째로 삼킨다. 지출 저장이 실패해도 **UI 는 성공처럼 보이고 기록만 사라진다.** 복구 불가.

```
① frontend 레포에서 queries.ts:430-439 확인
② catch {} 제거 → 에러를 호출부로 전파
③ 호출부에서 사용자에게 실패를 알리는 처리 확인(토스트 등)
④ npm run build 로 타입 검증  ← PR 전 프론트 빌드 CI 가 없으므로 로컬 필수
```

---

### B-3. services 일괄 PR · 60분 · [필수 #13·#24 + 권장 #1] — **recipe 제외**

**한 PR 로 묶는 이유**: `services/` 아래 파일을 여러 번 나눠 열면 서로 리베이스가 필요하다. 한 번에 간다.

| 대상 | 파일 | 변경 |
|---|---|---|
| **#13** | `services/operations/base/deployment.yaml` | `PGSSLMODE=require` env 추가 |
| **#24** | `services/mealplan/base/configmap.yaml` | `EVENT_PRODUCE_ENABLED: "true"` |
| **#1** | `services/*/base/deployment.yaml` × 11 | `priorityClassName: app-normal` |

**#13 상세** — 지금 `sslmode` 가 없어 psycopg 기본값 `prefer` 로 동작한다. 서버가 TLS 를 거부하면 **평문으로 조용히 fallback** 한다. `require` 면 거부 시 연결이 실패한다(= 평문으로 안 감).

**#1 대상** — 배치1(#103)에서 6파드만 처리됐다. 남은 것:
`price` `pantry` `notify` `operations` `recipebook` `video` `frontend(2)` `cloudflared` `gateway(2)` + `mp-ocr-config-canary` CronJob
쿼터 여유 1,792Mi > 배치2 서지 1,344Mi → **수용 가능**(태현 실측).

> 🔴 **`recipe(2)` 는 이 목록에서 뺐다** (§2 조정). `rollout.yaml` 이 카나리 세션 소유라
> 여기서 건드리면 충돌한다. **카나리 세션이 `priorityClassName` 을 함께 넣는다.**

> 🔴 **`ES_INDEX` → alias 변경도 이 PR 에서 뺐다.** 같은 `rollout.yaml` 이다.
> 카나리 세션이 처리하며, 태현은 그것을 **기다리지 않는다**(§4 T-3 순서 재배열).

---

### B-4. 적용·검증 · 25분

```bash
# #24 는 restart 필수 — envFrom 은 파드 기동 시점에만 주입된다
kubectl rollout restart deploy/mp-mealplan -n app
kubectl rollout status  deploy/mp-mealplan -n app

# #13 확인
kubectl -n app exec deploy/mp-operations -- env | grep PGSSLMODE

# #1 확인 — priorityClassName 이 빈 워크로드가 없어야 한다
kubectl get pods -n app -o custom-columns=NAME:.metadata.name,PC:.spec.priorityClassName

# ⚠️ recipe 는 이 레인 대상이 아니다(§2). Deployment 도 이미 없다(Rollout 전환).
#    확인이 필요하면:  kubectl get rollout -n app mp-recipe
```

---

### B-5. 여력 되면 — 유저경로 알람 3종 · 40분 · [#21↓]

**파일**: `monitoring/rules-app-symptom.yaml` (Claude 가 미리 만들어 둠 — 등록도 끝)

| 알람 | 잡으려는 것 |
|---|---|
| 검색 0건률 급증 | **#8 같은 장애** — 컴포넌트는 정상인데 결과가 안 나옴 |
| 로그인 실패율 | account 계열 이상 |
| 식단생성 실패율 | 핵심 여정 파손 |

🔴 **임계값은 둔감하게, `for:` 는 15~30분.** 내일부터 아무도 안 보므로 **오탐이 나면 그대로 방치**되고, 다음에 볼 때 알람 신뢰가 깎인다. 놓치는 것보다 **안 울리는 게 낫다**(놓쳐도 지금과 같을 뿐).

---

## 4. 태현 레인 — 6시간

> **표면**: `platform/pgsync/**` · `infra/ansible/**` · `scripts/` · argocd·data ns · ES
> **성격**: 라이브 조작 위주. 연속된 주의 필요.

### T-0. ES alias 선생성 · 2분 · [카나리 세션 해제]

**가장 먼저.** 이게 있어야 카나리 세션이 `rollout.yaml` 의 `ES_INDEX` 를 바꿀 수 있다.

```bash
curl -u elastic:$PW -XPOST localhost:9200/_aliases -H 'Content-Type: application/json' -d '
{"actions":[{"add":{"index":"recipes_pgsync","alias":"recipes_live"}}]}'
```

→ 끝나면 **카나리 세션에** "alias 생성됨" 한마디. 이후 서로 안 기다린다.

⚠️ alias 를 만들어도 앱은 아직 `recipes_pgsync` 를 직접 본다 — **아무것도 안 바뀐다.**
   그래서 이 단계는 언제 해도 안전하고, 순서에 아무도 안 묶인다.

---

### T-1. ArgoCD sourceRepos 복구 · 40분 · [필수 #2]

> 🔴 **2026-08-03 01:50 갱신 — playbook 을 한 번 더 돌려야 한다.**
> 01:20 경에 이미 한 번 돌았는데, **PR #488(descheduler 줄) 머지가 01:43** 이라
> 그 실행에는 descheduler 가 없었다. 결과:
>
> ```
> rollouts     Synced / Healthy    ✅ 복구됨 (argo-helm·argo-rollouts ns 는 git 에 이미 있었음)
> descheduler  Unknown / Unknown   ❌ 그대로
> ```
>
> → 아래 절차를 **재실행**하면 descheduler 도 복구된다. 나머지는 이미 반영돼 `changed` 가 적을 것이다.

**왜**: `descheduler`·`rollouts` Application 이 **죽어 있었다**(`InvalidSpecError`, 08-03 00:13·00:33~).

```
라이브 sourceRepos: grafana · cnpg · elastic · strimzi · ot-container-kit · keda · config레포
빠진 것:  ❌ kubernetes-sigs.github.io/descheduler   (git 에도 없음 — 과거 손 patch 가 지워짐)
          ❌ argoproj.github.io/argo-helm            (git 엔 있음 · 미적용)
          ❌ argo-rollouts ns in destinations        (git 엔 있음 · 미적용)
```

```bash
# ① defaults 에 1줄 추가 (Claude PR)
#    infra/ansible/roles/k8s_argocd/defaults/main.yml
#      - https://kubernetes-sigs.github.io/descheduler/

# ② 🔴 반드시 --check 먼저. 다른 손 patch 가 있으면 같이 지워진다 (이번 사고가 정확히 그것)
ansible-playbook k8s.yml --tags argocd --check --diff

# ③ 이상 없으면 실행
ansible-playbook k8s.yml --tags argocd

# ④ 확인 — 둘 다 Healthy 여야 한다
kubectl get application -n argocd | grep -E 'descheduler|rollouts'
```

**한 번에 3개가 동시 복구**된다(descheduler URL + argo-helm + argo-rollouts ns).

---

### T-2. PGSync 감시 · 1시간 30분 · [필수 #4 — 오늘의 최우선]

**왜 최우선인가** — 나머지 전부가 "사고 나면 아픔"인데 **이것만 혼자 OLTP 를 세운다**:

```
PGSync 정지 → 슬롯 active=f  ·  max_slot_wal_keep_size=-1 (무제한)
            → PG 가 WAL 을 무한 보존 (여유 8.7G)
            → 디스크 고갈 → PG 쓰기 전면 중단
```

그리고 지금 **알람이 이걸 못 잡는다**. `MpPGSyncDown` 이 `replicas_available<1` 기준이라
**"파드는 떠 있고 CDC 만 멈춘"** 상태가 정상으로 보인다.

```
① platform/pgsync/pgsync.yaml 에 프로브 추가
   🔴 failureThreshold 를 넉넉히 — 프로브가 CDC 를 재시작 루프에 빠뜨리는 게 최악이다
② monitoring/rules-data-tier.yaml 에 슬롯 알람
   기준을 replica 수가 아니라 슬롯 자체로:
     - pg_replication_slots_active == 0        (슬롯이 죽음)
     - pg_replication_slot_lag_bytes 증가 추세  (WAL 이 쌓임)
③ 적용 → 파드 정상 기동 확인 → 알람 규칙 로드 확인
```

---

### T-3. ES 인덱스 · 3시간 30분 · [권장 #8 + 여력 #9 #11]

**🔴 착수 마지노선 — 남은 시간이 3시간 미만이면 시작하지 않는다.**
재색인을 중간에 멈춘 상태(alias 는 구 인덱스인데 신규가 반쯤 참)가 **안 한 것보다 나쁘다.**
그 경우 `#9`(5분)만 하고 #8 은 통째로 이월.

**현재 상태**

```
index          health pri rep docs   비고
recipes        green    1   0  5900  nori 있음 · DR 폴백
recipes_pgsync green    1   1  8963  nori 없음 · 실서빙  ← 이걸 고친다
```

**절차 — 🔴 config 의존을 맨 뒤로 몰았다 (2026-08-03 조정)**

원안은 *"봉수 `ES_INDEX` PR 이 선행"* 이라 **머리에서 막혔다**. 그런데 3시간 중 대부분은
config 변경 없이 된다. 의존을 꼬리로 옮기면 **아무도 안 기다린다.**

```bash
# ══════ 여기부터 ③까지 config 무관 — 즉시 착수 가능 (~2.5h) ══════

# ① 새 인덱스 — nori 매핑 포함
PUT recipes_v2   { analysis: nori_tokenizer ... }

# ② 재색인 (8,963건)
POST _reindex  { source: recipes_pgsync, dest: recipes_v2 }

# ③ 🔴 검증 먼저. 스왑 전에 신규 인덱스로 **직접** 쿼리해서 확인
#    - 한글 형태소 검색 3~5건
#    - category=국&찌개 term 쿼리가 103건 나오는지 (지금은 0건)
#    ※ 앱을 거치지 않고 ES 에 직접 쏘므로 ES_INDEX 와 무관하다

# ══════ 여기서만 카나리 세션의 ES_INDEX 반영이 필요 ══════

# ④ alias 스왑 — 원자적으로
POST _aliases {"actions":[
  {"remove":{"index":"recipes_pgsync","alias":"recipes_live"}},
  {"add":   {"index":"recipes_v2",     "alias":"recipes_live"}}]}

# ⑤ 앱에서 실제 검색 3~5건 육안 확인까지 하고 손 뗀다

# 🔴 롤백 = 1커맨드. 구 인덱스를 절대 지우지 않는다.
POST _aliases {"actions":[
  {"remove":{"index":"recipes_v2",     "alias":"recipes_live"}},
  {"add":   {"index":"recipes_pgsync","alias":"recipes_live"}}]}
```

**④가 카나리 세션보다 먼저 준비되면** — alias 만 스왑해두고 `ES_INDEX` 반영을 기다린다.
앱은 그때까지 `recipes_pgsync` 를 직접 보므로 **구 인덱스로 계속 서빙된다**(안전).
`ES_INDEX` 가 `recipes_live` 로 바뀌는 순간 신 인덱스로 넘어간다.

⚠️ **PGSync 가 계속 `recipes_pgsync` 에 쓴다.** 스왑 후 신규 인덱스로 CDC 가 흐르도록 PGSync 대상도
바꿔야 한다 — 안 하면 새 레시피가 검색에 안 나온다. 이 배선까지가 #8 이다.

**여력 항목**
- **#9** (5분): `PUT /recipes/_settings {"number_of_replicas":1}` + `scripts/index_recipes_es.py:29` 주석·값 수정
- **#11** (30분): 폴백 카테고리 정합. 막히면 **문서 명시만** — *"폴백 = 축소 모드, 카테고리 필터 무효"*

---

### T-4. 여력 되면 — 데이터 티어 알람 · 60분 · [#3]

**파일**: `monitoring/rules-data-tier.yaml` (T-2 에서 이미 만든 파일에 추가)

우선순위 **ES → Kafka → MinIO**. ES 가 #9 와 직결이라 먼저.

| 알람 | 대상 |
|---|---|
| `MpESClusterYellow/Red` | 사본 상실·샤드 미할당 |
| `MpESDiskHigh` | 디스크 포화 |
| `MpKafkaBrokerDown` · `MpKafkaISRShrink` | 브로커 상실 |
| `MpMinIODiskHigh` | 오브젝트 스토어 포화 |

---

## 5. 접점 — 3개, 전부 짧다

병렬을 깨는 건 이것뿐이다. **나머지는 서로 완전히 모른 채 진행해도 된다.**

| # | 내용 | 방향 | 타이밍 | 상태 |
|---|---|---|---|---|
| **①** | ES alias `recipes_live` 생성 | 태현 → **카나리 세션** | 태현 T-0 (2분) | 대기 |
| **②** | `monitoring/kustomization.yaml` 에 규칙 파일 2개 선등록 | Claude → 둘 다 | 선처리 | ✅ **완료** (config#107) |
| **③** | `rollout.yaml` 의 `ES_INDEX` → `recipes_live` | 카나리 세션 → 태현 | **태현 T-3 ④ 직전** | 대기 |

**②를 미리 안 했다면** 봉수(`rules-app-symptom.yaml`)와 태현(`rules-data-tier.yaml`)이
둘 다 `kustomization.yaml` 을 고쳐 충돌했을 것이다. → config#107 로 선처리 완료.

**③이 왜 꼬리에 있나** — 원안은 이걸 머리에 뒀다가 태현이 처음부터 막혔다.
T-3 절차를 재배열해 **①~③단계(전체의 ~80%)는 config 무관**으로 만들었다(§4 T-3).
그래서 실질 대기는 마지막 스왑 직전 몇 분뿐이다.

> 🔴 **①과 ③의 상대는 봉수의 "계획 레인"이 아니라 "카나리 세션"이다.**
> `services/recipe/**` 소유권이 그쪽으로 갔기 때문이다(§2).

---

## 6. 왜 안 부딪히나 — 근거

| 우려 | 실제 |
|---|---|
| 둘 다 config 레포에 push | **디렉토리가 다르다.** 봉수 `services/**`(recipe 제외) · 태현 `platform/pgsync/**`. git 이 자동 병합 |
| 둘 다 `monitoring/` | **파일을 갈랐다**(§5-②, config#107 머지됨). `rules.yaml` 원본은 아무도 안 건드림 |
| 둘 다 클러스터 조작 | **ns 가 다르다.** 봉수 app ns 워크로드 · 태현 argocd·data ns·ES |
| **카나리 세션과 계획 레인이 같은 사람** | 🔴 **여기가 유일한 실제 위험이었다.** `services/recipe/**` 를 카나리 세션 단독 소유로 넘겨 해소(§2). 계획 레인은 recipe 를 안 건드린다 |
| 카나리 세션의 recipe 재배포가 태현 재색인을 깨나 | **안 깬다.** 파드는 인덱스/alias 를 **읽을** 뿐이고 재색인은 ES 안에서 돈다. 재배포 중에도 검색은 구 인덱스로 계속 나간다 |
| 태현 playbook 이 봉수 배포를 건드리나 | `--tags argocd` 는 **AppProject·root Application 만** 손댄다. 앱 워크로드 무관 |
| 태현 alias 생성이 앱에 영향을 주나 | **없다.** 앱은 `ES_INDEX` 가 바뀌기 전까지 `recipes_pgsync` 를 직접 본다. alias 는 그냥 하나 더 생기는 것 |

---

## 7. 완료 체크리스트

**봉수 (계획 레인)**
- [ ] `github_runner_pat` revoke · `DEPLOY_SSH_KEY` 삭제 (🔴 `argocd_repo_ssh_key` 는 **유지** — 지우면 CD 가 죽는다)
- [ ] `queries.ts` `catch {}` 제거 + `npm run build` 통과
- [ ] services PR 머지 — #13 · #24 · #1 **(recipe 제외 11종)**
- [ ] `mp-mealplan` restart 완료 · `PGSSLMODE` 주입 확인 · priorityClass 빈 파드 0
- [ ] (여력) 유저경로 알람 3종 — `for:` 15~30분

**카나리 세션 (봉수·별도)**
- [ ] 태현에게 alias 생성 확인 받기
- [ ] `rollout.yaml` 에 `priorityClassName: app-normal` (계획 레인에서 넘어온 몫)
- [ ] `rollout.yaml` 의 `ES_INDEX` → `recipes_live` (태현 T-3 ④ 전까지)
- [ ] 카나리 자체 마무리 — Rollout `Available` 이 True 로 수렴하는지 확인

**태현**
- [ ] ES alias `recipes_live` 생성 → **카나리 세션에** 통보
- [ ] `--check --diff` 확인 후 playbook **재실행** → `descheduler` **Healthy** (rollouts 는 이미 복구됨)
- [ ] PGSync 프로브 + 슬롯 알람 적용 · 파드 정상 기동
- [ ] (착수 시 잔여 3h 확보) 새 인덱스 → 재색인 → **직접 검증** → alias 스왑 → **구 인덱스 보존**
- [ ] PGSync CDC 대상을 신규 인덱스로 배선
- [ ] (여력) `#9` rep 1 · `#11` 문서 · `#3` 데이터 티어 알람

---

## 8. 이월 — 오늘 안 해도 안 깨지는 것

| 구간 | 항목 |
|---|---|
| **부채** | #23·#26(문서 15분) → #14a·#5(보안 마감) → #12a(audit) → #10(Harbor 백업, **시크릿 사람 선행**) |
| **성능** | §7 캐시·PG 왕복 9회 → **그 다음** #6 서킷브레이커 (순서 뒤집으면 2일 쓰고 knee 그대로) |
| **개발 끝물** | #12b · #14b · #15 · §7 미완 기능 4건 |
| **시한** | **8/5(수) 05:00** #17 크롤 관찰 → #16. 🔴 재현 기회 **주 1회** |
| **증설** | #18(4노드에선 **설정으로 못 고침**) · #19 |
| **안 함** | #7(오진) · #20 · #22 · #25 |

---

## 부록 — 태현 정리 중 정정 2건

| 항목 | 원 판정 | 실측 |
|---|---|---|
| **#7** HPA | "발화 불가" | ❌ **오진 — idle 을 쟀다.** 부하 실측 = recipe 4 pod 각 **380~525m**(`docs/mp_k6_부하테스트.md:100`), 트리거는 300m×70% = **210m** → 정상 발화. 100m→300m 상향은 **그 부하테스트로 한 진동 방지 튜닝** → 되돌리면 회귀 |
| **#9** ES | "nori 를 가진 유일 인덱스가 b2 종속" | ⚠️ 맞지만 **대상이 DR 폴백이다.** 실서빙 `recipes_pgsync` 는 이미 `rep 1` → b2 를 잃어도 **검색은 산다.** P1 → **P2** |

**#2 라이브**: 라이브 sourceRepos 에 **descheduler·argo-helm 둘 다 없음**.
태현 표의 *"descheduler 라이브 있음"* 은 이미 지나간 상태 — 그 사이 playbook 이 돌아 손 patch 가 지워졌다.
