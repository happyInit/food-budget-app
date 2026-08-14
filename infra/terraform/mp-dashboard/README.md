# mp-dashboard — 대시보드 EC2 Terraform 스택

FinOps·Operations AI 대시보드 EC2 1대(C-84)를 만든다. **`aws-platform` 스택과 완전히 별개**다 —
별도 state 버킷(`mp-dashboard-tfstate-ap2`), 별도 IAM 4종(`infra/iam/mp-dashboard/*.json`).
VPC·서브넷·SG(`mp-sg-dashboard`)·EKS 노드 SG 는 `aws-platform` 이 만들고, 이 스택은 그것들을
**이름으로 조회만** 한다(`data.tf`) — 여기서 재생성하거나 지우지 않는다.

## 선행 조건

1. `infra/iam/mp-dashboard/apply.sh` 가 이미 실행돼 IAM 정책 4종(`mp-dashboard-boundary` ·
   `mp-dashboard-dev` · `mp-dashboard-ops` · `mp-dashboard-guardrails`)과 `mealplanning-dashboard`
   그룹이 만들어져 있어야 한다. 이 그룹이 붙은 개인 프로필로만 apply 할 수 있다.
2. `aws-platform` 스택이 먼저 apply 돼 있어야 한다(VPC·서브넷·`mp-sg-dashboard`·`mp-sg-eks-node`
   가 이미 존재해야 `data` 조회가 성공한다).

## 사용법

```bash
cp backend.conf.example backend.conf   # profile 값을 본인 프로필로 채운다
terraform init -backend-config=backend.conf
terraform plan  -var="profile=<본인 프로필>"
terraform apply -var="profile=<본인 프로필>"
```

## 🔴 알려진 제약 — Athena·Glue

`mp-dashboard-boundary`(이 EC2 Instance Role 의 permissions boundary)는 `athena:*`·`glue:*` 를
포함하지 않는다. `dashboard_ec2.tf` 의 `dashboard_finops_cost_read` 에 Athena 권한을 넣어도
경계와의 교집합이 비어 **실질적으로 동작하지 않는다**(배포 후 조용히 AccessDenied). CUR+Athena
기반 상세 비용 조회(`operations-ai-aws-migration-plan.md` §2)는 지금 이 role 로는 불가능하다 —
경계 정책을 갱신하거나, 그 조회를 사람이 `mp-dashboard-ops` 프로필로 직접 실행하는 경로로
당분간 대체해야 한다. Cost Explorer 빠른 조회(`ce:GetCostAndUsage` 등)는 boundary 안이라 된다.

## ECR 을 쓰지 않는다

`mp-dashboard-boundary` 는 ECR pull 액션을 상한으로는 허용해 두었지만, 이 스택의 role 정책에는
의도적으로 ECR 액션을 넣지 않았다 — `operations-ai-aws-migration-plan.md` §4 확정대로 **EC2 에서
소스를 직접 빌드**한다. 다른 초안(`docs/aws-dashboard-ec2-deployment-plan.md`, SUPERSEDED)의
ECR pull 전제는 그 이후 뒤집힌 결정이다.
