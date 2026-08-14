# CI 잡 신원 = GitLab OIDC → 잡 전용 롤 (A-50 · A0.5)
#
# 🔴 **왜 이 파일이 있나** — 빌드 잡이 ECR 에 push 하려면 AWS 자격증명이 필요하다. 방법이 셋인데
#    앞의 둘을 버렸다:
#      ① 정적 액세스 키를 CI 변수에 → 🔴 `0-16` 으로 없앤 방식(유출되면 영구 유효). 안 쓴다.
#      ② 인스턴스 롤 + IMDS hop 2 → 기계 권한을 컨테이너가 물려받는다. **잡별 구분이 없다.**
#      ③ 🟢 **OIDC** — GitLab 이 *잡마다* 단수명 서명 토큰을 발급하고, AWS 가 그 서명을
#         GitLab **공개키**로 검증한 뒤 임시 자격증명을 준다. **저장되는 비밀이 0개.**
#    사용자 판단(2026-08-13) = **정석대로 ③**.
#
# 🟢 **우리는 이 패턴을 이미 쓰고 있다 — IRSA 가 그것이다**(`iam_irsa.tf`).
#    발급자만 EKS → GitLab 으로 바뀌고, `sub` 가 `system:serviceaccount:…` → `project_path:…` 가 된다.
#
# 🔴 **2단 apply 다** — GitLab 이 떠서 discovery URL 이 응답해야 이 리소스를 만들 수 있다.
#    `ci_oidc_issuer_url` 이 비어 있으면 전부 건너뛴다(A0 의 `create_node_group` 과 같은 패턴).
#      1단: EC2 apply → Ansible 로 GitLab 설치 → Cloudflare Access 에 **경로 2개 Bypass**
#      2단: `-var ci_oidc_issuer_url=https://gitlab.mealbong.cloud` 로 다시 apply
#
# 🔴 **Cloudflare Access Bypass 가 선행이다.** AWS STS 가 아래 둘을 **익명으로** 읽어야 한다:
#      https://<issuer>/.well-known/openid-configuration
#      https://<issuer>/oauth/discovery/keys        ← JWKS(공개키)
#    🟢 둘 다 공개키·메타데이터뿐이라 **노출로 잃는 것이 없다.**
#    ⚠️ C-61⑤ 가 기각한 Bypass 는 **git 경로**였다(뒤에 소스 전체가 있어 "검문소가 한 겹으로
#      줄어든다"). 이 두 경로는 보호할 비밀이 없어 **그 논거가 전이되지 않는다.**

locals {
  ci_oidc_enabled = var.ci_oidc_issuer_url != ""
  # 신뢰정책 Condition 의 키는 **발급자 호스트명**으로 시작한다(IRSA 와 같은 형식).
  ci_oidc_host = replace(replace(var.ci_oidc_issuer_url, "https://", ""), "/", "")
}

resource "aws_iam_openid_connect_provider" "gitlab" {
  count = local.ci_oidc_enabled ? 1 : 0

  url = var.ci_oidc_issuer_url
  # 🔴 `aud` — GitLab `.gitlab-ci.yml` 의 `id_tokens.<NAME>.aud` 와 **정확히 같아야** 한다.
  #    이 값을 두는 이유 = **토큰 재사용 방지**. aud 를 안 고정하면 다른 신뢰 당사자에게
  #    발급된 토큰이 우리 롤에도 통할 수 있다.
  client_id_list = [var.ci_oidc_audience]

  # 🔴 thumbprint 를 하드코딩하지 않는다 — TLS 인증서가 갱신되면 값이 바뀌고, 그때
  #    "왜 갑자기 AssumeRole 이 실패하나" 가 된다. 비우면 AWS 가 조회해서 채운다.
  tags = { Name = "mp-oidc-gitlab" }
}

# ── 잡 전용 롤 — 🔴 인스턴스 롤과 **완전히 분리**된다 ────────────────────────
resource "aws_iam_role" "ci_job" {
  count = local.ci_oidc_enabled ? 1 : 0

  name = "mp-ci-job"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.gitlab[0].arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.ci_oidc_host}:aud" = var.ci_oidc_audience
        }
        # 🔴🔴 **`sub` 를 반드시 좁힌다.** 이걸 `*` 로 두거나 생략하면 **그 GitLab 인스턴스의
        #    어떤 프로젝트·어떤 브랜치의 잡이든** 이 롤을 빌릴 수 있다. GitHub Actions OIDC 에서
        #    반복적으로 사고가 난 지점이 정확히 이것이다.
        #    형식: project_path:<group>/<repo>:ref_type:branch:ref:<branch>
        #    ⚠️ `StringLike` 를 쓰는 이유 = 브랜치 목록을 여러 개 허용하려면 와일드카드가 필요한데,
        #       **프로젝트 경로는 리터럴로 고정**해 폭발 반경을 그 레포 하나로 묶는다.
        StringLike = {
          "${local.ci_oidc_host}:sub" = [
            for r in var.ci_oidc_allowed_refs :
            "project_path:${var.ci_oidc_project_path}:ref_type:branch:ref:${r}"
          ]
        }
      }
    }]
  })
  tags = { Name = "mp-ci-job" }
}

# ECR push — 🔴 **A0.5 의 완료 판정이 이 권한에 달려 있다**(ECR 18리포에 arm64 이미지 적재).
resource "aws_iam_role_policy" "ci_job_ecr" {
  count = local.ci_oidc_enabled ? 1 : 0

  name = "ecr-push"
  role = aws_iam_role.ci_job[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 🔴 `GetAuthorizationToken` 은 **리소스를 지정할 수 없다**(`*` 필수) — 리포별로 좁힐 수
        #    없는 계정 단위 동작이다. 아래 문장이 실제 경계를 만든다.
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
          # pull 도 필요하다 — 멀티스테이지 빌드가 자기 베이스 이미지를 당기고,
          # Trivy 게이트가 방금 푸시한 이미지를 다시 읽는다.
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:DescribeImages",
          "ecr:ListImages",
        ]
        # 🔴 A-46 = 리포 접두사 `mealplanning/` 유지. 이 경계 덕분에 CI 가 다른 리포를 못 만진다.
        #    ⚠️ `ecr:CreateRepository` 를 **주지 않는다** — 리포는 Terraform 소관(`ecr.tf` 18개)이고,
        #       CI 가 만들 수 있으면 오타 하나가 새 리포를 만들어 A2 에서 pull 실패로 드러난다.
        Resource = "arn:aws:ecr:${var.region}:${data.aws_caller_identity.current.account_id}:repository/mealplanning/*"
      },
    ]
  })
}

output "ci_job_role_arn" {
  description = <<-EOT
    `.gitlab-ci.yml` 이 assume 할 롤 ARN. 🔴 OIDC 2단 apply 전에는 비어 있다.
    쓰는 형태(A-29):
      id_tokens: { AWS_TOKEN: { aud: "<ci_oidc_audience>" } }
      script:
        - aws sts assume-role-with-web-identity --role-arn <이 값>
            --role-session-name gitlab-$CI_JOB_ID --web-identity-token "$AWS_TOKEN"
    🔴 정적 키를 CI 변수에 넣지 말 것 — 그것이 `0-16` 으로 없앤 방식이다.
  EOT
  value       = local.ci_oidc_enabled ? aws_iam_role.ci_job[0].arn : ""
}
