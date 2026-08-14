# `aws-platform` — AWS 이관 A0 기반 (Terraform)

> 신설 2026-08-13. 근거 = `docs/mp_aws_prep_checklist.md` **C-77**(AWS IaC 전량 신규) ·
> **C-78 A0**(기반 = 네트워크·EKS·노드그룹) · **A-7**(Terraform AWS provider 골격).
> 🔴 **결정 정본은 그 체크리스트다.** 이 README 는 *어떻게 돌리는가* 만 적는다.

## 🔴 이 디렉터리가 왜 따로 있나

이 레포에는 Terraform 스택이 **셋**이고 서로 state 가 다르다.

| 경로 | 무엇 | state key |
|---|---|---|
| `../` | Proxmox VM (온프렘) | `tfstate/proxmox.tfstate` |
| `../aws/` | 크롤 운반 S3·SQS·IAM (C-44) | `tfstate/aws-crawl.tfstate` |
| **여기** | VPC·EKS·노드그룹·IRSA·ECR·Karpenter | `tfstate/aws-platform.tfstate` |

기존 파일을 고치지 않고 새로 쓴 이유는 **AWS 쪽 수정이 온프렘으로 번지지 않게** 하는 것이고,
state 를 가른 이유는 **이 스택의 apply 가 크롤 큐나 Proxmox VM 을 건드릴 수 없어야** 하는 것이다.

## 사람이 먼저 해야 하는 것

1. **플랫폼 권한 프로필** — 🔴 `mp-backup` 은 백업 전용이라 **안 된다**(VPC·EKS·IAM·ECR 을 만든다).
   `~/.aws/credentials` 에 프로필을 만들고 `terraform.tfvars` 의 `profile` 에 적는다.
2. **`cluster_admin_principals`** — 🔴 비면 **아무도 클러스터에 들어갈 수 없다.**
   `authentication_mode = "API"` + `bootstrap_cluster_creator_admin_permissions = false` 라
   클러스터를 만든 주체조차 자동 권한이 없다(구 `aws-auth` 시절과 다르다).
3. **Secrets Manager 시크릿**(🔴 SSM 파라미터가 아니다 — **C-36**) — `mp/prod/…`.
   최소 `mp/prod/repo-mealplanning-config` 가 있어야 ArgoCD 가 뜬 뒤 config 레포를 읽는다.
   🔴 **값은 JSON 3키 번들**이다 — `sshPrivateKey`(read-only 배포키) · `type: git` · `url`.
   개인키 원문만 넣으면 ESO 가 파싱에 실패한다.
   ```bash
   ssh-keygen -t ed25519 -N "" -C "mp-eks-argocd@mealplanning-config" -f ~/.ssh/mp-eks-argocd
   gh api -X POST repos/happyInit/mealplanning-config/keys \
     -f title="mp-eks argocd (AWS)" -f key="$(cat ~/.ssh/mp-eks-argocd.pub)" -F read_only=true
   python3 -c 'import json;json.dump({"sshPrivateKey":open("'$HOME'/.ssh/mp-eks-argocd").read(),
     "type":"git","url":"git@github.com:happyInit/mealplanning-config.git"},
     open("/tmp/mp-argocd-repo.json","w"))'
   aws secretsmanager create-secret --region ap-northeast-2 \
     --name mp/prod/repo-mealplanning-config --secret-string file:///tmp/mp-argocd-repo.json
   shred -u /tmp/mp-argocd-repo.json ~/.ssh/mp-eks-argocd ~/.ssh/mp-eks-argocd.pub
   ```
   ⚠️ KMS 키는 지정하지 않는다 = `aws/secretsmanager`(AWS 관리 · $0). 미결 ⑰ 이 CMK 를 고르면
   `update-secret --kms-key-id` 로 옮기고 **A-26**(키 정책에 IRSA 롤 명시)을 함께 한다.
   나머지 번들(app-secrets 등)은 A2 전까지.

## 돌리는 법 — 🔴 **2단 apply 다** (리허설에서 확정한 순서)

```bash
cp backend.conf.example backend.conf          # gitignored
cp terraform.tfvars.example terraform.tfvars  # gitignored
terraform init -backend-config=backend.conf
terraform plan                                # 전체 계획을 먼저 읽는다
```

### 1단 — 노드그룹만 빼고 전부

```bash
terraform apply -var create_node_group=false
terraform output -raw ansible_extra_vars_json > /tmp/eks-vars.json
cd ../../ansible && ansible-playbook eks.yml -e @/tmp/eks-vars.json --tags preflight,cilium
```

🔴 **`-target` 을 쓰지 않는다** — 리허설(2026-08-13)에서 실측으로 갈렸다. `-target` 은
*의존성만* 끌어오므로 1단이 **8개 리소스로 좁혀지고**(VPC·노드서브넷·클러스터·OIDC·IAM·로그그룹)
네트워크·IRSA·SQS·SG 가 통째로 빠진다. 그러면 `output "ansible_extra_vars_json"` 이
`aws_security_group.node`·`aws_iam_role.cilium_operator`·`aws_sqs_queue.karpenter_interruption` 을
참조하지 못해 **Ansible 에 넘길 변수 묶음 자체를 뽑을 수 없다** — 즉 다음 줄에서 막힌다.
Terraform 자신도 `-target` 을 *"not for routine use"* 라고 경고한다.
⇒ `create_node_group` 토글이면 **노드그룹 하나만** 빠지고 나머지 117개는 온전하다.

🔴 **왜 노드그룹을 여기서 빼는가** — C-82 로 CNI 가 없으므로 노드는 부팅 후 **NotReady** 로 남는다.
관리형 노드그룹은 노드가 *등록*되면 ACTIVE 가 되지만, Ready 를 기다리는 국면에 걸리면
`NodeCreationFailure: Instances failed to join the kubernetes cluster` 로 **약 20분 뒤 실패**한다.
Cilium 을 먼저 얹으면 노드가 뜨는 즉시 DaemonSet 이 내려가 Ready 가 된다 —
이것이 Cilium 공식 EKS 절차(`--without-nodegroup` → `cilium install` → `create nodegroup`)와 같은 순서다.

🟢 이 시점에 노드는 0대이고 `cilium-operator` 는 Pending 이다. **정상이다** — 그래서 롤이
`wait: false` 로 깔고, 노드 0대를 감지하면 다음 단계를 안내하고 넘어간다.

### 2단 — 나머지 전부

```bash
cd ../terraform/aws-platform && terraform apply      # 노드그룹 · ECR · IRSA · Karpenter …
terraform output -raw ansible_extra_vars_json > /tmp/eks-vars.json
cd ../../ansible && ansible-playbook eks.yml -e @/tmp/eks-vars.json
```

🟢 **`eks.yml` 은 멱등하다** — 1단에서 이미 한 것은 다시 하지 않고, cilium 롤은 이번엔
노드가 있으므로 Ready 대기까지 실제로 수행한다.

🔴 **`ansible_become`** — `group_vars/all.yml` 이 `ansible_become: true` 를 전 호스트에 걸고 있어
`eks.yml` 의 모든 플레이가 **play vars 로 `ansible_become: false` 를 덮는다.** 지우지 말 것 —
지우면 helm·kubectl·aws 가 **root 의 `~/.aws`·`~/.kube`** 를 보게 되어 자격증명이 사라진다.
(`become: false` 키워드로는 안 된다 — 커넥션 변수가 키워드를 이긴다.)

🔴 **값을 손으로 옮겨 적지 말 것.** 계정 ID·IRSA ARN·SG ID 가 여러 곳에 필요하고,
손으로 옮기면 갈린다. config 레포의 `scripts/sites.yaml` 도 같은 이유로 output 을 쓴다:

```bash
terraform output -raw ecr_registry   # → config 레포 sites.yaml 의 eks.registry
```

## 🔴 이 스택이 **만들지 않는** 것 — 의도된 경계

| 무엇 | 왜 · 어디서 |
|---|---|
| **ALB · ACM · AWS WAF** | 진입 전환은 순서가 곧 안전장치다(C-60 §1-G). `1-48`(ACM+CNAME) → `1-49`(WAF) → `1-50`(GW 리스너 HTTP) → `1-54`(DNS 전환) 를 **A2 에서 한 세트로** 한다. 지금 만들면 인증서만 있고 뒤가 없다 |
| **ElastiCache · KMS 키** | **A1**(데이터 티어) 소관. C-14 = Valkey · 미확정 ⑰(CMK vs 관리형)가 열려 있다 |
| **S3 버킷** | 🔴 `mp-backup-ap2` 는 **라이브 백업이 들어 있다.** Terraform 에 편입하면 `destroy` 한 번이 백업을 지운다. IRSA 정책이 ARN 으로만 참조한다. 라이프사이클(C-79)은 A4 |
| **SQS 크롤 큐 · 리파이너** | `../aws/` 스택 + **A5**(맨 뒤 · 사용자 지시) |
| **CloudTrail · GuardDuty** | `A-5` · `A-20`. Object Lock `COMPLIANCE` 가 붙는 버킷이라 실수 여지가 크다 → 별 PR |
| **CI EC2 (GitLab)** | `A-28`. SG 만 여기서 만든다(`ci_security_group_id`) |
| **대시보드 EC2** | C-84 · `docs/aws-dashboard-ec2-deployment-plan.md`. SG 만 여기서(`dashboard_security_group_id`) |
| **Karpenter NodePool** | K8s 오브젝트라 Ansible `eks_karpenter` 롤. 여기는 IRSA·큐·태그까지 |

## 🔴 읽는 사람이 놓치기 쉬운 것 3개

1. **노드는 처음에 `NotReady` 로 뜬다.** C-82 로 vpc-cni 를 안 깔았으므로 CNI 가 없다.
   Ansible `eks.yml --tags cilium` 이 그것을 해소한다. 🔴 *"노드가 안 뜬다"* 로 읽고
   vpc-cni 를 깔면 **Cilium 과 CNI 소유권을 다투게 된다**(preflight 의 assert 가 이걸 막는다).
2. **라우팅 테이블이 3개다** — `A-21` 은 "2개"라고 적고 있다. 데이터 티어의
   *"밖으로 나가는 경로 없음"*(§1)을 지키려면 노드와 RT 를 공유할 수 없다. 개수는 결과다.
3. **`gp3`/`gp3-retain` StorageClass 는 여기 없다.** EBS CSI 애드온은 SC 를 만들지 않고,
   config 레포 `platform/cluster-baseline/overlays/eks/storageclasses.yaml`(0-8e)이 정본이다.
   ⇒ ArgoCD 가 뜨기 전에 PVC 를 만들면 **Pending 이 정상**이다.

## 비용 (C-31 · 실단가 기준 · 이 스택이 만드는 것만)

| | 월 |
|---|---|
| EKS 컨트롤플레인 | $73 |
| `m7g.xlarge` × 2 (C-45) | $292.88 |
| NAT Gateway ×1 (C-47) + EIP | 약 $40 + 데이터 처리 |
| Interface 엔드포인트 3종 × 2AZ (C-56) | **$56.94** (절감이 아니라 NAT SPOF 보험) |
| EKS audit → CloudWatch (C-66) | 약 $59 **추정** — 🔴 1개월 실측 후 재판정 |
| ECR · SQS · EBS 루트 60Gi × 2 | 소액 |

🔴 **Karpenter 노드는 평시 0대**라 위 표에 없다. 상한은 `eks_karpenter_cpu_limit`(기본 16 vCPU)이다.
