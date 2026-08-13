# 보안그룹 — 🔴 통제 3층 중 하나다(C-58: SG + Cilium netpol + 라우팅. NACL 미채택).
#
# 🔴 **A-44 를 여기서 읽어야 한다** — C-82 는 근거 ④를 *"ENI 모드면 파드별 SG 를 되찾는다"* 로
#    적었지만 그것은 **vpc-cni 의 branch ENI 기능**이고, Cilium ENI IPAM 은 노드 ENI 의 보조 IP 를
#    나눠 주는 방식이라 **파드가 노드 SG 를 물려받을** 가능성이 크다. ⇒ 아래 노드 SG 는
#    *"파드 전체에 공통으로 걸리는 바닥"* 으로 보고 짜야 하며, **파드 단위 통제는 Cilium netpol 이 한다.**
#    ⇒ SG 를 느슨하게 잡고 "파드별 SG 가 있으니 괜찮다"고 읽으면 안 된다.
#
# 🔴 **이 파일의 `description` 은 전부 ASCII 다 — 한글을 넣지 말 것.** 2026-08-13 1단 apply 에서
#    실패로 잡았다(SG 4개 전멸 → 딸린 규칙·엔드포인트 17개 미생성):
#      `InvalidParameterValue: Value (...) for parameter GroupDescription is invalid.
#       Character sets beyond ASCII are not supported.`
#    🔴 **`terraform plan` 은 이걸 잡지 못한다** — 문자셋 검증이 API 쪽에만 있어서, plan 은
#    117개 전부 초록으로 보여 주고 apply 에서 처음 터진다. 규칙(`aws_vpc_security_group_*_rule`)의
#    description 은 허용 문자셋이 더 좁다(`a-zA-Z0-9. _-:/()#,@[]+=&;{}!$*`).
#    ⇒ **설명은 ASCII 한 줄로 두고, 이유·근거는 이렇게 주석에 쓴다.** 주석은 AWS 로 가지 않는다.

# ── EKS 노드 ──────────────────────────────────────────────────────────────────
# 노드 + (Cilium ENI 상) 파드. 클러스터 내부는 전부 허용 · 외부는 아웃바운드만.
resource "aws_security_group" "node" {
  name        = "mp-sg-eks-node"
  description = "EKS nodes and pods (Cilium ENI). Intra-cluster open, egress only outbound."
  vpc_id      = aws_vpc.service.id

  tags = {
    Name = "mp-sg-eks-node"
    # 🔴 Cilium ENI IPAM 이 새 ENI 에 붙일 SG 를 이 태그로 고른다(operator 의 security-group-tags).
    #    없으면 Cilium 이 기본 ENI 의 SG 를 추정하거나 실패한다.
    "mp.io/cilium-eni" = "true"

    # 🔴 Karpenter `EC2NodeClass.securityGroupSelectorTerms` 가 이 태그로 SG 를 찾는다.
    #    **`aws_ec2_tag` 로 빼지 말 것** — 근거는 `vpc_service.tf` 의 같은 태그 주석(결함 #8).
    "karpenter.sh/discovery" = var.cluster_name
  }

  lifecycle {
    create_before_destroy = true
  }
}

# 노드 ↔ 노드 = 전부 허용. 🔴 이건 느슨한 게 아니라 **필수**다 —
#   ENI 모드에서 파드 간 통신이 이 SG 를 통과하고(파드 IP 가 VPC 주소다),
#   Istio 사이드카·CNPG 스트리밍·ES 트랜스포트·Cilium VXLAN 아닌 native 라우팅이 전부 여기 얹힌다.
#   포트를 세려는 시도는 실패한다(파드 포트는 동적이다). **파드 단위 통제 = netpol 의 몫**이다.
resource "aws_vpc_security_group_ingress_rule" "node_self" {
  security_group_id            = aws_security_group.node.id
  referenced_security_group_id = aws_security_group.node.id
  ip_protocol                  = "-1"
  description                  = "node-to-node and pod-to-pod (ENI mode: pod IPs are VPC addresses)"
}

# 컨트롤플레인 → kubelet/webhook. EKS 가 만드는 클러스터 SG 를 참조한다.
resource "aws_vpc_security_group_ingress_rule" "node_from_control_plane" {
  security_group_id            = aws_security_group.node.id
  referenced_security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 1025
  to_port                      = 65535
  description                  = "control plane to kubelet 10250 and admission webhooks"
}

resource "aws_vpc_security_group_egress_rule" "node_all" {
  security_group_id = aws_security_group.node.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "outbound via NAT and VPC endpoints; fine-grained control is Cilium egress netpol"
}

# ── VPC Interface 엔드포인트 (C-56) ───────────────────────────────────────────
resource "aws_security_group" "endpoint" {
  name        = "mp-sg-vpce"
  description = "Interface endpoint ENIs. 443 from node SG only."
  vpc_id      = aws_vpc.service.id

  tags = { Name = "mp-sg-vpce" }
}

resource "aws_vpc_security_group_ingress_rule" "endpoint_from_node" {
  security_group_id            = aws_security_group.endpoint.id
  referenced_security_group_id = aws_security_group.node.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "nodes and pods to SQS, Secrets Manager, STS"
}

# ── 대시보드 EC2 (C-84) — SG 만 미리 만든다 ───────────────────────────────────
# 🔴 EC2 자체는 이 스택 밖이다(C-84 의 compose 형상 · 계획서 `docs/aws-dashboard-ec2-deployment-plan.md`).
#    SG 를 여기 두는 이유 = **C-85 의 NodePort 경로가 이 SG 를 참조**해야 하고, 그 참조가
#    노드 SG 규칙(아래)의 전제이기 때문이다. SG 만 있고 EC2 가 없는 상태는 무해하다(비용 0).
resource "aws_security_group" "dashboard" {
  name        = "mp-sg-dashboard"
  description = "FinOps and Operations dashboard EC2. Auth is origin oauth2-proxy with Google."
  vpc_id      = aws_vpc.service.id

  tags = { Name = "mp-sg-dashboard" }
}

# 🔴 인바운드 443 은 **전체 개방**이다 — C-84 가 Cloudflare **회색**(DNS 전용)을 골랐으므로
#    CF IP 로 못박을 대상이 없고, *"회색이면 우회라는 개념이 없다"*(C-60)가 그 근거다.
#    방어는 오리진 인증(oauth2-proxy + 이메일 allowlist) + `nginx limit_req` 다.
resource "aws_vpc_security_group_ingress_rule" "dashboard_https" {
  security_group_id = aws_security_group.dashboard.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "users to Nginx 443 (auth at origin: oauth2-proxy)"
}

resource "aws_vpc_security_group_egress_rule" "dashboard_all" {
  security_group_id = aws_security_group.dashboard.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "outbound: external PG 15432, GCP WIF, Bedrock, cluster NodePort"
}

# C-85 = **로드밸런서 0개.** 대시보드가 클러스터를 조회하는 유일한 경로 = NodePort + 노드 사설 IP.
# 🔴 대역이 아니라 **SG 참조**로 좁힌다 — 공개 서브넷에 나중에 뭐가 들어와도 자동으로 열리지 않는다.
# 🔴 대가 = MNG 롤링 업그레이드로 노드가 동시에 교체되면 끊긴다 ⇒ **nginx 502 알림이 필수**다(C-85).
resource "aws_vpc_security_group_ingress_rule" "node_nodeport_from_dashboard" {
  security_group_id            = aws_security_group.node.id
  referenced_security_group_id = aws_security_group.dashboard.id
  ip_protocol                  = "tcp"
  from_port                    = 30000
  to_port                      = 32767
  description                  = "dashboard EC2 to Prometheus and kubecost NodePort (no load balancer)"
}

# ── CI EC2 (VPC-B) ───────────────────────────────────────────────────────────
resource "aws_security_group" "ci" {
  name        = "mp-sg-ci"
  description = "GitLab, SonarQube, Runner EC2. Zero inbound rules: access via cloudflared tunnel."
  vpc_id      = aws_vpc.ci.id

  tags = { Name = "mp-sg-ci" }
}

# 🔴 **인바운드 규칙을 하나도 만들지 않는 것이 이 SG 의 산출물이다.** 규칙 부재를 코드로
#    표현할 방법이 없으므로(빈 SG = 전부 거부) 이 주석이 그 의도의 기록이다.
#    누가 SSH 22 를 열려고 하면 A-34 ① 을 먼저 다시 판정해야 한다.
resource "aws_vpc_security_group_egress_rule" "ci_all" {
  security_group_id = aws_security_group.ci.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "direct outbound via public IP (no NAT): ECR push, GitHub, Cloudflare tunnel"
}
