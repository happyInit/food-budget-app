# mp_config_merge_plan.md — config 레포 EKS 이관 브랜치 8개 정리·머지 계획

> 신설 2026-08-10. 대상 = `happyInit/mealplanning-config` 에 쌓인 미머지 브랜치 8개(+ 이 작업이 만든 1개).
> 이 문서는 **머지 계획**이다. 설계 정본은 config 레포 `SITES.md`(§0-1 구조 · §0-4 뿌리 IaC),
> 이관 체크리스트 정본은 `docs/mp_aws_prep_checklist.md`.
>
> 🔴 **이 작업에서 머지는 하지 않았다.** 검증 · 브랜치 · PR 생성까지가 범위다 —
> config main 은 라이브고(머지 = 즉시 반영), 앱 레포는 PR 리뷰 필수다.

## 0. 요약

| 항목 | 결과 |
|---|---|
| 재검증 대상 | 브랜치 8개 |
| 현재 `origin/main` 기준 rebase | **8/8 깨끗** (충돌 0) |
| **온프렘 렌더 불변** | **8/8 통과** — 트랙 32개 전부, 의도된 예외 2건 외 차이 0 |
| 브랜치 간 공유 파일 | 18개 (충돌 16 · 단순 병존 2) |
| 그중 **온프렘에 닿는 것** | **1개** (`platform/es/overlays/onprem/kustomization.yaml`) |
| 0-4 컷오버 1단계 | ✅ **머지 완료** (config #146, 2026-08-10 · 1~3 단계가 함께 들어감) — 라이브 무사고 실증 §4.2b |
| 컷오버 2단계 앱 레포 준비 | PR 3개로 분할 완료 — #579 · #581 · #582(draft) |
| 잔여 6개 브랜치 | ✅ **충돌 21건 해결 + 스택 재정렬 완료**(§4.2c) — 순서대로 **전부 fast-forward** · 온프렘 차이 **0** |

**한 줄 결론** — 8개 전부 온프렘 무영향이 증명됐고, 브랜치 간 충돌은 **한 곳만 빼고 전부 `overlays/eks/`
안**이다. 즉 머지 순서를 잘못 잡아도 깨지는 것은 아직 아무도 안 쓰는 EKS 오버레이지, 라이브가 아니다.

---

## 1. 브랜치 8개의 실제 모양 — 선형 스택이다

전수 확인 결과, 8개는 독립 브랜치가 아니라 **공통 밑동 3커밋을 공유하는 선형 스택**이다.

```
origin/main (dccf3f1)
  └─ 8764226  0-1  전 트랙 base/ + overlays/{onprem,eks} 골격      ← feat/eks-overlay-skeleton
      └─ af9aeef  0-4  bootstrap/argocd/ 신설(뿌리 2 + AppProject 4)
          └─ d482451  0-4  Ansible 변경 명세 문서                   ← feat/argocd-roots-iac
              ├─ 1780da6  L1  0-5·0-6·0-7·0-27                      ← feat/eks-workload-spec
              ├─ 69ddb27  L2  0-8·0-8c                              ← feat/eks-storage
              ├─ ab23567  L3  0-17·0-18                             ← feat/eks-netpol
              ├─ 33aacd6  L4  0-2·0-16                              ← feat/eks-eso-ssm
              ├─ 8fb0c38  L5  0-3c                                  ← feat/eks-observability
              ├─ ac3f30d  L7  0-9·0-10·1-31                         ← feat/eks-registry-validate
              └─ 31e97a0  0-4 컷오버 1단계 (이 작업)                ← feat/argocd-roots-cutover-1 🆕
```

이 사실이 계획 전체를 단순하게 만든다:

- **0-1 과 0-4 는 "머지 순서를 정할 대상"이 아니라 나머지 7개의 조상이다.** 순서를 고민할 것은
  잎 6개(L1·L2·L3·L4·L5·L7)뿐이고, 그 6개는 서로 **커밋 1개씩**이다.
- `feat/argocd-roots-iac` 를 머지하면 0-1 이 자동으로 따라 들어온다. 같은 이유로
  `feat/argocd-roots-cutover-1` 하나를 머지하면 0-1 + 0-4 + 컷오버 1단계가 한꺼번에 들어온다.

**브랜치 규모** (main 대비 3-dot diff · 대부분이 0-1 의 골격 191파일이다)

| 브랜치 | 변경 파일 | 잎 커밋이 실제로 건드리는 파일 |
|---|---:|---:|
| `feat/eks-overlay-skeleton` (0-1) | 191 | 191 |
| `feat/argocd-roots-iac` (0-4) | 197 | 8 |
| `feat/eks-workload-spec` (L1) | 202 | 12 |
| `feat/eks-storage` (L2) | 199 | 15 |
| `feat/eks-netpol` (L3) | 208 | 25 |
| `feat/eks-eso-ssm` (L4) | 214 | 27 |
| `feat/eks-observability` (L5) | 198 | 5 |
| `feat/eks-registry-validate` (L7) | 199 | 11 |

---

## 2. A. 8개 재검증 — 현재 main 기준

### 2.1 rebase — 8/8 깨끗

`git rebase --onto origin/main <fork-point>` 전건 성공, 충돌 파일 0.

이유는 단순하다. 포크 이후 main 이 움직인 것은 **커밋 1개뿐**이고
(`dccf3f1 ci(cd): mealplan to ffd5960e989b`), 그 커밋이 바꾼 파일은
`services/mealplan/overlays/onprem/kustomization.yaml` 의 이미지 태그 한 줄이다.
8개 브랜치 중 그 파일을 건드리는 것은 없다.

> ⚠️ 대신 **Jenkins 가 계속 이 파일들에 `:sha` 를 커밋한다**(CD 인계 지점). 머지가 늦어질수록
> 재검증이 낡는다 — 아래 §4 순서대로 빠르게 태우는 것이 이 계획의 실질적인 이유 중 하나다.

### 2.2 온프렘 렌더 불변 — 8/8 통과 ✅

**검증 방법** — "ArgoCD 가 실제로 무엇을 적용하는가"를 브랜치별로 재구성해 비교했다.

1. `argocd/applications/*.yaml` · `platform/argocd/*.yaml` 에서 **이 레포를 소스로 쓰는 child 32개**를
   뽑아 각자의 `spec.source.path` 를 읽는다. (나머지 12개는 Helm 리포지터리 소스라 렌더 대상이 아니다.)
2. 그 경로를 ArgoCD 와 같은 방식으로 렌더한다 — `kustomization.yaml` 이 있으면 `kubectl kustomize`,
   없으면 directory 모드(`recurse`·`include` 반영)로 `*.yaml` 을 편다.
   🔴 **경로를 하드코딩하지 않은 것이 핵심**이다. 0-1 이 `source.path` 를 `<트랙>` →
   `<트랙>/overlays/onprem` 으로 바꾸므로, Application 에서 경로를 읽어야 "같은 것을 다른 자리에서
   읽고 있는가"를 검사하게 된다.
3. 문서를 `(apiVersion, kind, namespace, name)` 로 정렬하고 키 정렬 JSON 으로 덤프해 main 과 비교.

**결과** — 8개 브랜치 전부, 트랙 32개 중 **차이가 난 트랙은 2개**이고 그 2개는
**각각 1줄**, 내용은 알림 `annotations.description` 안의 **런북 경로 문자열**이다.

| 트랙 | 오브젝트 | 바뀐 것 |
|---|---|---|
| `monitoring` | `PrometheusRule/mp-workload-spread` | `monitoring/rules.yaml` → `monitoring/base/rules.yaml` |
| `pipelines` | `PrometheusRule/mp-pipeline` | `pipelines/kustomization.yaml` → `pipelines/base/kustomization.yaml` |

이 2건은 **0-1 이 문서화한 의도된 예외**다(`SITES.md` §검증 방법). 파일이 실제로 옮겨갔으므로
런북 경로도 같이 고친 것이고, 알림의 신원은 `alertname`+라벨이라 **울리는 조건도 라우팅도 바뀌지 않는다.**
8개 전부가 0-1 을 조상으로 갖기 때문에 이 2건이 8개 모두에서 동일하게 나타난다.

> 즉 **"diff 가 0 이 아닌 브랜치"는 없다.** 0 이 아닌 곳은 8개 공통의 이 2줄뿐이고, 브랜치 고유의
> 온프렘 변화는 **어느 브랜치에도 없다.**

### 2.3 렌더된 것이 라이브와 같은 집합인가 (교차검증)

렌더 결과의 child 44개 이름 집합 = 라이브 Application 46개 − 뿌리 2개, **완전 일치**
(2026-08-10 실측, 읽기 전용 조회). 렌더 하네스가 빠뜨린 트랙이 없다는 뜻이다.

---

## 3. B. 브랜치 간 충돌 지도

잎 6개가 건드리는 파일 95개 중 **2개 이상이 공유하는 파일 = 18개**.
`git merge-tree` 로 15개 쌍을 전수 3-way 머지해 충돌/병존을 판정했다.

### 3.1 쌍별 충돌 행렬

|  | L1 | L2 | L3 | L4 | L5 | L7 |
|---|---|---|---|---|---|---|
| **L1** workload | — | ⚠️ 4 | ✅ | ⚠️ 7 | ✅ | ⚠️ 2 |
| **L2** storage | ⚠️ 4 | — | ✅ | ⚠️ 3 | ✅ | ⚠️ 2 |
| **L3** netpol | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| **L4** eso-ssm | ⚠️ 7 | ⚠️ 3 | ✅ | — | ✅ | ⚠️ 9 |
| **L5** observability | ✅ | ✅ | ✅ | ✅ | — | ✅ |
| **L7** registry | ⚠️ 2 | ⚠️ 2 | ✅ | ⚠️ 9 | ✅ | — |

**L3·L5 는 아무와도 안 부딪힌다.** 나머지 {L1, L2, L4, L7} 이 완전 그래프(4-clique)를 이룬다.

### 3.2 파일 → 브랜치 → 판정

| 파일 | 건드리는 브랜치 | 판정 |
|---|---|---|
| `platform/es/overlays/eks/kustomization.yaml` | L1 L2 L4 L7 | ⚠️ 충돌 (전 쌍) |
| `platform/pg/overlays/eks/kustomization.yaml` | L1 L2 L4 | ⚠️ 충돌 |
| `pipelines/overlays/eks/kustomization.yaml` | L2 L4 L7 | ⚠️ 충돌 |
| `ingress/overlays/eks/kustomization.yaml` | L1 L4 L7 | ⚠️ 충돌 |
| `SITES.md` | L1 L4 L7 | ⚠️ L4×L7 만 충돌 · L1 쌍은 자동 병합 |
| `common/overlays/eks/kustomization.yaml` | L4 L7 | ⚠️ 충돌 |
| `platform/kafka/overlays/eks/kustomization.yaml` | L1 L2 | ⚠️ 충돌 |
| `platform/pgsync/overlays/eks/kustomization.yaml` | L4 L7 | ⚠️ 충돌 |
| `platform/rollouts/overlays/eks/kustomization.yaml` | L4 L7 | ⚠️ 충돌 |
| `services/account/overlays/eks/kustomization.yaml` | L1 L4 | ⚠️ 충돌 |
| `services/mealplan/overlays/eks/kustomization.yaml` | L1 L4 | ⚠️ 충돌 |
| `services/price/overlays/eks/kustomization.yaml` | L1 L4 | ⚠️ 충돌 |
| `services/recipe/overlays/eks/kustomization.yaml` | L1 L4 | ⚠️ 충돌 |
| `services/video/overlays/eks/kustomization.yaml` | L4 L7 | ⚠️ 충돌 |
| `scripts/validate.py` | L4 L7 | ⚠️ 충돌 |
| 🔴 `platform/es/overlays/onprem/kustomization.yaml` | L1 L2 | ⚠️ **충돌 — 유일한 온프렘 파일** |
| `platform/es/base/elasticsearch.yaml` | L1 L2 | ✅ 단순 병존 (자동 병합) |
| `services/ranking-serving/overlays/eks/kustomization.yaml` | L2 L4 | ✅ 단순 병존 (자동 병합) |

### 3.3 충돌의 성질 — 전부 **합집합(union)** 이다

충돌 hunk 를 전수로 읽었다. **값이 서로 다른 곳은 한 군데도 없다.** 두 레인이 같은 파일의
**다른 필드**를 각자 얹으면서 (a) 머리말 체크리스트 주석과 (b) 인접한 `patches:` 블록이
텍스트로 겹쳤을 뿐이다. 예 — `platform/es/overlays/onprem`:

- L1: `…/nodeSets/{0,1}/podTemplate/spec/nodeSelector` 를 add (0-5)
- L2: `…/nodeSets/{0,1}/volumeClaimTemplates/0/spec/storageClassName` 를 add (0-8)

→ 해결 = **두 op 목록을 이어 붙이는 것**. 실제로 그렇게 풀어 검증했다(§4.3).

🔴 **다만 방언이 갈리는 곳이 둘 있다.** `platform/kafka/overlays/eks` · `platform/pg/overlays/eks` 에서
L1 은 **JSON6902**(`- op: replace …`)를, L2 는 **전략적/merge 패치**(`apiVersion/kind/spec` 매핑)를 쓴다.
kustomize 의 한 `patch:` 문자열은 **둘 중 하나여야 한다 — 섞을 수 없다.**
따라서 이 두 파일의 해결은 "한 블록으로 합치기"가 아니라 **같은 target 을 가리키는
`patches:` 항목을 2개로 나누는 것**이다. 기계적으로 이어 붙이면 렌더가 죽는다.

---

## 4. C. 머지 순서

### 4.1 순서

| # | 브랜치 | 예상 충돌 | 여기까지 머지했을 때 온프렘이 안전한 이유 |
|---:|---|---:|---|
| 1 | ✅ `feat/eks-overlay-skeleton` (0-1) | 0 | `source.path` 만 `<트랙>/overlays/onprem` 으로 옮겼고 오버레이가 **순수 통과**라 렌더가 같다(예외 = 런북 문자열 2건). |
| 2 | ✅ `feat/argocd-roots-iac` (0-4) | 0 | `bootstrap/argocd/` **신설뿐**. 두 뿌리의 감시 범위 밖이라 ArgoCD 가 읽지 않는다. |
| 3 | ✅ `feat/argocd-roots-cutover-1` | 0 | 뿌리 정의를 `base/overlays` 로 **복사만** 한다. 옛 경로 무변경 + 새 경로는 두 뿌리의 탐색 범위 밖 = 무생물(§5). |
| 4 | `feat/eks-netpol` (L3) | 0 | 변경이 전부 `overlays/eks/`. 온프렘 렌더 무변화. |
| 5 | `feat/eks-observability` (L5) | 0 | 물리계층 룰을 **온프렘 오버레이로 내리고** eks 에서 뺀다 — 온프렘 렌더는 그대로. |
| 6 | `feat/eks-workload-spec` (L1) | 0 | base 에서 걷어낸 nodeSelector·TSC 를 `overlays/onprem` 이 **같은 값으로 되돌려 얹는다**. CPU 재조정은 eks 전용. |
| 7 | `feat/eks-storage` (L2) | **4** | 6번과 같은 구조(SC 를 base→onprem 으로). 충돌은 union — 해결 후 렌더 재검증 필수. |
| 8 | `feat/eks-eso-ssm` (L4) | **8** | 충돌이 전부 `overlays/eks/`. 온프렘 ESO 는 K8s provider 그대로. |
| 9 | `feat/eks-registry-validate` (L7) | **9** | 충돌 중 온프렘에 닿는 것 0 (`overlays/eks/` 7 + `SITES.md` + `scripts/validate.py`). |

### 4.2 이 순서인 근거

- **1~3 은 의존성이 강제한다.** 나머지 6개가 전부 0-1·0-4 의 후손이라 다른 순서가 존재하지 않는다.
  3번(컷오버 1단계)을 여기 끼우는 이유는 §6 — Wave B(0-5 잔여 6건·0-8 일부·0-9)가 **이것 없이는
  손댈 수단이 0** 이기 때문이다. 3번은 2번을 포함하므로 **2+3 을 한 PR 로 합쳐도 된다.**
- **4~5 를 먼저 태운다.** L3·L5 는 누구와도 안 부딪힌다(§3.1). 충돌 0 인 것부터 빼면 대기열이
  줄고, 뒤의 4-clique 를 풀 때 재검증할 표면이 작아진다.
- **6~9 의 내부 순서는 "base 를 얼마나 건드리는가" 순**이다. L1 이 `platform/{es,kafka,pg}/base` 에서
  값을 가장 많이 걷어내므로 먼저 앉히고, L2 가 그 위에 SC 를 더한다(둘의 충돌 4건이 전부 이 관계다).
  L4·L7 은 base 를 거의 안 건드리고 eks 오버레이에 얹기만 해서 뒤로 뺐다.
- **L7 이 마지막인 추가 이유** — `scripts/validate.py` 를 고친다. 검증기는 **최종 트리를 보고**
  갱신되는 편이 낫다(중간 상태에 맞춰 두면 다음 머지에서 또 고쳐야 한다).

### 4.2b 🔴 1~3 머지 실행 결과 (2026-08-10) — squash 였고, 그래서 재정렬이 필요했다

**1~3 은 config PR #146 하나로 한꺼번에 들어갔다**(스택이라 cutover-1 이 0-1·0-4 를 포함한다 — §1).

#### 라이브 실측 — 예측대로였다

| 확인 항목 | 결과 |
|---|---|
| `mealplanning-root` 관리 child | **23** (프룬 0) |
| `platform-root` 관리 child | **21** (새 `platform/argocd/base/` 21개를 **안 집었다**) |
| Application 46개 sync | 45 Synced / **1 OutOfSync** = `monitoring` |
| `monitoring` 의 OutOfSync 대상 | `PrometheusRule/mp-workload-spread` **하나** = §2.2 의 런북 문자열 1줄 |
| `pipelines` Degraded | 머지 **11시간 전**부터(`mp-poller-kurly` 실패) — 무관 |

- `platform-root` 가 21 을 유지한 것이 §5.3 의 안전 논거(`recurse` 없음 = false → 하위 미탐색)에
  대한 **실증**이다. 읽혔다면 42가 되거나 `kustomization.yaml` 파싱 실패로 sync 가 깨졌을 것이다.
- `monitoring` 은 **manual sync** 앱이라 자동 반영이 안 된 것뿐이다. 해소:
  `kubectl patch application -n argocd monitoring --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'`

#### 🔴 squash 머지 → 남은 6개가 전부 충돌하게 됐다

PR #146 이 **squash 로 머지**됐다(`5fb982a` 단일 커밋). 내용은 전부 들어갔지만 스택의 원래 커밋
(`8764226` 0-1 · `af9aeef`/`d482451` 0-4)이 **main 의 조상이 아니다.** 그래서 남은 6개 브랜치가
아직 그 커밋들을 들고 있고, git 3-way 머지는 양쪽이 같은 파일 191개를 각자 "추가"하는 것으로 봐서
**add/add 충돌**을 낸다 — 실제로 6개 전부가 4~10건씩 충돌로 뒤집혔다(L3·L5 포함).

→ **6개를 새 main 위로 재정렬(rebase)했다.** `git rebase --onto origin/main d482451` 로 이미 머지된
부분을 떨구고 **잎 커밋 하나씩만** 남긴다. 결과:

| 확인 | 결과 |
|---|---|
| rebase | 6/6 깨끗, 각 브랜치 = main + **커밋 1개** |
| 변경분 보존 | 6/6 `git patch-id` **원본과 동일** |
| **온프렘 렌더** | 6/6 **차이 0** — 이제 예외 2건도 main 에 있어서 **문자 그대로 0** |
| 새 main 대비 머지 | 6/6 CLEAN |
| 잎 사이 충돌 지도 | §3.1 과 **동일** (L3·L5 는 무충돌, {L1,L2,L4,L7} clique) |

되돌리기용 원래 tip: `L1 1780da6` · `L2 69ddb27` · `L3 ab23567` · `L4 33aacd6` · `L5 8fb0c38` · `L7 ac3f30d`.

⚠️ **다음 머지도 squash 라면 같은 일이 또 일어난다.** 남은 6개는 서로 독립이라 한 번에 하나씩
머지할 때마다 **나머지를 rebase** 해야 한다. 피하려면 (a) merge commit 방식으로 머지하거나,
(b) 6개를 한 PR 로 묶어 한 번만 squash 한다. **어느 쪽이든 사람 결정이다.**

### 4.2c ✅ 충돌 21건 해결 완료 — 이제 6개가 전부 fast-forward 다 (2026-08-10)

머지 순서(L3 → L5 → L1 → L2 → L4 → L7)대로 **스택으로 재정렬**하고 충돌을 전부 풀어 올렸다.
각 브랜치는 이제 **직전 브랜치 위에 커밋 1개**이고, 순서대로 머지하면 **전건 fast-forward** 다
(리허설 6/6 확인). 즉 **머지하는 사람이 충돌을 만날 일이 없다.**

| 브랜치 | tip | 해결한 충돌 |
|---|---|---:|
| `feat/eks-netpol` (L3) | `b394349` | 0 |
| `feat/eks-observability` (L5) | `9487d18` | 0 |
| `feat/eks-workload-spec` (L1) | `6e5ed88` | 0 |
| `feat/eks-storage` (L2) | `ef795fe` | 4 |
| `feat/eks-eso-ssm` (L4) | `173eec5` | 8 |
| `feat/eks-registry-validate` (L7) | `5f2ac53` | 9 |

**최종 검증** — 6개 전부 머지한 상태에서:

| 항목 | 결과 |
|---|---|
| 온프렘 렌더 (트랙 32) | **차이 0** |
| eks 오버레이 렌더 (35개) | **성공 35 · 실패 0** |
| `python3 scripts/validate.py` | ✅ 통과 (경고 2 = `services/cloudflared` eks 부재[C-5 의도] · kubeconform 미설치) |
| 순서대로 머지 | 6/6 **fast-forward** |

#### 해결 원칙

전부 **union** 이다(값 충돌 0 — §3.3). 다만 세 가지는 기계적 이어붙이기로 풀리지 않는다:

1. **패치 방언이 갈리는 곳** — `platform/{kafka,pg}/overlays/eks` 는 L1 이 JSON6902,
   L2 가 merge 패치다. kustomize 의 한 `patch:` 문자열은 둘 중 하나여야 해서
   **같은 target 을 가리키는 `patches:` 항목 2개**로 나눴다. 건드리는 필드가 안 겹친다
   (TSC·CPU ↔ storage class)라 적용 순서와 무관하다.
   ⚠️ 합치려고 merge 패치를 op 목록으로 옮겨 적지 말 것 — `spec.storage` 가 jbod(리스트)로
   바뀌면 인덱스 경로가 조용히 엉뚱한 곳을 가리킨다.
2. **같은 top-level 키를 양쪽이 추가한 곳** — YAML 은 `patches:`/`images:` 를 두 번 못 쓴다.
   그냥 이어 붙이면 **뒤쪽 키의 항목이 앞쪽 목록에 흡수된다**(patch 항목이 images 항목으로 파싱).
   키 단위로 본문을 모아 한 번씩만 냈다.
3. **블록 스칼라 경계** — `patch: |-` 뒤 op 목록 다음에 주석 블록이 오는 파일에서, 상대편 op 를
   주석 뒤에 붙이면 스칼라 밖으로 나가 **YAML 이 깨진다**(실제로 한 번 걸렸다 — es eks).

#### 🔴 부수 발견 — L7 은 현재 main 기준으로 그대로는 실패했다

L7 이 추가한 `check_registry_split()` 이 **컷오버 1단계가 만든 `platform/argocd/overlays/eks`** 를
보고 Harbor LAN IP 를 잡아냈다(`rollouts` Application 의 `valuesObject` 안 initContainer 이미지).
L7 을 쓴 시점엔 그 디렉터리가 없었으니 저자 잘못이 아니라 **두 레인이 만나서 생긴 것**이다.

→ 그 자리에 **0-9 레지스트리 패치**를 넣어 해소했다(Wave B 15건 중 1건 선반영).
`images:` 트랜스포머로는 못 잡는다 — 컨테이너 spec 이 아니라 Helm `valuesObject` 안이라
기본 fieldSpec 밖이다. 그래서 `op: test` + `op: replace` 의 JSON6902 로 갔다.
test 를 앞에 둔 이유 = base values 구조가 바뀌면 replace 가 **엉뚱한 값을 조용히 덮어쓴다.**

#### 남은 사람 판단

- 위 1번의 `patches:` 2항목 분리 — `platform/kafka/overlays/eks` · `platform/pg/overlays/eks`
  **이 2파일이 리뷰 포인트**다. 나머지는 기계적이다.
- L7 이 `SITES.md` 실무규칙 번호를 6 으로 썼는데 L4 가 이미 6 을 쓰고 있어 **7 로 재번호**했다.
- `platform/argocd/overlays/eks` 의 ECR 값은 `PLACEHOLDER` 다 — 계정 ID 확정 시
  `scripts/sites.yaml` 과 함께 고친다.

### 4.3 이 순서를 실제로 태워서 검증했다 ✅

계획으로 끝내지 않고 **격리된 워크트리에서 1→9 를 순서대로 실제 머지**했다(로컬 전용, 푸시 없음).

- 1→6 (0-1 · 0-4+컷오버1 · L3 · L5 · L1): **충돌 0**. 이 시점 온프렘 렌더 = 런북 2줄 외 차이 0.
- 7 (L2): 충돌 4건. 그중 유일한 온프렘 파일 `platform/es/overlays/onprem` 을 **union 으로 해결**
  (L1 의 nodeSelector op 2개 + L2 의 storageClassName op 2개를 한 목록으로).
  → **재렌더 결과 온프렘 차이 = 런북 2줄 그대로.**
  🔴 이게 이 검증에서 가장 중요한 한 줄이다. L1 과 L2 는 **같은 base 파일**
  (`platform/es/base/elasticsearch.yaml`)에서 각자 다른 필드를 걷어내는데, git 이 그 파일을
  자동 병합한 뒤 **양쪽 오버레이가 둘 다 되돌려 얹어야** 라이브가 유지된다. 그 합성이 실제로
  성립함을 렌더로 확인했다.
- 8~9 (L4 · L7): 충돌 17건, **온프렘에 닿는 것 0** (전부 `overlays/eks/` + `SITES.md` +
  `scripts/validate.py`). eks 쪽 해결은 내용 소유자 판단이라 `--ours` 로 보류하고 진행.
- **전 스택 머지 완료 후 최종 렌더**: 트랙 32개, 차이 나는 트랙 2개, 각 **1줄**(런북 경로).

즉 **"8개를 다 머지해도 온프렘 라이브는 안 움직인다"가 계획이 아니라 실측이다.**

---

## 5. D. 0-4 컷오버 1단계 — 실행 완료

브랜치 **`feat/argocd-roots-cutover-1`** (config 레포, 푸시만·미머지 · `31e97a0`).

### 5.1 무엇을 했나

`SITES.md` §0-4 "컷오버 절차"의 **1단계(복사)** 만 그대로 실행했다.

```
argocd/
  applications/*.yaml   (23)   ← 그대로 둠. 한 글자도 안 건드렸다
  base/*.yaml           (23)   ← 복사 + kustomization.yaml 신설
  overlays/onprem/             ← 순수 통과
  overlays/eks/                ← 순수 통과 + 갈라야 할 것 체크리스트
platform/argocd/
  *.yaml                (21)   ← 그대로 둠
  base/*.yaml           (21)   ← 복사 + kustomization.yaml 신설
  overlays/{onprem,eks}/       ← 위와 같음
```

`bootstrap/argocd/overlays/eks` 가 이미 EKS 뿌리의 `path` 를 `argocd/overlays/eks` ·
`platform/argocd/overlays/eks` 로 적어 두었으므로, 이 커밋이 **그 경로를 실재하게 만든다.**

### 5.2 렌더 불변 증명

| 뿌리 | 옛 경로 (directory 모드) | 새 경로 (kustomize) | 문서 | 신원 집합 | 전 필드 값 |
|---|---|---|---:|---|---|
| `mealplanning-root` | `argocd/applications` (`recurse: true`) | `argocd/overlays/onprem` | 23 = 23 | 동일 | **차이 0** |
| `platform-root` | `platform/argocd` (`include: "*.yaml"`) | `platform/argocd/overlays/onprem` | 21 = 21 | 동일 | **차이 0** |

- 복사한 44개 파일은 원본과 **바이트 단위 동일**(`cmp` 전건 통과).
- 렌더된 child 44개 = 라이브 Application 46개 − 뿌리 2개, **이름 집합 완전 일치**.

🔴 **렌더 텍스트의 바이트 비교는 성립하지 않는다 — 이것만 지시와 다르다.**
kustomize 가 재직렬화하면서 **주석을 버리고 키를 정렬**한다(앱 27,942B → 11,909B ·
플랫폼 64,560B → 25,600B). 파일이 옮겨간 것이 아니라 **directory 모드 → kustomize 모드**로
읽는 방식이 바뀌는 단계라서 텍스트 동일성은 애초에 성립할 수 없다.
`SITES.md` §검증 방법이 이 경우를 미리 규정해 뒀다 — *"디렉터리형 → kustomize 변환처럼 바이트
비교가 성립하지 않는 경우에는 문서를 (apiVersion, kind, namespace, name) 로 정렬하고 키 정렬
JSON 으로 덤프해 비교한다"*. 0-1 이 디렉터리형 트랙 7종에 쓴 것과 **같은 방법**이고,
ArgoCD 도 텍스트가 아니라 파싱된 오브젝트를 비교·적용하므로 판정 기준으로 옳다.
**그 기준에서 차이는 0 이다.**

### 5.3 이 단계가 라이브를 못 건드리는 근거

라이브 실측(2026-08-10, 읽기 전용):

```
mealplanning-root  path=argocd/applications  directory={"recurse":true}   prune=true   selfHeal=true
platform-root      path=platform/argocd      directory={"include":"*.yaml"}  prune=false  selfHeal=true
```

- `mealplanning-root` 는 `argocd/applications` 만 본다. 새 `argocd/base`·`argocd/overlays` 는
  **그 밖의 형제 디렉터리**라 `recurse: true` 의 탐색 범위에 아예 들어오지 않는다.
- `platform-root` 는 `platform/argocd` 를 보되 **`recurse` 가 없다(=false)** → ArgoCD 는 앱 경로
  **바로 아래 파일만** 읽고 하위 디렉터리는 건너뛴다. 새 `base/`·`overlays/` 는 하위다.
- 🔴 **이중 안전판**: 설령 위 판단이 틀려 하위까지 읽히더라도, `platform-root` 는 **`prune: false`** 다.
  같은 이름·같은 내용의 Application 이 한 번 더 적용되는 SSA no-op 이 될 뿐, **child 삭제는
  구조적으로 일어날 수 없다.** 위험한 쪽(`prune: true` 인 `mealplanning-root`)은 애초에
  새 디렉터리와 경로가 겹치지 않는다.
- `SITES.md` 의 🔴 수칙 *"지금 감시 중인 디렉터리에 `kustomization.yaml` 을 넣지 말 것"* 도 지켰다 —
  `kustomization.yaml` 은 **하위 `base/` 안에만** 있고, 감시 중인 두 디렉터리의 최상단에는 없다.

`python3 scripts/validate.py` 통과(kustomization 35개 · 매니페스트 327개, 경고 2건은 기존 것 —
`services/cloudflared` eks 오버레이 부재[C-5 의도] · kubeconform 미설치).

### 5.4 2단계는 여기서 하지 않았다 — 앱 레포 PR 로 준비만 해 뒀다

뿌리의 `source.path` 재지정은 **앱 레포 Ansible `k8s_argocd` 롤 소관**이다. 이 config 브랜치만으로는
아무 일도 일어나지 않는다 — 새 디렉터리는 무생물이다. 앱 레포 쪽 준비는 §5.5 · §5.6 참조.

### 5.5 🔴 2단계의 함정 — `SITES.md` 가 "미검증"으로 남긴 지점의 답

`SITES.md` §0-4 는 *"ArgoCD 가 `spec.source.directory` 가 명시된 상태에서 `kustomization.yaml` 을
만나면 어느 모드로 가는가"* 를 **미검증**으로 남기고, 1단계를 회피 설계로 무해화했다.

**그런데 2단계는 그 질문을 정면으로 통과한다** — 뿌리가 보는 경로가 바로 kustomize 오버레이가
되기 때문이다. 그래서 라이브 Application 46개를 전수 조회해 답을 확정했다(2026-08-10, 읽기 전용):

| 조건 | `status.sourceType` | 예외 |
|---|---|---:|
| `spec.source.directory` **있음** (뿌리 2개) | `Directory` | 0 |
| `directory: null` + `kustomization.yaml` 있음 (19개) | `Kustomize` | 0 |
| `directory: null` + kustomization 없음 (7개) | `Directory` (자동판별) | 0 |

→ **`directory` 가 있으면 그것만으로 Directory 모드가 확정되고 kustomize 자동판별이 일어나지 않는다.**

🔴 즉 **2단계는 `path` 만 바꿔선 안 되고 `directory:` 블록을 같이 걷어내야 한다.** 남겨 두면
뿌리가 `kustomization.yaml` 을 매니페스트로 읽는다. 새 오버레이 디렉터리엔 그 파일 하나뿐이라
**유효 리소스가 0** 이 되고, `mealplanning-root` 는 `prune: true` 다 — child 23개가 프룬될 수 있는
경로다. 앱 레포 PR(§5.6)이 이 처리를 포함한다.

⚠️ `platform-root` 구 주석의 취지("child 는 평면으로 — `recurse: true` 면 `platform/pg/` 같은
본문 디렉터리까지 빨아들인다")는 `base/kustomization.yaml` 의 `resources` 목록이 승계한다.
이제 무엇이 child 인지는 **탐색 규칙이 아니라 명시 목록**이 정한다.

### 5.6 앱 레포 준비 — PR 3개로 쪼갰다

`SITES.md` §0-4 말미의 "앱 레포 쪽에 필요한 변경" 4항목을, **각 PR 이 단독으로 안전하도록** 갈랐다.

| PR | 내용 | 단독 적용 안전? |
|---|---|---|
| **#579** | `mealplanning` AppProject 중복 정의 제거 | ✅ 적용 시 라이브 변경 0 |
| **#581** | `mealplanning-root` Application IaC 편입 | ✅ 렌더가 **라이브와 필드 단위 일치** → 변경 0 |
| **#582** (draft) | `argocd_site` 신설 + 뿌리 경로 전환 + `directory` 제거 | ⛔ **컷오버 1단계 머지가 선행조건** |

🔴 **#579 는 이관과 무관하게 지금 급하다.** `mealplanning` AppProject 를 두 템플릿이 만들고 있고
(`argocd-mealplanning-project.yaml.j2` = `argocd_app_namespaces` / `argocd-repo.yaml.j2` ③ =
`argocd_allowed_namespaces`), `tasks/main.yml` 의 적용 순서상 **뒤에 오는 후자가 앞을 덮어쓴다.**
결과 = 누구든 `--tags argocd` 를 돌리면 `mp-ingress` destination 이 조용히 삭제되고
`mp-ingress` Application 이 배포 거부된다. 라이브가 멀쩡한 건 아무도 롤을 안 돌렸기 때문이다.

> ℹ️ `SITES.md` 는 이걸 *"`argocd_allowed_namespaces` 에 `mp-ingress` 추가"* 로 적어 뒀는데,
> 그건 증상 처리다. 실제 원인은 **정본이 둘**이라는 것이고, #579 는 중복 쪽을 없앤다.

---

## 6. 이 컷오버가 열어주는 것 (Wave B)

Helm 소스 child 12개의 인라인 `valuesObject` 에 갇혀 있던 **사이트 결합 값 15건**이
`platform/argocd/overlays/eks` 에서 필드 단위로 패치 가능해진다. 위치를 줄번호까지 확인해 뒀다:

| 값 | 건수 | 위치 |
|---|---:|---|
| **0-5** `nodeSelector: kubernetes.io/hostname` | 5 | `loki.yaml:79`(b1) · `kubecost.yaml:53,75,101,125`(a2) |
| **0-5** `nodeSelector: topology…/zone: host-b` | 1 | `tempo.yaml:108` |
| **0-8** `storageClass: openebs-lvm` → `gp3` | 6 | `loki.yaml:82` · `tempo.yaml:112` · `kubecost.yaml:25,62,80,83` |
| **0-9** Harbor LAN IP `192.168.0.10/…` → ECR | 1 | `rollouts.yaml:87` (initContainer 이미지) |
| MinIO 인클러스터 엔드포인트 → S3 | 2 | `loki.yaml:38` · `tempo.yaml:100` |

나머지 8개(`alloy` `keda` `descheduler` + 오퍼레이터 5)는 사이트 결합 값이 0 이다.

---

## 7. 🔴 사람이 판단해야 할 것

1. **머지 순서와 시점** — 앱 레포 준비 PR 3개는 §5.6 에 올려 뒀다(#579 · #581 · #582).
   앞의 둘은 **적용해도 라이브 변경 0** 임을 검증했으니 언제 태워도 되고, #582 만 컷오버 1단계
   머지가 선행조건이다. 결정할 것은 "언제 태우는가"뿐이다.
   🔴 다만 **#579 는 미루면 안 된다** — 이관과 무관하게 지금 살아 있는 지뢰다(§5.6).
2. **컷오버 1↔3 단계 사이의 "정본 두 곳" 창을 얼마나 열어둘지.** 그 창에서 child 를 수정하면
   `argocd/applications/` 와 `argocd/base/` **양쪽 다** 고쳐야 한다. 창을 짧게 가져가는 것이
   이 절차의 유일한 비용이다.
3. **`platform/kafka`·`platform/pg` eks 오버레이의 L1×L2 충돌 해결 방식** — §3.3. 패치 방언이
   달라 `patches:` 항목을 2개로 나눠야 한다. 기계적 union 은 렌더를 깨뜨린다.
4. **0-8b — PG·ES 의 reclaimPolicy 를 EKS 에서 재현할지 고칠지** (L2 가 문서로 남기고 손대지 않음).
   온프렘 의도는 "Retain" 이었는데 라이브는 PV 21/21 이 Delete 다. `gp3-retain` SC 추가 +
   `volumeClaimDeletePolicy` 를 **둘 다** 해야 반쪽이 아니다.
5. **C-21 (ES `nodeSets` 를 AZ 당 1개로 재편) 전에는 ES eks 오버레이를 붙이지 말 것** — L1 이
   경고로 남겼다. nodeSelector 를 걷어낸 결과 `node.attr.zone` 샤드 awareness 를 뒷받침하는 것이
   없어진다. 덧붙여 온프렘·EKS 양쪽의 ES/PG/Kafka 오버레이가 **JSON6902 인덱스 패치**라
   `nodeSets`·`topologySpreadConstraints` 순서가 바뀌면 조용히 엉뚱한 곳에 붙는다.
6. **머지 방식** — 9개를 각각 PR 로 갈지, 1~3 을 한 PR 로 묶을지. 3번이 2번을 포함하고 2번이
   1번을 포함하므로 **`feat/argocd-roots-cutover-1` 한 개만 머지해도 1~3 이 다 들어온다.**
7. **온프렘 렌더 diff 2건(런북 경로 문자열) 승인.** 0-1 이 의도한 예외이고 알림 동작은 불변이지만,
   "온프렘 diff = 0" 을 문자 그대로 요구한다면 이 2건이 유일한 예외임을 명시적으로 받아 두는 편이 낫다.

---

## 8. 재현 방법

렌더 하네스는 임시 스크립트로 돌렸다(레포에 커밋하지 않음 — `scripts/validate.py` 와 역할이 겹친다).
같은 검증을 다시 하려면:

```bash
# 1) 브랜치별 워크트리 (브랜치 전환 금지 — 다른 세션과 충돌한다)
git clone git@github.com:happyInit/mealplanning-config.git cfg && cd cfg
for b in eks-overlay-skeleton argocd-roots-iac eks-workload-spec eks-storage \
         eks-netpol eks-eso-ssm eks-observability eks-registry-validate \
         argocd-roots-cutover-1; do
  git worktree add --detach ../wt/$b origin/feat/$b
done

# 2) 각 워크트리에서 Application 의 source.path 를 읽어 렌더 → 정규화 JSON 으로 덤프 → main 과 diff
#    (경로 하드코딩 금지. 0-1 이 source.path 를 바꾸므로 Application 에서 읽어야 한다)

# 3) 0-4 컷오버 1단계 증명 — 옛 경로(directory 모드) vs 새 경로(kustomize)
kubectl kustomize argocd/overlays/onprem
kubectl kustomize platform/argocd/overlays/onprem
```

라이브 대조는 읽기 전용으로:

```bash
ssh ubuntu@192.168.0.17 "sudo kubectl -n argocd get applications \
  -o custom-columns=NAME:.metadata.name,PATH:.spec.source.path,SYNC:.status.sync.status"
```
