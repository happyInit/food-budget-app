# 인프라 현황 (온프렘 · Proxmox)

> **팀 공유용 상태 문서.** 최종 갱신: **2026-07-11**
> 설계 정본: [`design.md §8.4`](./design.md) · IaC: [`infra/`](../infra) · **모니터링 운영: [`monitoring-ops.md`](./monitoring-ops.md)** · 배포 모델: Docker(compose) 베이스라인

## 한눈에 요약

| 항목 | 상태 |
|---|---|
| Proxmox 호스트 | ✅ 가동 (standalone, 클린) |
| 4-VM 프로비저닝 (Terraform) | ✅ 완료, 전부 running |
| 공통 설정 (Ansible: agent·Docker·디스크) | ✅ 완료, 4대 검증 |
| 서비스 배포 | 🚧 진행 중 — **monitoring LGTM**(Prom+Grafana+Loki+Tempo+Alloy) + **Harbor** + **data 티어**(PG·ES·Redis·Kafka) 배포·검증 완료 |
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

**리소스 안전장치:** RAM 무오버커밋(26≤31) · fb-data만 벌룬 off(DB 보호) · thin 풀 610/643G(무오버프로비전) · **JVM heap 캡 적용(ES·Kafka 각 512m)** · 전 컨테이너 mem/cpu limit · Prometheus/Loki/Tempo retention 예정.

### 2.1 데이터 티어 (fb-data, Docker compose) — ✅ 배포·검증 완료

| 서비스 | 이미지 | mem limit | 포트 | 비고 |
|---|---|---|---|---|
| **PostgreSQL(공유)** | postgres:16-alpine | 1.5G | 5432 | DB 2개 — `terraform_state`(state backend) + `foodbudget`(앱 OLTP, `fbapp` 롤). **같은 인스턴스, DB만 분리** |
| **Elasticsearch** | ES 8.15.3 + **nori**(로컬빌드 커스텀 이미지) | 1.2G | 9200 | single-node · security off(내부망) · heap 512m · green |
| **Redis** | redis:7-alpine | 320M | 6379 | 캐시(LRU 256mb·비영속) |
| **Kafka** | apache/kafka:3.9.0 | 1.0G | 9092 | **KRaft 단일노드**(ZK 없음) · heap 512m · advertised=192.168.0.8 |
| exporters ×4 | postgres/redis/es/kafka | ~0.3G | 9187·9121·9114·9308 | Prometheus 스크레이프 |

- Ansible: `roles/tfstate_db`(공유 PG + app DB 멱등생성) + `roles/data_tier`(ES·Redis·Kafka·exporters) · `site.yml` data play.
- ES 요구 `vm.max_map_count=262144` sysctl 영속 적용. 실측 RAM ~2.2G/7.8G 사용(5.5G 여유).
- 검증: ES nori 한국어 토큰화·Kafka 토픽 CRUD·Redis PING·PG DB분리·`terraform_state` 무손상 확인. Prometheus 13/13 up.

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

# 배포된 서비스  (Harbor·Grafana = 로컬 CA HTTPS → 브라우저에 infra/certs/ca.crt 임포트)
https://192.168.0.10       # Harbor 레지스트리 (HTTPS, admin / secrets.yml)
https://192.168.0.11:3000  # Grafana — 메트릭·로그·트레이스 (HTTPS, 운영: docs/monitoring-ops.md)
http://192.168.0.11:9090   # Prometheus (내부, 타깃 13/13 up)
http://192.168.0.11:3100   # Loki (내부, 4대 수집)
http://192.168.0.11:3200   # Tempo (내부, OTLP :4317/:4318)

# 데이터 티어 (fb-data, 내부 — 앱이 소비)
192.168.0.8:5432   # PostgreSQL — DB: foodbudget(앱 OLTP) / terraform_state(state)
http://192.168.0.8:9200    # Elasticsearch (nori)
192.168.0.8:6379   # Redis (캐시)
192.168.0.8:9092   # Kafka (KRaft)
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
| ✅ | **전 컨테이너 리소스 제한** (monitoring·에이전트·Harbor·러너·tfstate) | 전VM | ✅ 완료 |
| ✅ | **Terraform state → PG backend** (전용 postgres, 공유·잠금) | fb-data | ✅ 완료 |
| ✅ | **ci: Harbor 레지스트리** (v2.15.2, HTTP, 7컴포넌트 healthy) | fb-ci-harbor | ✅ 완료 |
| ✅ | **ci: GitHub Actions 러너** (myoung34, PAT 자동등록, "Listening for Jobs") | fb-ci-harbor | ✅ 완료 |
| ✅ | **CI/CD 파이프라인** (push→build→**Trivy 게이트**→Harbor push→fb-app-ai 배포→헬스체크) | fb-ci→fb-app-ai | ✅ 완료 |
| ✅ | **data 티어 배포** (공유 PG+앱 OLTP DB분리 · ES nori · Redis · Kafka KRaft · exporter 4) | fb-data | ✅ 완료 (§2.1) |
| later | **app 배포** (FastAPI) | fb-app-ai | 🚧 chat-service 추가(PR 대기, §6.1 포트 참고) |
| future | K8s 이전 (하이브리드: DB 외부 + Kafka/앱은 K8s) | — | ⬜ 조건부 |

### 6.1 fb-app-ai 포트 레지스트리

> 리버스 프록시 부재 — 서비스마다 raw host port 직접 바인딩(`docker run -p`). 새 서비스 추가 시 여기 먼저 확인·갱신.

| 포트 | 서비스 | 컨테이너명 | 상태 |
|---|---|---|---|
| 8000 | ci-sample (CI/CD 검증용) | `ci-sample` | ✅ 배포됨 |
| 8001 | chat-service (RAG 챗봇 MVP) | `chat-service` | 🚧 PR 대기 |

---

## 7. 알려진 이슈 · Follow-up

- **템플릿 미포함(agent/docker)**: 템플릿 9001은 3.5G라 docker 베이킹 폐기 → **공통 설정은 Ansible이 담당**(재현성=플레이북 재실행).
- **Terraform 재생성 시 agent-hang**: 새 VM은 Ansible 실행 전까지 guest-agent가 없어 `terraform apply`가 agent 대기로 지연됨. 완전 해소하려면 **cloud-init 스니펫으로 agent만 first-boot 설치**(미적용).
- **`sda` 250GB 미사용**: 구 Windows. DB IO 격리/백업/확장 후보 (미결정).
- **백업 없음**: cross-host-backup 제거됨. 필요 시 `sda`나 외부 타깃으로 별도 설계.
- **취약점 스캔**: ✅ **CI 워크플로에 Trivy 게이트** 추가 — 빌드 직후 · push **전**에 `aquasec/trivy:0.72.0 image` 스캔(버전 핀 고정), **CRITICAL(fixable) 발견 시 파이프라인 실패**(취약 이미지 Harbor 반입 차단). 러너에서 컨테이너로 실행 → **Harbor RAM 부담 0**, DB는 `trivy-cache` 볼륨에 캐시. HIGH는 리포트만(비차단). **Harbor 통합 스캔**(레지스트리 scan-on-push)은 RAM 이유로 여전히 미포함(추후 `--with-trivy`, ~1GB+).
- **GitHub 러너**: ✅ 배포·등록 완료(Listening for Jobs). 등록 끝났으니 **PAT는 폐기 가능**(러너는 자체 자격증명 사용).
- **Prometheus 설정 반영 = 재생성**: `prometheus.yml`은 단일파일 bind-mount인데 Ansible이 원자적 rename으로 교체 → 컨테이너가 옛 inode를 물어 `/-/reload`가 무력. monitoring 롤이 **설정 변경 시 `--force-recreate prometheus`**로 반영(자동). loki/tempo 설정도 동일 특성(변경 시 해당 컨테이너 재생성 필요).
- **TLS**: ✅ Harbor·Grafana에 **로컬 CA HTTPS** 적용. 전 VM이 CA 신뢰(시스템+docker) → **insecure-registries 불필요**, docker push/pull이 HTTPS로 동작. **CA 키(`infra/certs/*.key`)는 gitignore** — 재발급하려면 CA 키 보유자 필요(팀 공유는 별도). **팀원 CA 설치법: [`ca-setup.md`](./ca-setup.md)** (WSL Ubuntu 매뉴얼) — `ca.crt`만 배포.

---

*이 문서는 인프라 상태 변경 시 갱신하세요. 세부 설계 근거는 [`design.md`](./design.md), 데이터소스 검증은 [`data-validation.md`](./data-validation.md).*
