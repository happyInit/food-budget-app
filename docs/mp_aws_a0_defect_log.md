# AWS 이관 A0 — 결함 이력 (트러블슈팅 기록)

> 작성 2026-08-13. 대상 = **C-78 A0(기반: 네트워크·EKS·노드그룹·부트스트랩)** 구축 중 발견한 결함 전량.
> 근거·결정 정본은 `docs/mp_aws_prep_checklist.md` 다. 🔴 **이 문서는 결정을 담지 않는다** — *무엇이 어떻게 깨졌고 어떻게 알아냈는가* 만 담는다.
> 각 항목의 코드 주석·커밋 메시지가 1차 사료이고, 이 문서는 그것을 한 장으로 모은 색인이다.

## 왜 이 문서가 있나

A0 는 **트래픽 0 · 데이터 0** 인 유일한 구간이다(C-78). 그래서 "실패해도 잃을 게 없는 동안 결함을 다 털고 간다"가 A0 의 목적이었고, 실제로 **25건**이 나왔다. 그중 **19건은 정적 검증(`terraform validate`·`plan`·`terraform graph`·`ansible --syntax-check`)을 전부 통과한 뒤 실행에서 드러났다.**

🔴 그리고 **마지막 2건(#24·#25)은 A0 의 마지막 관문(⑦ ArgoCD)이 열린 뒤에야 드러났다.** 이것이 A0 를 트래픽 0 구간에 몰아넣은 이유를 사후에 증명한다 — **#25 는 사이드카가 주입되는 워크로드가 하나라도 생기기 전까지 관측 자체가 불가능한 결함**이었고, A2(앱 이관)에서 만났다면 원인이 PSA 로 보여 며칠을 태울 수 있었다.

🔴 **이 문서의 핵심 주장은 하나다** — *IaC 는 그려서 검증되지 않고 흘려 봐야 검증된다.* 아래 표의 "정적검증" 열이 그 근거다.

## 전량 요약

| # | 무엇이 깨졌나 | 어떻게 드러났나 | 정적검증 | 분류 |
|---|---|---|---|---|
| 1 | `aws_eks_node_group` 이 NAT 경로·라우트 연결·S3 EP·컨트롤플레인 인바운드를 **기다리지 않음** | `terraform graph` 의존성 추적 | 🟢 잡음 | 순서 |
| 2 | `eks.yml` 이 **sudo 로** 돌아 root 의 `~/.aws`·`~/.kube` 를 봄 | 렌더 리허설 | 🟢 잡음 | 환경 |
| 3 | **Cilium ↔ 노드그룹 순서** — CNI 없이 노드를 만들면 20분 뒤 `NodeCreationFailure` | 설계 검토 | 🟢 잡음 | 순서 |
| 4 | 🟡 C-56 엔드포인트 3종에 `ssm` 이 없다(C-23 과 불일치) | 정합성 검토 | 🟢 잡음 | 정합성 |
| 5 | `required_version >= 1.6` 인데 `use_lockfile` 은 **1.10+** | 실물 `init` | 🟡 실행 | 버전 |
| 6 | `-target` 2단 apply 가 **output 을 못 채워** 절차가 끊김 | 실물 `plan` | 🟡 실행 | 절차 |
| 7 | 🔴 보안그룹 `description` 에 **한글** → SG 4개 + 연쇄 17개 미생성 | **apply** | ❌ 통과 | API 제약 |
| 8 | 🔴 `aws_ec2_tag` 이 우리 리소스와 **태그 소유권 다툼** → Karpenter 디스커버리 태그 삭제 | 재-`plan` | ❌ 통과 | 소유권 |
| 9 | `kubectl --version`·`helm --version` = **없는 플래그** | Ansible 실행 | ❌ 통과 | 도구 |
| 10 | 🔴 `--profile` 부재 — 이 머신에 `[default]` 프로필이 **없다** | Ansible 실행 | ❌ 통과 | 환경 |
| 11 | 🔴 **RBAC 순환** — ClusterRole 을 만들려면 cluster-admin 이 필요한데 그게 없다 | Cilium 설치 | ❌ 통과 | 순환 의존 |
| 12 | 🔴 gp2 조회 **403 을 "없음"으로** 읽음 → 0-8e ① 이 조용히 무력화될 뻔 | 로그 정독 | ❌ 통과 | 오탐 |
| 13 | 🔴🔴 **클러스터 SG 에 443 인그레스 부재** → 노드가 클러스터에 못 붙음 | 노드그룹 apply | ❌ 통과 | 연결성 |
| 14 | 🔴 **IRSA 가 조용히 안 붙음** — helm 값 키 오타(`operator.serviceAccount`) | operator CrashLoop | ❌ 통과 | 조용한 무시 |
| 15 | 🔴 operator 파드에 **리전 변수 부재** → ENI 할당 통째로 실패 | operator CrashLoop | ❌ 통과 | 조용한 무시 |
| 16 | 🔴 IRSA 정책에 **`ec2:DescribeRouteTables` 누락** | operator CrashLoop | ❌ 통과 | 권한 목록 |
| 17 | 🟡 `eni.firstInterfaceIndex`·`eni.securityGroupTags` 가 **ConfigMap 에 안 나타남** | ConfigMap 실측 | ❌ 통과 | 조용한 무시 |
| 18 | Jinja `default('')` 가 **`None` 을 통과시킨다**(`default('', true)` 여야 함) | 애드온 실행 | ❌ 통과 | 언어 함정 |
| 19 | 🔴 **버전 핀 3개가 틀렸다** — cert-manager·ESO·ArgoCD. ESO 는 **CRD 가 `v1beta1`↔`v1` 로 갈리는 차이** | 온프렘 `helm list -A` 대조 | ❌ 통과 | 온프렘 미대조 |
| 20 | `istio/cni` 의 `cniBinDir`·`cniConfDir` 를 **최상위에 씀**(키는 `cni.` 아래) | `helm show values` 대조 | ❌ 통과 | 조용한 무시 |
| 21 | 🔴 Cilium `cni.exclusive` 기본값 **true** → istio-cni 와 CNI 설정 무한 전쟁 → readiness 503 | helm `--wait` 타임아웃 | ❌ 통과 | 부품 상호무지 |
| 22 | 🔴 **ConfigMap 을 바꿔도 도는 파드는 옛 값을 쓴다** — `cni-exclusive:false` 가 37분째 미반영 | 파드 age 실측 | ❌ 통과 | 생성 순서 |
| 23 | 🔴🔴 **`argocd-secret` 을 helm 뒤에 만들어 데드락** — 파드는 시크릿을, helm 은 파드를 기다림 | helm `--wait` 타임아웃 | ❌ 통과 | 생성 순서 |
| 24 | 🔴🔴 **ESO 를 SSM ParameterStore 로 지음** — C-36 이 이미 Secrets Manager 로 정정한 것 | 사용자 지적 | ❌ 통과 | 정본 오독 |
| 25 | 🔴🔴 **istiod 에 `pilot.cni.enabled` 누락** → 주입 파드가 `istio-init`(NET_ADMIN)을 받아 **PSA `restricted` 가 전량 거부** | ⑦ 개방 후 `FailedCreate` | ❌ 통과 | 부품 상호무지 |

**정적검증 통과율**: `validate`·`plan`·`graph`·`syntax-check` 는 **19건(#7~#25)을 전부 초록으로 통과시켰다.**
정적으로 잡은 것은 **4건(#1~#4)** — 그중 #4 는 사후에 **오진이었음이 밝혀졌다**(아래 분류 ⑦).

## 🔴 분류 — 정적 검증이 구조적으로 못 잡는 7가지

### ① "조용한 무시" — helm/차트가 모르는 값을 에러 없이 버린다 (#14 · #15 · #17 · #20)

**가장 위험한 부류다.** 릴리스는 `deployed` 가 되고, 없는 것은 없는 채로 돈다.

```
❌ operator.serviceAccount.annotations      ← 차트가 모르는 키. 조용히 무시
🟢 serviceAccounts.operator.annotations     ← Cilium 차트의 실제 키
```

⇒ **대책 = 값이 실물에 반영됐는지 조회해서 assert 한다.** `eks_cilium` 롤에 그 태스크를 넣었다(SA 어노테이션 실측 후 `irsa_cilium_operator` 와 비교). "helm 이 성공했다"를 성공으로 읽지 않는 것이 유일한 방어다.

### ② "그래프에 없는 것은 그래프로 못 찾는다" (#13)

`terraform graph` 는 **있는 것들의 순서**만 본다. #1 은 그것으로 잡혔지만(의존성 누락), #13 은 **규칙 자체가 없었다** — 없는 노드는 그래프에 나타나지 않는다.

⇒ **대책 = 연결성은 흘려 봐야 검증된다.** `hostNetwork` 파드로 실제 TCP 를 쏘는 방법이 A0 에서 가장 효과적인 진단 도구였다(아래 §진단 도구).

### ③ "API 쪽 제약" — 문법은 맞는데 값이 거부된다 (#7)

```
InvalidParameterValue: … for parameter GroupDescription is invalid.
Character sets beyond ASCII are not supported.
```
`plan` 은 문자셋을 검증하지 않는다. 그리고 **서비스마다 다르다** — 같은 한글 description 이 ECR lifecycle policy 18개에서는 **전부 성공**했다.

### ④ "권한 목록은 돌려 봐야 완성된다" (#16 · #11)

문서를 읽어 만든 IAM 목록에서 `ec2:DescribeRouteTables` 하나가 빠졌고, 그 하나로 ENI 할당이 통째로 멈췄다. IAM 은 문법이 맞으면 `plan` 이 통과시킨다.

### ⑤ 🔴 "온프렘 실물을 대조하지 않은 것" (#19 · #25)

**이 프로젝트에는 같은 스택이 이미 1년째 돌고 있다.** 그런데 두 결함은 내가 그 라이브를 안 보고 문서·기억으로 값을 지어서 났다.

| | 내가 쓴 것 | 온프렘 라이브 | 대가 |
|---|---|---|---|
| #19 ESO | `2.8.0` | `0.20.2` 계열 | 🔴 **CRD 가 `v1beta1`↔`v1`** — 매니페스트가 통째로 안 맞는다 |
| #19 ArgoCD | `8.0.10` | `10.2.1` | 메이저가 갈려 AppProject 해석이 달라질 수 있다 |
| #25 istiod | `pilot.cni` 없음 | `pilot.cni.enabled: true` | **사이드카 주입 워크로드 전량 기동 불가** |

⇒ **대책 = 온프렘에 같은 컴포넌트가 있으면 값을 짓지 말고 뜬다.**
```bash
ssh ubuntu@192.168.0.17 'sudo helm list -A'                       # 버전 핀의 정본
ssh ubuntu@192.168.0.17 'sudo helm -n <ns> get values <release>'  # 값의 정본
```
🔴 **`helm list` 만으로는 #25 를 못 찾는다** — 버전은 같았다(둘 다 istio 1.30.3). **`get values` 를 봐야** 나온다. 즉 대조는 *버전*이 아니라 *값*까지 가야 한다.

### ⑥ 🔴 "체인의 두 부품이 서로를 모른다" (#21 · #25)

둘 다 **Cilium + istio-cni** 조합에서 났고, 원인이 같다 — **CNI 체이닝은 세 부품(Cilium · istio-cni · istiod)의 합의인데 그 합의를 아무도 강제하지 않는다.**

```
#21  Cilium 이 cni.exclusive=true (기본값)  →  istio-cni 의 설정을 계속 지운다
                                              → istio-cni 영구 NotReady · helm --wait 사망
#25  istiod 가 istio-cni 의 존재를 모른다   →  initContainer 를 istio-init 으로 넣는다
                                              → NET_ADMIN 요구 → PSA restricted 가 거부
```
🔴 **양쪽 다 "설치는 성공"이다.** `kubectl get ds istio-cni-node` 는 `2/2 Ready` 를 보여준다. 부품이 다 초록인데 체인이 안 선다.

⇒ **대책 = 체인은 "부품이 떴나"가 아니라 "합의가 성립했나"로 검증한다.** A0 에서 쓴 두 지표:
```bash
# ① CNI 설정 파일에 istio-cni 가 살아남았나 (= #21 이 안 났나)
kubectl -n istio-system exec ds/istio-cni-node -- \
  grep -o istio-cni /host/etc/cni/net.d/05-cilium.conflist
# ② 주입된 파드의 initContainer 이름 (= #25 가 안 났나)
kubectl -n app get pod -o jsonpath='{.items[0].spec.initContainers[*].name}'
#    istio-validation → CNI 모드 ✅ / istio-init → 비-CNI 모드 ❌
```

### ⑦ 🔴 "정정된 결정의 본문을 읽었다" (#4 · #24) — **가장 뼈아픈 부류**

체크리스트의 결정 행은 정정되면 **머리말이 앞에 붙고 정정 전 본문은 이력으로 남는다**:

```
| C-23 | 🔄 정정(2026-08-10, C-36) — 백엔드가 SSM → Secrets Manager.  ← 이게 현재
         … AWS = SSM standard 번들 6 + IRSA …                        ← 이건 이력
```
나는 **아래 절반을 읽었다.** 그 결과가 두 개다:
- **#24** ESO 를 ParameterStore 로 지었다(스토어·IAM·ExternalSecret 3층 전부).
- **#4** — 처음에 *"C-56 엔드포인트 3종에 `ssm` 이 없다. `secretsmanager` 는 소비자가 없다"* 를 **정합성 문제로 기록**했는데, 사실은 **C-56 이 옳고 내 전제가 틀렸다.** 즉 #4 는 결함이 아니라 **내 오독이 만든 유령**이었다. 🔴 그리고 그걸 "받아들인 위험"으로 `variables.tf` 에 명문화까지 해뒀다 — **잘못된 진단이 문서에 정착하는 경로**를 그대로 보여준다.

⇒ **대책 두 개.**
1. **정정된 행은 머리말이 본문을 이긴다.** 본문은 사료다.
2. 🔴 **워킹카피가 stale 이면 이 대책도 무용하다.** #24 를 검증하려고 grep 했을 때 로컬 `main` 이 **`origin/main` 보다 57 결정 뒤처져 있었고**(`maxC=29` · 2,652줄 vs `maxC=86` · 4,789줄) 그래서 `C-56` 이 "없다"고 나왔다. **정본을 인용하기 전에 `git fetch` 로 최신인지 먼저 확인한다.**

### ⑧ "생성 순서 의존" (#14 · #22 · #23)

K8s 는 선언적이지만 **주입은 생성 시점에 한 번**이다. 이 셋은 전부 그 틈에서 났다.

| | 무엇이 나중에 와서 안 먹혔나 |
|---|---|
| #14 | SA 어노테이션(IRSA) — **웹훅이 파드 생성 시점에** 토큰을 주입한다 ⇒ 도는 파드는 영원히 노드 롤 |
| #22 | ConfigMap(`cilium-config`) — 파드 템플릿이 안 바뀌면 helm 은 **롤아웃을 일으키지 않는다** |
| #23 | `argocd-secret` — helm `--wait` **앞에** 있어야 한다. 뒤면 교착 |

🔴 **#22 는 CLAUDE.md 가 온프렘 교훈으로 이미 적어둔 것과 같은 함정이다** — *"`envFrom.configMapRef` 는 파드 기동 시점에 주입된다 … `rollout restart` 가 별도로 필요하다."* **온프렘에서 배운 것이 AWS 에서 그대로 재현됐다.**

⇒ **대책 = 값을 바꾼 태스크가 `changed` 면 그 워크로드를 굴린다.** `eks_cilium` 롤에 `rollout restart ds/cilium` 을 `when: helm.changed` 로 넣었다.

## 상세 — 특히 배울 것이 있던 5건

### 🔴 #13 클러스터 SG 443 — *가장 조용하고 가장 늦게 드러난다*

**증상**: 노드그룹이 `status: CREATING` · `health.issues: []` 인데 `kubectl get nodes` 가 10분 넘게 `No resources found`. EC2 는 2대 Running, ASG desired 충족. **정상 진행과 구분할 방법이 없었다** — 약 20분 뒤 `NodeCreationFailure: Instances failed to join the kubernetes cluster` 로 죽는 경로였다.

**원인**: EKS 가 만드는 클러스터 SG 의 기본 규칙은 *"자기 자신에서 오는 트래픽 전부 허용"* **하나뿐**이다. 런치 템플릿에 `vpc_security_group_ids` 를 지정하면 EKS 의 기본 SG 부착이 **대체**되므로 노드는 클러스터 SG 를 달지 않는다 → 사설 API 엔드포인트(443)에 닿지 못해 **kubelet 이 등록조차 못 한다.**

🔴 **공개 엔드포인트(C-80)를 켰는데도 막히는 이유** = `endpoint_private_access = true` 면 VPC 안에서 클러스터 DNS 가 **사설 ENI 주소로 해석**된다. 노드는 공개 IP 로 가지 않는다. *"공개 엔드포인트가 있으니 노드도 그리로 가겠지"* 는 틀렸다.

**고침**: 클러스터 SG 에 노드 SG 출처 443 인그레스. **규칙 투입 10초 만에 노드 2대 등록 · 1분 30초 뒤 둘 다 Ready.**

**기각한 대안**: 런치 템플릿에 클러스터 SG 를 함께 붙이기(= EKS 기본 동작) → 🔴 **파드가 낫지 않는다.** Cilium ENI IPAM 은 `securityGroupTags` 로 보조 ENI 의 SG 를 고르므로 클러스터 SG 는 파드 ENI 에 붙지 않는다. kubeProxyReplacement 아래서 파드가 `kubernetes.default` 로 가면 API 서버 사설 ENI 로 **직접** 나가므로 파드도 443 이 필요하다 ⇒ **노드 SG 를 출처로 여는 방식이 파드까지 함께 덮는다.**

**절차 기록**: 노드그룹 apply 가 **state 락을 잡고 있어** Terraform 으로 즉시 고칠 수 없었고 20분 타이머가 먼저 끝날 상황이었다. ⇒ `aws ec2 authorize-security-group-ingress` 로 먼저 투입 → `terraform import` 로 인수 → apply 후 **`No changes. Your infrastructure matches the configuration.`** 로 드리프트 0 확인. 🔴 `terraform destroy` 하지 않고 `import` 한 것이 요점이다.

### 🔴 #15 리전 변수 부재 — *가설을 하나씩 실측으로 기각한 사례*

**증상**: `Failed initial EC2 API limits update: timed out waiting for the condition` → `Unable to start eni allocator` → operator CrashLoop → 에이전트 `required=2 available=0` → **파드 IP 0개.**

| 가설 | 검증 방법 | 결과 |
|---|---|---|
| IAM 권한 부족 | 정책 전수 확인 | ❌ 403 아니라 timeout |
| DNS 실패 | `ClusterFirst`+hostNetwork 동작 | ❌ `Default` 로 다운그레이드(노드 resolv.conf) |
| SG·서브넷 오배치 | EP 서브넷 vs 노드 서브넷 대조 | ❌ 일치 · 443 규칙 정확 |
| 네트워크 도달 불가 | **hostNetwork 파드로 TCP 실측** | ❌ STS(사설 EP) OK · EC2(NAT) OK |
| IRSA 자체 실패 | **operator SA 로 `sts get-caller-identity`** | ❌ **0.61초** 성공 |
| API 지연 > 5초 예산 | **`DescribeInstanceTypes` 250종 실측** | ❌ **1.55초** |
| 🔴 **리전 변수 부재** | 두 파드의 env 대조 | ✅ 검사 파드엔 있고 operator 엔 없다 |

**메커니즘**(미묘하다): 차트가 `AWS_DEFAULT_REGION` 을 **존재하지 않는 optional 시크릿**(`cilium-aws`)에서 가져오도록 선언한다. 그 선언이 있기 때문에 ① EKS 웹훅이 *"리전 변수가 이미 있다"* 로 보고 **주입을 건너뛴다** ② 시크릿이 없으니 런타임엔 **비어 있다** ③ `AWS_STS_REGIONAL_ENDPOINTS=regional` + 리전 없음 → STS 엔드포인트를 만들 수 없다 → 자격증명 해석 실패 → 5초 폴링 타임아웃.

④ 🔴 **같은 이름으로 덮어쓸 수도 없다** — env 리스트에 중복이 생겨 전략적 병합 패치가 깨진다:
```
Error: UPGRADE FAILED: failed to create patch: The order in patch list …
doesn't match $setElementOrder list
```
⇒ 통하는 것은 **`AWS_REGION`**(SDK 가 `AWS_DEFAULT_REGION` 보다 먼저 보는 변수) 하나뿐이다.

⚠️ **결함이 결함을 가리고 있었다** — #14(IRSA) 전에는 IMDS 자격증명 경로에서 리전도 IMDS 로 발견되므로 EC2 가 *응답*(403)을 줬다. #14 를 고치자 #15 가, #15 를 고치자 #16 이 드러났다.

### 🔴 #11 RBAC 순환 — *C-24 에 예외를 하나 만들게 한 결함*

```
Error: list: failed to list: secrets is forbidden: User "…:user/mp-platform"
cannot list resource "secrets" in API group "" in the namespace "kube-system"
```

`bootstrap_cluster_creator_admin_permissions = false`(C-24) 라 클러스터를 만든 주체조차 인가가 0 이고, `mp:admin` 의 실권한은 Ansible `eks_rbac` 가 만드는 ClusterRole 이 정한다. **그런데 ClusterRole 을 만드는 것 자체가 cluster-admin 이다.** ⇒ 인증은 되나 인가 0 으로 잠긴다. 첫 희생자가 Cilium 설치였다(helm 이 kube-system 릴리스 시크릿을 읽는다).

**고침**: `aws_eks_access_policy_association` + 새 변수 `cluster_bootstrap_admin_principals`.
🔴 **C-24 를 뒤집는 것이 아니다** — C-24 가 막은 것은 *사람에게 관리형 정책으로 권한을 주는 것*이고, 여기 것은 **부트스트랩 주체 1개**다. 팀원은 그대로 커스텀 `mp:admin` ClusterRole 로 간다 ⇒ **변수를 따로 둔 이유가 이것이다.**

**기각한 대안**: `bootstrap_cluster_creator_admin_permissions = true` → 그 필드는 **ForceNew** 라 이미 만든 클러스터를 파괴·재생성한다(8분 + 116개 재배선). 그리고 권한이 코드에 보이지 않는다.

🟢 **영구히 둔다** — 커스텀 ClusterRole 이 깨졌을 때 되돌아갈 문이 없으면 영구히 잠긴다. 온프렘 RBAC Phase1 에서 `admin.conf` 를 살려 둔 것과 같은 판단이다.

### 🔴 #8 `aws_ec2_tag` 태그 소유권 — *가장 조용한 위험*

`karpenter.sh/discovery` 를 `aws_ec2_tag` 로 붙였는데 `aws_subnet.node.tags` 가 그 키를 선언하지 않아 **서브넷이 그 태그를 지우려 했다**(재-plan 이 `2 to change` = 태그 제거).

🔴 왜 위험한가 = **조용하다.** apply 순서에 따라 태그가 실제로 사라지고, 그러면 Karpenter `subnetSelectorTerms` 가 0건을 돌려주며 **층2 노드가 에러 없이 영구히 프로비저닝되지 않는다.** C-87 에 *"태그 없으면 노드 영구 미생성"* 으로 적어 둔 함정을 코드로 만들어 둔 셈이었다.

**원인**: `aws_ec2_tag` 은 **이 Terraform 이 관리하지 않는** 리소스용이다. 우리 소유 리소스에 쓰면 리소스 쪽이 자기 `tags` 에 없는 키를 드리프트로 보고 지운다.

**state 처리**: `terraform state rm` 으로 잊게 했다 — `destroy` 하면 AWS 의 태그가 실제로 지워지는데 그 시점에 서브넷 쪽은 이미 `no diff` 라 아무도 되돌려주지 않는다.

### 🔴 #12 gp2 403 을 "없음"으로 — *오탐이 정책을 무력화하는 경로*

`failed_when: false` + `rc == 0` 게이트라 **"없다" 와 "못 읽었다" 가 구분되지 않았다.** #11 국면(403)에서 실제로 이 상태를 봤다 → gp2 가 default 로 남고 이후 PVC 가 **`gp3-retain` 대신 gp2(Delete)** 에 붙어 **0-8e ① 이 통째로 무력화**된다. 사고는 그 PVC 를 지울 때 처음 드러난다.

⇒ **"없다"는 NotFound 로만 판정**하고 그 밖의 실패는 시끄럽게 죽는 assert 를 넣었다.

## 진단 도구 — A0 에서 실제로 효과가 있었던 것

### 🟢 `hostNetwork` 검사 파드 — CNI 가 없어도 뜬다

CNI 가 없으면 파드가 IP 를 못 받아 아무것도 못 띄운다. **그런데 `hostNetwork: true` 파드는 CNI 없이 뜬다.** 이것이 A0 진단의 열쇠였다.

```bash
kubectl run netcheck -n kube-system --image=public.ecr.aws/docker/library/busybox:1.36 \
  --restart=Never --overrides='{"spec":{"hostNetwork":true,"tolerations":[{"operator":"Exists"}]}}' \
  --command -- sh -c 'nslookup sts.ap-northeast-2.amazonaws.com; nc -w 5 -z sts.ap-northeast-2.amazonaws.com 443'
```

### 🟢 문제 워크로드의 **SA 로** 자격증명을 재본다

IRSA 가 실제로 되는지 / 지연이 얼마인지를 한 번에 가린다. `serviceAccountName` 을 그 워크로드와 같게 두는 것이 요점이다.

```yaml
spec:
  serviceAccountName: cilium-operator     # ← 문제 워크로드와 동일
  hostNetwork: true
  containers:
  - image: public.ecr.aws/aws-cli/aws-cli:2.17.20
    command: ["/bin/sh","-c"]
    args: ["aws sts get-caller-identity; time aws ec2 describe-instance-types --query 'length(InstanceTypes)'"]
```

### 🟢 helm 값이 아니라 **결과물**을 본다

```bash
kubectl -n kube-system get cm cilium-config -o json      # 값이 실제로 반영됐나
kubectl -n kube-system get sa cilium-operator -o json    # 어노테이션이 붙었나
```
#14·#15·#17 은 전부 이 방법으로만 드러났다.

### ⚠️ 감시 스크립트도 검증 대상이다

노드그룹을 감시하는 스크립트를 짰는데 `describe-nodegroup` 의 응답이 `nodegroup.` 아래로 감싸여 있는 것을 놓쳐 **실패 탐지가 항상 빈 문자열**이었다 — 즉 **침묵이 성공으로 읽히는** 감시였다. 감시를 걸 때는 *"지금 이게 실패하면 내 필터가 뭔가 뱉는가"* 를 먼저 물어야 한다.

## 이 결함들이 정본에 남긴 정정

| 대상 | 정정 |
|---|---|
| `eks_nodegroup.tf` | *"hop limit 1 이면 파드가 IMDS 에 닿지 못한다"* → **hostNetwork 파드에는 적용되지 않는다**(#14 로 실증) |
| `A-21` | 라우팅 테이블 "2개" → **3개**(공개·노드·데이터 격리) |
| `C-24` | 예외 1개 신설 — 부트스트랩 주체에 한해 관리형 access policy(#11) |
| `C-71` | −$39.42/월 은 NAT 회피분만 센 값 → 공인 IPv4 약 $3.6/월 을 빼면 **실절감 약 $35.8/월** |
| C-16 PVC 표 | 🔴 **Kafka 30 GiB 는 AWS 로 안 간다**(C-3 = 온프렘 크롤 상시). AWS 실제는 **18 PVC · 95 GiB** 로 보이며 A1 에서 실물 확정 |
| `locals.tf`·`variables.tf` | 🔴 **#4 로 적어둔 "정합성 문제"·"받아들인 위험" 전량 철회**(#24) — C-56 의 3종은 처음부터 정합했고, *"ESO 호출이 NAT 를 탄다"* 는 상황은 **존재하지 않는다** |
| `bootstrap/eso/README.md`(config) | **4KB 천장 논거 전량 소멸** — SM 은 64KB·티어 없음. `pg-roles` 분리 근거도 4KB → **폭발 반경 분리**로 교체 |
| 온프렘 비밀 실측 | 정본 `6종 / 37키` ↔ 실측 **6종 36키**(+ `repo-food-budget-config` 3키 = 7종 39키). 🔴 **1키 어긋난다** — "키별 34" 라는 수치가 이 위에 서 있으므로 **A1 적재 직전 재실측** |

## 미해결

- **#17** `eni.firstInterfaceIndex: 1` · `eni.securityGroupTags` 가 `cilium-config` 에 나타나지 않는다.
  실물 = Cilium 이 만든 ENI **0개**, 노드 1차 ENI(idx 0)에 보조 IP **12·11개**.
  🟡 지금은 고장이 아니다(1차 ENI 에 이미 노드 SG 가 붙어 있어 파드가 올바른 SG 를 물려받는다 = A-44 가정과 일치).
  🔴 다만 파드가 늘어 Cilium 이 **새 ENI 를 만들 때** `securityGroupTags` 가 없으면 SG 를 **추정**한다.
  ⇒ 정확한 차트 키를 확인해 고친다. A1·A2 에서 터지면 원인 찾기가 훨씬 어렵다.
- ~~**#4** C-56 ↔ C-23 불일치~~ → 🔴 **결함이 아니었다**(#24 로 판정 역전). 위 분류 ⑦ 참조.
- **미결 ⑰ KMS 키** — 지금은 `aws/secretsmanager`(AWS 관리 · $0)로 돌고 있고 **`kms:Decrypt` 없이 동작함을 실증**했다. CMK 로 가면 `kms:Decrypt` + **A-26**(키 정책에 롤 ARN 명시)이 함께 필요. 🟢 `update-secret --kms-key-id` 로 되돌릴 수 있어 편도가 아니다.
- 🔴 **config `argocd/overlays/eks` 가 미완** — 자식 Application 23개의 `source.path` 가 아직 `overlays/onprem` 을 가리킨다(config 자신이 *"아직 안 했다 · 초록 = 이관 준비 완료가 아니다"* 라고 적어둔 Wave B). ⑦ 이 열리자 EKS 가 **Harbor `192.168.0.10` 에서 이미지를 당기려 하는 상태**가 됐다(`ImagePullBackOff` 19).
  🟢 **비용 영향 0 실측** — Karpenter NodeClaim **0개** · 노드 2대 유지. Unschedulable 2개는 CPU 부족이 아니라 **PVC 미바인딩**(`openebs-lvm` SC 잔여 · 0-8)이라 증설로 풀리지 않아 Karpenter 가 움직이지 않는다.
  ⇒ **처리 순서 = 사용자 결정(2026-08-13): CI(A0.5) 를 먼저 올리고 그 뒤에 path 를 `overlays/eks` 로 뒤집는다.** 근거 = 지금 뒤집어도 **ECR 이 0개 이미지**라 어차피 안 뜬다.

## A0 최종 실증 (2026-08-13)

| | |
|---|---|
| Terraform | **118개 · `No changes`**(드리프트 0) |
| 노드 | `m7g.xlarge` × 2 · **arm64** · `v1.34.9-eks` · AZ 당 1대 |
| **C-82(ENI 모드)** | 🟢 `hubble-relay` 파드 IP **`10.10.75.123`** (노드 `10.10.64.103`) — **노드 서브넷 `10.10.64.0/20` 안의 VPC 주소**. 오버레이(`10.244.x`) 없음 |
| C-82 게이트 | vpc-cni·kube-proxy **부재** 실증 |
| Cilium | 에이전트 **2/2 Ready** · operator **1/1**(재시작 0) · `cluster-name = mp-eks` |
| 0-8e ① | `gp2` 의 `is-default-class = false` 실증 |
| IRSA | `assumed-role/mp-cilium-operator` 로 EC2 호출 성공 |
| **비밀(C-36)** | 🟢 `mp-aws-secrets` = `SecretsManager` · **Valid** · prefix `mp/prod/`. `mp/prod/repo-mealplanning-config`(ed25519 432 B · JSON 3키) → ExternalSecret **SecretSynced**. 🟢 **`kms:Decrypt` 불요 실증** |
| **CNI 체인** | 🟢 `05-cilium.conflist` 에 `istio-cni` 생존(#21) + 주입 파드 initContainer = **`istio-validation`**(#25) — 두 지표 모두 통과 |
| **⑦ ArgoCD** | 🟢 뿌리 2개가 config 를 읽어 **자식 Application 49개** 생성 · `platform-root` **Synced/Healthy** · AppProject 4+default |
| 최종 `eks.yml` | `ok=57 · changed=8 · failed=0` (멱등) |

### 🔴 A0 가 남긴 한 줄

**부품을 다 초록으로 만드는 것과 체인이 서는 것은 다른 일이다.**
25건 중 정적 검증이 잡은 것은 4건(그중 1건은 오진), 나머지 21건은 **흘려 봐야** 나왔다.
그리고 마지막 2건은 **A0 의 마지막 관문이 열린 뒤에야** 나왔다 — *결함은 관측 가능해지는 순서로 나온다.*
