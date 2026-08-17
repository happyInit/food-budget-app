# Lambda ENI 가 붙을 보안그룹 — 🔵 **우리 것을 만든다. 남의 것을 빌리지 않는다.**
#
# 🔴 노드 SG 를 재사용하지 않는 이유가 편의가 아니라 **소관**이다. 노드 SG 는 이관 본체이고
#    (`docs/mp_aws_team_access.md §4` — "구조상 관리자에게 남는 것 ①"), 거기에 Lambda 를
#    얹으면 우리 함수가 **노드가 가진 규칙 전부**를 물려받는다. 나중에 그 SG 를 손볼 때
#    "여기 Lambda 도 붙어 있었나" 를 아무도 기억하지 못한다.
#
# 🔵 그리고 정책이 이 경로를 **명시적으로 열어 뒀다**(2026-08-17 실측):
#      ec2:CreateSecurityGroup            aws:RequestTag/Project = mp-ai  → allowed
#                                          태그 없이                       → **explicitDeny**
#      Authorize/Revoke·Delete            ec2:ResourceTag/Project = mp-ai → allowed
#                                          그 밖의 SG                      → **explicitDeny**
#    즉 «태그가 곧 소유권» 이다. 만들되 **태그를 떼면 우리도 못 만진다** — 우회 차단이 양방향이다.
#
# 🔴 **인그레스가 없다. 없는 게 맞다.** Lambda 는 항상 **거는 쪽**이다(PG·ES·Valkey·Bedrock).
#    받는 쪽 규칙은 **상대 SG** 에 달아야 하고, PG·ES 는 노드 SG 라 그건 관리자 몫이다(위 ①).

resource "aws_security_group" "lambda" {
  count = var.security_group_id == "" ? 1 : 0

  name        = "mp-ai-lambda"
  description = "AI Lambda ENI - outbound only (PG/ES/Valkey/Bedrock/Gemini)"
  vpc_id      = var.vpc_id

  # 🔴 태그가 없으면 **생성 자체가 거부**된다(`DenyCreatingUntaggedSecurityGroup`).
  #    그리고 이 태그가 이후 규칙 변경 권한의 근거이기도 하다 — 지우지 말 것.
  tags = { Name = "mp-ai-lambda", Project = "mp-ai" }
}

# 🔵 이그레스를 **명시적으로** 연다. AWS 가 SG 를 만들 때 붙여 주는 기본 전체허용에 기대지 않는다 —
#    Terraform 은 규칙을 배타적으로 관리해서 그 기본값을 회수하고, 그러면 함수가 밖으로 못 나간다.
#    (Bedrock·Gemini 는 NAT 로, SQS·SecretsManager·S3 는 VPC 엔드포인트로 나간다.)
resource "aws_vpc_security_group_egress_rule" "all" {
  count = var.security_group_id == "" ? 1 : 0

  security_group_id = aws_security_group.lambda[0].id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
  description       = "all outbound"
}
