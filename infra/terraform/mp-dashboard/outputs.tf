# 🔴 이 출력들은 다른 문서·다른 팀원의 입력값이다. 손으로 옮겨 적으면 갈린다.

output "dashboard_public_ip" {
  description = "대시보드 EIP. Cloudflare `ops.`/`finops.` A 레코드가 가리켜야 하는 값(회색·DNS 전용)."
  value       = aws_eip.dashboard.public_ip
}

output "dashboard_instance_id" {
  description = "SSM Session Manager로 접속할 때 --target 에 넣는 값."
  value       = aws_instance.dashboard.id
}

output "dashboard_ssm_command" {
  description = "대화형 셸이 아니라 send-command 를 쓴다(C-84) — 여기 값은 참고용 세션 시작 명령."
  value       = "aws ssm start-session --target ${aws_instance.dashboard.id} --region ${var.region} --profile <프로필>"
}

output "dashboard_role_arn" {
  description = "compose 서비스가 EC2 Instance Profile 로 어떤 권한을 받는지 확인할 때 쓴다."
  value       = aws_iam_role.dashboard.arn
}
