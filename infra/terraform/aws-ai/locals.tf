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

# ── 자격증명 배선 — 🔴 함수마다 DB 롤이 다르다 ─────────────────────────────────
#
# 스키마-퍼-서비스라 파드가 각자 다른 `svc_*` 롤로 붙는다. Lambda 도 **그대로 따라간다** —
# 하나로 뭉뚱그리면 권한이 모자라거나(작업 실패) 반대로 필요 이상으로 넓어진다.
# 아래 값은 전부 **EKS 파드 실측**(2026-08-18)이고, 추측이 아니다:
#
#     배치 5종   ← pipeline CronJob   PGUSER=svc_pipeline · ES_USER=mp_pipeline_writer
#     chat-api   ← mp-chat            PGUSER=svc_chat     · ES_USER=mp_recipe_reader
#     ocr-worker ← mp-ocr             PGUSER=svc_ocr
#
# 🔴 비밀번호는 `mp-ai/runtime` 에서 온다 — `mp/prod/*` 가 아니다. 실행 역할의 경계가
#    `mp-ai/*` 만 허용하기 때문이고(`iam.tf` 머리말), 그건 의도된 설계다.
# 🔴 그리고 **`MP_SECRET_KEYS` 가 없으면 `inject()` 가 아무것도 안 한다** —
#    `common/secrets.py`: *"둘 중 하나라도 비어 있으면 아무것도 하지 않는다"*.
#    종전엔 `MP_SECRET_NAMES` 만 있고 이게 없었다. 그러면 PGPASSWORD 가 안 채워진 채
#    함수가 뜨고, 실패는 **PG 인증 단계**에서야 나타나 원인이 안 드러난다.
locals {
  cred_batch = {
    PGUSER         = "svc_pipeline"
    ES_USER        = "mp_pipeline_writer"
    MP_SECRET_KEYS = "PGPASSWORD=PGPASSWORD_PIPELINE,ES_PASSWORD=ES_PASSWORD_PIPELINE"
  }
  cred_chat = {
    PGUSER         = "svc_chat"
    ES_USER        = "mp_recipe_reader"
    MP_SECRET_KEYS = "PGPASSWORD=PGPASSWORD_CHAT,ES_PASSWORD=ES_PASSWORD_RECIPE_READER,GEMINI_API_KEY=CHAT_GEMINI_API_KEY"
  }
  cred_ocr_worker = {
    PGUSER         = "svc_ocr"
    MP_SECRET_KEYS = "PGPASSWORD=PGPASSWORD_OCR,GEMINI_API_KEY=GEMINI_API_KEY"
  }
  # 🔵 접수 2종은 Valkey 만 쓴다 — 비밀이 필요 없다. 빈 채로 두면 `inject()` 가 조용히 건너뛴다.
  cred_none = {}
}

locals {
  functions = {
    # ── 배치 (수동 Invoke) ───────────────────────────────────────────────────
    "shelflife-draft" = {
      dir     = "ai_shelflife_draft", handler = "app.handler", role = "batch"
      timeout = 900, memory = 512, needs = ["pg"], trigger = "manual"
      env     = local.cred_batch
    }
    "ner-backfill" = {
      dir     = "ai_ner_backfill", handler = "app.handler", role = "batch"
      timeout = 900, memory = 1024, needs = ["pg"], trigger = "manual"
      env     = local.cred_batch
    }
    # ── 배치 (Scheduler) ─────────────────────────────────────────────────────
    # 🔴 cron 은 **EKS CronJob 과 같은 시각**이다(중복 실행 위험 — variables.tf `enable_schedules`).
    "price-detect" = {
      dir     = "ai_price_detect", handler = "app.handler", role = "batch"
      timeout = 900, memory = 1024, needs = ["pg"], trigger = "schedule"
      cron    = "cron(40 4 * * ? *)" # ← mp-poller-price-anomaly
      env     = local.cred_batch
    }
    "sentiment-batch" = {
      dir     = "ai_sentiment_batch", handler = "app.handler", role = "batch"
      timeout = 900, memory = 512, needs = ["pg"], trigger = "schedule"
      cron    = "cron(0 7 * * ? *)" # ← mp-score-review-sentiment
      env     = local.cred_batch
    }
    "summarize-batch" = {
      dir     = "ai_summarize_batch", handler = "app.handler", role = "batch"
      timeout = 900, memory = 512, needs = ["pg"], trigger = "schedule"
      cron    = "cron(0 8 * * ? *)" # ← mp-summarize-reviews
      env     = local.cred_batch
    }
    # ── 접수 (ALB) ───────────────────────────────────────────────────────────
    # 🔵 접수는 **모델을 안 부른다** — 받아서 큐에 넣고 202 를 준다. 그래서 타임아웃이 10초다.
    "video-api" = {
      dir     = "ai_video_api", handler = "app.handler", role = "api"
      timeout = 10, memory = 256, needs = ["valkey"], trigger = "alb"
      path    = "/api/recipes/extract*"
      env     = local.cred_none
    }
    "ocr-api" = {
      dir     = "ai_ocr_api", handler = "app.handler", role = "api"
      timeout = 10, memory = 512, needs = ["valkey"], trigger = "alb"
      path    = "/api/pantry/ocr*"
      env     = local.cred_none
    }
    # ── 워커 (SQS) ───────────────────────────────────────────────────────────
    # 🔴 **워커 타임아웃 < 락 TTL(180s).** 넘기면 "락은 풀렸는데 워커는 아직 도는" 구간이 생겨
    #    같은 영상이 두 번 분석된다(비용 2배) — `docs/serverless/01_…§3①`.
    "video-worker" = {
      dir     = "ai_video_worker", handler = "app.handler", role = "worker"
      timeout = 150, memory = 1024, needs = ["valkey"], trigger = "sqs"
      queue   = "video"
      # 🔴 이 함수는 Gemini 를 **실제로 부른다**(영상 → 레시피 추출). 키가 없으면
      #    접수는 202 로 통과하는데 처리만 조용히 실패한다 — 그 조합이 제일 안 보인다.
      env = { MP_SECRET_KEYS = "VIDEO_GEMINI_API_KEY=GEMINI_API_KEY" }
    }
    # 🔴 **워커 타임아웃 > `OCR_TIMEOUT_S`(기본 90s).** 반대면 Lambda 가 먼저 잘려서
    #    "마지막 시도에 FAILED 를 남긴다" 가 실행되지 않고, 잡이 PENDING 에 영영 남는다.
    "ocr-worker" = {
      dir     = "ai_ocr_worker", handler = "handler.handler", role = "worker"
      timeout = 120, memory = 1024, needs = ["pg", "valkey"], trigger = "sqs"
      queue   = "ocr"
      env     = local.cred_ocr_worker
    }
    # ── 서비스 (ALB) ─────────────────────────────────────────────────────────
    "chat-api" = {
      dir     = "ai_chat_api", handler = "handler.handler", role = "api"
      timeout = 30, memory = 1024, needs = ["pg", "es", "valkey"], trigger = "alb"
      path    = "/api/mealplan/assistant/chat"
      env     = local.cred_chat
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
    # 🔴 포트를 박아 두면 안 된다 — C-85 는 **NodePort**(30094·30095)라 5432·9200 이 아니다.
    #    박아 뒀던 값이 그대로 나갔으면 함수 8종이 전부 «연결 안 됨» 으로 죽었을 것이고,
    #    증상이 «SG 인가 netpol 인가 자격증명인가» 로 보여 원인이 안 드러났을 자리다.
    PGPORT     = var.pg_port
    PGDATABASE = var.pg_database
    ESHOST     = var.es_host
    ESPORT     = var.es_port
    REDISHOST  = var.valkey_host
    REDISPORT  = "6379"
  }

  # 🔴 `create_security_group = false` 인데 ID 도 없으면 함수가 SG 없이 뜨려다 죽는다.
  #    이 검사는 `count` 와 무관한 자리라 **항상 평가된다**(위 변수 주석의 실패 사례 참조).
  _sg_check = (var.create_security_group || var.security_group_id != "") ? true : tobool(
  "create_security_group = false 면 security_group_id 를 반드시 줘야 한다")

  queue_names = ["video", "ocr"]

  # 넘겨받은 것이 있으면 그것, 없으면 우리가 만든 것.
  security_group_id = var.create_security_group ? aws_security_group.lambda[0].id : var.security_group_id
}
