# ─────────────────────────────────────────────────────────────────────────────
# K8s 노드 VM — 호스트 B (Proxmox `k8s1` @ 192.168.0.22 · 스탠드얼론)
#
# P0 = B 에만 3노드(master 1 + worker 2). 호스트 A 쪽 워커는 P1·P4 램프에서 추가한다
# (A 의 RAM 이 현행 프로덕션 VM 과 워커를 동시에 수용하지 못함).
#   RAM·램프 근거 = docs/mp_k8s_infra_migration_plan.md §2.2
#
# A 쪽 리소스(proxmox_virtual_environment_vm.fb)와 완전히 분리된다:
#   provider = proxmox.b (별개 API 엔드포인트) · 내부 브리지(vmbr1) 미사용 · NIC 1장
# ─────────────────────────────────────────────────────────────────────────────
resource "proxmox_virtual_environment_vm" "k8s" {
  provider = proxmox.b
  for_each = var.k8s_nodes

  # map 키 = VM 이름 = 게스트 hostname = K8s 노드명 (PVE cloud-init 이 VM 이름을 hostname 으로 주입)
  name      = each.key
  node_name = var.node_name_b
  vm_id     = each.value.vmid
  tags      = ["k8s", "terraform"]

  clone {
    vm_id = var.template_vmid # 9002 (B 에 있는 사본) — qemu-guest-agent 사전설치본
    full  = true
  }

  agent {
    enabled = true
  }

  cpu {
    cores = each.value.cores
    type  = "host"
  }

  operating_system {
    type = "l26"
  }

  serial_device {
    device = "socket" # 부팅 실패 시 콘솔 진입 경로 (initrd 파손 사고 대비)
  }

  # 🔴 벌룬 OFF (floating = 0 → PVE balloon=0). kubelet 은 기동 시 노드 capacity 를
  # 캐시하므로, 벌룬이 나중에 메모리를 회수하면 스케줄러가 존재하지 않는 메모리를
  # 배분한다 → 정상적인 축출(eviction) 대신 OOM 이 난다.
  memory {
    dedicated = each.value.memory
    floating  = 0
  }

  # OS 디스크 = kubelet 의 nodefs (/var/lib/kubelet·emptyDir·/var/log/pods, master 는 +/var/lib/etcd)
  disk {
    datastore_id = var.datastore
    interface    = "scsi0"
    size         = each.value.disk_gb
    discard      = "on"
    ssd          = true
  }

  # containerd 전용 = kubelet 의 imagefs (/var/lib/containerd — 이미지·스냅샷·컨테이너 쓰기레이어).
  # 분리 이유: 이미지가 불어나도 nodefs 를 말려 노드를 죽이지 않고 imagefs 임계로 이미지 GC 가 돈다.
  disk {
    datastore_id = var.datastore
    interface    = "scsi1"
    size         = each.value.containerd_disk_gb
    discard      = "on" # 씬풀 블록 반환 (local-lvm 오버프로비저닝 상태라 필수)
    ssd          = true # 게스트에 non-rotational 로 보고 (물리 = SATA SSD)
  }

  # OpenEBS LVM LocalPV 용 raw 디스크 (워커만 · storage_disk_gb = 0 이면 미부착).
  # ⚠️ 이 디스크는 mkfs·mount 하지 않는다 — Ansible 이 pvcreate + vgcreate 만 하고,
  #    LVM CSI 가 그 VG 에서 LV 를 잘라 PVC 에 붙인다.
  dynamic "disk" {
    for_each = each.value.storage_disk_gb > 0 ? [each.value.storage_disk_gb] : []
    content {
      datastore_id = var.datastore
      interface    = "scsi2"
      size         = disk.value
      discard      = "on"
      ssd          = true
    }
  }

  # NIC 1장(vmbr0)만 — 호스트 B 에 내부 브리지(vmbr1)를 만들지 않는다.
  # host-only 브리지는 호스트 A 로 넘어가지 못해 크로스호스트 pod 트래픽은 결국 vmbr0 을
  # 타고, 2번째 NIC 는 Cilium 의 device 자동탐지·native routing 판단만 흐린다.
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

  lifecycle {
    ignore_changes = [clone]
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# K8s 노드 VM — 호스트 A (Proxmox `k8s2` @ 192.168.0.12) · P1 후 램프분
#
# 위 `k8s` 리소스와 **provider 만 다르다**(A = default provider). Terraform 은 provider 를
# 인스턴스마다 바꿀 수 없어서 리소스 블록을 나눌 수밖에 없다 — 스펙은 의도적으로 동일하게 둔다.
#
# 생성 전제(런북 §2-C-0): `.9`(fb-app-ai) 정지로 RAM 회수 · 구 fb-ci-harbor(203) 파괴로
#   디스크 회수. 2026-07-28 실측 = 호스트 A 여유 RAM 18GB · local-lvm(씬풀) 가용 ~589GB.
# 🔴 IP 는 예약이 아니라 **실점유 확인 후** 배정한다 — `.13` 을 예약해 뒀다가 타인 장비가
#    물고 있어 폐기한 전례가 있다. `.20` 은 2026-07-28 ARP 실측으로 무응답 확인(대조군 `.17`
#    은 MAC 응답) → 배정. 자세한 수칙 = status §1.1.
# ⚠️ 템플릿 9002 는 A·B 양쪽에 존재한다(B 로 "이관"된 게 아니라 사본이 각각 있다).
# ─────────────────────────────────────────────────────────────────────────────
resource "proxmox_virtual_environment_vm" "k8s_a" {
  for_each = var.k8s_nodes_a

  name      = each.key
  node_name = var.node_name
  vm_id     = each.value.vmid
  tags      = ["k8s", "terraform"]

  clone {
    vm_id = var.template_vmid
    full  = true
  }

  agent {
    enabled = true
  }

  cpu {
    cores = each.value.cores
    type  = "host"
  }

  operating_system {
    type = "l26"
  }

  serial_device {
    device = "socket"
  }

  # 벌룬 OFF — kubelet 이 기동 시 캐시한 capacity 를 벌룬이 나중에 회수하면
  # 축출 대신 OOM 이 난다(위 `k8s` 리소스와 동일 근거).
  memory {
    dedicated = each.value.memory
    floating  = 0
  }

  disk {
    datastore_id = var.datastore
    interface    = "scsi0"
    size         = each.value.disk_gb
    discard      = "on"
    ssd          = true
  }

  disk {
    datastore_id = var.datastore
    interface    = "scsi1"
    size         = each.value.containerd_disk_gb
    discard      = "on"
    ssd          = true
  }

  dynamic "disk" {
    for_each = each.value.storage_disk_gb > 0 ? [each.value.storage_disk_gb] : []
    content {
      datastore_id = var.datastore
      interface    = "scsi2"
      size         = disk.value
      discard      = "on"
      ssd          = true
    }
  }

  # NIC 1장(vmbr0)만 — A 에는 내부 브리지 vmbr1 이 있지만 K8s 노드는 붙이지 않는다.
  # host-only 브리지는 호스트 B 로 넘어가지 못해 크로스호스트 pod 트래픽은 결국 vmbr0 을
  # 타고, 2번째 NIC 는 Cilium 의 device 자동탐지만 흐린다(B 노드와 동일 판단).
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
}
