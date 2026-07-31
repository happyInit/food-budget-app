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
  # 🔴 P2 데이터 컷오버(2026-07-30) 후 **정지 보존** — P4 까지 최후 보험(디스크 유지). 파괴는 별도 판단.
  #    started=false 미선언 상태로 07-30~07-31 방치돼 있었다 — 2026-07-31 a2 추가 plan 에서
  #    `started false -> true`(= 구 데이터 티어 재기동)로 **실제로 잡혔다**. vm2_app 과 같은 지뢰.
  vm1_data = { vmid = 201, name = "fb-data", cores = 4, memory = 8192, balloon_floor = 0, disk_gb = 100, docker_disk_gb = 40, ip = "192.168.0.8", internal_ip = "10.10.10.8", started = false }
  # 🔴 P1 유입 전환(.14) 후 **정지 보존** — 2026-07-28. 파괴는 P2 안착 후 별도 판단.
  #    started=false 를 안 박으면 다음 apply 가 이 VM 을 다시 켠다(plan 에서 실제로 잡혔다).
  vm2_app  = { vmid = 202, name = "fb-app-ai", cores = 6, memory = 7168, balloon_floor = 4096, disk_gb = 80, docker_disk_gb = 30, ip = "192.168.0.9", internal_ip = "10.10.10.9", started = false }
  # 🔴 vm3_ci(203, fb-ci-harbor) = 은퇴·terraform 추적 제외(state rm, 2026-07-27). 되살리지 말 것 —
  #    켜지면 cloud-init 이 `.10` 을 물어 호스트 C(Harbor·Jenkins·SonarQube)와 충돌한다. 파괴는 수동.
  # 🔴 모니터링 컷오버(2026-07-30) 후 역할 전무 → **정지 보존**(2026-07-31, P4-A). 파괴는 별도 판단.
  #    보존 이유 = 이 디스크의 Prometheus TSDB 에 07-16~07-28 메트릭(사고 3회·온도 추이)이 있고
  #    인클러스터 Prometheus 는 07-28 09:59 부터라 **사본이 없다**. RAM 6GB 는 정지로 이미 회수됐고
  #    디스크는 556GB 여유라 서둘러 파괴할 이유가 없다.
  vm4_mon  = { vmid = 204, name = "fb-monitoring", cores = 3, memory = 6144, balloon_floor = 4096, disk_gb = 100, docker_disk_gb = 40, ip = "192.168.0.11", internal_ip = "10.10.10.11", started = false }
}

# K8s 노드 — 호스트 B(`k8s1` @ .22) · P0 = 3노드. 램프·RAM 근거 = 플랜 §2.2
# 벌룬 없음(고정) · NIC 1장(vmbr0) · IP = 예약대역 .17–.21 · vmid 3xx = B 의 K8s 노드
# 씬풀(794G) 점유 = 90 + 240×2 = 570G(72%). 부족 시 디스크 핫애드 + vgextend 로 무중단 증설.
k8s_nodes = {
  "k8s-master"    = { vmid = 301, cores = 2, memory = 6144, disk_gb = 50, containerd_disk_gb = 40, storage_disk_gb = 0, ip = "192.168.0.17" }
  "k8s-worker-b1" = { vmid = 302, cores = 6, memory = 11264, disk_gb = 50, containerd_disk_gb = 40, storage_disk_gb = 150, ip = "192.168.0.18" }
  "k8s-worker-b2" = { vmid = 303, cores = 6, memory = 11264, disk_gb = 50, containerd_disk_gb = 40, storage_disk_gb = 150, ip = "192.168.0.19" }
}

# 호스트 A 램프분 — .9 정지(RAM 회수)·구 harbor VM 203 파괴(디스크 회수) 후 생성.
# RAM 12GB = 플랜 §2.2 P1 후 램프값(P4 에 14GB 로 확장). IP .20 = 2026-07-28 ARP 실점유 확인 완료.
#
# a2 = P4 노드 램프 4→5 (2026-07-31). 스펙은 b1/b2 와 동일하게 맞췄다.
#   IP .21 = 예약대역(.17–.21)의 마지막 칸. **ARP·ping 실점유 확인 완료(2026-07-31)** — 로컬·
#   하이퍼바이저 ARP 테이블 모두 무응답. vmid 305 미사용 확인.
#   RAM 예산(호스트 A 32GB): a1 14336 + a2 11264 = 25GB → 호스트 여유 ~7GB.
#   ⚠️ 전제 = `.11`(vmid 204, 6144MB) 정지. 2026-07-31 정지 완료 — 되살리면 예산이 깨진다.
k8s_nodes_a = {
  "k8s-worker-a1" = { vmid = 304, cores = 6, memory = 12288, disk_gb = 50, containerd_disk_gb = 40, storage_disk_gb = 150, ip = "192.168.0.20" }
  "k8s-worker-a2" = { vmid = 305, cores = 6, memory = 11264, disk_gb = 50, containerd_disk_gb = 40, storage_disk_gb = 150, ip = "192.168.0.21" }
}
