# 함수 카탈로그 — **`serverless/README.md` 의 표가 정본**이고 여기는 그것의 기계 표현이다.
# 둘이 어긋나면 README 가 이긴다.
#
# 🔴 `handler` 가 함수마다 다르다. 실수로 통일하면 죽는다:
#      평면 번들      → `app.handler`
#      패키지 번들    → `handler.handler`   (chat·ocr-worker — 번들 루트에 `app/` 패키지가 서서
#                                            `import app` 이 패키지를 집는다. 실측으로 확인함)
#
# 🔴 `needs` = 이 함수가 있어야 도는 배선. 하나라도 비면 **그 함수를 만들지 않는다**(§lambda.tf).
#    반쯤 배포해 두면 «있는데 안 되는» 상태가 되고, 그게 제일 진단이 어렵다.

locals {
  functions = {
    # ── 배치 (수동 Invoke) ───────────────────────────────────────────────────
    "shelflife-draft" = {
      dir     = "ai_shelflife_draft", handler = "app.handler", role = "batch"
      timeout = 900, memory = 512, needs = ["pg"], trigger = "manual"
    }
    "ner-backfill" = {
      dir     = "ai_ner_backfill", handler = "app.handler", role = "batch"
      timeout = 900, memory = 1024, needs = ["pg"], trigger = "manual"
    }
    # ── 배치 (Scheduler) ─────────────────────────────────────────────────────
    # 🔴 cron 은 **EKS CronJob 과 같은 시각**이다(중복 실행 위험 — variables.tf `enable_schedules`).
    "price-detect" = {
      dir     = "ai_price_detect", handler = "app.handler", role = "batch"
      timeout = 900, memory = 1024, needs = ["pg"], trigger = "schedule"
      cron    = "cron(40 4 * * ? *)" # ← mp-poller-price-anomaly
    }
    "sentiment-batch" = {
      dir     = "ai_sentiment_batch", handler = "app.handler", role = "batch"
      timeout = 900, memory = 512, needs = ["pg"], trigger = "schedule"
      cron    = "cron(0 7 * * ? *)" # ← mp-score-review-sentiment
    }
    "summarize-batch" = {
      dir     = "ai_summarize_batch", handler = "app.handler", role = "batch"
      timeout = 900, memory = 512, needs = ["pg"], trigger = "schedule"
      cron    = "cron(0 8 * * ? *)" # ← mp-summarize-reviews
    }
    # ── 접수 (ALB) ───────────────────────────────────────────────────────────
    # 🔵 접수는 **모델을 안 부른다** — 받아서 큐에 넣고 202 를 준다. 그래서 타임아웃이 10초다.
    "video-api" = {
      dir     = "ai_video_api", handler = "app.handler", role = "api"
      timeout = 10, memory = 256, needs = ["valkey"], trigger = "alb"
      path    = "/api/recipes/extract*"
    }
    "ocr-api" = {
      dir     = "ai_ocr_api", handler = "app.handler", role = "api"
      timeout = 10, memory = 512, needs = ["valkey"], trigger = "alb"
      path    = "/api/pantry/ocr*"
    }
    # ── 워커 (SQS) ───────────────────────────────────────────────────────────
    # 🔴 **워커 타임아웃 < 락 TTL(180s).** 넘기면 "락은 풀렸는데 워커는 아직 도는" 구간이 생겨
    #    같은 영상이 두 번 분석된다(비용 2배) — `docs/serverless/01_…§3①`.
    "video-worker" = {
      dir     = "ai_video_worker", handler = "app.handler", role = "worker"
      timeout = 150, memory = 1024, needs = ["valkey"], trigger = "sqs"
      queue   = "video"
    }
    # 🔴 **워커 타임아웃 > `OCR_TIMEOUT_S`(기본 90s).** 반대면 Lambda 가 먼저 잘려서
    #    "마지막 시도에 FAILED 를 남긴다" 가 실행되지 않고, 잡이 PENDING 에 영영 남는다.
    "ocr-worker" = {
      dir     = "ai_ocr_worker", handler = "handler.handler", role = "worker"
      timeout = 120, memory = 1024, needs = ["pg", "valkey"], trigger = "sqs"
      queue   = "ocr"
    }
    # ── 서비스 (ALB) ─────────────────────────────────────────────────────────
    "chat-api" = {
      dir     = "ai_chat_api", handler = "handler.handler", role = "api"
      timeout = 30, memory = 1024, needs = ["pg", "es", "valkey"], trigger = "alb"
      path    = "/api/mealplan/assistant/chat"
    }
  }

  # 배선이 갖춰진 것만 만든다. 🔵 `valkey` 만 있으면 되는 3종은 06(내부 NLB) 없이도 뜬다.
  have = {
    pg     = var.pg_host != ""
    es     = var.es_host != ""
    valkey = var.valkey_host != ""
  }
  ready = {
    for name, f in local.functions : name => f
    if alltrue([for n in f.needs : local.have[n]])
  }

  alb_functions = { for k, f in local.ready : k => f if f.trigger == "alb" }

  # 🔴 **경로를 빼앗지 않는다.** 정본이 «EKS 앱 13종을 서버리스로 옮기는 것이 아니라 옆에
  #    독립적으로 세우는 프로젝트»(`docs/mp_aws_team_access.md §4` · 사용자 확정 2026-08-14)
  #    라고 못박았는데, 카탈로그의 `path` 를 그대로 ALB 에 걸면 그건 «옆에» 가 아니라
  #    **컷오버**다 — `/api/pantry/ocr` 가 그 순간부터 파드 대신 Lambda 로 간다.
  #    ⇒ 접두사를 씌워 **둘이 동시에** 살게 한다. 파드는 그대로 자기 경로를 받는다.
  #
  # 🔵 접두사를 비우면(`""`) 종전처럼 «대체» 형태가 된다 — 컷오버를 실제로 하기로 정한
  #    날 한 글자만 바꾸면 되고, 그때까지는 이 값이 «아직 대체가 아니다» 를 코드로 말해 준다.
  alb_paths          = { for k, f in local.alb_functions : k => "${var.alb_path_prefix}${f.path}" }
  sqs_functions      = { for k, f in local.ready : k => f if f.trigger == "sqs" }
  schedule_functions = { for k, f in local.ready : k => f if f.trigger == "schedule" }

  # 모든 함수가 공유하는 환경변수. 🔵 «모르는 값은 코드에 박지 않는다» 의 반대편 —
  # 코드가 비워 둔 자리를 여기서 채운다(`serverless/README.md §원칙`).
  common_env = {
    LOG_LEVEL       = "INFO"
    MP_SECRET_NAMES = var.secret_names
    PGHOST          = var.pg_host
    PGPORT          = "5432"
    PGDATABASE      = var.pg_database
    ESHOST          = var.es_host
    ESPORT          = "9200"
    REDISHOST       = var.valkey_host
    REDISPORT       = "6379"
  }

  # 🔴 `create_security_group = false` 인데 ID 도 없으면 함수가 SG 없이 뜨려다 죽는다.
  #    이 검사는 `count` 와 무관한 자리라 **항상 평가된다**(위 변수 주석의 실패 사례 참조).
  _sg_check = (var.create_security_group || var.security_group_id != "") ? true : tobool(
  "create_security_group = false 면 security_group_id 를 반드시 줘야 한다")

  queue_names = ["video", "ocr"]

  # 넘겨받은 것이 있으면 그것, 없으면 우리가 만든 것.
  security_group_id = var.create_security_group ? aws_security_group.lambda[0].id : var.security_group_id
}
