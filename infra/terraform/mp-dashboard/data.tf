# aws-platform 이 만든 리소스를 이름으로 조회한다 — 이 스택에서 만들지 않는다(C-77 분리).

data "aws_caller_identity" "current" {}

data "aws_vpc" "service" {
  filter {
    name   = "tag:Name"
    values = [var.service_vpc_name]
  }
}

data "aws_subnet" "dashboard" {
  filter {
    name   = "tag:Name"
    values = [var.dashboard_subnet_name]
  }
}

data "aws_security_group" "dashboard" {
  filter {
    name   = "tag:Name"
    values = [var.dashboard_sg_name]
  }
}

data "aws_security_group" "eks_node" {
  filter {
    name   = "tag:Name"
    values = [var.node_sg_name]
  }
}

# 최신 x86_64 Amazon Linux 2023 — C-84 는 x86_64 확정(arm64 이미지 가용성 미확인 리스크를
# 월 $5~8 로 산다).
#
# 🔴 SSM 파라미터(`/aws/service/ami-amazon-linux-latest/...`)가 아니라 `ec2:DescribeImages` 로
#    조회한다 — 실제로 apply 해보고 알았다: `mp-dashboard-dev` 에 SSM 파라미터 조회 권한이
#    아예 없다(있는 건 자기 몫인 `/mp/dashboard/*` 뿐, AWS 공용 파라미터는 별개라 걸린다).
#    `ec2:Describe*` 는 `ReadAllEc2AndNetwork` Sid 로 이미 허용돼 있어 이 방식은 추가 권한
#    요청 없이 된다. name 패턴에서 `-minimal-` 계열을 걸러야 표준 AL2023 만 남는다.
data "aws_ami" "al2023_x86" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-kernel-*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}
