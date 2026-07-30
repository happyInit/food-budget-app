# 밀플래닝 백업 전략 (Kubernetes) — 정본(SSOT)

> 작성: 2026-07-30 · 실측 근거: [P2 데이터 이전 런북](./mp_k8s_p2_data_runbook.md) 리허설·게이트①(2026-07-29)
>
> 🔴 **이 문서가 K8s 백업 전략의 정본이다.** [`backup-strategy.md`](./backup-strategy.md)(2026-07-20)는 **Docker/VM 시절 문서로 superseded** — RPO/RTO 목표와 "무엇을 백업/재생성하나" 원칙은 여기로 계승됐고, 메커니즘(데이터=VM·백업=VM systemd·pgBackRest)은 폐기됐다.

## 0. 한 줄 요약

데이터 티어가 **클러스터 안(CNPG·ECK·Strimzi·Redis)** 으로 옮겨오면서, 백업은 **CNPG barman-cloud 플러그인 → S3** 로 이미 구현·검증(왕복 복원)·가동 중이다. 연속 WAL + 정기 base 로 **RPO ~분·RTO <10분** 을 상시 보장한다. 미구현 갭 = etcd·Harbor·Jenkins 백업(§7).

## 1. 아키텍처 전제 (Docker → K8s 변경)

| | Docker/VM 시절 (구 문서) | **현재 (K8s, P2 이전 완료)** |
|---|---|---|
| 데이터 위치 | 클러스터 밖 `fb-data` VM | **클러스터 안** — PG=CNPG `pg`(data ns, 앱→`pg-rw.data.svc`) · ES=ECK · Redis=Sentinel · Kafka=Strimzi |
| 백업 실행 주체 | VM systemd timer + Ansible | **K8s 오퍼레이터** (CNPG barman-cloud 플러그인) |
| PG 백업 도구 | pgBackRest | **barman-cloud 플러그인 + `ObjectStore` CR** (in-tree 방식은 CNPG 1.31.0 에서 제거) |
| 오프사이트 | S3 `ap-northeast-2` | 동일 — `s3://mp-backup-ap2/` |

- 원칙은 안 바뀌었다: **"사용자가 만든 원본만 지키고, 재생성 가능한 건 백업하지 않는다."**

## 2. 백업 대상 매트릭스

| 대상 | 백업? | 방법 | 현재 상태 | 근거 |
|---|---|---|---|---|
| **PostgreSQL** (회원·예산·지출·냉장고·식단·레시피북) | ✅ 필수 | CNPG barman-cloud: **연속 WAL + 정기 base** → S3 | ✅ WAL 가동 · base = `ScheduledBackup/mp-pg-daily`(03:00 KST) | 사용자 원본, 재생성 불가 |
| **Elasticsearch** | ❌ 안 함 | **PG 에서 재색인** | 재색인 Job (리허설 실측 7초) | PG 에서 재파생 가능 |
| **Redis** | ❌ 안 함 | 재생성 | 비영속 캐시 설계 | 장바구니 원본은 PG `mealplan.cart_item` |
| **Kafka** | ❌ 안 함 | 재수집 / 드레인 | 7d 보존 큐 | 원본 사이트에서 재수집 · 처리 대기 메시지 손실은 명시적 허용 |
| **비밀·설정** | ✅ | AES-256 묶음 → S3 | ✅ 검증(2026-07-29) | 재생성 불가 |
| **tfstate** | ✅ | S3 backend 이관 | ✅ E2E 검증 | — |
| **etcd** (클러스터 상태) | ⬜ 권장·미구현 | etcd snapshot → S3 | ❌ **갭 (§7)** | 클러스터 DR |
| **Harbor** (DB·설정·인증서) | ⬜ 권장·미구현 | archive → S3 | ❌ **갭 (§7)** | 이미지는 CI 재빌드, DB·설정·인증서는 재생성 어려움 |
| **Jenkins** (`JENKINS_HOME`) | 🟡 선택·미구현 | archive → S3 | ❌ **갭 (§7)** | JCasC 가 git 이면 우선순위↓ |

## 3. RPO/RTO — K8s 재-baseline

구 문서의 목표는 **연속 WAL 이 없던 시절 기준**(RPO 12h)이었다. K8s 는 연속 WAL + HA 로 이를 크게 넘는다. 아래가 K8s 실측 기반 신 목표다.

| 대상 | 구 목표 (Docker) | **K8s 실측/능력** | **신 목표 (K8s)** |
|---|---|---|---|
| PG — RPO | 12시간 | 파드/노드 장애 = ~0 (HA standby 최신) · 전체 손실 = ~5분 (archive_timeout 302s) | **~5분** (전체 손실) / **~0** (파드·노드) |
| PG — RTO | 40분 | HA 페일오버 초 단위 · S3 복원 promote 4초·재구축 116초 (DB 141MB) | **< 10분** (손상·논리오류) |
| PG — RTO (파드·노드 장애) | (해당 계층 없음) | CNPG 자동 페일오버 | **초 ~ 1분** ← 신설 계층 |
| ES | RPO 12h · RTO 2h | 재색인 7초 | **분 단위** (재색인) |
| Redis | RTO 10분 | 재생성(즉시) | 분 단위 |
| Kafka | RTO 2h | 재수집/드레인 | RTO 2h (유지) |
| 전체 클러스터 DR | RTO 4시간 | IaC 재구축 + S3 복원 (+etcd 백업 시 단축) | 수 시간 (etcd 백업 + 런북 전제) |

> 🔴 개선된 RPO/RTO 는 **"최신 base + WAL 체인"이 항상 있어야** 성립한다. 정기 base(`ScheduledBackup`)가 이를 상시 보장하는 장치다 — base 가 오래되면 복구 시 WAL 재생량이 늘어 RTO 가 다시 열화한다.

## 4. PG 백업 구조 — "2개 한 쌍"

PG 백업은 두 조각이 짝을 이룬다.

| | 역할 | 비유 | 구현 |
|---|---|---|---|
| **연속 WAL 아카이빙** | 매 변경을 계속 S3 로 → PITR(RPO) | 소설의 "매 문장 수정 로그" | cluster 의 barman-cloud plugin (`ContinuousArchiving=True`) |
| **정기 base backup** | 가끔 전체 스냅샷 → 복구 앵커(RTO) | 소설의 "전체 저장본" | `ScheduledBackup/mp-pg-daily`, 매일 03:00 KST |

- **복구 = 최신 base 를 열고 → 그 이후 WAL 을 순서대로 재생.** base 가 최신일수록 재생할 WAL 이 적어 복구가 빠르다.
- **저장소** = `ObjectStore/mp-pg-backup` → `s3://mp-backup-ap2/pg`, **보존 30일**, data·WAL gzip.
- **자격증명** = `mp-pg-backup-s3` Secret(ESO), 앱 파드는 백업 자격증명을 갖지 않는다.

## 5. 복구 계층 (3단)

| 계층 | 상황 | 복구 방법 | 목표 |
|---|---|---|---|
| **Tier 1 — HA 페일오버** | 파드/노드 1대 사망 | CNPG 가 standby(`pg-2`)를 자동 primary 승격 | 초 ~ 1분, 데이터 손실 ~0 |
| **Tier 2 — 백업 복원** | 데이터 손상·논리 오류·양쪽 파드 손실 | 새 Cluster `bootstrap.recovery` → barman-cloud 가 S3 base+WAL 복원 → promote | < 10분 |
| **Tier 3 — 전체 DR** | 클러스터/사이트 상실 | Terraform·Ansible 로 재구축 → S3 복원(PG) → ES 재색인 → Redis 재생성 → 앱 재배포 | 수 시간 (etcd 백업 시 단축) |

## 6. 검증 (백업 파일 존재 ≠ 복구 가능)

- **왕복 복원 증명** = P2 게이트① 완료(2026-07-29) — barman-cloud 백업→S3→복원 왕복, 스냅샷 정합법으로 40테이블 350,850행·리허설 41테이블 630,889행 VM 완전 일치.
- **정기 훈련**: 월 1회 PG 표본 복원, 분기 1회 S3 만 사용한 전체 복구 훈련. 실측 시간 기록 → 목표 초과 시 RTO·자동화 조정.
- **기능 스모크**(복구 완료 판정 기준 — healthcheck 통과만으로 선언 금지): 로그인 · 예산/지출 · 냉장고 · 식단/장바구니 · 레시피북 · ES 검색 · 가격 비교.

## 7. 로드맵 — 미구현 갭 (우선순위)

현재 **PG 만 백업된다.** 아래는 아직 없는 것들, 우선순위순:

1. **PG `ScheduledBackup`** — ✅ (이 전략의 핵심, config `platform/pg/scheduledbackup.yaml`).
2. **etcd snapshot** — ❌ 클러스터 상태 DR. 마스터에 snapshot cron/systemd → S3. 없으면 클러스터를 IaC 로 재구축(느림).
3. **Harbor** — ❌ DB·설정·인증서 archive → S3(이미지는 CI 재빌드 가능).
4. **Jenkins** — 🟡 `JENKINS_HOME` archive → S3. JCasC 가 git 이면 credentials·job history 만 가치 → 우선순위 낮음.

> ES·Redis·Kafka 는 **의도적 백업 제외**(재파생/재수집) — 다이어그램의 ES snapshot 안은 채택하지 않는다(재색인 7초라 백업 실익 없음).

---

### 참고

- 구현·전환 세부(오퍼레이터 핀·전환창·게이트) = [`mp_k8s_p2_data_runbook.md`](./mp_k8s_p2_data_runbook.md)
- 인프라 현황 = [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md)
- 매니페스트 = config 레포 `platform/pg/`(CNPG Cluster·ObjectStore·ScheduledBackup)
