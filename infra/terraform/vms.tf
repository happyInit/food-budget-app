resource "proxmox_virtual_environment_vm" "fb" {
  for_each = var.vms

  name      = each.value.name
  node_name = var.node_name
  vm_id     = each.value.vmid
  tags      = ["food-budget", "terraform"]

  clone {
    vm_id = var.template_vmid
    full  = true
  }

  agent {
    enabled = true # qemu-guest-agent (템플릿에 설치돼 있어야 IP 리포팅됨)
  }

  cpu {
    cores = each.value.cores
    type  = "host"
  }

  # 템플릿(9001)에서 물려받은 설정 — import 정합용
  operating_system {
    type = "l26"
  }

  serial_device {
    device = "socket"
  }

  memory {
    dedicated = each.value.memory
    floating  = each.value.balloon_floor # 0=벌룬 off(VM1) / <dedicated=벌룬 on(VM2~4)
  }

  disk {
    datastore_id = var.datastore
    interface    = "scsi0" # OS 디스크 (템플릿 클론)
    size         = each.value.disk_gb
  }

  disk {
    datastore_id = var.datastore
    interface    = "scsi1" # /var/lib/docker 전용 (OS와 분리)
    size         = each.value.docker_disk_gb
  }

  network_device {
    bridge = var.bridge
  }

  initialization {
    datastore_id = var.datastore
    ip_config {
      ipv4 {
        address = "${each.value.ip}/24"
        gateway = var.gateway
      }
    }
    dns {
      servers = var.dns_servers
    }
    user_account {
      username = var.ci_user
      keys     = [trimspace(var.ssh_public_key)]
    }
  }

  # cloned VM을 import한 뒤 clone 블록이 replacement을 강제하는 것 방지
  lifecycle {
    ignore_changes = [clone]
  }
}
