# VPC 엔드포인트 — C-56
#
# 🔴 **판단 축이 비용이 아니다.** Interface EP 3종은 월 **$56.94 순증**이고, 그 값을 내는 이유는
#    NAT 가 1대(C-47)라서다 — AZ-a 가 죽으면 두 AZ 의 아웃바운드가 함께 죽는데, 그때
#    **SQS(파이프라인)·Secrets Manager·STS(IRSA 토큰 교환)** 가 NAT 를 안 거치면 살아남는다.
#    ⇒ 이건 절감이 아니라 **보험**이다.
#
# ❌ ECR Interface EP 미채택 — 이미지 레이어의 실제 바이트가 S3 에 있어 Gateway EP(무료)로 빠진다.
# ❌ KMS Interface EP 미채택 — 파드가 KMS 를 직접 부르지 않는다. S3·EBS·SM 이 우리 VPC 밖에서 부른다.

# S3 = Gateway 엔드포인트 (무료).
# 🔴 노드 RT 에만 붙인다 — 데이터 RT 는 *"밖으로 나가는 경로 없음"* 이 산출물이고(vpc_service.tf),
#    ElastiCache 는 S3 를 부르지 않는다. barman(WAL)·논리덤프·크롤 업로드는 전부 노드 티어 파드다.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.service.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.node.id]

  tags = { Name = "mp-vpce-s3" }
}

resource "aws_vpc_endpoint" "interface" {
  for_each = toset(local.interface_endpoints)

  vpc_id            = aws_vpc.service.id
  service_name      = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type = "Interface"

  # 🔴 **노드 서브넷 × 2AZ.** 같은 AZ 안에서 호출이 끝나야 cross-AZ 전송료가 0 이다(C-56 ①).
  #    EP 의 실물은 서브넷 안 ENI 이므로 AZ 당 1장씩 = 3종 × 2AZ = ENI 6장.
  subnet_ids          = [for az, s in aws_subnet.node : s.id]
  security_group_ids  = [aws_security_group.endpoint.id]
  private_dns_enabled = true # 🔴 이게 "앱 코드·설정 변경 0" 의 전부다 (C-56 ②)

  tags = { Name = "mp-vpce-${each.key}" }
}
