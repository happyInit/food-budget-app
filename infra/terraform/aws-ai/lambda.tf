# Lambda 함수 — zip 10종 + 컨테이너 1종.
#
# 🔴 **번들을 여기서 만들지 않는다.** `serverless/build.sh` 가 만든 것을 **묶기만** 한다:
#        for f in serverless/ai_*/; do serverless/build.sh "$(basename "$f")"; done
#    의존성 해석을 Terraform 에 맡기지 않는 이유 = 각 함수의 `requirements.txt` 가 **전이 의존까지
#    못 박은 락 파일**이고, 그렇게 해야 py3.12·aarch64 로 재현이 된다. 그 규율을 깨면
#    «빌드는 성공하는데 첫 호출에서 ModuleNotFoundError» 로 돌아간다(2026-08-14 실측).

data "archive_file" "bundle" {
  for_each = local.ready

  type        = "zip"
  source_dir  = "${var.build_dir}/${each.value.dir}"
  output_path = "${path.module}/.build/${each.key}.zip"
}

resource "aws_lambda_function" "fn" {
  for_each = local.ready

  function_name = "mp-ai-${each.key}"
  role          = local.role_arns[each.value.role]
  handler       = each.value.handler
  runtime       = "python3.12"

  # 🔴 **arm64 다**(C-29 Graviton). 번들의 휠도 `manylinux2014_aarch64` 로 받았다 —
  #    여기만 x86_64 로 두면 이미지는 만들어지고 **첫 호출에서** `invalid ELF header` 로 죽는다.
  architectures = ["arm64"]

  filename         = data.archive_file.bundle[each.key].output_path
  source_code_hash = data.archive_file.bundle[each.key].output_base64sha256

  timeout     = each.value.timeout
  memory_size = each.value.memory

  # 🔴 VPC 안에서만 돈다 — PG·ES·Valkey 가 전부 VPC 자원이다.
  #    ⚠️ 서브넷은 **노드 티어**여야 한다(데이터 서브넷은 아웃바운드 경로가 없다 — variables.tf).
  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [local.security_group_id]
  }

  environment {
    variables = merge(
      local.common_env,
      # 🔴 함수별 자격증명 배선(PGUSER·ES_USER·MP_SECRET_KEYS) — locals.tf 의 `cred_*`.
      #    **`common_env` 뒤에 와야 한다.** merge 는 뒤가 이기고, 여기가 더 구체적이다.
      lookup(each.value, "env", {}),
      # 잡 상태 키 네임스페이스. 🔴 안 주면 `common/jobs.py` 기본값이 `video` 라
      #    OCR 이 조용히 video 키에 쓴다 — 코드가 INIT 에서 터지게 해 뒀지만(설계상 의도),
      #    여기서 정확히 주는 것이 1차 방어다.
      contains(["ocr-api", "ocr-worker"], each.key) ? { JOB_NS = "ocr" } : {},
      contains(["video-api", "video-worker"], each.key) ? { JOB_NS = "video" } : {},
      # 접수는 자기 큐 URL 을 알아야 한다.
      each.key == "video-api" ? { VIDEO_JOBS_QUEUE_URL = aws_sqs_queue.jobs["video"].url } : {},
      each.key == "ocr-api" ? {
        OCR_JOBS_QUEUE_URL = aws_sqs_queue.jobs["ocr"].url
        OCR_UPLOAD_BUCKET  = aws_s3_bucket.uploads.bucket
      } : {},
      each.key == "ocr-worker" ? { OCR_UPLOAD_BUCKET = aws_s3_bucket.uploads.bucket } : {},
    )
  }

  # 🔵 로그 그룹을 명시적으로 만든다 — Lambda 가 자동 생성하게 두면 **보존이 무기한**이고
  #    그게 조용히 쌓인다. `depends_on` 으로 함수보다 먼저 서게 한다.
  depends_on = [aws_cloudwatch_log_group.fn]
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each = local.ready

  name              = "/aws/lambda/mp-ai-${each.key}"
  retention_in_days = var.log_retention_days
}

# ── SQS → 워커 ───────────────────────────────────────────────────────────────
resource "aws_lambda_event_source_mapping" "sqs" {
  # 🔴 `enable_sqs_triggers` 기본 false — 우리 권한으로 못 만든다(variables.tf 참조).
  for_each = var.enable_sqs_triggers ? local.sqs_functions : {}

  event_source_arn = aws_sqs_queue.jobs[each.value.queue].arn
  function_name    = aws_lambda_function.fn[each.key].arn

  # 🔴 **1 이다.** 한 번에 여러 건을 받으면, 한 건이 실패했을 때 배치 전체가 재전달되어
  #    이미 성공한 잡까지 다시 돈다(유료 모델 호출이 그만큼 늘어난다).
  #    워커 코드도 «배치 크기 1 이 계약» 을 전제로 쓰였다(`ai_*_worker` 주석).
  batch_size = 1
}

# 🔵 **컨테이너 함수는 없다.** `rank-serve` 는 이관하지 않기로 했다 — 동기·지연민감 경로인데
#    콜드스타트 하한이 1.05초이고, scale-to-zero·요청당 과금 같은 서버리스의 이득이
#    «상시 호출» 앞에서 전부 무의미하다. 근거 = `docs/serverless/09`.
#    ⇒ `libgomp` 을 위한 컨테이너 경로가 사라지고 **10종이 전부 zip** 이 된다.
