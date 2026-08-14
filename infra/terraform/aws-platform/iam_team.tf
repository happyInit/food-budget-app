# 팀원(사람) 접근 — C-24·C-35·C-80 의 마지막 한 조각
#
# 🔴 **사람이 클러스터에 붙으려면 서로 다른 층 세 개가 전부 있어야 한다.** 하나만 빠져도
#    에러 메시지가 원인을 가리키지 않는다 — 2026-08-14 실측에서 세 층 중 **두 층이 비어 있었다**:
#
#      ① IAM 자격증명            → `aws sts get-caller-identity` 가 된다        ✅ 있었다(수동 생성)
#      ② IAM 권한 `eks:DescribeCluster` → `aws eks update-kubeconfig` 이 된다    ❌ 없었다  ← 이 파일
#      ③ EKS Access Entry        → `kubectl` 이 된다                            ❌ 없었다  ← 이 파일
#
#    ②가 없으면 kubeconfig **파일 자체가 안 만들어지고**(`AccessDeniedException`),
#    ③이 없으면 파일은 생기는데 `error: You must be logged in to the server (Unauthorized)` 가 난다.
#    🔴 셋 다 "키가 잘못됐나?" 로 읽히는 메시지라 **재발급 요청이 돌아온다.** 그래서 한 파일에 모았다.
#
# 🔴 **권한의 실체는 여기가 아니다.** 여기는 IAM 주체 → K8s 그룹 매핑까지고,
#    `mp:admin` 이 무엇을 할 수 있는지는 Ansible `eks_rbac` 가 만드는 ClusterRole 이 정한다(C-24).
#    ⇒ 이 파일만 apply 하고 `eks.yml` 을 안 돌리면 그룹만 생기고 권한이 0 이다.
#      (2026-08-14 실측 = ClusterRole `mp-admin`·`mp-viewer` 와 그 바인딩은 **이미 라이브**다.)

# 🔴 이 변수를 `variables.tf` 가 아니라 여기 둔 이유 = 그 파일을 A2(ALB·ACM·WAF) 세션이
#    지금 동시에 고치고 있고, 양쪽이 같은 파일 끝에 추가하면 머지에서 충돌한다.
#    새 파일 하나로 자족시키면 두 레인이 서로를 안 건드린다(C-72 "덧셈만" 과 같은 취지).
variable "team_dev_group_name" {
  description = <<-EOT
    팀원이 들어 있는 **기존 IAM 그룹** 이름. 이 그룹의 멤버 전원이 EKS Access Entry 를 받는다.
    빈 문자열이면 이 파일의 리소스를 전부 건너뛴다(그룹을 아직 안 만든 계정에서 plan 이 죽지 않게).

    🔴 그룹은 Terraform 이 만들지 않는다 — 사용자가 콘솔에서 이미 만들어 뒀고(2026-08-14),
       사람·키 발급은 손으로 하는 편이 낫다는 판단이다(키를 state 에 넣지 않는다).
       ⇒ 여기서는 **읽기만** 한다(`data`). 그룹을 지우면 plan 이 죽는다 — 의도한 것이다.
  EOT
  type        = string
  default     = "mealplanning-dev"
}

data "aws_iam_group" "team_dev" {
  count      = var.team_dev_group_name == "" ? 0 : 1
  group_name = var.team_dev_group_name
}

locals {
  # 🔴 명시 목록(`cluster_admin_principals`·`cluster_viewer_principals`)에 이미 있는 ARN 은 뺀다.
  #    같은 principal 로 Access Entry 를 두 번 만들면 apply 가 `ResourceInUseException` 으로 죽는데,
  #    그 에러가 "그룹에 사람을 넣었더니 터졌다" 로 읽히지 않아 원인을 찾기 어렵다.
  team_dev_explicit = concat(var.cluster_admin_principals, var.cluster_viewer_principals)

  team_dev_members = var.team_dev_group_name == "" ? {} : {
    for u in data.aws_iam_group.team_dev[0].users :
    u.user_name => u.arn if !contains(local.team_dev_explicit, u.arn)
  }
}

# ── ③ EKS Access Entry ────────────────────────────────────────────────────────
#
# 🔴 **그룹 멤버십에서 파생시킨다 — 사람 목록을 tfvars 에 손으로 적지 않는다.**
#    받아들인 대가 = *"그룹에 넣으면 조용히 클러스터 admin 이 된다"* (명시 목록보다 암묵적이다).
#    그럼에도 이쪽을 고른 이유는 **tfvars 가 gitignored 라서**다 — 워크트리마다 사본이 갈리고,
#    옛 사본을 든 세션이 apply 하면 **여기서 만든 엔트리를 조용히 지운다.**
#    (2026-08-14 실측 = aws-platform 의 tfvars 사본이 다른 세션 워크트리에 딱 하나 있었다.)
#    ⇒ 사람 목록을 tfvars 에서 빼면 그 사고 자체가 성립하지 않는다.
#    좁히는 방법 = 그룹을 admin/viewer 둘로 쪼개고 이 리소스를 둘로 늘리는 것이다.
resource "aws_eks_access_entry" "team_dev" {
  for_each = local.team_dev_members

  cluster_name  = aws_eks_cluster.main.name
  principal_arn = each.value
  type          = "STANDARD"

  # 🔴 온프렘 RBAC 은 4단계였다(admin/app-dev/observability/data-dev · #449·#454).
  #    EKS 쪽 커스텀 ClusterRole 은 지금 `mp-admin`·`mp-viewer` **2종뿐**이라 그대로 못 옮긴다.
  #    이관 기간에는 전원 admin 으로 간다(사용자 판단 2026-08-14 = "개발 환경이 다 똑같았다").
  #    🔴 A3 컷오버 후 온프렘과 같은 4단계로 좁히는 것이 남은 숙제다.
  kubernetes_groups = ["mp:admin"]

  tags = { Name = "mp-team-${each.key}" }
}

# ── ② IAM 권한 ────────────────────────────────────────────────────────────────
#
# 🔴 사용자가 손으로 만든 `mealplanning-dev-policy` 는 **건드리지 않는다**(S3 + Bedrock).
#    이 정책은 거기에 **덧붙는** 별개 정책이다 — 손으로 만든 것을 Terraform 이 덮으면
#    콘솔에서 한 수정이 다음 apply 에 조용히 사라진다.
resource "aws_iam_policy" "team_dev" {
  count = var.team_dev_group_name == "" ? 0 : 1

  name        = "mp-team-dev"
  description = "팀원 공용 — EKS kubeconfig 발급 + CI 서버 Session Manager 셸"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 🔴 이것이 없으면 `aws eks update-kubeconfig` 이 **AccessDeniedException** 으로 죽는다.
        #    kubectl 이 아니라 kubeconfig 를 만드는 단계에서 막히는 것이라 증상이 다르다.
        Sid      = "EksKubeconfig"
        Effect   = "Allow"
        Action   = ["eks:DescribeCluster"]
        Resource = aws_eks_cluster.main.arn
      },
      {
        # 콘솔 EKS 목록 화면. 없어도 kubectl 은 되지만 콘솔이 빈 화면이라 "권한이 없다"로 오해한다.
        Sid      = "EksListForConsole"
        Effect   = "Allow"
        Action   = ["eks:ListClusters"]
        Resource = "*"
      },
      {
        # SSM 대상 찾기. 🔴 인스턴스 ID 를 이름으로 조회하려면 `ec2:DescribeInstances` 가 필요하고,
        #    이 액션들은 리소스 단위 제한을 지원하지 않아 `*` 가 강제된다(읽기 전용이다).
        Sid    = "SsmDiscoverTargets"
        Effect = "Allow"
        Action = [
          "ssm:DescribeInstanceInformation",
          "ssm:DescribeSessions",
          "ssm:GetConnectionStatus",
          "ec2:DescribeInstances",
        ]
        Resource = "*"
      },
      {
        # 🔴 **CI 서버 한 대로 못박는다.** 지금은 EKS 노드에 SSM 에이전트 권한이 없어
        #    어차피 못 들어가지만(노드 롤에 `AmazonSSMManagedInstanceCore` 없음),
        #    나중에 누가 노드에 그 정책을 붙이는 순간 이 태그 조건이 유일한 방어선이 된다.
        #    노드 셸 = 그 노드 파드의 Secret 전부 = **K8s RBAC 우회**다.
        Sid      = "SsmStartSessionOnCiServer"
        Effect   = "Allow"
        Action   = ["ssm:StartSession"]
        Resource = "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:instance/*"
        Condition = {
          StringEquals = { "ssm:resourceTag/Name" = "mp-ci-server" }
        }
      },
      {
        # 기본 셸 문서. AWS 관리 문서라 ARN 에 계정 자리가 비어 있다(`:ssm:region::document/`).
        # 🔴 포트포워딩 문서(`AWS-StartPortForwardingSession`)는 **일부러 뺐다** — GitLab 은
        #    `https://gitlab.mealbong.cloud` 로 이미 열려 있어 터널이 필요 없다.
        Sid      = "SsmSessionDocument"
        Effect   = "Allow"
        Action   = ["ssm:StartSession"]
        Resource = "arn:aws:ssm:${var.region}::document/SSM-SessionManagerRunShell"
      },
      {
        # 🔴 **자기 세션만 끊을 수 있다.** `session/*` 로 열면 남이 붙어 있는 셸을 끊을 수 있고,
        #    세션 ID 는 `<IAM 사용자명>-<난수>` 형식이라 이 접두사가 실제로 사람을 가른다.
        Sid      = "SsmOwnSessionOnly"
        Effect   = "Allow"
        Action   = ["ssm:TerminateSession", "ssm:ResumeSession"]
        Resource = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:session/$${aws:username}-*"
      },
    ]
  })
}

resource "aws_iam_group_policy_attachment" "team_dev" {
  count = var.team_dev_group_name == "" ? 0 : 1

  group      = data.aws_iam_group.team_dev[0].group_name
  policy_arn = aws_iam_policy.team_dev[0].arn
}

# 팀원에게 "당신 ARN 이 등록됐다" 를 보여주는 용도. 🔴 계정 ID 가 찍히므로 공개 채널에 붙이지 말 것.
output "team_dev_access_entries" {
  description = "IAM 그룹 멤버십에서 파생된 EKS Access Entry (사용자명 → ARN)"
  value       = local.team_dev_members
}
