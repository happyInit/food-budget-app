# Proxmox VM 프로비저닝 (Terraform)

두 대상을 한 워크스페이스에서 관리한다 (state = PG 원격 backend 공유):

| 대상 | provider | Proxmox | 내용 |
|---|---|---|---|
| 호스트 A | default | `k8s2` @ 192.168.0.12 | `design.md §8.4` Docker 베이스라인 VM (현행 프로덕션) |
| 호스트 B | **alias `b`** | `k8s1` @ 192.168.0.22 | **K8s 노드 VM** (P0 3노드 — 플랜 §2.2) |

템플릿 `9002`(qemu-guest-agent 사전설치본)을 full clone + cloud-init. 두 호스트는 각자 사본을 갖고 있다.

## VM 스펙 — 호스트 A (Docker 베이스라인)

| VM | vmid | IP | RAM(MB) | vCPU | Disk | 벌룬 |
|---|---|---|---|---|---|---|
| fb-data | 201 | .8 | 8192 | 4 | 100G | off(고정) |
| fb-app-ai | 202 | .9 | 7168 | 6 | 80G | on(≥4G) |
| fb-monitoring | 204 | .11 | 6144 | 3 | 100G | on(≥4G) |

> ~~fb-ci-harbor (203, .10)~~ = **은퇴**(2026-07-27, 호스트 C 가 `.10` 승계). 정지·`onboot=0` 상태로
> Proxmox 에 남아 있으나 **terraform state 에서 제거해 추적하지 않는다** — 파괴는 수동(220G 회수).
> ⚠️ tfvars 에 되살리지 말 것: 켜지면 `.10` 을 호스트 C 와 다퉈 Harbor·Jenkins 접근이 깨진다.

## VM 스펙 — 호스트 B (K8s 노드, P0)

| VM = 노드명 | vmid | IP | RAM(MB) | vCPU | scsi0 (nodefs) | scsi1 (containerd) | scsi2 (OpenEBS VG) |
|---|---|---|---|---|---|---|---|
| k8s-master | 301 | .17 | 6144 | 2 | 50G | 40G | — |
| k8s-worker-b1 | 302 | .18 | 11264 | 6 | 50G | 40G | 150G raw |
| k8s-worker-b2 | 303 | .19 | 11264 | 6 | 50G | 40G | 150G raw |

- **벌룬 없음**(`floating = 0`) — kubelet 은 기동 시 capacity 를 캐시하므로 벌룬 회수는 축출 대신 OOM 을 만든다.
- **NIC 1장(vmbr0)** — 호스트 B 엔 vmbr1 을 만들지 않는다(host-only 는 호스트 A 로 못 넘어감).
- **scsi2 는 mkfs 하지 않는다** — Ansible 이 `pvcreate` + `vgcreate` 만 하고 OpenEBS LVM CSI 가 LV 를 잘라 쓴다.
- 씬풀(794G) 점유 = 570G(72%). 부족하면 디스크 핫애드 + `vgextend` 로 무중단 증설.

## 사전 준비

1. **비밀번호** — `credentials.env`에 Proxmox root 비밀번호 입력 (이 파일은 `.gitignore`됨):
   ```
   export TF_VAR_proxmox_password='실제_비밀번호'     # 호스트 A (k8s2 @ .12)
   export TF_VAR_proxmox_b_password='실제_비밀번호'   # 호스트 B (k8s1 @ .22) — K8s 노드용
   ```
   호스트 B 는 A 와 **별개 스탠드얼론 서버**라 자격증명이 따로다(`provider "proxmox"` alias `b`).
   B 쪽 값이 비어 있으면 `terraform plan` 이 변수 미정의로 즉시 실패한다.
2. **SSH 공개키** — `terraform.tfvars`의 `ssh_public_key`를 본인 것으로 교체:
   ```
   cat ~/.ssh/id_ed25519.pub
   ```
3. **템플릿 디스크 인터페이스 확인** — `disk.interface`는 `scsi0` 기본값.
   템플릿이 다르면(`qm config 9002` 출력에서 확인) 그 값으로 수정.

## 실행

```bash
cd infra/terraform
set -a; source credentials.env; set +a          # 비밀번호 환경변수 주입 (A·B 둘 다)
terraform init -backend-config=backend.conf     # state = PG 원격 backend
terraform plan                                  # 🔴 반드시 리뷰: A 쪽 VM 은 No changes 여야 한다
terraform apply
```

🔴 **plan 에 A 쪽 VM 의 in-place 변경이 보이면 멈출 것.** 손으로 만진 상태(정지·onboot 등)와 코드가
어긋난 것이고, 그대로 apply 하면 terraform 이 코드 쪽으로 되돌린다 — 은퇴 VM 이 켜지면 IP 충돌이 난다.

## 결과 확인 / 정리

```bash
terraform output              # VM IP·SSH 타깃 (k8s_ssh_targets = Ansible 인벤토리에 넣을 값)
ssh ubuntu@192.168.0.8        # 예: fb-data 접속
ssh ubuntu@192.168.0.17       # 예: k8s-master 접속
terraform destroy             # 전체 제거 (주의 — A·B 양쪽 전부)
```

## 주의

- `credentials.env`·`backend.conf`·`*.tfstate`는 커밋 금지(.gitignore 처리).
- 벌룬: 호스트 A 는 VM1(Data)만 고정(`floating=0`), 나머지는 최소치 지정 → 호스트가 미사용분 회수.
  **K8s 노드는 전부 고정** — 이유는 위 K8s 스펙 표.
- `qemu-guest-agent`가 템플릿에 있어야 `terraform`이 VM IP를 리포팅.
- 두 호스트가 한 state 를 공유하므로 `terraform destroy`·`-refresh=false` 는 특히 조심.
