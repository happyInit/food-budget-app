# `infra/terraform/aws-ai` — AI 서버리스 (Lambda 11종)

**이 스택은 인프라를 만들지 않는다. 받는다.**
VPC·서브넷·SG·ALB·IAM 롤은 전부 `../aws-platform` 과 인프라 담당 소관이고(C-1~C-89),
여기서 만들면 두 스택이 같은 자원을 서로 자기 것이라 주장하게 된다.

```
   ../             Proxmox VM            tfstate/proxmox.tfstate
   ../aws/         크롤 S3·SQS (C-44)    tfstate/aws-crawl.tfstate
   ../aws-platform VPC·EKS·ALB·IRSA      tfstate/aws-platform.tfstate
   여기            Lambda 11종           tfstate/aws-ai.tfstate      ← state 를 가르는 이유 =
                                                                       AI 배포가 플랫폼을 못 건드리게
```

## 만드는 것

| | 개수 | 비고 |
|---|---|---|
| Lambda 함수 | **11** | zip 10 + 컨테이너 1(`rank-serve`) · 전부 **arm64**(C-29) |
| CloudWatch 로그그룹 | 11 | 🔵 명시적으로 만든다 — 자동 생성이면 **보존이 무기한**이다 |
| SQS | 4 | `mp-ai-{video,ocr}-jobs` + DLQ |
| S3 | 1 | 영수증 업로드 · **수명주기 1일**(개인정보) |
| EventBridge Scheduler | 3 | ⏸ `enable_schedules` 기본 false |
| ALB 타겟그룹·규칙 | 각 3 | ⏸ `enable_alb_routes` 기본 false |

## 🔴 배선이 갖춰진 함수만 만든다

`pg_host`·`es_host`·`valkey_host` 로 «무엇에 닿을 수 있나» 를 주면, 그것만으로 도는 함수만
생성된다. 반쯤 배포해 두면 «있는데 안 되는» 상태가 되고 그게 제일 진단이 어렵다.

| 준 것 | 생기는 함수 | 자원 수 |
|---|---|---|
| `valkey_host` 만 | **3** — `video-api` · `video-worker` · `ocr-api` | 24 |
| `+ pg_host` | **+6** — 배치 5 + `ocr-worker` (+`rank-serve` 는 이미지 URI 필요) | |
| `+ es_host` | **+1** — `chat-api` | |
| 전부 + 스위치 2개 | **11** | 47 |

🔵 **`valkey_host` 는 지금 당장 줄 수 있다** — ElastiCache(`mp-cache`)는 이미 살아 있고
VPC 네이티브라 내부 NLB 선행이 필요 없다. ⇒ **권한만 오면 3종은 바로 올라간다.**
안 만들어진 함수와 그 이유는 `terraform output not_created` 로 드러난다.

## 🟢 권한 — 이미 있다 (2026-08-17 실측으로 확인)

권한요청서를 준비하면서 A안(*"인프라가 역할을 만들고 AI 는 PassRole 만"*)을 전제했는데,
`simulate-principal-policy` 로 재 보니 **`mp-ai` 권한 세트가 이미 라이브**였다(2026-08-14 ·
`docs/mp_aws_team_access.md §4`). 요청서가 필요 없다.

| 액션 | |
|---|---|
| `lambda:CreateFunction` · `UpdateFunctionCode` · `InvokeFunction` | ✅ |
| `sqs:*` · `s3:*` (`mp-ai-*`) · `scheduler:*` · `logs:*` | ✅ |
| `iam:CreateRole` (**`iam:PermissionsBoundary` 조건**) · `PutRolePolicy` · `PassRole`→lambda | ✅ |
| `ec2:CreateSecurityGroup` (**`aws:RequestTag/Project=mp-ai`**) · 그 SG 의 규칙 | ✅ |
| `ec2:DescribeSubnets` · `DescribeSecurityGroups` | ✅ |

🔵 경계에 **`ec2:CreateNetworkInterface`** 가 들어 있다 = **VPC Lambda 를 전제한 설계**다.
즉 역할·SG 를 우리가 만드는 것은 우회가 아니라 그 설계가 의도한 사용법이다.

### 🔴🔴 구멍 셋 — 하나는 **정책 결함**이다 (관리자 몫)

#### ① `ec2:CreateSecurityGroup` — 「태그 없는 것 금지」가 실제로는 「전부 금지」다

`mp-ai-guardrails` 의 이 문장이 **의도대로 동작하지 않는다**(라이브 = 레포 JSON, 대조 확인):

```json
{ "Sid": "DenyCreatingUntaggedSecurityGroup", "Effect": "Deny",
  "Action": ["ec2:CreateSecurityGroup"], "Resource": "*",
  "Condition": { "StringNotEquals": { "aws:RequestTag/Project": "mp-ai" } } }
```

**왜** — `ec2:CreateSecurityGroup` 은 리소스를 **둘** 검사한다: 만들어질 `security-group` 과
**대상 `vpc`**. `aws:RequestTag/*` 는 `TagSpecifications` 로 **생성되는 리소스에만** 붙는 키라
**VPC 쪽 평가에서는 키가 없다.** `StringNotEquals` 는 키가 없으면 **참** → Deny 가 성립한다.

**증거** — 실제 API 에러가 **VPC 를 리소스로 지목**한다:
```
not authorized to perform: ec2:CreateSecurityGroup
  on resource: arn:aws:ec2:…:vpc/vpc-0cbc077b708599115
  with an explicit deny in: mp-ai-guardrails
```
Terraform 도 CLI(`--tag-specifications` 로 태그를 정확히 실음)도 **똑같이** 거부됐다.

🔴 **`simulate-principal-policy` 로는 안 잡힌다** — 시뮬레이터는 내가 준 조건 키를 **모든
   리소스에** 적용해서 `allowed` 를 낸다. 시뮬레이션이 통과해도 **실제 호출은 죽는다.**
   ⇒ 권한 검증은 시뮬레이터로 «있다» 를 확인하고 **실호출로 «된다» 를 확인**해야 한다.

**고치는 법 (택1 · 관리자)**
```json
"Resource": "arn:aws:ec2:*:*:security-group/*"          ← 권장. 보호 대상을 명시한다
"Condition": {"StringNotEqualsIfExists": {"aws:RequestTag/Project": "mp-ai"}}
```
🔵 **의도는 그대로 지켜진다** — 태그 없는 SG 생성은 여전히 막힌다. VPC 쪽 오탐만 사라진다.

**막는 것** = Lambda 함수 전부. VPC 밖에서는 ElastiCache 에 못 닿는다.
**우회** = 관리자가 SG 를 하나 만들어 주면 `security_group_id` 로 받는다(코드 변경 0).

### 🔴 나머지 둘 (관리자 몫)

| | 왜 | 막는 것 |
|---|---|---|
| `elasticloadbalancing:Create*` | guardrails 가 **통째로 Deny**(이름과 무관) | 접수 3종의 **공개 HTTP 경로** |
| `lambda:CreateEventSourceMapping` | `implicitDeny` — 정책이 함수 ARN 에 리소스 수준으로 허용했는데 이 액션은 그 형태를 지원하지 않는다(`Resource: *` + `lambda:FunctionArn` 조건이어야) | **워커의 SQS 트리거** |

⇒ 둘 다 `enable_alb_routes` · `enable_sqs_triggers` 기본 false 로 **apply 에서 빠져 있다.**
지금 형상 그대로는 통과한다. `mp-ai-dev.json` 에 문장 하나면 후자는 풀린다.

## 🔴 state 버킷이 `mp-backup-ap2` 가 아니다

형제 스택은 전부 `mp-backup-ap2/tfstate/<스택>.tfstate` 를 쓰는데, **그 버킷은 guardrails 의
explicit deny 대상**이다(백업 버킷 보호). 로컬에 `mp-backup` 프로필도 없다.

```
explicit deny in identity-based policy: mp-ai-guardrails
```

⇒ **`mp-ai-tfstate-ap2`** 를 따로 두고 **key 규약은 그대로** 가져간다(`tfstate/aws-ai.tfstate`).
인프라 담당의 규약을 깨지 않으면서 우리 경계 안에 머무는 선택이다.
버전관리·SSE·퍼블릭 차단을 켜 뒀다(부트스트랩은 Terraform 밖 — 닭과 달걀).

## 쓰는 법

```bash
# 0. 번들 빌드가 선행이다 — 이 스택은 의존성을 해석하지 않는다(락 파일이 그 일을 한다)
for f in serverless/ai_*/; do serverless/build.sh "$(basename "$f")"; done

cd infra/terraform/aws-ai
cp backend.conf.example backend.conf        # backend.conf 는 .gitignore
terraform init -backend-config=backend.conf
terraform plan  -var-file=ai.tfvars
terraform apply -var-file=ai.tfvars
```

🔴 **`ai.tfvars` 는 커밋하지 않는다** — 서브넷·SG·역할 ARN 이 들어간다.

## 🔴 위험한 스위치 두 개

| | 켜면 | 켜기 전에 |
|---|---|---|
| `enable_schedules` | Scheduler 가 배치 3종을 돌린다 | **같은 K8s CronJob 을 suspend** — 안 하면 하루 두 번 돌고 유료 모델 비용이 두 배 |
| `enable_alb_routes` | 🔴 **그 순간부터 파드가 아니라 Lambda 가 받는다** | 이건 apply 가 아니라 **컷오버**다. 되돌리기는 규칙 삭제지만 그 사이 실패한 요청은 안 돌아온다 |

## 아직 정하지 못한 것

### `rank-serve` 의 진입점

이 함수를 부르는 것은 브라우저가 아니라 **`mealplan` 파드**다
(`RANKING_SERVING_URL` → `/rank/personalize`). 그래서 공개 ALB 에 붙이면 안 되고, 후보가 둘이다:

| 안 | 비용 | 코드 변경 |
|---|---|---|
| 내부 ALB | ≈ $16/월 | **0** — `RANKING_SERVING_URL` 환경변수만 바꾼다 |
| Function URL + SigV4 | $0 | `mealplan` 에 boto3 추가 + 서명 코드 |

⚠️ 그리고 **애초에 Lambda 가 맞는지부터 재검토 대상**이다. 동기·지연민감 경로인데
콜드스타트 하한이 **1.05초**다(로컬 x86·sklearn 만 실측 — arm64 + lightgbm 이면 더 크다).
추천 요청마다 타는 경로라 이 값이 그대로 사용자 체감이 된다.
⇒ 결정 전에는 **함수만 만들고 아무도 못 부르는 상태**로 둔다(트리거 없음).

## 검증 (2026-08-17)

```
terraform fmt -check   ✅
terraform validate     ✅
terraform plan         ✅  최소 배선 15개 · 전체 47개 (Lambda 11 · 스케줄 3 · ALB 규칙 3)
```

🔴 **`validate` 만으로는 부족했다** — `scheduler.tf` 가 **파일 통째로 없었는데** 그걸 참조하는
자원이 없어서 validate 가 통과했다. `plan` 의 자원 목록을 세고 나서야 드러났다.
⇒ 이 스택을 고칠 때는 **plan 까지 돌리고 자원 개수를 확인**할 것.

⚠️ plan 은 **원격 state 를 안 건드리는 사본**에서 돌렸다(`backend.tf` 제거). AWS 호출은
프로바이더 초기화용 읽기뿐이다.
