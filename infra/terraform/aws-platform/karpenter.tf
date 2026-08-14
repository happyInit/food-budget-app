# Karpenter — 층2 노드 (A-19 · C-45 "평시 0대 · 부하/배포 시에만")
#
# 🔴 **채택 = 사용자 확정 (2026-08-13)** → `A-12` 닫힘. 정본이 이미 Karpenter 를 전제로 짜여 있었다:
#    C-45(2대 시작 + Karpenter 로 확장) · C-29(MNG 고정 + Karpenter NodePool) ·
#    §1 다이어그램(*"평시 0대"*) · `1-43`(taint 로 stateful 배제). A-12 는 그 **형식 게이트**였다.
#
# 🔴 여기 있는 것은 **AWS 쪽 배선뿐**이다. `NodePool`·`EC2NodeClass`(= 어떤 인스턴스를 살지, taint,
#    consolidation 정책)는 K8s 오브젝트라 Ansible `eks_karpenter` 롤이 만든다.
#    ⇒ 이 파일만 apply 해도 노드가 늘지 않는다. 그게 맞다(평시 0대).

# ── 인터럽션 큐 ───────────────────────────────────────────────────────────────
# 🔴 **Spot 을 안 쓰는데도 필요하다.** C-29 가 Spot 을 기각했으므로 "Spot 중단" 은 안 오지만,
#    이 큐가 받는 것은 그것만이 아니다: **예정된 유지보수(scheduled change) · 인스턴스 상태 변경 ·
#    AZ 재조정**. 큐가 없으면 Karpenter 는 그 통지를 못 보고, 노드가 죽는 순간 파드가 갑자기 사라진다
#    (drain 없이). 온디맨드에서도 AWS 는 하드웨어 사유로 인스턴스를 회수한다.
resource "aws_sqs_queue" "karpenter_interruption" {
  name = "mp-karpenter-interruption"

  # Karpenter 권장값. 🔴 짧게 두는 이유 = 오래된 중단 통지는 쓸모가 없다(이미 죽었다).
  message_retention_seconds = 300
  sqs_managed_sse_enabled   = true

  tags = { Name = "mp-karpenter-interruption" }
}

resource "aws_sqs_queue_policy" "karpenter_interruption" {
  queue_url = aws_sqs_queue.karpenter_interruption.url

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = ["events.amazonaws.com", "sqs.amazonaws.com"]
      }
      Action   = ["sqs:SendMessage"]
      Resource = aws_sqs_queue.karpenter_interruption.arn
    }]
  })
}

# EventBridge → SQS. 4종 전부 필요하다(Karpenter 공식 구성).
locals {
  karpenter_events = {
    scheduled_change = {
      source      = "aws.health"
      detail_type = "AWS Health Event"
    }
    spot_interruption = {
      source      = "aws.ec2"
      detail_type = "EC2 Spot Instance Interruption Warning"
    }
    rebalance = {
      source      = "aws.ec2"
      detail_type = "EC2 Instance Rebalance Recommendation"
    }
    instance_state_change = {
      source      = "aws.ec2"
      detail_type = "EC2 Instance State-change Notification"
    }
  }
}

resource "aws_cloudwatch_event_rule" "karpenter" {
  for_each = local.karpenter_events

  name = "mp-karpenter-${replace(each.key, "_", "-")}"

  event_pattern = jsonencode({
    source        = [each.value.source]
    "detail-type" = [each.value.detail_type]
  })

  tags = { Name = "mp-karpenter-${each.key}" }
}

resource "aws_cloudwatch_event_target" "karpenter" {
  for_each = aws_cloudwatch_event_rule.karpenter

  rule = each.value.name
  arn  = aws_sqs_queue.karpenter_interruption.arn
}

# ── 컨트롤러 IRSA ─────────────────────────────────────────────────────────────
resource "aws_iam_role" "karpenter" {
  name               = "mp-karpenter"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["karpenter"].json
}

resource "aws_iam_role_policy" "karpenter" {
  name = "provision"
  role = aws_iam_role.karpenter.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Provision"
        Effect = "Allow"
        Action = [
          "ec2:RunInstances",
          "ec2:CreateFleet",
          "ec2:CreateLaunchTemplate",
          "ec2:CreateTags",
          "ec2:DeleteLaunchTemplate",
          "ec2:TerminateInstances",
        ]
        Resource = "*"
      },
      {
        Sid    = "Describe"
        Effect = "Allow"
        Action = [
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeImages",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceTypeOfferings",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeLaunchTemplates",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSpotPriceHistory",
          "ec2:DescribeSubnets",
          "pricing:GetProducts",
        ]
        Resource = "*"
      },
      {
        # AMI ID 조회 (AL2023 arm64). Karpenter 는 SSM 공개 파라미터에서 최신 AMI 를 읽는다.
        Sid      = "AmiLookup"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = "arn:aws:ssm:${var.region}::parameter/aws/service/*"
      },
      {
        # 🔴 노드 롤을 **MNG 와 공유한다** — `mp-eks-node` 하나로 두 층을 다 태운다.
        #    이유 = `authentication_mode = "API"` 에서 MNG 가 그 롤의 Access Entry(`EC2_LINUX`)를
        #    자동으로 만들어 준다. 롤을 따로 만들면 **Access Entry 를 손으로 만들어야 하고,
        #    잊으면 Karpenter 노드가 뜨고도 클러스터에 붙지 못한다**(NotReady 로 방치).
        Sid      = "PassNodeRole"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = aws_iam_role.node.arn
      },
      {
        # Karpenter 는 EC2NodeClass 마다 인스턴스 프로파일을 **자기가 만들고 지운다**.
        Sid    = "ManageInstanceProfile"
        Effect = "Allow"
        Action = [
          "iam:CreateInstanceProfile",
          "iam:AddRoleToInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:GetInstanceProfile",
          "iam:TagInstanceProfile",
        ]
        Resource = "*"
      },
      {
        Sid      = "ClusterRead"
        Effect   = "Allow"
        Action   = ["eks:DescribeCluster"]
        Resource = aws_eks_cluster.main.arn
      },
      {
        Sid    = "InterruptionQueue"
        Effect = "Allow"
        Action = [
          "sqs:DeleteMessage",
          "sqs:GetQueueUrl",
          "sqs:GetQueueAttributes",
          "sqs:ReceiveMessage",
        ]
        Resource = aws_sqs_queue.karpenter_interruption.arn
      },
    ]
  })
}

# ── 디스커버리 태그는 여기 없다 ───────────────────────────────────────────────
# 🔴 Karpenter 의 `EC2NodeClass` 는 서브넷·SG 를 **`karpenter.sh/discovery` 태그로 찾는다.**
#    태그가 없으면 selectorTerms 가 0건을 돌려주고 층2 노드가 **영구히 프로비저닝되지 않는다**
#    (에러도 조용하다 — C-87). 그만큼 중요한 태그인데, 여기 두지 않는다:
#
#      · `aws_subnet.node.tags`         (vpc_service.tf)
#      · `aws_security_group.node.tags` (security_groups.tf)
#
# 🔴 **처음에는 `aws_ec2_tag` 로 이 파일에 모아 뒀고, 그것이 틀렸다**(2026-08-13 1단 apply 실측,
#    결함 #8). 의도는 *"A-12 가 뒤집히면 이 파일만 지우면 된다"* 였지만:
#      ① `aws_ec2_tag` 은 **이 Terraform 이 관리하지 않는** 리소스에 태그를 붙이는 자원이다.
#         우리 소유 리소스에 쓰면 `aws_subnet`/`aws_security_group` 이 자기 `tags` 에 없는 키를
#         **드리프트로 보고 지우려 한다** → 매 plan 이 `will be updated in-place`(태그 제거).
#      ② 그리고 apply 순서에 따라 **태그가 실제로 사라진다.** 그러면 Karpenter 는 에러 없이
#         노드를 만들지 않는 상태로 굳는다 — 위 "조용하다" 가 정확히 이 국면이다.
#      ③ A-12 는 이미 **채택 확정(C-87)** 이라 되돌릴 유연성 자체가 필요 없어졌다.
#    ⇒ 태그 2개는 리소스 정의 안으로 옮겼다. 이 파일은 **큐·EventBridge·IRSA** 만 담는다.
