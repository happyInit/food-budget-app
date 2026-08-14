# 공개 진입 ALB — C-60 (`1-34` · `1-36` · `1-48` · `1-49` · `1-50` · `1-54`)
#
#   유저 → Cloudflare(회색·DNS 전용) → **ALB** (ACM 종단 · AWS WAF) → Istio Gateway → 앱
#
# 🔴 **엣지가 여기 하나다.** C-60 의 근거가 성능도 비용도 아니라 *"엣지를 하나로 만드는 것"*
#    이었다 — CF 주황 + AWS 두 엣지면 *"이 트래픽이 CF 를 거쳤다"* 를 증명하는 장치
#    (CF IP 허용목록 상시 갱신 · mTLS · 헤더 락)가 **영구 운영 부담**으로 남는다.
#    회색이면 그 개념 자체가 없다. ⇒ 이 SG 가 **공개인 것이 정상**이다.
#
# 🔴 **대가도 여기 있다** — CF 무료 L7 DDoS 를 잃었고(C-60①), CloudFront 로 되사는 안은
#    **C-75 로 명시 기각**됐다. ⇒ **L7 방어는 `waf.tf` 의 레이트룰이 유일하다.**
#    SG 오설정이 아니라 **룰 미비**가 이 구성의 실패 양식이다(정본 2080행).

# ── ALB 보안그룹 ──────────────────────────────────────────────────────────────
# 🔴 `description` 은 ASCII 만 — 한글이면 apply 에서 SG 가 전멸한다(파일 `security_groups.tf` 머리말).
resource "aws_security_group" "alb" {
  name        = "mp-sg-alb-public"
  description = "Public ALB. Internet-facing by design: C-60 makes this the only edge."
  vpc_id      = aws_vpc.service.id

  tags = {
    Name = "mp-sg-alb-public"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "users to ALB 443 (TLS terminated here with ACM)"
}

# 🔴 80 을 여는 것은 평문 서비스가 아니라 **301 리다이렉트 전용**이다(아래 리스너).
#    `1-38` = 리다이렉트를 앱(`mp-https-redirect` HTTPRoute)이 하면 **무한 루프**가 된다 —
#    ALB 가 HTTP 로 넘기는데 GW 가 HTTPS 로 되돌리고 ALB 가 다시 HTTP 로 넘긴다.
#    ⇒ 승격은 **여기 리스너 규칙이 한다. 코드 변경 0.**
resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "users to ALB 80, redirect only (see listener http_redirect)"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_nodes" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.node.id
  ip_protocol                  = "-1"
  description                  = "ALB to gateway pods (Cilium ENI: pod IPs are VPC addresses)"
}

# ── 노드 SG 인입 — 🔴 `1-34` 가 *"선행작업 어디에도 없었다"* 고 적은 바로 그 규칙 ──────
#
# 🔴 **여기가 C-82(ENI 모드)의 배당금이 실제로 들어오는 자리다.**
#    오버레이 CNI 였다면 `target-type: instance` 강제 → NodePort → 노드 홉 →
#    `externalTrafficPolicy` 함정 → 헬스체크 포트 문제가 줄줄이 따라왔다.
#    ENI 모드는 **파드 IP 가 진짜 VPC 주소**라 ALB 가 파드에 직접 등록한다(`target-type: ip`).
#    ⇒ NodePort 없음 · 노드 홉 없음 · 헬스체크는 파드의 15021 을 그냥 찌른다.
#
# 🔴 **파드는 노드 SG 를 물려받는다**(A-44 · `security_groups.tf` 머리말). 그래서 "ALB → 파드"의
#    허용을 **노드 SG 에** 적는다. 파드 단위 통제는 여기가 아니라 Cilium netpol 이 한다.
#
# 🔴 포트 443 은 **추측이 아니라 온프렘 실측이다** — `mp-gw-public-istio` Service 의 targetPort 가
#    `15021,80,443` 이다(8080/8443 이 아니다. Istio 게이트웨이가 NET_BIND_SERVICE 로 저포트에 직접
#    바인딩한다 — PSA `restricted` 가 이 capability 하나는 허용한다).
#    ⚠️ EKS 오버레이에서 GW 리스너를 HTTPS→HTTP 로 내려도(`1-50`) **포트 번호 443 은 그대로다.**
resource "aws_vpc_security_group_ingress_rule" "node_from_alb_data" {
  security_group_id            = aws_security_group.node.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "ALB to Istio gateway pod 443 (plaintext HTTP behind ALB per C-60)"
}

resource "aws_vpc_security_group_ingress_rule" "node_from_alb_health" {
  security_group_id            = aws_security_group.node.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 15021
  to_port                      = 15021
  description                  = "ALB health check to Istio gateway readiness port"
}

# ── ALB ───────────────────────────────────────────────────────────────────────
resource "aws_lb" "public" {
  name               = "mp-alb-public"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [for s in aws_subnet.public : s.id]

  # 🔴 `1-36` — 타임아웃 계층은 **ALB 120 > CF 100 > GW ≤75** 로 정렬한다.
  #    기본 60s 면 **ALB 가 CF 보다 먼저 문다.** OAuth 산술 최악이 60.4s 라
  #    (`account/app/oauth.py:22` — token POST 30.2s + userinfo GET 30.2s 직렬)
  #    60s 면 지금도 넘는다. 로그인이 간헐 실패하는 형태로 나타나 원인 찾기가 나쁘다.
  idle_timeout = 120

  # 🔴 헤더 위조 방어. XFF 를 우리가 신뢰하게 되므로(`1-53`) 잘못된 헤더는 ALB 에서 버린다.
  #    ⚠️ 이것만으로 `1-37`(chat 이 XFF **최좌측**을 읽는 결함)은 안 고쳐진다 — 그건 앱 코드다.
  drop_invalid_header_fields = true

  # 🔴 A2 동안은 끈다 — 형상을 여러 번 고쳐 세울 구간이다.
  #    **A3 컷오버 직후 `true` 로 올릴 것**(그때부터 이건 사용자 트래픽의 유일한 입구다).
  enable_deletion_protection = false

  access_logs {
    bucket  = aws_s3_bucket.observability.id
    prefix  = "alb"
    enabled = true
  }

  tags = {
    Name = "mp-alb-public"
  }

  # 🔴 접근로그 버킷 정책이 **먼저** 있어야 한다 — 없으면 ALB 생성이
  #    `Access Denied for bucket` 로 실패한다(ELB 가 생성 시점에 쓰기 테스트를 한다).
  depends_on = [aws_s3_bucket_policy.observability_alb_logs]
}

# ── 타깃그룹 — `target-type: ip` (C-82 로 가능해진 것) ─────────────────────────
resource "aws_lb_target_group" "gateway" {
  name        = "mp-tg-gw-public"
  port        = 443
  protocol    = "HTTP" # 🔴 ALB→GW 구간은 평문이다(C-60 대가 ③ = 형상 분기)
  target_type = "ip"
  vpc_id      = aws_vpc.service.id

  # 🔴 `1-34` — 헬스체크는 **데이터 포트가 아니라 15021** 을 본다.
  #    Envoy 는 라우트가 0개여도 443 에서 200 을 줄 수 있고(또는 404), 반대로 xDS 를 못 받아
  #    **실질 불능인데 포트는 열려 있는** 구간이 있다. `/healthz/ready` 는 istiod 로부터
  #    설정을 받았는지까지 본다 ⇒ "떠 있다" 가 아니라 "**받을 준비가 됐다**" 를 재는 유일한 신호다.
  health_check {
    enabled             = true
    protocol            = "HTTP"
    port                = "15021"
    path                = "/healthz/ready"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # 기본 300초는 파드 교체(롤링·BG·Karpenter 축소)마다 죽은 IP 를 5분간 붙잡는다.
  # Istio 게이트웨이는 종료 시 드레인을 하므로 30초면 충분하다.
  deregistration_delay = 30

  tags = {
    Name = "mp-tg-gw-public"
  }

  # 🔴 이름을 바꾸면 재생성인데, 리스너가 참조 중이라 순서가 꼬인다.
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.public.arn
  port              = 443
  protocol          = "HTTPS"

  # TLS 1.2 하한 + TLS 1.3 지원. 🔴 온프렘 Istio GW 와 정책이 갈리는 지점이다(C-60 대가 ③).
  ssl_policy = "ELBSecurityPolicy-TLS13-1-2-2021-06"

  # 🔴 **`aws_acm_certificate.public.arn` 이 아니라 validation 쪽을 참조한다.**
  #    ELBv2 는 `ISSUED` 인증서만 받는다 — 인증서 리소스를 직접 참조하면 Terraform 이
  #    `PENDING_VALIDATION` 상태에서 리스너를 만들려다 죽는다. 이 참조가 곧 **순서 강제**다.
  certificate_arn = aws_acm_certificate_validation.public.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.gateway.arn
  }
}

# 🔴 `1-38`·`1-51` 의 집행부 — HTTP→HTTPS 승격은 **여기서만** 한다.
#    config 의 `mp-https-redirect` HTTPRoute 는 EKS 오버레이에서 **반드시 걷는다.**
#    남겨 두면: ALB(HTTP 로 전달) → GW(301 to https) → ALB(다시 HTTP 로 전달) → **무한 루프**.
resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.public.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# ── ALB 접근로그 버킷 정책 (`1-55` = *"ALB 접근로그 적재"* 실증 대상) ───────────
#
# 🔴 관측 버킷을 **재사용**한다 — 로그를 위해 버킷을 또 만들면 라이프사이클·암호화·공개차단을
#    세 벌 관리하게 된다(`1-44` 가 전 버킷 표를 요구하는 이유가 그것이다).
#    프리픽스 `alb/` 로 Loki·Tempo 와 갈린다.
#
# 🔴 **`aws_elb_service_account` 를 쓴다** — ap-northeast-2 는 2016년 리전이라 접근로그를
#    *서비스 주체*가 아니라 **리전별 ELB 계정 ID** 로 쓴다. 계정 ID 를 손으로 적으면
#    리전을 바꿀 때 조용히 틀린다.
data "aws_elb_service_account" "main" {}

data "aws_iam_policy_document" "observability_alb_logs" {
  statement {
    sid    = "AllowELBAccessLogs"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = [data.aws_elb_service_account.main.arn]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.observability.arn}/alb/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
  }
}

resource "aws_s3_bucket_policy" "observability_alb_logs" {
  bucket = aws_s3_bucket.observability.id
  policy = data.aws_iam_policy_document.observability_alb_logs.json
}

# ── AWS Load Balancer Controller 용 IRSA — 🔴 **권한을 일부러 좁혔다** ──────────
#
# 왜 컨트롤러가 필요한가 = `target-type: ip` 의 타깃은 **파드 IP** 이고 파드는 재스케줄마다
# 바뀐다. Terraform 은 그것을 따라갈 수 없다. 컨트롤러의 `TargetGroupBinding` CRD 가
# **Service → 타깃그룹** 을 묶어 등록/해제를 대신한다.
#
# 🔴 **그런데 공식 IAM 정책(약 350줄)을 붙이지 않는다.** 그 정책은 컨트롤러가 **ALB·NLB 를
#    스스로 만들 수 있게** 하는 것이고, 우리는 그걸 원하지 않는다 —
#    LB 는 Terraform 이 소유해야 WAF·SG·ACM 배선이 한 곳에 있다(C-77 · `1-49`).
#    ⇒ **`TargetGroupBinding` 에 필요한 것만 준다.**
#
# 🟢 이게 주는 보증이 크다: 누군가 실수로 `Ingress` 나 `Service type: LoadBalancer` 를
#    만들어도 **컨트롤러가 LB 를 만들 권한이 없어 조용히 못 만든다.** 감사 #58 이 경고한
#    *"scheme 을 틀리면 그대로 인터넷 노출"* 이 **권한 수준에서 불가능**해진다.
#    (C-85 = 내부 접근은 LB 0개 · `kubectl port-forward`. 그 결정을 IAM 이 떠받친다.)
resource "aws_iam_role" "lb_controller" {
  name               = "mp-lb-controller"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["lb_controller"].json
}

resource "aws_iam_role_policy" "lb_controller" {
  name = "target-group-binding-only"
  role = aws_iam_role.lb_controller.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 타깃 등록/해제 + 상태 조회. 🔴 `CreateLoadBalancer`·`CreateTargetGroup` 은 **없다**.
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:RegisterTargets",
          "elasticloadbalancing:DeregisterTargets",
          "elasticloadbalancing:DescribeTargetGroups",
          "elasticloadbalancing:DescribeTargetGroupAttributes",
          "elasticloadbalancing:DescribeTargetHealth",
          "elasticloadbalancing:DescribeLoadBalancers",
          "elasticloadbalancing:DescribeListeners",
          "elasticloadbalancing:DescribeRules",
          "elasticloadbalancing:DescribeTags",
        ]
        Resource = "*"
      },
      {
        # 컨트롤러가 기동 시 VPC·서브넷·SG·ENI 를 조회한다(파드 IP → ENI 해석).
        # 🔴 전부 읽기다. 쓰기 동사는 위 블록의 등록/해제 2개뿐이다.
        Effect = "Allow"
        Action = [
          "ec2:DescribeVpcs",
          "ec2:DescribeSubnets",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeInstances",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeAvailabilityZones",
        ]
        Resource = "*"
      },
    ]
  })
}
