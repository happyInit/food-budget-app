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
    Lambda ENI 에 붙일 SG. 🟢 **비워 두면 이 스택이 만든다**(`security_group.tf` · `mp-ai-lambda`).
    정책이 `Project=mp-ai` 태그가 붙은 SG 는 우리 소유로 열어 뒀다(태그 없이 만드는 것은 거부).
    🔴 노드 SG 를 여기 넣지 말 것 — 그러면 우리 함수가 **노드의 규칙 전부**를 물려받고,
       나중에 그 SG 를 손볼 때 "여기 Lambda 도 붙어 있었나" 를 아무도 기억하지 못한다.
    🔴 이 SG **참조**로 PG·ES 쪽 인바운드를 여는 것이 남은 배선인데, 받는 쪽이 노드 SG 라
       그건 관리자 몫이다(`docs/mp_aws_team_access.md §4` "구조상 관리자에게 남는 것 ①").
  EOT
  type        = string
  default     = ""
}

variable "vpc_id" {
  description = "SG 를 만들 VPC(`mp-vpc-service`). `security_group_id` 를 직접 줄 때는 안 쓴다."
  type        = string
  default     = ""
}

variable "exec_role_arns" {
  description = <<-EOT
    함수 역할 ARN 맵 — 권한요청서 A안 = **인프라가 만들고 AI 는 PassRole 만** 받는다.
    필요한 키 **4개**:
      `batch`     PG · Bedrock · Secrets Manager                (배치 5종)
      `api`       Valkey · SQS send · S3 put/head/presign        (접수 2종 + chat-api)
      `worker`    위 + Gemini(외부) · S3 get/delete · SQS receive (워커 2종)
      `scheduler` 🔴 **EventBridge Scheduler 가 맡는 역할**이다 — 함수 실행용이 아니라
                  «스케줄러가 함수를 부를 수 있게» 하는 것이라 성격이 다르다.
                  `enable_schedules = false` 면 안 쓰이지만, 맵에는 있어야 plan 이 돈다.
    🔵 함수마다가 아니라 **역할을 나눠 쓰는** 이유 = 권한 경계는 «무엇을 하는가» 로 갈리지
       «함수가 몇 개인가» 로 갈리지 않는다. 11개 역할은 검토도 회수도 어렵다.

    🟢 **비워 두면 이 스택이 직접 만든다**(`iam.tf`). 권한요청서는 A안(인프라가 만든다)을
       전제했지만 실측해 보니 그럴 필요가 없었다 — `iam:CreateRole` 이 **경계 조건부로 이미
       허용**돼 있고, 경계에 `ec2:CreateNetworkInterface` 가 들어 있어 **VPC Lambda 를
       전제한 설계**다. 넘겨받고 싶으면 여기 4개(batch·api·worker·scheduler)를 채우면 된다.
  EOT
  type        = map(string)
  default     = {}
}

variable "boundary_policy_name" {
  description = <<-EOT
    실행 역할에 붙일 PermissionsBoundary 정책 이름. 🔴 **이게 안 붙으면 `iam:CreateRole`
    자체가 거부된다** — 없으면 «관리자 권한 역할을 만들어 Lambda 에 넘기는» 권한 상승이 되기 때문.
    정책 원문 = `infra/iam/mp-ai/mp-ai-boundary.json`.
  EOT
  type        = string
  default     = "mp-ai-boundary"
}

variable "enable_sqs_triggers" {
  description = <<-EOT
    🔴 **기본 false — 우리 권한으로 못 만들기 때문이다**(2026-08-17 실측).
    `lambda:CreateEventSourceMapping` 이 `implicitDeny` 다. 정책이 이 액션을 «함수 ARN 에
    리소스 수준으로» 허용했는데, 이 액션은 그 형태를 지원하지 않아 매칭되지 않는다
    (`Resource: *` + `lambda:FunctionArn` 조건이어야 한다).
    ⇒ 관리자가 `infra/iam/mp-ai/mp-ai-dev.json` 에 문장 하나를 더하면 풀린다.
    🔵 그 전까지 워커는 **함수는 만들어지되 아무도 안 깨운다** — 반쯤 배포보다 낫다:
       큐에 쌓이기만 하고 유실은 없다(보존 4일).
  EOT
  type        = bool
  default     = false
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

variable "alb_path_prefix" {
  description = <<-EOT
    ALB 경로 앞에 붙이는 접두사. 🔵 기본 `/ai` — 파드가 받는 경로를 **빼앗지 않고 옆에** 세운다.
    예: `/ai/api/pantry/ocr*`. 정본 = `docs/mp_aws_team_access.md §4`
    (*"EKS 앱 13종을 서버리스로 옮기는 것이 아니라 옆에 독립적으로 세우는 프로젝트"*).

    🔴 `""` 로 비우면 **파드의 경로를 그대로 가져간다 = 컷오버**다. 그날의 결정으로만 비울 것.
    ⚠️ 접두사를 쓰면 프론트가 그 경로를 명시적으로 불러야 한다 — 그게 «둘이 동시에 산다» 의 대가다.
  EOT
  type        = string
  default     = "/ai"
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
