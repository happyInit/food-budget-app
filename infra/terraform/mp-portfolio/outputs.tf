output "public_ip" {
  description = "고정 공인 IP. 🔴 Cloudflare DNS 에 직접 넣지 않는다 — 유입은 터널로만 받는다."
  value       = aws_lightsail_static_ip.app.ip_address
}

output "ssh" {
  description = "접속 명령. 키는 Lightsail 콘솔에서 내려받는다(기본 키페어)."
  value       = "ssh ubuntu@${aws_lightsail_static_ip.app.ip_address}"
}

output "backup_user" {
  description = "액세스 키를 발급할 IAM 사용자 (terraform 은 키를 만들지 않는다)."
  value       = aws_iam_user.backup.name
}
