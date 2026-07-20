# 밀플래닝 서비스 백업 전략

> 작성일: 2026-07-20
> 상태: 팀 검토용 제안서 — 아직 인프라에 적용되지 않음
> 범위: 현재 Docker Compose 운영 환경과 향후 Kubernetes 이전 환경

## 1. RPO/RTO 전략

### PostgreSQL

- **RPO:** 12시간
- **RTO:** 40분
- **백업 시각:** 매일 14시·02시
- **복구 시간 산정:** 컨테이너·DB 복원 20분 + 핵심 기능 검증 20분

사용자가 작성한 회원·예산·지출·냉장고·식단·장바구니·레시피북 데이터를 보호하기 위해 물리 백업과 논리 백업을 병행한다.

```text
pg_basebackup + WAL archive
└─ PostgreSQL 인스턴스 전체를 특정 시점으로 복구

pg_dump
├─ foodbudget
└─ terraform_state

pg_dumpall --globals-only
└─ PostgreSQL role·권한 복구
```

전체 장애에는 base backup과 WAL을 우선 사용하고, 특정 데이터베이스나 테이블만 복원할 때는 `pg_dump`를 사용한다.

RPO 12시간은 현재 서비스가 허용하는 최대 데이터 손실 목표이고, `pg_dump` 실행 간격도 12시간이다. WAL archive는 지속적으로 외부 저장소에 전송하여 마지막 보관 WAL 시점까지 복구하기 위한 수단이다. 따라서 WAL archive 구축 후 실제 PostgreSQL RPO는 12시간보다 짧아질 수 있으며, 그 값은 WAL 전송 지연과 복구 시험 결과를 측정한 뒤 별도로 확정한다.

현재 저장소에는 `pg_basebackup`, WAL archive와 정기 dump를 실행하는 운영 자동화가 아직 구현되지 않았다. RTO 40분도 현재 데이터량을 기준으로 한 목표이므로, 자동화 구축 후 정기 복구 시험으로 검증한다.

### 핵심 운영 데이터

- **RPO:** 12시간
- **제한 모드 목표 RTO:** 1시간
- **전체 핵심 기능 목표 RTO:** 2시간
- **제한 모드 시간 산정:** PostgreSQL 복구 40분 + 일반 Redis·API·프론트엔드 복구 20분

PostgreSQL 복구 후 일반 Redis 캐시와 PGSync 상태를 확인하고 Elasticsearch를 복원한다. 이후 Harbor의 배포 이미지와 애플리케이션 설정을 사용해 API·프론트엔드를 기동한다.

```text
PostgreSQL
→ 일반 Redis·PGSync 상태 확인
→ Elasticsearch snapshot 복원 또는 재색인
→ API
→ 프론트엔드
→ 핵심 기능 smoke test
```

1시간 목표는 로그인·예산·냉장고·식단·장바구니처럼 PostgreSQL 중심 기능을 우선 제공하는 제한 모드 기준이다. API와 프론트엔드만 기동되고 Elasticsearch 검색이 복구되지 않은 상태도 제한 모드 복구로 구분한다. 레시피 검색과 가격 비교까지 정상 동작해야 핵심 서비스가 완전히 복구된 것으로 판단하며, 이때는 Elasticsearch 복구 시간을 포함해 2시간을 목표로 한다.

현재 API의 `/health`와 프론트엔드 `/healthz`는 주로 프로세스·웹 서버의 생존 여부를 확인한다. PostgreSQL·Redis·Elasticsearch를 실제로 사용할 수 있는지 모두 보장하지 않으므로, healthcheck 통과만으로 복구 완료를 선언하지 않는다.

### Elasticsearch

- **RPO:** 12시간
- **RTO:** 2시간

Elasticsearch는 매일 14시·02시에 snapshot을 생성한다. 장애 시 snapshot을 복원하거나 PostgreSQL 데이터를 기반으로 검색 인덱스를 재생성한다.

snapshot 복원 또는 전체 재색인과 결과 검증에 시간이 필요하므로 목표 RTO를 2시간으로 설정한다. snapshot repository는 Elasticsearch 데이터 볼륨과 같은 물리 서버가 아닌 외부 저장소에 둔다.

### Kafka

- **복구 목표:** 토픽 재생성 후 수집 파이프라인 재개
- **목표 RTO:** 2시간
- **RPO:** 메시지 종류별로 구분

Kafka는 토픽·파티션·복제 설정, consumer group 상태와 수집 watermark를 보관한다. 그러나 설정과 offset만 저장하는 것은 Kafka 메시지 본문을 백업하는 것이 아니다.

- 마켓컬리·오아시스·만개의레시피처럼 원본을 다시 조회할 수 있는 수집 메시지는 장애 후 재수집한다.
- 이미 PostgreSQL에 반영된 메시지는 PostgreSQL 백업 정책으로 보호한다.
- 아직 처리되지 않고 Kafka에만 있는 메시지는 `kafka_data` 손실 시 함께 유실될 수 있다.
- `VIEW`, `ADD_CART`, `NOTIF_CLICK` 같은 사용자 행동 이벤트는 외부에서 재수집할 수 없다.

따라서 Kafka 전체에 RPO 12시간을 일괄 적용하지 않는다. 사용자 행동 이벤트와 처리 대기 메시지까지 보호하려면 Kafka 데이터 볼륨 백업, 복제 브로커, producer 재전송 또는 outbox 방식 중 하나를 추가로 도입해야 한다. 도입 전에는 처리 중 메시지 일부가 손실될 수 있음을 명시한다.

### Redis

- **일반 Redis(6379) 복구 방식:** 재생성
- **일반 Redis 목표 RTO:** 10분

일반 Redis(6379)는 현재가·추출 캐시이며 persistence를 사용하지 않는다. 빈 컨테이너를 기동한 뒤 PostgreSQL과 수집 파이프라인에서 캐시를 다시 구성한다. 장바구니 원본은 PostgreSQL의 `mealplan.cart_item`에 저장하므로 일반 Redis를 백업하지 않아도 사용자 장바구니는 PostgreSQL 백업으로 보호한다.

PGSync 전용 Redis(6380)는 일반 캐시와 구분한다. 이 인스턴스는 `noeviction`과 AOF를 사용하며 PGSync 동기화 상태와 관련된다. `redis_pgsync_data`와 `pgsync_checkpoint`는 선택적 백업 대상으로 두고, 백업하지 않거나 복구할 수 없으면 PostgreSQL을 기준으로 Elasticsearch 전체 재색인을 수행한다.

현재 PGSync는 `wal_level=logical` 전환 전이라 조건부 기동 상태다. PGSync를 실제 운영에 활성화할 때 이 복구 절차도 함께 시험한다. Redis에 사용자 원본 데이터가 새로 생기면 PostgreSQL 등 영구 저장소로 이전하거나 별도 필수 백업 대상으로 재분류한다.

### API·프론트엔드

- **복구 방식:** 재배포
- **RTO:** 15분

Harbor가 정상인 경우 현재 배포 이미지를 pull하고 Docker Compose로 기동한 뒤 healthcheck와 기능 smoke test를 확인한다. 컨테이너 자체와 Docker build cache는 백업하지 않는다.

RTO 15분은 Harbor·네트워크·이미지 저장소가 정상이고 필요한 이미지가 이미 존재한다는 전제의 목표다. Harbor까지 손상된 경우에는 이 RTO가 아니라 물리 서버 손상 복구 절차를 적용한다.

### 물리 서버 손상

- **복구 전제:** 대체 장비 확보
- **초기 목표 RTO:** 4시간
- **자동화 이후 목표 RTO:** 3시간

대체 장비에 Proxmox를 설치하고 Terraform·Ansible로 VM 4대를 재생성한 뒤 정해진 순서로 복원한다.

### 1.1 물리 서버 복구 순서

1. 대체 장비와 네트워크를 준비한다. — 1시간
2. Proxmox를 설치하고 Terraform·Ansible로 VM 4대를 생성한다. — 1시간
3. `fb-data` → `fb-ci-harbor` → `fb-app-ai` → `fb-monitoring` 순서로 데이터와 애플리케이션을 복원한다. — 1시간 30분
4. 핵심 기능을 확인한다. — 30분

자동화 이후에는 VM 생성·복원 시간을 1시간 단축해 목표 RTO를 3시간으로 잡는다. 4시간과 3시간은 모두 복구 훈련으로 검증하기 전의 목표값이며, 대체 장비 확보에 걸리는 시간은 RTO 계산 시작 전의 전제 조건으로 분리한다.

### 1.2 서비스 특성과 목표 선정 이유

이 서비스는 20~30대 1인 가구가 월 식비 예산 안에서 식단을 계획하는 밀플래닝 서비스다. 레시피에서 재료를 추출하고 마켓컬리·오아시스 가격을 비교해 식단·장바구니·지출을 연결하는 것이 핵심이다.

회원·예산·지출·냉장고·식단·레시피북은 사용자가 직접 만든 데이터이며 PostgreSQL에 저장된다. 외부에서 다시 만들 수 없으므로 하루 두 번 백업하고 RPO를 12시간으로 정한다.

Elasticsearch 검색 인덱스는 PostgreSQL에서 재색인할 수 있고, 일반 Redis 캐시는 재생성할 수 있다. Kafka의 외부 수집 데이터도 원본이 남아 있으면 다시 수집할 수 있다. 다만 사용자 행동 이벤트와 Kafka에만 남은 처리 대기 메시지는 재생성할 수 없으므로 별도 보호 대책 또는 명시적인 손실 허용 기준이 필요하다.

현재 데이터량이 크지 않아 PostgreSQL 복원 20분과 로그인·예산·냉장고·식단 확인 20분을 합쳐 목표 RTO를 40분으로 정한다. Elasticsearch와 Kafka는 재색인·재수집 및 결과 검증 시간이 추가되므로 목표 RTO를 2시간으로 정한다. 모든 시간은 실제 복구 시험에서 측정한 결과로 확정한다.

## 2. 현재 Docker Compose 전략

현재 물리 컴퓨터 1대 안에서 VM 4대를 사용한다.

### 2.1 백업 시간

- **14:00:** 점심 이용 시간 이후 PostgreSQL을 먼저 백업하고 나머지 데이터를 순차 백업한다.
- **02:00:** 저녁 이용 시간 이후 PostgreSQL을 먼저 백업하고 나머지 데이터를 순차 백업한다.

사용자가 점심과 저녁 전후에 식단과 관련 정보를 저장할 것으로 예상해 두 이용 시간대가 지난 뒤 백업하며, 두 백업 사이의 12시간 간격을 유지한다.

백업 작업이 한 번 실패하면 마지막 정상 백업이 24시간 이상 전이 되어 RPO 12시간을 위반할 수 있다. 따라서 실패 자동 재시도, 담당자 알림, 마지막 정상 백업 시각 모니터링을 함께 구성한다.

### 2.2 백업 대상 선정 원칙

백업 여부는 데이터를 다시 만들 수 있는지와 복구에 걸리는 시간을 기준으로 결정한다.

- **반드시 백업:** 사용자가 작성했거나 외부에서 다시 만들 수 없는 원본 데이터
- **선택적으로 백업:** 원본에서 재생성할 수 있지만 재생성 시간이 긴 데이터
- **재생성:** 캐시·컨테이너·빌드 결과처럼 원본에서 빠르게 다시 만들 수 있는 데이터

```text
사용자가 만든 원본 데이터
└─ 반드시 백업

재생성 가능하지만 시간이 오래 걸리는 데이터
└─ snapshot 또는 설정 백업

컨테이너·캐시·재배포 가능한 프로그램
└─ 백업하지 않고 재생성
```

### 2.3 VM별 백업 대상과 제외 대상

#### `fb-data`

다음 항목을 백업한다.

- PostgreSQL `pg_basebackup`과 WAL archive
- `foodbudget`, `terraform_state`의 `pg_dump`
- PostgreSQL role·권한
- Elasticsearch snapshot
- Kafka 토픽·파티션·복제 설정
- Kafka consumer offset 또는 마지막 수집 위치
- Kafka 메시지 본문을 보호하기로 결정한 경우 `kafka_data` 볼륨
- PGSync 전용 `redis_pgsync_data`와 `pgsync_checkpoint`
- 만개의레시피 크롤링 재개·중복 방지용 `recipe-crawl-state`
- 데이터 서비스 설정 파일
- 정기 Proxmox VM 백업

Proxmox VM 백업은 물리 서버 전체 복구 속도를 높이기 위한 보조 수단이다. 실행 중인 PostgreSQL VM의 snapshot만으로 데이터베이스 정합성과 시점 복구를 보장하지 않으며, PostgreSQL native backup을 주 복구 수단으로 사용한다.

다음 항목은 백업하지 않고 재생성한다.

- Redis 캐시
- PostgreSQL에서 다시 만들 수 있는 Elasticsearch 인덱스
- 원본 사이트에 데이터가 남아 있어 다시 수집할 수 있는 Kafka 메시지

사용자 행동 이벤트처럼 다시 만들 수 없는 Kafka 메시지는 위 제외 대상에 포함하지 않는다. 해당 메시지는 Kafka 보호 방식을 확정하거나 처리 중 손실 허용 기준을 별도로 기록한다.

#### `fb-ci-harbor`

다음 항목을 백업한다.

- Harbor 데이터베이스와 registry 데이터
- Harbor 설정 파일·인증서
- 프로젝트·사용자·권한 설정
- 현재 운영 이미지와 직전 안정 버전 이미지
- 배포 스크립트와 self-hosted Runner 설정

다음 항목은 백업하지 않고 재생성한다.

- CI 작업 디렉터리
- 임시 빌드 캐시
- Git에서 다시 받을 수 있는 소스 코드
- 사용하지 않는 과거 이미지

#### `fb-app-ai`

다음 항목을 백업한다.

- Docker Compose와 애플리케이션 설정
- 환경 변수와 Secret의 안전한 사본
- AI 모델 파일·버전·설정과 `ranking-model` 볼륨
- 향후 로컬 영구 볼륨에 저장하게 되는 사용자 업로드 파일

다음 항목은 백업하지 않고 재배포한다.

- API·프론트엔드 컨테이너
- Harbor에서 다시 pull할 수 있는 이미지
- Docker build cache와 임시 파일

현재 영수증 원본 이미지는 저장하지 않고 OCR 결과만 PostgreSQL에 저장한다. 향후 영수증·레시피 이미지 등 사용자 업로드 파일을 보관하도록 변경하면 컨테이너 내부 파일시스템에만 저장하지 않는다. 영구 볼륨이나 외부 저장소로 분리하고 PostgreSQL과 동일한 RPO 범위로 백업한다.

#### `fb-monitoring`

다음 항목을 백업한다.

- Grafana 대시보드·데이터소스 설정
- Prometheus 설정과 recording rule
- Alertmanager 설정과 알림 규칙
- 로그·메트릭 수집 설정

다음 항목은 보존 요구사항에 따라 선택한다.

- Prometheus 과거 메트릭
- 장기간 보관 로그

단기 메트릭과 임시 로그는 핵심 사용자 데이터가 아니므로 기본적으로 재생성 대상으로 분류한다.

### 2.4 물리 서버와 백업 저장 위치

물리 서버 장애 시 백업까지 함께 손실되지 않도록 다음 항목을 현재 Proxmox 서버와 다른 저장소에 보관한다.

- PostgreSQL base backup·WAL·논리 dump
- Elasticsearch snapshot
- Harbor 설정·registry 백업
- `fb-data` VM 백업
- Proxmox·네트워크 설정
- Terraform 코드와 state
- Ansible inventory와 playbook
- Docker Compose 파일과 복구 절차서

백업 목적지는 NAS, 외장 스토리지 또는 별도 장비로 분리한다. 같은 물리 디스크나 같은 Proxmox 서버에만 저장한 복사본은 물리 서버 손상에 대한 백업으로 인정하지 않는다.

백업 저장소에는 다음 운영 통제를 적용한다.

- 백업 종류별 보존 기간과 보관 개수 정의
- 전송 중·보관 중 암호화
- 백업 파일 checksum 생성과 정기 무결성 검사
- 운영 계정과 분리된 최소 권한 백업 계정 사용
- 백업 실패 자동 재시도와 Alertmanager 알림
- 마지막 정상 백업 시각 모니터링
- 가능한 경우 오프라인 또는 변경 불가능한 사본 보관

### 2.5 복구 검증

백업 파일 생성 성공만으로 복구 가능하다고 판단하지 않는다. 정기 복구 시험에서 다음 기능을 확인한다.

1. 회원 로그인
2. 예산·지출 조회
3. 냉장고 재고 조회
4. 식단·장바구니 조회
5. 사용자 레시피북 조회
6. Redis 캐시 재생성
7. API·프론트엔드 healthcheck
8. Elasticsearch 검색 또는 재색인
9. 가격 비교와 핫딜 조회
10. Kafka 수집 파이프라인 재개와 중복·누락 확인

healthcheck는 프로세스 생존 확인용으로만 사용한다. 로그인·조회·검색·가격 비교 같은 기능 smoke test까지 통과해야 복구 완료로 판정한다.

복구 시험 결과와 실제 소요 시간을 기록하고, 측정 시간이 목표 RTO를 초과하면 RTO 또는 자동화 절차를 조정한다. 최소 월 1회 PostgreSQL 표본 복원과 최소 분기 1회 전체 복구 훈련을 목표로 하며, 팀 운영 여건에 맞춰 최종 주기를 확정한다.

## 3. 향후 Kubernetes 전략

> 현재 설계 정본의 하이브리드 이전 방향은 PostgreSQL·Elasticsearch·Redis를 Kubernetes 밖에 유지하고 Kafka·애플리케이션·AI를 Kubernetes 안으로 이전하는 것이다. 아래 스토리지 구성은 향후 PostgreSQL까지 Kubernetes 내부로 이전하기로 별도 결정한 경우에만 적용하는 제안이다. Longhorn을 포함한 스토리지 구현체와 PostgreSQL 이전 여부는 아직 확정하지 않는다.

### 3.1 Kubernetes 스토리지 오브젝트

PostgreSQL 데이터는 컨테이너 내부 파일시스템에 저장하지 않는다. Pod가 재생성될 때 데이터가 사라질 수 있으므로 영구 볼륨을 사용한다.

```text
StorageClass
      │
      ▼
PersistentVolumeClaim
      │
      ▼
PersistentVolume
      │
      ▼
PostgreSQL 데이터 디렉터리
```

#### 3.1.1 StorageClass

StorageClass는 스토리지를 어떤 방식으로 생성하고 관리할지 정의한다.

검토 항목은 다음과 같다.

- CSI 기반 동적 프로비저닝
- 볼륨 확장 허용
- 데이터 보호를 위한 `Retain` 정책
- PostgreSQL 전용 StorageClass 분리

예시 이름은 다음과 같다.

```yaml
storageClassName: longhorn-postgresql
```

#### 3.1.2 PersistentVolumeClaim

PersistentVolumeClaim(PVC)은 PostgreSQL에 필요한 저장 공간을 Kubernetes에 요청하는 오브젝트다.

```yaml
resources:
  requests:
    storage: 50Gi
```

#### 3.1.3 PersistentVolume

PersistentVolume(PV)은 PVC 요청에 따라 실제로 제공되는 영구 저장 공간이다. PostgreSQL Pod가 재시작되거나 교체되더라도 PV의 데이터는 유지된다.

#### 3.1.4 VolumeSnapshot

VolumeSnapshot은 PVC의 특정 시점 상태를 저장하는 스냅샷 오브젝트다. 다만 VolumeSnapshot만으로 PostgreSQL 백업을 대체해서는 안 된다.

다음 백업 수단과 복구 검증을 함께 사용한다.

- PostgreSQL base backup
- WAL archive
- `pg_dump`
- 외부 저장소 백업
- 정기 복구 테스트

### 3.2 PostgreSQL 인스턴스별 스토리지 구성

Primary와 각 Standby는 하나의 PVC를 공유하지 않는다. 각 PostgreSQL 인스턴스에 독립적인 데이터 디렉터리와 PVC를 할당한다.

잘못된 구성:

```text
Primary ───┐
Standby 1 ─┼── 하나의 공유 PVC
Standby 2 ─┘
```

올바른 구성:

```text
Primary   ── Primary 전용 PVC
Standby 1 ── Standby 1 전용 PVC
Standby 2 ── Standby 2 전용 PVC
```

권장 접근 모드 예시는 다음과 같다.

```yaml
accessModes:
  - ReadWriteOncePod
```

### 3.3 스토리지 시스템 제안

온프레미스 Kubernetes 환경에서는 CSI 기반 분산 스토리지인 Longhorn을 우선 검토한다.

```text
PostgreSQL
    │
    ▼
PVC
    │
    ▼
StorageClass
    │
    ▼
Longhorn Volume
```

검토 대상은 다음과 같다.

- PostgreSQL 데이터 PVC
- WAL 저장 공간
- VolumeSnapshot
- 스토리지 용량 확장
- 볼륨 장애 복구

Longhorn 도입 여부와 세부 구성은 노드 중단·볼륨 복원 시험 및 팀 검토 후 확정한다.

Longhorn replica와 VolumeSnapshot이 같은 물리 Proxmox 서버 안의 VM에만 존재하면 물리 서버 손상에는 함께 유실될 수 있다. 따라서 Longhorn을 사용하더라도 PostgreSQL base backup·WAL·논리 dump와 Longhorn backup을 별도 물리 장비나 외부 저장소에 보관한다.
