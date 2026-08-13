# VPC-A "서비스" — 목표 아키텍처 §1 · C-34 · C-32(AZ 2) · C-33(3티어 6서브넷) · C-47(NAT 1대)

resource "aws_vpc" "service" {
  cidr_block = var.vpc_service_cidr

  # 🔴 둘 다 ON 이 **C-56 의 전제**다 — Interface 엔드포인트의 Private DNS 가 이걸 요구하고,
  #    Private DNS 가 꺼지면 앱이 엔드포인트 전용 호스트명을 알아야 해서 **코드 변경 0** 이 깨진다.
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "mp-vpc-service" }
}

resource "aws_internet_gateway" "service" {
  vpc_id = aws_vpc.service.id
  tags   = { Name = "mp-igw-service" }
}

# ── ① 공개 티어 ───────────────────────────────────────────────────────────────
resource "aws_subnet" "public" {
  for_each = local.public_subnets

  vpc_id            = aws_vpc.service.id
  availability_zone = each.key
  cidr_block        = each.value

  # 🔴 대시보드 EC2(C-84)가 EIP 를 받으므로 자동 공인 IP 는 불필요하고, 켜 두면
  #    나중에 여기 뭘 띄울 때 **의도 없이 인터넷에 노출**된다. 명시적으로 끈다.
  map_public_ip_on_launch = false

  tags = {
    Name = "mp-subnet-public-${each.key}"
    Tier = "public"
    # ALB(1-48·1-49 · A2 에서 생성)가 자동 서브넷 선택을 하려면 이 태그가 필요하다.
    "kubernetes.io/role/elb" = "1"
  }
}

# ── ② 노드 티어 — 🔴 파드도 여기 산다 (C-82 ENI 모드) ────────────────────────
resource "aws_subnet" "node" {
  for_each = local.node_subnets

  vpc_id                  = aws_vpc.service.id
  availability_zone       = each.key
  cidr_block              = each.value
  map_public_ip_on_launch = false

  tags = {
    Name = "mp-subnet-node-${each.key}"
    Tier = "node"
    # 🔴 Cilium ENI IPAM 이 **새 ENI 를 붙일 서브넷을 이 태그로 고른다**(operator 의 subnet-tags-filter).
    #    태그가 없으면 노드 서브넷을 못 찾아 파드에 IP 를 못 준다.
    "mp.io/cilium-eni"                = "true"
    "kubernetes.io/role/internal-elb" = "1"
  }
}

# ── ③ 데이터 티어 — 🔴 밖으로 나가는 경로 없음 ───────────────────────────────
resource "aws_subnet" "data" {
  for_each = local.data_subnets

  vpc_id                  = aws_vpc.service.id
  availability_zone       = each.key
  cidr_block              = each.value
  map_public_ip_on_launch = false

  tags = {
    Name = "mp-subnet-data-${each.key}"
    Tier = "data"
  }
}

# ── NAT — 1대 (C-47) ─────────────────────────────────────────────────────────
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "mp-eip-nat" }

  # EIP 는 IGW 가 붙기 전에 만들면 연결이 실패할 수 있다.
  depends_on = [aws_internet_gateway.service]
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[local.nat_az].id
  tags          = { Name = "mp-nat" }

  depends_on = [aws_internet_gateway.service]
}

# ── 라우팅 테이블 ────────────────────────────────────────────────────────────
# 🔴 **3개다. `A-21` 은 "2개"라고 적고 있다** — 그 항목이 쓰일 때는 데이터 티어의
#    *"밖으로 나가는 경로 없음"*(§1 다이어그램)이 아직 라우팅으로 번역돼 있지 않았다.
#    노드와 데이터가 같은 사설 RT 를 공유하면 **ElastiCache 서브넷에도 NAT 기본 경로가 생긴다.**
#    ⇒ 격리를 지키려면 RT 를 하나 더 만드는 수밖에 없다. 개수는 결과이고 결정은 격리다.
#    (정본 쪽 표기 정정은 `A-21` 에서 다룬다 — 여기서 정본을 고치지 않는다.)

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.service.id
  tags   = { Name = "mp-rt-public" }
}

resource "aws_route" "public_default" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.service.id
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

# 노드 = NAT 경유 아웃바운드. ECR·Bedrock·외부 API(OAuth)가 이 길로 나간다.
resource "aws_route_table" "node" {
  vpc_id = aws_vpc.service.id
  tags   = { Name = "mp-rt-node" }
}

resource "aws_route" "node_default" {
  route_table_id         = aws_route_table.node.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main.id
}

resource "aws_route_table_association" "node" {
  for_each = aws_subnet.node

  subnet_id      = each.value.id
  route_table_id = aws_route_table.node.id
}

# 데이터 = 로컬 전용. 🔴 **기본 경로를 넣지 않는 것이 이 RT 의 존재 이유다.**
resource "aws_route_table" "data" {
  vpc_id = aws_vpc.service.id
  tags   = { Name = "mp-rt-data" }
}

resource "aws_route_table_association" "data" {
  for_each = aws_subnet.data

  subnet_id      = each.value.id
  route_table_id = aws_route_table.data.id
}

# ❌ NACL 미채택 (C-58) — 통제는 SG + Cilium netpol + 라우팅이 한다.
#    NACL 이 되사주지 못하는 것: 파드 단위 통제(SG·netpol 소관) · 서브넷→인터넷(라우팅이 이미 강제).
