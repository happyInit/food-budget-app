# mp-k8s RBAC 계획 (사람 접근 · 포지션 기반)

> **상태: 계획(PLAN) — 아직 적용 안 함.** 팀이 개발 중이라 지금 권한을 조이면 걸린다.
> 이 문서는 "개발이 안정된 뒤 무중단으로 켤 수 있게" 설계·오브젝트·롤아웃 단계를 미리 박아둔 것이다.
> 적용은 **Phase 1(무중단 발급) → Phase 2(컷오버)** 순서로만 하며, 컷오버는 개발 끝물에 한다.
> 인접 보안(NetworkPolicy·mTLS·PodSecurity·etcd 암호화[완료])는 별개 층 — 정본 = `docs/mp_k8s_infra_object_spec.md §10/§11`, `docs/mp_k8s_backup_strategy.md §7`.

작성 2026-07-31. 실측 근거(라이브 클러스터)는 각 절에 인라인.

---

## 0. 왜 지금 필요한가 (현황·리스크)

- **현재 = 사람 RBAC 층이 없다.** 팀원 전원이 마스터(`192.168.0.17`)에 공유 `ubuntu` SSH → `~/.kube/config`(=`admin.conf`) → **cluster-admin**. 개인 신원·클라이언트 인증서·OIDC 전무. (실측: cluster-admin 바인딩 = kubeadm 기본 `system:masters`·`kubeadm:cluster-admins` 2개뿐, 팀원용 User/Group 바인딩 0개.)
- **최대 리스크는 "권한이 넓다"가 아니라 "취소 불가"다.** `admin.conf`는 무기한·revoke 불가한 cluster-admin 자격증명(정본 경고 = `docs/mp_k8s_infra_status.md §4.0` 🔴, `docs/mp_k8s_p1_app_handoff.md`). 한 명 노트북 유출 = 클러스터 전면 노출이고, 막을 방법이 CA 교체뿐.
- 그래서 이 설계의 1순위 목표 = **개인 신원 + 즉시 취소 가능성**(등급 세분화는 그 다음).
- 문서상 개인 계정은 "ESO·OIDC 도입 시점으로 연기"돼 있었고(`§4.0`), 5인 역할분담도 `design.md §10` "미정"이었다 → 이 문서가 그 역할분담을 받아 RBAC로 구체화한다.

---

## 1. 티어 설계 (포지션 → 소수 티어)

5인에 5개 맞춤 롤은 과설계다. **포지션을 소수 티어로** 묶는다. 권한 정의는 **K8s 기본 ClusterRole 재사용**(`view`/`edit`/`admin`/`cluster-admin`), 스코핑은 **바인딩 종류**로 한다(§3 원칙).

| 티어 | 권한 | 근거 |
|---|---|---|
| **admin** | `cluster-admin` (전역) | 클러스터·오퍼레이터·CI/CD를 실제로 만지는 사람만 |
| **app-dev** | 전체 `view` + `app`·`pipeline` ns `edit` | 자기 앱은 풀로(배포·exec·logs·port-forward), cluster-scoped 쓰기·타 ns 쓰기 차단 |
| **observability** | 전체 `view` + `observability` ns `edit` + `mp-monitoring-edit`(모니터링 CRD) | 알림룰·대시보드 config-as-code 배포 |
| **data-dev** | 전체 `view` + `pipeline`·`cost` ns `edit` (data ns는 view; psql/exec 필요 시 edit 추가) | 파이프라인·finops 배포. datastore CR 변경은 admin 몫 |

- 기본 `view`는 **Secret 값 조회를 제외**한다(K8s 설계) → 전체 view를 줘도 비밀은 안 샌다.
- `fb-secrets`(전 비밀 원본) ns는 **admin 외 아무에게도** edit/view 안 준다.

---

## 2. 사람 → 티어 매핑 (2026-07-31 사용자 확정 포지션)

| 사람 | 포지션 | 티어 | SSH 키(현행) |
|---|---|---|---|
| **봉수** | 인프라·CI/CD·PM | **admin** | `bongsu.pub` |
| **태현** | 인프라·data pipeline | **admin** (잠정 ⚠️) | *(키 미등록 — 추가 필요)* |
| **건우** | AI 기능(앱 서비스) | **app-dev** | `geonu.pub` |
| **정현** | 모니터링·이상징후 대시보드 | **observability** | *(키 미등록 — `jungeun.pub`? 확인)* |
| **정은** | data pipeline·finops | **data-dev** | *(키 매핑 확인 — `team6.pub`?)* |

- ⚠️ **미확정: 태현 admin 여부.** 봉수가 PM이라 상시 대응이 어려울 수 있어 **인프라 admin 2명(버스팩터)** 권장. 엄격 최소권한을 원하면 태현을 `data-dev + 클러스터 view`로 낮춘다. 컷오버(Phase 2) 전에 확정.
- ⚠️ **SSH 키 ↔ 사람 매핑 확인 필요.** 현재 등록 키 = `bongsu`·`geonu`·`jungeun`·`team6` 4개(role `team_ssh_keys`). 정현/정은/태현의 실제 키를 대조해 채운다.
- 건우의 AI 기능(`mp-ranking-serving`·`mp-ocr`·`mp-recipe`·`mp-chat`·`mp-video`)은 전부 `app` ns → app-dev 하나로 커버(실측).

---

## 3. Role vs ClusterRole — 구성 원칙

1. **ClusterRole = 권한 정의**(verb×resource). 기본 `view`/`edit`/`admin`/`cluster-admin` 재사용, 재발명 금지.
2. **RoleBinding(ns 스코프) = ClusterRole을 "그 ns 안에서만" 부여** → ns별 커스텀 Role 없이 스코핑.
3. **ClusterRoleBinding = 전역**(cluster-admin·전체 view)에만.
4. **커스텀 ClusterRole은 CRD 갭에만.** 실측 결과 기본 `edit`에 `monitoring.coreos.com` **없음** → 정현용 `mp-monitoring-edit`(aggregate-to-edit 라벨) 1개만 신설. 그 외 커스텀 0개.

> 참고: 독립 ns Role이 맞는 경우 = `k8s_eso` 롤의 `eso-reader`처럼 "단일 ns·단일 목적". 우리 티어는 재사용형이라 ClusterRole+RoleBinding이 정답.

---

## 4. 만들 오브젝트 (실행 시 이대로)

네이밍 규칙: 신규 전부 `mp-` 접두(§CLAUDE.md). 사람 SA는 전용 ns `mp-users`.

```yaml
# ── ns ─────────────────────────────────────────────
apiVersion: v1
kind: Namespace
metadata: { name: mp-users }
---
# ── 사람당 ServiceAccount (신원) — 5개 ──────────────
apiVersion: v1
kind: ServiceAccount
metadata: { name: bongsu,  namespace: mp-users }   # 그리고 taehyun / geonu / junghyun / jungeun
---
# ── admin (봉수, 태현[잠정]) — 전역 ────────────────
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: { name: mp-bongsu-cluster-admin }
roleRef:  { apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: cluster-admin }
subjects: [{ kind: ServiceAccount, name: bongsu, namespace: mp-users }]
---
# ── 비-admin 공통: 전체 view (Secret 값 제외라 안전) ─
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: { name: mp-geonu-view }
roleRef:  { apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: view }
subjects: [{ kind: ServiceAccount, name: geonu, namespace: mp-users }]
---
# ── app-dev(건우): app·pipeline ns edit ────────────
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: { name: mp-geonu-edit, namespace: app }        # + namespace: pipeline 로 하나 더
roleRef:  { apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: edit }
subjects: [{ kind: ServiceAccount, name: geonu, namespace: mp-users }]
---
# ── observability(정현): 커스텀 CRD 롤 + ns edit ────
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: mp-monitoring-edit
  labels: { rbac.authorization.k8s.io/aggregate-to-edit: "true" }   # 기본 edit 에 흡수
rules:
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["prometheusrules","servicemonitors","podmonitors","alertmanagerconfigs"]
    verbs: ["*"]
# → 정현은 전체 view(CRB) + observability ns edit(RB, 위 aggregate 로 CRD 포함)
---
# ── data-dev(정은): pipeline·cost ns edit ──────────
# 전체 view(CRB) + RB edit @pipeline + RB edit @cost.
# data ns 는 view 기본 — psql/exec 필요 시 RB edit @data 추가.
```

**바인딩 요약**

| 사람 | ClusterRoleBinding | RoleBinding(edit) |
|---|---|---|
| 봉수 | cluster-admin | — |
| 태현(잠정) | cluster-admin | — |
| 건우 | view | app, pipeline |
| 정현 | view | observability |
| 정은 | view | pipeline, cost (필요시 +data) |

실측 ns: `app argocd cert-manager cnpg-system cost data elastic-system external-secrets fb-secrets istio-system keda kube-system metallb-system observability openebs pipeline redis-operator-system strimzi-system`. (관측=`observability`, finops/Kubecost=`cost`, `monitoring` ns 없음.)

---

## 5. 신원·kubeconfig (취소 가능)

- 각 SA 토큰을 kubeconfig에 심어 개인에게 배포(**git 밖**).
- 토큰 수명 2안 — **(a)** `kubectl create token <sa> -n mp-users --duration=...` 만료형(재발급) / **(b)** SA 바인딩 장수 Secret 토큰. 캡스톤 UX엔 (b)가 편하나 (a)가 더 안전 — Phase 1에서 택1.
- **취소 = SA/바인딩 삭제 → 즉시 무효**(admin.conf "취소 불가" 🔴 해소).
- 전부 선언적 → 새 ansible role `k8s_team_rbac`(매핑은 `group_vars`, 토큰 발급만 수동 스텝).

---

## 6. 롤아웃 단계 (개발 안 걸리게)

| Phase | 시점 | 내용 | 개발 영향 |
|---|---|---|---|
| **0** | **지금** | 이 문서만. 클러스터 무변경. `admin.conf` 그대로 | **없음** |
| **1** | 개발 안정될 때 | `mp-users` ns + SA 5 + 바인딩 생성, 개인 kubeconfig 배포. **`admin.conf`는 계속 살려둠** — 각자 원하면 스코프 kubeconfig 써보되 강제 아님(섀도 모드) | **없음**(additive) |
| **2** | 개발 끝물·운영 전환 | `admin.conf` 팀 배포 중단 + 회수, 개인 kubeconfig로 일원화. 여기서부터 권한 제한이 "걸림" | 있음 → **이 시점을 개발 안정 후로** |
| **3** | 후속 | §8 항목(automount off·ArgoCD RBAC·UI 인증) | 개별 |

핵심: **Phase 1은 무중단**(기존 admin 경로 유지한 채 새 경로 추가)이라 언제 해도 안 걸린다. 걸리는 건 Phase 2뿐이고 그건 개발이 끝나갈 때 한다.

---

## 7. 롤백

- Phase 1/2 모두 **바인딩·SA 삭제로 즉시 원복**. `admin.conf`는 Phase 2 전까지 살아 있으므로 언제든 복귀 가능.
- 컷오버(Phase 2)에서 문제가 나면 admin.conf 재배포로 즉시 복구 → 진짜 리스크 창은 Phase 2 이후뿐.

---

## 8. 범위 밖 / 후속 (RBAC 인접, 별건)

1. **`automountServiceAccountToken: false`** — 앱 파드(§10.6 스펙). 워크로드측 하드닝, **config 레포(`mealplanning-config`) 소관**.
2. **ArgoCD per-user RBAC**(`argocd-rbac-cm`) — 현재 단일 `admin`. 건우·정현·정은이 ArgoCD UI를 본다면 read-only/sync 등급 필요. AppProject 울타리(구현됨)와 별개 층.
3. **웹UI 인증**(Grafana·Kubecost·ArgoCD) — K8s RBAC 밖, 각 UI 자체 인증. 정현·정은의 "대시보드" 열람은 이쪽. **Grafana 비번 로테이트 미완**(별도 이슈).

---

## 9. 착수 전 확정할 것 (미확정)

- [ ] **태현 admin 여부** (버스팩터 admin vs 엄격 최소권한 data-dev)
- [ ] **SSH 키 ↔ 사람 매핑** (정현·정은·태현 키 대조; 미등록분 `team_ssh_keys`로 추가)
- [ ] **토큰 수명 방식** (만료형 vs 장수 Secret)
- [ ] 정은 `data` ns edit 필요 여부(psql/exec)
