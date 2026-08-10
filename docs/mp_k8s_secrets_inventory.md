# fb-secrets 원본 인벤토리 — 키 목록 · 사이트 동기화 대상 · 위생 가드

> 체크리스트 `0-11b`(같아야 하는 키 명문화) · `0-11c`(죽은 키) · `0-11d`(SSM 4KB 가드).
> 확정 결정 **C-23**(비밀 = 양 사이트 독립 · AWS=SSM+Pod Identity / 온프렘=현행 ESO 유지) 의 부속 문서다.
> 🔴 **`0-11`(SOPS/age 로 git 화)은 아직 미착수다** — 이 문서는 그 전까지 *"뭐가 있는지"* 를 아는 유일한 수단이다.

작성 2026-08-09 (라이브 실측). 값은 **한 번도 조회하지 않았다** — 키 이름·바이트수·소비처만 봤다.

---

## 0. 왜 이 문서가 필요한가

`fb-secrets` ns 의 Secret 6종은 **전 IaC 밖에서 손으로 만들어졌다**(실측: `managedFields=[]`, 라벨 없음).
ESO 전체의 뿌리가 여기인데 **키 이름 목록조차 git 에 없었다** — 그 머신이 죽으면 뭐가 있었는지도 모른다.

C-23 이 *"양 사이트 독립"* 을 택하면서 두 번째 이유가 생겼다: **드리프트를 막을 구조적 수단이 없다.**
*"비밀이 바뀌면 양쪽 갱신"* 의 약한 고리는 **"바뀌었다는 걸 어떻게 아나"** 이고, 지금 그 답은 **사람 기억**이다.

---

## 1. 원본 6종 · 37키 (2026-08-09 실측)

| Secret | 키 수 | SSM 번들 크기 | 한도 대비 |
|---|---|---|---|
| `app-secrets` | 13 | **3,385 B** | 🔴 **82.6%** (여유 711 B) |
| `data-secrets` | 9 | 550 B | 13.4% |
| `repo-food-budget-config` | 3 | 516 B | 12.6% |
| `pipeline-secrets` | 7 | 261 B | 6.4% |
| `alertmanager-slack` | 2 | 206 B | 5.0% |
| `harbor-pull` | 3 | 113 B | 2.8% |

한도 = SSM Parameter Store **standard tier 4,096 B**. 번들 = 그 Secret 을 JSON 한 덩어리로 넣었을 때의 바이트수(C-23 의 "SSM 번들 6").

---

## 2. 🔴 0-11d — 번들 크기 가드

`app-secrets` 는 이미 **82.6%** 다. **SA JSON 하나만 더 넣으면 4,096 B 를 넘는다.**
넘으면 `PutParameter` 가 실패하고, 그 실패 모드가 **"조용한 갱신 정지"** 다 — 앱은 옛 값으로 계속 돌기 때문에 아무도 모른다.

**채택: 경보선 3,600 B 에서 막는다.** 한도(4,096)에서 막으면 이미 늦다.

```bash
# 마스터에서
python3 /usr/local/sbin/mp-check-secret-bundles.py --strict
# 또는 IaC 로 (eso 롤에 포함, 초과 시 플레이 실패)
ansible-playbook k8s.yml --tags eso
```

구현 = `infra/ansible/roles/k8s_eso/files/check-secret-bundles.py` (읽기 전용 · 값 미출력).
변수 = `eso_bundle_warn_bytes`(3600) · `eso_bundle_guard_strict`(true).

### ⚠️ `Tier: Intelligent-Tiering` 은 대체재가 아니라 보완재다

체크리스트 `0-11d` 는 `PutParameter` 에 Intelligent-Tiering 을 걸어 *"실패 대신 자동 advanced 승격"* 을 제안한다.
그건 **AWS 착수 시점의 항목**이고(지금 SSM 이 없다), **가드를 대체하지 않는다** —
🔴 **advanced 승격은 되돌릴 수 없다.** 넘기 전에 알아야 한다.

---

## 3. 🔴 0-11c — 죽은 키 3개

어떤 ExternalSecret 도 참조하지 않는다(전수 대조 실측):

| 키 | 크기 | 추정 유래 |
|---|---|---|
| `app-secrets/ES_PASSWORD` | 24 B | per-role ES 계정(`0-15`)으로 대체된 잔재 — 지금 앱은 `data-secrets/ES_RECIPE_READER_PASSWORD` 를 쓴다 |
| `pipeline-secrets/ES_PASSWORD` | 24 B | 같음 — 지금은 `data-secrets/ES_PIPELINE_WRITER_PASSWORD` |
| `pipeline-secrets/AWS_REGION` | 14 B | 비밀이 아니다. 리전은 ConfigMap 이 맞다 |

⇒ **SSM 이관 대상은 37키가 아니라 34키.** 충실히 복제하기 전에 지운다 — 안 그러면 죽은 키가 이관돼 영원히 산다.

**조치**: `fb-secrets` 가 IaC 밖이라 지금은 **수동**이다.
```bash
# 🔴 반드시 0-11(SOPS 인벤토리)로 백업한 뒤에. 지금 복구 경로는 etcd 스냅샷뿐이고 보존 14일이다.
kubectl -n fb-secrets patch secret app-secrets      --type=json -p '[{"op":"remove","path":"/data/ES_PASSWORD"}]'
kubectl -n fb-secrets patch secret pipeline-secrets --type=json -p '[{"op":"remove","path":"/data/ES_PASSWORD"}]'
kubectl -n fb-secrets patch secret pipeline-secrets --type=json -p '[{"op":"remove","path":"/data/AWS_REGION"}]'
```
지운 뒤 `check-secret-bundles.py` 로 죽은 키 0 확인.

### 부수 발견 — 빈 값 키 2개 (체크리스트에 없던 것)

**참조는 살아 있는데 값이 0 bytes** 다. 죽은 키와 다르다 — 배선은 멀쩡한데 **기능이 조용히 꺼져 있다**.

| 키 | 소비처 | 결과 |
|---|---|---|
| `pipeline-secrets/DATA_GO_KR_SERVICE_KEY` | `pipelines/ingest/_db.py` (없으면 `SystemExit`) | 이걸 쓰는 `load_price.py` 는 **CronJob 이 없다** → 현재 무영향 |
| `pipeline-secrets/REPORT_GEMINI_API_KEY` | `ml/chat-insights/reports.py` | CronJob `mp-chat-insights` 는 **실제로 도는데** 서술분석이 스킵된다 |

→ 뒤엣것은 *"돌고 있지만 반쪽만 한다"* 라서 알림에도 안 잡힌다. **별건으로 판단 필요**(값을 넣을지, 키를 뺄지).

---

## 4. 0-11b — 두 사이트에서 같아야 하는 키

C-23 이 *"양 사이트 독립"* 을 택했으므로 값 동기화는 **사람이 한다**. 그래서 *무엇을* 맞춰야 하는지가 문서로 있어야 한다.

### 4.1 🔴 조용히 갈리는 7키 — 확정 (C-23)

나머지 키는 갈리면 **즉시 접속 실패**로 드러난다. 이 7개만 **페일오버하는 그 순간에** 드러난다.

| 키 | 갈렸을 때 | 왜 안 드러나나 |
|---|---|---|
| `app-secrets/JWT_SECRET` | 🔴 **전 유저 로그아웃** | 평시엔 각 사이트가 자기 토큰을 자기가 검증한다. 사이트가 바뀌는 순간 기존 토큰이 전부 무효 |
| `app-secrets/GOOGLE_CLIENT_ID` | 로그인 불가 | OAuth 앱은 도메인 기준인데 도메인이 같다 → 평시엔 한쪽만 쓰이므로 안 드러남 |
| `app-secrets/GOOGLE_CLIENT_SECRET` | 로그인 불가 | 〃 |
| `app-secrets/KAKAO_CLIENT_ID` | 로그인 불가 | 〃 |
| `app-secrets/KAKAO_CLIENT_SECRET` | 로그인 불가 | 〃 |
| `app-secrets/CLOUDFLARE_API_TOKEN` | 인증서 발급·DNS 조작 실패 | DNS-01 은 갱신 주기에만 쓴다 |
| `app-secrets/CLOUDFLARE_TUNNEL_CREDS` | 🔴 **터널 미기동** = DR 유입 경로 없음 | 온프렘 cloudflared 는 평시 replicas 0(C-5) — 페일오버 전엔 한 번도 안 뜬다 |

🔴 **7개 중 6개가 `app-secrets` 에 있다.** 그리고 `app-secrets` 가 4KB 한도에 가장 가까운 번들이다(§2) — 같은 파일이 두 위험을 동시에 진다.

### 4.2 나머지 30키 — ⚠️ 제안(미확정). 확정 전 검토 필요

C-23 은 *"같아야 17 / 달라야 17 / 죽은 3"* 으로 총량만 확정했고 **개별 목록은 정하지 않았다.**
아래는 소비처 실측 + 복제 방식으로부터 유도한 **제안**이며, 결정이 아니다.

| 분류 | 키 | 근거 |
|---|---|---|
| **같아야** (물리 복제로 롤이 따라온다) | `app-secrets/PGPASSWORD` · `app-secrets/OPERATIONS_EXTERNAL_PGPASSWORD` · `data-secrets/PGSYNC_PG_PASSWORD` · `data-secrets/STREAMING_REPLICA_PASSWORD` | CNPG replica cluster = 물리 복제 → `pg_authid` 는 클러스터 레벨이라 **비밀번호가 그대로 복제된다**(#546). 다른 값을 넣으면 복제본에서 무시되고 접속만 깨진다 |
| **같아야** (같은 외부 계정) | `app-secrets/GEMINI_API_KEY` · `app-secrets/CHAT_GEMINI_API_KEY` · `app-secrets/GCP_SA_KEY_JSON` · `alertmanager-slack/webhook_default` · `alertmanager-slack/webhook_critical` | 외부 SaaS. 양쪽이 각자 키를 가져도 동작은 하나, 회수·로테이트가 두 배가 된다 |
| **같아야** (같은 레포) | `repo-food-budget-config/{sshPrivateKey,type,url}` | 양 사이트 ArgoCD 가 같은 config 레포를 본다. ⚠️ 별도 deploy key 로 나누는 편이 회수엔 낫다 — **결정 필요** |
| **달라야** (사이트 고유) | `harbor-pull/{USERNAME,PASSWORD,REGISTRY}` | 온프렘=Harbor `192.168.0.10` / AWS=ECR. `REGISTRY` 부터 다르다 |
| **달라야** (사이트 고유) | `data-secrets/ES_{RECIPE_READER,PIPELINE_WRITER,PGSYNC_WRITER}_PASSWORD` | ES 는 **파생 데이터라 재색인**한다(C-15) — 클러스터가 별개고 계정도 별개 |
| **달라야** (사이트 고유) | `data-secrets/PG_BACKUP_AWS_{ACCESS_KEY_ID,SECRET_ACCESS_KEY}` | 🔴 `0-23` 이 barman 경로를 `pg-prod`/`pg-dr` 로 가른다. 자격증명도 함께 가르는 것이 자연스럽다 |
| **온프렘 전용** (AWS 에 없음) | `data-secrets/PG_ONSITE_MINIO_{ACCESS_KEY,SECRET_KEY}` | MinIO 자격증명이다. **C-18 로 AWS 에선 MinIO 가 삭제**된다 |
| **소멸 예정** | `pipeline-secrets/AWS_{ACCESS_KEY_ID,SECRET_ACCESS_KEY}` | `0-16` 이 Pod Identity 로 대체한다. 🔴 **온프렘엔 영구 잔류**(Pod Identity 는 온프렘에서 재현 불가) |
| **값 없음** | `pipeline-secrets/{DATA_GO_KR_SERVICE_KEY,REPORT_GEMINI_API_KEY}` | §3 부수 발견 |
| **죽음** | 3키 | §3 |
| **판단 보류** | `pipeline-secrets/PGPASSWORD` | 앱과 같은 `fbapp` 계정인지 확인 필요. `0-13`(서비스별 롤)이 이걸 바꾼다 |

### 4.3 갱신 절차 (지금은 이게 전부다)

```
1) 어느 한쪽에서 비밀을 바꾼다
2) 🔴 반대쪽 fb-secrets / SSM 에도 같은 값을 넣는다   ← 사람 기억이 유일한 메커니즘
3) 받는 워크로드를 rollout restart               ← envFrom 은 파드 기동 시점 주입이다
4) check-secret-bundles.py 로 번들 크기 재확인
```
🔴 **2번이 이 설계의 약한 고리다.** `0-11`(SOPS 로 git 커밋)이 붙으면 **PR 이 곧 변경 신호**가 되고,
두 사이트 값이 같은 파일에 있어 **조용한 드리프트가 구조적으로 불가능**해진다. 그게 0-11 의 진짜 값어치다.

---

## 5. 복구 경로 — 🔴 지금은 하나뿐이다

`secrets_backup` 묶음에 **`fb-secrets` Secret 자체가 안 들어간다**(체크리스트 0-11).
현 복구 경로 = **etcd 스냅샷 + aescbc 키** 조합 단 하나이고, **etcd 보존 14일 = 시크릿의 실질 RPO** 다.

→ `0-11`(SOPS/age)이 이걸 해소한다. age 개인키는 `secrets_backup` 묶음 + 오프라인 2곳
(2026-07-29 passphrase 소실 전례가 있어 같은 묶음 단독 보관은 SPOF 를 상속한다).

---

## 6. 관련

- `docs/mp_aws_prep_checklist.md` — C-23(비밀 양 사이트 독립) · 0-11 계열 · 0-16 · 0-23
- `docs/mp_k8s_rbac_plan.md` §11~§13 — 이 시크릿들에 누가 닿을 수 있는가
- `infra/ansible/roles/k8s_eso/` — ClusterSecretStore(`0-14b` 로 참조 ns 제한됨) · 위생 가드
- 이슈 #521(ES PoLP) · #546(PG 서비스별 롤) — 4.2 의 여러 항목이 이 둘에 걸려 있다
