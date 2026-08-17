# Operations AI 대시보드 EC2 구축 — AWS 권한 요청 (최종본)

> 작성 2026-08-14 · 요청자: 정현(Operations)
> 배경: `docs/operations-ai-aws-migration-plan.md` 기준으로 대시보드 EC2(Operations+FinOps 공용)를
> Terraform으로 구축 중. 코드는 `infra/terraform/aws-platform/dashboard_ec2.tf`에 이미 작성해서
> `terraform fmt`·`terraform validate` 통과했고, 검수 반영(SG description ASCII화·AMI를 공식
> SSM 파라미터로·SSM 정책을 관리형으로 통일·누락 애플리케이션 권한 추가·EBS 암호화)까지 끝났다.
> **이 상태에서 `plan`/`apply`만 못 돌리고 있다 — 코드 문제가 아니라 권한 문제다.**

## 지금 확인된 것

현재 `mp` 프로필(실제 신원 = IAM 사용자 `jeonghyeon`, `arn:aws:iam::689192361171:user/jeonghyeon`)은
**EKS `kubectl` 접근 전용**(PR #676 = Access Entry)이다. 이 계정으로 `terraform init`을
시도하면 state 버킷 접근에서 바로 `403 Forbidden`이 난다(실측 확인).

## 최종 요청 — 3가지

이 3가지만 있으면 대시보드 EC2 구축부터, 이후 Prometheus/Loki/Tempo 데이터 연결·Bedrock 호출까지
**추가 요청 없이** 전부 진행 가능하다(이유는 문서 하단 "왜 이게 전부인가" 참고).

### 요청 A — Terraform state 읽기

`infra/terraform/aws-platform/backend.tf`가 `mp-backup-ap2` 버킷의
`tfstate/aws-platform.tfstate`를 원격 state로 쓴다. `plan`을 돌리려면 최소한 이 객체를
읽을 수 있어야 한다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TfStateRead",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::mp-backup-ap2",
        "arn:aws:s3:::mp-backup-ap2/tfstate/aws-platform.tfstate"
      ]
    }
  ]
}
```

### 요청 B — Terraform apply 쓰기 권한 (EC2 구축 실행)

VPC·EKS·노드그룹은 이미 만들어져 있어 그쪽은 상태 조회만 하면 되고, `dashboard_ec2.tf`가
**새로 만드는 리소스로만 범위를 좁힐 수 있다**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DashboardEc2Manage",
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:TerminateInstances",
        "ec2:Describe*",
        "ec2:AllocateAddress",
        "ec2:AssociateAddress",
        "ec2:ReleaseAddress",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:AuthorizeSecurityGroupEgress",
        "ec2:CreateTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DashboardIamManage",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:PutRolePolicy",
        "iam:CreateInstanceProfile",
        "iam:AddRoleToInstanceProfile",
        "iam:AttachRolePolicy",
        "iam:GetRole",
        "iam:GetInstanceProfile"
      ],
      "Resource": [
        "arn:aws:iam::689192361171:role/mp-dashboard-ec2",
        "arn:aws:iam::689192361171:instance-profile/mp-dashboard-ec2"
      ]
    },
    {
      "Sid": "DashboardPassRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::689192361171:role/mp-dashboard-ec2",
      "Condition": {
        "StringEquals": { "iam:PassedToService": "ec2.amazonaws.com" }
      }
    }
  ]
}
```

state 자체(VPC·EKS 등 기존 리소스)는 **읽기만** 하고 바꾸지 않는다 — `dashboard_ec2.tf`가
참조만 하지 수정하는 리소스가 없다.

### 요청 C — SSM 접속 범위를 이 EC2까지 확장

PR #676에서 실측 확인된 대로, 현재 `mp-team-dev` 정책의 `ssm:StartSession`은
**`Name=mp-ci-server` 태그로만** 허용돼 있다:

```
ssm:StartSession → mp-ci-server : allowed
ssm:StartSession → mp-eks-node  : implicitDeny
```

새로 만드는 대시보드 EC2는 태그가 `Name=mp-dashboard`(`Component=finops-dashboard`)라서
**이 조건에 안 걸린다.** EC2가 만들어진 뒤 실제로 들어가서 `docker compose`를 띄우려면,
이 조건에 새 태그를 추가해야 한다.

```json
{
  "Sid": "SsmSessionDashboard",
  "Effect": "Allow",
  "Action": "ssm:StartSession",
  "Resource": "arn:aws:ec2:ap-northeast-2:689192361171:instance/*",
  "Condition": {
    "StringEquals": { "ssm:resourceTag/Name": "mp-dashboard" }
  }
}
```

## 왜 이게 전부인가 — 이미 해결된 것들

| 나중에 할 일 | 왜 추가 요청이 필요 없나 |
|---|---|
| **Bedrock 호출(RCA)** | `dashboard_ec2.tf`에 이미 IAM 정책으로 작성됨 — 요청 B가 승인되면 EC2 Instance Profile이 자동으로 이 권한을 갖는다 |
| **Secrets Manager `mp/prod/dashboard/*` 읽기** | 위와 동일, 이미 코드에 있음 |
| **SSM Parameter Store `/mp/dashboard/*` 읽기** | 위와 동일 |
| **Cost Explorer·CloudWatch·Athena(FinOps 비용 조회)** | 위와 동일 |
| **`ec2:DescribeInstances`(cluster-proxy 노드 IP 자동조회)** | 위와 동일 |
| **Prometheus NodePort 신설** | Terraform/IAM이 아니라 Ansible(`kube-prometheus-stack-values.yaml.j2`) 수정 — kubectl 권한만 필요한데 팀원 4명 전원 `mp:admin`(PR #676)이라 이미 있음 |
| **Loki/Tempo NodePort 신설** | 위와 동일 |
| **신규 NodePort들에 대한 SG 규칙** | `mp-sg-dashboard → mp-sg-eks-node`가 이미 `30000-32767` 전 범위로 열려 있음(`infra/terraform/aws-platform/security_groups.tf` 확인됨) — 포트가 늘어나도 SG는 안 바뀐다 |

## 별개로 남는 것 — 본인 요청 사항 아님

`finops-dashboard-resource-read`라는 IAM 정책이 실제로 이 계정에 있는지 확인이 안 된 상태다.
`FinOpsDashboardReadOnlyRole`(FinOps 담당자 계정)에는 `iam:GetPolicy`/`iam:ListPolicies`
권한이 없어서 FinOps 담당자 본인도 확인이 막혀 있다. 이건 Operations 요청이 아니라
**FinOps 담당자가 별도로 확인·요청할 사항**이라 여기 포함하지 않았다(참고로만 남김).
