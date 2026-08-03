# 카나리 배포 런북 — Argo Rollouts (`account`·`recipe`)

> **이 문서를 펴는 순간** = Slack `#alerts-critical` 에 `MpRolloutAborted` 가 떴을 때.
> 다른 진입점은 §7 표 참조. 배포전략 결정·근거는 [`adr/0001-deployment-strategy-canary.md`](adr/0001-deployment-strategy-canary.md).

---

## 0. 30초 요약 — 겁먹지 말 것

**카나리 중단은 장애가 아니다.**

- 트래픽은 **이미 stable(구버전) 100%** 로 돌아가 있다. 유저는 영향 없다.
- 멈춘 것은 **배포**지 서비스가 아니다.
- 그래서 **급하게 되살릴 이유가 없다.** 원인을 읽고 판단하는 게 먼저다.

> 실제로 2026-08-03 에 recipe 가 50% 에서 중단됐지만 `/api/recipes` 는 내내 200 이었다.

🔴 **하지 말 것: 이유를 모른 채 `retry`.** 진짜 회귀였다면 나쁜 버전을 다시 밀어넣는 것이다.

---

## 1. 우리 카나리는 이렇게 돈다 (정상 4~7분)

```
setWeight 20 → pause 30s → 분석 ①  →  setWeight 50 → pause 30s → 분석 ②  →  setWeight 100 → promote
```

- 분석 = `<svc>-canary-analysis` (5xx 비율 `< 0.05` · p95 `< 2000ms`)
- 분석이 실패하면 **자동 abort → stable 100% 로 롤백**. 사람이 누를 것이 없다.
- 대상은 **`account`·`recipe` 둘뿐**. 나머지 7개 서비스는 롤링이라 이 문서와 무관하다.

---

## 2. 준비 — 명령을 어디서 치나

```bash
ssh ubuntu@192.168.0.17            # k8s-master, 플러그인이 깔려 있는 공용 지점
sudo -i                             # 아래 명령은 admin.conf 기준
export KUBECONFIG=/etc/kubernetes/admin.conf
```

**내 노트북에 깔고 싶다면** (선택):
```bash
curl -LO https://github.com/argoproj/argo-rollouts/releases/download/v1.9.1/kubectl-argo-rollouts-linux-amd64
sudo install -m 0755 kubectl-argo-rollouts-linux-amd64 /usr/local/bin/kubectl-argo-rollouts
kubectl argo rollouts version        # v1.9.1 이어야 한다(컨트롤러와 같은 버전)
```
> 🔴 버전은 **컨트롤러와 맞춘다.** master 쪽은 Ansible 이 관리한다 —
> `infra/ansible/roles/k8s_rollouts_cli`(`--tags rollouts_cli`).

---

## 3. 즉시 판단 — 유저 영향이 있나 (30초)

```bash
kubectl argo rollouts list rollouts -n app
```

```
NAME        STRATEGY   STATUS        STEP  SET-WEIGHT  READY  DESIRED  UP-TO-DATE  AVAILABLE
mp-recipe   Canary     Degraded      4/7   50          2/2    2        2           2
```

| 볼 것 | 정상 | 이상 |
|---|---|---|
| `READY` | `2/2` — stable 파드가 살아 있다 | `0/2` 면 **서비스 장애**다. 이 문서 말고 일반 장애대응으로 |
| `STATUS` | `Degraded`(=중단) 여도 유저는 무사 | — |

확인 사살:
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://app.mealbong.cloud/api/recipes    # 200 이면 정상
```

**유저 영향이 있으면** → 이 런북을 덮고 장애대응으로. **없으면** → §4 로.

---

## 4. 진단 — 갈림길 하나를 정한다

모든 카나리 중단은 결국 **둘 중 하나**다. 이 절의 목적은 그 판정뿐이다.

```
        ┌─ 진짜 회귀   → §5-A  (retry 금지. 코드 고쳐서 새 버전)
중단 ───┤
        └─ 분석 오탐   → §5-B  (retry + 분석 고치기)
```

### 4-1. 어느 지표가 왜 실패했나 ← **핵심**

```bash
kubectl -n app get analysisrun --sort-by=.metadata.creationTimestamp | tail -3
kubectl -n app get analysisrun <이름> -o yaml | grep -A25 "metricResults:"
```

**측정값(`measurements[].value`)이 판정을 결정한다:**

| 측정값 | 뜻 | 가지 |
|---|---|---|
| `[0.31]` 같은 **실제 숫자**가 임계 초과 | 진짜로 나빴다 | **§5-A 회귀** |
| `[NaN]` | 시리즈는 있는데 관측이 0 = **무트래픽** | **§5-B 오탐** |
| `[]` (빈 벡터) | 시리즈 자체가 없음 = 무트래픽 | **§5-B 오탐** |

> 🔴 `[NaN]` 은 실제로 우리를 물었다(2026-08-03). 그래서 쿼리에 `(<expr> >= 0) or vector(0)`
> 가드를 넣었다(ADR §6.5). **또 `[NaN]` 이 보이면 가드가 빠진 지표가 있다는 뜻**이니
> 해당 AnalysisTemplate 을 고쳐야 한다.

### 4-2. 애매하면 — 판정 못 하겠을 때

**애매하면 오탐으로 취급하지 말고 회귀로 취급한다**(안전한 쪽). 즉 retry 하지 말고,
카나리 파드 로그를 직접 본다:

```bash
kubectl -n app logs -l app=<svc>,rollouts-pod-template-hash=<카나리해시> --tail=100
kubectl argo rollouts get rollout mp-<svc> -n app        # 해시·리비전 확인
```

---

## 5. 조치

### 5-A. 진짜 회귀 — 되살리지 않는다

1. **그대로 둔다.** stable 이 서빙 중이라 급하지 않다.
2. 코드를 고쳐 새 `:sha` 를 배포한다(정상 CI/CD 경로). 새 리비전이 들어오면 카나리가 다시 돈다.
3. 급히 옛 버전으로 못 박아야 하면:
   ```bash
   kubectl argo rollouts undo rollout mp-<svc> -n app          # 직전 리비전으로
   kubectl argo rollouts undo rollout mp-<svc> -n app --to-revision=3
   ```
   > ⚠️ `undo` 는 **라이브만** 되돌린다. config 레포(git)는 그대로라 다음 sync 에 되돌아온다.
   > 진짜 롤백은 **config 레포에서 `:sha` 를 되돌리는 것**이다. undo 는 응급 조치다.

### 5-B. 오탐 — retry

```bash
kubectl argo rollouts retry rollout mp-<svc> -n app
kubectl argo rollouts get rollout mp-<svc> -n app --watch     # 20→50→100 진행 확인
```

**그리고 반드시 원인을 없앤다** — 안 고치면 다음 배포에서 똑같이 막힌다.
무트래픽 오탐이면 해당 `AnalysisTemplate` 의 쿼리에 NaN 가드가 있는지 확인
(`config` 레포 `services/<svc>/base/analysistemplate.yaml`).

### 5-C. 최후수단 — 안전망을 끄고 밀어붙이기

🔴 **분석을 건너뛴다. 이걸 누르면 카나리를 쓰는 의미가 사라진다.** 장애 중 핫픽스처럼
"이 버전이 옳다는 확신"이 있을 때만.

```bash
kubectl argo rollouts promote mp-<svc> -n app          # 현재 스텝만 건너뜀
kubectl argo rollouts promote mp-<svc> -n app --full   # 남은 스텝·분석 전부 건너뜀
```

### 5-D. 진행 중인 카나리를 지금 세우기

```bash
kubectl argo rollouts abort rollout mp-<svc> -n app    # stable 100% 로 즉시 복귀
```

---

## 6. 사후 — 두 줄이면 된다

1. **왜 멈췄나 / 회귀였나 오탐이었나** 를 PR 이나 이슈에 남긴다.
2. 오탐이었다면 **분석을 고친 PR 링크**를 같이 남긴다. 안 고치면 늑대 소년이 된다.

> 임계값이 실측 대비 너무 널널하면(예: p95 실측 4.6ms / 임계 2000ms) 조정 후보다 —
> 다만 조정은 **실측 데이터가 쌓인 뒤**에 한다(ADR §6.7).

---

## 7. 다른 알림으로 들어온 경우

| 알림 | 뜻 | 첫 명령 |
|---|---|---|
| `MpRolloutAborted` | 카나리 거부 — **이 문서의 주 진입점** | §3 → §4 |
| `MpRolloutsControllerDown` | 컨트롤러 전멸 = **새 배포 전면 정지**(도는 트래픽은 무사) | `kubectl -n argo-rollouts get pod` · §8 |
| `MpRolloutError` | 컨트롤러가 Rollout 을 진행 못 시킴(분석실패와 다름) | `kubectl argo rollouts get rollout mp-<svc> -n app` |
| `MpRolloutStuck` | 30분 정체 — 대개 카나리 파드가 안 뜬다 | `kubectl -n app get pods -l app=<svc>` (ImagePullBackOff·스케줄 실패) |

---

## 8. 알려진 함정 (전부 실측으로 물린 것)

| 함정 | 증상 | 대응 |
|---|---|---|
| **컨트롤러가 플러그인 없이는 기동하지 않는다** | `Init:ErrImagePull` → 배포 전면 정지 | Harbor 풀 시크릿 확인(`kubectl -n argo-rollouts get secret harbor`). ADR §6.2 |
| **`gateway` 앱은 수동 sync** | Rollout 이 `backendRef was not found` 로 무한재시도 | `kubectl patch application -n argocd gateway --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'` |
| **`ignoreDifferences` 가 미적용을 `Synced` 로 위장** | 앱은 Synced 인데 HTTPRoute 에 canary backendRef 가 없다 | 앱 상태 말고 **실물**을 본다: `kubectl -n app get httproute mp-<svc>-route -o yaml` |
| **무트래픽 `NaN` 오탐** | 멀쩡한 배포가 롤백 | §4-1. 쿼리에 `(<expr> >= 0) or vector(0)` |
| **Deployment→Rollout 전환 시 구 Deployment 가 안 지워진다** | 파드가 두 벌 | prune:false 라 수동 삭제. 삭제 전 `svc` 셀렉터에 `rollouts-pod-template-hash` 주입 확인 |

---

## 9. 참조

| 무엇 | 어디 |
|---|---|
| 배포전략 결정·근거·구현방침 | [`adr/0001-deployment-strategy-canary.md`](adr/0001-deployment-strategy-canary.md) |
| Rollout·분석 매니페스트 | config 레포 `services/{account,recipe}/base/` |
| 컨트롤러 설치 | config 레포 `platform/argocd/rollouts.yaml` |
| CLI 설치(master) | `infra/ansible/roles/k8s_rollouts_cli` (`--tags rollouts_cli`) |
| 알림 규칙 | config 레포 `monitoring/rules-rollouts.yaml` |
