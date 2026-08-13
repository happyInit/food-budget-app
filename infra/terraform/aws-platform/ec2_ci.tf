# CI 서버 (GitLab Omnibus + SonarQube docker + 러너) — A0.5 · A-28
#
# 정본 = C-2(CI = GitLab) · C-38(`t4g.xlarge` 4vCPU/16GiB + 스왑 · SonarQube 동거)
#      · C-59(Omnibus deb / SonarQube docker) · C-61①(러너 = 같은 기계 privileged DinD)
#      · C-63(arm64 확정 · `m7i` 미채택) · C-37(**키페어 금지**) · C-61⑥(Ansible over SSM)
#
# 🔴 **네트워크는 이 파일에 없다** — VPC-B·서브넷·IGW·RT·S3 EP 는 `vpc_ci.tf`, SG 는
#    `security_groups.tf` 의 `aws_security_group.ci` 에 **A0 에서 이미 만들어져 있다**
#    (인바운드 규칙 0개 = cloudflared 아웃바운드 터널로만 들어온다 · A-34①).
#    ⇒ 이 파일은 그 위에 얹는 **컴퓨트 델타**다.

# AMI = Canonical 이 발행하는 SSM 공개 파라미터. 🔴 AMI ID 를 하드코딩하지 않는다 —
#   리전마다 다르고 갱신되며, 하드코딩하면 "왜 이 ID 인가"를 아무도 설명할 수 없다.
#   🟢 이것도 `ssm:GetParameter` 지만 **공개 파라미터**다(Karpenter 의 AMI 조회와 같은 계열).
#      우리 비밀 경로(`mp/prod/*` · Secrets Manager · C-36)와 무관하다.
data "aws_ssm_parameter" "ubuntu_arm64" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id"
}

# ── Ansible over SSM 이 파일 전송에 쓰는 버킷 (C-61⑥) ────────────────────────
# 🔴 `community.aws.aws_ssm` 커넥션은 **S3 를 경유해 파일을 옮긴다** — 버킷이 없으면
#    플레이가 첫 `copy`/`template` 에서 죽는다. Session Manager 자체는 무료지만 이건 별개다.
# 🟢 바이트는 `vpc_ci.tf` 의 S3 Gateway 엔드포인트로 빠진다(무료 · NAT 없음).
# 🔴 **백업 버킷(`mp-backup-ap2`)을 재사용하지 않는다** — 그쪽은 백업 전용이고, 전송용
#    임시 객체가 섞이면 라이프사이클·권한 판단이 오염된다(0-22·A-49 와 같은 이유).
resource "aws_s3_bucket" "ssm_transfer" {
  bucket = "mp-ssm-transfer-${var.region_short}"
  tags   = { Name = "mp-ssm-transfer" }
}

resource "aws_s3_bucket_public_access_block" "ssm_transfer" {
  bucket                  = aws_s3_bucket.ssm_transfer.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ssm_transfer" {
  bucket = aws_s3_bucket.ssm_transfer.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# 🔴 전송 객체는 하루면 쓸모가 없다. 안 지우면 **플레이북이 옮긴 파일이 영구히 남는다** —
#    그중에 `gitlab.rb`(초기 root 비번·시크릿 토큰 포함 가능) 같은 것이 들어간다.
resource "aws_s3_bucket_lifecycle_configuration" "ssm_transfer" {
  bucket = aws_s3_bucket.ssm_transfer.id
  rule {
    id     = "expire-transfer-objects"
    status = "Enabled"
    filter {}
    expiration { days = 1 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

# ── IAM — 🔴 키페어가 없으므로 이 롤이 유일한 접근·권한 경로다 (C-37) ─────────
resource "aws_iam_role" "ci" {
  name = "mp-ci-server"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = { Name = "mp-ci-server" }
}

# Session Manager. 🔴 이것이 SSH 를 대체한다 — 없으면 **기계에 들어갈 방법이 아예 없다**
#    (SG 인바운드 0개 + 키페어 없음). 관리형 정책을 쓰는 이유 = AWS 가 SSM 기능 추가에
#    맞춰 갱신하는 목록이고, 우리가 베낀 사본은 조용히 낡는다.
resource "aws_iam_role_policy_attachment" "ci_ssm" {
  role       = aws_iam_role.ci.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# ECR push — 🔴 **A0.5 의 완료 판정이 이 권한에 달려 있다**(ECR 18리포에 arm64 이미지 적재).
resource "aws_iam_role_policy" "ci_ecr" {
  name = "ecr-push"
  role = aws_iam_role.ci.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 🔴 `GetAuthorizationToken` 은 **리소스를 지정할 수 없다**(`*` 필수) — 리포별로
        #    좁힐 수 없는 계정 단위 동작이다. 아래 문장이 실제 경계를 만든다.
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
          # pull 도 필요하다 — 멀티스테이지 빌드가 자기 베이스 이미지를 당기고,
          # Trivy 게이트가 방금 푸시한 이미지를 다시 읽는다.
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:DescribeImages",
          "ecr:ListImages",
        ]
        # 🔴 A-46 = 리포 접두사 `mealplanning/` 유지. 이 경계 덕분에 CI 가 다른 리포를 못 만진다.
        #    ⚠️ `ecr:CreateRepository` 를 **주지 않는다** — 리포는 Terraform 소관(`ecr.tf` 18개)이고,
        #       CI 가 만들 수 있으면 오타 하나가 새 리포를 만들어 A2 에서 pull 실패로 드러난다.
        Resource = "arn:aws:ecr:${var.region}:${data.aws_caller_identity.current.account_id}:repository/mealplanning/*"
      },
      {
        # Ansible over SSM 의 파일 전송 버킷 (C-61⑥)
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.ssm_transfer.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = aws_s3_bucket.ssm_transfer.arn
      },
    ]
  })
}

resource "aws_iam_instance_profile" "ci" {
  name = "mp-ci-server"
  role = aws_iam_role.ci.name
}

# ── 볼륨 3장 — 🔴 온프렘 호스트 C 에서 아프게 배운 것을 코드로 옮긴다 ─────────
# 정본(CLAUDE.md §인프라)이 호스트 C 에 대해 이렇게 적고 있다:
#   *"단일 98GB 파일시스템에 OS·Harbor 이미지 블롭·JENKINS_HOME·SonarQube 데이터가 전부
#     얹혀 있다. 무언가 디스크를 채우면 Harbor 가 죽고 클러스터 배포가 전면 실패한다.
#     호스트 C 에 뭘 얹을지 판단할 때 RAM 이 아니라 디스크가 제약이다."*
#
# 🔴 **가르는 기준은 "용량"이 아니라 ① 어떻게 늘어나나 ② 잃어도 되나 다.**
#
#   /dev/sda  root    OS · Omnibus 패키지        경계 있음      🟢 재생성 가능
#   /dev/sdb  docker  /var/lib/docker            🔴 상한 없음   🟢 **버려도 된다**(prune)
#   /dev/sdc  data    /var/opt/gitlab · Sonar DB 꾸준히 늘어남  🔴 **소실 = 복구 불가**
#
# 이 셋을 가르면 두 가지가 성립한다:
#   ① **폭주가 다른 것을 죽이지 않는다** — docker 가 자기 볼륨을 꽉 채워도 GitLab 은 돌고,
#      루트가 살아 있으니 **Session Manager 로 들어가서 지울 수 있다.**
#      🔴 단일 볼륨이면 그 복구 경로까지 같이 막힌다 — 호스트 C 가 정확히 그 상태다.
#   ② **회수 정책이 갈린다** — 스냅샷은 `data` 만 뜬다. 캐시와 섞으면 *버려도 되는 60GB 를
#      매번 백업*하게 되고, 반대로 `docker system prune` 을 겁내게 된다.
#
# ⚠️ **LVM 을 쓰지 않는다** — 온프렘은 OpenEBS LVM 이 필요했지만 **gp3 는 볼륨 단위로 무중단
#    확장**되므로(`allowVolumeExpansion` 과 같은 성질) 논리볼륨 계층을 얹을 이유가 없다.
# 🟢 `/dev/sdb` = docker 는 온프렘 Ansible `base` 롤의 `docker_data_disk` 관례와 같은 이름이다.
#    🔴 단 그 롤을 그대로 쓰지 않는다 — C-77(AWS IaC 전량 신규)에 따라 `gitlab.yml` 이 별도다.

# ① docker — 🔴 **`prevent_destroy` 를 일부러 걸지 않는다.** 이 볼륨은 버릴 수 있어야 하고,
#    "버려도 된다"를 코드로 말하는 방법이 이 부재다. 잃으면 다음 빌드가 조금 느릴 뿐이다.
resource "aws_ebs_volume" "ci_docker" {
  availability_zone = var.azs[0]
  size              = var.ci_docker_volume_size
  type              = "gp3"
  encrypted         = true

  tags = {
    Name    = "mp-ebs-ci-docker"
    Reclaim = "disposable" # 스냅샷 대상 아님
  }
}

resource "aws_volume_attachment" "ci_docker" {
  device_name = "/dev/sdb"
  volume_id   = aws_ebs_volume.ci_docker.id
  instance_id = aws_instance.ci.id
}

# ② data — git 저장소·artifact·SonarQube DB·스왑(C-38).
# 🔴 실수로 다시 만들면 **소스 저장소와 품질 이력이 사라진다.**
#    0-8b(온프렘 PV 전량 Retain)와 같은 취지의 최소 방어선이다.
#    ⚠️ 이것은 백업이 아니다 — 백업은 `gitlab-ctl backup`(A-28)이 따로 진다.
resource "aws_ebs_volume" "ci_data" {
  availability_zone = var.azs[0]
  size              = var.ci_data_volume_size
  type              = "gp3"
  encrypted         = true

  tags = {
    Name    = "mp-ebs-ci-data"
    Reclaim = "retain" # 스냅샷·백업 대상
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_volume_attachment" "ci_data" {
  device_name = "/dev/sdc"
  volume_id   = aws_ebs_volume.ci_data.id
  instance_id = aws_instance.ci.id
}

# ── EC2 ───────────────────────────────────────────────────────────────────────
resource "aws_instance" "ci" {
  ami                    = data.aws_ssm_parameter.ubuntu_arm64.value
  instance_type          = var.ci_instance_type
  subnet_id              = aws_subnet.ci_public.id
  vpc_security_group_ids = [aws_security_group.ci.id]
  iam_instance_profile   = aws_iam_instance_profile.ci.name

  # 🔴 **`key_name` 을 지정하지 않는다 — C-37.** 키페어가 없으므로 접근은 Session Manager
  #    단독이고, 그래서 `AmazonSSMManagedInstanceCore` 부착이 *편의*가 아니라 *생명선*이다.

  # 🔴 `user_data` 를 쓰지 않는다 — C-61⑥ 의 근거가 이것이다: *"`user_data` 는 재실행
  #    불가라 `gitlab-ctl reconfigure` 를 요구하는 Omnibus(C-59)와 어긋난다."*
  #    ⇒ 형상은 전부 Ansible(`gitlab.yml`)이 만든다. Ubuntu 24.04 AMI 는 SSM 에이전트를
  #      스냅으로 미리 담고 있어 부팅만으로 Session Manager 에 등록된다.

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 강제 (A-28·A-30)

    # 🔴🔴 **정본과 어긋나는 값이다 — A-28 은 `hop limit 1` 을 요구한다.**
    #    그런데 C-61① 이 러너를 **privileged DinD** 로 정했다. 그러면 빌드 잡이
    #    **컨테이너 안에서** 돌고, 그 컨테이너가 `aws ecr get-login-password` 를 부른다.
    #    컨테이너는 IMDS 에서 **한 홉 더 멀다** ⇒ hop limit 1 이면 자격증명을 못 받고
    #    **ECR push 가 전량 실패한다**(= A0.5 완료 판정 자체가 불가).
    #    ⇒ 2 로 두되 **왜 상쇄되는지**를 남긴다: SG 인바운드 0개(A-34①) · 러너가 도는 코드는
    #      우리 레포 단독(외부 MR 빌드 없음) · 이 롤의 권한이 `mealplanning/*` 로 좁다.
    #    🔴 **변수로 뺐다** — 사용자가 1 을 원하면 값 하나로 되돌아가고, 그때는 ECR 로그인을
    #      호스트에서 하고 토큰을 잡에 주입하는 별도 설계가 필요하다(A-29 범위).
    http_put_response_hop_limit = var.ci_imds_hop_limit
  }

  root_block_device {
    volume_size = var.ci_root_volume_size
    volume_type = "gp3"
    encrypted   = true
    tags        = { Name = "mp-ebs-ci-root" }
  }

  tags = { Name = "mp-ci-server" }

  # AMI 파라미터가 갱신될 때마다 인스턴스를 다시 만들지 않는다 — 🔴 재생성은 GitLab 을
  # 통째로 날리는 동작이다. 이미지 갱신은 **의도적으로** 할 일이고, 그때는 데이터 볼륨을
  # 떼어 새 인스턴스에 붙인다(그래서 볼륨을 가른 것이기도 하다).
  lifecycle {
    ignore_changes = [ami]
  }
}
