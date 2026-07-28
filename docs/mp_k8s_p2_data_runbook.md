# P2 데이터 플랫폼 이전 런북 — PG·ES·Redis·Kafka + Pooler·PGSync

> **P2 담당자의 단일 진입점.** 상위 계획·근거 = [`mp_k8s_infra_migration_plan.md §10`](./mp_k8s_infra_migration_plan.md) — 이 문서는 그 P2 행의 **실행 상세**다.
> 2026-07-28 grilling 인터뷰로 확정(Q1~Q10 전건 합의). 여기 없는 상위 결정(오퍼레이터 선정·배치·따라잡기 전략·전환창 골격)은 플랜이 정본이고 **재논의하지 않는다.**
> 🔴 **선행 게이트 2개**: ① S3 백업·복구 왕복 증명(플랜 §10 — 없이 착수 금지) ② worker-a1 합류(P1 후 — 3노드에 데이터 티어 13.4GB 는 안 들어간다).

---

## 0. 확정 결정 요약 (2026-07-28)

| # | 결정 | 내용 |
|---|---|---|
| Q1 | 매니페스트 git 집 | **config 레포 `platform/`** — 단일 배포 소스. ⚠️ 수용 리스크: P2 의 Jenkins 쓰기 자격증명이 같은 레포 전체에 닿는다(경로 스코프 불가 — 탐지는 ArgoCD diff·커밋 이력, 예방은 없음) |
| Q2 | 오퍼레이터 설치 | **platform-root(app-of-apps) 신설** — `platform/argocd/*.yaml` child 를 자동으로 집음. 오퍼레이터 4종 = 공개 Helm 차트 소스 child. LGTM Application 3개도 git 으로 이사, `k8s_platform_apps` 롤 은퇴. Ansible 바닥 = AppProject + platform-root 하나 |
| Q3 | Redis 구현체 | **OT-Container-Kit 후보 + 선행 실물 검증**: master 파드 kill → master Service 실갱신 확인. 통과→앱 무변경(A) / 부실→오퍼레이터 유지+클라이언트 Sentinel 전환(C, 접속 3곳: chat·price `db.py` + `pipelines/stream/_redis.py`) / 오퍼레이터 불신→수제(B). Spotahome=유지보수 중단·Bitnami=이미지 유료화로 기각 |
| Q4 | PG | **16 유지 컷오버**(메이저 업그레이드는 안착 후 별건) · `externalClusters`+`pg_basebackup`→replica→promote · 🔴 **promote 직후 REINDEX**(musl→glibc collation, §9 함정) · PVC data 20Gi+wal 10Gi · **tfstate DB 는 S3 백엔드로 이관**(K8s PG 로 가면 순환 의존) · dev DB(51MB) 이관 안 함 · role 3종은 basebackup 자동 승계 |
| Q5 | ES | **8.19.x 상향**(재파생이라 자유·클라이언트 핀 `<9` 무변경) · products 인덱스 = 스코프 아웃(현존 안 함) · **nori 이미지 신설**: `infra/images/elasticsearch-nori/` + Jenkins CATALOG, 태그 = ES 버전 그대로 · 재색인 = **K8s Job**(mp-data-pipeline 이미지, 소스=CNPG standby 읽기전용) · PVC 10Gi×3 |
| Q6 | Kafka | **4.0.x 후보**(클라이언트 핀 호환 게이트, 걸리면 3.9 동결) · KafkaTopic CRD 4개 — 파티션 현행(3/3/3/2)·RF=3·retention 7d 명시 · **무인증 PLAINTEXT + NetworkPolicy 접근 제어**(SASL 기각 — WireGuard=암호화·NetPol=접근·변경 반경 대비 실익 없음) · PVC 20Gi×3 · `persistent-claim` 명시(LOG_DIRS 사고) |
| Q7 | 복제 경로 | 파드→`.8` 은 **노드 IP 로 SNAT** → VM 준비: `streaming_replica` user + pg_hba `host replication` ×노드IP 4개(`.20` 포함) + **`wal_keep_size=1GB`**(슬롯 안 씀 — 고아 슬롯 디스크 잠식보다 재-basebackup[분 단위]이 싼 실패 모드) · data ns egress `.8` 허용 |
| Q8 | 전환창 | **쓰기 봉인 = VM PG `default_transaction_read_only=on`**(앱 유지·쓰기만 봉인 — 유실 0 보장) · 예산 15분/목표 10분 · **평일 09:00~10:30 KST** · **풀 리허설 1회**(구축→promote→검증→삭제→재부트스트랩) · **데이터 CR 앱 = manual sync**(P2 기간 — selfHeal 이 promote 를 리버트하는 사고 방지, P3 에 automated 승격) · 파이프라인 매니페스트 = config 레포 **`pipelines/`**(소유=인프라, child 는 platform-root 가 집고 project=mealplanning) |
| Q9 | 관측·알림 | 경로 = in-cluster 수집→remote_write→`.11` 규칙 평가(기존 브리지) · **PG 만 지표 개명**(`pg_*`→CNPG `cnpg_*`) → PG·PGSync 계열 규칙만 P2 에서 재작성, 나머지(Kafka lag·Redis·ES)는 같은 exporter 라 무수정 · **전환 후 `.11` 의 `.8` 스크레이프·규칙 정리**(알람 폭풍 방지 — ⚠️ `--limit monitoring` 지뢰: 파일복사+재생성 경로로만) |
| Q10 | 검증·산출물 | 정합 4종(아래 §5) + CNPG 페일오버 데모(컷오버 후 며칠 내 — kill primary(A)→자동 승격(B)→RTO 실측→switchback) + 이 문서가 산출물 |

---

## 1. 실측 인벤토리 (2026-07-28 — 수치가 오래되면 재측정)

| 대상 | 실측 |
|---|---|
| PG | **16.14-alpine(musl)** · foodbudget **141MB** + dev 51MB + tfstate 8MB · 확장 = plpgsql 뿐 · role = terraform·fbapp·pgsync · `wal_level=logical` ✓ · PGSync 논리 슬롯 1 · 🔴 `datcollate=en_US.utf8`(musl 스텁 — §9-1) · 🔴 pg_hba 의 replication 라인 = **localhost 전용**(§9-2) · `wal_keep_size=0` |
| ES | **8.15.3** · 인덱스 2개뿐 — `recipes_pgsync`(8,419 docs·4.1MB)·`recipes`(1.9MB) · analysis-nori 플러그인 · 클라이언트 핀 `elasticsearch[async]>=8.15,<9`(chat·recipe) |
| Kafka | **3.9.0**(apache 이미지·단일 브로커) · 114MB · 토픽 4: `recipe.crawl.raw`(3p)·`retail.crawl.raw`(3p)·`events.user.activity`(3p)·`retail.deal.raw`(2p), 전부 retention 7d · 그룹 4: retail-refiner·deal-notifier·recipe-refiner·user-event-sink |
| Redis | redis:7-alpine ×2(app + redis-pgsync 분리) · 앱 소비자 = **chat·price 의 `db.py` + `pipelines/stream/_redis.py` = 접속 코드 3곳**, 전부 단일주소·Sentinel 비인지 |

## 2. 준비 작업 (전환창 전 — 시점별)

**A. 지금 가능 (P1 과 무관):**
1. **Redis 오퍼레이터 실물 검증** (Q3 — 반나절): OT RedisReplication+Sentinel 임시 배포 → master kill → Service 갱신·소요시간·클라이언트 에러 형태 기록 → 분기 결정(A/C) → 철거
2. **nori 이미지**: `infra/images/elasticsearch-nori/Dockerfile`(elastic 공식 8.19.x + `elasticsearch-plugin install analysis-nori`) → Jenkins CATALOG 추가 → 빌드·push
3. **config 레포 구조 + platform-root 배선** (Q1·Q2): `platform/argocd/` 신설 · platform-root Application+AppProject(Ansible) · LGTM 3개 이사 · 앱 담당자에게 디렉토리 신설 공유
   - 🔴 **platform AppProject 화이트리스트 확장 필수**(2026-07-28 충돌 검사): 현행 = ClusterRole·Binding 2종뿐 — 오퍼레이터가 만드는 **CRD + Validating/MutatingWebhookConfiguration**(CNPG·Strimzi)을 추가해야 child sync 가 산다
   - 🔴 **LGTM 이사 순서 고정**: git 추가 → root 인수 확인 → **같은 날 `k8s_platform_apps` 태스크 은퇴** (정본 이원화 창 최소화)
4. **VM PG 준비** (Q7, data_tier 롤): `streaming_replica` user · pg_hba replication ×4 · `wal_keep_size=1GB` · 검증 = 노드에서 `psql "host=192.168.0.8 user=streaming_replica replication=1"`
4-1. **노드 sysctl `vm.max_map_count=262144`** (`k8s_node` 롤 — 2026-07-28 충돌 검사): ECK 기본은 특권 initContainer 로 이걸 설정하는데 **data ns PSS baseline 이 거부한다**(istio-init 사고와 동형). 노드 레벨로 미리 깔고 ES 매니페스트에서 init 비활성
5. 오퍼레이터 4종 child Application 작성(버전은 이 시점에 타르볼 검증 후 핀 — CNPG 의 PG16 지원·ECK 의 ES 8.19·K8s 1.34 매트릭스·Strimzi 의 Kafka 4.0/클라이언트 호환 게이트)

**B. S3 게이트 열리면:** 백업·복구 왕복 증명(플랜 §10) + **tfstate → S3 백엔드 이관**(Q4-4)

**C. P1 후 (worker-a1 합류):** 데이터 CR 배포(manual sync) → CNPG replica 구축·복제 확인 → ES 사전 재색인 Job(§3 — standby 정합 실증 겸) → 파이프라인 dark-deploy → **풀 리허설(§7)** → 전환창 일정 확정

## 3. 매니페스트 구조 (config 레포)

```
platform/
  argocd/            # child Application 들 — platform-root 가 자동으로 집음
    cnpg-operator.yaml  eck-operator.yaml  strimzi-operator.yaml  redis-operator.yaml
    loki.yaml  tempo.yaml  alloy.yaml            # LGTM 이사분
    pg.yaml  es.yaml  kafka.yaml  redis.yaml  pgsync.yaml   # 데이터 CR 앱 (manual sync!)
  pg/  es/  kafka/  redis/  pgsync/               # CR·values 본문
pipelines/           # 컨슈머 4 + CronJob 11 + retrain (kustomize, dark-deploy 상태로 작성)
```

## 4. 전환창 순서 (예산 15분 · 평일 09:00 KST)

```
T-1일   리허설 완료 상태 확인 · 팀 공지 · .8 스냅샷(안전망)
0. 사전: replica lag≈0 확인 · 검증 스크립트 준비 · ArgoCD 데이터 앱 전부 manual 확인
1. VM 크론 정지 (파이프라인 쓰기 중단)
2. Kafka 드레인: 4개 그룹 lag=0 확인 → 컨슈머 정지
3. 🔒 쓰기 봉인: VM PG default_transaction_read_only=on + reload  ← 열화 시계 시작
4. CNPG promote (replica.enabled=false — git 커밋 + manual sync, 또는 kubectl cnpg promote)
5. REINDEX DATABASE foodbudget + collation version refresh  (§9-1 — 필수, ~2분)
6. 정합 검증 §5-①(행 수 전수 대조) — 불일치 시 여기서 중단·원복(비용 최소 지점)
7. 앱 ConfigMap 좌표 갱신(PG→Pooler·ES basic_auth·ES_INDEX=recipes·Kafka bootstrap) → 롤아웃
8. 앱 스모크 §5-⑤ → 통과 시 열화 종료 (여기까지 목표 10분)
9. 파이프라인 기동: KafkaTopic CRD sync → CronJob unsuspend·컨슈머 replicas up
10. PGSync: 슬롯 생성 → 초기 동기화 → recipes_pgsync 반영 확인 → ES_INDEX 플립
11. .11 관측 정리: .8 스크레이프 잡 제거·PG 규칙 cnpg_* 재작성 반영 (⚠️ §9-5 지뢰)
12. 관찰창 60분 (§6) → 종료 선언 · .8 정지(P4 까지 보존)
```

## 5. 검증 (리허설·본번 공용 — 스크립트화)

1. **PG 행 수 전수 대조**: 전 스키마·전 테이블 count 를 VM·K8s 양쪽에서 뽑아 diff — 쓰기 봉인 후라 **완전 일치가 정상**
2. **ES 재파생 정합**: PG servable 레시피 count = ES `docs.count`
3. **Kafka 구조**: 토픽 4·파티션 3/3/3/2·RF=3 describe
4. **PGSync CDC 왕복**: 테스트 레코드 INSERT → `recipes_pgsync` 반영 → 삭제
5. **앱 스모크**: 전 서비스 헬스 + 검색 1 + 쓰기 플로우 1(밀플랜 저장)

## 6. 롤백 기준

- **관찰창 = 60분.** Sev-1(정합 깨짐·주요 플로우 불능)이면: 앱 ConfigMap 을 VM 좌표로 원복 + VM read_only 해제. **그간 K8s 쓰기는 유실 수용**(역복제 없음 — 그래서 60분으로 짧게)
- **60분 경과 후 = roll-forward 원칙** — 쌓인 쓰기가 롤백 비용을 역전시킨다. 평시에 정한 이 기준을 장애 중에 재논쟁하지 않는다
- 스텝 6(행 수 대조) 불일치 = 그 자리에서 중단·원복이 최저비용 — 앱 전환 전이라 유실도 0

## 7. 리허설 (1회 필수 — DB 141MB 라 가능한 사치)

replica 구축 → promote → REINDEX → 검증 §5-①② → **클러스터 CR 삭제 → 재-basebackup 재구축**까지 통으로. 산출: 스텝별 실소요(→ §4 예산 보정) · promote/REINDEX 실동작 · **"망하면 지우고 재구축" 복구 경로의 사전 검증**. 리허설 중 VM 은 무영향(읽기만).

## 8. 관측·알림 조정 (Q9)

- CNPG `enablePodMonitor` · Strimzi `kafkaExporter`(동일 exporter=지표명 보존) · OT `redisExporter` 사이드카 · ES exporter 차트 1개(basic_auth)
- P2 규칙 손질 = **PG·PGSync 계열만** `.11` 위에서 `cnpg_*`/K8s 표현식으로 — 전면 이관은 P4 그대로
- CNPG 공식 Grafana 대시보드 = `grafana_dashboard` 라벨 CM (sidecar 자동 로드)

## 9. 함정 목록 (이 계획이 밟고 지나간 지뢰 — 실측 근거)

1. 🔴 **collation**: VM 은 musl 빌드인데 `datcollate=en_US.utf8` — 물리 복제로 glibc(CNPG)에 옮기면 텍스트 인덱스가 조용히 오작동. **promote 직후 REINDEX 필수** (§4-5)
2. 🔴 **pg_hba**: `host all all all` 은 있어도 **replication 은 localhost 전용** — 원격 복제는 별도 라인 필요 (§2-A4)
3. 🔴 **ArgoCD selfHeal vs promote**: automated 면 전환창의 수동 CR 조작이 몇 초 만에 리버트된다 — 데이터 앱은 P2 기간 manual (§0-Q8)
4. 🔴 **`.8` 정지 = 알람 폭풍**: `.11` 이 보던 VM exporter 가 전부 down — 정리 스텝(§4-11) 없이 정지하면 진짜 장애가 묻힌다
5. 🔴 **`.11` 규칙 수정 지뢰**: `--limit monitoring` 플레이는 Slack 웹훅을 지운다 — 파일복사+컨테이너 재생성 경로로만
6. **WAL 보존**: 슬롯 대신 `wal_keep_size=1GB` — 고아 슬롯의 디스크 잠식(PGSync 슬롯 사고 계열)보다 재-basebackup(분)이 싼 실패 모드
7. **Jenkins 쓰기 자격증명**(P2 개통 시): config 레포 전체에 닿는다 — platform/ 도 사정거리. 수용 리스크, ArgoCD diff·커밋 이력으로 탐지
8. 🔴 **platform AppProject 가 오퍼레이터를 못 담는다**(2026-07-28 충돌 검사 실측): 클러스터 스코프 화이트리스트가 RBAC 2종뿐 — CRD·웹훅 추가 없이 child 를 넣으면 sync 즉사 (§2-A3)
9. 🔴 **ECK 특권 init vs baseline**: `vm.max_map_count` 를 노드 sysctl 로 선반영 + init 비활성 (§2-A4-1)
10. **PriorityClass 실이름**(실측): 앱 급 = `app-normal`(100000) · 데이터 = `data-critical`(1000000) · 파이프라인 = `pipeline-low`(1000) — 매니페스트에 이 이름 그대로(없는 이름 = 스케줄 거부). PGSync = `app-normal`
11. **P2 시점 RAM = requests 기준 ~78%**(4노드 30Gi 중 23.5Gi — 기반·LGTM 5 + P1 5.1 + 데이터 13.4): 예산 내지만 빡빡 — P4(5노드)에서 해소, 그전까지 requests 정합 관리 필수. worker-a1 VG 150G 는 템플릿 동일 가정 — **P1 생성 시 확인**
