# Docker 인프라 현황 (온프렘 · Proxmox) — ⛔ SUPERSEDED

> ## ⛔ 이 문서는 폐기됐다 (2026-07-31, P4). 운영 지침으로 쓰지 말 것.
>
> 여기 적힌 것은 **Proxmox 4-VM 위의 Docker Compose 스택** 이야기다.
> 그중 `.8`(fb-data)·`.9`(fb-app-ai)·`.11`(fb-monitoring) 은 **2026-07-31 에 전부 실물 파괴**됐고,
> 이 문서가 코드 참조처로 가리키던 `monitoring`·`data_tier`·`data_pipeline`·`tfstate_db` 롤도 **같은 날 삭제**됐다.
> 아래 §2·§2.1·§3·§4·§6 의 주소(`192.168.0.8:5432`·`https://192.168.0.11:3000` 등)는 **전부 죽은 주소**다.
> Terraform state 도 **S3(`mp-backup-ap2`)로 이관**됐다 — 여기 적힌 PG 원격 backend(fb-data `terraform_state`)는 2026-07-29 폐기.
>
> **살아 있는 것은 호스트 C(`.10`)와 물리 하이퍼바이저(`.12`) 뿐이고, 그 내용은 아래 표대로 승계됐다.**
>
> **현행 정본**
> | 찾는 것 | 지금 어디 |
> |---|---|
> | 인프라 전반 (목표 아키텍처·구축 현황) | [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md) — **SSOT** |
> | **호스트 C(`.10`)** 구성·적용 롤·호스트 포트·백업·운영 함정 *(구 §3·§4·§7 의 Harbor·CI·TLS 분)* | [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md) **§4.1** |
> | **하이퍼바이저(`.12`)** — Ansible 경계(`hosts: vms` 지뢰)·온도 감시 *(구 §1·§1.1)* | [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md) **§4.1 "하이퍼바이저"** |
> | 접속 정보 (호스트 C SSH · Harbor 직결 · Proxmox 웹 UI) | [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md) **§4.0** |
> | 데이터 티어 (PG·ES·Redis·Kafka — 구 §2.1) | 인클러스터 오퍼레이터 = `mp_k8s_infra_status.md` **§2.1** (CNPG·ECK·Strimzi·Redis) |
> | 앱 스택·포트 레지스트리 (구 §6.1) | K8s `app` ns + 공개 Gateway `.14` — config 레포 `services/`·`gateway/` |
> | 모니터링 스택·접속 (구 §4 의 Grafana·Prometheus·Loki·Tempo) | `mp_k8s_infra_status.md` **§4.0** — `https://<이름>.mealbong.cloud` (내부 GW `.15`) |
> | Terraform state backend | **S3 `mp-backup-ap2`** — `infra/terraform/backend.tf` (2026-07-29 이관) |
> | 사고 이력·근인 분석 (구 §7) | **이 문서 원문**(아래) 이 유일 기록 · 재발방지 수칙 요약 = `mp_k8s_infra_status.md` **§3** |
>
> 아래 원문은 **이력 참고용**으로만 남긴다.

---

> ⚠️ **이 문서는 인프라 SSOT가 아니다.** 인프라 SSOT = **[`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md)** (2026-07-24 이관).
>
> **다만 지금 실제로 돌아가는 것은 여기 적힌 Docker compose 스택이다** — 단 **CI 는 예외**: 2026-07-27부터 CI 는 신규 물리 호스트 C(`.10` 승계)의 Jenkins 가 수행하고, 구 fb-ci-harbor VM(러너·구 Harbor)은 정지·파괴 예정이다. **오늘의 운영·장애대응·접속은 이 문서를 본다.** 컷오버(P4, [`mp_k8s_infra_migration_plan.md §10`](./mp_k8s_infra_migration_plan.md)) 완료 시 이 문서는 폐기한다.
>
> | 용도 | 문서 |
> |---|---|
> | 인프라 SSOT (목표 아키텍처·구축 현황) | [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md) |
> | 이전 결정·근거·컷오버 절차 | [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md) |
> | **현행 운영 레퍼런스 (지금 돌아가는 것)** | **이 문서** |
>
> 최종 갱신: **2026-07-23** · 설계 정본: [`design.md §8.4`](./design.md) · IaC: [`infra/`](../infra) · **모니터링 운영: [`monitoring-ops.md`](./monitoring-ops.md)**

## 한눈에 요약

| 항목 | 상태 |
|---|---|
| Proxmox 호스트 | ✅ 가동 (standalone, 클린) |
| 4-VM 프로비저닝 (Terraform) | ✅ 완료, 전부 running |
| 공통 설정 (Ansible: agent·Docker·디스크) | ✅ 완료, 4대 검증 |
| 서비스 배포 | 🚧 진행 중 — **monitoring LGTM**(Prom+Grafana+Loki+Tempo+Alloy) + **Harbor** + **data 티어**(PG·ES·Redis·Kafka) 배포·검증 완료 |
| Terraform state | ✅ **PG 원격 backend** (fb-data, 공유·잠금) |
| CI (Jenkins, 호스트 C `.10`) | ✅ **전환 완료** (2026-07-27) — GH Actions 러너 은퇴, 구 fb-ci-harbor VM 파괴 예정 |
| K8s 이전 | 📋 **계획 확정** — 앱 먼저 P0~P4, SSOT = [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md) *(구 "하이브리드 방향" 서술은 폐기)* |

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
| 클론 템플릿 | **`9002` ubuntu-2404-template-agent** (cloud-init + **qemu-guest-agent 사전설치**) — Terraform 이 사용하는 정본. `9001` 은 원본 보존(롤백용) |
| 네트워크 브리지 | `vmbr0`(물리 업링크·관리망 192.168.0.0/24) + **`vmbr1`(host-only 내부망 10.10.10.0/24, host=10.10.10.1)** — vmbr1은 Terraform 관리(`proxmox_network_linux_bridge.internal`) |
| 감시 | **node-exporter(네이티브 apt, `:9100`)** — 2026-07-22 추가. Prometheus job `hypervisor`. 온도·팬·디스크. Ansible = `hypervisor.yml`(site.yml **아님**, 아래 ⚠️) |

### 1.1 하이퍼바이저는 Ansible `site.yml` 대상이 아니다 🔴

`.12` 는 인벤토리 **`[hypervisor]`** 그룹이고, site.yml 의 전-호스트 플레이는 `hosts: all` 이 아니라 **`hosts: vms`** 를 쓴다. `all` 은 Ansible 이 인벤토리의 모든 호스트를 자동 포함하는 암묵 그룹이라 `[all:children]` 에서 빼는 것으로는 못 막기 때문이다.

**막지 않으면 무슨 일이 나나** — `base` 롤이 하이퍼바이저에 Docker 를 깔고, 더 나쁘게는 `group_vars/all.yml` 의 `docker_data_disk: /dev/sdb` 를 전용 디스크로 잡는다. `.12` 에서 `/dev/sdb` 는 **VM 4대 스토리지가 전부 올라간 `pve` VG 디스크**다. 3중으로 막아뒀다 — ① `hosts: vms` ② `base` 롤 선두의 `assert`(hypervisor 그룹이면 실패) ③ `group_vars/hypervisor.yml` 에서 `docker_data_disk` 무효값 덮어쓰기.

```bash
ansible-playbook hypervisor.yml        # .12 전용 (node-exporter)
ansible-playbook site.yml              # VM 4대 전용 (.12 는 안 닿음)
```

**발열 감시 (2026-07-19·07-21 급사 후속)**: Prometheus job `hypervisor` → `node_hwmon_temp_celsius`.
센서 해독 — `chip=platform_coretemp_0`: `temp1`=Package, `temp2`~`temp9`=Core 0~7 / `chip=0000:00:01_0_…`: nouveau GPU(GTX 1060).
알람은 임계값을 하드코딩하지 않고 **각 센서가 스스로 보고하는 한계치**(`node_hwmon_temp_max_celsius` = CPU 80·GPU 95, `node_hwmon_temp_crit_celsius` = CPU 100·GPU 105)에 맞춘다 → `HypervisorTempHigh` / `HypervisorTempCritical` / `HypervisorTempCritAlarm`.

> ⚠️ **급사 자체는 이 알람으로 통보받을 수 없다.** Prometheus·Alertmanager 가 `.12` 위의 VM 이라 호스트가 죽으면 같이 죽는다. 얻는 것은 ① 급사 *전* 온도 상승 경고 ② 재부팅 후에도 남는 **급사 직전 온도 곡선**(TSDB 는 fb-monitoring VM 디스크에 영속)이다. `HypervisorExporterDown` 은 호스트는 살아있고 exporter 만 죽은 경우용.

---

## 2. VM 현황 (4-VM)

전부 **Ubuntu 24.04**, running. 역할·위치는 `design.md §8.4` 기준.

| VM | vmid | IP | 내부IP | vCPU | RAM | 벌룬 | OS디스크 | docker디스크 | 담는 역할 |
|---|---|---|---|---|---|---|---|---|---|
| **fb-data** | 201 | `.8` | `10.10.10.8` | 4 | 8GB | off(고정) | 100G | 40G (`/dev/sdb`) | PostgreSQL·Elasticsearch·Redis·Kafka |
| **fb-app-ai** | 202 | `.9` | `10.10.10.9` | 6 | 7GB | on(≥4G) | 80G | 30G | FastAPI 7개·ML 서빙·크롤러 |
| ~~**fb-ci-harbor**~~ | 203 | ~~`.10`~~ | `10.10.10.10` | 3 | 5GB | on(≥3G) | 150G | 70G | ⚠️ **은퇴 수순**(2026-07-27) — Harbor·CI 가 신규 물리 호스트 C 로 이관(`.10`·인증서 승계). 구 이미지(`food-budget/*`)는 VM 파괴와 함께 소멸(백필 안 함). 파괴 후 5GB 회수 → worker-a1 재원. 🔴 **terraform 추적 제외**(`state rm`, 2026-07-27) — 정지 상태를 코드가 "켜져 있어야 한다"로 되돌려 `.10` 을 호스트 C 와 다투는 사고를 막기 위함. **tfvars 에 되살리지 말 것**, 파괴는 수동 |
| **fb-monitoring** | 204 | `.11` | `10.10.10.11` | 3 | 6GB | on(≥4G) | 100G | 40G | Prometheus·Loki·Tempo·Grafana |
| **합계** | | | | 16 | **26GB** | | | | RAM 여유 ~5GB + swap 8G |

**내부망(vmbr1, 2026-07-20 적용·4대 검증):** 전 VM에 두 번째 NIC(net1) — host-only `10.10.10.0/24`(끝자리 미러링, host=`.1`). **gateway 없음**(기본 라우트는 vmbr0 유지 — 단절 방지). ⚠️ **add-only 단계**: 서비스 엔드포인트(Kafka advertised·Prometheus 타깃·Harbor URL 등 ~20개 파일)는 여전히 `192.168.0.x` — 내부망 이전은 별도 작업.

**리소스 안전장치:** RAM 무오버커밋(26≤31) · fb-data만 벌룬 off(DB 보호) · thin 풀 610/643G(무오버프로비전) · **JVM heap 캡 적용(ES·Kafka 각 512m)** · 전 컨테이너 mem/cpu limit · **retention 적용 완료** — Prometheus 15d · Loki 168h · **Tempo 168h**(2026-07-23 신설, §7 OOM 사고 후속. 이전엔 tempo 만 무제한이라 기본 336h 로 쌓였다).

### 2.1 데이터 티어 (fb-data, Docker compose) — ✅ 배포·검증 완료

| 서비스 | 이미지 | mem limit | 포트 | 비고 |
|---|---|---|---|---|
| **PostgreSQL(공유)** | postgres:16-alpine | 1.5G | 5432 | DB 2개 — `terraform_state`(state backend) + `foodbudget`(앱 OLTP, `fbapp` 롤). **같은 인스턴스, DB만 분리** |
| **Elasticsearch** | ES 8.15.3 + **nori**(로컬빌드 커스텀 이미지) | 1.5G | 9200 | single-node · security off(내부망) · heap 512m · **cpu 1.5**(실측 84.5%, 압박은 off-heap이라 힙 아닌 컨테이너 상한↑) · green |
| **Redis** | redis:7-alpine | 320M | 6379 | 캐시(LRU 256mb·비영속) |
| **Kafka** | apache/kafka:3.9.0 | 1.0G | 9092 | **KRaft 단일노드**(ZK 없음) · heap 512m · **cpu 2.0**(스로틀 최다) · **`KAFKA_LOG_DIRS=/var/lib/kafka/data`**(볼륨 실사용 — 미설정 시 recreate로 토픽 전멸, §7) · advertised=192.168.0.8 |
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
| **fb-ioburst 워처** | ✅ 4대 상주 (**임시 진단** — 디스크 읽기 폭주 범인 포착, §7) · 롤 `ioburst_watch` |

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
http://192.168.0.11:9090   # Prometheus (내부, 타깃 34/34 up — VM 4대 + 하이퍼바이저)
http://192.168.0.11:3100   # Loki (내부, 4대 수집)
http://192.168.0.11:3200   # Tempo (내부, OTLP :4317/:4318)

# 데이터 티어 (fb-data, 내부 — 앱이 소비)
192.168.0.8:5432   # PostgreSQL — DB: foodbudget(앱 OLTP) / terraform_state(state)
http://192.168.0.8:9200    # Elasticsearch (nori)
192.168.0.8:6379   # Redis (캐시)
192.168.0.8:9092   # Kafka (KRaft)
```
> SSH는 (초기) cloud-init 주입키 + (운영) **Ansible `team_ssh_keys`**. 팀원 추가 = 공개키를 `infra/ansible/roles/team_ssh_keys/files/<이름>.pub`에 넣고 `ansible-playbook site.yml --tags team_keys` (**additive** — 기존 키 보존). 초기 클론 주입은 `infra/terraform/terraform.tfvars`.

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
ansible vms -m ping            # VM 4대 연결 확인 (`all` 은 하이퍼바이저까지 포함됨)
ansible-playbook site.yml      # agent·Docker·디스크 — VM 4대 전용
ansible-playbook hypervisor.yml # .12 물리 호스트 (node-exporter 온도감시)

# 특정 롤만 좁혀 돌리기 (base 롤이 docker 데몬을 재시작하므로)
ansible-playbook site.yml --tags ioburst   # 디스크 폭주 워처만
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
| ~~✅~~ | ~~**ci: GitHub Actions 러너** (myoung34, PAT 자동등록, "Listening for Jobs")~~ | ~~fb-ci-harbor~~ | 🔴 **은퇴**(2026-07-27 Jenkins 이관 → 2026-07-31 `github_runner` 롤 삭제) |
| ✅ | **CI/CD 파이프라인** (push→build→**Trivy 게이트**→Harbor push→fb-app-ai 배포→헬스체크) | fb-ci→fb-app-ai | ✅ 완료 |
| ✅ | **data 티어 배포** (공유 PG+앱 OLTP DB분리 · ES nori · Redis · Kafka KRaft · exporter 4) | fb-data | ✅ 완료 (§2.1) |
| ✅ | **app 배포** (FastAPI 8[chat 포함] + nginx, compose `foodbudget`) | fb-app-ai | ✅ 완료 — `deploy/app/`, §6.1 |
| future | K8s 이전 (하이브리드: DB 외부 + Kafka/앱은 K8s) | — | ⬜ 조건부 |

### 6.1 fb-app-ai 포트 레지스트리

> **앱 스택 = compose 프로젝트 `foodbudget` + nginx 리버스 프록시** (배포 = `deploy/app/`). FastAPI 8개 + 프론트는 내부망 `fbnet` 에서 서비스명 DNS 로만 통신 — **호스트 포트 미노출**. 호스트로 나오는 앱 포트는 nginx `:80` 하나(SPA + `/api/*` 라우팅). 새 **앱** 서비스는 내부 포트만 배정(호스트 충돌 없음); 호스트 포트를 새로 여는 것(별도 컨테이너·에이전트)만 아래 표 확인·갱신.

**호스트 publish 포트**

| 포트 | 서비스 | 컨테이너 | 상태 |
|---|---|---|---|
| **80** | **앱 게이트웨이** — nginx (SPA + `/api/*` 리버스 프록시 → 백엔드) | `foodbudget-frontend-1` | ✅ 배포됨 |
| 8080 | cAdvisor (컨테이너 메트릭) | `cadvisor` | 모니터링 에이전트 |
| 9100 | node-exporter (호스트 메트릭, host-net) | `node-exporter` | 모니터링 에이전트 |
| 12345 | Alloy (로그·트레이스 수집) | `alloy` | 모니터링 에이전트 |

**compose 내부 포트** (호스트 미노출 · nginx `/api/*` → `서비스명:포트`)

| 포트 | 서비스 | 포트 | 서비스 |
|---|---|---|---|
| 8001 | recipe | 8005 | pantry |
| 8002 | price | 8006 | recipebook |
| 8003 | chat | 8007 | mealplan |
| 8004 | account | 8008 | notify |

> **은퇴** — ~~8000 ci-sample~~ (CI/CD 검증 샘플, 실 파이프라인 `build-push-app` 이 대체 → 컨테이너·`build-push.yml`·`ci-sample/` 제거) · ~~8001 chat-service standalone~~ (compose 로 편입, 내부 8003 → 컨테이너·`build-push-chat.yml` 제거). 호스트 `:8000`·`:8001` 미사용.

---

## 7. 알려진 이슈 · Follow-up

- **⚠️ terraform apply = 게스트 재부팅 유발(cloud-init 변경 시)**: VM의 `initialization` 변경은 게스트를 재부팅시킨다. **2026-07-19 사고**: apply발 재부팅이 fb-app-ai의 커널 업데이트(initramfs 재생성) 도중에 걸려 initrd 파손 → GRUB은 ext4 저널을 재생하지 못해 부팅 행(호스트에서 `kpartx`+`fsck`로 복구, 데이터 손실 0). 또한 fb-data 재부팅 중 PG(=terraform state backend)가 내려가 state 저장 실패(`state push`로 화해). **교훈**: VM 스펙 변경 apply는 유지보수창에서 + 게스트 unattended-upgrade 미실행 확인 후.
- **⚠️ Kafka `KAFKA_LOG_DIRS` 미배선 → recreate 시 토픽 전멸(해소 2026-07-21, PR #271)**: compose 에 `kafka_data` 볼륨은 붙어 있었으나 `KAFKA_LOG_DIRS` 미설정으로 apache/kafka 기본값(`/tmp/kraft-combined-logs`=컨테이너 FS)에 저장 → **볼륨은 2024-10-26 이후 텅 빈 채**였다. restart 는 살아남지만 **recreate 하면 토픽 전소**(2026-07-21 리소스 상향발 recreate 로 토픽 4개 전멸 → `create_topics.py` 재생성 복구, 직전 lag 0·크롤러 미실행이라 데이터 유실 0). `KAFKA_LOG_DIRS=/var/lib/kafka/data` 명시로 해소, 적용 후 볼륨에 `__cluster_metadata`·`__consumer_offsets` 실적재 확인.
- **Harbor 재부팅 자동기동 실패 → systemd 유닛(해소 2026-07-21, PR #270)**: 호스트 재부팅 시 Harbor 9개 중 harbor-log 만 살고 나머지 8개가 Exited(128) — 로깅 드라이버(syslog→harbor-log:1514) 경합. Docker 가 restart:always 를 **동시** 기동해 harbor-log 리스닝 전에 나머지가 뜨며 **생성 단계** 실패(compose depends_on 은 부팅 자동재시작 경로에 미적용). 실피해=재부팅 때마다 CI 'Harbor 로그인' 스텝 실패. `harbor.service`(Type=oneshot, docker.service 이후 `compose up -d` + RemainAfterExit)로 depends_on 순서 보장 → fb-ci-harbor 실재부팅으로 9개 Up 검증. **단독 배포 태그**: `--tags harbor` / `--tags data_tier`(site.yml 롤에 태그 추가 — base 롤이 docker 데몬 재시작하므로 좁혀 돌릴 수 있게).
- **템플릿 미포함(docker)**: 템플릿은 3.5G라 docker 베이킹 폐기 → **공통 설정은 Ansible이 담당**(재현성=플레이북 재실행). *(agent 는 아래대로 템플릿에 포함으로 전환)*
- ~~**Terraform 재생성 시 agent-hang**~~ → **해소(2026-07-21)**: 새 VM 은 Ansible 실행 전까지 guest-agent 가 없는데 `terraform apply` 는 agent 의 IP 리포팅을 기다려 **최대 30분(프로바이더 생성 타임아웃) 행**이었다(agent 를 설치하는 base 롤은 apply 이후에나 도는 닭과 달걀). **템플릿에 agent 사전설치**로 전환 — 9001 을 full clone 한 **9002**(`ubuntu-2404-template-agent`)에 `qemu-guest-agent` 설치 후 `cloud-init clean` + 호스트키·machine-id 초기화하여 재템플릿화. `template_vmid = 9002`. **실측 41초**(신규 VM 생성 → agent IP 리포팅 → 완료). 기존 4대는 `lifecycle { ignore_changes = [clone] }` 로 무영향(`terraform plan` = No changes 확인). 롤백 = `template_vmid` 를 9001 로 되돌리면 즉시.
- **🔴 물리 호스트 `.12` 무흔적 급사 3회 — 원인 미확정**: 2026-07-19 17:03 · 07-21 18:09:45 · **07-21 23:49:52**(KST — 게스트 `journalctl --list-boots` 의 boot 종료시각 기준. 종전 기록 "23:30" 은 `sar` 10분 샘플의 14:40→22:53 공백을 뭉뚱그린 값이었다). 세 번 다 패닉·OOM·MCE·I/O 에러 없이 로그가 그냥 끊기고, 다음날 아침까지 8~15시간 꺼져 있었다(수동 전원 투입). *(그 사이 07-21 19:24 종료는 정상 셧다운 — `journalctl --list-boots` 만 보면 4회로 오독한다.)* 유력 후보였던 **발열은 근거가 약해졌다** — 냉각 작업 후 유휴 90→71→**07-22 51°C**(부하 시 68°C, 경고선 80)로 안정됐고 thermal throttle·MCE 기록이 0건이다. **07-21 23:49 급사의 실피해** = redis-pgsync AOF 손상 → PGSync 16시간 정지(`docs/pgsync-adoption.md §운영 사고`). **07-22 부터 `.12` 온도 감시 가동**(위 §1.1) → 다음 급사 때는 직전 온도 곡선이 남는다. ⚠️ 단 **급사 실시간 통보는 구조적으로 불가**(Prometheus 가 `.12` 위의 VM).
  - **연속 감시 첫 실측(2026-07-23)**: 유휴 평균 **61~67°C**(순간 스파이크 75~79 — coretemp 순간값 샘플링), 이상부하 시 평균 **78.4°C·최대 88°C**. `_crit_`=100 이라 **열보호 셧다운 임계엔 미달** → 발열로 급사를 설명하기는 여전히 어렵다. *(07-22 16:30 의 51°C 는 유휴 스팟 측정값 — 연속 곡선은 그보다 높게 나온다. 시각·실온 차이.)* 단 i7-10700F 유휴 정상치(30~45°C)보다는 확실히 높아 냉각 여유가 얇다.
  - **급사 시각 소급 확인 = 게스트 `sar` 공백**(방법은 아래 폭주 항목): 07-19 08:03→23:29 UTC(15.4h) · 07-21 09:00→09:18(18분) · 07-21 14:40→22:52(8.2h) — 기록된 3회와 일치한다. ⚠️ 단 `sar` 는 10분 샘플이라 **공백의 시작이 곧 급사 시각은 아니다**(위 본문의 23:49:52 도 sar 로는 14:40 공백으로 보인다). 분 단위가 필요하면 **게스트 `journalctl --list-boots` 의 boot 종료시각**을 볼 것 — 그쪽이 정밀값이다.
- **🔴 정체불명 디스크 읽기 폭주 — 원인 미상, 조사 중(2026-07-23)**: `fb-data` `sda`(루트)에서 **390~400 MB/s · 9,230 read IOPS · util 99%** 가 **28분** 지속돼 호스트 SSD(`sdb`, WD Blue 1TB)를 포화시켰다. 쓰기는 26 IOPS 로 평소와 동일 = **순수 읽기**. 총 ~670GB 로 100GB 디스크를 7회 재독한 양인데 **페이지 캐시는 1.77→2.06GB 로 거의 안 늘었다**(메모리 여유 4.7GB) → O_DIRECT/원시 블록 읽기 추정.
  - **영향**: 전 게스트 iowait 폭증(fb-data user 3.8%·**iowait 74.9%**) + 호스트 CPU **78.4°C 평균·88°C 최대**(유휴 61~67 대비 +12~17°C). 부수적으로 **cadvisor 가 메모리한도(256MB) 초과 OOM-kill** 되어 해당 구간 컨테이너 메트릭이 통째로 비었다(**→ 2026-07-23 한도 512M 로 상향 해소.** 24h 실측 최대가 fb-app-ai 99.9%·fb-ci-harbor 93.5%·fb-data 86.9% 로 상시 한계선이었다).
  - **주기적이지 않다**: 07-21 01:50 UTC · 07-22 18:32 UTC **2회만**, 07-18·19·20·23 은 0건. 크론·systemd 타이머·컨테이너 시작·vzdump 백업 모두 해당 시각에 없음을 확인했다.
  - **크롤러 폴러는 무관 — 반증 완료**: 폴러는 매일 18:30 UTC 도는데 폭주는 07-22 에만 있었다. 자연대조(`sar -u`) — 07/20 같은 창 user 5.8%·**iowait 0.8%** vs 07/22 user 15%·**iowait 62~76%**. `poller-kurly` 자체 소비는 8분간 CPU 4분47초(≈0.6코어 = 호스트 16스레드의 ~4%), `poller-oasis` 는 58분 걸려도 CPU 6.7→8.6%(네트워크 바운드).
  - **대응**: 다음 발생을 현장에서 잡으려고 **`fb-ioburst` 워처를 VM 4대에 상주**시켰다(롤 `ioburst_watch`, `--tags ioburst`). 15초마다 전 디스크 읽기 MB/s 를 보고 **100 MB/s 초과 시** `/proc/PID/io` 5초 델타로 **범인 프로세스 + 컨테이너 ID** 를 `/var/log/fb-ioburst/burst-<ts>.txt` 에 덤프(+pidstat·iostat·PSI·docker ps·top). 상시 비용 RSS 1.2MB·CPU ~25ms. 발동 시 journal(`-t fb-ioburst`) → Alloy → Loki 로도 남는다.
  - **⚠️ 임시 도구다.** 원인 규명되면 롤 defaults 의 `ioburst_enabled: false` 로 바꿔 커밋 후 `--tags ioburst` 한 번 = 깨끗이 철수(덤프는 보존). 방치하면 IaC 에 진단 잔재가 남는다.
  - **🔎 부산물(유용)**: **게스트 `sar` 커버리지 공백 = 호스트 다운타임**. `sar -u -f /var/log/sysstat/sa<DD>` 샘플 시각의 15분 이상 공백을 찾으면 급사 시각이 나온다(게스트는 UTC). 실제로 급사 3회와 정확히 일치했고, sysstat 은 약 한 달치를 보존하므로 **`.12` 온도 감시가 없던 기간의 급사도 소급 확인 가능**하다.
- **Tempo OOM 크래시루프 (2026-07-21, 완화 완료 · retention 신설)**: 07-21 **14:48:13~14:49:41 UTC**(=23:48~23:49 KST) Tempo 가 12~13초 간격으로 **8회 OOM-kill** 됐다. 매회 `anon-rss` **781,440kB(763MiB)** 로 오차 128kB 이내 동일 — 무작위 부하가 아니라 **결정론적 기동 작업이 한도(768M)에 부딪힌** signature 이고, 재기동마다 같은 지점에서 죽어 **자력 회복이 불가능한 루프**였다. `CONSTRAINT_MEMCG` = 컨테이너 한도 초과지 호스트 메모리 부족이 아니다. 루프는 고쳐져서 끝난 게 아니라 **11초 뒤 호스트가 급사**(14:49:52)하면서 끝났다.
  - **근인 3중**: ① **Tempo 에만 보존기간 설정이 없었다** — Loki 는 `retention_period: 168h`, Prometheus 는 retention 플래그가 있는데 `tempo.yaml` 엔 압축·보존 블록이 0줄이라 기본 336h(14일)로 쌓였다(`design.md §8.4` 의 "Prometheus/Loki/Tempo retention 7~15일 캡" 이 tempo 만 미이행). ② **OTEL 샘플링 100%** — `OTEL_TRACES_SAMPLER_ARG` 기본값 1.0, `perf-infra-handoff.md` 의 0.1 권고 미적용. ③ 한도 768M. 07-21 실측 14:05 **491MiB** → 14:10 **613MiB**(5분 +122MiB)로 급증 중이었다.
  - **조치**: 한도 **2G**(서버에만 반영돼 있던 값을 레포에 정합) + `tempo.yaml` 에 **보존 168h** 신설(Loki 와 정렬) + 앱 **OTEL 샘플링 0.1**. ⚠️ Tempo 3.0 은 2.x 의 `compactor:` 최상위 키가 없다 — 압축이 `backend_scheduler`/`backend_worker` 로 분리됐고 **양쪽 모두** 지정해야 한다. 키 경로는 `/status/config` 로 확인하고 `tempo -config.verify=true` 로 검증했다.
  - **🔴 2차 피해 — 압축·보존 33시간 정지(2026-07-23 해소)**: 급사 순간 쓰이던 **블록 15개의 `meta.json` 이 0바이트**로 남아(`bloom-0`·`data.parquet`·`index` 까지 전부 0바이트 = 트레이스 0건) 블록리스트 폴러가 5분마다 실패했다 — `failed reading unknown blocks: unexpected end of JSON input`. 인덱스가 없으니 압축기·보존기가 대상 목록을 못 받아 **`tempodb_blocklist_length` 메트릭 자체가 부재**했고 압축이 "empty tenant" 로만 돌았다. Loki 기준 07-22 07:58 KST ~ 07-23 15:48 KST **384회 반복, 무알람**. 그동안 Tempo 컨테이너는 계속 `Up` 이었다.
  - **조치**: 손상 블록 15개 + 크래시 잔여 임시파일 2개를 **삭제가 아니라 `/var/tmp/tempo-corrupt-20260723/` 로 이동**(0바이트 아닌 파일이 하나라도 있으면 중단하는 가드 후 실행) → tempo 재생성. 즉시 압축 재개(L0 394·L1 84·L2 14·L3 4, `compaction_errors_total=0`), `blocklist_length=515`(디스크 실제 블록 수와 일치), 폴러 에러 0건.
  - **💡 한도 2G 가 여기서 값을 했다**: 압축 백로그를 소화하며 메모리가 **피크 836MiB** 까지 올랐다(실측). 구 한도 768M 이었다면 손상 블록을 치우는 순간 다시 OOM 이었다 — 순서가 반대였으면 크래시루프가 재발했다.
  - **관찰 대기**: `tempodb_retention_deleted_total` 이 아직 0 이다. 데이터가 07-16 부터라 168h 기준 삭제 대상이 이제 막 생겼고 백로그 처리 중이라 판단이 이르다. **하루 뒤에도 0 이면 보존이 여전히 안 도는 것** — 재조사할 것. 볼륨도 압축 중 1.4G→2.1G 로 늘었는데(원본+결과 공존, 정상) 압축 종료 후 줄어드는지 확인 필요.
  - **알람 신설(2026-07-23)**: 이 "죽지 않고 조용히 일을 안 하는" 상태를 잡는 룰이 없었다 → `alert-rules.yml` 에 **`observability-health`** 그룹 추가. `TempoBlocklistIndexBroken`(**`absent()` 기반** — 폴러가 실패하면 값이 0이 되는 게 아니라 시리즈가 사라진다. 실제 사고 구간 31시간 연속 발화 백테스트 완료) · `TempoCompactionErrors` · `ContainerMemoryNearLimit`(한도 대비 85%, 전 컨테이너 — OOM 사전 경고).
  - **남은 것**: monitoring 스택이 전부 `:latest` 무핀이라 재현성이 없다(이번 사고 기간엔 v3.0.0 로 동일했음을 `tempo_build_info` 로 확인 — 버전 점프는 원인이 아니었다). **크래시루프 알람이 Tempo 를 커버하지 않는다** — 일반 `PrometheusTargetDown`(`up==0`, `for: 1m`)은 scrape 30초 vs 재시작 12초라 놓칠 수 있고, 정작 잘 듣는 룰인 `PGSyncCrashLooping`(PR #275 — cadvisor 의 `restartcount` 라벨로 15분 창의 시계열 개수를 세는 방식. `container_start_time_seconds` 로는 못 잡는다는 실측까지 주석에 있다)은 `name=~"pgsync|redis-pgsync"` 로 한정돼 있다. **이 룰을 전 컨테이너로 일반화하면 이번 Tempo 사고도 잡혔다** — 후속 개선거리.
- **`sda` 250GB 미사용**: 구 Windows. ⚠️ **SMART 수명 96% 소진**(`Percent_Lifetime_Remain` 잔여 4%, 임계 1% — 2026-07-22 실측). VM 스토리지(`sdb`)와는 무관하고 `pve` VG 에도 없어 급사와 관계없으나, **DB IO 격리·백업 용도로 쓰기엔 부적합**하다(언제 죽어도 이상하지 않음). 활용하려면 교체 전제.
- **백업 없음**: cross-host-backup 제거됨. 필요 시 `sda`나 외부 타깃으로 별도 설계.
- **취약점 스캔**: ✅ **CI 워크플로에 Trivy 게이트** 추가 — 빌드 직후 · push **전**에 `aquasec/trivy:0.72.0 image` 스캔(버전 핀 고정), **CRITICAL(fixable) 발견 시 파이프라인 실패**(취약 이미지 Harbor 반입 차단). 러너에서 컨테이너로 실행 → **Harbor RAM 부담 0**, DB는 `trivy-cache` 볼륨에 캐시. HIGH는 리포트만(비차단). **Harbor 통합 스캔**(레지스트리 scan-on-push)은 RAM 이유로 여전히 미포함(추후 `--with-trivy`, ~1GB+).
- ~~**GitHub 러너**: ✅ 배포·등록 완료(Listening for Jobs). 등록 끝났으니 **PAT는 폐기 가능**(러너는 자체 자격증명 사용).~~
  → 🔴 **은퇴 완료**. CI 는 2026-07-27 부터 호스트 C 의 **Jenkins**(레포 루트 `Jenkinsfile`)가 수행하고, Ansible `github_runner` 롤은 **2026-07-31(P4)에 삭제**됐다(`group_vars/ci.yml` 변수 3종·`secrets.yml.example` 의 `github_runner_pat` 포함). **"PAT는 폐기 가능"은 이제 "폐기해야 한다"** — 러너가 없어 쓰이지 않지만 토큰 자체는 여전히 유효하므로 GitHub 에서 revoke 할 것.
- **Prometheus 설정 반영 = 재생성**: `prometheus.yml`은 단일파일 bind-mount인데 Ansible이 원자적 rename으로 교체 → 컨테이너가 옛 inode를 물어 `/-/reload`가 무력. monitoring 롤이 **설정 변경 시 `--force-recreate prometheus`**로 반영(자동). loki/tempo 설정도 동일 특성(변경 시 해당 컨테이너 재생성 필요).
- **TLS**: ✅ Harbor·Grafana에 **로컬 CA HTTPS** 적용. 전 VM이 CA 신뢰(시스템+docker) → **insecure-registries 불필요**, docker push/pull이 HTTPS로 동작. **CA 키(`infra/certs/*.key`)는 gitignore** — 재발급하려면 CA 키 보유자 필요(팀 공유는 별도). **팀원 CA 설치법: [`ca-setup.md`](./ca-setup.md)** (WSL Ubuntu 매뉴얼) — `ca.crt`만 배포.

---

*이 문서는 인프라 상태 변경 시 갱신하세요. 세부 설계 근거는 [`design.md`](./design.md), 데이터소스 검증은 [`data-validation.md`](./data-validation.md).*
