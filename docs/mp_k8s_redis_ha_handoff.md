# Redis HA(캐시) 담당자 핸드오프

> **이 문서의 범위** — P2 데이터 티어 중 **앱 캐시용 Redis** 하나만. 다른 데이터 티어(PG·ES·Kafka)와
> 분리해 독립 진행하기 위한 문서다.
> 상위 계획 = [`mp_k8s_p2_data_runbook.md`](./mp_k8s_p2_data_runbook.md) (Q3·§2-A-1) · 현황 =
> [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md). **여기서 그 내용을 복제하지 않는다.**
> 작성 2026-07-28

---

## 1. 왜 이것만 떼어낼 수 있나 (의존성 실측)

**Redis 만 스토리지·인증 의존이 0이다.** 2026-07-22 사고(호스트 급사 → AOF 손상 → PGSync 16시간
크래시루프)로 **영속성을 끄기로 확정**했기 때문에 PVC 가 아예 필요 없다. PG·ES·Kafka 는 전부 PVC 를
잡아야 해서 스토리지 계층에 묶이는데, Redis 는 거기서 자유롭다. 인증도 현행 무인증 유지라 ESO·Secret 도
안 걸린다.

| 필요한 것 | 상태 |
|---|---|
| 4노드 클러스터 (Sentinel 3개를 B 2 · A 1 로 분산) | ✅ 2026-07-28 `k8s-worker-a1` 합류로 충족 |
| `data` 네임스페이스 (PSS `baseline`) | ✅ 존재, **현재 비어 있음** |
| PriorityClass `data-critical` | ✅ |
| StorageClass / PVC | **불필요** (비영속) |
| Secret · ESO | **불필요** (무인증 유지) |
| ArgoCD `platform` AppProject · `platform/` 디렉토리 | ⬜ 미배선 — **하지만 검증을 막지 않는다**(아래) |

🔴 **검증 단계는 GitOps 를 안 거친다.** 런북이 정의한 작업 자체가 **"임시 배포 → 검증 → 철거"** 라
helm/kubectl 로 직접 하는 throwaway 다. 그래서 platform-root 배선(인프라 담당 진행 중)과 **무관하게
지금 당장** 시작할 수 있다. GitOps 편입은 검증이 끝나고 platform-root 가 생긴 뒤에 합류한다.

## 2. 🔴 이건 네 범위가 **아니다**

- **`redis-pgsync`** — 별개 인스턴스다. PGSync 전용이라 PGSync 이전 작업에 묶여 있다. 같이 가져가면 충돌한다.
- **`config` 레포 편집** — 검증엔 불필요. 편입 시점에 인프라 담당의 `platform/` 구조와 합친다.
- **새 네임스페이스 생성** — PSS 라벨이 필요하고 그건 `k8s_cluster_base`(인프라 담당) 소관이다.
  **검증은 `data` ns 안에서 임시 이름으로** 하면 아무것도 안 건드린다.
- **앱 코드 수정** — 분기 C 가 확정되기 전엔 손대지 않는다(§5).

## 3. 물려받는 것 — 실제 이름과 좌표

| 종류 | 값 | 비고 |
|---|---|---|
| 대상 ns | `data` | `enforce: baseline` · 메시 OFF(사이드카 없음) |
| PriorityClass | `data-critical` (1000000) | 매니페스트에 이 이름 그대로 |
| 노드 zone 라벨 | `topology.kubernetes.io/zone` = `host-a` / `host-b` | **배치의 유일한 기준** |
| 배치 원칙 | **primary = A** · **Sentinel 다수(2) = B** | A 급사 시 B 의 중재자가 승격시켜야 한다 |
| 현행 Redis | `192.168.0.8:6379` (redis:7-alpine · LRU 256mb · **비영속**) | 컷오버까지 그대로 산다 |
| 오퍼레이터 | OT-Container-Kit `redis-operator` | 🔄 **2026-07-29 변경: 네가 설치하지 않는다** — platform-root(ArgoCD)가 `redis-operator-system` ns 에 차트 0.25.0(이미지 v0.25.0 정합)으로 **자동 설치**한다(config 레포 `platform/argocd/redis-operator.yaml`). `kubectl -n redis-operator-system get deploy` 로 Ready 확인만 |
| 차트 repo | `https://ot-container-kit.github.io/helm-charts` | |
| 부속 차트 | `redis-replication` 0.17.0 · `redis-sentinel` 0.16.13 | |

⚠️ **v0.26.0 오버라이드는 "기본"에서 "검증 결과로 판단"으로 바뀌었다**(2026-07-29, 런북 §1.1 정정).
근거: 차트 0.25.0 이 들고 있는 **CRD 도 0.25.0 시절 것**이라, 이미지만 올리면 오퍼레이터가 자기보다
낡은 CRD 위에서 돈다. → **먼저 0.25.0 정합 상태로 4단계를 돌려라.** 시나리오 2(#1711)가 실제로
재현되면 그때 v0.26.0 오버라이드(+CRD 영향 확인)를 시험한다 — **재현 여부 자체가 산출물**이고,
오버라이드가 필요해지면 config 레포 `platform/argocd/redis-operator.yaml` 수정이라 **인프라 담당과 함께**(§8 동기화 S2).

**Redis 버전**: 7.x 로 이미지 태그를 명시 핀할 것. 오퍼레이터 기본 이미지는 `quay.io/opstree/redis:v8.x`
계열이라 그냥 두면 8 로 뜬다. (오퍼레이터의 Redis 버전 상한 매트릭스는 **공식 근거를 못 찾았다**.)

## 4. 🔴 검증 4단계 — 이게 산출물이다

**목적**: "페일오버 시 오퍼레이터가 master Service 의 대상을 **실제로** 갱신하는가". 우리 요구사항이
**앱 코드 수정 0** 이라 이게 통과해야 앱을 안 건드린다.

메커니즘(소스 확인): `<name>-master` Service 의 셀렉터가 `redis-role=master` 라벨이고, 컨트롤러가
매 reconcile 마다 각 파드에 실제 role 을 **물어봐서** 라벨을 다시 붙인다. 즉 **Sentinel 이벤트 구독이
아니라 폴링 수렴**이다 — 그 루프가 막히면 Service 가 굳는다. 아래 4단계가 그 실패 경로를 하나씩 친다.

| # | 시나리오 | 확인 | 관련 이슈 |
|---|---|---|---|
| 1 | master 파드 `delete` | `<name>-master` 엔드포인트가 새 master 로 바뀌는가 · **수렴까지 몇 초** | 기본 동작 |
| 2 | master 노드 `cordon` 후 파드가 **Pending 인 채로** 재측정 | 파드 unreachable 이면 role 조회가 `connection refused` → reconcile 백오프 → **Service 가 안 바뀜** | **#1711** (v0.26.0 에서 수정됐다지만 **실측 필요**) |
| 3 | 페일오버 후 **각 슬레이브**에서 `INFO replication` 의 `master_host` | 죽은 IP 를 물고 있지 않은가 | 🔴 **#1779 OPEN** |
| 4 | sentinel 파드에서 `SENTINEL get-master-addr-by-name` | 반환 IP 가 **살아 있는가** | 🔴 **#1781 OPEN** |

```bash
# 3·4 확인 예시 (이름은 실제 CR 이름으로 바꿀 것)
kubectl -n data get endpoints <name>-master -o jsonpath='{.subsets[*].addresses[*].ip}'
kubectl -n data exec <slave-pod> -- redis-cli INFO replication | grep master_host
kubectl -n data exec <sentinel-pod> -- redis-cli -p 26379 SENTINEL get-master-addr-by-name <name>
```

🔴 **판정: ④까지 통과 못 하면 채택 불가.** ③이 걸리면 특히 위험하다 — Service 도 sentinel 도 정상으로
보이고 쓰기도 성공하는데 **복제본이 0개인 상태로 조용히 운영**된다(신고 사례 19시간 방치).

**#1779 의 원인은 구조적이다**: 슬레이브 재구성 분기가 `!instance.EnableSentinel()` 로 게이팅돼 있어
**sentinel 을 켜면 그 코드가 아예 안 돈다.** 우리는 sentinel 을 켤 것이므로 정면으로 해당된다.

### 4.1 실측 결과 (2026-07-29 · 인프라 담당 수행 — 트랙 인계됨)

#### 1차 — 원본 CR(#370) 그대로

대상 = `food-budget-app#370` 의 CR 을 **손으로 적용한 상태 그대로**(배치 제약·PDB 없음). 교정판은
config 레포 `platform/redis/` 로 이관했고(mealplanning-config#11), **재측정은 그 위에서 다시 한다.**

| # | 시나리오 | 결과 | 수치 |
|---|---|---|---|
| 1 | master 파드 `delete` | ⚠️ **조건부 통과** — Service 는 갱신되지만 일어난 일은 페일오버가 아니라 **failback** 이다 | 엔드포인트 **공백 0~26초** · **31초**에 `mp-redis-0`(재기동된 옛 master)으로 복귀 · sentinel 승격은 **16초** |
| 2 | 노드 `cordon` 후 Pending 재측정 | ⬜ 미실시 | — |
| 3 | 슬레이브의 `master_host` | ✅ 죽은 IP 를 물지 않음 | `mp-redis-1 → 10.244.2.40`(살아있는 pod-0) |
| 4 | `SENTINEL get-master-addr-by-name` | 🔴 **실패** | 3대 만장일치로 **읽기전용 복제본**을 반환. **수동 개입(sentinel 3대 재기동) 전까지 자가 복구 안 됨** |

**무슨 일이 일어났나** — 오퍼레이터 로그가 결정적이다:
```
No master with attached slaves found, falling back to Status.MasterNode
updated pod role label
```
sentinel 이 `mp-redis-1` 을 승격시킨 뒤, 오퍼레이터가 **그걸 무시하고 `mp-redis-0` 을 master 로 되돌렸다.**
그 결과 두 제어면이 영구히 갈라진다 — sentinel 은 계속 `mp-redis-1` 을 master 라 답하고, 자기가 붙인
플래그가 `s_down,o_down,master` + `role-reported: slave` 인데도 **재선출을 하지 않는다.**

**클라이언트 에러 형태 (§7 산출물)**
- sentinel 이 알려준 주소로 쓰기 → **`READONLY You can't write against a read only replica.`**
- `<name>-master` Service 경로 → 페일오버 직후 **~26초간 엔드포인트 없음**(연결 실패), 이후 정상

🔴 **부수 발견 — 파드 재시작 한 번에 캐시가 전멸한다.** 페일오버 전 master 에 심은 카나리가 복제본까지
전파돼 있었는데 페일오버 후 **양쪽 다 비었다.** 비영속 설계라 pod-0 이 빈 채로 살아났고, 오퍼레이터가
걔를 master 로 되돌리면서 **빈 데이터셋을 복제본에 덮어썼다.** 노드 하나를 잃는 게 아니라 캐시 전체가
리셋된다 — §6 "price 캐시는 nGrinder 병목 대책의 절반" 과 같이 읽어야 한다.

#### 2차 — 교정판(mealplanning-config#11) 위 **4단계 전수**

배치 제약(zone/hostname 분산)·PDB·CPU limits 제거·ServiceMonitor 를 적용한 상태. **결론은 바뀌지 않았다.**

| # | 시나리오 | 판정 | 실측 |
|---|---|---|---|
| 1 | master 파드 `delete` | ⚠️ 조건부 | 엔드포인트 공백 **5초**(1차 26초에서 개선) → **7초**에 failback. 그 과정에서 **마스터 2개·복제 0**(스플릿브레인) 구간 발생 → 오퍼레이터가 **~2분** 뒤 자가복구 |
| 2 | 노드 `cordon` 후 Pending | 🔴 **#1711 재현** | **110초 내내 Service 엔드포인트 없음** → `Connection refused`. 살아있는 복제본 `mp-redis-1` 은 **끝까지 `role:slave`, 승격 없음** |
| 3 | 슬레이브의 `master_host` | 🔴 **#1779 재현** | master 가 새 노드·새 IP 로 재기동한 뒤 슬레이브가 **죽은 IP 를 62초** 물고 있었다(그 뒤 오퍼레이터가 수정) |
| 4 | `SENTINEL get-master-addr-by-name` | 🔴 **실패(3회 연속)** | 슬레이브를 master 로 광고. **수동 재기동 전까지 자가복구 없음** |

**총 불통 = 약 3분**(09:13:33 → 09:16:37). 시나리오 2 구간의 오퍼레이터 로그가 §4 가 예측한 메커니즘 그대로다:
`dial tcp :6379: connect: connection refused` **56회** + `Failed to Get the role Info of the` **14회** + `Reconciler error`/`requeue with error`.

✅ **알람 초안이 실제로 잡았다** — 스플릿브레인 구간에 `MpRedisMasterCountAbnormal` 이 **pending** 진입.
`redis_up` 은 내내 1이었으므로 이 규칙이 없으면 **아무도 모른 채 지나갔다**(§6 의 "복제본 수를 직접 봐라" 와 같은 계열).

#### 🔴 구조적 근인 — 연결되지 않은 두 제어면

`RedisReplication.spec.sentinel` 이 **비어 있다**(CRD 에 필드는 있다). 그래서
**replication 컨트롤러는 자신을 "sentinel 없음"으로 보고 ordinal 기반으로 독자 복구**하고,
별도 `RedisSentinel` CR 은 그 사실을 모른 채 **독립적으로 선출**한다. 둘이 서로를 덮어쓰는 것이 1·4 실패의 정체다.

§4 가 지목한 `!instance.EnableSentinel()` 게이팅과도 맞물린다 — 우리 구성은 게이팅이 **열려** 있어
슬레이브 재구성 코드가 돌았고(62초에 죽은 IP 수정), 그 대가로 sentinel 과 충돌한다.
→ `spec.sentinel` 을 인라인으로 채우면 게이팅이 닫히면서 **OPEN 인 #1779 가 살아난다**.
**시끄러운 실패를 조용한 실패로 바꾸는 교환이라 채택하지 않는다.**

#### 3차 — 오퍼레이터 이미지 **v0.26.0** (mealplanning-config#12)

차트는 0.25.0 그대로(0.26.0 차트는 **없다**) + `redisOperator.imageTag=v0.26.0`. 오퍼레이터는 깨끗하게 떴고
(`setting up v1beta2 scheme`, restarts 0) **CRD 비정합의 즉각적 악영향은 없었다** — CR·파드 churn 0.

**v0.26.0 이 실제로 고친 것**

| 항목 | 0.25.0 | v0.26.0 |
|---|---|---|
| 스플릿브레인(마스터 2개·복제 0) | 🔴 발생 | ✅ 없음 |
| 시나리오 3 (#1779) | 🔴 죽은 IP 62초 | ✅ 즉시 추종 |
| Sentinel 자가 수렴 | ❌ 수동 재기동 전까지 불가 | ⚠️ **때때로**(30초 성공 1회 · **245초까지 실패** 1회) |

**여전히 실패하는 것 — A 와 C 가 서로 다른 국면에서 깨진다**

| 국면 | A = `<name>-master` Service | C = Sentinel-aware 클라이언트 |
|---|---|---|
| ① 파드 delete(재스케줄 가능) | ✅ 31초 수렴 | 🔴 **죽은 IP 를 150초+ 광고** |
| ② 노드 상실(Pending 고정) | 🔴 **엔드포인트 영구 공백** | ✅ **11초 · 살아있는 master** |
| ③ failback 직후 | ✅ 정상 | 🔴 **슬레이브 광고 245초+**(자가수렴 실패) |
| ④ 슬레이브 `master_host`(#1779) | ✅ | ✅ |

③ 실측 스냅샷:
```
실제 master        = mp-redis-0 @ 10.244.1.79
Service 가 주는 곳  = 10.244.1.79   → 쓰기 OK
Sentinel 이 주는 곳 = 10.244.3.41   → READONLY You can't write against a read only replica.
sentinel flags = s_down,o_down,master / role-reported = slave   ← 다운인 줄 알면서 재선출 안 함
```

🔴 **둘 다 §4 판정 기준("④까지 통과 못 하면 채택 불가")을 넘지 못한다.**

**같은 뿌리다** — 오퍼레이터는 **항상 ordinal-0 을 master 로 되돌리고** Sentinel 은 자기 선출을 유지한다.
pod-0 이 살아 돌아올 수 있는 국면(①③)에서는 **Sentinel 이 틀리고**, pod-0 이 못 돌아오는 국면(②)에서는
**Service 가 빈다.** 한쪽이 맞을 때 다른 쪽이 틀리므로 **단일 경로로는 두 국면을 다 덮을 수 없다.**

#### 🔴 방법론 정정 — 1·2차의 시나리오 2 측정은 무효였다

1·2차 모두 **sentinel 이 이미 오염된 상태(`num-slaves 0`)에서 시나리오 2 를 시작**했다. 승격 후보를 모르는
sentinel 이 승격을 못 한 건 당연하므로, 그 위에서 내린 **"sentinel 이 승격을 못 한다"·"C 는 확실히 실패하는
경로다" 는 근거가 없었다.** 시야가 정상(`num-slaves 1`)인 상태로 다시 재니 **11초에 정확히 승격**했다.
→ **재측정 사전조건 = `SENTINEL master <name>` 의 `flags=master`·`num-slaves≥1` 확인.** 안 보고 재면 무효다.

master 를 인위적으로 응답불능으로 만드는 시도 3건도 **전부 조용히 무효**였다(측정값이 나오므로 속기 쉽다):
- `redis-cli -t` — 이 이미지의 redis-cli 에 **없는 옵션**(`Unrecognized option`)
- `DEBUG SLEEP` — **Redis 7 부터 기본 비활성**(`enable-debug-command no`) → `ERR DEBUG command not allowed`
- `kill -STOP 1` — **컨테이너 PID 1 에는 커널이 SIGSTOP 을 전달하지 않는다**
→ 유효했던 방법 = **NetworkPolicy 격리**(런북 §9-27 라벨 함정 주의) · 파드 삭제 + 노드 cordon.

### 4.3 🔴 결정 지점 — "② 를 수용할 것인가"

3차까지가 좁혀준 결론: **이 오퍼레이터에게는 ordinal-0 이 아닌 파드를 master 로 승격시키는 능력이 없다.**
Sentinel 이 승격시켜도 pod-0 이 돌아오면 되돌린다. 따라서 **어떤 구성을 골라도 "master 파드가 뜰 수 없는
동안 캐시 없음"(②)은 남는다.** 선택은 사실상 **② 수용 여부**로 좁혀진다.

- **수용** = ⓒ(Sentinel 제거) + Service 단독. **실패 지점이 2개→1개**로 줄고(①③은 정의상 소멸), 앱 코드 무변경,
  탐지는 `MpRedisNoReplica`·`MpRedisMasterCountAbnormal`(2차에서 실제 탐지 확인)
- **불수용** = §5 의 **B(수제 구성)**. CLAUDE.md "Redis 오퍼레이터 선정" 미정 항목을 다시 여는 결정

🔴 **판단 재료**: 호스트 급사 이력 **3회**(status §1.0.2) · §6 "price 캐시는 nGrinder 200VU 포화 해소 대책의
절반" · 페일오버마다 **캐시 전멸**(비영속 pod-0 이 빈 채로 master 복귀하며 복제본을 덮어씀 — 3라운드 전부 재현).

### 4.2 🔴 §5 분기 매트릭스의 전제가 실측과 어긋난다

§5 는 **"Sentinel 은 믿을 만하고 약한 고리는 오퍼레이터의 Service 갱신"** 을 가정한다(그래서 C =
"Service 갱신이 부실 → 클라이언트를 Sentinel-aware 로"). 1차 실측은 **정반대**다:

- Service 갱신은 **된다**(31초, 실제 role 폴링 추종)
- **Sentinel 이 깨진다**(읽기전용 복제본을 영구 광고)

→ **C 는 대피로가 아니라 확실히 실패하는 경로다.**

🔴 **2차에서 A 도 닫혔다.** 시나리오 2 에서 **master 파드가 스케줄되지 못하면 Service 는 빈 채로 남고
아무도 승격하지 않는다.** 이건 sentinel 탓이 아니라 오퍼레이터 자체다 — 즉 **이 오퍼레이터는
"master 노드 상실"을 견디지 못한다.** 그런데 이 프로젝트의 실제 사고 이력이 정확히 그것이다
(호스트 급사 3회, status §1.0.2). 캐시가 3분 불통되면 §6 이 경고한 nGrinder 병목이 그대로 돌아온다.

**남은 후보 (2026-07-29 기준)**

| | 후보 | 근거·상태 |
|---|---|---|
| **ⓑ** | 오퍼레이터 이미지 **v0.26.0** | ✅ **시험 완료(3차)** — 스플릿브레인 소멸·#1779 해소는 실측됐으나 **④는 여전히 실패**. **개선이지 해결이 아니다.** 되돌릴 이유는 없어 유지 |
| ⓒ | Sentinel 제거, 오퍼레이터 단일 제어면 | 3차로 의미가 바뀌었다 — **①③의 실패가 정의상 소멸**하고 남는 실패가 **②뿐**이 된다. 상세 = §4.3 |
| ⓓ | `RedisReplication.spec.sentinel` 인라인 | 게이팅이 닫혀 **OPEN 인 #1779 가 살아난다**. 비추천(위 구조적 근인 항목) |

**ⓑ 로도 시나리오 2 를 못 넘으면** — 그건 §5 의 **B(수제 구성)** 를 여는 근거다. CLAUDE.md 의
"Redis 오퍼레이터 선정" 미정 항목이 그 자리다.

## 5. 결과에 따른 분기 (런북 Q3)

| 분기 | 조건 | 후속 작업 |
|---|---|---|
| **A** | 4단계 전부 통과 | **앱 코드 무변경.** 앱은 master Service 이름 하나만 본다. 전환창에서 ConfigMap 좌표만 바꾼다 |
| **C** | Service 갱신이 부실 | 오퍼레이터는 유지하되 **클라이언트를 Sentinel-aware 로 전환** — 🔴 **접속 코드 4곳**: `services/chat/app/db.py` · `services/price/app/db.py` · `pipelines/stream/_redis.py` · `pipelines/ingest/refresh_price_matview.py`. 앱 이미지 재빌드까지 파생되므로 **일정 여유가 필요**하다 |
| **B** | 오퍼레이터 자체를 못 믿겠다 | 수제 구성 — 이건 CLAUDE.md 의 "오퍼레이터 후보" 결정을 다시 여는 것이라 **별도 논의** |

## 6. 함정

- 🔴 **영속성을 켜지 마라.** AOF/RDB 를 켜면 2026-07-22 사고가 재발한다. HA 의 목적은 데이터 보존이
  아니라 **연속성**이다 — 캐시·세션은 유실돼도 재생성된다.
- 🔴 **"그냥 캐시니까 없어도 된다"가 성립하지 않는다.** price 캐시는 nGrinder 200VU 포화를 해소한
  대책의 절반이다. Redis 가 죽으면 해소했던 병목이 그대로 돌아온다 — 가용성 문제다.
- **`connected_slaves` 를 알람으로 걸어라.** #1779 의 조용한 실패는 `redis_up`·`redis_master_link_up`
  으로는 **안 잡힌다**(이슈 본문 명시). 복제본 수를 직접 봐야 한다.
- 🔄 **철거 범위 변경(2026-07-29): 오퍼레이터·CRD 는 이제 공용 인프라다**(ArgoCD 관리) — **절대 지우지 마라.** 철거 대상은 **네가 만든 CR(RedisReplication·RedisSentinel)과 그 PVC 뿐**이다. CRD·오퍼레이터를 지우면 P2 본배포가 죽는다.
- 검증 중 RAM 은 다른 워크로드와 공유한다(호스트 A 여유 ~18GB 기준으로 시작했으나 worker-a1 이
  12GB 를 가져갔다). 데이터 티어 Redis 예산은 **~1.2GB** 다.

## 7. 완료 판정 체크리스트

- [ ] 4단계 검증 **전부** 수행하고 **수렴 시간(초)을 기록**했다 — 통과/실패만이 아니라 숫자가 산출물이다
- [ ] 클라이언트에서 관측되는 **에러 형태**를 기록했다(전환창에서 무엇을 보게 될지의 근거)
- [ ] A/C **분기를 확정**하고 근거를 남겼다
- [ ] C 라면 접속 4곳의 수정 범위를 산정했다
- [ ] 임시 배포물을 **철거**했다(CRD 포함)
- [ ] Redis 버전 7.x 이미지 태그 핀을 정했다
- [ ] `connected_slaves` 알람 초안을 남겼다

결과를 인프라 담당에게 넘기면 `platform/redis/` 매니페스트와 전환창 스텝 7(Redis 좌표)에 반영된다.

## 8. 병렬 진행 단계표 (2026-07-29 신설) — 인프라 트랙과 같은 시기에 끝내기

> 두 트랙이 **지금 동시에 시작**해서 **리허설 전에 합류**하는 것이 목표다. 절대 시각이 아니라
> **이벤트 기준**으로 정렬한다(인프라 트랙이 머지·sync 진행 속도에 따라 하루쯤 밀릴 수 있다).
> 🔴 하드 데드라인은 하나 — **S3(리허설) 시작 전까지 분기 확정**(런북 §2 "리허설 전까지 필요").

| 단계 | 인프라 담당 (P2 §2-C 체인) | Redis 담당 (이 문서 §4) | 동기화 / 전달물 |
|---|---|---|---|
| **D0** (지금) | config#2 머지 → 오퍼레이터 5종 자동 설치 확인 → fb-secrets 적재(ⓑ)·pg_hba `.20`(ⓓ) → 데이터 CR manual sync 시작(kafka+토픽 선생성 · pg replica · es · pgsync dark) | §1~§6 숙지 → `redis-operator-system` Ready 확인(**설치 금지** — §3) → RedisReplication+Sentinel **임시 CR 초안·배포**(data ns · 임시 이름 · `data-critical` · zone 배치 §3) | ▶ **S0**: 인프라가 "오퍼레이터 Ready" 를 알리면 Redis 트랙 즉시 착수 가능. 이게 유일한 선행조건이다 |
| **D0~D1** | CNPG replica 복제 확인(C-2) → ES 비번 복사(ⓔ)·사전 재색인 Job(C-3) → 파이프라인 트랙 릴리스 런(ⓐ)·dark-deploy(C-4) | **검증 4단계 실측**(반나절) — 수렴시간(초)·클라이언트 에러 형태 기록. 시나리오 2(#1711) 재현 여부 주목 | ▶ **S1**(조건부): #1711 재현 시 → v0.26.0 오버라이드 시험은 config 레포 수정이라 **인프라와 함께**(§3 ⚠️) |
| **D1~D2** | 리허설 준비(§7 절차·검증 스크립트) — **Redis 분기 대기** | **분기 A/B/C 확정 + §7 체크리스트 완성** → 결과 전달: ① 분기 ② master Service 실이름 ③ Redis 7.x 태그 핀 ④ 수렴시간·에러형태 ⑤ `connected_slaves` 알람 초안 | ▶ 🔴 **S2 (합류 지점)**: 이 전달물로 인프라가 `platform/redis/` CR + `platform/argocd/redis.yaml` child + `pipelines/configmap.yaml` 의 `REDIS_URL` placeholder 해소 + 전환창 스텝 7 좌표 확정. **C 분기면** 접속 코드 4곳 수정 산정 → 앱 담당 리뷰 루프가 추가되므로 **하루 이상 당겨 알릴 것** |
| **D2~D3** | **풀 리허설(§7)** → 전환창 일정 확정 | 임시 배포물 **철거**(🔴 CR·PVC 만 — §6) → 본 redis CR manual sync 배석·검증 | ▶ **S3**: 리허설 진입 = Redis 분기 확정이 선행조건. 미확정이면 리허설이 밀린다 |
| **전환창** | 런북 §4 주도 | 스텝 7(Redis 좌표 전환) 검증 배석 — 기록해 둔 "클라이언트 에러 형태"가 정상 전환 판정 기준 | |

**막힘 보고 규칙**: 각 단계에서 반나절 이상 막히면 상대 트랙에 즉시 알린다 — 특히 S2 가 밀리면
리허설·전환창이 통째로 밀리는 구조라, "거의 다 됐다"보다 "언제 나온다"가 필요하다.
