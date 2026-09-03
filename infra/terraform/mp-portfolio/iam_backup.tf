# 시드 내려받기 + 백업 올리기용 IAM 사용자.
#
# 🔴 Lightsail 에는 인스턴스 프로파일(역할)이 없다. EC2 였다면 키 없이 역할로 끝날 일인데
#    여기서는 액세스 키를 호스트에 둬야 한다 — Lightsail 을 고른 대가다.
#    그래서 권한을 이 버킷의 두 프리픽스로만 좁힌다.
#
# 🔴 액세스 키는 Terraform 이 만들지 않는다. tfstate 는 평문이라 키가 state 에 남는다
#    (이 레포의 기존 관행과 같다 — 비밀은 terraform 밖에서 만든다).
#    apply 후 손으로:
#      aws iam create-access-key --user-name mp-portfolio-backup --profile <프로필>
#    결과를 deploy/portfolio/.env 의 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 에 넣는다.

resource "aws_iam_user" "backup" {
  name = "mp-portfolio-backup"
  tags = { Purpose = "portfolio host seed download + backup upload" }
}

resource "aws_iam_user_policy" "backup" {
  name = "mp-portfolio-s3"
  user = aws_iam_user.backup.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadSeed"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::${var.seed_bucket}/portfolio-seed/*"
      },
      {
        Sid      = "WriteBackups"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "arn:aws:s3:::${var.seed_bucket}/portfolio-backup/*"
      },
      {
        Sid      = "ListScoped"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = "arn:aws:s3:::${var.seed_bucket}"
        Condition = {
          StringLike = {
            "s3:prefix" = ["portfolio-seed/*", "portfolio-backup/*"]
          }
        }
      }
    ]
  })
}
