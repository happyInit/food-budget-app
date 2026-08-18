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
    🔵 이 값만으로는 **아무것도 파괴되지 않는다** — 생성 여부는 `create_security_group` 이
       따로 정한다(아래). 값을 채우기만 하면 무시되고, 실제로 갈아타려면 그 불린을 함께
       내려야 한다. **파괴에 신호 두 개를 요구하는 것이 이 설계의 요점이다.**
    🔴 노드 SG 를 여기 넣지 말 것 — 그러면 우리 함수가 **노드의 규칙 전부**를 물려받고,
       나중에 그 SG 를 손볼 때 "여기 Lambda 도 붙어 있었나" 를 아무도 기억하지 못한다.
    🔴 이 SG **참조**로 PG·ES 쪽 인바운드를 여는 것이 남은 배선인데, 받는 쪽이 노드 SG 라
       그건 관리자 몫이다(`docs/mp_aws_team_access.md §4` "구조상 관리자에게 남는 것 ①").
  EOT
  type        = string
  default     = ""
}

variable "create_security_group" {
  description = <<-EOT
    🔴 **이 스택이 SG 를 만들고 소유할 것인가.** 기본 true.

    false 로 내리면 `aws_security_group.lambda` 의 `count` 가 0 이 되어 **이미 만든 SG 가
    파괴된다.** 그러면 인프라가 넣어 준 인그레스 규칙(ElastiCache 6379 · 노드 30094/30095)이
    **같이 죽고** Lambda 가 데이터 티어에서 통째로 끊긴다.

    🔴 **왜 변수를 둘로 갈랐나** — 원래는 `security_group_id` 하나가 «쓸 SG» 와 «만들지 여부» 를
    겸했다. 그래서 남의 SG ID 를 **적어 보기만 해도** 파괴가 계획됐다(2026-08-17 plan
    `1 to destroy` 로 실제로 나왔고, 15개 add 에 묻혀 하마터면 넘어갈 뻔했다).
    `precondition` 으로 막으려 했지만 **`count = 0` 이면 그 블록이 평가조차 안 된다** —
    막아야 하는 바로 그 상황에서 무력하다. `check` 도 원격 backend 에서는 조건을 못 만든다.
    ⇒ 경고로 때우지 않고 **구조를 바꿨다**: 파괴에는 **명시적 신호 두 개**가 필요하다.

    갈아타는 순서: ① `terraform state rm aws_security_group.lambda[0]`(관리에서만 뗀다)
                   ② `create_security_group = false` + `security_group_id = "sg-..."`
  EOT
  type        = bool
  default     = true
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

# ── 데이터 티어 주소 (C-85) ──────────────────────────────────────────────────
#
# 🔴 **NLB 가 아니다.** 종전 서술("내부 NLB 의 DNS 이름")은 폐기한다 — 내가 `docs/serverless/06`
#    에서 내부 NLB 를 권했다가 **두 번 철회**했고, 확정은 C-85 **"내부 접근 = 로드밸런서 0개"**
#    (NodePort + 노드 사설 IP)다. 그래서 주소는 DNS 가 아니라 **IP**이고 포트가 5432 가 아니다.
#
# 🔴 그리고 그 대가가 아래 `*_port` 를 변수로 뽑은 이유다 — 값이 **노드에 매인다.**
#    MNG 가 노드를 교체하면 IP 가 죽는다. 그 순간을 `serverless/alarms.sh` 의 ①(함수 오류)이
#    잡도록 짜 뒀다. 되돌리는 길은 C-85 가 명시한 대로 NLB 로 승격하는 것이고, 그때는
#    여기에 DNS 이름과 5432·9200 을 넣으면 그만이다 — **코드는 그대로 산다.**
variable "pg_host" {
  description = <<-EOT
    PG pooler 에 닿는 주소. C-85 = **노드 사설 IP**(예: 10.10.64.103).
    비워 두면 PG 를 쓰는 함수 8종이 **생성되지 않는다**(반쯤 배포된 상태보다 낫다).
  EOT
  type        = string
  default     = ""
}

variable "pg_port" {
  description = <<-EOT
    🔴 C-85 의 NodePort(**30094**). 5432 를 넣으면 **연결이 그냥 안 된다** — 노드에는 그 포트가
    열려 있지 않다. 짝 = config 레포 `platform/policies-data/overlays/eks/lambda-access.yaml`.
  EOT
  type        = string
  default     = "30094"
}

variable "es_host" {
  description = "ES 에 닿는 주소. C-85 = 노드 사설 IP. 비면 `chat-api` 가 생성되지 않는다(ES 를 쓰는 유일한 함수)."
  type        = string
  default     = ""
}

variable "es_port" {
  description = "🔴 C-85 의 NodePort(**30095**). 9200 이 아니다 — 위 `pg_port` 와 같은 이유."
  type        = string
  default     = "30095"
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
  description = <<-EOT
    Secrets Manager 시크릿 이름(쉼표). `common/secrets.py` 의 `MP_SECRET_NAMES` 로 들어간다.

    🔴 **`mp/prod/*` 를 넣으면 안 된다.** 종전 기본값이 `mp/prod/pipeline-secrets` 였는데
       실행 역할은 그걸 **못 읽는다** — 경계(`mp-ai-boundary` RuntimeOwnResources)가
       `secretsmanager:GetSecretValue` 를 `mp-ai/*` 로 제한한다. 의도된 설계다(`iam.tf` 머리말).
       그리고 그 시크릿은 실제로 **필드 2개가 다 비어 있었다**(2026-08-18 실측) — 넣었어도
       PGPASSWORD 는 안 나왔다.

    🔵 그래서 `mp-ai/runtime` 을 따로 만들었다. 내용 = `mp/prod/{pg-roles,data-secrets,
       app-secrets}` 에서 **필요한 7개만** 옮긴 것.
    ⚠️ 복사본이라 **원본을 회전하면 갈라진다.** 회전 후 재적재 = `serverless/scripts/make_mpai_secret.py`
       (멱등 — 있으면 값만 갱신한다).
  EOT
  type        = string
  default     = "mp-ai/runtime"
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
    ALB 리스너 규칙을 만들지 여부. 🔵 **기본 false 지만 «컷오버 스위치» 는 아니다.**

    ⚠️ **종전 서술은 폐기한다.** 여기엔 *"이걸 켜는 것이 곧 트래픽 전환이다 … 그 순간부터
    파드가 아니라 Lambda 가 받는다"* 라고 적혀 있었다. 그건 `alb_path_prefix` 가 생기기
    **전**에 쓴 문장이고 **지금은 사실이 아니다.**

    🔵 지금 만들어지는 규칙은 `/ai` 접두사가 붙은 경로다(`locals.alb_paths`).
       `/api/pantry/ocr` 는 **계속 파드로 간다.** 새 경로가 하나 더 생길 뿐이고,
       정본이 말하는 *"옆에 독립적으로 세우는"* 형태 그대로다(`mp_aws_team_access.md §4`).
       ⇒ 컷오버는 이 스위치가 아니라 **`alb_path_prefix` 를 비우는 것**이다.

    🔴 이 문구를 바로잡는 이유 = 권한을 검토하는 사람이 «컷오버구나» 로 읽으면
       요청이 거절된다. 실제 위험(우선순위를 기존 100번 **앞**에 둔다)은
       `alb_rule_priority_base` 쪽에 적어 뒀다 — **거기가 진짜 봐야 할 자리**다.

    기본 false 인 이유는 단순하다 — `elasticloadbalancing:*` 이 아직 명시 Deny 라
    켜면 `apply` 가 죽는다. 권한이 오면 true 로 바꾼다.
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
  description = <<-EOT
    리스너 규칙 우선순위 시작값.

    🔴 **작아야 한다. 200 이었는데 그건 «규칙이 절대 안 타는» 값이었다.**
    443 리스너의 실측(2026-08-18):

        100      host = aws.mealbong.cloud   → forward   ← **경로를 안 따진다**
        default                              → fixed-response

    ALB 는 우선순위 **오름차순으로 먼저 맞는 하나**만 적용한다. 100 번이 그 호스트의
    **모든 경로**를 잡으므로, 200 에 `/ai/*` 를 걸면 거기까지 내려오지 않는다.
    ⇒ 함수는 배포돼 있고 규칙도 있는데 **요청이 0건**인 상태가 된다. 그리고 그건
       "권한이 없어서 안 된다" 와 증상이 완전히 같아서, 원인이 안 드러난다.

    🔵 그래서 10 번대다 — 100 보다 **앞**에 서되, 매칭 조건이 `/ai` 접두사라
       그 밖의 트래픽은 종전대로 100 번으로 흘러간다. 파드 경로는 그대로다.
    ⚠️ 대역을 옮길 때는 인프라 담당과 맞출 것 — 겹치면 `apply` 가 죽는다(그건 안전한 실패다).
  EOT
  type        = number
  default     = 10
}

variable "alb_host_headers" {
  description = <<-EOT
    리스너 규칙에 함께 걸 호스트 목록. 기존 100번 규칙과 **같은 집합**이어야 한다.

    🔴 **둘이다.** 종전에 `string` 타입에 `aws.mealbong.cloud` 하나만 넣어 뒀는데 그건
       실측이 반쪽이었다 — `Conditions[0].Values[0]` 만 보고 첫 값만 읽었다.
       실제 100번 규칙(`e3f1036e76244344`):

           host-header = ["aws.mealbong.cloud", "app.mealbong.cloud"]

    🔴 하나만 걸면 **A3 컷오버 날 조용히 깨진다** — `app.mealbong.cloud/ai/*` 가 우리 규칙에
       안 걸리고 100번을 타고 파드로 가서 404 가 된다. 그때는 «어제까지 되던 게 안 된다» 로
       보이고 원인이 이 파일에 있다는 걸 아무도 떠올리지 않는다. (인프라 지적 2026-08-18)

    🔵 우리 규칙이 100번 **앞**에 서므로 경로만으로는 범위가 넓다 — 호스트로 한 겹 더 좁힌다.
    ⚠️ 빈 리스트면 호스트 조건이 빠진다(그 리스너에 오는 **모든** 호스트의 `/ai/*` 를 받는다).
  EOT
  type        = list(string)
  default     = ["aws.mealbong.cloud", "app.mealbong.cloud"]
}

variable "upload_bucket_name" {
  description = "영수증 업로드 버킷. 🔴 개인정보라 수명주기 1일(아래 s3.tf)."
  type        = string
  default     = "mp-ai-uploads-ap2"
}

variable "alert_emails" {
  description = <<-EOT
    알람을 받을 이메일. 🔴 **비우면 알람이 아무에게도 안 간다** — 토픽만 서고 조용하다.
    그건 오늘 하루 우리를 괴롭힌 «조용한 실패» 와 정확히 같은 모양이라, `outputs.tf` 가
    비어 있을 때 경고를 뱉는다.
    ⚠️ 이메일 구독은 **수신자가 확인 메일을 눌러야** 활성화된다(그전엔 PendingConfirmation).
    🔵 Slack 으로 보내려면 SNS → Lambda(`mp-security-notifier` 와 같은 형태)가 필요한데,
       그건 별건이다. 우선 사람에게 닿게 하는 것이 먼저다.
  EOT
  type        = list(string)
  default     = []
}

variable "log_retention_days" {
  description = "CloudWatch 로그 보존. 🔵 기본을 두는 이유 = 안 정하면 **무기한**이고 그게 조용히 쌓인다."
  type        = number
  default     = 14
}
