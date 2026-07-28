terraform {
  required_version = ">= 1.6"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = ">= 0.66"
    }
  }
}

provider "proxmox" {
  endpoint = var.proxmox_endpoint
  username = var.proxmox_username
  password = var.proxmox_password
  insecure = true # PVE 자체서명 인증서

  ssh {
    agent    = false
    username = "root"
    password = var.proxmox_password
  }
}

# 호스트 B(.22) — 스탠드얼론 별개 서버이므로 default provider 로 닿지 않는다.
# 이 alias 를 쓰는 리소스만 B 에 생성된다(K8s 노드 VM). A 의 기존 VM 4대는 default provider 소관 — 서로 영향 없음.
provider "proxmox" {
  alias    = "b"
  endpoint = var.proxmox_b_endpoint
  username = var.proxmox_b_username
  password = var.proxmox_b_password
  insecure = true

  ssh {
    agent    = false
    username = "root"
    password = var.proxmox_b_password
  }
}
