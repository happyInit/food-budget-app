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
| `valkey_host` 만 | **3** — `video-api` · `video-worker` · `ocr-api` | 15 |
| `+ pg_host` | **+6** — 배치 5 + `ocr-worker` (+`rank-serve` 는 이미지 URI 필요) | |
| `+ es_host` | **+1** — `chat-api` | |
| 전부 + 스위치 2개 | **11** | 47 |

🔵 **`valkey_host` 는 지금 당장 줄 수 있다** — ElastiCache(`mp-cache`)는 이미 살아 있고
VPC 네이티브라 내부 NLB 선행이 필요 없다. ⇒ **권한만 오면 3종은 바로 올라간다.**
안 만들어진 함수와 그 이유는 `terraform output not_created` 로 드러난다.

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
