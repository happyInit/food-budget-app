# mp-k8s RBAC — 사람 접근 (포지션 기반) · 계획·구현·운영

> **상태: Phase 1 라이브 (적용·검증 완료 2026-08-01).** 개인 신원 + 포지션 티어가 클러스터에 떠 있고
> `auth can-i` 20/20 + 노트북 실접속까지 검증됐다. 구현체 = ansible role `k8s_team_rbac` (PR #449 + 첫적용 픽스 #454).
> 🔴 **`admin.conf`는 그대로 살려둔다** → 개발이 안 걸린다. 최종 컷오버(admin.conf 회수)는 **Phase 2**로, 개발이 끝물일 때 한다.
> 인접 보안(NetworkPolicy·mTLS·PodSecurity·etcd 암호화[완료])은 별개 층 — 정본 = `docs/mp_k8s_infra_object_spec.md §10/§11`, `docs/mp_k8s_backup_strategy.md §7`.

> 🔴 **Phase 1.5 신설 (2026-08-09) — 내장 `edit` 을 verb 단위 커스텀 롤로 교체한다.** 체크리스트 `0-14`(Phase 0 차단급) · 이슈 #550.
> 아래 §1~§10 은 **Phase 1 의 기록**이며, 티어 권한의 정본은 이제 **§11~§13** 이다.
> 계기는 AWS 이관(EKS 에서 `serviceaccounts/token` 이 IAM 롤이 된다 — `docs/mp_aws_prep_checklist.md` C-24)이었지만,
> 실측 중 **온프렘에 이미 뚫려 있는 cluster-admin 상승 경로**가 나와서 이관과 무관하게 고쳐야 하는 항목이 됐다(§11).

작성 2026-07-31 · 갱신 2026-08-01(Phase 1 적용·검증·발급) · 2026-08-09(Phase 1.5 설계·실측). 실측 근거(라이브 클러스터)는 각 절에 인라인.

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
| **정은** | data pipeline·finops | **data-dev**<br>→ 🔴 **`pipeline-dev` 로 정정**(§12) | `jungeun` |

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
for who in geonu junghyun jungeun; do        # 🔴 admin 2명은 장수 토큰이 없다(§11)
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

---

## 11. 🔴 Phase 1.5 의 계기 — 관측 담당이 이미 cluster-admin 이다 (2026-08-09 실측)

체크리스트 `0-14` 의 종전 근거는 *"내장 `edit` 이 그 ns 의 Secret 전권을 준다"* 였다. **실측해보니 그보다 나쁘다.**

```
정현 = RoleBinding observability/mp-junghyun-edit → ClusterRole/edit
  │  ┌─ create serviceaccounts/token             = yes
  ├──┼─ create pods/exec → 파드 안 토큰 읽기      = yes   (AUTO=true 파드 7/9)
  │  ├─ create pods (SA 지정)                    = yes
  │  └─ patch deployments (command 교체)         = yes
  ▼        └ 넷 다 도착지가 같다
SA observability/kube-prometheus-stack-operator
    ClusterRole 규칙 = {apiGroups:[""], resources:[configmaps, secrets], verbs:["*"]}
    ClusterRoleBinding = 전 ns 적용
    실측: get secrets -n {mp-users, fb-secrets, kube-system, data, app} = 전부 yes
  ▼
Secret mp-users/bongsu-token   (type=kubernetes.io/service-account-token · 만료 없음)
  ▼
cluster-admin
```

각 단계를 `kubectl auth can-i` 로 개별 실증했다(토큰 실제 발급·탈취는 실행하지 않았다 — 읽기 전용 조사).

**대조군 — `app`·`pipeline` 에는 같은 경로가 없다.**
두 ns 의 ServiceAccount 는 `default` 하나뿐이고(실측), 그 SA 의 실효 권한은 discovery 수준이다
(`get secrets -n mp-users` = no). app 은 `automountServiceAccountToken: false` 가 14/14 라 exec 해도 훔칠 토큰 자체가 없다.

### 여기서 나온 설계 귀결 3가지

| # | 귀결 | 근거 |
|---|---|---|
| ① | **`serviceaccounts/token` 만 빼는 것으로는 효과가 0** | 경로가 4개인데 하나만 막는 셈 |
| ② | **관측 티어는 워크로드 쓰기를 전부 뺀다** (exec·pods create·deployments/statefulsets patch) | 넷 중 아무거나 하나면 도착지가 같다 |
| ③ | **app·pipeline 에서는 exec 를 준다** | 그 ns 엔 훔칠 토큰이 없다. 없으면 admin.conf 를 계속 쓰게 돼 더 나쁘다 |

②는 초안(체크리스트 0-14 🅒·기본값 ②)을 **뒤집은 것**이다. 초안은 `pods/exec` 를 전 티어에 주자고 했다.

### 종착지도 잘랐다 — admin 장수 토큰 회수

위 연쇄가 *cluster-admin* 까지 가는 마지막 이유는 **만료 없는 cluster-admin 토큰이 etcd 안 Secret 으로 앉아 있어서**다.
`admin: true` 인 사람에게는 장수 토큰 Secret 을 만들지 않는다(2026-08-09 결정).
- 봉수·태현은 master SSH + `admin.conf` 경로가 이미 있어 접근이 끊기지 않는다.
- 비-admin 3명의 장수 토큰은 그대로 둔다 — 훔쳐도 이미 가진 권한 이상을 못 얻으므로 UX 를 깎을 이유가 없다.
- 효과: 최악의 결과가 *cluster-admin* → *전 시크릿 열람* 으로 **한 단계 내려간다**. 없앤 게 아니라 낮춘 것이다.

### 🔴 근본 원인은 우리 롤이 아니다 (범위 밖 · 명세로 인계)

`kube-prometheus-stack-operator` 가 **클러스터 전역 `secrets: ["*"]`** 를 갖는 것이 진짜 원인이고,
그건 Helm 차트 기본값이라 **config 레포 소관**이다 → `docs/mp_k8s_prom_operator_polp_spec.md` 로 넘긴다.

---

## 12. Phase 1.5 티어 — verb 단위 커스텀 롤 (정본)

**설계 원칙 — GitOps 라서 PoLP 가 싸다.** 정본은 ArgoCD 이고 클러스터 직접 수정은 되돌려지거나 drift 다.
사람에게 실제로 필요한 건 **보기 + 운영 액션**(재시작·로그·디버깅)이지 create/update 가 아니다.

**1단계 범위 = `edit` 만 교체한다.** 내장 `view`(전역 읽기)는 그대로 둔다 — core Secret 을 안 주므로 위험이 낮고,
변경 범위가 작아 되돌리기 쉽다. `view` 커스텀화는 2단계 선택사항.

| 롤 | 대상 | 읽기 | 운영(쓰기) | 명시적 제거 |
|---|---|---|---|---|
| `mp-app-dev` | 건우 · `app` | 워크로드·네트워크·관측 CR·Rollout·KEDA·ExternalSecret | `deployments`·`rollouts` patch · `pods` delete · `pods/exec`·`pods/portforward` create | secrets · serviceaccounts(+token·impersonate) · pods create · configmaps/pvc 쓰기 |
| `mp-pipeline-dev` | 건우·정은 · `pipeline` | 위 + `jobs`·`cronjobs` | 위 + `jobs` create/delete · `cronjobs` patch | 동일 |
| `mp-observability` | 정현 · `observability` | 위 + cert-manager CR + Prometheus/Alertmanager **본체 CR 읽기** | 관측 룰 CR create/patch/delete · `pods` delete · `pods/portforward` create | 위 + 🔴 **`pods/exec` · `pods create` · `deployments`/`statefulsets` patch** (§11) |
| (없음) | 봉수·태현 | `cluster-admin` 유지 | — | 장수 토큰 Secret |

`data` ns 는 **아무에게도 주지 않는다** — PG·ES·Kafka 는 CR 하나로 데이터가 죽는다(초안 기본값 ①).
⚠️ 종전 문서의 티어명 **"data-dev"(정은)는 오해를 부른다** — 실제 스코프는 `pipeline` ns 다. 이번에 `pipeline-dev` 로 정정했다.

### 실측으로 확인한 함정 (RBAC 는 틀려도 에러가 안 난다)

오타·잘못된 apiGroup 은 **조용히 아무 권한도 안 준다.** 렌더된 롤의 `(apiGroup, resource)` **67쌍을 전부 라이브와 대조**했다(미존재 0건).

| 함정 | 실측 |
|---|---|
| `events` | core `""` 와 `events.k8s.io` **둘 다 존재하고 RBAC 는 별개로 취급**한다. kubectl 은 core 를 쓴다 → `events.k8s.io` 만 적은 규칙은 무용지물. **둘 다 넣었다** |
| `pods/eviction` | 디스커버리는 kind group 을 `policy` 로 보고하지만 **RBAC 는 `""`(core)** 다. `policy` 로 적으면 무권한 |
| HPA | apiGroup 은 `autoscaling` (버전 안 붙임). `autoscaling/v2` 라는 그룹은 없다 |
| PDB | `policy` · `policy/v1` 만 서빙 |
| `deployments/scale` | 실재하나 verbs 가 **get/patch/update 뿐** — `list`·`watch` 를 적으면 데드코드 |
| `rollouts/scale` | **실재**한다(`argoproj.io`). app ns HPA 2개가 Rollout 을 겨냥하므로 실제 경로다 |
| `clustersecretstores` | **클러스터 스코프** → RoleBinding 으로는 효과 없음. 롤에서 뺐다 |
| `keda.sh` · `gateway.networking.k8s.io` | **어떤 aggregate 라벨에도 없다** → 내장 view/edit 으로는 안 보인다. 커스텀 롤에서 명시적으로 준다(실제로는 **권한이 넓어지는** 항목) |
| aggregate-to-edit | 실측 **11개**(`external-secrets-edit`·`rollouts-…-aggregate-to-edit`·ECK·cert-manager·우리가 만든 `mp-monitoring-edit` 포함). 오퍼레이터를 깔 때마다 아무도 결정하지 않은 채 늘어난다 — 커스텀 롤은 **aggregation 을 쓰지 않는다** |

### 🔴 잔여 위험 (정직하게 적는다 — "다 막았다"가 아니다)

| 잔여 | 왜 남기나 |
|---|---|
| `deployments`·`rollouts` patch = **파드 스펙 편집력** → 그 ns Secret 을 볼륨으로 붙여 간접 열람 가능 | 완전 차단은 rollout restart·카나리 promote 를 포기해야 가능. 완화 = `pods create` 가 없어 조용한 디버그 파드를 못 띄우고, 라이브 워크로드를 건드려야 해서 ArgoCD OutOfSync·감사로그에 남는다 |
| `jobs create`(pipeline) = 임의 파드 스펙 → `mp-pipeline-secrets` 열람 가능 | CronJob 수동 재실행이 크롤 운영에 필수. **0-14d(시크릿 분리)·0-16(정적 AWS 키 제거)이 이 잔여를 줄이는 항목** |
| `servicemonitors` 쓰기(관측) → 그 ns Secret 을 basicAuth 로 외부 스크레이프 대상에 실어 보낼 여지 | 룰 실험을 막으면 알림을 못 만든다(초안 기본값 ③ 유지). 1차 방어 = egress netpol |
| 전역 `view` 의 자동 확장 | `aggregate-to-view` 6개가 붙어 있고 오퍼레이터마다 는다. 2단계에서 다룬다 |
| `mp-users` 비-admin 장수 토큰 | 훔쳐도 그 사람 권한 이상을 못 얻는다 |

**이번에 실제로 사라지는 것** = cross-ns 유출 · `serviceaccounts/token` 다리(EKS 에서 IAM 롤이 되는 것) · ESO 우회로 `fb-secrets` 전량 복사(**0-14b 와 함께**) · 관측 티어의 cluster-admin 상승.

---

## 13. 적용 순서·검증·롤백

### 순서

```
1) 커스텀 롤 3종을 만든다 (바인딩 전)         ← 이 PR. 오브젝트만 생기고 아무 권한도 안 바뀐다
2) 기준선을 뜬다                              verify-rbac.sh > before.txt
3) 🔴 0-14b(ClusterSecretStore spec.conditions)를 **먼저** 넣는다
      안 하면 롤을 좁혀도 ESO 우회로 fb-secrets 6종이 그대로 샌다 → 효과 0
4) RoleBinding 을 사람 단위로 교체            defaults 의 role: 한 줄
5) 1~2주 관찰, 막히면 PR 로 넓힌다
6) EKS 에서 같은 ClusterRole 을 Access Entry kubernetesGroups 로 매핑 (C-24)
```

### 검증

```bash
ssh ubuntu@<master> 'sudo bash -s' < infra/ansible/roles/k8s_team_rbac/files/verify-rbac.sh
ssh ubuntu@<master> 'sudo bash -s' < .../verify-rbac.sh -- --list   # can-i --list 원문(diff 용)
```

**적용 전 기준선(2026-08-09 실측): `ok=70 · MISMATCH=48`.** 이 48건이 이번 작업이 닫는 대상이다.
적용 후 `MISMATCH=0` 이어야 한다.

부수 실측: 현행 edit 4개 블록(`geonu@app`·`geonu@pipeline`·`jungeun@pipeline`·`junghyun@observability`)의
`can-i --list` 출력은 **148줄이 바이트 단위로 동일**하다 — 즉 지금 "티어 3종"은 *바인딩 위치*의 구분이지
*권한 내용*의 구분이 아니었다.

### 🔴 조용히 실패하는 두 가지 (tasks 가 처리한다)

1. **`roleRef` 는 불변**이다. 같은 이름 RoleBinding 의 롤만 바꾸면 apply 가 `cannot change roleRef` 로 거부된다
   → 다르면 먼저 지우고 다시 만든다. 삭제~생성 사이 몇 초는 그 사람의 ns 권한이 없다(전역 읽기는 유지).
2. **`kubectl apply` 는 매니페스트에서 사라진 오브젝트를 지우지 않는다.** 종전 `mp-<이름>-edit` RoleBinding 이
   그대로 살아남으면 **커스텀 롤을 깔아도 실효 권한이 안 바뀐다** → 레거시 정리 태스크가 명시적으로 지운다.

### 롤백

- 사람 단위: `defaults/main.yml` 의 `role: mp-app-dev` → `role: edit` 한 줄, 재실행.
- 전체: 이 커밋 되돌리고 재실행. `admin.conf` 는 Phase 2 전까지 살아 있어 언제든 복귀 가능.
- 🔴 **되돌아가지 않는 것 하나** — admin 장수 토큰 Secret 은 지워지면 같은 값으로 안 돌아온다.
  재발급하면 새 토큰이고, 옛 kubeconfig 는 계속 무효다(그게 목적).

### 넓히는 절차 (막혔을 때)

① 본인이 `kubectl auth can-i <verb> <resource> -n <ns>` 로 확인 → ② 이슈에 **명령 원문**을 적어 요청
→ ③ 이 롤에 규칙 추가 PR → **권한 변경 이력이 git diff 로 남는다** → ④ 급하면 admin 2명이 대신 실행.
🔴 **"임시 승격"은 하지 않는다** — 임시가 영구가 된 게 지금 `admin.conf` 상태다.
