# AWS(EKS) Stage1 부하시험 — 실행 런북

**한 줄**: `loadtest/run_aws_stage1.sh run` — 준비·실행·원복이 한 번에 돈다.

```bash
loadtest/run_aws_stage1.sh check          # 전제만 확인(부하 안 걸림)
loadtest/run_aws_stage1.sh run            # 500 VU · 고원 8분
VUS=1500 loadtest/run_aws_stage1.sh run   # Karpenter 최대치
```

---

## 1. 온프렘 시험과 무엇이 다른가

| | 온프렘(기존) | AWS |
|---|---|---|
| 진입점 | MetalLB VIP `.14` **단일** | ALB — **AZ 당 IP 1개씩 2개** |
| k6 `hosts` 고정 | 함 (`.14`) | 🔴 **안 함**(`IP=none`) |
| 앞단 방어 | 없음 | 🔴 **AWS WAF 레이트룰** |
| 노드 | 고정 5대 | 고정 2대 + **Karpenter 최대 4대** |
| 고원 길이 | 90초 | 🔴 **8분** |

🔴 **IP 를 고정하면 AZ 한쪽만 측정한다.** ALB 는 AZ 당 ENI 를 하나씩 두고 DNS 가 둘 다 준다.
한 IP 에 못 박으면 "2 AZ 로 분산된 클러스터"가 아니라 "AZ 한 개"의 성능을 재게 된다.
⇒ `stage1_journey.js` 에 `IP=none` 스위치를 넣었다(기본값은 온프렘 `.14` 그대로 — 기존 실행 불변).

---

## 2. 🔴 WAF — 안 풀면 시험 자체가 성립하지 않는다

`mp-waf-public` 의 `rate-limit-per-ip` = **2000 요청 / 5분 / IP = 초당 6.7건**.
500 VU 는 think-time 평균 2초에 반복당 3요청이므로 **한 IP 에서 초당 약 750건**을 보낸다.
⇒ **약 3초 만에 차단**되고, 그 뒤 측정치는 우리 스택이 아니라 **WAF 403** 이다.

이건 예견돼 있던 조건이다 — `infra/terraform/aws-platform/variables.tf` 의
`waf_rate_limit_per_5min` 주석이 *"EKS 로 부하를 걸 때는 값을 한시로 올리거나 출발지 IP 를
예외로 뺄 것. **올린 뒤 되돌리는 것까지가 그 작업의 일부다**"* 라고 못박아 뒀다.

스크립트가 하는 일: `terraform apply -var waf_rate_limit_per_5min=5000000` → 시험 → **원복 apply**.
원복은 `trap` 에 걸려 있어 **Ctrl-C·k6 자동중단·중간 실패 어느 쪽이든** 되돌아간다.

⚠️ 시험 중에는 레이트 방어가 사실상 없다. 창이 10분 남짓이라 감수하되, **원복을 반드시 확인**한다:
```bash
aws --profile mp-platform wafv2 get-web-acl --scope REGIONAL --region ap-northeast-2 \
  --name mp-waf-public --id <id> --query 'WebACL.Rules[0].Statement.RateBasedStatement.Limit'
# 2000 이어야 한다
```

---

## 3. 🔴 Karpenter 를 실제로 발동시키려면

**HPA max=4 로는 안 뜬다.** 산수:

| | 값 |
|---|---|
| 노드 allocatable | 3920m × 2 = **7840m** |
| 현재 요청 합 | 3230m + 3240m = 6470m (82%) |
| **여유 CPU** | **1370m** |
| account 파드 1개 | 350m + 사이드카 30m = **380m** |
| recipe 파드 1개 | 200m + 사이드카 30m = **230m** |

max=4 면 증가분이 (2×380)+(2×230) = 1220m 로 **여유 1370m 안에 들어간다** → Pending 파드가
안 생긴다 → **Karpenter 는 Pending 파드에만 반응하므로 아무 일도 안 한다.**

⇒ 스크립트가 **max 를 8 로 올린다**. 그러면 (6×380)+(6×230) = 3660m 이 필요해 **2290m 이 부족** →
Pending 발생 → Karpenter 가 `mp-burst` NodePool 로 노드를 띄운다.

- NodePool 상한 `cpu: 16` = m7g.xlarge 기준 **최대 4대** (총 2 + 4 = 6대)
- taint `mp.io/burst=true:NoSchedule` — account·recipe 에 **toleration 이 붙어 있는 것 확인함**
  (1-43 결손은 해소됨. 이게 없으면 Karpenter 는 영원히 일하지 않는다)
- 🔴 **고원 8분** — 노드 기동+부트스트랩+조인에 60~90초가 걸린다. 90초 고원이면 노드가 Ready 되는
  순간 시험이 끝나 *"NodeClaim 은 생겼는데 처리량은 그대로"* 라는 **측정 실패**가 나온다.

메모리는 여유 4153Mi 에 증가분 3840Mi 라 아슬하게 들어간다 ⇒ **CPU 가 먼저 막힌다**(의도한 대로).

### 🔴 3.1 1회차 실행에서 드러난 것 (2026-08-17 · 500 VU · 리허설)

위 산수는 맞았지만 **Karpenter 는 발동하지 않았다**(NodeClaim 0). 이유가 두 개였다.

**① `kubectl patch` 로 올린 max=8 을 ArgoCD 가 되돌렸다.**
시험 시작 80초 뒤 `mp-account` 에 자동 싱크가 들어왔다(sync history #11, 05:19:04Z).
`selfHeal: false` 라 드리프트 치유가 아니라 **새 리비전 싱크**였다 — 팀원이 1시간 전 머지한
커밋이 하필 그때 처음 반영됐다. 즉 **시험·촬영 중 config 레포 머지 하나면 상한이 날아간다.**
⇒ **해소**: `maxReplicas: 8` 을 config 레포 EKS 오버레이에 커밋했다(account·recipe).
   스크립트의 HPA patch 는 이제 안전망일 뿐이고, git 값이 정본이다.

**② 500 VU 로는 애초에 수요가 부족했다.** 고원 실측:

| | 4 replica 일 때 | HPA 가 실제로 원한 수 |
|---|---|---|
| account | 41% / 목표 100% | **1.6** |
| recipe | 75% / 목표 105% | **2.9** |

4개까지 간 것은 램프업 스파이크였고 정상상태 수요는 3개 미만이었다.
⇒ **Karpenter 를 보려면 `VUS=1500`** (수요 약 3배 → recipe 8.7·account 4.9 → 신규 5파드 ≈ 3,200m).

### 🔴 3.2 Karpenter 단독 실증 (같은 날)

부하와 분리해 더미 파드(cpu 3000m) 하나로 먼저 증명했다 — **뜬다, 51초.**

```
+0s   파드 생성 → Pending      +2s   NodeClaim 생성
+20s  노드 등록                +48s  파드 Scheduled      +51s  Running
```

⚠️ 이때 **파드 1개에 노드 3대**가 떴다(지명 20초 < 노드 기동 45초).
`NodePool.spec.template.spec.startupTaints` 누락이 원인이고 **적용 후 3 → 1 대로 해소**했다.
상세 = 앱 레포 `infra/ansible/roles/eks_karpenter/templates/nodepool.yaml.j2` 주석.
🔴 이걸 안 고치면 과발주가 NodePool 상한(cpu 16)을 먼저 먹어 **정작 필요한 파드가 Pending 에 갇힌다.**

---

## 3.5 🔴 로그인 스탬피드 — setup 으로 뺐다 (2026-08-17)

로그인은 `account` 고정창 스로틀에 걸린다: **IP당 100/분** · 이메일당 10/분(파드별 in-memory).
k6 는 **단일 IP** 라 램프업의 로그인 몰림이 그대로 429 가 된다.
1회차 실측: 로그인 762건 중 **357건 429**, 토큰 못 받은 VU 가 `/api/users/budget` 을
무인증 호출해 **budget 4xx 132건**까지 파생.

⚠️ **서비스 결함이 아니다** — 실사용자 500명은 IP 도 500개다. 발생기가 단일 IP 라서 생기는
**계측 인공물**이다.

🔴 1500 VU 에서는 이 인공물이 **시험을 죽인다**: 램프 1분에 로그인 1500건 → 대부분 429 →
그 VU 들이 계속 4xx 를 만들어 `http_req_failed` 가 10% 를 넘고 **abortOnFail 이 중단**시킨다.

⇒ `stage1_journey.js` 의 **`setup()` 에서 토큰을 페이스 맞춰(기본 120/분) 미리 받는다.**
`NUSERS=200` 기준 약 **100초**가 시험 시작 전에 추가로 걸린다(`setupTimeout: 10m`).

**앱에 `LOGIN_RATE_PER_IP=0` 을 임시 주입하는 길은 기각했다** — account 는 Blue-Green
(`autoPromotionEnabled: false` + `prePromotionAnalysis`)이라 env 한 줄이 **수동 승격이 필요한
새 리비전**을 만들고, 그 분석 게이트가 읽는 Prometheus 를 부하시험이 바로 흔든다.
시험 전후로 BG 사이클을 두 번 도는 셈이라 **운영 설정은 건드리지 않는다.**

---

## 3.6 🔴 3회차 — 진짜 벽은 HPA 도 부하량도 아닌 **ResourceQuota** 였다 (2026-08-17)

§3.1 을 다 고치고 1500 VU 로 올렸는데도 **NodeClaim 이 0** 이었다. 원인은 `app` ns 의
`mp-app-quota`(`requests.memory: 6Gi`)였고, 평시에 이미 **84%** 가 차 있었다.

```
Error creating: pods "mp-account-…" is forbidden: exceeded quota: mp-app-quota,
  requested: requests.memory=384Mi, used: 6080Mi, limited: 6Gi
```

🔴 **쿼터 초과는 `Pending` 이 아니라 admission 거부다** — 파드가 아예 안 만들어진다
(`ReplicaSet: FailedCreate`). Pending 파드가 없으면 **Karpenter 는 반응할 대상이 없다.**
HPA 는 "늘렸다"고 이벤트를 남기고 실제 파드는 0 이라 **조용히 죽는다.** BG green 세트도 같은 벽에 막힌다.

⇒ **원칙: 쿼터는 노드 용량보다 느슨해야 한다.** 부족분이 `Pending` 으로 드러나야 오토스케일러가
신호를 받는다. 쿼터의 일은 용량 계획이 아니라 **폭주 차단**이다.
값·산출 = config 레포 `platform/cluster-baseline/overlays/eks/quotas.yaml` §"② 검산 완료"
(6→18Gi · 6→16). 침묵 자체는 값을 올려도 안 없어지므로 **감시를 같이 넣었다**
(`monitoring/overlays/eks/rules-quota.yaml` — 기본 `KubeQuotaAlmostFull` 은 `for: 15m`·`info` 라
9.5분짜리 이 사고를 못 잡는다. 그리고 `KubeQuotaExceeded` 는 **원리상 안 뜬다**).

**3회차 결과** — 바꾼 것은 쿼터 하나뿐인데:

| | 2회차 (6Gi) | 3회차 (18Gi) |
|---|---|---|
| 처리량 | 930 req/s | **1,243 req/s** |
| p95 | 1.09s | **711ms** |
| 실패 | 0.38% | 0.19% |
| Karpenter | **0대** | **5대** |

남은 실패는 **전부 price** 였다(→ §3.7).

## 3.7 🔴 4회차 — price 캐시 스탬피드 (2026-08-17 · 최종)

3회차의 실패 1,783건 · `max 45.19s` 는 용량 부족이 아니라 **동시성 결함**이었다.
핫딜은 캐시 키가 **하나**(`price:hotdeals:20`)고 TTL 120초, 미스 1.36초 · 히트 34ms.
초당 526건 × 1.36초 ⇒ 만료 순간 **약 715건이 같은 쿼리를 동시 실행** → PG 커넥션 고갈.

🔴 **HPA 로는 못 고친다 — 오히려 나빠진다.** replica 를 늘리면 만료 순간 PG 를 때리는 주체가
그 배수만큼 늘어난다. ⇒ **stale-while-revalidate + single-flight** 로 고쳤다(앱 레포 MR !70).

**4회차 결과** (1500 VU · 고원 8분 · 3회차와 같은 조건, price 코드만 다름):

| | 3회차 | 4회차 |
|---|---|---|
| 처리량 | 1,243 req/s | **1,346 req/s** |
| p95 / p99 | 711ms / 1.43s | **655ms / 1.26s** |
| 총 요청 | — | 979,220 |
| **실패** | 0.19% | **0.0012%** (12건) |
| **hotdeals 실패** | **1,783건** | **2건** |
| hotdeals p95 | — | 589ms |
| Karpenter | 5대 | **6대** (2→8 노드) |
| 로그인 p95 | — | **0s** (§3.5 setup 효과) |

같은 고원에서 **Blue-Green 승격도 함께** 돌렸다 — green 6/6 · 게이트 27초 통과 ·
승격 **1.80초** · 공개 `/api/auth/health` 의 `release` 가 `68cdcfc688 → 5fc5969574` 로 바뀜.

## 3.8 ⚠️ 시험 직후 5분간 공개 엔드포인트가 **403** 이다

WAF 레이트룰을 2000/5분/IP 로 원복하는 순간, **직전 5분 창에 시험 트래픽이 남아 있어**
같은 IP 의 정상 요청까지 차단된다. 실측 2026-08-17: 18:40:44 → 18:45:32(**약 5분**) 뒤 자동 회복.
🔴 **고장이 아니다.** 시험 직후 데모·촬영을 이어서 하려면 5분을 기다리거나 다른 IP 에서 접속한다.

---

## 4. 전제 (스크립트가 자동 확인)

- 엔드포인트 4종 200: `/api/auth/login` · `/api/recipes?q=` · `/api/prices/hotdeals` · `/api/users/budget`
- `loadtest-pool-*` 유저 = **AWS PG 에 200명 실재**(`account.app_user`). 그래서 `NUSERS` 기본값이 **200** 이다.
  🔴 온프렘 기본값 500 을 그대로 쓰면 없는 계정으로 로그인해 실패한다.
- k6 = `/mnt/c/temp/k6.exe` (Windows 실행파일 · WSL interop)
- terraform = `wt-team` 워크트리(main·init 됨). 다른 곳이면 `TF_DIR=...` 로 지정.

---

## 5. 예상 비용

m7g.xlarge on-demand $0.2006/h. 최대 4대 추가로 30분 → **약 $0.40**. WAF 요청과 ALB LCU 를
더해도 **$1 미만**. 🟢 비용은 이 시험의 제약이 아니다.

---

## 6. 시험 중 볼 것

```bash
watch -n5 'kubectl get nodes; kubectl -n app get hpa; kubectl get nodeclaims'
tail -f /tmp/mp-loadtest-scale.log     # 스크립트가 20초마다 노드·replica 를 찍는다
```

알림은 **끄지 않는다** — 이번 시험은 2026-08-17 에 고친 `-preview` 2중 계상 수정이
실부하에서 맞게 도는지 확인할 첫 기회이기도 하다. Slack 에 뜨는 것을 그대로 본다.

---

## 7. 끝난 뒤

- HPA·WAF 는 스크립트가 원복(위 §2 확인 명령으로 검산)
- Karpenter 노드는 `consolidationPolicy: WhenEmpty` + `consolidateAfter: 5m` 이라 **자동 축소**
- 결과는 `loadtest/stage1_results.md` 규약대로 기록
