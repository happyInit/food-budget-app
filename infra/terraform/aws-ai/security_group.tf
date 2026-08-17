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
  count = var.create_security_group ? 1 : 0

  name = "mp-ai-lambda"
  # 🔴 **실물과 한 글자도 다르면 안 된다** — SG description 은 **불변**이라 바뀌면 Terraform 이
  #    «replace» 로 판단하고 **ID 가 바뀐다.** 그 ID 는 노드 SG·ElastiCache SG 의 인그레스 규칙이
  #    참조하는 값이라, 조용히 갈리면 **Lambda 가 데이터 티어에 못 닿는다.**
  #    (2026-08-17 실측: 이 한 줄 때문에 plan 이 destroy+create 를 내밀었다.)
  description = "mp-ai Lambda functions in VPC - outbound only"
  vpc_id      = var.vpc_id

  # 🔴 태그가 없으면 **생성 자체가 거부**된다(`DenyCreatingUntaggedSecurityGroup`).
  #    그리고 이 태그가 이후 규칙 변경 권한의 근거이기도 하다 — 지우면 **우리도 못 만진다**
  #    (`DenySecurityGroupsNotOwnedByMpAi` 가 `ec2:ResourceTag/Project == mp-ai` 로 판정한다).
  tags = { Name = "mp-ai-lambda", Project = "mp-ai" }

  lifecycle {
    # 🔴🔴 **태그를 Terraform 이 건드리지 못하게 한다. 이유가 둘이고 둘 다 크다.**
    #
    # ① **못 한다** — `mp-ai-dev` 의 `TagOnCreateOnly` 가 `ec2:CreateTags` 를
    #    `ec2:CreateAction` 조건부로만 허용한다. 즉 **생성 시점에만** 태그를 붙일 수 있고
    #    사후 변경은 거부다. 프로바이더의 `default_tags`(ManagedBy·Stack)를 얹으려 하면
    #    `UnauthorizedOperation: ec2:CreateTags` 로 apply 가 죽는다(2026-08-17 실측).
    #
    # ② **하면 안 된다** — `default_tags` 에 **`Project = "mealplanning"`** 이 있다.
    #    그게 덮이면 이 SG 의 `Project` 가 `mp-ai` 가 아니게 되고, 그 순간
    #    `DenySecurityGroupsNotOwnedByMpAi` 가 **우리를 막는다** — 우리가 만든 SG 를
    #    우리가 못 고치는 상태가 된다. 🔵 다행히 ①이 먼저 걸려서 사고가 안 났다.
    #
    # ⇒ 태그는 **생성 시 확정**이고 이후 불변이다. 바꿔야 하면 SG 를 새로 만든다.
    ignore_changes = [tags, tags_all]
  }
}

# ── 이그레스 — 🔴 **Terraform 이 관리하지 않는다. 관리할 수 없다.** ──────────────
#
# 🔵 **필요한 규칙은 이미 있다** — AWS 가 SG 를 만들 때 붙여 주는 전체허용
#    (`sgr-02ec80f985581612d` · `-1` → `0.0.0.0/0`)이 그대로 살아 있고, 그게 우리가 원하는
#    바로 그것이다(Bedrock·Gemini 는 NAT 로, SQS·SecretsManager·S3 는 VPC 엔드포인트로 나간다).
#
# 🔴 **왜 코드로 안 두나 — 두 겹으로 막힌다**(2026-08-17 실측):
#    ~~① `AuthorizeSecurityGroupEgress` 가 rule 리소스에서 explicitDeny~~
#       ✅ **해소됨**(guardrails v3 · 2026-08-17 11:39) — `Resource` 가 `security-group/*` 로
#          좁혀지면서 태그 없는 rule 리소스가 더는 안 걸린다. 실측 `allowed` 확인.
#    🔴 **② 는 그대로 남아 있다 — 이것 하나 때문에 여전히 못 관리한다.**
#       `TagOnCreateOnly` 가 `ec2:CreateTags` 를 **`security-group/*` 에만**, 그것도
#       `ec2:CreateAction == CreateSecurityGroup` 조건으로만 허용한다.
#       ⇒ `security-group-rule` 에는 **생성 시점에도** 태그를 못 붙이는데, 프로바이더는
#          `default_tags` 3개를 항상 실어 보낸다 → `CreateTags` 거부 → apply 사망.
#          `lifecycle { ignore_changes = [tags_all] }` 로도 안 막힌다(프로바이더 한계, 실측).
#
# ⇒ **되살리려면** `TagOnCreateOnly` 에 `arn:aws:ec2:*:*:security-group-rule/*` 와
#    `ec2:CreateAction` 값 확장이 필요하다. 그때까지는 실물(AWS 기본 규칙)을 그대로 둔다.
#    🔵 급하지 않다 — 필요한 동작(전체 아웃바운드)은 이미 나오고 있다.
#
#   resource "aws_vpc_security_group_egress_rule" "all" {
#     security_group_id = aws_security_group.lambda[0].id
#     ip_protocol       = "-1"
#     cidr_ipv4         = "0.0.0.0/0"
#   }
