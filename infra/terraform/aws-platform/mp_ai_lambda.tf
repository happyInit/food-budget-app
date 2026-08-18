# ── mp-ai Lambda → 데이터 티어 인그레스 (2026-08-17) ──────────────────────────
#
# 🔴 **이 파일이 통째로 «옆 프로젝트에 뚫어 준 구멍» 이다.** 회수 = 파일 삭제 또는
#    `mp_ai_lambda_access = false` 후 apply ⇒ 규칙 4개만 사라진다. 한 곳에 모은 이유가 그것이다.
#    (그래서 변수도 `variables.tf` 가 아니라 여기 둔다 — 지울 때 한 파일로 끝나야 한다.)
#
# 상대 = `mp-ai` 트랙(서버리스·**독립 프로젝트**, EKS 앱 이전이 아니다). 함수는 VPC 안에서
# 돌고 `mp-ai-lambda` SG 를 단다. 인그레스는 **받는 쪽에 다는 것**이라 그쪽 IAM 으로는
# 넣을 수 없다 — 노드·캐시 SG 가 `Project=mealplanning` 이라 `DenySecurityGroupsNotOwnedByMpAi`
# 가 막는다(`infra/iam/mp-ai/mp-ai-guardrails.json`). ⇒ **구조상 이쪽 몫이다.**

# 🔴 상대 SG 는 **이 스택 밖**에서 만들어진다(`Project=mp-ai` 태그를 그쪽 IAM 이 강제한다).
#    참조 방법이 둘인데 —
#      ① SG ID 리터럴 → **채택 안 함.** 이 레포는 공개고 `.tf` 에 `sg-…` 리터럴은 **0건**이며,
#         `infra/terraform/.gitignore` 가 tfvars 를 통째로 막은 이유가 «네트워크 구조를 적지 않는다» 다.
#         게다가 상대가 SG 를 다시 만들면 ID 가 어긋나 **apply 에서 처음** 터진다.
#      ② **태그 조회** → 이걸 쓴다. 재생성을 자동으로 따라가고 레포에 ID 가 남지 않는다.
#    대가 = SG 가 사라지면 **`plan` 이 죽는다**(0건 매칭 = 에러). 그때는 토글을 내린다.
#    🔵 이건 결함이 아니라 의도다 — 상대가 SG 를 지웠는데 규칙만 남아 있는 상태가 더 나쁘다.
data "aws_security_group" "mp_ai_lambda" {
  count = var.mp_ai_lambda_access ? 1 : 0

  vpc_id = aws_vpc.service.id

  # 🔴 태그 **두 개를 다** 건다 — `Name` 만 걸면 남이 같은 이름을 쓰는 순간 조용히 그쪽을 참조한다.
  #    `Project=mp-ai` 는 그쪽 IAM 이 생성 시점에 강제하므로 위조하려면 IAM 을 먼저 넘어야 한다.
  tags = {
    Name    = "mp-ai-lambda"
    Project = "mp-ai"
  }
}

variable "mp_ai_lambda_access" {
  description = <<-EOT
    mp-ai Lambda 에 데이터 티어 인그레스를 열지 여부. `false` 면 이 파일의 규칙 4개와
    SG 조회가 통째로 사라진다(= 회수 스위치).
    🔴 상대 SG(`mp-ai-lambda`)가 없는 상태로 `true` 면 **plan 이 죽는다** — 상대가 SG 를
       지웠거나 아직 안 만들었다면 이 값을 `false` 로 내리고 apply 할 것.
  EOT
  type        = bool
  default     = true
}

# ── ① 노드 NodePort 2종 (C-85 = 로드밸런서 0개) ──────────────────────────────
#
# 대상 Service = config 레포 `platform/policies-data/overlays/eks/lambda-access.yaml`
#   30094 → `data/mp-pg-pooler-nodeport` (CNPG pooler 5432)
#   30095 → `data/mp-es-nodeport`        (ES 9200)
# 🔴 **SG 를 열어도 그것만으로는 안 닿는다** — data ns 는 Cilium netpol 이 걸려 있어
#    상대가 `netpol-lambda.yaml` 을 `resources` 에 넣는 시점에 비로소 뚫린다. 여기는 «바깥문» 이다.
# 🔵 대시보드는 같은 자리에서 30000-32767 **전 범위**를 받는데(`security_groups.tf`),
#    여기는 **2포트만** 연다. 선례보다 좁은 것이 의도다.
resource "aws_vpc_security_group_ingress_rule" "node_nodeport_from_mp_ai_lambda" {
  for_each = var.mp_ai_lambda_access ? {
    pg = { port = 30094, note = "PG pooler" }
    es = { port = 30095, note = "Elasticsearch" }
  } : {}

  security_group_id            = aws_security_group.node.id
  referenced_security_group_id = data.aws_security_group.mp_ai_lambda[0].id
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port

  # 🔴 description 은 ASCII 만 — `security_groups.tf` 머리말의 결함 기록 참조
  #    (`plan` 은 통과하고 `apply` 에서만 터진다).
  description = "mp-ai Lambda to ${each.value.note} NodePort (no load balancer)"
}

# ── ② ElastiCache Valkey 6379 ────────────────────────────────────────────────
#
# 🔴 이건 netpol 이 없는 경로다 — 캐시는 **클러스터 밖**이라 SG 가 유일한 문이고,
#    이 한 줄만으로 즉시 통한다. (그래서 상대의 스모크가 `TimeoutError` 로 죽고 있었다.)
# ⚠️ `elasticache.tf` 의 머리말 *"클라이언트 = EKS 노드/파드뿐. 넓히지 말 것"* 을 **여기서 넓힌다.**
#    근거 = mp-ai 함수 3종이 세션·큐 상태를 이 Valkey 에 둔다. 별도 캐시를 세우지 않는 판단은
#    비용(노드 추가)과 운영면(캐시 2벌) 양쪽 때문이고, 격리는 **키 접두사가 아니라 SG 단위**로만
#    보장된다는 점을 알고 여는 것이다. 🔴 더 넓히려면 그때 전용 캐시를 먼저 검토할 것.
resource "aws_vpc_security_group_ingress_rule" "elasticache_from_mp_ai_lambda" {
  count = var.mp_ai_lambda_access ? 1 : 0

  security_group_id            = aws_security_group.elasticache.id
  referenced_security_group_id = data.aws_security_group.mp_ai_lambda[0].id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
  description                  = "Valkey from mp-ai Lambda"
}

# ── ③ VPC 인터페이스 엔드포인트 443 (Secrets Manager · STS · SQS) ─────────────
#
# 🔴 **이걸 빠뜨려서 함수 10종 중 배치 5종이 전부 죽어 있었다**(2026-08-18 실측).
#
#      [ERROR] ConnectTimeoutError: Connect timeout on endpoint URL:
#              "https://secretsmanager.ap-northeast-2.amazonaws.com/"
#        common/secrets.py:42  boto3.client("secretsmanager").get_secret_value(...)
#
#    `mp-ai-price-detect` 는 **INIT 이 160초** 걸리고 `Runtime.Unknown` 으로 끝났다.
#    `secrets.inject()` 가 모듈 최상단에서 도는 설계라 **import 단계에서** 죽는다.
#
# 🔴 **«NAT 가 있으니 나가겠지» 가 이 사고의 핵심 오해다.** 노드 서브넷에 NAT 라우트는 있다.
#    그런데 `endpoints.tf` 가 `private_dns_enabled = true` 라 AWS API DNS 이름이 **VPC 안
#    엔드포인트 ENI 로 해석**된다 — 즉 NAT 로 가는 경로 자체가 선택되지 않는다.
#    ⇒ 인터페이스 엔드포인트에서 **SG 가 유일한 문**이고, 여기가 막히면 폴백이 없다.
#
# 🔴 그리고 **증상이 원인을 안 가리킨다.** SG 드롭은 거부가 아니라 **무응답**이라 커넥트
#    타임아웃으로 나타난다 — *"자격증명이 틀렸나 · IAM 이 모자라나 · 시크릿 이름이 틀렸나"* 로
#    읽히고, 실제로 그 셋을 먼저 의심하게 된다. 같은 모양을 이 프로젝트에서 반복해 밟았다
#    (Cilium `toFQDNs` 누락 · Loki S3 가상호스트 이름 · EKS netpol 라벨 누락).
#
# 🔵 범위 = 기존 `endpoint_from_node`(노드 SG)와 **똑같이 443 한 포트**다. 엔드포인트가
#    무엇을 노출하는지는 `endpoints.tf` 의 `local.interface_endpoints` 가 정하고, 여기서
#    늘어나는 것은 «누가 그 문을 두드릴 수 있나» 뿐이다.
# ⚠️ STS·SQS 도 같은 엔드포인트 SG 를 공유한다 — 이 한 줄이 셋을 동시에 연다. 셋 다
#    상대가 실제로 쓰는 것이다(시크릿 조회 · 역할 자격증명 · 워커 큐).
resource "aws_vpc_security_group_ingress_rule" "endpoint_from_mp_ai_lambda" {
  count = var.mp_ai_lambda_access ? 1 : 0

  security_group_id            = aws_security_group.endpoint.id
  referenced_security_group_id = data.aws_security_group.mp_ai_lambda[0].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443

  # 🔴 description 은 ASCII 만 (위 ① 의 결함 기록 참조)
  description = "mp-ai Lambda to interface endpoints (Secrets Manager, STS, SQS)"
}
