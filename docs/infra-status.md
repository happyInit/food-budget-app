# 인프라 현황 (온프렘 · Proxmox)

> **팀 공유용 상태 문서.** 최종 갱신: **2026-07-11**
> 설계 정본: [`design.md §8.4`](./design.md) · IaC: [`infra/`](../infra) · **모니터링 운영: [`monitoring-ops.md`](./monitoring-ops.md)** · 배포 모델: Docker(compose) 베이스라인

## 한눈에 요약

| 항목 | 상태 |
|---|---|
| Proxmox 호스트 | ✅ 가동 (standalone, 클린) |
| 4-VM 프로비저닝 (Terraform) | ✅ 완료, 전부 running |
| 공통 설정 (Ansible: agent·Docker·디스크) | ✅ 완료, 4대 검증 |
| 서비스 배포 | 🚧 진행 중 — **monitoring LGTM**(Prom+Grafana+Loki+Tempo+Alloy) + **Harbor** 배포·검증 완료 |
| Terraform state | ✅ **PG 원격 backend** (fb-data, 공유·잠금) |
| K8s 이전 | ⬜ 향후 조건부 (하이브리드 방향) |

---

## 1. 호스트 (Proxmox VE)

| 항목 | 값 |
|---|---|
| 주소 / 노드명 | `192.168.0.12` (웹: https://192.168.0.12:8006) / `k8s2` |
| 버전 | Proxmox VE 9.1.1 (kernel 6.17.2-1-pve), standalone |
| CPU | Intel i7-10700F — **8코어 / 16스레드** @ 2.9GHz |
| RAM | 32GB (31GiB 가용) + swap 8GB |
| 시스템 디스크 | `sdb` WD Blue 1TB SSD → VG `pve`: root 96G(xfs) + swap 8G + **thin `data`(local-lvm) 643G** + VFree ~183G |
| 여유 디스크 | `sda` Crucial 250GB SSD — **미사용**(구 Windows), 활용 후보 |
| 스토리지 | `local`(dir) · `local-lvm`(thin) · **ZFS 아님(XFS)** |
| 클론 템플릿 | `9001` ubuntu-2404-template (cloud-init) |

---

## 2. VM 현황 (4-VM)

전부 **Ubuntu 24.04**, running. 역할·위치는 `design.md §8.4` 기준.

| VM | vmid | IP | vCPU | RAM | 벌룬 | OS디스크 | docker디스크 | 담는 역할 |
|---|---|---|---|---|---|---|---|---|
| **fb-data** | 201 | `.8` | 4 | 8GB | off(고정) | 100G | 40G (`/dev/sdb`) | PostgreSQL·Elasticsearch·Redis·Kafka |
| **fb-app-ai** | 202 | `.9` | 6 | 7GB | on(≥4G) | 80G | 30G | FastAPI 7개·ML 서빙·크롤러 |
| **fb-ci-harbor** | 203 | `.10` | 3 | 5GB | on(≥3G) | 150G | 70G | Harbor·GitHub 러너 |
| **fb-monitoring** | 204 | `.11` | 3 | 6GB | on(≥4G) | 100G | 40G | Prometheus·Loki·Tempo·Grafana |
| **합계** | | | 16 | **26GB** | | | | RAM 여유 ~5GB + swap 8G |

**리소스 안전장치:** RAM 무오버커밋(26≤31) · fb-data만 벌룬 off(DB 보호) · thin 풀 610/643G(무오버프로비전) · JVM heap 캡(ES/Kafka)·Prometheus/Loki/Tempo retention 예정.

---

## 3. 공통 설정 (전 VM, Ansible base 역할 적용 완료)

| 항목 | 상태 |
|---|---|
| qemu-guest-agent | ✅ active (Proxmox 연동) |
| Docker Engine | ✅ **29.6.1** + compose 플러그인 |
| Docker data-root | ✅ `/var/lib/docker` = **전용 디스크 `/dev/sdb`** (OS와 분리) |
| ubuntu 유저 | ✅ docker 그룹 |

---

## 4. 접근 방법

```bash
# VM SSH (team6 키 기준)
ssh ubuntu@192.168.0.8     # fb-data
ssh ubuntu@192.168.0.9     # fb-app-ai
ssh ubuntu@192.168.0.10    # fb-ci-harbor
ssh ubuntu@192.168.0.11    # fb-monitoring

# Proxmox 웹 UI
https://192.168.0.12:8006  (root@pam)

# 배포된 서비스
http://192.168.0.11:3000   # Grafana — 메트릭·로그·트레이스 (운영: docs/monitoring-ops.md)
http://192.168.0.11:9090   # Prometheus (타깃 9/9 up)
http://192.168.0.11:3100   # Loki (로그, 4대 수집 중)
http://192.168.0.11:3200   # Tempo (트레이스, OTLP :4317/:4318)
http://192.168.0.10        # Harbor 레지스트리 (admin / secrets.yml)
```
> SSH는 cloud-init에 주입된 공개키 인증. 접근이 필요하면 본인 공개키를 `infra/terraform/terraform.tfvars`에 추가 후 재적용 or 관리자에게 요청.

---

## 5. IaC — 코드 위치 & 운영

| 구성 | 위치 | 역할 |
|---|---|---|
| **Terraform** | [`infra/terraform/`](../infra/terraform) | Proxmox VM 프로비저닝 (bpg/proxmox, 템플릿 클론) |
| **Ansible** | [`infra/ansible/`](../infra/ansible) | 공통 설정 (agent·Docker·디스크 마운트) |
| 비밀 | `infra/terraform/credentials.env` | **`.gitignore`됨 — 커밋 안 됨** (Proxmox root 비번) |

**재현 / 운영 커맨드**
```bash
# 1) VM 프로비저닝 (또는 스펙 변경 반영)
cd infra/terraform
cp backend.conf.example backend.conf        # 최초 1회, 비번 채우기 (state=PG backend)
set -a; source credentials.env; set +a      # Proxmox 비번 주입
terraform init -backend-config=backend.conf # PG backend 연결
terraform plan && terraform apply

# 2) 공통 설정 적용 (멱등 — 언제든 재실행 가능)
cd infra/ansible
ansible all -m ping            # 연결 확인
ansible-playbook site.yml      # agent·Docker·디스크
```

---

## 6. 로드맵 (다음 단계)

| 순위 | 작업 | 대상 VM | 상태 |
|---|---|---|---|
| — | 호스트·VM·공통설정 | 전체 | ✅ 완료 |
| ✅ | **monitoring 메트릭** (Prometheus+Grafana+node-exporter+cAdvisor, 9/9 up) | fb-monitoring +전VM | ✅ 완료 |
| ✅ | **monitoring 로그·트레이스** (Loki+Tempo+Alloy, 4대 로그 수집) | fb-monitoring +전VM | ✅ 완료 |
| ✅ | **컨테이너 리소스 제한** (monitoring·에이전트·tfstate) | 전VM | ✅ 완료 |
| ✅ | **Terraform state → PG backend** (전용 postgres, 공유·잠금) | fb-data | ✅ 완료 |
| ✅ | **ci: Harbor 레지스트리** (v2.15.2, HTTP, 7컴포넌트 healthy) | fb-ci-harbor | ✅ 완료 |
| next | **ci: GitHub Actions 러너** (PAT `Administration:write` 필요) | fb-ci-harbor | ⬜ |
| next | **Harbor 컨테이너 리소스 제한** (자체 compose라 별도) | fb-ci-harbor | ⬜ |
| next | **data 배포** (앱용 PG·ES·Redis·Kafka) | fb-data | ⬜ |
| later | **app 배포** (FastAPI) | fb-app-ai | ⬜ (앱 코드 대기) |
| future | K8s 이전 (하이브리드: DB 외부 + Kafka/앱은 K8s) | — | ⬜ 조건부 |

---

## 7. 알려진 이슈 · Follow-up

- **템플릿 미포함(agent/docker)**: 템플릿 9001은 3.5G라 docker 베이킹 폐기 → **공통 설정은 Ansible이 담당**(재현성=플레이북 재실행).
- **Terraform 재생성 시 agent-hang**: 새 VM은 Ansible 실행 전까지 guest-agent가 없어 `terraform apply`가 agent 대기로 지연됨. 완전 해소하려면 **cloud-init 스니펫으로 agent만 first-boot 설치**(미적용).
- **`sda` 250GB 미사용**: 구 Windows. DB IO 격리/백업/확장 후보 (미결정).
- **백업 없음**: cross-host-backup 제거됨. 필요 시 `sda`나 외부 타깃으로 별도 설계.
- **Harbor HTTP**: 이미지 push 클라이언트(app/ci VM·러너)는 `/etc/docker/daemon.json`에 `{"insecure-registries":["192.168.0.10"]}` 필요 (push 시점 설정). Trivy 스캔은 RAM 절약 위해 미포함(추후 `--with-trivy`).
- **GitHub 러너 미배포**: 등록 토큰(GitHub PAT/runner token) 필요 → 토큰 확보 시 배포.

---

*이 문서는 인프라 상태 변경 시 갱신하세요. 세부 설계 근거는 [`design.md`](./design.md), 데이터소스 검증은 [`data-validation.md`](./data-validation.md).*
