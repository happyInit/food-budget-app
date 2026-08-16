# PG 논리 덤프 버킷 + 백업 버킷 라이프사이클 — A4 안정화 (2026-08-14)
#
# ── 🔴 이 파일이 필요한 이유 = "정책은 다 정해졌는데 실물이 없다" ──────────────────
#   · `iam_irsa.tf` 의 A-47 롤 `mp-pg-dump` 는 `arn:aws:s3:::mp-pg-dump-ap2/aws/*` 에
#     PutObject 를 준다. **그 버킷이 존재하지 않는다**(실측 2026-08-14: NoSuchBucket).
#   · config `platform/pg/overlays/eks` 의 A-49 주석이 *"라이프사이클 쪽은 A4 에서 버킷과
#     함께 생긴다 — 지금은 버킷 자체가 없다"* 고 적어 뒀다. 여기가 그 A4 다.
#   · 그리고 라이브 S3 에 **라이프사이클 규칙이 걸린 버킷은 `mp-observability-eks` 하나뿐**이다
#     (실측: 백업 버킷 4개 전부 NoSuchLifecycleConfiguration). C-79 의 산출물이 *"보관정책이
#     무엇이고 언제 삭제되는지"* 라는 **스토리**인데, 지금은 그 스토리가 코드에 없다.

# ══ ① 논리 덤프 버킷 (C-69 · 2트랙 중 논리 쪽) ═══════════════════════════════════
#
# 🔴 **`mp-backup-ap2`(barman)와 분리하는 것이 C-69 의 요지다** — 한 버킷이 사람 실수로
#    지워질 때 두 트랙이 함께 죽으면 2트랙을 둔 의미가 없다. `iam_irsa.tf` 가 같은 이유로
#    이 롤에 barman 버킷을 주지 않는다.
# 🔵 이름은 `var.pg_dump_bucket` 이 정본이다(기본값 `mp-pg-dump-ap2`) — IRSA 정책이 같은
#    변수를 참조하므로 여기서 리터럴을 쓰면 둘이 갈릴 수 있다.
resource "aws_s3_bucket" "pg_dump" {
  bucket = var.pg_dump_bucket
  tags   = { Name = var.pg_dump_bucket }
}

resource "aws_s3_bucket_public_access_block" "pg_dump" {
  bucket                  = aws_s3_bucket.pg_dump.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-S3. 🔵 KMS 를 안 쓰는 이유는 `s3_observability.tf` 와 같다 — 덤프는 하루 1객체라
#    KMS 요청료가 문제는 아니지만, **복구 경로에 키 의존을 하나 더 얹지 않는다**는 쪽이 크다.
#    이 버킷은 barman 이 못 쓰는 상황(메이저 업그레이드·논리 손상)의 탈출구다(C-69 ②③).
resource "aws_s3_bucket_server_side_encryption_configuration" "pg_dump" {
  bucket = aws_s3_bucket.pg_dump.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# ── C-79 배치: Std → IA 30-90d → Glacier IR 90-180d → 만료 190일 ────────────────
#
# 🔴 **이 규칙이 유일한 삭제 주체다.** 미결 ㉕ 해소(2026-08-13)로 업로드 컨테이너의
#    `mc rm --older-than 7d` 를 eks 오버레이에서 걷었고(A-49 ②), A-47 IAM 롤에서
#    `s3:DeleteObject` 도 뺐다. 즉 **여기를 지우면 아무도 안 지운다.**
# 🔴 반대로 7일로 낮추면 **Standard-IA 최소 저장 30일에 도달조차 못 해** 계층 전환이
#    영원히 발동하지 않는다 — C-79 가 보존창을 먼저 늘리라고 한 이유가 이것이다.
# 🔵 정상상태 저장량 = 318 MiB × 190 ≈ 60.4 GiB (C-69 재산정) · 계층 반영 월 $1 내외 추정.
# 🔵 프리픽스로 나누지 않는다 — C-69 가 `aws/`·`onprem/` 두 사이트 프리픽스를 예고하지만
#    보존 정책은 같다. 온프렘이 이 버킷을 쓰기 시작해도(2-8) 규칙을 안 고쳐도 된다.
resource "aws_s3_bucket_lifecycle_configuration" "pg_dump" {
  bucket = aws_s3_bucket.pg_dump.id

  rule {
    id     = "c79-tier-and-expire"
    status = "Enabled"
    filter {}

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
    expiration { days = 190 }

    # 업로드가 중간에 죽으면 조각이 남아 조용히 과금된다. 덤프는 318 MiB 라 멀티파트가 실제로 쓰인다.
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

# ══ ② barman 버킷 라이프사이클 — 🔴 프리픽스를 반드시 건다 ═══════════════════════
#
# 🔴🔴 **`mp-backup-ap2` 에 무필터 만료를 걸면 안 된다.** 실측(2026-08-14) 최상위 프리픽스:
#        etcd/  jenkins/  pg/  pg-eks/  pg-final/  pg-premigration/  secrets/  **tfstate/**
#      `tfstate/` 는 **이 Terraform 스택 자신의 state** 이고, 이 버킷은 **버전관리가 꺼져 있다**
#      (`backend.tf` 주석: 권한 부족으로 못 켰다). 무필터 35일 = **35일 뒤 state 소멸**이다.
#      복구 수단이 없다.
#
# 🔴 **그래서 `pg-eks/` 하나만 건다.** 나머지는 의도적으로 손대지 않는다:
#      · `pg/`     = 온프렘 barman 목적지 (실측: 온프렘 ObjectStore dest=s3://mp-backup-ap2/pg)
#      · `etcd/` `secrets/` `jenkins/` = 온프렘 백업 트랙
#      ⇒ 전부 **C-83(온프렘 형상 동결)** 대상이다. AWS 작업은 덧셈만 한다.
#      ⚠️ C-79 는 버킷 단위로 *"만료 35일"* 이라고만 적었다 — 그 문장이 쓰인 맥락은
#        barman WAL·base 이고, 같은 버킷에 온프렘 트랙과 tfstate 가 동거한다는 사실은
#        반영돼 있지 않다. **프리픽스 축소는 C-79 의 축소가 아니라 그 전제의 복원이다.**
#
# 🔵 **이건 백스톱이지 보존 정책이 아니다** — 진짜 보존은 CNPG 가 한다(실측: EKS·온프렘 양쪽
#    ObjectStore `retentionPolicy: 30d`). barman 이 30일에 지우고 S3 가 35일에 받친다.
#    `s3_observability.tf` 의 30일 백스톱과 같은 논리다: 백스톱은 앱 보존보다 넉넉해야 한다.
#    ⚠️ 여기를 30일 미만으로 낮추면 barman 이 아직 참조 중인 WAL 을 S3 가 먼저 지워
#      **PITR 이 조용히 깨진다**(복구 시점에야 드러난다).
#
# 🔴 **계층 전환을 걸지 않는다** — C-79 가 이 버킷만 예외로 못박았다:
#      ⓐ WAL 은 16MB 객체가 수천 개라 **요청료가 저장료를 넘고**
#      ⓑ PITR 이 필요한 순간에 복구가 몇 시간 걸리면 그건 백업이 아니다.
#
# 🔴 **버킷당 라이프사이클 설정은 하나뿐이다.** 나중에 다른 프리픽스에 규칙을 더할 때는
#    새 리소스를 만들지 말고 **이 리소스에 `rule` 블록을 추가**해야 한다. 새로 만들면
#    둘이 서로를 덮어써 규칙이 조용히 사라진다.
# 🟢 버킷 자체는 이 스택이 만들지 않는다(`variables.tf` 의 `backup_bucket` 주석 — 라이브
#    데이터가 든 버킷을 편입하면 `destroy` 한 번이 백업을 통째로 지운다). 라이프사이클만
#    관리하므로 그 위험이 없다 — 이 리소스의 destroy 는 **규칙만** 걷는다.
resource "aws_s3_bucket_lifecycle_configuration" "backup_barman_eks" {
  bucket = var.backup_bucket

  rule {
    id     = "backstop-expire-barman-eks"
    status = "Enabled"

    filter {
      prefix = "pg-eks/"
    }

    expiration { days = 35 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

# ══════════════════════════════════════════════════════════════════════════════
# `mp-source-backup-ap2` 라이프사이클 — C-79 (2026-08-16 감사에서 **전무**로 발견)
# ══════════════════════════════════════════════════════════════════════════════
# 🔴 **버킷은 Terraform 이 만들지 않는다.** 온프렘 시절 만들어졌고 Ansible `source_backup`
#    롤이 쓴다. 그래서 `aws_s3_bucket` 을 선언하지 않고 **이름으로 라이프사이클만** 건다 —
#    import 없이 안전하고, 버킷 자체를 IaC 로 들이는 것은 별건이다(소유권 이전이라 파괴 위험).
#
# 🔴 **접두사가 둘이고 성격이 완전히 다르다** (C-68: 버킷 하나를 prefix 로 공유):
#      `source/`  월 1회 소스 미러 · 400일 — GitHub/GitLab 을 통째로 잃었을 때의 마지막 사본
#      `gitlab/`  GitLab 인스턴스 백업 · **14일** — 운영 백업이라 회전이 빠르다
#
# 🔴 **`gitlab/` 에는 계층 전환을 걸지 않는다** — 14일 만료인데 IA 최소 저장이 30일이라
#    전환하면 **조기삭제 수수료를 16일치 더 문다.** 계층은 `source/` 에만 의미가 있다.
#    ⇒ C-79 의 "Std 0-90 → IA 90-180 → Deep Archive 180+" 는 `source/` 전용으로 읽는다.
#
# 🔵 `source/` 는 월 1회 × ~92MB(실측 2026-08-01 분 91,878,437 B) 라 IA·Deep Archive 의
#    최소 과금 크기 128KB 를 여유 있게 넘는다. Deep Archive 는 최소 저장 **180일**이고
#    전환도 180일이라 만료(400일)까지 220일이 남아 조기삭제가 발생하지 않는다.
#
# ⚠️ **복구 시간을 알고 고른 것이다** — Deep Archive 는 표준 복구가 **최대 12시간**이다.
#    이 사본은 *"레포 호스팅을 통째로 잃었다"* 는 시나리오용이고 그때는 12시간을 기다릴 수 있다.
#    빠르게 필요한 것은 GitLab push mirror(온프렘 CD 생명줄)이지 이 tar 가 아니다.
resource "aws_s3_bucket_lifecycle_configuration" "source_backup" {
  bucket = "mp-source-backup-ap2"

  rule {
    id     = "source-tier-and-expire"
    status = "Enabled"
    filter { prefix = "source/" }
    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 180
      storage_class = "DEEP_ARCHIVE"
    }
    expiration { days = 400 }
  }

  rule {
    id     = "gitlab-expire"
    status = "Enabled"
    filter { prefix = "gitlab/" }
    expiration { days = 14 }
  }

  # 업로드가 중간에 죽으면 조각이 남아 조용히 과금된다(수명주기 없이는 영구히).
  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}
