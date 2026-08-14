# VPC-B "CI" — C-34 · C-62③(AZ-a 단일) · C-71(**NAT 미채택** = −$39.42/월)
#
# 🔴 여기 EC2(GitLab)는 **NAT 없이 공인 IP 로 직접 아웃바운드**한다. 그 대가가 A-34 의
#    상쇄 조건 3종이고, 그중 두 개를 이 파일이 코드로 강제한다:
#      ① SG 인바운드 0개 (security_groups.tf — cloudflared 아웃바운드 터널로만 들어온다)
#      ② IMDSv2 필수 + hop limit 1 (A-28 의 EC2 는 이 스택 밖 · 그 요구사항을 README 에 남긴다)
#      ③ (남은 하나 = 공개 서브넷 상쇄 점검 · A-34)
# 🔴 **VPC 피어링을 하지 않는다** — config 레포가 GitHub 이라 CI 가 VPC-A 를 볼 필요가 없다(C-61③).
#    이것이 DR 근거이기도 하다: AWS 가 통째로 잠겨도 config 정본은 우리 손에 남는다.

resource "aws_vpc" "ci" {
  cidr_block           = var.vpc_ci_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "mp-vpc-ci" }
}

resource "aws_internet_gateway" "ci" {
  vpc_id = aws_vpc.ci.id
  tags   = { Name = "mp-igw-ci" }
}

# 공개 서브넷 1개. 🟡 AZ-b `10.11.1.0/24` 는 **예약(미생성)** — 만들면 서브넷당 비용은 0 이지만
#    "쓰지 않는 것이 존재한다" 는 상태가 감사 때 매번 설명 대상이 된다.
resource "aws_subnet" "ci_public" {
  vpc_id            = aws_vpc.ci.id
  availability_zone = var.azs[0]
  cidr_block        = cidrsubnet(var.vpc_ci_cidr, 8, 0)

  # 🔴 여기는 켠다 — NAT 가 없으므로 **공인 IP 가 유일한 아웃바운드 경로**다(C-71).
  map_public_ip_on_launch = true

  tags = {
    Name = "mp-subnet-ci-public"
    Tier = "public"
  }
}

resource "aws_route_table" "ci_public" {
  vpc_id = aws_vpc.ci.id
  tags   = { Name = "mp-rt-ci-public" }
}

resource "aws_route" "ci_default" {
  route_table_id         = aws_route_table.ci_public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.ci.id
}

resource "aws_route_table_association" "ci_public" {
  subnet_id      = aws_subnet.ci_public.id
  route_table_id = aws_route_table.ci_public.id
}

# S3 Gateway 엔드포인트 — **무료**. 🔴 CI 에서 이게 특히 중요하다: NAT 가 없으므로
#    ECR 이미지 레이어(= S3 에 실제로 저장된다)가 이 길로 빠지지 않으면 공인 IP 로
#    인터넷을 왕복해야 하고, 빌드마다 수 GB 다.
resource "aws_vpc_endpoint" "ci_s3" {
  vpc_id            = aws_vpc.ci.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.ci_public.id]

  tags = { Name = "mp-vpce-ci-s3" }
}
