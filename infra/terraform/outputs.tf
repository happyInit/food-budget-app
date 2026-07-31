output "vm_ips" {
  description = "프로비저닝된 VM → IP"
  value       = { for k, v in var.vms : v.name => v.ip }
}

output "ssh_targets" {
  description = "SSH 접속 타깃"
  value       = { for k, v in var.vms : v.name => "${var.ci_user}@${v.ip}" }
}

output "k8s_node_ips" {
  description = "K8s 노드(호스트 B) → IP"
  value       = { for k, v in var.k8s_nodes : k => v.ip }
}

output "k8s_ssh_targets" {
  description = "K8s 노드 SSH 접속 타깃 (Ansible 인벤토리에 넣을 값)"
  value       = { for k, v in var.k8s_nodes : k => "${var.ci_user}@${v.ip}" }
}
