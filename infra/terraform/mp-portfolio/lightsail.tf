# 밀플래닝 포트폴리오 호스트 — Lightsail 1대에 전 서비스를 올린다.
#
# 왜 EC2 가 아니라 Lightsail 인가:
#   · 스토리지·고정IP·전송량이 요금에 포함이라 월 $24 고정. EC2 는 인스턴스 $30 + EBS + IPv4 로 쪼개진다
#   · 약정이 없다. EC2 + Savings Plan 이 월 $23 로 근소하게 싸지만 1년($276)이 묶인다
#   · VPC·서브넷·IGW·라우팅테이블을 만들 필요가 없다 (aws-platform 철거 후 남길 것이 적다)
#
# 대가:
#   · x86_64 뿐이라 ECR 의 arm64 이미지를 못 쓴다 → 이 호스트에서 직접 빌드한다
#   · IAM 인스턴스 프로파일이 없다 → S3 접근은 아래 IAM 사용자의 액세스 키로 한다

resource "aws_lightsail_instance" "app" {
  name              = "mp-portfolio"
  availability_zone = var.availability_zone
  blueprint_id      = var.blueprint_id
  bundle_id         = var.bundle_id
  user_data         = file("${path.module}/user_data.sh")

  tags = {
    Name = "mp-portfolio"
    Role = "all-in-one"
  }
}

# 고정 IP. Lightsail 은 인스턴스에 붙어 있는 한 추가 과금이 없다(EC2 의 퍼블릭 IPv4 $3.65/월과 다르다).
resource "aws_lightsail_static_ip" "app" {
  name = "mp-portfolio-ip"
}

resource "aws_lightsail_static_ip_attachment" "app" {
  static_ip_name = aws_lightsail_static_ip.app.name
  instance_name  = aws_lightsail_instance.app.name

  # 🔴 인스턴스를 교체하면 이 부착도 같이 다시 만들어야 한다. 이름만 참조하면 이름이 안 바뀌어서
  #    테라폼이 "변경 없음"으로 보고 넘어가고, 실물은 고정 IP 가 떨어진 채 임시 IP 로 뜬다
  #    (2026-08-30 실제로 겪음).
  lifecycle {
    replace_triggered_by = [aws_lightsail_instance.app.id]
  }
}

# 🔴 웹 인바운드를 열지 않는다. 외부 유입은 cloudflared 가 아웃바운드로 만든 터널로만 들어온다.
#    이 리소스는 선언한 포트만 남기고 나머지(기본 80 포함)를 닫는다.
resource "aws_lightsail_instance_public_ports" "app" {
  instance_name = aws_lightsail_instance.app.name

  # 🔴 위와 같은 이유. 새 인스턴스는 Lightsail 기본값(22·80 개방)으로 뜨므로
  #    교체 때 이 규칙을 다시 밀어넣지 않으면 80 이 열린 채로 남는다.
  lifecycle {
    replace_triggered_by = [aws_lightsail_instance.app.id]
  }

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = [var.ssh_allowed_cidr]
  }
}
