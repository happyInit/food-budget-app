# 🔴 **이 스택은 인프라를 만들지 않는다. 받는다.**
#    VPC·서브넷·SG·ALB·IAM 롤은 전부 `../aws-platform` 과 인프라 담당 소관이고(C-1~C-89),
#    여기서 그것들을 «만들면» 두 스택이 같은 자원을 서로 자기 것이라고 주장하게 된다.
#    ⇒ 아래 값들은 **넘겨받는 입력**이다. 기본값이 없는 것은 «모르면 진행하면 안 되는» 값이다.

variable "region" {
  type    = string
  default = "ap-northeast-2"
}

variable "profile" {
  description = <<-EOT
    apply 용 AWS 프로필. 🔴 backend 프로필(`mp-backup`)과 **다르다** — 이쪽은 Lambda·SQS·S3·
    Scheduler 를 만든다. 권한요청서 A안 기준 = `lambda:*` + 범위 제한 `iam:PassRole` + `scheduler:*`.
  EOT
  type        = string
}

# ── 넘겨받는 인프라 (인프라 담당이 만든다) ───────────────────────────────────
variable "subnet_ids" {
  description = <<-EOT
    Lambda 를 붙일 서브넷. 🔴 **노드 서브넷(`mp-subnet-node-*`) × 2AZ 다.**
    데이터 서브넷은 *"밖으로 나가는 경로 없음"* 이 산출물이라(`aws-platform/vpc_service.tf`)
    거기 두면 Bedrock·Gemini·NAT 가 전부 막힌다. 근거 = `docs/serverless/06_…§3.3`.
  EOT
  type        = list(string)
}

variable "security_group_id" {
  description = <<-EOT
    Lambda ENI 에 붙일 SG. 🔴 이 SG **참조**로 PG·ES 쪽 인바운드를 여는 것이 배선의 전부다
    (`0.0.0.0/0` 로 열지 말 것 — 내부 NLB 여도 VPC 안의 아무나 붙는 것과는 다르다).
  EOT
  type        = string
}

variable "exec_role_arns" {
  description = <<-EOT
    함수 역할 ARN 맵 — 권한요청서 A안 = **인프라가 만들고 AI 는 PassRole 만** 받는다.
    필요한 키 **4개**:
      `batch`     PG · Bedrock · Secrets Manager                (배치 5종 + rank-serve)
      `api`       Valkey · SQS send · S3 put/head/presign        (접수 2종 + chat-api)
      `worker`    위 + Gemini(외부) · S3 get/delete · SQS receive (워커 2종)
      `scheduler` 🔴 **EventBridge Scheduler 가 맡는 역할**이다 — 함수 실행용이 아니라
                  «스케줄러가 함수를 부를 수 있게» 하는 것이라 성격이 다르다.
                  `enable_schedules = false` 면 안 쓰이지만, 맵에는 있어야 plan 이 돈다.
    🔵 함수마다가 아니라 **역할을 나눠 쓰는** 이유 = 권한 경계는 «무엇을 하는가» 로 갈리지
       «함수가 몇 개인가» 로 갈리지 않는다. 11개 역할은 검토도 회수도 어렵다.
  EOT
  type        = map(string)
}

# ── 데이터 티어 주소 (선행 = docs/serverless/06) ─────────────────────────────
variable "pg_host" {
  description = <<-EOT
    🔴 **내부 NLB 의 DNS 이름**이다. 노드 사설 IP 를 넣지 말 것 — Karpenter 가 노드를 수시로
    갈아서 그 값은 수명이 분 단위다(실측 2026-08-17). 근거·대안비교 = `docs/serverless/06_…`.
    비워 두면 PG 를 쓰는 함수 8종이 **생성되지 않는다**(반쯤 배포된 상태보다 낫다).
  EOT
  type        = string
  default     = ""
}

variable "es_host" {
  description = "ES 내부 NLB DNS. 비면 `chat-api` 가 생성되지 않는다(ES 를 쓰는 유일한 함수)."
  type        = string
  default     = ""
}

variable "valkey_host" {
  description = "ElastiCache for Valkey 기본 엔드포인트(C-14). 🟢 VPC 네이티브라 06 의 선행이 필요 없다."
  type        = string
  default     = ""
}

variable "pg_database" {
  type    = string
  default = "foodbudget"
}

variable "secret_names" {
  description = "Secrets Manager 시크릿 이름(쉼표). `common/secrets.py` 의 `MP_SECRET_NAMES` 로 들어간다."
  type        = string
  default     = "mp/prod/pipeline-secrets"
}

# ── 번들 ─────────────────────────────────────────────────────────────────────
variable "build_dir" {
  description = <<-EOT
    `serverless/build.sh` 가 만든 번들 디렉터리의 부모. 🔴 **apply 전에 빌드가 선행**이다 —
    이 스택은 의존성을 해석하지 않는다(락 파일이 그 일을 한다).
        for f in serverless/ai_*/; do serverless/build.sh "$(basename "$f")"; done
  EOT
  type        = string
  default     = "../../../.build"
}

variable "rank_serve_image_uri" {
  description = <<-EOT
    `mp-ai-rank-serve` 의 ECR 이미지 URI(`:sha` 로 핀). 🔴 이 함수만 zip 이 아니라 컨테이너다
    (`libgomp` 이 OS 패키지라 zip 에 못 들어간다 — `serverless/ai_rank_serve/Dockerfile`).
    비워 두면 **생성하지 않는다** — 이미지가 없는 채로 함수를 만들면 apply 가 죽는다.
  EOT
  type        = string
  default     = ""
}

# ── 🔴 위험한 스위치 두 개 — 기본값이 false 인 이유를 읽고 켤 것 ──────────────
variable "enable_schedules" {
  description = <<-EOT
    🔴 **기본 false.** 켜면 EventBridge Scheduler 가 배치 3종을 돌린다. 그런데 **같은 일을 하는
    K8s CronJob 이 EKS 에서 이미 돌고 있다**(`mp-score-review-sentiment` 0 7 · `mp-summarize-reviews`
    0 8 · `mp-poller-price-anomaly` 40 4). 둘 다 켜면 **하루에 두 번 돈다** — 리뷰 요약·감성은
    유료 모델 호출이라 곧 **비용이 두 배**고, 결과도 중복 갱신된다.
    ⇒ 켜기 **전에** 해당 CronJob 을 suspend 하는 것이 순서다. 그 전환은 이 스택 밖이다.
  EOT
  type        = bool
  default     = false
}

variable "alb_listener_arn" {
  description = "공개 ALB 의 HTTPS 리스너 ARN. `enable_alb_routes` 가 true 일 때만 쓴다."
  type        = string
  default     = ""
}

variable "enable_alb_routes" {
  description = <<-EOT
    🔴 **기본 false. 이걸 켜는 것이 곧 «트래픽 전환» 이다.**
    지금 `/api/pantry/ocr` · `/api/recipes/extract` · 챗 경로는 ALB 기본 타겟(Istio → 파드)이
    받는다. 여기에 리스너 규칙을 얹으면 **그 순간부터 파드가 아니라 Lambda 가 받는다.**
    apply 로 조용히 넘어갈 일이 아니라 **의도한 컷오버**여야 한다.
    ⚠️ 되돌리기는 규칙 삭제 한 번이지만, 그 사이 실패한 요청은 돌아오지 않는다.
  EOT
  type        = bool
  default     = false
}

variable "alb_rule_priority_base" {
  description = "리스너 규칙 우선순위 시작값. 기존 규칙과 겹치면 apply 가 죽는다 — 인프라 담당과 맞출 것."
  type        = number
  default     = 200
}

variable "upload_bucket_name" {
  description = "영수증 업로드 버킷. 🔴 개인정보라 수명주기 1일(아래 s3.tf)."
  type        = string
  default     = "mp-ai-uploads-ap2"
}

variable "log_retention_days" {
  description = "CloudWatch 로그 보존. 🔵 기본을 두는 이유 = 안 정하면 **무기한**이고 그게 조용히 쌓인다."
  type        = number
  default     = 14
}
