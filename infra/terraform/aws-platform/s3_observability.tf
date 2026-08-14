# 관측 오브젝트 스토어 — Loki(로그) · Tempo(트레이스) 공용 (A2, 2026-08-14)
#
# 🔴 **왜 이 파일이 필요한가** — config 레포는 EKS 형상을 이미 다 적어 뒀는데
#    (`platform/argocd/overlays/eks/kustomization.yaml` 이 버킷 이름·S3 엔드포인트·IRSA
#    `role-arn` 까지 지정한다) **AWS 쪽 실물이 통째로 없었다.** 실측(2026-08-14):
#      · S3 버킷 목록에 `mp-observability-eks` 없음
#      · IAM 롤 목록에 `mp-loki-s3` · `mp-tempo-s3` 없음
#      · Terraform 전체에서 loki·tempo·observability 언급 **0건**
#    증상은 tempo 가 CrashLoopBackOff 로 그대로 말해 준다:
#      failed to create store: unexpected error from ListObjects on mp-observability-eks:
#      The specified bucket does not exist
#
# 🔴 **버킷 이름은 config 가 정한 값을 따른다** — `mp-observability-eks`. 여기서 `${var.region_short}`
#    를 붙여 다른 이름을 만들면 config 세 곳(loki chunks·ruler·admin + tempo)을 같이 고쳐야 하고,
#    한쪽만 고치면 **"버킷은 있는데 앱은 없다고 한다"** 가 된다. 이름의 정본은 config 다.

resource "aws_s3_bucket" "observability" {
  bucket = "mp-observability-eks"
  tags   = { Name = "mp-observability-eks" }
}

resource "aws_s3_bucket_public_access_block" "observability" {
  bucket                  = aws_s3_bucket.observability.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-S3. 🔵 KMS 를 안 쓰는 이유는 C-67 의 CloudTrail 판단과 같은 계열이 아니다 —
#    여기는 단순히 **로그·트레이스라 키 분리의 이득이 작고**, KMS 요청 요금이 객체 수에 비례해
#    붙는다(Loki 는 청크를 잘게 쓴다). 필요해지면 나중에 SSE-KMS 로 올릴 수 있다(가역).
resource "aws_s3_bucket_server_side_encryption_configuration" "observability" {
  bucket = aws_s3_bucket.observability.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# 🔴 **이건 백스톱이지 보존 정책이 아니다.** 진짜 보존은 앱이 한다 — config 실측:
#      loki  `limits_config.retention_period: 168h` + `compactor.retention_enabled: true`
#      tempo `retention: 168h` (→ compactor.compaction.block_retention)
#    즉 정상 동작 중이면 7일치만 남는다. 30일은 **compactor 가 놓친 고아 객체**만 걷는 값이라
#    앱 보존 정책과 경쟁하지 않는다(7일 ≪ 30일).
# ⚠️ 여기 값을 7일로 낮추면 compactor 가 아직 참조 중인 객체를 S3 가 먼저 지워
#    **조회가 조용히 비는** 상황이 생길 수 있다. 백스톱은 앱 보존보다 넉넉해야 한다.
resource "aws_s3_bucket_lifecycle_configuration" "observability" {
  bucket = aws_s3_bucket.observability.id
  rule {
    id     = "backstop-expire-orphans"
    status = "Enabled"
    filter {}
    expiration { days = 30 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

# ── IRSA 정책 — Loki · Tempo ──────────────────────────────────────────────────
#
# 🔴 **프리픽스 조건(`s3:prefix`)을 걸지 않는다.** 두 가지 이유:
#    ① config 가 두 앱에 **프리픽스를 지정하지 않는다** — loki 는 chunks·ruler·admin 을 전부
#      같은 버킷 이름으로 받고 tempo 도 마찬가지다. 우리가 통제하지 않는 경로에 조건을 걸면
#      앱 업그레이드가 경로를 바꾸는 날 조용히 깨진다.
#    ② `#49` 에서 실제로 데인 함정이다 — barman 에 `StringLike {s3:prefix}` 를 걸었더니
#      **프리픽스 인자가 없는 `HeadBucket` 이 403** 이 났다(`StringLikeIfExists` 로 해소).
#      같은 형태의 사고를 반복하지 않는다.
#    ⇒ 대신 **버킷을 이 둘만 쓰도록 분리**하는 것으로 경계를 만든다(이 버킷에 다른 용도를 얹지 말 것).
data "aws_iam_policy_document" "observability_s3" {
  statement {
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.observability.arn]
  }

  statement {
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      # 🔵 멀티파트 = Loki 청크 플러시·Tempo 블록 업로드에 실제로 쓰인다.
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.observability.arn}/*"]
  }
}

resource "aws_iam_role" "loki_s3" {
  name               = "mp-loki-s3"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["loki_s3"].json
}

resource "aws_iam_role_policy" "loki_s3" {
  name   = "observability-s3"
  role   = aws_iam_role.loki_s3.id
  policy = data.aws_iam_policy_document.observability_s3.json
}

resource "aws_iam_role" "tempo_s3" {
  name               = "mp-tempo-s3"
  assume_role_policy = data.aws_iam_policy_document.irsa_trust["tempo_s3"].json
}

resource "aws_iam_role_policy" "tempo_s3" {
  name   = "observability-s3"
  role   = aws_iam_role.tempo_s3.id
  policy = data.aws_iam_policy_document.observability_s3.json
}
