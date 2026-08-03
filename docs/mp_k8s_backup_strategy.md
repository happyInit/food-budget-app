# 밀플래닝 백업 전략 (Kubernetes) — 정본(SSOT)

> 작성: 2026-07-30 · **갱신: 2026-07-31**(호스트 레벨 백업 3트랙 가동 — §7) · 실측 근거: [P2 데이터 이전 런북](./mp_k8s_p2_data_runbook.md) 리허설·게이트①(2026-07-29)
>
> 🔴 **이 문서가 K8s 백업 전략의 정본이다.** [`backup-strategy.md`](./backup-strategy.md)(2026-07-20)는 **Docker/VM 시절 문서로 superseded** — RPO/RTO 목표와 "무엇을 백업/재생성하나" 원칙은 여기로 계승됐고, 메커니즘(데이터=VM·백업=VM systemd·pgBackRest)은 폐기됐다.

## 0. 한 줄 요약

데이터 티어가 **클러스터 안(CNPG·ECK·Strimzi·Redis)** 으로 옮겨오면서, 백업은 **CNPG barman-cloud 플러그인 → S3** 로 이미 구현·검증(왕복 복원)·가동 중이다. 연속 WAL + 정기 base 로 **RPO ~분·RTO <10분** 을 상시 보장한다. 여기에 **호스트 레벨 백업**(클러스터 밖 systemd timer → S3, 전용 IAM 유저 `mp-backup`)으로 **etcd·소스코드·릴리스 이미지**까지 가동(2026-07-31 왕복검증) — Harbor·Jenkins config 는 코드 완료·적용 보류(§7).

## 1. 아키텍처 전제 (Docker → K8s 변경)

| | Docker/VM 시절 (구 문서) | **현재 (K8s, P2 이전 완료)** |
|---|---|---|
| 데이터 위치 | 클러스터 밖 `fb-data` VM | **클러스터 안** — PG=CNPG `pg`(data ns, 앱→`pg-rw.data.svc`) · ES=ECK · Redis=Sentinel · Kafka=Strimzi |
| 백업 실행 주체 | VM systemd timer + Ansible | **K8s 오퍼레이터** (CNPG barman-cloud 플러그인) |
| PG 백업 도구 | pgBackRest | **barman-cloud 플러그인 + `ObjectStore` CR** (in-tree 방식은 CNPG 1.31.0 에서 제거) |
| 오프사이트 | S3 `ap-northeast-2` | PG·tfstate=`mp-backup-ap2` · 호스트 백업은 **컴포넌트별 전용 버킷**(§7) · 공용 IAM 유저 `mp-backup`(최소권한) |

- 원칙은 안 바뀌었다: **"사용자가 만든 원본만 지키고, 재생성 가능한 건 백업하지 않는다."**

## 2. 백업 대상 매트릭스

| 대상 | 백업? | 방법 | 현재 상태 | 근거 |
|---|---|---|---|---|
| **PostgreSQL** (회원·예산·지출·냉장고·식단·레시피북) | ✅ 필수 | CNPG barman-cloud: **연속 WAL + 정기 base** → S3 | ✅ WAL 가동 · base = `ScheduledBackup/mp-pg-daily`(03:00 KST) | 사용자 원본, 재생성 불가 |
| **PostgreSQL — 온사이트 논리 덤프** | ✅ 보조 | `pg_dump -Fc` → 인클러스터 MinIO | ✅ **E2E 검증**(2026-08-03) · `CronJob/mp-pg-onsite-dump`(04:00 KST) · 보존 7일 (§4.1) | 테이블 단위 즉시 복원. 🔴 **DR 아님** — MinIO 가 b2 단독이라 호스트 B 와 운명을 같이한다 |
| **Elasticsearch** | ❌ 안 함 | **PG 에서 재색인** | 재색인 Job (리허설 실측 7초) | PG 에서 재파생 가능 |
| **Redis** | ❌ 안 함 | 재생성 | 비영속 캐시 설계 | 장바구니 원본은 PG `mealplan.cart_item` |
| **Kafka** | ❌ 안 함 | 재수집 / 드레인 | 7d 보존 큐 | 원본 사이트에서 재수집 · 처리 대기 메시지 손실은 명시적 허용 |
| **비밀·설정** | ✅ | AES-256 묶음 → S3 | ✅ 검증(2026-07-29) | 재생성 불가 |
| **tfstate** | ✅ | S3 backend 이관 | ✅ E2E 검증 | — |
| **etcd** (클러스터 상태) | ✅ 구현 | etcd snapshot → S3 (마스터 systemd timer) | ✅ **왕복검증**(2026-07-31) · 매일 02:00 KST → `mp-etcd-backup-ap2` (§7) | 클러스터 DR |
| **소스코드** (레포 미러) | ✅ 구현 | `git clone --mirror`→tar.gz→S3 (호스트 C timer) | ✅ **왕복검증**(2026-07-31) · 매월 1일 03:30 → `mp-source-backup-ap2` (§7) | GitHub 상실 DR (전 히스토리·태그) |
| **릴리스 이미지** | ✅ 구현 | `docker save`→S3 (Jenkinsfile 릴리스 스테이지) | ✅ 배선 완료 · 릴리스마다 → `mp-image-backup-ap2` (§7) · best-effort | 재빌드 불가 대비 산출물 보관 |
| **Harbor** (DB·키·설정·인증서) | 🟡 코드완료·미적용 | archive → S3 (호스트 C timer) | ⏸ 롤·버킷 준비, 적용 보류 (§7) | 이미지는 CI 재빌드, DB·키·설정은 재생성 어려움 |
| **Jenkins** (`JENKINS_HOME`) | 🟡 코드완료·미적용 | archive → S3 (호스트 C timer) | ⏸ 롤·버킷 준비, 적용 보류 (§7) | JCasC 없음 → credentials·마스터키·job 이 HOME 에만 |

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
| **etcd** (클러스터 상태·Secret 포함) | (해당 없음) | **단일 멤버**(control-plane 1대) · 스냅샷 매일 02:00 · 복원 `etcdctl snapshot restore` | **RPO ≤ 24h** (스냅샷 간격 — 단일 멤버라 노드 상실=스냅샷 복원) / **RTO ~30분** (복원, 노드 재구축 시 Tier3 포함) |
| 전체 클러스터 DR | RTO 4시간 | IaC 재구축 + S3 복원 (etcd 백업 가동으로 단축) | 수 시간 (etcd 백업 §7 + 런북 전제) |

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

### 4.1 온사이트 논리 덤프 — 세 번째 조각 (2026-08-03 신설 · ✅ E2E 검증)

위 2개는 **오프사이트(S3)** 다. 여기에 **인클러스터 논리 덤프**를 하나 더 붙였다.

| | 온사이트 덤프 (신설) | 오프사이트 barman (기존) |
|---|---|---|
| 구현 | `CronJob/mp-pg-onsite-dump`, 매일 **04:00 KST** | 연속 WAL + `ScheduledBackup` 03:00 KST |
| 저장 | 인클러스터 MinIO `mp-pg-onsite` 버킷 | `s3://mp-backup-ap2/pg` |
| 형식 | `pg_dump -Fc -Z6` (논리) | 물리 base + WAL |
| 보존 | **7일** | 30일 |
| 잘하는 것 | **테이블 1개만 즉시 되살리기** (`pg_restore -t`) | **PITR** — 임의 시점 복원 |
| 못 하는 것 | 시점 복원 불가 · **사이트 상실에 무력** | 부분 복원이 무거움(새 Cluster bootstrap) |

**왜 추가했나** — 기존 구조에는 *"누가 실수로 한 테이블을 날렸다"* 에 대한 **가벼운 답이 없었다.**
S3 PITR 은 새 Cluster 를 bootstrap 해야 해서 분 단위가 들고 절차도 무겁다. 논리 덤프가 있으면
`pg_restore -t <테이블>` 한 줄이다.

**배치 (2026-08-03 실측)** — 덤프는 호스트를 가로지른다:

```
호스트 A                       호스트 B
├ worker-a1  pg-1 (primary) ──┐  ├ master
└ worker-a2                   │  ├ worker-b1  pg-2 (replica)
                              └─▶└ worker-b2  MinIO (단일 replica)
                          pg_dump              mp-pg-onsite 버킷
```

🔴 **DR 로 오해하면 안 된다.** 다만 이유는 "PG 와 같이 죽어서"가 **아니다** — PG 는 A·B 에 갈라져 있어
한쪽 호스트가 죽어도 CNPG 가 살린다. 진짜 이유는 **저장소 쪽**이다:

- MinIO 는 **단일 replica · `worker-b2` 고정 · OpenEBS LocalPV**(노드 로컬 디스크) → **사본이 0개**다.
  b2 의 디스크가 나가면 **7일치 덤프가 한 번에 전부** 사라진다. 복구할 백업이 없어지는 백업은 DR 이 아니다.
- 그리고 **PG 와 MinIO 가 같은 클러스터·같은 사이트**에 있다. 정전·네트워크·하이퍼바이저 같은
  사이트 단위 사건에는 둘 다 함께 나간다.

→ 사이트 상실의 답은 **S3 하나뿐**이다. 이건 백업 **벌 수**가 아니라 **복구 속도 계층**이 는 것이다
(§5 Tier 2 를 "무겁고 안전한 S3" / "가볍고 빠른 온사이트" 둘로 가른다).

**실측(2026-08-03 검증 런)**: `foodbudget` 238MB → **23MB · 약 30초**(덤프 3초 + 검증 + 업로드).
7일 보존 ≈ 170MB, MinIO 여유 49GB 대비 0.4% → 용량은 제약이 아니다.

**설계상 짚은 것 3가지**
1. **superuser 를 안 쓴다.** `fbapp` 이 DB 소유자이자 앱 스키마 8개 전부의 소유자라 전체 덤프가 된다
   (실측 exit=0 · 복원 오브젝트 353개). CNPG `enableSuperuserAccess: false` 를 유지한다.
   🔴 **대가 = 전역 오브젝트(롤)가 덤프에 없다.** 복원 순서는 **CNPG 로 빈 클러스터 → 덤프 restore** 다.
2. **pooler 경유 금지.** `PGHOST=pg-rw` 직결. PgBouncer transaction 모드에서 `pg_dump` 는 깨진다.
3. **netpol 이 실제 함정이었다.** `mp-pg-instance` 가 PG 인그레스를 5개 출처로 제한하는데
   백업 파드는 어디에도 안 걸려 **조용히 타임아웃**한다(드롭이라 로그도 없다).
   → ingress 9) 신설 + 백업 파드 자신도 egress 잠금(`netpol-pg-onsite.yaml`, DNS·PG·MinIO 만).
4. **자격증명은 MinIO root 가 아니다.** 버킷 한정 키(`mp-pg-onsite` 유저 + `mp-pg-onsite-rw` 정책).
   root 를 data ns 에 두면 그 ns 가 뚫렸을 때 loki·tempo·models 버킷까지 넘어간다.

**"파일이 생겼다"로 끝내지 않는다** — Job 안에서 `pg_restore --list` 로 아카이브 목차를 읽고
오브젝트 수가 50 미만이면 **업로드 자체를 중단**한다(§6 원칙의 자동화판).

**매니페스트** = config 레포 `platform/pg/onsite-backup.yaml` · `platform/pg/externalsecrets.yaml`
(`mp-pg-onsite-minio`) · `platform/policies-data/netpol-pg{,-onsite}.yaml`.

**남은 것** = ① 알람(덤프 실패·최신 객체 나이) 미구현 ② 월 1회 실제 `pg_restore` 훈련에 이 덤프 편입.

## 5. 복구 계층 (3단)

| 계층 | 상황 | 복구 방법 | 목표 |
|---|---|---|---|
| **Tier 1 — HA 페일오버** | 파드/노드 1대 사망 | CNPG 가 standby(`pg-2`)를 자동 primary 승격 | 초 ~ 1분, 데이터 손실 ~0 |
| **Tier 2 — 백업 복원** | 데이터 손상·논리 오류·양쪽 파드 손실 | 새 Cluster `bootstrap.recovery` → barman-cloud 가 S3 base+WAL 복원 → promote | < 10분 |
| **Tier 3 — 전체 DR** | 클러스터/사이트 상실 | Terraform·Ansible 로 재구축 → **etcd 복원**(§7) → S3 복원(PG) → ES 재색인 → Redis 재생성 → 앱 재배포 | 수 시간 (etcd 백업으로 단축) |

## 6. 검증 (백업 파일 존재 ≠ 복구 가능)

- **왕복 복원 증명** = P2 게이트① 완료(2026-07-29) — barman-cloud 백업→S3→복원 왕복, 스냅샷 정합법으로 40테이블 350,850행·리허설 41테이블 630,889행 VM 완전 일치.
- **정기 훈련**: 월 1회 PG 표본 복원, 분기 1회 S3 만 사용한 전체 복구 훈련. 실측 시간 기록 → 목표 초과 시 RTO·자동화 조정.
- **기능 스모크**(복구 완료 판정 기준 — healthcheck 통과만으로 선언 금지): 로그인 · 예산/지출 · 냉장고 · 식단/장바구니 · 레시피북 · ES 검색 · 가격 비교.

## 7. 호스트 레벨 백업 (클러스터 밖 · systemd timer → S3)

PG·tfstate 외의 백업은 **클러스터 밖 호스트의 systemd timer**(이미지는 Jenkinsfile)로 돈다 — k8s CronJob 이 아닌 이유: **컨트롤플레인·클러스터가 죽어도 백업이 계속돼야** DR 이 성립한다(etcd 는 클러스터가 죽은 그 순간을 복구하는 대상이라 특히).

- **자격증명 = 전용 IAM 유저 `mp-backup`** (2026-07-31 신설). 개인 팀원 계정 키 의존을 제거했다. 백업 버킷들에 `PutObject/GetObject/ListBucket/DeleteObject` 만 갖는 최소권한 인라인 정책 `mp-backup-s3`. 키는 `infra/ansible/secrets.yml`(호스트 백업) + Jenkins credential `mp-backup-s3`(이미지). PG barman(`mp-pg-backup-s3` ESO)은 **별개 키·미이전**(§4).
- **버킷 = 컴포넌트별 전용**(2026-07-31 분리 — blast-radius·수명주기·접근제어 독립). 한 버킷 prefix 로 뭉치던 것을 쪼갰다.

| 트랙 | 버킷 | 주기 | 실행 | 담는 것 / 상태 |
|---|---|---|---|---|
| **etcd** | `mp-etcd-backup-ap2` | 매일 02:00 KST | 마스터 timer (`k8s.yml`) | 클러스터 상태 전부 = 오브젝트·**Secret**·ConfigMap·RBAC·토큰 · ✅ 왕복검증 |
| **소스코드** | `mp-source-backup-ap2` | 매월 1일 03:30 | 호스트 C timer (`site.yml` ci) | 레포 mirror(전 히스토리·태그) · ✅ 왕복검증 |
| **릴리스 이미지** | `mp-image-backup-ap2` | 릴리스 런마다 | Jenkinsfile 스테이지 | 릴리스 `:X.Y.Z` 이미지 · ✅ 배선(best-effort) |
| **Harbor config** | `mp-harbor-backup-ap2` | 매일 02:20 | 호스트 C timer | DB·암호화키·설정·인증서 · 🟡 코드완료·미적용 |
| **Jenkins config** | `mp-jenkins-backup-ap2` | 매일 02:40 | 호스트 C timer | secrets(마스터키)·credentials·jobs·plugins · 🟡 코드완료·미적용 |

- **보존**: etcd/harbor/jenkins = S3 14일 · 소스 = 400일(~13개) · 이미지 = S3 lifecycle(버킷 설정, 릴리스 저빈도). 로컬은 최근 2~3개.
- **역할·매니페스트**: `infra/ansible/roles/{etcd,source,harbor,jenkins}_backup/`(etcd 는 `k8s.yml`, 나머지는 `site.yml` ci 플레이 — 단독 `--tags <name>_backup`) · 이미지는 레포 루트 `Jenkinsfile`(릴리스 런에서만, credential `mp-backup-s3`).
- **복원**: etcd = `etcdctl snapshot restore` · 소스 = `tar xzf`→`git clone <name>.git` · 이미지 = `gunzip│docker load`→새 Harbor push · Harbor/Jenkins = 아카이브 풀어 DB/HOME 복원.
- **적용 순서(계단식)**: etcd 02:00 → Harbor 02:20 → Jenkins 02:40 → **PG base 03:00** → 소스 03:30. "클러스터 상태 먼저, 데이터 나중" 순으로 복구 정합.
- 🔴 **etcd 스냅샷 = Secret 평문 포함**: 클러스터에 at-rest 암호화(`encryption-provider-config`)가 꺼져 있어 Secret 이 etcd 에 base64(평문)로 저장된다 → 스냅샷·S3 사본에 **모든 Secret 이 평문**으로 담긴다. 방어 = S3 퍼블릭 차단(라이브)·`mp-backup` 최소권한·로컬 `/var/backups/etcd` 0700. (근본 강화 = at-rest 암호화 켜기 — 별건.)
- **etcd 는 단일 멤버**(control-plane 1대, HA 아님) — 노드 상실 = etcd 상실 → 스냅샷 복원(RPO ≤ 24h, §3). 24h 가 부담이면 스냅샷 주기를 6h/1h 로 좁히는 게 싸다(스냅샷 ~94MB·수초, `etcd_backup_schedule`).

### 남은 갭

- **Harbor·Jenkins config 백업 적용** — 롤·버킷 준비 완료, `ansible-playbook site.yml --tags harbor_backup,jenkins_backup --limit ci` 만 남음(우선순위 낮음 — CI config 는 재구성 가능, 뒤로 미룸).
- **PG barman → mp-backup 유저 이전**(선택) — 현재 PG 는 별개 키. `data-secrets` 의 `PG_BACKUP_AWS_*` 를 mp-backup 키로 교체하면 통일되나, 라이브 PITR 이라 신중히(§4).
- ES·Redis·Kafka 는 **의도적 백업 제외**(재파생/재수집) — 유지.

---

### 참고

- 구현·전환 세부(오퍼레이터 핀·전환창·게이트) = [`mp_k8s_p2_data_runbook.md`](./mp_k8s_p2_data_runbook.md)
- 인프라 현황 = [`mp_k8s_infra_status.md`](./mp_k8s_infra_status.md)
- 매니페스트 = config 레포 `platform/pg/`(CNPG Cluster·ObjectStore·ScheduledBackup)
