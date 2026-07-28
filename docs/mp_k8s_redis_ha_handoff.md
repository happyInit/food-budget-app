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
| 오퍼레이터 | OT-Container-Kit `redis-operator` | 차트 **0.25.0** + `image.tag=v0.26.0` (아래 ⚠️) |
| 차트 repo | `https://ot-container-kit.github.io/helm-charts` | |
| 부속 차트 | `redis-replication` 0.17.0 · `redis-sentinel` 0.16.13 | |

⚠️ **차트가 이미지보다 한 릴리스 뒤처져 있다.** 차트 0.25.0 의 appVersion 이 아직 0.25.0 인데,
우리가 필요한 수정(#1711)은 **v0.26.0** 에 들어 있다. `image.tag` 오버라이드가 필수이고, 이 불일치를
기록해두지 않으면 다음 사람이 차트만 보고 0.25.0 으로 되돌린다.

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
- **CRD 는 클러스터 스코프다.** helm 으로 깔면 클러스터 전역에 남는다 — 철거할 때 CRD 정리까지.
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
