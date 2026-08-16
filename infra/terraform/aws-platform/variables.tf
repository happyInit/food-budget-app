variable "region" {
  description = "AWS 리전. 백업 버킷(mp-backup-ap2)·크롤 스택과 같아야 한다."
  type        = string
  default     = "ap-northeast-2"
}

variable "profile" {
  description = <<-EOT
    apply 에 쓰는 ~/.aws 프로필. 🔴 **백업 전용 `mp-backup` 으로는 안 된다** —
    이 스택은 VPC·EKS·IAM 롤·ECR 을 만든다(backend.tf 주석). 기본값을 두지 않은 것은
    의도다: 잘못된 프로필로 절반쯤 apply 되는 것보다 **처음부터 멈추는 쪽**이 싸다.
  EOT
  type        = string
}

variable "azs" {
  description = <<-EOT
    가용영역 2개 (C-32 · 선생님 지시로 고정). 🔴 늘리지 말 것 —
    C-21(정족수 = AZ 당 1개) · C-42(pg-1/pg-2 배치) · C-52(EBS 는 AZ 를 벗어나지 못한다)가
    이 숫자를 전제로 짜여 있다.
  EOT
  type        = list(string)
  default     = ["ap-northeast-2a", "ap-northeast-2b"]

  validation {
    condition     = length(var.azs) == 2
    error_message = "C-32 = AZ 2개 고정. 바꾸려면 C-21·C-42·C-52 를 먼저 다시 판정해야 한다."
  }
}

# ── VPC 대역 (C-34) ────────────────────────────────────────────────────────────
variable "vpc_service_cidr" {
  description = "VPC-A '서비스' (C-34). 온프렘 LAN 192.168.0.0/24 · 파드 10.244.0.0/16 · svc 10.96.0.0/12 과 겹치지 않는다."
  type        = string
  default     = "10.10.0.0/16"
}

variable "vpc_ci_cidr" {
  description = "VPC-B 'CI' (C-34). 🔴 VPC 피어링은 하지 않는다 — config 레포가 GitHub 에 있어 두 VPC 가 서로를 몰라도 된다(C-61③)."
  type        = string
  default     = "10.11.0.0/16"
}

# ── A0.5 CI 서버 (A-28) ───────────────────────────────────────────────────────
variable "region_short" {
  description = "버킷 이름에 쓰는 리전 약칭. 기존 `mp-backup-ap2` 와 같은 관례다(ap-northeast-2 → ap2)."
  type        = string
  default     = "ap2"
}

variable "ci_instance_type" {
  description = <<-EOT
    CI 서버 인스턴스 타입. 🔴 **C-38·C-63 확정값** — `t4g.xlarge`(4vCPU/16GiB · arm64 Graviton).
    `m7i.xlarge`(x86, +$59/월)는 **미채택**이고, 판정을 막던 근거(`sonar-scanner-cli` amd64 단일)는
    **aarch64 zip 실기동으로 무너졌다**(C-63). 바꾸려면 그 결정을 먼저 다시 열어야 한다.
    ⚠️ arm64 를 벗어나면 `1-6`(이미지 arm64 멀티아치)의 네이티브 빌드 전제가 깨진다.
  EOT
  type        = string
  default     = "t4g.xlarge"
}

variable "ci_root_volume_size" {
  description = <<-EOT
    루트 볼륨(GiB). 🔴 **정본에 값이 없다** — C-52 가 "GitLab EC2 (🟡 미검증)" 로 남긴 칸이다.
    30 을 고른 근거 = OS + Omnibus 패키지만 얹는다(형상·데이터는 전부 `/dev/sdb`).
    🔴 **작게 두는 것이 의도다** — 루트가 차면 SSM 에이전트까지 죽어 **들어가서 지울 수도 없다**.
    데이터를 가른 이유가 그것이고(`ec2_ci.tf` 주석), 루트를 키우는 것은 그 방어를 흐린다.
  EOT
  type        = number
  default     = 30
}

variable "ci_docker_volume_size" {
  description = <<-EOT
    docker 볼륨(GiB) — `/dev/sdb` → `/var/lib/docker`. 🟢 **버려도 되는 볼륨**(`prevent_destroy` 없음).
    🔴 **정본에 값이 없다.** 60 을 고른 근거 = 여기가 **상한 없이 늘어나는 유일한 곳**이고
    **arm64 + amd64 두 아치**의 이미지·빌드 캐시가 얹힌다(멀티아치는 C-3 의 x86 DR 때문에 강제 · C-63).
    18개 서비스 × 2아치 + 베이스 + 캐시를 감당하는 크기다. 월 약 $4.8.
    ⚠️ `.gitlab-ci.yml` 에 주기적 `docker system prune` 을 넣는 것이 이 볼륨의 짝이다(A-29).
  EOT
  type        = number
  default     = 60
}

variable "ci_data_volume_size" {
  description = <<-EOT
    데이터 볼륨(GiB) — `/dev/sdc`. GitLab 저장소·artifact · SonarQube DB · 스왑(C-38).
    🔴 **잃으면 복구 불가**라 `prevent_destroy` 가 걸려 있다.
    🔴 **정본에 값이 없다.** 50 을 고른 근거 = 온프렘 실측(`JENKINS_HOME` 4.3G · SonarQube 1.65G)
    + git 저장소·artifact 여유 + 스왑 8GiB. 월 약 $4.
    🟢 `gp3` 는 무중단 확장이 되므로 **작게 시작해도 되돌릴 수 있다.**
  EOT
  type        = number
  default     = 50
}

variable "ci_imds_hop_limit" {
  description = <<-EOT
    IMDS hop limit. 🟢 **`1` = 정본 A-28 값** — 컨테이너는 IMDS 에 닿지 못한다.
    한때 `2` 를 검토했다(C-61① privileged DinD 의 빌드 잡이 컨테이너 안에서 ECR 로그인을 한다).
    🔴 **사용자 판단(2026-08-13) = 정석대로** ⇒ 잡은 IMDS 대신 **OIDC 로 자기 롤을 받는다**
    (`iam_ci_oidc.tf` · A-50)므로 `1` 이 유지된다. 🟢 게다가 인스턴스 롤에서 ECR 을 뺐으므로
    **컨테이너가 IMDS 에 닿아도 가져갈 것이 없다** — 잠근 것보다 강한 경계다.
  EOT
  type        = number
  default     = 1
}

# ── A-50 CI 잡 OIDC (2단 apply — GitLab 이 뜬 뒤) ─────────────────────────────
variable "ci_oidc_issuer_url" {
  description = <<-EOT
    GitLab 의 OIDC 발급자 URL(예: `https://gitlab.mealbong.cloud`).
    🔴 **비어 있으면 OIDC 리소스를 전부 건너뛴다** — GitLab 이 떠서 discovery 가 응답해야
    만들 수 있으므로 2단 apply 다(A0 의 `create_node_group` 과 같은 패턴).
    🔴 **선행 = Cloudflare Access 에 경로 2개 Bypass**(`/.well-known/openid-configuration` ·
    `/oauth/discovery/keys`). AWS STS 가 **익명으로** 읽어야 한다. 🟢 둘 다 공개키·메타데이터뿐이라
    노출로 잃는 것이 없고, C-61⑤ 가 기각한 **git 경로** Bypass 와는 성질이 다르다.
  EOT
  type        = string
  default     = ""
}

variable "ci_oidc_audience" {
  description = <<-EOT
    OIDC 토큰의 `aud`. `.gitlab-ci.yml` 의 `id_tokens.<NAME>.aud` 와 **정확히 같아야** 한다.
    🔴 고정하는 이유 = **토큰 재사용 방지**. 안 좁히면 다른 신뢰 당사자용으로 발급된 토큰이
    우리 롤에도 통할 수 있다.
  EOT
  type        = string
  default     = "sts.amazonaws.com"
}

variable "ci_oidc_project_path" {
  description = "OIDC `sub` 에 리터럴로 박는 프로젝트 경로. 🔴 와일드카드를 쓰지 않는다 — 폭발 반경을 이 레포 하나로 묶는 값이다."
  type        = string
  default     = "happyInit/food-budget-app"
}

variable "ci_oidc_allowed_refs" {
  description = <<-EOT
    이 롤을 빌릴 수 있는 브랜치 목록. 🔴 **`main` 만 두는 것이 의도다** — ECR push 는
    `Jenkinsfile` 의 CD 가드(`branch 'main'` + not changeRequest)와 같은 경계여야 한다.
    ⚠️ 여기에 `*` 를 넣으면 **아무 브랜치를 만든 사람이 ECR 에 push** 할 수 있다.

    🔴 **A-29 개발 기간 한정 예외**(2026-08-13 · 사용자 확정) — 파이프라인을 ECR push 까지
    실증하려면 잡이 롤을 빌려야 하는데 이 목록이 `main` 뿐이면 기능 브랜치에서 못 돈다.
    ⇒ 개발 브랜치 **한 개**를 한시로 더한다(`terraform.tfvars.example` 참조).
    🔴 **A0.5 완료 판정(ECR 18리포 arm64) 직후 `["main"]` 으로 되돌린다** — 되돌리는 것까지가
    이 예외의 일부다. 아래 validation 이 `*` 는 애초에 막지만, 브랜치 추가는 막지 못한다.
  EOT
  type        = list(string)
  default     = ["main"]

  # 🔴 위 경고를 **기계로 강제한다** — 원칙을 주석으로만 두면 샌다(C-83 의 검증 게이트와 같은 태도).
  #    `*` 하나면 이 GitLab 에 브랜치를 만들 수 있는 누구나 ECR 에 push 할 수 있다.
  validation {
    condition     = length(var.ci_oidc_allowed_refs) > 0 && !contains(var.ci_oidc_allowed_refs, "*")
    error_message = "ci_oidc_allowed_refs 는 비울 수 없고 `*` 를 포함할 수 없다 — 브랜치를 명시할 것."
  }
}

# ── EKS ───────────────────────────────────────────────────────────────────────
variable "cluster_name" {
  description = <<-EOT
    EKS 클러스터 이름. 🔴 **정본에 값이 없다** — 명명 규칙(CLAUDE.md: 신규는 전부 `mp-`)만 따랐다.
    ECR 리포·IRSA 롤 이름과 달리 이 값은 **나중에 바꾸면 클러스터를 다시 만들어야 한다**.
  EOT
  type        = string
  default     = "mp-eks"
}

variable "cluster_version" {
  description = <<-EOT
    🔴 **정본 미확인 ⑩ 이다** — 체크리스트가 *"EKS 버전: 1.34 표준지원 2026-12-02 종료 ↔
    Cilium 1.19.6 상한 1.34 ↔ CLAUDE.md '1.35 금지' 락 = 3자 충돌 해소 필요"* 〔#27〕로 남겨 뒀다.
    기본값 `1.34` 는 **새 결정이 아니라 기존 락 두 개의 교집합**이다(Cilium e2e 상한 = 1.34 ·
    CLAUDE.md 가 1.35 를 금지). ⇒ #27 이 닫히면 이 변수를 고친다. **여기서 올리지 말 것.**
  EOT
  type        = string
  default     = "1.34"
}

variable "cluster_public_access_cidrs" {
  description = <<-EOT
    EKS 공개 엔드포인트 허용 대역 (C-80). 기본값 전체 개방은 **의도된 선택**이다 —
    C-80 이 *"비대화형 접근이 필수"* 로 확정했고 팀원 회선이 고정 IP 가 아니다.
    🟢 인증은 IAM 이라 대역 개방이 곧 접근 허용이 아니다(C-24 Access Entry 없이는 아무것도 못 한다).
    🔴 좁히려면 **팀원 전원의 고정 IP 를 먼저 확보**해야 하고, 못 하면 `kubectl` 이 죽는다.
  EOT
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "cluster_log_types" {
  description = <<-EOT
    컨트롤플레인 로그 → CloudWatch (C-66 · `1-26` 해소). 🔴 **비용이 있다 — 월 약 $59 추정**이고
    C-66 이 *"1개월 실측 후 재판정"* 으로 남겼다. `audit` 을 빼면 그 추정이 대부분 사라지지만
    S4 의 탐지 설계가 audit 를 전제로 한다.

    🔴 **`audit` 하나가 정답이다 — 종전 기본값 `["api","audit","authenticator"]` 는 결정과
       어긋나 있었다**(2026-08-16 실측으로 발견 · 라이브 클러스터가 3종을 켜고 있었다).
       C-66 본문이 *"❌ `api`·`authenticator`·`controllerManager`·`scheduler` **미채택**(볼륨 폭증)"*
       이라고 명시적으로 기각한다. 셋을 켜면 C-66 이 남긴 "월 $59 추정"의 전제가 달라져
       **미결 ㉒(1개월 실측 후 재판정)를 판단할 수 없게 된다** — 무엇을 재고 있는지가 흐려진다.
    🔵 되돌리기는 스위치 하나다(in-place 갱신 · 클러스터 재생성 없음). 조사 목적으로 잠깐
       넓혀야 하면 이 변수만 바꾼다.
  EOT
  type        = list(string)
  default     = ["audit"]
}

variable "secrets_kms_key_arn" {
  description = <<-EOT
    EKS Secrets 봉투암호화(envelope encryption) CMK. **기본값 null = 사용 안 함.**
    🔴 미확정 ⑰(CMK $1/키 vs AWS 관리형 $0)이 열려 있어 여기서 정하지 않는다.
    온프렘은 etcd at-rest 암호화(aescbc)가 켜져 있으므로 **이 값이 null 이면 그만큼은 후퇴**다.
    🟢 기존 클러스터에도 나중에 켤 수 있다(단 되돌릴 수 없다) ⇒ 지금 미루는 쪽이 가역적이다.
  EOT
  type        = string
  default     = null
}

# ── 노드그룹 (C-45 · C-29) ─────────────────────────────────────────────────────
variable "node_instance_type" {
  description = "🔴 `m7g` = Graviton/arm64 (C-29·C-45). 이미지가 arm64 여야 한다(`1-6`) — amd64 단일이면 전면 CrashLoop 다."
  type        = string
  default     = "m7g.xlarge"
}

variable "node_desired_size" {
  description = <<-EOT
    🔴 **2 로 시작한다 (C-45)** — C-43 의 "3대" 를 정정한 값이다.
    실측 6.22 vCPU / 18.86 GiB(0-27 적용 후) vs 2대 allocatable 7.84 / 29.1 → CPU 79% · 메모리 63%.
    ⚠️ **`0-27`(CPU 요청 재조정)이 전제** — 미적용이면 104% 로 파드가 안 뜬다.
  EOT
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = <<-EOT
    MNG(층1) 상한. 🔴 **버스트의 정본은 Karpenter(층2)다** — A-12 채택 확정(2026-08-13)으로
    부하·배포 시 확장은 NodePool 이 맡는다(C-45 · A-19 · 평시 0대).
    그럼에도 MNG 상한을 2 보다 크게 두는 이유 = **Karpenter 자신이 MNG 위에서 돈다.**
    Karpenter 컨트롤러가 없으면 층2 가 안 뜨므로, 층1 이 자기 파드를 재배치할 여유는 있어야 한다.
    🔴 **평시 대수를 늘리는 값이 아니다**(desired = 2). Blue-Green promote 창의 실제 버스트 폭은
    `A-35` 가 실측해서 NodePool `limits` 로 정한다 — 이 값이 아니다.
  EOT
  type        = number
  default     = 4
}

variable "node_root_volume_gib" {
  description = "노드 루트 EBS (C-16 — 종전 계획서에서 통째로 누락됐던 항목). 상한 없는 emptyDir 160개가 여기 얹힌다(0-8d)."
  type        = number
  default     = 60
}

variable "create_node_group" {
  description = <<-EOT
    관리형 노드그룹(층1)을 만들 것인가. 🔴 **최초 구축 때만 `false` 로 한 번 돈다** — README "2단 apply".

    왜 변수인가 = C-82 로 CNI 가 없으므로 **Cilium 보다 먼저 노드를 만들면 안 된다**
    (`NodeCreationFailure` 로 약 20분 뒤 실패). 그 순서를 강제하는 방법이 둘인데:
      ❌ `terraform apply -target=aws_eks_cluster.main`
         → **`-target` 은 의존성만 끌어오므로 네트워크·IRSA·SQS·SG 가 전부 빠진다.**
           그러면 `output "ansible_extra_vars_json"` 이 `aws_security_group.node` 등을
           참조하지 못해 **Ansible 에 넘길 변수 묶음 자체를 뽑을 수 없다.**
           (2026-08-13 리허설에서 실측 — 1단 타깃이 8개로 좁혀졌다.
            Terraform 도 `-target` 을 *"not for routine use"* 라고 경고한다.)
      🟢 이 토글
         → 노드그룹 **하나만** 빠지고 나머지 117개는 다 만들어져 output 이 온전하다.

    ⚠️ `false` 로 두면 노드가 0대이므로 파드는 전부 Pending 이다. **그게 1단의 정상 상태다.**
    🔴 2단 이후로는 손대지 말 것 — `true` → `false` 는 **노드그룹 파괴**다(= 클러스터 전체 정지).
  EOT
  type        = bool
  default     = true
}

# ── 사람 접근 (C-24) ──────────────────────────────────────────────────────────
variable "cluster_admin_principals" {
  description = <<-EOT
    `mp:admin` 그룹으로 Access Entry 를 만들 IAM 주체 ARN 목록 (C-24 = Access Entry
    `kubernetesGroups` + 우리 커스텀 ClusterRole. **관리형 access policy 미채택**).
    🔴 비어 있으면 **아무도 클러스터에 들어갈 수 없다** — 클러스터를 만든 주체조차
    `authentication_mode = "API"` 에서는 자동 권한이 없다(구 aws-auth 시절과 다르다).
    🔴 여기 넣는 것은 **그룹 매핑뿐**이다. 실제 권한은 config/Ansible 이 만드는 ClusterRole 이 준다.
  EOT
  type        = list(string)
  default     = []
}

variable "cluster_viewer_principals" {
  description = "`mp:viewer` 그룹 Access Entry (읽기 전용 · 예: `mp-agent-ro`). 권한 실체는 커스텀 ClusterRole."
  type        = list(string)
  default     = []
}

variable "cluster_bootstrap_admin_principals" {
  description = <<-EOT
    🔴 **부트스트랩 전용** — `AmazonEKSClusterAdminPolicy` 를 붙일 주체. **여기에 팀원을 넣지 말 것.**

    왜 필요한가 = `bootstrap_cluster_creator_admin_permissions = false`(C-24) 이면 클러스터를
    만든 주체조차 인가가 0 이고, `mp:admin` 그룹의 실권한은 Ansible `eks_rbac` 가 만드는
    ClusterRole 이 정한다. **그런데 ClusterRole 을 만드는 것 자체가 cluster-admin 이다.**
    ⇒ 넣지 않으면 Cilium 설치부터 막힌다(2026-08-13 실측 · 결함 #11 — `eks_access.tf` 주석).

    🔴 **`cluster_admin_principals` 와 섞지 말 것.** 그쪽은 *사람*이고 커스텀 ClusterRole 로 간다
    (verb 단위 PoLP · 장수 admin 토큰 0 = `0-14`·#568 의 연장). 여기는 **플랫폼 운영 주체 1개**다.
    같은 ARN 을 양쪽에 넣어야 동작한다(Access Entry 가 먼저 있어야 정책을 붙일 수 있다).
  EOT
  type        = list(string)
  default     = []
}

# ── ECR (A-46 · A-2) ─────────────────────────────────────────────────────────
variable "ecr_keep_last_images" {
  description = "리포당 보존 이미지 수 (A-2 lifecycle). 🔴 이관 후 롤백 폭을 정하는 값이다 — 너무 작게 잡으면 되돌릴 태그가 없다."
  type        = number
  default     = 20
}

variable "ecr_untagged_expire_days" {
  description = "태그 없는 레이어 만료일. 멀티아치 빌드는 매니페스트 리스트만 태그되고 아치별 이미지가 무태그로 남으므로 0 으로 두면 안 된다."
  type        = number
  default     = 14
}

# ── 버킷·모델 ARN (기존 리소스 참조 — 이 스택이 만들지 않는다) ─────────────────
variable "backup_bucket" {
  description = <<-EOT
    barman·비밀·etcd 백업 버킷 (C-18 · 이미 **살아 있다**). 🔴 이 스택이 만들지 않는다 —
    라이브 데이터가 든 버킷을 Terraform 에 편입하면 `destroy` 한 번이 백업을 통째로 지운다.
    IRSA 정책이 ARN 으로만 참조한다.
  EOT
  type        = string
  default     = "mp-backup-ap2"
}

variable "pg_dump_bucket" {
  description = "논리 덤프 버킷 (C-69 · 2트랙 중 논리 쪽). 🔴 barman 버킷과 **분리**가 결정의 요지다 — 장애 도메인을 가른다."
  type        = string
  default     = "mp-pg-dump-ap2"
}

variable "bedrock_model_arns" {
  description = <<-EOT
    `A-47` 의 *"모델 ARN 2개 한정"*. 정본이 모델을 **`nova-micro`** 로 적고 있고(§D4-a 흐름도 ·
    C-84), 개인정보 리전 항목이 `apac.amazon.nova-micro-v1:0`(**교차리전 추론 프로파일**)로 적는다.
    🔴 교차리전 프로파일은 **프로파일 ARN + 실제 추론이 일어나는 리전의 파운데이션 모델 ARN** 을
    함께 허용해야 한다 — 그것이 "2개" 다. `apac.` 프로파일이 도는 리전이 ap-northeast-2 하나가
    아니면 ARN 이 더 필요하다. ⚠️ **A5(파이프라인) 착수 때 실제 호출로 확인할 것** — 부족하면
    `AccessDeniedException` 으로 명확히 실패한다(조용히 실패하지 않는다).
  EOT
  type        = list(string)
  default = [
    "arn:aws:bedrock:ap-northeast-2:*:inference-profile/apac.amazon.nova-micro-v1:0",
    "arn:aws:bedrock:ap-northeast-2::foundation-model/amazon.nova-micro-v1:0",
  ]
}

variable "interface_endpoints" {
  description = <<-EOT
    VPC Interface 엔드포인트 목록. 기본값 = **C-56 이 확정한 3종 그대로**(`sqs`·`secretsmanager`·`sts`).
    ⟳ **2026-08-13 정정** — 여기 있던 *"`secretsmanager` 는 소비자가 없다"* 는 서술은 **내 오독**이었다
    (결함 #24 · 근거는 `locals.tf` 의 같은 지점 주석). **C-36 이 비밀 백엔드를 Secrets Manager 로
    확정**했으므로 이 엔드포인트의 소비자는 **ESO** 이고, 3종은 처음부터 정합했다.
    🟢 그때 "받아들인 위험" 으로 적어 둔 것(ESO 호출이 NAT 를 탄다)도 **존재하지 않는다.**
    🔴 남는 진짜 함정은 하나 = **`ssm` 은 여기 없어도 된다**(우리 비밀 경로가 아니다). 단
    Karpenter 가 AMI 조회로 `ssm:GetParameter` 를 쓰는데(`karpenter.tf`) 그건 **공개 파라미터**라
    NAT 로 나가도 무해하다 — 노드 증설 지연은 AZ 단절 국면에서 이미 다른 이유로 발생한다.
  EOT
  type        = list(string)
  default     = ["sqs", "secretsmanager", "sts"]
}

# ── 공개 진입 (C-60 · A2 후반) ────────────────────────────────────────────────
variable "public_domain" {
  description = <<-EOT
    사용자 트래픽이 들어오는 최종 호스트. 🔴 **A3 컷오버 전까지 이 이름은 온프렘을 가리킨다**
    (Cloudflare 주황 + cloudflared 터널). ACM 인증서에 미리 넣어 두는 이유는 `1-54` 의
    컷오버 창이 5~10분이라 그 안에 발급·검증을 끼워 넣을 수 없기 때문이다.
  EOT
  type        = string
  default     = "app.mealbong.cloud"
}

variable "verify_domain" {
  description = <<-EOT
    A2 내부 검증용 호스트 (C-78 = *"앱 12종 + `aws.mealbong.cloud`(회색→ALB) 내부 검증"*).
    🔴 **와일드카드 레코드가 이 이름을 이미 가로채고 있다**(실측) — `*.mealbong.cloud` 가
    회색으로 사설주소를 가리켜 NXDOMAIN 이 아니라 **타임아웃**으로 보인다.
    ⇒ 이 이름의 A/CNAME 을 **명시적으로** 만들어야 와일드카드보다 우선한다.
    🔴 **A-40 이 짝이다** — 카카오·구글 OAuth 콘솔에 이 호스트를 redirect URI 로 등록하지 않으면
    다른 건 다 되는데 **로그인만** 막힌다.
  EOT
  type        = string
  default     = "aws.mealbong.cloud"
}

variable "waf_rate_limit_per_5min" {
  description = <<-EOT
    IP 당 5분 요청 상한 (`1-49`). 초과분을 **차단**한다.

    🔴 **근거** — 실트래픽 **0.959 req/s**(정본 실측)이면 전 트래픽이 한 IP 에서 와도
    5분에 288건이다. 2000 은 그 **약 7배**이고, 브라우저 한 명의 콜드 방문(443KB · 자산 수십 개)
    이 5분에 2000건을 넘길 일은 없다. ⇒ 정상 사용자를 막지 않으면서 증폭 공격에는 선다.

    🔴 **`1-49` 가 못박은 조건 = k6 부하시험이 자기 자신을 차단하지 않게 할 것.**
    지금 k6 는 온프렘 `.14` 를 직타하므로 이 룰 밖이지만, EKS 로 부하를 걸 때는
    ⓐ 이 값을 한시로 올리거나 ⓑ 시험 출발지 IP 를 예외 룰로 빼야 한다.
    **올린 뒤 되돌리는 것까지가 그 작업의 일부다.**

    ⚠️ 이 값을 내리는 것보다 **왜 내리는지**가 중요하다 — 적응형이 아니라서, 낮추면
    정상 트래픽이 조용히 502/403 을 받기 시작한다(C-75).
  EOT
  type        = number
  default     = 2000

  validation {
    condition     = var.waf_rate_limit_per_5min >= 100
    error_message = "AWS WAF 레이트룰의 하한은 100 이다."
  }
}

# ── ElastiCache (C-14 · A1) ───────────────────────────────────────────────────
variable "cache_node_type" {
  description = <<-EOT
    ElastiCache 노드 타입 (C-14). 🔴 **`t4g` = Graviton** — C-29 와 같은 이유로 arm 이 싸다.
    2노드 합계 **월 $28.03**(실측 단가 기준. D10 $857 의 3.3%) ⇒ **비용은 지배 요인이 아니다.**
    올리기 전에 볼 것 = 온프렘 Redis 실사용은 **6 ops/s** 였다(`mp-redis-pgsync` 383 과 혼동 금지).
  EOT
  type        = string
  default     = "cache.t4g.micro"
}

variable "cache_engine_version" {
  description = <<-EOT
    Valkey 엔진 버전. 온프렘이 **Redis 7.2.3** 이고 Valkey 는 Redis **7.2.4** 에서 갈라진
    포크라 프로토콜·코어 명령이 호환된다 — 우리가 쓰는 명령은 전부 코어다
    (GET·SET·EXPIRE·TTL·DELETE·RPUSH·pipeline).
    🔴 올릴 때 확인할 것 = 사이트별 엔진이 이미 갈려 있다(온프렘 Redis / AWS Valkey).
  EOT
  type        = string
  default     = "7.2"
}

# ══ 보안 감사·알림 (C-65 · C-66 · C-68) ═══════════════════════════════════════

variable "cloudtrail_bucket" {
  description = <<-EOT
    CloudTrail 버킷 이름 (C-68 신설 3개 중 하나).
    🔴 이 버킷만 **Object Lock COMPLIANCE 90일 + 버전관리**다 — 목적이 *"아무도 못 지운다"* 하나뿐이라
       다른 버킷과 설정이 다르다. COMPLIANCE 는 **루트도 못 푼다**(GOVERNANCE 는 우회 가능해서 무의미).
    🔴 **Object Lock 은 버킷 생성 시에만 켤 수 있다.** 이름을 바꾸면 새 버킷이 생기고 옛 감사기록은
       따라오지 않는다 — 이름 변경은 사실상 감사 이력 단절이다.
  EOT
  type        = string
  default     = "mp-cloudtrail-ap2"
}

variable "cloudtrail_name" {
  description = <<-EOT
    CloudTrail 트레일 이름. 버킷 정책의 `aws:SourceArn` 조건이 이 값으로 ARN 을 조립하므로
    🔴 **여기를 바꾸면 버킷 정책도 같이 바뀌어야 한다**(안 그러면 트레일이 쓰기 거부된다).
    터라폼이 같은 변수를 양쪽에서 참조하므로 자동으로 맞는다 — 리터럴로 쓰지 말 것.
  EOT
  type        = string
  default     = "mp-trail"
}

variable "security_slack_secret_name" {
  description = <<-EOT
    `#mp-security` 웹훅이 든 Secrets Manager 시크릿 이름 (C-65).
    🔴 **값은 터라폼이 만들지 않는다** — `aws_secretsmanager_secret_version` 을 쓰면 웹훅이
       **tfstate 에 평문**으로 들어가고 state 버킷은 버전관리조차 없다(`infra/terraform/aws/iam.tf`
       의 액세스 키 머리말과 같은 판단). 주입은 수동 1회:
         aws secretsmanager create-secret --name mp/prod/security-slack-webhook \
           --secret-string file://<웹훅파일>
    🔵 Lambda 는 **호출마다 읽는다** ⇒ 웹훅을 교체해도 재배포가 필요 없다.
  EOT
  type        = string
  default     = "mp/prod/security-slack-webhook"
}
