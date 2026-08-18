# ALB → Lambda (접수 2종 + chat).
#
# 🔵 **`enable_alb_routes` 는 «컷오버 스위치» 가 아니다**(종전 서술 폐기 — variables.tf 참조).
#    분리 축이 경로가 아니라 **호스트**(`ai.mealbong.cloud`)라, 규칙을 얹어도
#    `aws.`·`app.` 트래픽은 우리 규칙에 매칭되지 않는다. 파드는 그대로 자기 것을 받는다.
#
# 🔴 그리고 **ALB → Lambda 요청 본문 상한은 1 MB 다**(AWS 고정). OCR 은 그래서 클라이언트
#    축소가 선행이고, 넘치면 접수가 413 과 함께 presigned 경로를 안내한다.
#    🟢 프론트가 그 413 을 받아 2단계로 가는 폴백을 갖췄다(2026-08-18 · G-06 해소).

# 🔴 **켜는데 리스너 ARN 이 비어 있으면 여기서 멈춘다.**
#    안 막으면 `listener_arn = ""` 로 apply 가 죽는데, 그 순간엔 «권한이 덜 왔나 · 규칙이
#    틀렸나» 로 보여서 원인이 안 드러난다. 착수는 대개 급한 상황이라 그때 헤매면 비싸다.
#    ⇒ 값이 없다는 사실을 **문장으로** 말하게 한다(오늘 SG 파괴 방어와 같은 형태).
locals {
  _alb_check = (!var.enable_alb_routes || var.alb_listener_arn != "") ? true : tobool(
  "enable_alb_routes = true 인데 alb_listener_arn 이 비어 있다 — ai.tfvars 를 볼 것")
}

resource "aws_lb_target_group" "fn" {
  for_each = var.enable_alb_routes ? local.alb_functions : {}

  # 🔵 이름도 `mp-ai-` 안에 둔다 — 경계가 이름으로 갈리는 설계라 일관성을 지킨다.
  #    (다만 `elasticloadbalancing:Create*` 는 guardrails 가 **통째로 Deny** 라 이름과 무관하게
  #     우리가 못 만든다 — 그래서 `enable_alb_routes` 가 기본 false 다.)
  name        = "mp-ai-tg-${replace(each.key, "-api", "")}"
  target_type = "lambda"

  # 🔵 헬스체크는 끈다. Lambda 타겟의 헬스체크는 **호출마다 과금**되고, 우리 함수는
  #    «떠 있지 않다» 는 상태가 없다(호출되면 뜬다). 대신 관측은 CloudWatch 로 한다.
  health_check { enabled = false }
}

resource "aws_lambda_permission" "alb" {
  for_each = var.enable_alb_routes ? local.alb_functions : {}

  statement_id  = "AllowExecutionFromALB"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn[each.key].function_name
  principal     = "elasticloadbalancing.amazonaws.com"

  # 🔴 타겟그룹으로 **범위를 좁힌다** — 이게 없으면 계정 안의 아무 ALB 나 이 함수를 부를 수 있다
  #    (confused deputy). AWS 문서가 `aws:SourceArn` 을 권고하는 그 자리다.
  source_arn = aws_lb_target_group.fn[each.key].arn
}

resource "aws_lb_target_group_attachment" "fn" {
  for_each = var.enable_alb_routes ? local.alb_functions : {}

  target_group_arn = aws_lb_target_group.fn[each.key].arn
  target_id        = aws_lambda_function.fn[each.key].arn

  # 🔴 권한이 **먼저** 서야 한다. 없으면 등록 시점에 ALB 가 함수를 못 불러서 attach 가 실패한다.
  depends_on = [aws_lambda_permission.alb]
}

resource "aws_lb_listener_rule" "fn" {
  for_each = var.enable_alb_routes ? local.alb_functions : {}

  listener_arn = var.alb_listener_arn
  # 🔴 우선순위가 기존 규칙과 겹치면 apply 가 죽는다. 인프라 담당과 맞출 것(variables.tf).
  #    그리고 **너무 크면 규칙이 아예 안 탄다** — 그쪽이 더 위험하다(variables.tf 의 실측표).
  priority = var.alb_rule_priority_base + index(keys(local.alb_functions), each.key)

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.fn[each.key].arn
  }

  condition {
    # 🔵 `local.alb_paths` = 접두사가 씌워진 경로. 파드의 경로를 안 건드린다(locals.tf).
    path_pattern { values = [local.alb_paths[each.key]] }
  }

  # 🔵 호스트까지 못박는다 — 우리 규칙이 기존 100번 **앞**에 서기 때문이다.
  #    경로만 걸면 이 리스너에 도달하는 *어떤* 호스트의 `/ai/*` 든 Lambda 로 간다.
  # 🔴 값이 **둘**이다(`aws.` + `app.`). 하나만 걸면 A3 컷오버 날 `app.` 쪽이 조용히
  #    100번을 타고 파드로 간다 — variables.tf 의 근거 참조.
  dynamic "condition" {
    for_each = length(var.alb_host_headers) == 0 ? [] : [1]
    content {
      host_header { values = var.alb_host_headers }
    }
  }

  # 🔴 태그가 «권한의 근거» 다. 인프라가 준 조건이 `aws:ResourceTag/Project = mp-ai` 로
  #    `DeleteRule`·`ModifyRule` 을 좁히기 때문에(2026-08-18 회신 ②), 이 태그가 없으면
  #    우리가 만든 규칙을 **우리가 지우지도 못한다.** 장식이 아니다.
  tags = { Project = "mp-ai" }
}
