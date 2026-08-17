# FinOps 대시보드 AWS 권한 요청 — 리소스·사양·예상 비용 조회용 

**요청 파트** FinOps 대시보드   
**대상 IAM Role** `arn:aws:iam::689192361171:role/FinOpsDashboardReadOnlyRole`   
**작성** 2026-08-14 · **필요 시점** 즉시   
**범위** AWS 계정 `689192361171` · 리전 `ap-northeast-2`의 리소스 목록·구성 사양·상태 조회   
**권한 성격** 조회 전용 — 생성·수정·삭제·배포·Secret 값 조회 권한 없음 

--- 

## 0. 왜 지금 요청하는가 

FinOps 대시보드는 현재 CloudWatch Metric과 AWS Price List를 이용해 AWS 리소스 58개를 표시하고 있습니다. 
하지만 `FinOpsDashboardReadOnlyRole`에 주요 Resource API 조회 권한이 없어 다음 문제가 있습니다. 

- EC2·EBS·EKS·NAT Gateway는 CloudWatch Dimension으로 ID만 확인하고 현재 상태와 정확한 사양을 조회하지 못합니다. 
- EBS 13개는 용량·볼륨 타입·IOPS·Throughput을 알 수 없어 비용을 계산하지 못합니다. 
- Load Balancer·RDS·Public IPv4·Lambda·SNS는 실제 리소스 목록을 표시하지 못합니다. 
- ECR·ElastiCache는 CloudWatch 사용량은 표시하지만 저장 용량·노드 타입을 알 수 없어 비용을 계산하지 못합니다. 
- Logs·EventBridge·SQS·KMS·Secrets Manager 등은 사용량만 보이고 보존 기간·암호화·연결 구성 같은 운영 설정이 빠집니다. 

2026-08-14에 대상 Role로 실제 읽기 API를 호출한 결과, 아래 요청 정책에 포함한 API가 모두 `AccessDenied` 또는 `UnauthorizedOperation`으로 거부되는 것을 확인했습니다. 

--- 

## 1. 요청 요약 

| # | 요청 내용 | 부여 방법 | 위험도 | 
|:--:|---|---|:--:| 
| **①** | AWS 리소스 목록·사양·상태 조회 | 아래 §3 커스텀 정책 생성 | 낮음 | 
| **②** | 정책을 대시보드 Role에 연결 | `FinOpsDashboardReadOnlyRole`에 부착 | 낮음 | 

요청 정책 이름: 

```text 
finops-dashboard-resource-read 
``` 

`ReadOnlyAccess` 관리형 정책 전체를 요청하지 않고, 대시보드에서 필요한 조회 API만 명시합니다. 

--- 

## 2. 권한별 사유 

| 서비스 | 요청 권한 | 대시보드에서 표시할 정보 | 
|---|---|---| 
| EC2 | `DescribeInstances` | Name 태그·인스턴스 타입·상태·시작 시각·구매 옵션·AZ | 
| EBS | `DescribeVolumes` | 용량·gp2/gp3·IOPS·Throughput·연결 EC2·생성 시각·예상 비용 | 
| Public IPv4 | `DescribeAddresses` | Elastic IP·연결 대상·도메인·예상 비용 | 
| NAT Gateway | `DescribeNatGateways` | 상태·VPC·Subnet·생성 시각·처리량 비용 | 
| PrivateLink | `DescribeVpcEndpoints` | Endpoint 상태·서비스·VPC·Subnet·생성 시각 | 
| Auto Scaling | `DescribeAutoScalingGroups` 등 | Min·Max·Desired·InService·Launch Template | 
| EKS | `ListClusters`·`DescribeCluster`·Nodegroup 조회 | Kubernetes 버전·지원 유형·상태·Node Group 사양 | 
| Load Balancer | `Describe*` | ALB/NLB 타입·상태·Listener·Target Group·LCU 계산 근거 | 
| RDS | `DescribeDBInstances`·`DescribeDBClusters` | 엔진·인스턴스 타입·스토리지·Multi-AZ·상태 | 
| ElastiCache | `DescribeCacheClusters`·`DescribeReplicationGroups` | 엔진·노드 타입·노드 수·Replication 구성·예상 비용 | 
| CloudWatch Logs | `DescribeLogGroups` | 로그 클래스·보존 기간·저장 용량 계산 근거 | 
| EventBridge | Rule·Target 조회 | Rule 상태·Schedule·Target 구성 | 
| SQS | Queue 목록·속성·태그 조회 | Standard/FIFO·암호화·DLQ·보존 기간 | 
| SNS | Topic 목록·속성·태그 조회 | Topic 목록·암호화·구독 구성 | 
| Lambda | 함수 목록·설정·태그 조회 | 함수·런타임·메모리·아키텍처·Timeout | 
| ECR | Repository·Image·Lifecycle·Scan 조회 | 이미지 수·이미지 크기·Lifecycle·Scan 상태·저장 비용 | 
| Firehose | Stream 목록·설정 조회 | Delivery Stream·목적지·전송 구성 | 
| KMS | Key·Alias·회전 상태 조회 | Key 상태·Alias·Key Manager·Rotation | 
| Secrets Manager | Secret 목록·메타데이터 조회 | Secret 이름·상태·Rotation 설정 — 값은 조회하지 않음 | 
| Roles Anywhere | Profile·Trust Anchor 조회 | Profile·Trust Anchor 상태와 연결 정보 | 
| S3 | Bucket 설정 메타데이터 조회 | Region·Versioning·암호화·Lifecycle — Object 값은 조회하지 않음 | 

--- 

## 3. 붙여넣을 정책 — `finops-dashboard-resource-read` 

```json 
{ 
  "Version": "2012-10-17", 
  "Statement": [ 
    { 
      "Sid": "Ec2AndVpcResourceRead", 
      "Effect": "Allow", 
      "Action": [ 
        "ec2:DescribeInstances", 
        "ec2:DescribeVolumes", 
        "ec2:DescribeAddresses", 
        "ec2:DescribeNatGateways", 
        "ec2:DescribeVpcEndpoints", 
        "ec2:DescribeLaunchTemplates", 
        "ec2:DescribeLaunchTemplateVersions" 
      ], 
      "Resource": "*" 
    }, 
    { 
      "Sid": "AutoScalingRead", 
      "Effect": "Allow", 
      "Action": [ 
        "autoscaling:DescribeAutoScalingGroups", 
        "autoscaling:DescribeLaunchConfigurations", 
        "autoscaling:DescribeTags" 
      ], 
      "Resource": "*" 
    }, 
    { 
      "Sid": "EksRead", 
      "Effect": "Allow", 
      "Action": [ 
        "eks:ListClusters", 
        "eks:DescribeCluster", 
        "eks:ListNodegroups", 
        "eks:DescribeNodegroup" 
      ], 
      "Resource": "*" 
    }, 
    { 
      "Sid": "LoadBalancerRead", 
      "Effect": "Allow", 
      "Action": [ 
        "elasticloadbalancing:DescribeLoadBalancers", 
        "elasticloadbalancing:DescribeLoadBalancerAttributes", 
        "elasticloadbalancing:DescribeListeners", 
        "elasticloadbalancing:DescribeTargetGroups", 
        "elasticloadbalancing:DescribeTargetHealth", 
        "elasticloadbalancing:DescribeTags" 
      ], 
      "Resource": "*" 
    }, 
    { 
      "Sid": "DatabaseAndCacheRead", 
      "Effect": "Allow", 
      "Action": [ 
        "rds:DescribeDBInstances", 
        "rds:DescribeDBClusters", 
        "rds:ListTagsForResource", 
        "elasticache:DescribeCacheClusters", 
        "elasticache:DescribeReplicationGroups", 
        "elasticache:ListTagsForResource" 
      ], 
      "Resource": "*" 
    }, 
    { 
      "Sid": "MessagingRead", 
      "Effect": "Allow", 
      "Action": [ 
        "sqs:ListQueues", 
        "sqs:GetQueueUrl", 
        "sqs:GetQueueAttributes", 
        "sqs:ListQueueTags", 
        "sns:ListTopics", 
        "sns:GetTopicAttributes", 
        "sns:ListSubscriptionsByTopic", 
        "sns:ListTagsForResource", 
        "events:ListRules", 
        "events:DescribeRule", 
        "events:ListTargetsByRule" 
      ], 
      "Resource": "*" 
    }, 
    { 
      "Sid": "LogsRead", 
      "Effect": "Allow", 
      "Action": [ 
        "logs:DescribeLogGroups" 
      ], 
      "Resource": "*" 
    }, 
    { 
      "Sid": "LambdaRead", 
      "Effect": "Allow", 
      "Action": [ 
        "lambda:ListFunctions", 
        "lambda:GetFunctionConfiguration", 
        "lambda:ListTags" 
      ], 
      "Resource": "*" 
    }, 
    { 
      "Sid": "EcrRead", 
      "Effect": "Allow", 
      "Action": [ 
        "ecr:DescribeRepositories", 
        "ecr:DescribeImages", 
        "ecr:ListImages", 
        "ecr:GetLifecyclePolicy", 
        "ecr:DescribeImageScanFindings", 
        "ecr:ListTagsForResource" 
      ], 
      "Resource": "*" 
    }, 
    { 
      "Sid": "FirehoseRead", 
      "Effect": "Allow", 
      "Action": [ 
        "firehose:ListDeliveryStreams", 
        "firehose:DescribeDeliveryStream", 
        "firehose:ListTagsForDeliveryStream" 
      ], 
      "Resource": "*" 
    }, 
    { 
      "Sid": "SecurityMetadataRead", 
      "Effect": "Allow", 
      "Action": [ 
        "kms:ListKeys", 
        "kms:ListAliases", 
        "kms:DescribeKey", 
        "kms:GetKeyRotationStatus", 
        "secretsmanager:ListSecrets", 
        "secretsmanager:DescribeSecret", 
        "secretsmanager:ListSecretVersionIds", 
        "rolesanywhere:ListProfiles", 
        "rolesanywhere:GetProfile", 
        "rolesanywhere:ListTrustAnchors", 
        "rolesanywhere:GetTrustAnchor" 
      ], 
      "Resource": "*" 
    }, 
    { 
      "Sid": "S3ConfigurationRead", 
      "Effect": "Allow", 
      "Action": [ 
        "s3:ListAllMyBuckets", 
        "s3:GetBucketLocation", 
        "s3:GetBucketVersioning", 
        "s3:GetEncryptionConfiguration", 
        "s3:GetLifecycleConfiguration" 
      ], 
      "Resource": "*" 
    } 
  ] 
} 
``` 

### 정책에서 의도적으로 제외한 권한 

다음 권한은 FinOps 대시보드에 필요하지 않아 요청하지 않습니다. 

- 모든 `Create*`, `Put*`, `Update*`, `Delete*` 권한 
- `secretsmanager:GetSecretValue` 
- `kms:Decrypt`, `kms:GenerateDataKey` 
- `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` 
- `ecr:GetAuthorizationToken`, 이미지 Pull·Push 권한 
- `bedrock:InvokeModel` 
- `iam:PassRole` 및 IAM 생성·수정 권한 
- EKS Access Entry와 Kubernetes `kubectl` 접근 권한 

--- 

## 4. 적용 방법 

### IAM 콘솔 

```text 
IAM → 정책 → 정책 생성 → JSON 
→ §3 정책 붙여넣기 
→ 정책 이름: finops-dashboard-resource-read 
→ 역할 → FinOpsDashboardReadOnlyRole → 권한 추가 
→ finops-dashboard-resource-read 연결 
``` 

### AWS CLI 

```bash 
aws iam create-policy \ 
  --policy-name finops-dashboard-resource-read \ 
  --policy-document file://finops-dashboard-resource-read.json 

aws iam attach-role-policy \ 
  --role-name FinOpsDashboardReadOnlyRole \ 
  --policy-arn arn:aws:iam::689192361171:policy/finops-dashboard-resource-read 
``` 

기존에 같은 이름의 정책이 있으면 새 정책을 중복 생성하지 않고 새 Policy Version으로 반영해 주시면 됩니다. 

--- 

## 5. 권한 적용 후 검증할 항목 

| 확인 항목 | 기대 결과 | 
|---|---| 
| EC2 | 인스턴스 3개의 Name·상태·Launch Time·구매 옵션 표시 | 
| EBS | 볼륨 13개의 용량·타입·IOPS·Throughput과 예상 비용 표시 | 
| EKS | `mp-eks`의 Kubernetes 버전·지원 유형·Node Group 표시 | 
| NAT·PrivateLink | VPC·Subnet·상태·생성 시각 표시 | 
| Load Balancer·RDS·Public IPv4 | 실제 리소스 목록과 사양 표시 | 
| ECR | Repository 18개의 이미지 수·크기·Lifecycle 표시 | 
| ElastiCache | `mp-cache-001`, `mp-cache-002`의 노드 타입·엔진 표시 | 
| Logs·EventBridge·SQS | 보존 기간·Target·암호화·DLQ 표시 | 
| KMS·Secrets Manager | Key·Secret 메타데이터와 Rotation 상태 표시 | 
| Lambda·SNS·Firehose | 리소스가 존재하면 목록과 설정 표시 | 

권한 적용 후 IAM 전파와 대시보드 캐시 때문에 기존 결과가 최대 60초 동안 보일 수 있습니다. 이후 대시보드의 새로고침을 실행해 검증합니다. 

--- 

## 6. 요청드리는 작업 

1. §3의 `finops-dashboard-resource-read` 정책을 생성합니다. 
2. `FinOpsDashboardReadOnlyRole`에 정책을 연결합니다. 
3. 적용 완료 여부를 FinOps 담당자에게 전달합니다. 
4. FinOps 담당자가 대시보드에서 목록·사양·비용 계산 결과를 검증합니다. 

이 요청은 운영 리소스를 변경하기 위한 권한 요청이 아니라, **현재 사용 중인 AWS 리소스의 목록·사양·상태를 읽고 예상 비용을 계산하기 위한 지속적인 조회 권한 요청**입니다. 
