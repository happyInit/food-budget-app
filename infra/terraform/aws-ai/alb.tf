# ALB → Lambda (접수 2종 + chat).
#
# 🔴 **`enable_alb_routes` 를 켜는 것이 곧 트래픽 전환이다**(variables.tf 참조).
#    지금 이 경로들은 ALB 기본 타겟(Istio → 파드)이 받는다. 규칙을 얹는 순간 Lambda 가 받는다.
#
# 🔴 그리고 **ALB → Lambda 요청 본문 상한은 1 MB 다**(AWS 고정). OCR 은 그래서 클라이언트
#    축소가 선행이고, 넘치면 접수가 413 과 함께 presigned 경로를 안내한다 —
#    결정과 근거 = `docs/serverless/07_G-06_…`.

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
  #    범위를 좁히는 것이 인프라 소관(C-77)을 덜 침범한다.
  # ⚠️ 비우면 이 조건이 사라진다 — 호스트가 늘어날 때 의도적으로만 비울 것.
  dynamic "condition" {
    for_each = var.alb_host_header == "" ? [] : [var.alb_host_header]
    content {
      host_header { values = [condition.value] }
    }
  }
}
