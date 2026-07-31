# 모니터링 운영 가이드 (담당자용) — ⛔ SUPERSEDED

> ## ⛔ 이 문서는 폐기됐다 (2026-07-31, P4). 운영 지침으로 쓰지 말 것.
>
> 여기 적힌 것은 **`.11`(fb-monitoring) VM 위의 Docker Compose LGTM 스택** 이야기다.
> 그 VM 은 모니터링 컷오버(2026-07-30) 후 **2026-07-31 에 파괴**됐고, 이 문서가 코드 참조처로
> 가리키던 `infra/ansible/roles/monitoring` 롤도 **같은 날 삭제**됐다.
> 아래 접속 정보(`https://192.168.0.11:3000` 등)는 **전부 죽은 주소**다.
>
> **현행 정본**
> | 찾는 것 | 지금 어디 |
> |---|---|
> | 접속·조회·장애대응 | [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md) **§4.0** — 내부 도구 6종 = `https://<이름>.mealbong.cloud` (내부 게이트웨이 `.15`) |
> | 스택 구성(Prometheus·Grafana·Alertmanager) | `infra/ansible/roles/k8s_observability` (kube-prometheus-stack) |
> | 로그·트레이스(Loki·Tempo·Alloy) | config 레포 `platform/` — ArgoCD Application, platform AppProject |
> | 대시보드 13종 | config 레포 `monitoring/dashboards/` → CM `app/mp-grafana-dashboards` |
> | 알람 규칙 | config 레포 `monitoring/rules.yaml`·`rules-physical.yaml` + 컴포넌트별 `monitoring.yaml` (PrometheusRule CR, `Mp` 접두사) |
> | 호스트 C(`.10`) 에이전트 | `infra/ansible/roles/monitoring_agents` — **존치**. alloy 가 `https://loki.mealbong.cloud` 로 송신 |
>
> 아래 원문은 **이력 참고용**으로만 남긴다.

---

> 온프렘 LGTM 스택 조작·조회·트러블슈팅. 인프라 전반은 [`docker-infra-status.md`](./docker-infra-status.md), 코드는 [`infra/ansible/roles/monitoring*`](../infra/ansible/roles).
> 최종 갱신: 2026-07-16

---

## 0. 30초 요약

- **Grafana 접속**: **https://192.168.0.11:3000** (로컬 CA HTTPS — 브라우저 경고 없애려면 `infra/certs/ca.crt` 임포트) · 최초 `admin`/`admin` → 변경
- **로그 보고 싶다** → Grafana 좌측 **Explore** → 데이터소스 **Loki** → `{host="fb-data"}`
- **메트릭(CPU/메모리/디스크)** → Explore → **Prometheus** → 아래 §4 쿼리
- **트레이스** → Explore → **Tempo** (⚠️ 앱이 아직 없어 데이터 없음 — 앱 배포 후)

---

## 1. 구조 — 뭐가 어디서 도나

```
[전 VM: fb-data/.8 · fb-app-ai/.9 · fb-ci-harbor/.10 · fb-monitoring/.11]
   node-exporter(:9100)  ─ 호스트 메트릭(CPU/메모리/디스크)
   cAdvisor(:8080)       ─ 컨테이너별 메트릭
   Alloy(:12345)         ─ 컨테이너 로그 수집 ──┐
                                                │
[fb-monitoring/.11 = 중앙]                      │
   Prometheus(:9090) ◀── 위 node/cadvisor 스크레이프(30s)
   Loki(:3100)       ◀───────────────────────┘ (로그 저장)
   Tempo(:3200, OTLP :4317/:4318)  ◀── 앱 트레이스(향후)
   Grafana(:3000)    ── Prometheus/Loki/Tempo 를 한 화면에

[fb-data/.8 = 데이터 파이프라인]
   poller(host cron) ── textfile metrics ──▶ node-exporter
   retail-refiner(:9401) / deal-notifier(:9402)
   recipe-refiner(:9403) / deal-pruner(:9404) ──▶ Prometheus
```

전부 **Docker 컨테이너**. 중앙 스택은 `/opt/monitoring/`, 에이전트는 `/opt/monitoring-agents/`.

---

## 2. 접속 (fb-monitoring = 192.168.0.11)

| 도구 | URL | 용도 |
|---|---|---|
| **Grafana** | https://192.168.0.11:3000 | 메인 대시보드/조회 (여기만 봐도 됨) · 로컬 CA HTTPS |
| Prometheus | http://192.168.0.11:9090 | 메트릭 원본·타깃 상태 (`/targets`) |
| Loki | http://192.168.0.11:3100 | 로그 API (보통 Grafana 통해) |
| Tempo | http://192.168.0.11:3200 | 트레이스 API |

---

## 3. Grafana 사용법 (핵심)

1. **로그인** → 최초 `admin`/`admin`, 즉시 새 비번 설정.
2. **로그 보기**: 좌측 **Explore**(나침반 아이콘) → 상단 데이터소스 **Loki** 선택 → 쿼리 입력(§4) → Run.
3. **메트릭 보기**: Explore → **Prometheus** → PromQL(§4).
4. **대시보드 추가**(추천, 직접 안 짜도 됨): 좌측 **Dashboards → New → Import** → 아래 ID 입력 → 데이터소스 Prometheus 선택:
   - **1860** — Node Exporter Full (호스트 CPU/메모리/디스크/네트워크)
   - **193** 또는 **14282** — cAdvisor (컨테이너별 리소스)
   - (Loki 로그 대시보드 **13639**)

---

## 4. 자주 쓰는 쿼리 (복붙용)

**로그 — LogQL (Loki)**
```logql
{host="fb-data"}                          # 특정 VM 전체 로그
{container="harbor-core"}                 # 특정 컨테이너
{host="fb-ci-harbor"} |= "error"          # error 포함만
{project="monitoring"}                    # compose 프로젝트별
{host="fb-app-ai"} | json                 # JSON 로그 파싱
```
라벨: `host`(VM), `container`(컨테이너명), `project`(compose).

**메트릭 — PromQL (Prometheus)**
```promql
# 물리 하이퍼바이저(.12) 온도 — temp1=CPU Package, temp2~9=Core 0~7, nouveau chip=GPU
node_hwmon_temp_celsius{job="hypervisor"}
# 각 센서의 자체 한계치 대비 여유(°C). 음수면 이미 경고선 초과
node_hwmon_temp_max_celsius{job="hypervisor"} - on(instance, chip, sensor) node_hwmon_temp_celsius{job="hypervisor"}
# 호스트 CPU 사용률(%)
100 - (avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
# 메모리 사용률(%)
(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100
# 루트 디스크 여유(GB)
node_filesystem_avail_bytes{mountpoint="/"} / 1e9
# 컨테이너 메모리 사용(상위)
topk(10, container_memory_usage_bytes{name!=""})
# 컨테이너 CPU
rate(container_cpu_usage_seconds_total{name!=""}[5m])

# 데이터 파이프라인 poller 마지막 실행 결과·freshness
fb_poller_last_run_success
time() - fb_poller_last_success_timestamp_seconds
# Kafka consumer lag
sum by(consumergroup, topic) (kafka_consumergroup_lag)
# consumer 처리·저장 결과
rate(fb_pipeline_records_total[5m])
rate(fb_pipeline_sink_writes_total[5m])
```

Grafana의 **02 Data Pipeline**은 poller 실행·freshness → Kafka 유입·lag → consumer 처리 → PG/Redis 저장·item 매칭 품질 순서로 조사합니다.

---

## 5. 운영 작업 (조작)

**상태 확인**
```bash
# Prometheus 타깃 up/down (pipeline consumer 추가로 개수는 구성에 따라 달라짐)
curl -s http://192.168.0.11:9090/api/v1/targets | grep -o '"health":"[a-z]*"' | sort | uniq -c
# Loki가 로그 받고 있나 (host 라벨 목록)
curl -s "http://192.168.0.11:3100/loki/api/v1/label/host/values"
# 컨테이너 상태 (VM 접속)
ssh ubuntu@192.168.0.11 'docker ps'
```

**재시작 / 재배포**
```bash
# 컨테이너 하나 재시작 (예: grafana)
ssh ubuntu@192.168.0.11 'cd /opt/monitoring && docker compose restart grafana'
# 전체 모니터링 스택 재적용 (코드 기준, 멱등)
cd infra/ansible && ansible-playbook site.yml --limit fb-monitoring
```

**데이터 파이프라인 계측 배포 순서**
1. 새 pipeline/kurly 이미지를 Harbor에 배포하고 fb-data의 상주 consumer와 poller cron을 갱신합니다.
2. `ansible-playbook site.yml --limit fb-data`로 node-exporter textfile collector를 활성화합니다.
3. `ansible-playbook site.yml --limit fb-monitoring`으로 scrape job·알림 규칙·02 대시보드를 반영합니다.

2·3을 먼저 적용하면 아직 열리지 않은 `:9401~:9404` target이 DOWN으로 보이므로 애플리케이션 이미지를 먼저 반영합니다.

**설정 변경** (⚠️ 중요)
1. 코드 수정: `infra/ansible/roles/monitoring/templates/` (prometheus.yml.j2 · loki-config.yaml.j2 · tempo.yaml.j2 등)
2. 반영: `ansible-playbook site.yml --limit fb-monitoring`
3. ⚠️ **config 파일은 bind-mount라 `docker compose up -d`만으론 재적용 안 됨** → 해당 컨테이너 강제 재생성:
   ```bash
   ssh ubuntu@192.168.0.11 'cd /opt/monitoring && docker compose up -d --force-recreate <서비스명>'
   ```

**스크레이프 타깃 추가** (새 VM/서비스 감시)
- 새 VM이면 인벤토리(`infra/ansible/inventory.ini`)에 추가 후 `ansible-playbook site.yml` → node-exporter/cAdvisor/Alloy 자동 배포 + Prometheus가 인벤토리에서 타깃 자동 생성.

---

## 6. 설정값 (retention · 리소스 제한)

**보관기간(retention)**
| 데이터 | 보관 | 설정 위치 |
|---|---|---|
| 메트릭 (Prometheus) | 15일 | `group_vars/all.yml: prometheus_retention` |
| 로그 (Loki) | 7일 | `loki-config.yaml.j2: retention_period` |
| 트레이스 (Tempo) | 기본값 | `tempo.yaml.j2` |

**컨테이너 리소스 제한** (compose `deploy.resources.limits`)
| 컨테이너 | 메모리 | CPU |
|---|---|---|
| prometheus | 1G | 1.0 |
| loki / tempo | 768M | 0.5 |
| grafana | 512M | 0.5 |
| cadvisor / alloy | 256M | 0.5 / 0.3 |
| node-exporter | 128M | 0.3 |

→ 실사용은 대부분 제한의 10~30% (여유 큼). 변경은 role의 compose.yml.j2 수정 후 재배포.

---

## 7. 트러블슈팅

| 증상 | 확인 | 조치 |
|---|---|---|
| Grafana에 로그 안 뜸 | `curl .../loki/api/v1/label/host/values` 비어있나 | 해당 VM `docker logs alloy` 확인 → Alloy 재시작 |
| Prometheus 타깃 down | Grafana Explore 또는 `/targets` | 해당 VM node-exporter/cadvisor `docker ps` → 재시작 |
| Tempo에 트레이스 없음 | 정상 (앱이 OTLP로 보내야 함) | 앱 배포 후 OTLP를 `192.168.0.11:4317`로 |
| 컨테이너 재시작 루프 | `docker ps` STATUS=Restarting | `docker logs <name>` 로 원인 → 대개 config 오류 |
| 디스크 참 | Prometheus/Loki 데이터 증가 | retention 축소 or 디스크(`/var/lib/docker`) 확인 |

---

## 8. 코드로 관리 (IaC)

| 대상 | 위치 |
|---|---|
| 중앙 스택 (Prom/Loki/Tempo/Grafana) | `infra/ansible/roles/monitoring/` |
| 에이전트 (node-exporter/cadvisor/alloy) | `infra/ansible/roles/monitoring_agents/` |
| 배포 | `cd infra/ansible && ansible-playbook site.yml` |

**절대 서버에서 직접 손대지 말 것** — `/opt/monitoring/*`는 Ansible이 덮어씁니다. 항상 role의 `templates/` 수정 → `ansible-playbook`.

---

*질문/변경은 인프라 담당(team6)에게. 상위 인프라 현황은 [`docker-infra-status.md`](./docker-infra-status.md).*
