# 비-비밀 설정 (커밋 OK). 비밀번호는 여기 넣지 말 것 → credentials.env
proxmox_endpoint = "https://192.168.0.12:8006/"
proxmox_username = "root@pam"
node_name        = "k8s2"
template_vmid    = 9002 # qemu-guest-agent 사전설치본(9001 사본). agent 미설치 시 신규 VM 생성이 agent 대기로 행
datastore        = "local-lvm"
bridge           = "vmbr0"
gateway          = "192.168.0.1"

# ⚠️ 본인 SSH 공개키로 교체:  cat ~/.ssh/id_ed25519.pub
ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEVwVV7f3SzeDoNRtpjceWiefP6trEx7BulQ4wsZuqNR team6@DESKTOP-97HF5IH"

# design.md §8.4 (Docker 베이스라인). memory=MB, balloon_floor 0=벌룬off
# 내부망(vmbr1, 10.10.10.0/24)은 끝자리 미러링: 192.168.0.X → 10.10.10.X (host=.1)
vms = {
  vm1_data = { vmid = 201, name = "fb-data", cores = 4, memory = 8192, balloon_floor = 0, disk_gb = 100, docker_disk_gb = 40, ip = "192.168.0.8", internal_ip = "10.10.10.8" }
  vm2_app  = { vmid = 202, name = "fb-app-ai", cores = 6, memory = 7168, balloon_floor = 4096, disk_gb = 80, docker_disk_gb = 30, ip = "192.168.0.9", internal_ip = "10.10.10.9" }
  # 🔴 vm3_ci(203, fb-ci-harbor) = 은퇴·terraform 추적 제외(state rm, 2026-07-27). 되살리지 말 것 —
  #    켜지면 cloud-init 이 `.10` 을 물어 호스트 C(Harbor·Jenkins·SonarQube)와 충돌한다. 파괴는 수동.
  vm4_mon  = { vmid = 204, name = "fb-monitoring", cores = 3, memory = 6144, balloon_floor = 4096, disk_gb = 100, docker_disk_gb = 40, ip = "192.168.0.11", internal_ip = "10.10.10.11" }
}

# K8s 노드 — 호스트 B(`k8s1` @ .22) · P0 = 3노드. 램프·RAM 근거 = 플랜 §2.2
# 벌룬 없음(고정) · NIC 1장(vmbr0) · IP = 예약대역 .17–.21 · vmid 3xx = B 의 K8s 노드
# 씬풀(794G) 점유 = 90 + 240×2 = 570G(72%). 부족 시 디스크 핫애드 + vgextend 로 무중단 증설.
k8s_nodes = {
  "k8s-master"    = { vmid = 301, cores = 2, memory = 6144, disk_gb = 50, containerd_disk_gb = 40, storage_disk_gb = 0, ip = "192.168.0.17" }
  "k8s-worker-b1" = { vmid = 302, cores = 6, memory = 11264, disk_gb = 50, containerd_disk_gb = 40, storage_disk_gb = 150, ip = "192.168.0.18" }
  "k8s-worker-b2" = { vmid = 303, cores = 6, memory = 11264, disk_gb = 50, containerd_disk_gb = 40, storage_disk_gb = 150, ip = "192.168.0.19" }
}
