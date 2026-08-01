# mp-k8s RBAC — 사람 접근 (포지션 기반) · 계획·구현·운영

> **상태: Phase 1 라이브 (적용·검증 완료 2026-08-01).** 개인 신원 + 포지션 티어가 클러스터에 떠 있고
> `auth can-i` 20/20 + 노트북 실접속까지 검증됐다. 구현체 = ansible role `k8s_team_rbac` (PR #449 + 첫적용 픽스 #454).
> 🔴 **`admin.conf`는 그대로 살려둔다** → 개발이 안 걸린다. 최종 컷오버(admin.conf 회수)는 **Phase 2**로, 개발이 끝물일 때 한다.
> 인접 보안(NetworkPolicy·mTLS·PodSecurity·etcd 암호화[완료])은 별개 층 — 정본 = `docs/mp_k8s_infra_object_spec.md §10/§11`, `docs/mp_k8s_backup_strategy.md §7`.

작성 2026-07-31 · 갱신 2026-08-01(Phase 1 적용·검증·발급). 실측 근거(라이브 클러스터)는 각 절에 인라인.

---

## 0. 왜 필요했나 (현황·리스크)

- **그 전엔 사람 RBAC 층이 없었다.** 팀원 전원이 마스터(`192.168.0.17`)에 공유 `ubuntu` SSH → `~/.kube/config`(=`admin.conf`) → **cluster-admin**. 개인 신원·클라이언트 인증서·OIDC 전무. (실측: cluster-admin 바인딩 = kubeadm 기본 `system:masters`·`kubeadm:cluster-admins` 2개뿐, 팀원용 User/Group 바인딩 0개.)
- **최대 리스크는 "권한이 넓다"가 아니라 "취소 불가"다.** `admin.conf`는 무기한·revoke 불가한 cluster-admin 자격증명(정본 경고 = `docs/mp_k8s_infra_status.md §4.0` 🔴, `docs/mp_k8s_p1_app_handoff.md`). 한 명 노트북 유출 = 클러스터 전면 노출이고, 막을 방법이 CA 교체뿐.
- 그래서 이 설계의 1순위 목표 = **개인 신원 + 즉시 취소 가능성**(등급 세분화는 그 다음).
- 문서상 개인 계정은 "ESO·OIDC 도입 시점으로 연기"돼 있었고(`§4.0`), 5인 역할분담도 `design.md §10` "미정"이었다 → 이 문서가 그 역할분담을 받아 RBAC로 구체화했다.

---

## 1. 티어 설계 (포지션 → 소수 티어)

5인에 5개 맞춤 롤은 과설계다. **포지션을 소수 티어로** 묶는다. 권한 정의는 **K8s 기본 ClusterRole 재사용**(`view`/`edit`/`admin`/`cluster-admin`), 스코핑은 **바인딩 종류**로 한다(§3 원칙).

| 티어 | 권한 | 근거 |
|---|---|---|
| **admin** | `cluster-admin` (전역) | 클러스터·오퍼레이터·CI/CD를 실제로 만지는 사람만 |
| **app-dev** | 전체 `view` + `app`·`pipeline` ns `edit` | 자기 앱은 풀로(배포·exec·logs·port-forward), cluster-scoped 쓰기·타 ns 쓰기 차단 |
| **observability** | 전체 `view` + `observability` ns `edit` + `mp-monitoring-edit`(모니터링 CRD) | 알림룰·대시보드 config-as-code 배포 |
| **data-dev** | 전체 `view` + `pipeline` ns `edit` (`data`는 view; psql/exec 필요 시 edit 추가) | 파이프라인 배포. finops(Kubecost)는 웹UI라 `cost` edit 불요 — 전체 view로 커버. datastore CR 변경은 admin 몫 |

- 기본 `view`는 **Secret 값 조회를 제외**한다(K8s 설계) → 전체 view를 줘도 비밀은 안 샌다.
- `fb-secrets`(전 비밀 원본) ns는 **admin 외 아무에게도** edit/view 안 준다.

---

## 2. 사람 → 티어 매핑 (2026-08-01 확정·적용)

| 사람 | 포지션 | 티어 | SA 이름 |
|---|---|---|---|
| **봉수** | 인프라·CI/CD·PM | **admin** | `bongsu` |
| **태현** | 인프라·data pipeline | **admin** (버스팩터 확정) | `taehyun` |
| **건우** | AI 기능(앱 서비스) | **app-dev** | `geonu` |
| **정현** | 모니터링·이상징후 대시보드 | **observability** | `junghyun` |
| **정은** | data pipeline·finops | **data-dev** | `jungeun` |

- **태현 admin 확정**: 봉수가 PM이라 상시 대응이 어려울 수 있어 **인프라 admin 2명(버스팩터)**. 나중에 조이고 싶으면 `data-dev`로 낮추면 됨(바인딩 교체만).
- 건우의 AI 기능(`mp-ranking-serving`·`mp-ocr`·`mp-recipe`·`mp-chat`·`mp-video`)은 전부 `app` ns → app-dev 하나로 커버(실측).
- ⚠️ **SSH 키 ↔ 사람 매핑은 별개 관심사** (RBAC 신원은 SA, SSH 키는 마스터 호스트 접근용). 현재 등록 키 = `bongsu`·`geonu`·`jungeun`(=정은)·`team6`. **태현·정현은 SSH 키 미등록** — 마스터 SSH가 필요하면 `team_ssh_keys`로 추가. kubectl 접근은 kubeconfig(토큰)라 SSH 키와 무관하게 동작한다.

---

## 3. Role vs ClusterRole — 구성 원칙

1. **ClusterRole = 권한 정의**(verb×resource). 기본 `view`/`edit`/`admin`/`cluster-admin` 재사용, 재발명 금지.
2. **RoleBinding(ns 스코프) = ClusterRole을 "그 ns 안에서만" 부여** → ns별 커스텀 Role 없이 스코핑.
3. **ClusterRoleBinding = 전역**(cluster-admin·전체 view)에만.
4. **커스텀 ClusterRole은 CRD 갭에만.** 실측: 기본 `edit`에 `monitoring.coreos.com` **없음** → `mp-monitoring-edit`(aggregate-to-edit 라벨) 1개만 신설. 그 외 커스텀 0개. aggregate 덕에 "어떤 ns 의 edit 보유자는 그 ns 의 PrometheusRule/ServiceMonitor 도 관리"가 자동 성립(관측=observability, 앱=app…).

> 참고: 독립 ns Role이 맞는 경우 = `k8s_eso` 롤의 `eso-reader`처럼 "단일 ns·단일 목적". 우리 티어는 재사용형이라 ClusterRole+RoleBinding이 정답.

---

## 4. 만든 오브젝트 (라이브)

네이밍 규칙: 신규 전부 `mp-` 접두(§CLAUDE.md). 사람 SA는 전용 ns `mp-users`. 구현체 = `infra/ansible/roles/k8s_team_rbac/` (매핑 = `defaults/main.yml` 의 `mp_team_rbac`).

**바인딩 요약 (적용됨)**

| 사람 | ClusterRoleBinding | RoleBinding(edit) |
|---|---|---|
| 봉수 | `cluster-admin` | — |
| 태현 | `cluster-admin` | — |
| 건우 | `view` | `app`, `pipeline` |
| 정현 | `view` | `observability` |
| 정은 | `view` | `pipeline` (필요 시 +`data`) |

**오브젝트 수(라이브)**: ns `mp-users` ×1 · ServiceAccount ×5 · 장수 토큰 Secret ×5 · ClusterRole `mp-monitoring-edit` ×1 · ClusterRoleBinding ×5 · RoleBinding ×4.

핵심 매니페스트(발췌 — 정본은 role 템플릿 `team-rbac.yaml.j2`):
```yaml
# admin — 전역
kind: ClusterRoleBinding
metadata: { name: mp-bongsu-cluster-admin }
roleRef:  { kind: ClusterRole, name: cluster-admin, apiGroup: rbac.authorization.k8s.io }
subjects: [{ kind: ServiceAccount, name: bongsu, namespace: mp-users }]
---
# 비-admin: 전체 view(Secret 값 제외라 안전)
kind: ClusterRoleBinding
metadata: { name: mp-geonu-view }
roleRef:  { kind: ClusterRole, name: view, apiGroup: rbac.authorization.k8s.io }
subjects: [{ kind: ServiceAccount, name: geonu, namespace: mp-users }]
---
# ns 스코프 edit
kind: RoleBinding
metadata: { name: mp-geonu-edit, namespace: app }   # + pipeline
roleRef:  { kind: ClusterRole, name: edit, apiGroup: rbac.authorization.k8s.io }
subjects: [{ kind: ServiceAccount, name: geonu, namespace: mp-users }]
---
# 모니터링 CRD — 기본 edit 에 흡수
kind: ClusterRole
metadata: { name: mp-monitoring-edit, labels: { rbac.authorization.k8s.io/aggregate-to-edit: "true" } }
rules: [{ apiGroups: ["monitoring.coreos.com"],
          resources: ["prometheusrules","servicemonitors","podmonitors","alertmanagerconfigs"], verbs: ["*"] }]
```

실측 ns: `app argocd cert-manager cnpg-system cost data elastic-system external-secrets fb-secrets istio-system keda kube-system metallb-system observability openebs pipeline redis-operator-system strimzi-system`. (관측=`observability`, finops/Kubecost=`cost`, `monitoring` ns 없음.)

---

## 5. 신원·kubeconfig (취소 가능)

- 신원 = ns `mp-users`의 개인 SA. kubeconfig에 **장수 Secret 토큰**(만료 없음)을 심는다(사용자 택 — 캡스톤 UX). `kubectl create token` 만료형은 대안(더 안전·재발급 필요).
- 발급 위치 = 마스터 `/root/mp-team-kubeconfigs/<name>.kubeconfig`(root 0600, `no_log`). 각자에게 **안전 채널**로 배포(git·평문 채널 금지).
- **취소 = SA/바인딩 삭제 → 즉시 무효**(admin.conf "취소 불가" 🔴 해소).
- 전부 선언적 → role `k8s_team_rbac`. `apply` 로 수렴(변경 판정 = apply 출력. 🔴 `kubectl diff`는 안 씀 — 새 `mp-users` ns 안의 SA/Secret을 서버 dry-run이 NotFound로 죽인다: 첫적용 닭-달걀, #454에서 해소).

---

## 6. 롤아웃 단계 (개발 안 걸리게)

| Phase | 시점 | 내용 | 상태 |
|---|---|---|---|
| **0** | 계획 | 설계 문서 | ✅ 완료 |
| **1** | 2026-08-01 | `mp-users`+SA+바인딩 생성, 개인 kubeconfig 발급. **`admin.conf` 살려둠**(섀도) | ✅ **적용·검증·발급 완료** — 배포는 각자 페이스 |
| **2** | 개발 끝물·운영 전환 | `admin.conf` 배포 중단+회수, 개인 kubeconfig로 일원화. 여기서부터 권한 제한이 "걸림" | ⏳ 대기 (개발 안정 후) |
| **3** | 후속 | §8 항목(automount off·ArgoCD RBAC·UI 인증) | 📋 별건 |

핵심: **Phase 1은 무중단**(기존 admin 경로 유지한 채 새 경로 추가). 걸리는 건 Phase 2뿐이고 그건 개발이 끝나갈 때 한다.

---

## 6.1 운영 런북

**적용/갱신** (매핑 추가·변경 후):
```bash
git checkout main && git pull
ansible-playbook k8s.yml --tags team_rbac        # opt-in 전용(전체 플레이북으로는 안 돎)
```

**kubeconfig 회수·배포** (마스터 접근자 = 봉수, 노트북에서):
```bash
mkdir -p ~/mp-kubeconfigs && chmod 700 ~/mp-kubeconfigs && cd ~/mp-kubeconfigs
for who in bongsu taehyun geonu junghyun jungeun; do
  ssh ubuntu@192.168.0.17 "sudo cat /root/mp-team-kubeconfigs/$who.kubeconfig" > "$who.kubeconfig"
  chmod 600 "$who.kubeconfig"
done
# 각자에게 자기 파일만 안전 채널로 전달 → 끝나면: shred -u ~/mp-kubeconfigs/*.kubeconfig
```

**각 팀원 설치**(한 번):
```bash
mkdir -p ~/.kube && cp <자기이름>.kubeconfig ~/.kube/config
kubectl get pods -n <자기ns>       # 되면 완료 (kubectl 필요·클러스터 6443 도달 전제)
```

**멤버 추가**: `roles/k8s_team_rbac/defaults/main.yml` 의 `mp_team_rbac` 에 추가 → `--tags team_rbac` 재실행.
**취소(즉시)**: 목록에서 제거 후 재실행, 또는 `kubectl -n mp-users delete sa <name>` (+ 관련 바인딩).

---

## 7. 검증 (2026-08-01 라이브)

**`kubectl auth can-i --as=system:serviceaccount:mp-users:<name>` — 20/20 OK, mismatch 0:**

| 대상 | 허용(want=yes) | 차단(want=no) |
|---|---|---|
| 봉수·태현 | `* *` 전권 | — |
| 건우 | app·pipeline deploy 생성 · app secret 조회 · 전체 pod 조회 | data deploy 생성 · **fb-secrets secret 조회** |
| 정현 | observability PrometheusRule 편집·deploy 생성 · 전체 pod 조회 | data PrometheusRule 편집 · app deploy 생성 |
| 정은 | pipeline deploy 생성 · 전체 pod 조회 | data deploy 생성 · **fb-secrets secret 조회** |

**엔드투엔드**: 팀원 노트북(WSL)에서 `KUBECONFIG=./geonu.kubeconfig kubectl get pods -n app` → app 파드 조회 성공(네트워크·토큰·권한 전 체인 확인).

핵심 방어선 실증: **비-admin은 `fb-secrets` 접근 불가 · 자기 담당 ns 밖은 읽기 전용 · 모니터링 CRD 편집은 관측 담당 ns에만 흡수.**

---

## 8. 롤백

- Phase 1/2 모두 **바인딩·SA 삭제로 즉시 원복**. `admin.conf`는 Phase 2 전까지 살아 있으므로 언제든 복귀 가능.
- 컷오버(Phase 2)에서 문제가 나면 admin.conf 재배포로 즉시 복구 → 진짜 리스크 창은 Phase 2 이후뿐.

---

## 9. 범위 밖 / 후속 (RBAC 인접, 별건)

1. **`automountServiceAccountToken: false`** — 앱 파드(`§10.6` 스펙). 워크로드측 하드닝, **config 레포(`mealplanning-config`) 소관**.
2. **ArgoCD per-user RBAC**(`argocd-rbac-cm`) — 현재 단일 `admin`. 건우·정현·정은이 ArgoCD UI를 본다면 read-only/sync 등급 필요. AppProject 울타리(구현됨)와 별개 층.
3. **웹UI 인증**(Grafana·Kubecost·ArgoCD) — K8s RBAC 밖, 각 UI 자체 인증. 정현·정은의 "대시보드" 열람은 이쪽. **Grafana 비번 로테이트 미완**(별도 이슈).

---

## 10. 남은 작업 (요약)

- [ ] **개인 kubeconfig 배포 마무리** — 각자에게 전달 + 각자 설치(사용자 페이스, admin.conf 살아 있어 안 걸림).
- [ ] **Phase 2 컷오버** — `admin.conf` 회수. 개발 안정 후.
- [ ] (선택) 태현·정현 **SSH 키 등록**(마스터 호스트 접근이 필요할 때만).
- [ ] (별건) §9 후속 3종.
