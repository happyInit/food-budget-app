# Proxmox VM 프로비저닝 (Terraform)

`design.md §8.4` Docker 베이스라인 토폴로지를 Proxmox(`k8s2`, 192.168.0.12)에 프로비저닝.
템플릿 `9001 (ubuntu-2404-template)`을 full clone + cloud-init.

## VM 스펙

| VM | vmid | IP | RAM(MB) | vCPU | Disk | 벌룬 |
|---|---|---|---|---|---|---|
| fb-data | 201 | .8 | 8192 | 4 | 100G | off(고정) |
| fb-app-ai | 202 | .9 | 7168 | 6 | 80G | on(≥4G) |
| fb-ci-harbor | 203 | .10 | 5120 | 3 | 150G | on(≥3G) |
| fb-monitoring | 204 | .11 | 6144 | 3 | 100G | on(≥4G) |

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
3. **템플릿 디스크 인터페이스 확인** — `vms.tf`의 `disk.interface`는 `scsi0` 기본값.
   템플릿이 다르면(`qm config 9001` 출력에서 확인) 그 값으로 수정.

## 실행

```bash
cd infra/terraform
set -a; source credentials.env; set +a     # 비밀번호 환경변수 주입
terraform init
terraform plan      # 생성 계획 리뷰
terraform apply     # 4-VM 생성
```

## 결과 확인 / 정리

```bash
terraform output              # VM IP·SSH 타깃
ssh ubuntu@192.168.0.8        # 예: fb-data 접속
terraform destroy             # 전체 제거 (주의)
```

## 주의

- `credentials.env`·`*.tfstate`는 커밋 금지(.gitignore 처리). state에 비밀번호가 남을 수 있으니 원격 백엔드(선택) 고려.
- 벌룬: VM1(Data)만 고정(`floating=0`), 나머지는 `floating`으로 최소치 지정 → 호스트가 미사용분 회수.
- `qemu-guest-agent`가 템플릿에 있어야 `terraform`이 VM IP를 리포팅.
