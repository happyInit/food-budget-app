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

# design.md §8.4 (Docker 베이스라인) VM 3대 — **전부 파괴 완료 (2026-07-31, P4)**.
#
# 🔴 **손으로 `qm destroy` 하지 말 것.** 이 VM 들은 Terraform 관리 대상이었으므로 선언에서
#    걷어내고 apply 로 파괴해야 한다. 손으로 지우면 다음 apply 가 **다시 만든다**
#    (같은 날 그 정반대 방향 — 정지만 하고 선언을 안 고쳐서 apply 가 되살리려던 것 — 을 밟았다).
#
# 이력 (되살릴 일이 생기면 여기부터 읽을 것):
#   vm1_data(201, fb-data, .8)     P2 데이터 컷오버 2026-07-30 → 정지 → 07-31 파괴.
#                                  최종 PG 덤프 = s3://mp-backup-ap2/pg-final/2026-07-30/ (SHA256 검증)
#   vm2_app (202, fb-app-ai, .9)   P1 유입 전환(.14) 2026-07-28 → 정지 → 07-31 파괴.
#                                  .env 백업 = /home/team6/backups/dot-env-20260728/
#   vm3_ci  (203, fb-ci-harbor)    2026-07-27 은퇴·state rm 후 수동 파괴 (호스트 C 가 .10 승계)
#   vm4_mon (204, fb-monitoring, .11)  모니터링 컷오버 2026-07-30 → 07-31 정지 → 같은 날 파괴.
#                                  ⚠️ 이 디스크의 Prometheus TSDB(07-16~07-28)는 **사본 없이 소멸**했다.
#                                  인클러스터 Prometheus 는 07-28 09:59 부터다.
#
# 회수량(씬 프로비저닝이라 선언 390G 이 아니라 실사용 기준): 약 80 GiB.
# RAM 은 파괴로 회수되는 게 없다 — 정지 시점에 이미 반납됐다.
#
# 내부망 브리지(vmbr1, 10.10.10.0/24)는 남긴다 — 이 VM 들 전용이었지만 재사용 여지가 있고
# 지우는 것 자체가 별건이다.
vms = {}

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
