# AWS 접속 세팅 — 팀 안내

> **§1 = 팀원용**(그대로 읽으면 됨) · **§2 = 관리자용**(사람을 새로 붙일 때) · **§3 = 배선 상태·검증·남은 숙제**
>
> 🟢 **2026-08-14 기준 팀원 4명 접근 라이브**(#678 apply · 검증 완료 — §3).
>
> 관련 결정 = **C-80**(비대화형 접근 필수) · **C-35**(Identity Center 미채택 = 브라우저 로그인 없음) ·
> **C-24**(사람 신원 = Access Entry `kubernetesGroups` + 커스텀 ClusterRole) · **C-85**(내부 도구 = LB 0개) ·
> **C-37**(CI 서버 키페어 금지) · **C-83**(온프렘 형상 동결).

---

## §1 팀원용

이제 EKS 클러스터에 **각자 본인 노트북에서 직접** 붙습니다.
온프렘처럼 `ssh wsl-dev` 로 어딘가를 경유하지 않습니다 — 인터넷만 되면 카페에서도 됩니다.
(온프렘 클러스터는 **그대로** `ssh wsl-dev` 를 씁니다. 두 사이트가 당분간 같이 삽니다.)

전부 합쳐 **15분** 정도 걸리고, 설치는 **딱 한 번**만 하면 됩니다.

### 🔴 시작하기 전에 — 이것만 지켜주세요

**① 명령을 여러 줄 한꺼번에 붙여넣지 마세요. 한 줄씩입니다.**
`aws configure` 는 값을 되묻는 **대화형** 명령이라, 3줄을 한꺼번에 붙이면
**2·3번째 줄이 명령이 아니라 "Access Key" 답변으로 먹힙니다.** 실제로 발생했습니다:

```
AWS Access Key ID [None]:      ← "aws eks update-kubeconfig ..." 가 들어가 버림
AWS Secret Access Key [None]:  ← "kubectl get nodes" 가 들어가 버림
```

에러가 안 나고 **조용히 잘못된 값이 저장돼서** 나중에 엉뚱한 곳에서 터집니다.
이미 이렇게 됐다면 `Ctrl + C` 로 빠져나온 뒤 §1-3 을 처음부터 다시 하면 덮어써집니다.

**② 🔴 `k8s-master` 같은 공용 서버에서 하지 마세요. 본인 노트북입니다.**
- 그 머신의 `kubectl` 은 **온프렘 클러스터**를 봅니다. 거기에 EKS 를 얹으면 나중에 컨텍스트를
  착각한 채 친 명령이 **엉뚱한 클러스터에 맞습니다.** 온프렘은 이관의 롤백 원본이라(C-83)
  가장 건드리면 안 되는 물건입니다.
- 본인 Access Key 가 **여러 사람이 들어가는 머신에 평문으로** 남습니다.
- 애초에 경유할 이유가 없습니다. EKS 는 노트북에서 바로 붙습니다.

**③ Secret Access Key 를 채팅·이슈·PR 에 붙여넣지 마세요.** 이 레포는 **공개**입니다.

---

### 0. 받는 것

- **IAM 사용자 이름** + **Access Key ID** + **Secret Access Key** — DM 으로 전달
- 권한 등급 — 지금은 전원 `admin`

🔴 Secret Access Key 는 **발급 때 한 번만** 보입니다. 못 받았으면 재발급 요청하세요(다시 볼 방법이 없습니다).

---

### 1. 터미널 열기

<details open>
<summary><b>Windows</b></summary>

`Win + R` → `powershell` 입력 → Enter.
(또는 시작 메뉴에서 "PowerShell" 검색)

🔴 **WSL(Ubuntu 창)을 쓰고 계셔도, 여기서는 Windows PowerShell 하나로 통일하는 걸 권합니다.**
WSL 과 Windows 는 **파일 시스템도 PATH 도 완전히 별개**라, 한쪽에 설치하고 다른 쪽에서 찾으면
`command not found` 가 납니다. 양쪽 다 쓰고 싶으면 **양쪽에 각각** 설치·설정해야 합니다.
</details>

<details open>
<summary><b>macOS</b></summary>

`Cmd + Space` → `터미널` 입력 → Enter.
</details>

<details open>
<summary><b>Linux · WSL(Ubuntu)</b></summary>

Ubuntu 터미널 그대로. WSL 이면 시작 메뉴에서 "Ubuntu".
</details>

---

### 2. 설치 (한 번만)

필요한 것은 **2개**입니다. `session-manager-plugin` 은 §1-7(CI 서버 셸) 쓸 사람만.

| | 무엇 | 왜 |
|---|---|---|
| **AWS CLI v2** | AWS 명령줄 도구 | 🔴 **v1 은 안 됩니다** — EKS 토큰 발급이 없습니다 |
| **kubectl** | 쿠버네티스 명령줄 도구 | 클러스터가 1.34 라 **1.33~1.35** 사이면 됩니다 |

<details open>
<summary><b>Windows</b></summary>

```powershell
winget install -e --id Amazon.AWSCLI
winget install -e --id Kubernetes.kubectl
```

🔴 **설치 후 PowerShell 창을 닫고 새로 여세요.** PATH 가 새 창부터 반영됩니다 —
안 그러면 방금 깐 것을 두고 `aws 용어가 인식되지 않습니다` 가 뜹니다.

`winget` 이 없다는 오류가 나면(구형 Windows 10) 설치 파일로 하세요:
- AWS CLI → <https://awscli.amazonaws.com/AWSCLIV2.msi> 받아서 실행
- kubectl → <https://kubernetes.io/ko/docs/tasks/tools/install-kubectl-windows/>
</details>

<details open>
<summary><b>macOS</b></summary>

```bash
brew install awscli kubectl
```

`brew: command not found` 가 나면 Homebrew 부터:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
</details>

<details open>
<summary><b>Linux · WSL(Ubuntu)</b></summary>

AWS CLI v2 — 🔴 **`apt install awscli` 로 깔지 마세요. 그건 v1 입니다.**
```bash
curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip -q awscliv2.zip && sudo ./aws/install && rm -rf aws awscliv2.zip
```

kubectl:
```bash
curl -sLO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable-1.34.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && rm kubectl
```
</details>

**설치 확인** — 아래 두 줄을 **한 줄씩** 돌려서 버전이 나오면 성공입니다:

```bash
aws --version        # aws-cli/2.x.x  ← 🔴 앞이 2 여야 합니다
kubectl version --client
```

---

### 3. 자격증명 등록

🔴 **아래 한 줄만** 입력하고 Enter. (다음 명령을 미리 붙여넣지 마세요 — §1 시작 전 ①)

```bash
aws configure --profile mp
```

그러면 4번 물어봅니다. **하나씩 입력하고 Enter**:

```
AWS Access Key ID [None]:     ← DM 으로 받은 값
AWS Secret Access Key [None]: ← DM 으로 받은 값 (화면에 안 보이는 게 정상입니다)
Default region name [None]:   ap-northeast-2
Default output format [None]: json
```

**확인:**
```bash
aws sts get-caller-identity --profile mp
```

본인 이름이 들어간 ARN 이 나오면 성공입니다:
```json
{ "Arn": "arn:aws:iam::<계정>:user/본인이름" }
```

---

### 4. kubectl 붙기

```bash
aws eks update-kubeconfig --name mp-eks --region ap-northeast-2 --profile mp
```

`Added new context ...` 가 나오면 됩니다. 이제:

```bash
kubectl get nodes
```

노드 2대가 `Ready` 로 보이면 **끝입니다.**

```bash
kubectl -n app get pods        # 앱 파드
kubectl config current-context # 지금 어느 클러스터를 보고 있는지
```

🔴 **마지막 줄을 기억해두세요.** 온프렘과 EKS 를 오갈 때 **지금 어디를 보고 있는지 확인하는 습관**이
사고를 막습니다. 두 클러스터는 파드 이름이 거의 같아서 화면만으로는 구분이 안 됩니다.

---

### 5. 내 권한

지금은 **전원 `admin`** 입니다 — 클러스터에서 뭐든 됩니다(삭제 포함).
그래서 §1-4 의 "지금 어디를 보고 있는지" 확인이 더 중요합니다.

---

### 6. 내부 도구(Grafana·ArgoCD 등) 보는 법 — 주소가 없습니다

```bash
kubectl -n observability port-forward svc/<서비스> 3000:80
```

→ 브라우저에서 `localhost:3000`. 끝낼 때는 그 터미널에서 `Ctrl + C`.

AWS 쪽엔 내부 도구용 주소를 **안 만듭니다**(LB 비용 0으로 가기로 했습니다 — C-85).
🟢 온프렘은 SSH + port-forward **2겹**이었는데 여기는 **1겹**이라 오히려 편합니다.

---

### 7. SSM — CI 서버 셸 (필요한 사람만)

GitLab CI 서버는 **SSH 키도 22 포트도 없습니다.** 의도한 것이고(C-37), 들어가는 유일한 길이 SSM 입니다.

먼저 플러그인 설치 — <https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html>
(macOS: `brew install --cask session-manager-plugin`)

```bash
aws ssm start-session --target <인스턴스ID> --region ap-northeast-2 --profile mp
```

🔴 **대부분은 필요 없습니다** — GitLab 은 `https://gitlab.mealbong.cloud` 웹 UI 로 쓰시면 됩니다.
서버 안에서 뭘 고쳐야 할 때만 쓰고, 그때 인스턴스 ID 를 받아 가세요.

---

### 8. 🔴 하지 말아주세요

- **`terraform apply`** — 여러 레인이 **같은 state** 를 씁니다. 돌리기 전에 물어봐주세요.
- **온프렘 클러스터 형상 변경** — 이관이 끝날 때까지 동결입니다(되돌릴 원본이라서요 · C-83).
- **`kubectl get secret -o yaml`·`-o jsonpath`** — 값이 터미널과 기록에 남습니다. 키 목록만 볼 땐 `kubectl describe secret`.
- Access Key 를 공용 채널·이슈·PR 에 붙여넣기.

---

### 9. 안 될 때 — 에러 메시지로 찾기

🔴 **에러 메시지가 원인을 정확히 가리킵니다.** 아래 표에서 찾아보고, 없으면 채널에
**메시지를 그대로** 올려주세요. `Unauthorized` 와 `AccessDenied` 는 원인이 완전히 다릅니다.

| 나온 메시지 | 원인 | 조치 |
|---|---|---|
| `aws : 용어가 인식되지 않습니다` / `command not found: aws` | 설치 후 **터미널을 새로 안 열었다** | 창 닫고 새로 열기 → 그래도면 재설치 |
| `aws --version` 이 `aws-cli/1.x` | **v1 이 깔려 있다** | v2 로 재설치 (Ubuntu 면 `apt remove awscli` 먼저) |
| `Unable to locate credentials` | `--profile mp` 를 빼먹었거나 §1-3 미완료 | 명령 끝에 `--profile mp` 확인 |
| `The config profile (mp) could not be found` | 프로필 이름 오타 | `aws configure list-profiles` 로 확인 |
| `AccessDeniedException ... eks:DescribeCluster` | **IAM 그룹에 등록이 안 됐다** | 🔴 키 문제 아님 — 관리자에게 본인 ARN 전달 |
| `You must be logged in to the server (Unauthorized)` | **클러스터 등록(Access Entry)이 안 됐다** | 🔴 키 문제 아님 — 재발급 요청하지 말고 ARN 전달 |
| `exec: "aws": executable file not found` | kubectl 은 있는데 **aws 가 그 환경 PATH 에 없다** | 🔴 WSL/Windows 를 섞어 쓴 경우가 대부분. 한쪽으로 통일 |
| `dial tcp ... i/o timeout` | 네트워크 | 사내망·VPN·방화벽 확인 |
| `error: You must specify a namespace` 류 | `-n <네임스페이스>` 누락 | `kubectl get ns` 로 목록 확인 |

**ARN 전달하는 법** — 이 한 줄의 출력을 그대로 복사해서 주시면 됩니다:
```bash
aws sts get-caller-identity --profile mp
```

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

## §4 `mp-ai` — 서버리스·AI 프로젝트 권한 (2026-08-14 라이브)

**정책 문서 = `infra/iam/mp-ai/*.json` · 적용 = `infra/iam/mp-ai/apply.sh`**

🔴 **Terraform 이 아니다.** 사람·수동 IAM(사용자 4명·그룹 `mealplanning-dev`)이 이미 콘솔 생성이라
여기만 IaC 로 끌어오면 정본이 둘이 된다. 대신 **정책 문서를 레포에 두고 스크립트로만 적용**한다
— *"누가 무엇을 줬는지"* 는 git 이 답한다. 계정 ID 는 `${ACCOUNT_ID}` 플레이스홀더다(이 레포는 공개).

### 무엇인가

**AI 파트(정현·건우)의 별도 트랙**이다. 🔴 **EKS 앱 13종을 서버리스로 옮기는 것이 아니라
옆에 독립적으로 세우는 프로젝트**다(사용자 확정 2026-08-14). 그래서 8/11 검토서
(`docs/mp_serverless_design_review.md` — **미커밋**)가 든 확정 결정 6건 충돌
(C-9 진입점 · C-3 DR · C-27 Blue-Green · C-46 WAF)은 **전제가 바뀌어 해당하지 않는다.**

| 정책 | 붙는 곳 | 역할 |
|---|---|---|
| `mp-ai-dev` | 그룹 `mealplanning-ai` | 허용 |
| `mp-ai-guardrails` | 〃 | 거부 |
| `mp-ai-boundary` | 🔴 **그룹 아님** — `mp-ai-*` **실행 역할**의 PermissionsBoundary | 천장 |

### 설계 — 이름이 곧 권한 경계다

`mp-ai-*` / `mp-ai/*` 접두사 밖은 전부 거부한다. SG 만 ARN 에 이름 자리가 없어
**태그 `Project=mp-ai`** 로 대신한다(태그 없이 만드는 것도 거부 — 만들고 태그를 떼는 우회 차단).

🔴 **`iam:CreateRole` 은 `iam:PermissionsBoundary` 조건부다.** 이게 없으면
*"`AdministratorAccess` 붙인 역할을 만들어 Lambda 에 넘기는"* 권한 상승이 된다.
경계가 붙으면 실효 권한 = **경계 ∩ 정책** 이라 천장을 못 넘고, 그 안에서는 자유롭다.

🔴 **Deny 는 "바꾸는 것"만 막는다. `Describe`/`List` 를 넣으면 안 된다** —
같은 사람이 `mp:admin` 이라 `eks:*` 를 통째로 Deny 하면 **`kubectl` 이 죽는다**(Deny 가 Allow 를 이긴다).

🔴 **`mp/prod/*` 비밀과 `mealplanning/*` 이미지는 읽기를 연다.** 막아도 보호되는 게 없다 —
ESO 가 `mp/prod/*` 를 K8s Secret 으로 동기화하므로 `mp:admin` 인 사람은 `kubectl` 로 같은 값을 본다.
**쓰기만** 막는다(이미지 push 는 CI 몫 · 비밀 변경은 관리자 몫).

### 실측 검증 (2026-08-14 · `simulate-principal-policy` 18건 전부 의도대로)

| allowed 여야 | | Deny 여야 | |
|---|---|---|---|
| Lambda `mp-ai-*` | ✅ | Lambda `mp-chat` | 🔒 |
| Bedrock | ✅ | `eks:DeleteCluster` | 🔒 |
| **`eks:DescribeCluster`** (kubectl) | ✅ | `iam:CreateUser` | 🔒 |
| 운영 이미지 **조회** | ✅ | 운영 이미지 **push** | 🔒 |
| `mp/prod/*` **읽기** | ✅ | `mp/prod/*` **쓰기** | 🔒 |
| `PassRole` → lambda | ✅ | 경계 없이 역할 생성 | 🔒 |
| SG 생성 (태그 있음) | ✅ | SG 생성 (태그 없음) | 🔒 |
| ALB·알람 조회/생성 | ✅ | 남의 SG 규칙 · 백업 버킷 | 🔒 |

### 🔴 구조상 관리자에게 남는 것 3개

| # | 무엇 | 왜 넘길 수 없나 |
|---|---|---|
| ① | **노드 SG 인그레스** (Lambda → PG·ES) | 인그레스 규칙은 **받는 쪽 SG** 에 단다. 노드 SG 는 이관 본체다 |
| ② | **`mp/prod/*` 에 값 넣기** | 프로덕션 자격증명 저장소. 앞뒤(요청·ExternalSecret PR·rollout)는 본인이 한다 |
| ③ | 🔴 **Bedrock 모델 추가** | IRSA `mp-pipeline-bedrock` 이 **`nova-micro` 2개 ARN 으로 못박혀** 있다. 모델을 바꾸면 **로컬은 되는데 EKS 배포 후 `AccessDeniedException`** 이 난다 — 원인 찾기가 제일 어려운 부류다 |

### 결정 기록

- **벡터 저장소 = 관리형 미채택.** OpenSearch Serverless 는 **최소 OCU 과금**이라 데이터가 0이어도
  월 수백 달러다(이관 실단가 월 $857 위에 얹힌다). ⇒ `aoss:*` 를 **회수**했고, RAG 는
  **PG 일반 테이블 + 코드 유사도 계산**으로 간다. `pgvector` 는 서버에 확장 파일이 없어 불가.
  🟢 C-15(RDS·OpenSearch·MSK 전부 기각 · 자체운영 우선)와 같은 방향이다.
- **모델 아티팩트 버킷 = `mp-ai-model-ap2`** (~~`mp-model-ap2`~~). 접두사가 권한 경계라 예외를 두면
  경계가 무의미해진다. 버킷이 아직 없어 이름만 맞추면 된다.
- **`mp/prod/*` 를 읽어 쓴다**(복사 금지)는 요청은 **성립하지 않는다.** 우리가 주는 건 복사본이 아니라
  **별도의 읽기 전용 PG 롤**이라 원본 비번이 바뀌어도 갈라지지 않는다.

---

## 변경 이력

| 날짜 | 내용 |
|---|---|
| 2026-08-14 | 신설. 팀원 온보딩 절차 + 관리자 절차 + 미해결 3건. |
| 2026-08-14 | #678 apply 후 갱신. 🔴 층이 2개가 아니라 **3개**였다(`eks:DescribeCluster` 누락 발견) · §3 을 "막힌 것" → "해소·검증 결과" 로 교체 · 검증 절차와 남은 숙제 3건 추가. |
| 2026-08-14 | §1 전면 개편 — 터미널 여는 법부터 OS 3종(Windows·macOS·Linux/WSL) 설치·설정 전 과정 + 에러 메시지별 문제 해결표. 🔴 실제 사고 2건을 맨 앞 경고로 승격(여러 줄 붙여넣기가 `aws configure` 답변으로 먹힘 · 공용 서버 `k8s-master` 에서 실행). |
| 2026-08-14 | §4 신설 — `mp-ai` 서버리스·AI 트랙 권한(정현·건우). 🔴 **EKS 앱을 옮기는 게 아니라 독립 프로젝트**라 8/11 검토서의 확정결정 6건 충돌은 전제가 바뀌었다. 정책 3종을 `infra/iam/mp-ai/` 로 레포에 편입 · 시뮬레이터 18건 검증. |
