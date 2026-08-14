# AWS 접속 세팅 — 팀 안내

> **§1 = 팀원용**(그대로 읽으면 됨) · **§2 = 관리자용**(사람을 새로 붙일 때) · **§3 = 지금 막혀 있는 것**
>
> 관련 결정 = **C-80**(비대화형 접근 필수) · **C-35**(Identity Center 미채택 = 브라우저 로그인 없음) ·
> **C-24**(사람 신원 = Access Entry `kubernetesGroups` + 커스텀 ClusterRole) · **C-85**(내부 도구 = LB 0개) ·
> **C-37**(CI 서버 키페어 금지) · **C-83**(온프렘 형상 동결).

---

## §1 팀원용

이제 EKS 클러스터에 **각자 노트북에서 직접** 붙습니다. 온프렘처럼 `ssh wsl-dev` 를 경유하지 않습니다.
(온프렘 클러스터는 **그대로** `ssh wsl-dev` 를 씁니다 — 두 사이트가 당분간 같이 삽니다.)

### 0. 받는 것

- IAM 사용자 이름 + Access Key ID / Secret Access Key — **DM 으로** 전달
- 권한 등급: `admin`(전체) 또는 `viewer`(읽기 전용)

🔴 Secret Access Key 는 **발급 때 한 번만** 보입니다. 못 받았으면 재발급 요청하세요.
🔴 **어디에도 커밋하지 마세요.** `food-budget-app` 레포는 공개입니다.

### 1. 설치 (한 번만)

- **AWS CLI v2**
- **kubectl** — 클러스터가 1.34 이니 1.33~1.35 중 아무거나
- **session-manager-plugin** — 6번(SSM) 쓸 사람만

### 2. 자격증명 등록

```bash
aws configure --profile mp
#   AWS Access Key ID     : (전달받은 값)
#   AWS Secret Access Key : (전달받은 값)
#   Default region name   : ap-northeast-2
#   Default output format : json

aws sts get-caller-identity --profile mp     # 본인 ARN 이 나오면 성공
```

### 3. kubectl 붙기 (전원)

```bash
aws eks update-kubeconfig --name mp-eks --region ap-northeast-2 --profile mp
kubectl get nodes
kubectl -n app get pods
```

🔴 **`Unauthorized` 가 나오면** IAM 은 통과했는데 **클러스터 등록(Access Entry)이 안 된 것**입니다.
키 문제가 아니니 재발급 요청하지 마시고, `aws sts get-caller-identity` 로 나온 **ARN 을 그대로 전달**해주세요.

### 4. 내 권한이 뭔지

| 등급 | 할 수 있는 것 |
|---|---|
| `admin` | 전부 |
| `viewer` | **읽기만** — `get`/`list`/`watch`. 배포·수정·Secret 값 읽기는 안 됩니다 |

### 5. 내부 도구(Grafana·ArgoCD 등) 보는 법 — 도메인이 없습니다

```bash
kubectl -n observability port-forward svc/<서비스> 3000:80
# → 브라우저에서 localhost:3000
```

AWS 쪽엔 내부 도구용 주소를 **안 만듭니다**(LB 비용 0으로 가기로 했습니다 — C-85).
🟢 온프렘은 SSH + port-forward **2겹**이었는데 여기는 **1겹**이라 오히려 편합니다.

### 6. SSM — CI 서버 셸 (필요한 사람만)

GitLab CI 서버는 **SSH 키도 22 포트도 없습니다.** 의도한 것이고(C-37), 들어가는 유일한 길이 SSM 입니다.

```bash
aws ssm start-session --target <인스턴스ID> --region ap-northeast-2 --profile mp
```

🔴 **대부분은 필요 없습니다** — GitLab 은 `https://gitlab.mealbong.cloud` 웹 UI 로 쓰시면 됩니다.
서버 안에서 뭘 고쳐야 할 때만 쓰고, 그때 인스턴스 ID 를 받아 가세요.

### 7. 🔴 하지 말아주세요

- **`terraform apply`** — 지금 데이터 티어·앱 두 레인이 **같은 state** 를 씁니다. 돌리기 전에 물어봐주세요.
- **온프렘 클러스터 형상 변경** — 이관이 끝날 때까지 동결입니다(되돌릴 원본이라서요 · C-83).
- **`kubectl get secret -o yaml`·`-o jsonpath`** — 값이 터미널과 기록에 남습니다. 키 목록만 볼 땐 `kubectl describe secret`.
- Access Key 를 공용 채널·이슈·PR 에 붙여넣기.

막히면 채널에 **에러 메시지 그대로** 올려주세요. `Unauthorized` 와 `AccessDenied` 는 원인이 완전히 다릅니다.

---

## §2 관리자용 — 사람을 새로 붙이는 절차

🔴 **IAM 사용자를 만드는 것만으로는 `kubectl` 이 되지 않는다. 층이 세 개다.**

```
① IAM 사용자 + Access Key   → aws sts get-caller-identity 가 된다
② eks:DescribeCluster       → aws eks update-kubeconfig 가 된다   ← 없으면 AccessDeniedException
③ EKS Access Entry          → kubectl 이 된다                     ← 없으면 Unauthorized
```

🔴 **②는 2026-08-14 실측에서 뒤늦게 찾았다** — 이 문서의 초판은 ①③ 두 단계라고 적었다.
②가 없으면 **kubeconfig 파일 자체가 안 만들어져서** ③까지 가지도 못한다. 증상이 다른데
**셋 다 "키가 잘못됐나?" 로 읽히는 메시지**라 재발급 요청이 돌아온다.
③이 없으면 `error: You must be logged in to the server (Unauthorized)` 가 나는데, 변수 설명이
그 함정을 이미 적고 있다 — *"비어 있으면 아무도 클러스터에 들어갈 수 없다 — 클러스터를 만든 주체조차"*.

### ②③ 실제 배선 — `infra/terraform/aws-platform/iam_team.tf`

**②** = IAM 정책 `mp-team-dev` 가 그룹 `mealplanning-dev` 에 붙는다(`eks:DescribeCluster` + SSM).
**③** = 그 **그룹 멤버십에서 Access Entry 가 파생된다.** 사람 목록을 tfvars 에 손으로 적지 않는다 —
tfvars 는 gitignored 라 워크트리마다 사본이 갈리고, **옛 사본을 든 세션이 apply 하면 Access Entry 를
조용히 지운다.** 대가 = *"그룹에 넣으면 조용히 클러스터 admin 이 된다"* 는 암묵성이다.

| 경로 | 그룹 | 실권한 |
|---|---|---|
| `iam_team.tf` — IAM 그룹 파생 | `mp:admin` | ClusterRole `mp-admin` (`*` on `*`) |
| `cluster_admin_principals` — 명시 | `mp:admin` | 〃 |
| `cluster_viewer_principals` — 명시 | `mp:viewer` | ClusterRole `mp-viewer` (get/list/watch) |

🔴 **여기 넣는 것은 그룹 매핑뿐이다.** 실제 권한은 Ansible `eks_rbac` 가 만드는 ClusterRole 이 준다
— Terraform 만 고치고 `eks.yml` 을 안 돌리면 그룹은 생겼는데 아무 권한이 없다.

🔴 **`cluster_bootstrap_admin_principals` 에 팀원을 넣지 말 것.** 그건 플랫폼 운영 주체 1개 자리이고
`AmazonEKSClusterAdminPolicy`(관리형)를 붙인다. 사람은 커스텀 ClusterRole 로 가는 게 C-24 다.

### 추가 순서

1. IAM 사용자 생성 + Access Key 발급 → **DM 으로만** 전달
2. **IAM 그룹 `mealplanning-dev` 에 넣는다** — 🔴 이것이 곧 "클러스터 admin 을 준다"는 뜻이다
3. `terraform plan` → 🔴 **destroy 줄이 0인지 확인** (다른 레인 리소스를 지우지 않는지)
4. `terraform apply` — 🔴 **`main` 을 리베이스한 워크트리에서** · 한 번에 한 레인만
5. 아래 검증 → 본인에게 `kubectl get nodes` 확인 요청

### 검증 — 사람을 붙잡지 않고 확인하는 법

```bash
# ② IAM 층
aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::<계정>:user/<이름> \
  --action-names eks:DescribeCluster --resource-arns <클러스터 ARN>      # allowed

# ③ K8s 층 (가장)
kubectl auth can-i get pods -n app --as=<이름> --as-group=mp:admin       # yes
kubectl auth can-i get pods -n app --as=<이름>                            # no  ← 대조군
```

🔴 **대조군을 같이 돌려야 의미가 있다** — `yes` 만 보면 그 사람이 다른 경로로 권한을 갖고 있어도
통과로 읽힌다. 🔴 서브리소스는 `--subresource` 로 본다: `can-i create serviceaccounts/token` 의
`token` 이 **리소스 이름으로 해석돼** 검증이 통째로 헛돈 적이 있다(`0-14` · #587).

### 제거할 때

IAM 그룹에서 빼고 apply 하면 Access Entry 가 사라져 **클러스터 접근이 끊긴다.**
🔴 다만 **IAM Access Key 는 따로 비활성/삭제해야 한다** — 그게 남아 있으면 S3·Bedrock 등 IAM 쪽 권한은 그대로다.

---

## §3 상태 — ✅ 해소됨 (2026-08-14 apply · 검증 완료)

초판에서 막혀 있다고 적은 3건은 **#678 로 전부 해소**됐다(`6 added, 0 destroyed`).

| # | 막혔던 것 | 지금 |
|---|---|---|
| ① | `ssm:StartSession` 권한 0건 | ✅ `mp-team-dev` 정책 — 🔴 `Name=mp-ci-server` **태그로 못박음** |
| ② | Access Entry 0건 | ✅ 4명 전원 `mp:admin` (IAM 그룹 파생) |
| ③ | apply 순서 경합 | ✅ `-target` 으로 이 6개만 잘라서 적용 — ALB 레인은 건드리지 않았다 |
| — | *(초판에 없던 것)* `eks:DescribeCluster` 0건 | ✅ 같은 정책에 포함 |

### 실측 검증

| 검증 | 결과 |
|---|---|
| `simulate-principal-policy` `eks:DescribeCluster` | **allowed** |
| `describe-access-entry` × 4 | 전원 **`mp:admin`** |
| `can-i get/delete/create --as-group=mp:admin` | **yes** |
| `can-i get pods --as=<이름>` (그룹 없이) | **no** ← Access Entry 가 판정을 가른다는 증거 |
| `ssm:StartSession` → `mp-ci-server` | **allowed** |
| `ssm:StartSession` → `mp-eks-node` | **implicitDeny** ← 태그 조건이 실제로 막는다 |

🔴 **SSM 을 CI 서버 한 대로 못박은 이유** — 지금은 노드 롤에 `AmazonSSMManagedInstanceCore` 가
없어 어차피 못 들어가지만, **누가 나중에 그걸 붙이는 순간 이 태그 조건이 유일한 방어선**이 된다.
노드 셸 = 그 노드 파드의 Secret 전부 = **K8s RBAC 우회**다.
세션 종료는 `${aws:username}-*` 로 묶었다 — 안 그러면 **남이 붙어 있는 셸을 끊을 수 있다.**

### 🔴 남은 숙제

| # | 것 | 왜 |
|---|---|---|
| ㉠ | **전원 `mp:admin`** | 온프렘은 4단계였다(admin/app-dev/observability/data-dev · #449·#454). EKS 커스텀 ClusterRole 이 2종뿐이라 못 옮겼다. **A3 컷오버 후 좁힌다.** |
| ㉡ | 수동 정책 `mealplanning-dev-policy` 의 **S3 문장이 죽어 있다** | `mealplanning-*` 버킷이 **0개**고 실제 버킷은 전부 `mp-*` 다. 팀원이 S3 를 써야 하면 손봐야 한다. |
| ㉢ | 그룹 멤버십 = 클러스터 admin | `mealplanning-dev` 에 사람을 넣으면 다음 apply 에 **조용히** 접근이 생긴다. 받아들인 대가다(§2). |

---

## 변경 이력

| 날짜 | 내용 |
|---|---|
| 2026-08-14 | 신설. 팀원 온보딩 절차 + 관리자 절차 + 미해결 3건. |
| 2026-08-14 | #678 apply 후 갱신. 🔴 층이 2개가 아니라 **3개**였다(`eks:DescribeCluster` 누락 발견) · §3 을 "막힌 것" → "해소·검증 결과" 로 교체 · 검증 절차와 남은 숙제 3건 추가. |
