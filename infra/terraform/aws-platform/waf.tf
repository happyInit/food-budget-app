# AWS WAF — `1-49` (C-60 채택 · C-46 을 뒤집은 것)
#
# ── 🔴 이것이 L7 방어의 **전부**다 ────────────────────────────────────────────
# C-60 으로 Cloudflare 를 회색(DNS 전용)으로 내리면서 **CF 무료 L7 DDoS 를 잃었고**,
# ALB 앞에 CloudFront 를 얹어 되사는 안은 **C-75 로 명시 기각**됐다.
# Shield Standard 는 L3/L4 만 하고 Advanced 는 월 $3,000 이라 논외다.
# ⇒ *"AWS WAF 레이트룰이 유일해진다 → 룰 설계 비중이 커진다"*(C-75 원문).
#
# 🔴 **그리고 이건 적응형이 아니다.** Cloudflare 는 학습해서 임계를 스스로 움직였지만
#    여기서는 **우리가 숫자를 적는다.** 틀리면 둘 중 하나다 — 못 막거나, 우리를 막는다.
#
# ── 왜 ALB 인가(부착점) ──────────────────────────────────────────────────────
# AWS WAF 는 CloudFront·**ALB**·API Gateway·AppSync·Cognito·App Runner 에만 붙는다.
# C-46 이 WAF 를 기각한 근거가 *"NLB(L4)에는 부착 자체가 불가"* 였고, C-60 은 그 사실을
# 뒤집은 게 아니라 **LB 를 ALB 로 바꿔 부착점을 만들었다.**

# ── 룰 1 — 레이트 리밋 (`1-41` 이 CF 엣지에서 여기로 대상 교체된 것) ───────────
resource "aws_wafv2_web_acl" "public" {
  name  = "mp-waf-public"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "rate-limit-per-ip"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.waf_rate_limit_per_5min
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "mp-waf-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  # ── 룰 2 — 알려진 악성 입력 (차단) ──────────────────────────────────────────
  # 🔴 이 그룹만 처음부터 **차단**으로 켠다. 매칭 대상이 *알려진 익스플로잇 문자열*
  #    (Log4j JNDI · 경로탈출 · 잘린 헤더 등)이라 정상 요청과 겹칠 여지가 실질적으로 없다.
  rule {
    name     = "aws-known-bad-inputs"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "mp-waf-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  # ── 룰 3 — 공통 룰셋 (🔴 **집계만 · 차단 안 함**) ───────────────────────────
  #
  # 🔴 **차단으로 켜면 우리 앱이 먼저 죽는다.** 확인한 것 두 가지:
  #   ① `SizeRestrictions_BODY` — 본문 **8KB 초과를 차단**한다. `ocr` 이 영수증 이미지를
  #      받고(`ingress/base/request-body-limit.yaml` 이 존재하는 이유가 그것이다) `video` 가
  #      URL 추출 페이로드를 받는다. 켜면 **영수증 업로드가 전건 실패**한다.
  #   ② `CrossSiteScripting_BODY`·`GenericRFI_BODY` — JSON 본문에 오탐이 잦다.
  #      레시피 본문·챗 프롬프트처럼 **자유 텍스트를 받는 엔드포인트**가 정확히 그 표적이다.
  #
  # ⇒ **`count` 로 켜서 먼저 센다.** `1-55`(전환 실증)에서 CloudWatch 메트릭·샘플 요청으로
  #    어떤 룰이 몇 번 걸렸는지 보고, 그때 ⓐ 오탐 룰만 `rule_action_override` 로 빼고
  #    ⓑ 이 블록을 `none {}` 으로 바꾼다. **한 줄 변경이다.**
  # 🔴 세지 않고 차단부터 켜는 것과, 세지도 않고 끄는 것은 둘 다 틀렸다 —
  #    끄면 나중에 켤 근거가 영영 안 생긴다.
  rule {
    name     = "aws-common-ruleset-count-only"
    priority = 3

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "mp-waf-common-ruleset"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "mp-waf-public"
    sampled_requests_enabled   = true
  }

  tags = {
    Name = "mp-waf-public"
  }
}

# 🔴 **부착하지 않으면 Web ACL 은 아무 일도 하지 않는다.** 콘솔에 룰이 보이므로
#    "켜져 있는 것처럼" 보이는 실패 양식이다 — `1-54` 가 CF 회색 전환에 대해 경고한 것과 같은 부류.
resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = aws_lb.public.arn
  web_acl_arn  = aws_wafv2_web_acl.public.arn
}

# ── 🔴 전량 로깅(`aws_wafv2_web_acl_logging_configuration`)은 **일부러 안 켰다** ────
#
# 켜려면 CloudWatch Logs·Firehose·S3 중 하나로 **모든 요청**을 흘려야 하는데, 이 계정은
# 이미 EKS audit 로그로 **월 약 $59** 를 쓰고 있고(C-66) 그 항목 자체가 *"1개월 실측 후 재판정"*
# 으로 열려 있다. 여기서 두 번째 대형 로그 스트림을 무판정으로 여는 것은 그 재판정을 흐린다.
#
# 🟢 **`1-55`(전환 실증)에는 지금 구성으로 충분하다** — `sampled_requests_enabled = true` 가
#    최근 3시간의 실제 매칭 요청을 콘솔·`aws wafv2 get-sampled-requests` 로 보여 주고,
#    CloudWatch 메트릭(`AllowedRequests`/`BlockedRequests`/`CountedRequests`)이 룰별로 찍힌다.
#    ⇒ *"WAF 로그에 요청이 실제로 찍히는지"* 는 이것으로 확인한다.
# 🔴 룰 3 을 차단으로 승격할 때 전량 로깅을 함께 판정할 것 — 그때는 오탐 조사가 필요해진다.
