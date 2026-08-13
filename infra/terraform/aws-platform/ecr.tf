# ECR — A-46(`mealplanning/` 유지 · 사용자 확정) · A-2(lifecycle 을 클러스터 생성과 *동시에*)
#
# 🔴 **리포는 자동 생성되지 않는다.** 이름이 config 의 `newName` 과 한 글자라도 다르면
#    A2(앱 배포·검증) 단계의 **pull 실패로 가장 늦게** 드러난다. 목록의 출처와 18개의 근거는
#    locals.tf 주석에 있다(추측이 아니라 config 레포에서 뽑은 것).
#
# 🔴 `mealplanning/` 를 유지한 이유 = Harbor 경로와 **1:1** 이 되어 onprem↔eks 차이가
#    **레지스트리 호스트 하나**로 줄어든다(C-77·C-83 이 선호하는 형태).

resource "aws_ecr_repository" "app" {
  for_each = toset(local.ecr_repositories)

  name = each.value

  # 🔴 **MUTABLE 이다.** IMMUTABLE 이 더 안전해 보이지만 우리 태깅 정책(3태그)이
  #    `:latest` 를 **가변**으로 규정한다(CLAUDE.md · #97). IMMUTABLE 로 두면 `:latest`
  #    두 번째 push 가 실패해서 CI 가 죽는다. 불변 신원은 `:<sha>` 가 이미 담당한다.
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    # 🔴 CI 에 Trivy CRITICAL 차단 게이트가 이미 있다(중복). 그래도 켜는 이유 =
    #    Trivy 는 **빌드 시점**만 보고, 여기는 이미 푸시된 이미지에 **나중에 발견된** CVE 를 붙인다.
    #    (`A-10` = Inspector 채택 판정은 별건이다 — 그쪽은 유료다.)
    scan_on_push = true
  }

  encryption_configuration {
    # AES256 = ECR 관리 = **$0**. KMS 는 미결 ⑰ 와 같은 축이라 여기서 정하지 않는다.
    encryption_type = "AES256"
  }

  tags = { Name = replace(each.value, "/", "-") }
}

# A-2 — 🔴 "클러스터 생성과 *동시에*" 가 항목의 요구사항이다. 나중에 붙이면 그 사이에 쌓인
#   이미지가 전부 만료 대상이 되어 **롤백 대상 태그가 한꺼번에 사라질 수 있다.**
resource "aws_ecr_lifecycle_policy" "app" {
  for_each = aws_ecr_repository.app

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        # 🔴 멀티아치(`1-6`)에서 **무태그 이미지가 정상적으로 생긴다** — 매니페스트 리스트만
        #    태그되고 arm64/amd64 개별 이미지는 태그가 없다. 0 일로 두면 방금 푸시한
        #    이미지의 실물이 사라진다. 기본 14일.
        rulePriority = 1
        description  = "무태그 레이어 만료 (멀티아치 부산물)"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.ecr_untagged_expire_days
        }
        action = { type = "expire" }
      },
      {
        # `tagStatus: any` 규칙은 **반드시 마지막**이어야 한다(ECR 규칙 · 앞에 두면 나머지가 무의미).
        rulePriority = 2
        description  = "최근 ${var.ecr_keep_last_images}개만 보존 — 그 이전은 롤백 대상이 아니다"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.ecr_keep_last_images
        }
        action = { type = "expire" }
      },
    ]
  })
}
