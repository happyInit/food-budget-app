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

# ── 디스커버리 태그 ───────────────────────────────────────────────────────────
# 🔴 Karpenter 의 `EC2NodeClass` 는 서브넷·SG 를 **태그로 찾는다.** 태그가 없으면
#    `subnetSelectorTerms` 가 0건을 돌려주고 노드가 **영구히 프로비저닝되지 않는다**(에러도 조용하다).
#    vpc_service.tf / security_groups.tf 에 직접 넣지 않고 여기 모은 이유 = 이 태그의 소비자가
#    Karpenter 뿐이므로, A-12 가 뒤집혔을 때 이 파일만 지우면 되게 두는 것이다.
resource "aws_ec2_tag" "karpenter_subnet" {
  for_each = aws_subnet.node

  resource_id = each.value.id
  key         = "karpenter.sh/discovery"
  value       = var.cluster_name
}

resource "aws_ec2_tag" "karpenter_sg" {
  resource_id = aws_security_group.node.id
  key         = "karpenter.sh/discovery"
  value       = var.cluster_name
}
