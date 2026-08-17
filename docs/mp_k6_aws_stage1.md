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
