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

# 🔴 노드 롤의 Access Entry 는 **만들지 않는다** — 관리형 노드그룹은
#    `authentication_mode = "API"` 에서 EKS 가 `EC2_LINUX` 타입 엔트리를 자동으로 만든다.
#    여기서 또 만들면 중복으로 apply 가 실패한다.
