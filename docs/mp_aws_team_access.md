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

🔴 **IAM 사용자를 만드는 것만으로는 `kubectl` 이 되지 않는다.** 두 단계가 별개다.

```
① IAM 사용자 + Access Key          → aws sts get-caller-identity 가 된다
② EKS Access Entry 에 ARN 등록     → kubectl 이 된다        ← 이걸 빼먹으면 Unauthorized
```

②를 안 하면 팀원은 `error: You must be logged in to the server (Unauthorized)` 를 보는데,
**IAM 키 문제로 오해하기 딱 좋은 메시지**다. 변수 설명이 그 함정을 이미 적고 있다 —
*"비어 있으면 아무도 클러스터에 들어갈 수 없다 — 클러스터를 만든 주체조차"*.

### ② 실제 배선

`infra/terraform/aws-platform/variables.tf`:

| 변수 | 그룹 | 실권한 |
|---|---|---|
| `cluster_admin_principals` | `mp:admin` | ClusterRole `mp-admin` (`*` on `*`) |
| `cluster_viewer_principals` | `mp:viewer` | ClusterRole `mp-viewer` (get/list/watch) |

🔴 **여기 넣는 것은 그룹 매핑뿐이다.** 실제 권한은 Ansible `eks_rbac` 가 만드는 ClusterRole 이 준다
— Terraform 만 고치고 `eks.yml` 을 안 돌리면 그룹은 생겼는데 아무 권한이 없다.

🔴 **`cluster_bootstrap_admin_principals` 에 팀원을 넣지 말 것.** 그건 플랫폼 운영 주체 1개 자리이고
`AmazonEKSClusterAdminPolicy`(관리형)를 붙인다. 사람은 커스텀 ClusterRole 로 가는 게 C-24 다.

### 추가 순서

1. IAM 사용자 생성 + Access Key 발급 → **DM 으로만** 전달
2. `cluster_admin_principals` 또는 `cluster_viewer_principals` 에 ARN 추가
3. `terraform plan` → 🔴 **destroy 줄이 0인지 확인** (다른 레인 리소스를 지우지 않는지)
4. `terraform apply` — 🔴 **`main` 에서 · 한 번에 한 레인만**
5. 본인에게 `kubectl get nodes` 확인 요청

### 제거할 때

Access Entry 에서 ARN 을 빼는 것으로 **클러스터 접근은 즉시 끊긴다.**
🔴 다만 **IAM Access Key 는 따로 비활성/삭제해야 한다** — 그게 남아 있으면 S3·ECR 등 IAM 쪽 권한은 그대로다.

---

## §3 🔴 지금 막혀 있는 것

| # | 막힌 것 | 영향 | 필요한 조치 |
|---|---|---|---|
| ① | **`ssm:StartSession` 권한이 Terraform 에 0건** | §1-6 이 `AccessDenied` 로 실패한다 | 사람용 SSM 정책 신설 (아래) |
| ② | Access Entry 변수가 **비어 있는 동안** | §1-3 이 `Unauthorized` | §2 절차대로 ARN 추가 + apply |
| ③ | ①② 둘 다 **`terraform apply`** | A1·A2 레인과 같은 state 라 경합 | apply 순서 조율 |

### ① 에 필요한 최소 권한

```
ssm:StartSession           Resource = 대상 인스턴스 ARN
                                    + arn:aws:ssm:<region>::document/AWS-StartInteractiveCommand
ssm:TerminateSession       Resource = arn:aws:ssm:*:*:session/${aws:username}-*
ssm:DescribeSessions · ssm:GetConnectionStatus
```

🔴 `TerminateSession` 을 `${aws:username}-*` 로 제한하는 것이 요점이다 — 안 그러면
**남의 세션을 끊을 수 있다.**

---

## 변경 이력

| 날짜 | 내용 |
|---|---|
| 2026-08-14 | 신설. 팀원 온보딩 절차 + 관리자 절차 + 미해결 3건. |
