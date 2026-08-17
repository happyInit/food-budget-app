# 영수증 업로드 버킷. 🔴 **개인정보다.**
#
# 흐름 = 브라우저 → (인라인 또는 presigned) → 이 버킷 → 워커가 읽고 **성공 즉시 삭제**.
# 그래도 실패 잔여물이 남으므로 수명주기로 한 번 더 받는다. 결정 근거 = `docs/serverless/07_…`.

resource "aws_s3_bucket" "uploads" {
  bucket = var.upload_bucket_name
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    id     = "expire-receipts"
    status = "Enabled"
    filter { prefix = "receipts/" }

    # 🔴 1일. 워커가 성공하면 즉시 지우므로 여기 남는 것은 **실패했거나 접수만 되고 버려진** 것들이다.
    #    보관할 이유가 없고, 영수증은 이름·품목·금액이 다 들어 있다.
    expiration { days = 1 }

    # 멀티파트 찌꺼기도 같이 — 안 지우면 «보이지 않는 채로» 과금된다.
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}
