# ACM 인증서 — 🔴 **C-60 이 만든 새 물건이다**(온프렘에는 대응물이 없다).
#
# ── 왜 인증서가 두 벌이 되는가 ────────────────────────────────────────────────
# 온프렘은 cert-manager 가 Let's Encrypt(DNS-01)로 발급해 **Istio Gateway 가 TLS 를 끊는다**.
# AWS 는 **ALB 가 끊는다**(C-60) ⇒ 인증서 주체가 갈린다.
# 🔴 정본이 이 대가를 명시해 뒀다 — *"온프렘(LE) ↔ AWS(ACM) 인증서 체계가 갈린다 =
#    C-3 상시증명에서 한 겹 더 빠진다"*(§C-26 검사표). **이건 결함이 아니라 지불한 값이다.**
# 🟢 대신 얻는 것 = 갱신이 AWS 자동(만료 없음) · 개인키가 우리 손에 없다 · cert-manager
#    DNS-01 에 필요한 **Cloudflare API 토큰이 AWS 쪽에는 아예 필요 없다**.
#
# ── 🔴 SAN 이 2개인 이유 = A2 와 A3 가 다른 호스트를 쓴다 ──────────────────────
#   `aws.mealbong.cloud`  A2 내부 검증용 (C-78 = *"앱 12종 + aws.mealbong.cloud 내부 검증"*)
#   `app.mealbong.cloud`  A3 컷오버 때 실제 사용자 트래픽이 옮겨 오는 이름 (1-54)
# 한 인증서에 둘 다 넣는다 — A3 에서 인증서를 **다시 만들지 않기 위해서**다. 컷오버 창은
# 5~10분(C-78)이고 그 안에 ACM 발급·검증을 끼워 넣으면 창이 인증서 전파에 걸린다.
#
# ── 🔴 Cloudflare 쪽 함정 2개 ─────────────────────────────────────────────────
#  ① **검증 CNAME 은 반드시 회색(DNS only)** 이어야 한다. 주황(프록시)이면 Cloudflare 가
#     자기 주소를 돌려주고 ACM 이 값을 못 읽어 **영원히 PENDING_VALIDATION** 이다.
#  ② **와일드카드 레코드가 `aws.` 를 미리 가로챈다**(실측). `*.mealbong.cloud` 가 회색으로
#     사설주소를 가리키고 있어서 `aws.mealbong.cloud` 는 NXDOMAIN 이 아니라 **타임아웃**으로
#     보인다. ⇒ `aws` A/CNAME 레코드를 **명시적으로** 만들어야 와일드카드보다 우선한다.
#     (검증용 `_xxx.aws.mealbong.cloud` CNAME 은 더 긴 이름이라 와일드카드보다 우선한다 — 무해)

resource "aws_acm_certificate" "public" {
  domain_name               = var.public_domain
  subject_alternative_names = [var.verify_domain]
  validation_method         = "DNS"

  tags = {
    Name = "mp-cert-public"
  }

  # 🔴 인증서를 바꿔야 할 때 **리스너가 참조 중이라 삭제가 막힌다.** 새로 만들고 나서 지운다.
  lifecycle {
    create_before_destroy = true
  }
}

# ── 🔴 2단 apply — 검증 레코드를 사람이 Cloudflare 에 넣어야 한다 ──────────────
#
# DNS 가 아직 IaC 밖이다(`1-56` = `cloudflare` provider·`cloudflare_record` **0건**).
# 그래서 이 사이에 **손 작업 한 번**이 낀다:
#
#   1단  terraform apply -target=aws_acm_certificate.public
#   2단  terraform output acm_validation_records   → Cloudflare 에 CNAME 2개 추가(🔴 회색)
#   3단  terraform apply                            → 아래 validation 이 확인하고 ALB 가 선다
#
# 🔴 **여기서 `-target` 을 쓰는 것은 `create_node_group` 때 `-target` 을 기각한 것과 모순이 아니다.**
#    그때 기각한 이유는 *"-target 이 의존성만 끌어와 네트워크·IRSA·SG 가 통째로 빠진다"* 였다
#    (`variables.tf` 주석). 이 리소스는 **의존성이 provider 하나뿐인 잎(leaf)** 이라 그 문제가
#    성립하지 않는다 — 딸려 오는 것이 없어서 1단이 정확히 인증서 1개다.
#
# ⚠️ 이 리소스를 넣지 않고 그냥 apply 하면 ALB 리스너가 `PENDING_VALIDATION` 인증서를 붙이려다
#    `CertificateNotFound` 로 죽는다(ELBv2 는 ISSUED 만 받는다). 즉 이 대기는 편의가 아니라 **순서 강제**다.
resource "aws_acm_certificate_validation" "public" {
  certificate_arn = aws_acm_certificate.public.arn

  # 🔴 기본 75분을 30분으로 줄인다 — 레코드를 안 넣었을 때 **빨리 실패하는 편이 싸다**.
  #    ACM 은 레코드가 맞으면 보통 1~5분 안에 ISSUED 로 간다.
  timeouts {
    create = "30m"
  }
}
