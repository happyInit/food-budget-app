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
    🔴 app/pipeline SA 36개(config #161) 중 **3개만** 받는다(pipeline_bedrock·pg_barman·pg_dump).
    나머지 33개에 붙이지 않는 것이 `0-14c` 의 산출물이다.
    🔵 loki_s3·tempo_s3 는 그 36개와 **별개 ns(`observability`)** 라 위 셈에 들지 않는다.
  EOT
  value       = local.irsa_role_arns

  # 🔴 **이 precondition 이 이 커밋의 본론이다.**
  #
  #    바로 아래 주석(2026-08-13)이 *"복붙 두 벌은 키를 하나 추가할 때 한쪽만 고치게 된다"* 고
  #    적어 뒀는데, **2026-08-14 에 정확히 같은 부류로 또 났다** — `s3_observability.tf` 가
  #    IRSA 롤 2개(`mp-loki-s3`·`mp-tempo-s3`)를 추가했는데 이 map 은 손으로 적힌 7개 그대로여서
  #    `terraform output` 이 **롤 9개 중 7개만** 보여줬다. 기능은 멀쩡했기 때문에(config 가 ARN 을
  #    직접 적는다) **아무도 안 죽고 조용히 어긋났다** — 가장 나쁜 형태다.
  #
  #    ⇒ 손으로 맞추는 대신 **어긋나면 죽게** 만든다. 비교 대상은
  #      `data.aws_iam_policy_document.irsa_trust` 의 키다 — **IRSA 롤은 신뢰정책 없이 존재할 수
  #      없으므로** 그 for_each 맵이 "IRSA 롤 전부"의 사실상 정본이다.
  #      새 롤을 추가하면 거기에 키가 생기고, 여기 map 을 안 고치면 `terraform plan` 이 죽는다.
  #
  # ⚠️ `aws_iam_role` 들을 `for_each` 로 묶어 map 을 자동 생성하는 리팩터는 **일부러 안 했다** —
  #    리소스 주소가 `aws_iam_role.pg_barman` → `aws_iam_role.irsa["pg_barman"]` 로 바뀌어
  #    `moved` 블록 없이는 **destroy + create** 가 되고, 그건 라이브 IRSA 를 잠깐 끊는다.
  #    가드로 얻는 것이 같고 위험은 0 이다.
  precondition {
    condition     = toset(keys(local.irsa_role_arns)) == toset(keys(data.aws_iam_policy_document.irsa_trust))
    error_message = <<-EOT
      IRSA 롤 목록이 어긋났다 — `locals.irsa_role_arns` 와 `irsa_trust` 의 for_each 키가 다르다.
      IRSA 롤을 추가/삭제했다면 **양쪽 다** 고쳐야 한다.
        irsa_trust        : ${join(", ", sort(keys(data.aws_iam_policy_document.irsa_trust)))}
        irsa_role_arns    : ${join(", ", sort(keys(local.irsa_role_arns)))}
    EOT
  }
}

# 🔴 **두 output 이 같은 map 을 각자 적고 있었다 — 하나로 합쳤다**(2026-08-13).
#    복붙 두 벌은 키를 하나 추가할 때 한쪽만 고치게 되고, 그 갈림은
#    `-e @vars.json` 을 쓰는 쪽에서만 드러나 찾기 어렵다. 정의는 `locals.ansible_extra_vars` 다.
output "ansible_extra_vars" {
  description = <<-EOT
    Ansible `eks.yml` 에 그대로 넘기는 값들.
      ansible-playbook eks.yml -e "$(terraform output -raw ansible_extra_vars_json)"
    처럼 쓰지 말고, README 의 절차대로 `-e @vars.json` 으로 넘긴다(따옴표 사고 방지).
  EOT
  value       = local.ansible_extra_vars
}

output "ansible_extra_vars_json" {
  description = "위와 같은 내용의 JSON 한 줄 — `terraform output -raw ansible_extra_vars_json > vars.json`."
  value       = jsonencode(local.ansible_extra_vars)
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

# ── A0.5 CI (A-28) — 🔴 `gitlab.yml` 이 요구하는 값 ────────────────────────────
# 쓰는 법:  terraform output -raw ci_ansible_extra_vars_json > /tmp/ci-vars.json
#           ansible-playbook -i inventory_aws.aws_ec2.yml gitlab.yml -e @/tmp/ci-vars.json
#
# 🔴 **볼륨 ID 를 넘기는 것이 이 output 의 존재 이유다.** 크기(60/50)나 `nvme` 번호로 고르면
#    안 된다 — Nitro 에서 **디바이스 이름 순서와 nvme 번호가 어긋난다**(2026-08-13 실측 · 결함 #26:
#    `/dev/sdf`(docker) → `nvme2n1` / `/dev/sdg`(data) → `nvme1n1`). 크기가 같아지는 날엔
#    구분이 아예 불가능해지고, 그때 **데이터 볼륨을 포맷**한다.
#    ⇒ Ansible 은 `/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_vol<ID>` 로만 식별한다.
output "ci_ansible_extra_vars" {
  description = "A0.5 `gitlab.yml` 용 변수 묶음."
  value       = local.ci_ansible_extra_vars
}

output "ci_ansible_extra_vars_json" {
  description = "위와 같은 내용의 JSON 한 줄."
  value       = jsonencode(local.ci_ansible_extra_vars)
}

# ── 공개 진입 ALB (C-60 · A2 후반) ────────────────────────────────────────────
#
# 🔴 **이 output 은 `aws_acm_certificate_validation` 에 의존하지 않는다** — 그래야
#    1단(`terraform apply -target=aws_acm_certificate.public`) 직후에 읽을 수 있다.
#    검증 레코드를 못 읽으면 2단으로 못 넘어간다(`acm.tf` 의 3단 절차).
output "acm_validation_records" {
  description = <<-EOT
    🔴 **Cloudflare 에 손으로 넣을 CNAME 2개**(DNS 가 아직 IaC 밖 — `1-56`).
      · **반드시 회색(DNS only)** — 주황이면 CF 가 자기 주소를 돌려줘 영원히 PENDING_VALIDATION 이다
      · TTL 은 아무 값이나(검증용이라 수명이 짧다)
    넣고 나면 보통 1~5분 안에 ISSUED 로 바뀐다.
  EOT
  value = {
    for dvo in aws_acm_certificate.public.domain_validation_options :
    dvo.domain_name => {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  }
}

output "alb_dns_name" {
  description = <<-EOT
    🔴 **Cloudflare 에 만들 CNAME 의 대상**이다.
      `aws.mealbong.cloud`  CNAME → 이 값 · **회색(DNS only)** — A2 내부 검증 (C-78)
      `app.mealbong.cloud`  A3 컷오버 때 여기로 옮긴다 (`1-54` · 주황→회색)
    🔴 **`aws` 레코드를 명시적으로 만들어야 한다** — 와일드카드 `*.mealbong.cloud` 가
       이미 그 이름을 가로채 사설주소로 응답하고 있다(실측: NXDOMAIN 이 아니라 타임아웃).
  EOT
  value       = aws_lb.public.dns_name
}

output "alb_zone_id" {
  description = "ALIAS 레코드를 쓸 경우의 호스팅존 ID. Cloudflare 는 CNAME 이면 되므로 지금은 참고용이다."
  value       = aws_lb.public.zone_id
}

output "alb_target_group_arn" {
  description = <<-EOT
    `TargetGroupBinding` 이 참조할 ARN. **Ansible `eks_lb_controller` 가 이 값을 받는다**
    (`ansible_extra_vars` 에도 같은 값이 들어 있다 — config 레포는 계정 ID 를 담지 않는다).
  EOT
  value       = aws_lb_target_group.gateway.arn
}

output "waf_web_acl_arn" {
  description = "AWS WAF Web ACL (`1-49`). 🔴 부착(association)까지 돼야 실제로 작동한다 — 콘솔에 룰만 보이는 상태가 흔한 실패다."
  value       = aws_wafv2_web_acl.public.arn
}

# ── ElastiCache (C-14) ────────────────────────────────────────────────────────
# 🔴 config 의 `common/overlays/eks` 가 이 값을 `REDISHOST` 로 받는다.
#    함께 `REDIS_SENTINELS` 를 **빈 문자열로** 덮어야 한다 — 안 그러면 앱이 Sentinel 분기를
#    타서 존재하지 않는 온프렘 주소를 찾는다(`common/base/app-common.yaml`).
output "cache_primary_endpoint" {
  description = "Valkey primary 엔드포인트 (쓰기·읽기 공용). config `REDISHOST` 값."
  value       = aws_elasticache_replication_group.valkey.primary_endpoint_address
}

output "cache_reader_endpoint" {
  description = "Valkey reader 엔드포인트. 지금은 소비자가 없다 — 읽기 분리를 할 때 쓴다."
  value       = aws_elasticache_replication_group.valkey.reader_endpoint_address
}
