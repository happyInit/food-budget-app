# 🔴 이 출력들은 **다른 레포·다른 도구의 입력값**이다. 손으로 옮겨 적으면 갈린다.

output "ecr_registry" {
  description = <<-EOT
    🔴 **config 레포 `scripts/sites.yaml` 의 `eks.registry` 에 넣을 값이다.**
    지금 그 파일은 `PLACEHOLDER.dkr.ecr...` 이고, 그 레포의 절차가
    *"① sites.yaml 을 고친다 ② validate.py 가 안 맞는 오버레이를 전부 열거한다
    ③ 목록대로 newName 을 맞춘다"* 로 적혀 있다. 손으로 15곳을 세지 않는다.
  EOT
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com/mealplanning"
}

output "account_id" {
  description = "계정 ID. IRSA 신뢰정책·ECR·KMS 정책이 이 값을 쓴다(정본은 PLACEHOLDER 로 비워 둔다 — 공개 레포)."
  value       = data.aws_caller_identity.current.account_id
}

output "cluster_name" {
  value = aws_eks_cluster.main.name
}

output "kubeconfig_command" {
  description = "C-80 의 비대화형 경로. 이 한 줄이 온프렘의 `ssh wsl-dev 'kubectl …'` 2겹을 1겹으로 만든다."
  value       = "aws eks update-kubeconfig --name ${aws_eks_cluster.main.name} --region ${var.region} --profile <프로필>"
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.eks.arn
}

output "irsa_role_arns" {
  description = <<-EOT
    ServiceAccount 애너테이션(`eks.amazonaws.com/role-arn`)에 넣을 값.
    🔴 config #161 이 만든 SA 36개 중 **3개만** 받는다(pipeline_bedrock·pg_barman·pg_dump).
    나머지 33개에 붙이지 않는 것이 `0-14c` 의 산출물이다.
  EOT
  value = {
    cilium_operator  = aws_iam_role.cilium_operator.arn
    ebs_csi          = aws_iam_role.ebs_csi.arn
    external_secrets = aws_iam_role.external_secrets.arn
    karpenter        = aws_iam_role.karpenter.arn
    pipeline_bedrock = aws_iam_role.pipeline_bedrock.arn
    pg_barman        = aws_iam_role.pg_barman.arn
    pg_dump          = aws_iam_role.pg_dump.arn
  }
}

output "ansible_extra_vars" {
  description = <<-EOT
    Ansible `eks.yml` 에 그대로 넘기는 값들.
      ansible-playbook eks.yml -e "$(terraform output -raw ansible_extra_vars_json)"
    처럼 쓰지 말고, README 의 절차대로 `-e @vars.json` 으로 넘긴다(따옴표 사고 방지).
  EOT
  value = {
    eks_cluster_name        = aws_eks_cluster.main.name
    eks_cluster_endpoint    = aws_eks_cluster.main.endpoint
    eks_region              = var.region
    eks_node_security_group = aws_security_group.node.id
    eks_vpc_id              = aws_vpc.service.id
    eks_ecr_registry        = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com"
    irsa_cilium_operator    = aws_iam_role.cilium_operator.arn
    irsa_ebs_csi            = aws_iam_role.ebs_csi.arn
    irsa_external_secrets   = aws_iam_role.external_secrets.arn
    irsa_karpenter          = aws_iam_role.karpenter.arn
    karpenter_queue_name    = aws_sqs_queue.karpenter_interruption.name
    karpenter_node_role     = aws_iam_role.node.name
  }
}

output "ansible_extra_vars_json" {
  description = "위와 같은 내용의 JSON 한 줄 — `terraform output -raw ansible_extra_vars_json > vars.json`."
  value = jsonencode({
    eks_cluster_name        = aws_eks_cluster.main.name
    eks_cluster_endpoint    = aws_eks_cluster.main.endpoint
    eks_region              = var.region
    eks_node_security_group = aws_security_group.node.id
    eks_vpc_id              = aws_vpc.service.id
    eks_ecr_registry        = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com"
    irsa_cilium_operator    = aws_iam_role.cilium_operator.arn
    irsa_ebs_csi            = aws_iam_role.ebs_csi.arn
    irsa_external_secrets   = aws_iam_role.external_secrets.arn
    irsa_karpenter          = aws_iam_role.karpenter.arn
    karpenter_queue_name    = aws_sqs_queue.karpenter_interruption.name
    karpenter_node_role     = aws_iam_role.node.name
  })
}

output "node_subnet_ids" {
  value = { for az, s in aws_subnet.node : az => s.id }
}

output "dashboard_security_group_id" {
  description = "C-84 의 대시보드 EC2 를 띄울 때 붙일 SG. 이 SG 만이 노드 NodePort(30000-32767)에 닿는다(C-85)."
  value       = aws_security_group.dashboard.id
}

output "ci_security_group_id" {
  description = "A-28 의 GitLab EC2 용. 🔴 인바운드 규칙 0개 — SSH 를 열려면 A-34 ① 을 먼저 다시 판정한다."
  value       = aws_security_group.ci.id
}
