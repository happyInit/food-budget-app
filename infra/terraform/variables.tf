variable "proxmox_endpoint" {
  description = "Proxmox API 엔드포인트"
  type        = string
  default     = "https://192.168.0.12:8006/"
}

variable "proxmox_username" {
  description = "Proxmox API 사용자 (realm 포함)"
  type        = string
  default     = "root@pam"
}

variable "proxmox_password" {
  description = "Proxmox root 비밀번호 — credentials.env(TF_VAR_proxmox_password)로 주입. 절대 커밋 금지."
  type        = string
  sensitive   = true
}

variable "node_name" {
  description = "PVE 노드명 (hostname)"
  type        = string
  default     = "k8s2"
}

# ── 호스트 B (Proxmox `k8s1` @ 192.168.0.22 · 스탠드얼론) — K8s 노드 VM 전용 ──
# A(.12)와 별개 클러스터가 아니라 별개 *스탠드얼론 서버*라 API 엔드포인트·자격증명이 따로다.
# → provider.tf 의 alias = proxmox.b 가 이 값들을 쓴다.
variable "proxmox_b_endpoint" {
  description = "호스트 B Proxmox API 엔드포인트"
  type        = string
  default     = "https://192.168.0.22:8006/"
}

variable "proxmox_b_username" {
  description = "호스트 B Proxmox 사용자 (realm 포함)"
  type        = string
  default     = "root@pam"
}

variable "proxmox_b_password" {
  description = "호스트 B Proxmox root 비밀번호 — credentials.env(TF_VAR_proxmox_b_password)로 주입. 절대 커밋 금지."
  type        = string
  sensitive   = true
}

variable "node_name_b" {
  description = "호스트 B 의 PVE 노드명 (⚠️ 호스트명 역전 — B=k8s1, A=k8s2)"
  type        = string
  default     = "k8s1"
}

variable "template_vmid" {
  description = "클론 원본 cloud-init 템플릿 VMID"
  type        = number
  default     = 9001
}

variable "datastore" {
  description = "VM 디스크 저장소 (thin)"
  type        = string
  default     = "local-lvm"
}

variable "bridge" {
  description = "외부(관리) 네트워크 브리지 — 물리 업링크, 기본 gateway"
  type        = string
  default     = "vmbr0"
}

variable "internal_bridge" {
  description = "내부 전용(host-only) 브리지 — 물리 포트 없음, gateway 없음. VM 간 사설망(10.10.10.0/24)."
  type        = string
  default     = "vmbr1"
}

variable "internal_bridge_address" {
  description = "내부 브리지에 부여할 호스트(Proxmox) 측 IP (CIDR). VM 미러링 대역의 .1 앵커."
  type        = string
  default     = "10.10.10.1/24"
}

variable "gateway" {
  description = "게이트웨이 IP"
  type        = string
  default     = "192.168.0.1"
}

variable "dns_servers" {
  description = "DNS 서버"
  type        = list(string)
  default     = ["192.168.0.1", "1.1.1.1"]
}

variable "ci_user" {
  description = "cloud-init 기본 사용자"
  type        = string
  default     = "ubuntu"
}

variable "ssh_public_key" {
  description = "cloud-init 주입 SSH 공개키 (본인 것으로 교체)"
  type        = string
}

variable "k8s_nodes" {
  description = "K8s 노드 VM 스펙 (호스트 B). map 키 = VM 이름 = 게스트 hostname = K8s 노드명(RFC-1123 소문자). 램프·RAM 근거 = 플랜 §2.2"
  type = map(object({
    vmid               = number
    cores              = number
    memory             = number # MB — 고정(벌룬 off)
    disk_gb            = number # scsi0 OS = kubelet nodefs
    containerd_disk_gb = number # scsi1 → /var/lib/containerd = kubelet imagefs
    storage_disk_gb    = number # scsi2 → OpenEBS LVM VG 용 raw. 0 = 미부착(master)
    ip                 = string # vmbr0 정적 IP (예약대역 .17–.21)
  }))
}

variable "vms" {
  description = "프로비저닝할 VM 스펙 (design.md §8.4 · Docker 베이스라인)"
  type = map(object({
    vmid           = number
    name           = string
    cores          = number
    memory         = number # MB, dedicated(최대)
    balloon_floor  = number # MB, floating(최소). 0 = 벌룬 off(고정)
    disk_gb        = number # OS 디스크(GB)
    docker_disk_gb = number # /var/lib/docker 전용 디스크(GB)
    ip             = string # 외부(vmbr0) 관리망 IP — gateway 있음
    internal_ip    = string # 내부(vmbr1) 전용망 IP — gateway 없음
  }))
}
