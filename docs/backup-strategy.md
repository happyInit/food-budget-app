# 밀플래닝 서비스 백업 전략

> 🔴 **SUPERSEDED (2026-07-30)** — 이 문서는 **Docker/VM 시절** 전략이다(데이터=클러스터 밖 `fb-data` VM, 백업=VM systemd·pgBackRest). P2 데이터 이전으로 데이터 티어가 **클러스터 안(CNPG·ECK 등)** 으로 옮겨져 메커니즘이 폐기됐다.
> **K8s 백업 전략의 정본 = [`mp_k8s_backup_strategy.md`](./mp_k8s_backup_strategy.md).** RPO/RTO 목표와 "무엇을 백업/재생성하나" 원칙은 그 문서로 계승됐다(K8s 실측 기준 재-baseline). 이 문서는 이력 참고용으로만 보존한다 — **수정하지 말 것.**

> 작성일: 2026-07-20 · 최종 결정 반영: 2026-07-21
> 상태: 스토리지 방향 확정 — S3 연동은 향후 Kubernetes 이전 단계에서 구현·복구 시험 예정
> 범위: 현재 Docker Compose 운영 환경과 향후 Kubernetes 이전 환경

## 0. 확정 결정

- PostgreSQL·Elasticsearch·Redis는 Kubernetes 밖의 `fb-data` VM에 유지한다.
- 현재 Docker Compose 운영 단계에서는 S3 백업을 적용하지 않는다. Amazon S3 서울 리전(`ap-northeast-2`) 연동은 향후 Kubernetes 이전 단계에서 오프사이트 백업 저장소로 도입한다.
- S3는 PostgreSQL 데이터 디렉터리나 Kubernetes PVC를 대신하지 않는다. 실행 데이터는 VM의 블록 스토리지에 두고 백업 객체만 S3로 전송한다.
- 백업 실행은 Kubernetes CronJob이 아니라 `fb-data` VM의 systemd timer와 Ansible로 관리한다. Kubernetes 전체가 중단돼도 데이터 백업 경로가 유지되어야 하기 때문이다.
- S3 비용은 월 예산 알림과 Lifecycle로 제한하며, 교차 리전 복제는 초기 범위에서 제외한다.

## 1. RPO/RTO 전략

### PostgreSQL

- **RPO:** 12시간
- **RTO:** 40분
- **백업 시각:** 매일 14시·02시
- **복구 시간 산정:** 컨테이너·DB 복원 20분 + 핵심 기능 검증 20분

사용자가 작성한 회원·예산·지출·냉장고·식단·장바구니·레시피북 데이터를 보호하기 위해 물리 백업과 논리 백업을 병행한다.

```text
pgBackRest full/differential/incremental + continuous WAL archive
└─ S3 복구 저장소에서 PostgreSQL 전체를 특정 시점으로 복구

pg_dump
├─ foodbudget
└─ terraform_state

pg_dumpall --globals-only
└─ PostgreSQL role·권한 복구
```

전체 장애에는 pgBackRest backup과 WAL을 우선 사용하고, 특정 데이터베이스나 테이블만 복원할 때는 `pg_dump`를 사용한다.

백업 일정은 일요일 02시 full, 나머지 날 02시 differential, 매일 14시 incremental로 정한다. `foodbudget`·`terraform_state` 논리 dump와 globals dump는 매일 02시·14시에 생성한다. WAL은 pgBackRest `archive-push`로 S3 복구 저장소에 지속 전송한다.

RPO 12시간은 현재 서비스가 허용하는 최대 데이터 손실 목표이고, `pg_dump` 실행 간격도 12시간이다. 지속 WAL archive 구축 후에는 마지막 정상 업로드 WAL까지 시점 복구할 수 있지만, 공식 RPO는 WAL 전송 지연과 실제 복구 시험을 측정한 뒤에만 단축한다.

현재 저장소에는 pgBackRest, WAL archive와 정기 dump를 실행하는 운영 자동화가 아직 구현되지 않았다. RTO 40분도 현재 데이터량을 기준으로 한 목표이므로, 자동화 구축 후 정기 복구 시험으로 검증한다.

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

향후 Kubernetes 이전 단계에서 Elasticsearch는 Amazon S3 snapshot repository에 매일 14시·02시 snapshot을 생성하고 14일간 보존한다. snapshot repository는 S3 Standard에 유지하며 Glacier 계열로 전환하지 않는다. 도구가 직접 관리하는 repository 객체를 임의 이동하거나 삭제하면 복구 저장소가 손상될 수 있기 때문이다. 장애 시 snapshot을 복원하거나 PostgreSQL 데이터를 기반으로 검색 인덱스를 재생성한다.

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

- PostgreSQL pgBackRest full/differential/incremental backup과 WAL archive
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

현재 영수증 원본 이미지는 저장하지 않고 OCR 결과만 PostgreSQL에 저장한다. 향후 영수증·레시피 이미지 등 사용자 업로드 파일을 보관하도록 변경하면 S3의 운영 객체 전용 prefix 또는 별도 bucket에 저장한다. 백업 bucket과 사용자 콘텐츠 bucket은 권한·Lifecycle을 분리하고, PostgreSQL에는 객체 key와 메타데이터만 저장한다.

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

### 2.4 Amazon S3 백업 저장소 — Kubernetes 이전 시 도입 예정

이 절은 현재 Docker Compose 운영 구성이 아니라 **향후 Kubernetes 이전 단계에서 적용할 목표 구성**이다. 해당 시점에 물리 서버 장애와 운영 계정 오작동을 함께 대비하기 위해 Amazon S3 서울 리전(`ap-northeast-2`)에 목적이 다른 bucket 두 개를 만든다. 실제 bucket 이름은 전역 고유 이름이어야 하므로 코드와 문서에 고정하지 않고 `BACKUP_S3_REPO_BUCKET`, `BACKUP_S3_VAULT_BUCKET` 환경 변수로 주입한다.

#### 2.4.1 복구 저장소 bucket

`BACKUP_S3_REPO_BUCKET`은 백업 도구가 직접 읽고 쓰고 만료시키는 저장소다.

```text
postgres/pgbackrest/       pgBackRest backup + WAL
elasticsearch/snapshots/  Elasticsearch snapshot repository
```

- Versioning과 Block Public Access를 활성화한다.
- 기본 암호화는 추가 KMS 호출 비용이 없는 SSE-S3를 사용한다.
- PostgreSQL prefix에는 pgBackRest 전용 IAM principal만 읽기·쓰기 권한을 갖는다.
- Elasticsearch prefix에는 snapshot 전용 IAM principal만 읽기·쓰기 권한을 갖는다.
- Object Lock을 적용하지 않는다. pgBackRest expire와 Elasticsearch snapshot 삭제가 정상 동작해야 하기 때문이다.
- Elasticsearch prefix는 S3 Standard에 유지한다. PostgreSQL prefix는 실제 복구 시간 시험 전까지 S3 Standard에 두고, 이후 30일이 지난 복구 세트만 Standard-IA 전환을 검토한다.
- pgBackRest는 최근 full backup 4세트와 그 복구에 필요한 differential·incremental·WAL을 보존한다.
- Elasticsearch snapshot은 14일 보존 후 Snapshot Lifecycle Management로 삭제한다. S3 Lifecycle에서 repository 내부 객체를 직접 삭제하지 않는다.

#### 2.4.2 불변 보관소 bucket

`BACKUP_S3_VAULT_BUCKET`은 사람이 복구할 수 있는 독립 사본을 보관한다.

```text
postgres/dump/       foodbudget·terraform_state·globals dump
harbor/              Harbor DB·설정·registry archive
proxmox/             선택한 VM backup과 Proxmox·네트워크 설정
config/              Terraform state·Ansible·Compose·복구 절차
models/              운영 AI 모델과 checksum
```

- Versioning, Block Public Access, Object Lock Governance mode 30일을 활성화한다.
- 백업 writer에는 `PutObject`와 필요한 multipart upload 권한만 주고 `DeleteObject`, bucket 정책 변경, `s3:BypassGovernanceRetention` 권한은 주지 않는다.
- 기본 암호화는 SSE-S3를 사용하며 전송은 HTTPS/TLS만 허용한다. Secret 원문은 업로드 전에 별도 암호화하고 복호화 키를 S3와 같은 위치에 두지 않는다.
- 0~30일은 S3 Standard, 31~90일은 Standard-IA, 91~365일은 Glacier Flexible Retrieval로 전환하고 365일 뒤 만료한다.
- Object Lock 기간에는 Lifecycle 만료보다 잠금이 우선하며, 30일 안의 보호된 객체 버전은 삭제하거나 변경할 수 없다. 같은 key로 다시 업로드하면 기존 버전을 지우는 대신 새 버전이 생성된다.
- 일일 논리 dump는 35일, 주간 archive는 12주, 월말 archive는 12개월을 기본 보존 목표로 한다. 업로더가 보존 등급 tag를 지정하고 Lifecycle이 tag별 만료를 수행한다.

#### 2.4.3 백업 흐름과 도구

```text
PostgreSQL ── pgBackRest + WAL ────────────────→ S3 복구 저장소
          └─ pg_dump + checksum + 암호화 ─────→ S3 불변 보관소

Elasticsearch ── repository-s3 snapshot ──────→ S3 복구 저장소

Harbor·VM·설정·모델 ── tar.zst + age ────────→ S3 불변 보관소
```

- pgBackRest와 Elasticsearch는 각자의 S3 연동 기능을 사용한다.
- 파일·설정·Harbor·선택적 VM archive는 `tar`와 `zstd`로 묶고, Secret 포함 archive는 `age`로 암호화한 뒤 SHA-256 checksum과 함께 시간별 고유 key로 업로드한다. Object Lock과 충돌할 수 있는 저장소 내부 lock/prune가 필요한 도구는 불변 bucket에 직접 사용하지 않는다.
- 대용량 전체 VM backup은 초기 필수 S3 대상에서 제외한다. 먼저 PostgreSQL·Elasticsearch·Harbor·설정처럼 재생성하기 어렵거나 복구 시간이 긴 데이터를 보호하고, 월 비용과 업로드 시간을 측정한 뒤 `fb-data` VM 월간 사본 추가를 결정한다.
- 로컬 복구 속도를 위해 여유 SSD 또는 별도 NAS에 최근 1세트를 캐시할 수 있지만, 같은 Proxmox 서버 안의 사본은 오프사이트 백업으로 계산하지 않는다.

#### 2.4.4 운영·비용 통제

- AWS 계정·bucket·prefix 모두 public access를 차단한다.
- 운영 서비스 자격증명과 백업 자격증명을 분리하고, 키는 Ansible Vault 또는 호스트 전용 secret 파일로 주입한다. Git에는 저장하지 않는다.
- 업로드 완료 후 checksum을 비교하고, 마지막 정상 backup·WAL archive 시각과 S3 객체 나이를 모니터링한다.
- 실패 시 3회 지수 백오프 재시도 후 Alertmanager로 알린다.
- AWS Budget 월 한도와 50%·80%·100% 알림을 설정한다. 초기에는 교차 리전 복제, Deep Archive, S3 Inventory를 사용하지 않는다.
- 초기 S3 월 예산 상한은 미화 10달러로 둔다. 80% 도달 시 선택적 VM·모델 archive를 중단하고, 100% 도달 시에도 PostgreSQL WAL·backup·논리 dump는 중단하지 않은 채 보존 기간과 선택 백업 범위를 팀이 즉시 조정한다.
- 최소 월 1회 PostgreSQL 표본 복원, 최소 분기 1회 S3만 사용한 전체 복구 훈련을 수행한다.

#### 2.4.5 구현 설정

pgBackRest 목표 설정은 다음과 같다. 실제 access key와 secret key는 설정 파일에 직접 기록하지 않고 전용 secret 파일 또는 환경 주입을 사용한다.

```ini
[global]
repo1-type=s3
repo1-s3-region=ap-northeast-2
repo1-s3-endpoint=s3.ap-northeast-2.amazonaws.com
repo1-s3-bucket=<BACKUP_S3_REPO_BUCKET>
repo1-path=/postgres/pgbackrest
repo1-retention-full=4
start-fast=y
process-max=2
```

Ansible이 `<BACKUP_S3_REPO_BUCKET>`을 실제 bucket 이름으로 렌더링하고, on-premise VM에서는 pgBackRest S3 key와 secret을 환경 변수 또는 root 전용 secret 파일로 제공한다.

Elasticsearch에는 현재 배포 버전에 포함된 S3 repository 기능을 사용하고, credential은 Elasticsearch keystore에 넣는다.

```json
PUT _snapshot/fb_s3_repository
{
  "type": "s3",
  "settings": {
    "bucket": "<BACKUP_S3_REPO_BUCKET>",
    "base_path": "elasticsearch/snapshots",
    "server_side_encryption": true
  }
}
```

S3 client region과 credential은 repository JSON이 아니라 Elasticsearch keystore와 client 설정에 둔다.

불변 보관소 객체 key는 덮어쓰지 않도록 생성 시각과 checksum을 포함한다.

```text
postgres/dump/2026/07/21/140000/foodbudget-<sha256>.dump.age
config/2026/07/21/terraform-state-<sha256>.tar.zst.age
```

#### 2.4.6 도입 순서

1. Terraform으로 서울 리전의 repo·vault bucket, Versioning, Block Public Access, SSE-S3, vault Object Lock, Lifecycle과 AWS Budget을 생성한다.
2. prefix별 IAM policy와 전용 backup principal을 만들고 Ansible Vault로 자격증명을 배포한다.
3. `fb-data`에 pgBackRest를 설치하고 staging에서 full backup·WAL archive·PITR을 검증한다.
4. Elasticsearch S3 repository를 등록하고 repository verify API와 snapshot restore를 검증한다.
5. 논리 dump·Harbor·설정 archive 업로더와 systemd timer를 배포한다.
6. 마지막 정상 backup·WAL 시각, S3 업로드 실패, bucket 용량과 월 비용 알림을 연결한다.
7. 복구 훈련을 통과한 뒤 운영 전환하고 기존 임시 백업 경로를 정리한다.

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

Amazon S3 백업 연동은 이 Kubernetes 이전 단계에서 함께 도입한다. 이전 후에도 데이터 계층과 백업 실행 주체는 클러스터 밖에 두며, S3를 Pod의 일반 파일시스템이나 PostgreSQL 데이터 볼륨처럼 mount하지 않는다.

### 3.1 하이브리드 배치

```text
Kubernetes
├─ Gateway·API·AI serving
├─ Kafka(Strimzi)
├─ KEDA·HPA
└─ ArgoCD

Kubernetes 외부 fb-data VM
├─ PostgreSQL ── pgBackRest/WAL ──→ Amazon S3
├─ Elasticsearch ── snapshot ─────→ Amazon S3
└─ Redis
```

- PostgreSQL·Elasticsearch·Redis의 실행 데이터는 `fb-data` VM의 블록 스토리지에 유지한다.
- Kubernetes 애플리케이션은 가능한 한 stateless로 운영한다.
- Kafka는 Strimzi 이전 대상이지만 Kafka 데이터 보호 정책은 별도 결정이 필요하다. S3가 Kafka persistent volume을 대체하지 않는다.
- ArgoCD 선언과 애플리케이션 설정은 Git을 정본으로 삼고, Git에 둘 수 없는 Secret의 암호화 사본만 S3 불변 보관소에 백업한다.

### 3.2 S3 접근 경로

백업 업로드는 `fb-data` VM에서 직접 수행한다. 애플리케이션 Pod가 PostgreSQL 백업 자격증명을 갖지 않도록 한다.

```text
fb-data systemd timer
├─ pgBackRest → S3 repo bucket/postgres
├─ Elasticsearch snapshot → S3 repo bucket/elasticsearch
└─ dump·config·archive → S3 vault bucket
```

- K8s 장애와 무관하게 systemd timer가 계속 실행된다.
- K8s Service와 수동 Endpoints/EndpointSlice는 애플리케이션이 외부 데이터 계층에 접근하는 용도로만 사용한다.
- K8s ServiceAccount에는 백업 bucket 쓰기 권한을 부여하지 않는다.
- 향후 사용자 업로드 파일을 S3에 저장할 때는 백업 bucket이 아닌 별도 콘텐츠 bucket과 제한된 presigned URL 정책을 사용한다.

### 3.3 장애 복구 순서

1. Terraform·Ansible로 VM과 네트워크를 복구한다.
2. S3 복구 저장소의 pgBackRest backup과 WAL로 PostgreSQL을 복구한다.
3. S3 snapshot으로 Elasticsearch를 복구하거나 PostgreSQL에서 재색인한다.
4. Redis를 재생성하고 PGSync 상태를 복구한다.
5. Kubernetes 노드와 ArgoCD를 복구해 애플리케이션을 재배포한다.
6. 로그인·예산·냉장고·레시피·가격 비교 smoke test를 수행한다.

### 3.4 향후 상태 저장 서비스 변경 원칙

PostgreSQL 등 상태 저장 서비스를 Kubernetes 내부로 옮기는 안은 현재 범위가 아니다. 향후 이 결정을 변경하면 S3와 별도로 지연 시간·IOPS·fsync를 지원하는 블록 스토리지를 다시 선정해야 한다. 그 경우에도 S3는 오프사이트 백업 저장소 역할을 유지한다.
