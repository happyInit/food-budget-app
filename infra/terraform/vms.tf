# 내부 전용(host-only) 브리지 — 물리 포트 없음 = 외부와 격리, VM 간 사설망.
# gateway 미지정: 이 대역은 기본 라우트를 만들지 않음(외부 나가는 경로는 vmbr0 유지).
resource "proxmox_network_linux_bridge" "internal" {
  node_name = var.node_name
  name      = var.internal_bridge
  address   = var.internal_bridge_address # 호스트(pve) 측 IP = 10.10.10.1/24
  comment   = "food-budget internal host-only net (terraform)"
  autostart = true
  # ports 미지정 = 물리 업링크 없음 → host-only
}

resource "proxmox_virtual_environment_vm" "fb" {
  for_each = var.vms

  # 은퇴한 VM 은 tfvars 에서 started=false 로 선언한다(파괴는 별도 판단).
  started = each.value.started

  # 내부 브리지가 먼저 존재해야 net1이 유효 (bridge 참조는 문자열이라 명시적 의존)
  depends_on = [proxmox_network_linux_bridge.internal]

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
    bridge = var.bridge # net0 — 외부/관리망 (vmbr0), 기본 gateway
  }

  network_device {
    bridge = var.internal_bridge # net1 — 내부 전용망 (vmbr1), gateway 없음
  }

  initialization {
    datastore_id = var.datastore
    # ip_config 순서 = network_device 순서 (net0 → net1)
    ip_config {
      ipv4 {
        address = "${each.value.ip}/24"
        gateway = var.gateway
      }
    }
    ip_config {
      ipv4 {
        address = "${each.value.internal_ip}/24"
        # gateway 없음: 내부망은 기본 라우트를 만들지 않음(단절 방지)
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
