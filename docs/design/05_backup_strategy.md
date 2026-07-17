# food-budget-app 백업·복구 전략

> **현재 Docker: 물리 컴퓨터 1대, 내부 VM 4대**
>
> **향후 Kubernetes: 물리 컴퓨터 2대, 2노드 구성 계획**

현재는 물리 컴퓨터 한 대가 고장 나면 VM 4대가 함께 중단된다. 향후에는 앱을 두
K8s 노드에 나눠 배치해 한 대가 멈춰도 다른 한 대에서 서비스를 계속하는 것이 목표다.

## 1. 핵심 데이터

우리 서비스의 핵심은 회원, 예산·지출, 냉장고 재고, 식단·장바구니와 사용자
레시피북이다. 모두 PostgreSQL에 있고 외부에서 다시 만들 수 없으므로 최우선으로
백업·복구한다.

Elasticsearch 검색 인덱스, Kafka 수집 이벤트와 Redis 캐시는 재색인·재수집·재생성이
가능하므로 PostgreSQL보다 복구 우선순위가 낮다.

**따라서 PostgreSQL을 가장 먼저 보호하되, 현재 구축 수준에서 달성할 수 있는 값부터
단계적으로 줄인다.** 현재는 자동 백업과 복원 시험이 없어 RPO/RTO를 보장할 수 없다.

## 2. RPO/RTO 목표

- **RPO**: 장애 시 최대 얼마 동안의 데이터를 잃어도 되는가
- **RTO**: 장애 후 서비스를 몇 분 안에 다시 사용할 수 있게 할 것인가

예를 들어 `RPO 24시간 / RTO 4시간`은 최대 하루치 데이터가 손실될 수 있고,
장애 후 네 시간 안에 서비스를 복구한다는 의미다.

### 단계별 현실 목표

| 단계 | PostgreSQL RPO | PostgreSQL RTO | 전체 볼륨 RPO/RTO | 상태 |
|---|---:|---:|---:|---|
| 현재 | 측정 불가 | 측정 불가 | 측정 불가 | 독립 백업·복원 시험 없음 |
| Docker 1차 | 24시간 | 4시간 | 24시간 / 4시간 | 일일 백업·수동 복원 구축 목표 |
| Docker 자동화 후 | 1시간 | 2시간 | 1시간 / 2시간 | 증분 snapshot·복원 스크립트·훈련 필요 |
| 장기 선택 목표 | 15분 | 1시간 | 1시간 / 2시간 | WAL PITR 자동화와 반복 검증 후에만 채택 |

API·프론트엔드는 데이터 볼륨이 정상인 단순 재기동이면 15분을 목표로 한다. Redis
캐시는 복원하지 않고 빈 상태로 시작하므로 10분, ES·Kafka는 재색인·재수집을 포함해
초기 4시간에서 자동화 후 2시간을 목표로 한다.

### 15분 시점 복구가 가능한 조건

15분마다 DB 전체를 복사하는 방식이 아니다. PostgreSQL 전체 백업을 기준점으로 두고,
그 이후 변경 기록인 WAL을 계속 보관한 뒤 원하는 시각까지 재생하는 PITR 방식이다.
현재는 WAL 아카이빙과 PITR 복원 절차가 없으므로 RPO 15분을 현재 목표로 쓰지 않는다.

## 3. 장애별 대응

| 장애 | 대응 | 목표 시간 |
|---|---|---:|
| 앱 컨테이너 중단 | Docker 재시작 | 5분 |
| 앱 VM 중단 | VM·Compose 재기동 | 15분 |
| PG 중단, 볼륨 정상 | PG 재기동 | 15분 |
| PG 데이터 손상 | 1차: 일일 백업 복원 / 향후: PITR | 4시간 → 자동화 후 2시간 |
| 일반 볼륨 손상 | 최근 snapshot 복원 | 4시간 → 자동화 후 2시간 |
| Docker 물리 서버 손상 | 현재 대체 컴퓨터가 없어 보장 불가 | 4시간 이상 가능 |
| 향후 K8s 노드 1대 중단 | 다른 노드의 Pod로 전환 | 5분 목표 |

단순 프로세스·VM 중단은 먼저 재시작한다. 운영 볼륨이 손상되거나 삭제된 경우에만
백업 저장소에서 복원한다.

## 4. 볼륨·스토리지 계획

### 현재 Docker

현재 운영 볼륨에 **중앙 백업 저장소 볼륨 1개**를 추가한다. 모든 Docker 디스크를
통째로 복사하지 않고 복구 가치가 있는 데이터만 서비스에 맞는 방식으로 저장한다.

| 서비스 | 현재 운영 볼륨 | 백업 방식 | 복구 방식 |
|---|---|---|---|
| PostgreSQL | `tfstate_pg` | 1차 일일 전체 dump, 후속 주간 전체본+WAL | 새 PG에 복원, 후속 PITR |
| Elasticsearch | `es_data` | ES snapshot | snapshot 복원 또는 PG 재색인 |
| Kafka | `kafka_data` | 토픽 설정·PG watermark 기록 | 토픽 재생성 후 누락 구간 재수집 |
| Redis PGSync | `redis_pgsync_data` | AOF 일일 보관 | AOF 복원 또는 PG 전체 동기화 |
| Redis 캐시 | 영속 볼륨 없음 | 백업 안 함 | 빈 캐시로 재시작 |
| Harbor | `/data` | 설정·현재 배포 이미지 보관 | 설정 복원 또는 CI 재빌드 |
| 모니터링 | `prometheus/loki/tempo/grafana_data` | 설정은 Git, `grafana_data`만 보조 백업 | 재배포 후 새 데이터 수집 |
| 레시피 폴러 | crawl-state bind mount | 상태 파일 일일 보관 | 상태 복원 후 수집 재개 |

`fb-app-ai`의 API·프론트엔드는 상태를 PG에 저장하므로 별도 영속 볼륨을 만들지 않고
Git/Harbor 이미지로 재배포한다.

```text
운영 named volumes ── 서비스별 백업 ──→ backup_repo 볼륨
PostgreSQL ── dump/전체본, 후속 WAL ──→ backup_repo/postgres
ES ── snapshot ───────────────────────→ backup_repo/elasticsearch
기타 상태 파일 ───────────────────────→ backup_repo/state
```

백업 저장소는 운영 `/var/lib/docker`와 다른 디스크에 둔다. 미사용 `sda` 250GB는
후보일 뿐이며 사용 여부는 아직 결정하지 않았다.

용량은 실제 사용량을 측정한 뒤 다음 식으로 정한다.

```text
backup_repo 최소 용량
= PG 전체본 2개
+ 일일 변경분 7일
+ ES snapshot 2개
+ 기타 상태 파일
+ 20% 여유 공간
```

처음에는 일일 백업으로 시작하고 실제 복원에 성공한 뒤 시간별 증분 snapshot과 WAL을
추가한다. 측정 전에는 RPO/RTO를 달성했다고 표시하지 않는다.

### 향후 2노드 Kubernetes

앱·프론트는 stateless Pod로 두 노드에 배치하므로 PV가 필요 없다. 설계 방향상
PG·ES·Redis는 우선 K8s 외부에 유지하고, K8s 내부의 Kafka 등 stateful workload에
노드별 PV를 사용한다.

필요한 저장 역할은 세 가지다.

1. 물리 컴퓨터 A의 운영 PersistentVolume
2. 물리 컴퓨터 B의 복제 PersistentVolume
3. 두 컴퓨터와 별개로 복원할 백업 저장소 볼륨

노드 간 replica는 빠른 전환용이고 백업 저장소는 삭제·손상 복구용이다. replica는
잘못 삭제된 데이터도 복제할 수 있으므로 백업을 대신하지 않는다.

```text
K8s 노드 A 운영 PV ── 복제 ── K8s 노드 B 복제 PV
          └──────── 증분 snapshot ──────────────→ 독립 백업 저장소
외부 PostgreSQL ── 전체 백업 + 선택적 WAL ─────→ 독립 백업 저장소
```

앱은 두 노드의 replica로 빠르게 전환한다. PG·ES·Redis는 설계 방향대로 우선 K8s
외부에 두므로, 두 K8s 노드의 PV 복제만으로 PostgreSQL 장애가 해결되지는 않는다.

2노드에서는 완전한 quorum을 보장하기 어려우므로 스토리지 replica 수와 구현체를
지금 확정하지 않는다. 스토리지 구현체를 정한 뒤 노드 한 대 중단·볼륨 복원 시험을
통과한 구성만 운영안으로 채택한다.

## 5. Docker에서 한 일과 남은 일

완료:

- 물리 컴퓨터 1대에 VM 4대 구성
- VM별 `/var/lib/docker` 전용 디스크 연결
- PG·ES·Kafka·PGSync Redis 볼륨 영속화
- Compose restart·healthcheck 적용
- GitHub → CI → Harbor → 앱 배포 구성
- Terraform·Ansible·Compose 재현 코드와 모니터링 구성

미완료:

- 독립 백업 저장소 볼륨 연결
- 일일 볼륨 snapshot과 PG 일일 백업
- 복원 스크립트와 실제 복원 시험
- 후속 1시간 증분 snapshot·WAL 아카이빙
- ES snapshot과 Kafka 재수집 기준
- 실제 복원 시간 측정

## 6. 향후 Kubernetes 계획

- 동일 사양 물리 컴퓨터를 추가해 2노드 구성
- API replica를 두 노드에 분산하고 장애 시 트래픽 전환
- readiness/liveness probe로 장애 Pod 제외
- 앱·AI·Kafka는 K8s 내부 운영
- PG·ES·Redis는 우선 K8s 외부 유지
- 운영·복제·백업 볼륨을 분리
- 스토리지 구현체 확정 후 VolumeSnapshot 자동화

CNI, Gateway API와 스토리지 구현체는 아직 확정하지 않는다.

K8s가 2노드여도 외부 PostgreSQL이 한 대면 데이터 계층은 단일 장애점이다. 먼저 앱
전환을 구축하고 이후 PostgreSQL standby 또는 별도 데이터 노드를 검토한다.

## 7. 검증

- 매일 마지막 백업·snapshot 시간이 RPO 이내인지 확인
- 매주 임시 PostgreSQL 복원으로 실제 RTO 측정
- 매월 PG → ES → 앱 전체 복구 시험
- K8s 전환 후 노드 한 대 중단 시 5분 안에 앱 전환 확인

백업 담당자는 본인이며 대체 담당자는 없다.
