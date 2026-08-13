# 사람 신원 = EKS Access Entry + `kubernetesGroups` (C-24 · C-35 로 IAM 단독 확정)
#
# 🔴 **관리형 access policy(`AmazonEKSClusterAdminPolicy` 등)를 붙이지 않는다** — C-24 가
#    *"우리 커스텀 ClusterRole"* 로 확정했다. 온프렘에서 verb 단위 커스텀 롤을 만들어
#    `mp-*-edit` 4→0 · admin 장수 토큰 2→0 을 실증한 것(`0-14` · #568)의 연장이다.
#    ⇒ 여기서 하는 일은 **IAM 주체 → K8s 그룹 매핑뿐**이고, 그 그룹에 무엇을 허용하는지는
#      Ansible `eks.yml` 이 만드는 ClusterRole/ClusterRoleBinding 이 정한다.
#
# 🔴 **`0-14` 에서 나온 교훈을 여기서 반복하지 말 것** — 검증 도구가 틀렸던 사건(#587):
#    `kubectl auth can-i create serviceaccounts/token` 의 `token` 이 서브리소스가 아니라
#    **리소스 이름**으로 해석돼, EKS 에서 IAM 롤로 가는 가장 중요한 다리가 한 번도
#    실제로 검사된 적이 없었다. ⇒ 접근 검증은 `--subresource` 플래그로 한다.

resource "aws_eks_access_entry" "admin" {
  for_each = toset(var.cluster_admin_principals)

  cluster_name  = aws_eks_cluster.main.name
  principal_arn = each.value
  type          = "STANDARD"

  # 그룹 이름은 온프렘 RBAC 과 같은 어휘를 쓴다(`mp-k8s RBAC Phase1` 라이브 · #449·#454).
  kubernetes_groups = ["mp:admin"]
}

resource "aws_eks_access_entry" "viewer" {
  for_each = toset(var.cluster_viewer_principals)

  cluster_name      = aws_eks_cluster.main.name
  principal_arn     = each.value
  type              = "STANDARD"
  kubernetes_groups = ["mp:viewer"]
}

# ── 🔴 부트스트랩 관리자 — C-24 의 예외 하나 (2026-08-13 실행에서 강제로 드러났다) ────────
#
# 결함 #11. 위 매핑만으로는 **아무것도 설치할 수 없다.** 실측 에러:
#
#   Error: list: failed to list: secrets is forbidden: User
#   "arn:aws:iam::…:user/mp-platform" cannot list resource "secrets"
#   in API group "" in the namespace "kube-system"
#
# 🔴 **순환 의존이다.** `bootstrap_cluster_creator_admin_permissions = false` 라 클러스터를
#    만든 주체조차 권한이 없고, `mp:admin` 그룹에 무엇을 허용하는지는 Ansible `eks_rbac` 가
#    만드는 ClusterRole 이 정한다. 그런데 **ClusterRole 을 만드는 것 자체가 cluster-admin 권한**이다.
#    ⇒ 인증은 되지만 인가가 0 인 상태로 잠긴다. Cilium 설치(= helm 이 kube-system 의
#      릴리스 시크릿을 읽는다)가 첫 번째 희생자다.
#
# 🔴 **C-24 를 뒤집는 것이 아니다.** C-24 가 막은 것은 *"사람에게 관리형 정책으로 권한을 주는 것"*
#    이고(verb 단위 커스텀 롤 · 장수 admin 토큰 0 — `0-14`·#568), 여기 것은
#    **부트스트랩 주체 1개**다. 팀원 4명은 그대로 `mp:admin` 커스텀 ClusterRole 로 간다.
#    ⇒ `cluster_admin_principals`(사람)과 **변수를 따로 둔 이유**가 이것이다. 섞지 말 것.
#
# 기각한 대안 = `bootstrap_cluster_creator_admin_permissions = true`
#   ① 그 필드는 **ForceNew** 다 — 이미 만든 클러스터를 **파괴하고 다시 만든다**(8분 + 116개 재배선).
#   ② 권한이 코드에 안 보인다(누가 admin 인지 state 를 캐야 안다). 이 리소스는 한 줄로 보인다.
#
# 🟢 **영구히 둔다 — 임시 조치가 아니다.** 커스텀 ClusterRole 이 깨졌을 때 되돌아갈 문이
#    없으면 클러스터에서 영구히 잠긴다. 온프렘에서 RBAC Phase1 을 넣고도
#    `admin.conf` 를 살려 둔 것과 같은 판단이다([[mp-k8s-rbac-plan]] — Phase2 컷오버는 개발 끝물).
#    좁히는 방법 = 이 변수를 비우는 것이고, 그때 `mp:admin` ClusterRole 이 이미 살아 있어야 한다.
resource "aws_eks_access_policy_association" "bootstrap_admin" {
  for_each = toset(var.cluster_bootstrap_admin_principals)

  cluster_name  = aws_eks_cluster.main.name
  principal_arn = each.value
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  # 🔴 Access Entry 가 먼저 있어야 정책을 붙일 수 있다. 같은 ARN 이 위 `admin` 엔트리에
  #    들어 있어야 하며, 없으면 `ResourceNotFoundException` 이 난다.
  depends_on = [aws_eks_access_entry.admin]
}

# 🔴 노드 롤의 Access Entry 는 **만들지 않는다** — 관리형 노드그룹은
#    `authentication_mode = "API"` 에서 EKS 가 `EC2_LINUX` 타입 엔트리를 자동으로 만든다.
#    여기서 또 만들면 중복으로 apply 가 실패한다.
