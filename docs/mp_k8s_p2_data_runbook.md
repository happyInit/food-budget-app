# P2 데이터 플랫폼 이전 런북 — PG·ES·Redis·Kafka + Pooler·PGSync

> **P2 담당자의 단일 진입점이자 P2 실행 세부의 정본**(Q16). 정본 계층: 전략 결정(오퍼레이터 선정·배치·따라잡기 전략·컷오버 골격)과 그 근거 = [`mp_k8s_infra_migration_plan.md §10`](./mp_k8s_infra_migration_plan.md) — **재논의하지 않는다** / **준비·전환창·검증·게이트의 실행 세부 = 이 문서** / 현황 = `mp_k8s_infra_status.md`.
> 확정 이력: 2026-07-28 grilling Q1~Q10 → 같은 날 객체 충돌 검사(#337) → **딥인스펙트(4각 교차검사) → 2차 grilling 16건 = Q11~Q16 신설 + Q1~Q10 개정**(이 판).
> 🔴 **선행 게이트 3개**:
> ① **S3 백업·복구 왕복 증명 없이 전환창 진입 금지** — 증명은 리허설에 통합(§7). §2-C(구축·replica·리허설)는 이 게이트와 **독립**(그동안 정본은 VM — 무백업 노출 아님). 준비물(버킷+IAM 키) 데드라인 = 리허설 시작 전.
> ② **worker-a1 합류** — §2-C 진입 조건(3노드에 데이터 티어 13.4GB 는 안 들어간다). 생성 체인 = §2-C-0.
> ③ **A↔B 실링크 iperf 실측** — a1 합류 직후(§2-C-0). 집계 대역은 리허설 산출물(§7)로 go/no-go 판정.

---

## 0. 확정 결정 요약 (2026-07-28 · 2차 개정 반영)

| # | 결정 | 내용 |
|---|---|---|
| Q1 | 매니페스트 git 집 · ArgoCD 배선 | **config 레포 `platform/`** — 단일 배포 소스. **오퍼레이터 4종·데이터 CR 5종 전부 `project=platform`**(2차) — platform AppProject **3종 동시 확장**: sourceRepos(+차트 레포 4+config 레포) · destinations(+data+오퍼레이터 ns) · 클러스터 스코프(+CRD·웹훅 — 정확 kind 는 §2-A-5 타르볼 실렌더링으로 확정). 오퍼레이터 ns 생성 = Ansible `k8s_cluster_base`(PSS 라벨 일관 — ArgoCD `CreateNamespace` 금지). ⚠️ 수용 리스크: P2 의 Jenkins 쓰기 자격증명이 같은 레포 전체에 닿는다(경로 스코프 불가 — 탐지는 ArgoCD diff·커밋 이력, 예방은 없음) |
| Q2 | 오퍼레이터 설치 | **platform-root(app-of-apps) 신설** — `platform/argocd/*.yaml` child 를 자동으로 집음. 오퍼레이터 4종 = 공개 Helm 차트 소스 child. LGTM Application 3개도 git 으로 이사, `k8s_platform_apps` 롤 은퇴. Ansible 바닥 = AppProject + platform-root 하나 |
| Q3 | Redis 구현체 | **OT-Container-Kit 후보**(핀 = §1.1 — 차트·이미지 **0.25.0 정합**, v0.26.0 상향은 검증 담당자 판단) **+ 선행 실물 검증**: master 파드 kill → master Service 실갱신 확인. 통과→앱 무변경(A) / 부실→오퍼레이터 유지+클라이언트 Sentinel 전환(C — 접속 코드 **4곳**(2차): chat·price `db.py` + `pipelines/stream/_redis.py` + `pipelines/ingest/refresh_price_matview.py`) / 오퍼레이터 불신→수제(B). Spotahome=유지보수 중단·Bitnami=이미지 유료화로 기각 |
| Q4 | PG | **16 유지 컷오버**(메이저 업그레이드는 안착 후 별건 — 🔴 **CNPG 차트 기본 이미지가 PG 18.4** 라 `imageName` 명시 핀 필수, §1.1) · **백업은 처음부터 barman-cloud 플러그인 + `ObjectStore` CR**(in-tree 방식은 CNPG 1.31.0 에서 제거 — §1.1) · `externalClusters`+`pg_basebackup`→replica→promote(방식 = Q8 장전) · 🔴 **promote 직후 REINDEX**(musl→glibc collation, §9-1) · PVC data 20Gi+wal 10Gi · **tfstate DB 는 S3 백엔드로 이관**(K8s PG 로 가면 순환 의존) · 🔴 **dev·tfstate DB 는 물리 복제로 무조건 딸려온다**(2차 — "이관 안 함"의 실행형 = **roll-forward 확정 후 DROP**, §4.1-⑤) · role 3종은 basebackup 자동 승계 |
| Q5 | ES | **8.19.19 고정**(ECK 3.4.1 — 핀·함정 = §1.1. 재파생이라 상향 자유·클라이언트 핀 `<9` 무변경) · products 인덱스 = 스코프 아웃(현존 안 함) · **nori 이미지**: `infra/images/elasticsearch-nori/` + Jenkins CATALOG 15번째, **태깅 = infra 트랙 신설**(2차 — 3태그 구조 유지·버전 자리만 업스트림 ES 버전, 재빌드 시 `-rN`, **ECK CR 의 image 핀은 `:sha`**) · 재색인 = **K8s Job**(mp-data-pipeline 이미지) — 사전 재색인(§2-C)은 실증·예열·리허설용, **본번 서빙 인덱스는 창 내 재실행본**(§4-5.5, 2차) · PVC 10Gi×3 |
| Q6 | Kafka | 🔴 **Kafka 4.3.0 + Strimzi 1.1.0 확정**(2026-07-28 개정 — 원안 "4.0.x 후보/3.9 동결"은 전제 2개가 다 깨져 폐기, 경위·핀 = **§1.1·§1.1.1**) · KafkaTopic CRD 4개 — 파티션 현행(3/3/3/2)·RF=3·retention 7d 명시, 🔴 **§2-C 에서 클러스터 CR 과 함께 선생성**(2차 — 빈 토픽 무해·"토픽은 프로듀서보다 먼저", 전환창은 describe 확인만) · **무인증 PLAINTEXT + NetworkPolicy 접근 제어**(SASL 기각 — WireGuard=암호화·NetPol=접근·변경 반경 대비 실익 없음) · PVC 20Gi×3 · `persistent-claim` 명시(LOG_DIRS 사고) |
| Q7 | 복제 경로 | 파드→`.8` 은 **노드 IP 로 SNAT** → VM 준비: `streaming_replica` user + pg_hba `host replication` ×노드 IP(우선 `.17/.18/.19` 3줄 — **a1 줄은 IP 실점유 확인 후 확정 IP 로 추가**, Q15) + **`wal_keep_size=1GB`**(슬롯 안 씀 — 고아 슬롯 디스크 잠식보다 재-basebackup[분 단위]이 싼 실패 모드) · data ns egress `.8` 허용(제거 = §4.1-②) |
| Q8 | 전환창 | **쓰기 봉인 = VM PG `default_transaction_read_only=on`**(앱 유지·쓰기만 봉인 — 유실 0 보장, 전제 = §4-3.5) · 예산 15분/목표 10분(리허설 실측으로 재보정) · **평일 09:00~10:30 KST** · **풀 리허설 1회**(§7 — S3 왕복·집계 대역 포함) · **데이터 CR 앱 = manual sync**(P2 기간 — selfHeal 이 promote 를 리버트하는 사고 방지, P3 에 automated 승격) · **promote = T-1 사전 장전 + manual sync 1클릭**(2차, §4-T-1·4 — `kubectl cnpg promote` 는 오용, §9-13) · **앱 전환은 `pg-rw` 직접 — Pooler 는 P2 배포만·앱 전환·반복부하 검증·`prepare_threshold` 는 P3**(2차) · 파이프라인 매니페스트 = config 레포 **`pipelines/`**(소유=인프라, child 는 platform-root 가 집고 project=mealplanning) |
| Q9 | 관측·알림 | 경로 = in-cluster 수집→remote_write→`.11` 규칙 평가(**브리지 자체는 P1 산출물** — P2 는 그 위에서 규칙만 재작성) · **PG 만 지표 개명**(`pg_*`→CNPG `cnpg_*`) → PG·PGSync 계열 규칙만 P2 에서 재작성, 나머지(Kafka lag·Redis·ES)는 같은 exporter 라 무수정 · **켜는 것(신규 규칙) = 창 직후 §4-11, 끄는 것(`.8` 스크레이프·규칙 정리) = roll-forward 후 §4.1**(2차 — ⚠️ `--limit monitoring` 지뢰: 파일복사+재생성 경로로만) |
| Q10 | 검증·산출물 | 정합 4종+스모크(§5) + CNPG 페일오버 데모(컷오버 후 며칠 내 — kill primary(A)→자동 승격(B)→RTO 실측→switchback) + 이 문서가 산출물 |
| Q11 | 전환창 수술(2차) | 스텝 **3.5**(봉인 후 최종 lag=0)·**5.5**(재색인 재실행) 신설 · 스텝 1 = **두 동작**(크론 8 주석 + 상주 루프 3 stop) · **정리 체크리스트 §4.1 신설** — 원칙 = **"켜는 건 빨리, 끄는 건 롤백 소멸 후"**(관찰창 60분 동안 롤백 경로·`.8` 감시 온전 유지) |
| Q12 | 파이프라인 열거(2차) | **CronJob 11 = 크론탭 8줄 + 상주 루프 3 전환**(deal-pruner `*/10`+`concurrencyPolicy: Forbid` · user-data-pruner · chat-insights 일1회) · 소유 = **인프라**(KST 환산표 포함 — P1 문서의 "앱 담당 작성" 서술은 정정 대상, 별도 PR) |
| Q13 | ES basic_auth(2차) | 코드 4파일(chat·recipe `db.py`+config, `pipelines/ingest/_db.py`) = **인프라 일괄 작성·env 하위호환**(`ES_USER`/`ES_PASSWORD` 없으면 무인증 — VM 동작 불변) · 앱은 리뷰만 · **데드라인 = P1 이 핀할 앱 이미지 확정 전** · PGSync env 2개·es-exporter URI 는 매니페스트 몫 · 🔴 **HTTP TLS 는 끈 채로 간다 — 2026-07-29 재확인·종결**(경로별 TLS 는 ECK API 에 없다 = 서버 전역 스위치. 근거·재전환 비용 = 플랜 §5.2. **매니페스트 작성 중 재논의 금지** — ES CR 은 `http.tls.selfSignedCertificate.disabled: true`, 클라이언트는 `http://` + basic auth 그대로) |
| Q14 | RAM 강제장치(2차) | **ResourceQuota+LimitRange**(`k8s_cluster_base`) — app·pipeline ns 의 requests 캡 = **앱 6Gi · 파이프라인 3Gi**(2026-07-28 적용 완료 — 실측 2816Mi 의 2배인 "전체 앱 동시 롤아웃"을 수용해야 해서 4Gi 안을 상향, §9-16) · **적용 = P1 완료 직후·데이터 CR 배포 전**(§2-C-0) — 예산 초과를 "조용한 P2 붕괴"에서 "배포 시점 명시적 거부"로 |
| Q15 | worker-a1 체인(2차) | 소유 = **인프라**(Terraform — P1 아님) · 진입 조건 = **`.9`(fb-app-ai)+구 fb-ci-harbor VM 전부 해체**(`.env` 백업 선행) · **IP = 0 대역 실점유 확인(arp/ping 스윕+DHCP 예약 대조) 후 확정** — 후보 a1=`.20`·a2=`.21`(`.13` 이 예약 후 타인 장비에 물린 전례) · 템플릿 소재 확인(9002 는 B 로 이동 — A 재이관 or 9001+agent 택일) · P1 핸드오프에 인터페이스 한 줄 추가(별도 PR) |
| Q16 | 정본 계층(2차) | 플랜 = 전략·근거(why) / **이 문서 = P2 실행 정본**(what·how) / status = 현황 — 플랜은 최소 정정만(별도 PR: Redis 4곳·Spotahome 병기 제거·전환창 한 줄·§7.4 infra 트랙) |

---

## 1. 실측 인벤토리 (2026-07-28 — 수치가 오래되면 재측정)

| 대상 | 실측 |
|---|---|
| PG | **16.14-alpine(musl)** · foodbudget **141MB** + dev 51MB + tfstate 8MB(🔴 물리 복제로 전부 딸려옴 — Q4) · 확장 = plpgsql 뿐 · role = terraform·fbapp·pgsync · `wal_level=logical` ✓ · PGSync 논리 슬롯 1 · 🔴 `datcollate=en_US.utf8`(musl 스텁 — §9-1) · 🔴 pg_hba 의 replication 라인 = **localhost 전용**(§9-2) · `wal_keep_size=0` · 🔴 **컨테이너 이름 = `tfstate-db`**(2026-07-29 실측 — "tfstate 전용 PG" 가 따로 있는 게 아니라 **이 컨테이너 하나가 foodbudget+terraform_state 전부**를 담는 유일 PG 다. superuser=`terraform`. `docker ps` 에서 "postgres 가 없다"고 놀라지 말 것) |
| ES | **8.15.3** · 인덱스 2개뿐 — `recipes_pgsync`(8,419 docs·4.1MB)·`recipes`(1.9MB) · analysis-nori 플러그인 · 클라이언트 핀 `elasticsearch[async]>=8.15,<9`(chat·recipe·ingest) · 🔴 접속 전부 무인증 http — basic_auth 코드 자체가 없음(Q13) |
| Kafka | **3.9.0**(apache 이미지·단일 브로커) · 114MB · 토픽 4: `recipe.crawl.raw`(3p)·`retail.crawl.raw`(3p)·`events.user.activity`(3p)·`retail.deal.raw`(2p), 전부 retention 7d · 그룹 4: retail-refiner·deal-notifier·recipe-refiner·user-event-sink · 클라이언트 = confluent-kafka `>=2.5` · 🔴 mealplan 프로듀서는 best-effort(§9-12) |
| Redis | redis:7-alpine ×2(app + redis-pgsync 분리) · 앱 소비자 = **접속 코드 4곳**(chat·price `db.py`[REDISHOST/PORT] + `pipelines/stream/_redis.py`·`pipelines/ingest/refresh_price_matview.py`[REDIS_URL]), 전부 단일주소·Sentinel 비인지 |
| 파이프라인 | **크론탭 8줄**(kurly 03:30K · oasis 04:10/13:10K · timesale 15:05K · closesale 17:05K · recipe 일·수 05:00K · price-matview 매시 :20 · es-recipes 일·수 06:30K) + **상주 루프 3**(deal-pruner 600s · user-data-pruner · chat-insights 일1회) + 컨슈머 4 → K8s 환산 = **CronJob 11 + Deployment 4**(Q12) |

## 1.1 버전 핀 (2026-07-28 확정 — 준비 ⑤ 산출물)

> 업스트림 릴리스·호환 매트릭스 실조사 + 사용자 승인. **매니페스트는 이 표의 값을 그대로 박는다** — 차트 기본값에 맡기면 "함정" 열이 그대로 사고가 된다. 4종 모두 K8s **1.34** 지원 확인.

| 오퍼레이터 | 차트 | 앱(오퍼레이터) | 대상 컴포넌트 | 🔴 함정 |
|---|---|---|---|---|
| CloudNativePG | `cloudnative-pg` **0.29.0** | **1.30.0** | **PG 16 명시 핀 필수** | 차트 기본 이미지가 **PG 18.4** — `imageName` 을 안 박으면 18 로 생성되고, VM(16) 물리 복제가 애초에 성립하지 않는다 |
| ↳ 백업 플러그인 | `plugin-barman-cloud` **0.7.0** | **v0.13.0** | S3(barman-cloud) | **in-tree `spec.backup.barmanObjectStore` 는 CNPG 1.31.0 에서 제거** → 처음부터 **플러그인 + `ObjectStore` CR** 로 간다(사용자 승인). 웹의 in-tree 예제 붙여넣기 금지 |
| ECK | `eck-operator` **3.4.1** | **3.4.1** | **ES 8.19.19 고정** | ECK 3.4 는 Elastic Stack **9.x 도 지원** — `spec.version` 을 느슨하게 두면 9 로 올라가 클라이언트 핀 `elasticsearch[async]>=8.15,<9` 가 즉사한다 |
| Strimzi | `strimzi-kafka-operator` **1.1.0** | **1.1.0** | **Kafka 4.3.0** (경위 = §1.1.1) | CRD **`v1` 전용**(웹의 `v1beta2` 예제 붙여넣기 금지) · **`KafkaNodePool` 필수** — `spec.kafka.replicas`·`spec.kafka.storage` 가 `Kafka` CR 에서 사라졌다(§9-19) |
| OT-Container-Kit `redis-operator` | **0.25.0** | **0.25.0** | Redis 7.x 태그 핀 | **차트·이미지를 0.25.0 으로 맞춘다**(2026-07-29 정정). 업스트림엔 **v0.26.0**(2026-07-15)이 있고 차트 0.25.0 은 `quay.io/opstree/redis-operator:v0.25.0` 을 박지만, **그 차트가 들고 있는 CRD 도 0.25.0 시절 것**이라 이미지만 올리면 오퍼레이터가 자기보다 낡은 CRD 위에서 돈다. v0.26.0 상향 여부는 **Redis 실물 검증 담당자 판단**(Q3) |

### 1.1.1 Kafka 4.3.0 — 원안의 전제 2개가 다 깨졌다 (Q6 개정)

원안 = "**4.0.x 후보 · 클라이언트 호환 안 되면 3.9 동결**". 실조사 결과:

1. **3.9 동결 경로가 데드엔드다.** Strimzi 0.51.0 이 Kafka 4.0 지원을 제거했고, Kafka 3.9 를 지원하는 마지막 Strimzi 는 **0.45.2 — "last patch release" 로 못 박힌 버전**이다. 3.9 를 고르면 오퍼레이터가 더 이상 움직이지 않는 조합에 앉는다.
2. **폴백 사유였던 "confluent-kafka 프로토콜 비호환"은 사실무근이다.** Kafka 4.x 의 KIP-896 이 드롭한 것은 **Kafka 2.1.0(2018) 이전 API 버전**이고, Confluent 가 명시한 최소 클라이언트는 **1.8.2** 다. 우리 핀은 `confluent-kafka>=2.5` 라 한참 위 — **호환 게이트 자체가 성립하지 않는다**.

→ **Strimzi 1.1.0 + Kafka 4.3.0 확정**(사용자 승인). Q6 의 "4.0.x 후보 / 3.9 동결" 서술은 이 절로 대체된다.

## 2. 준비 작업 (전환창 전 — 시점별)

> **진행 상황 (2026-07-28 밤)** — ①`VM PG 준비` ✅(A-4, 복제 접속 실검증) · ②`노드 sysctl` ✅(**이미 `k8s_node` 롤에 있었다** — 3노드 실측 262144, worker-a1 도 자동 적용. A-4-1 은 실행 항목이 아니라 확인 항목) · ④`ES basic_auth` ✅(A-6) · ⑦`ResourceQuota` ✅(A-8, 적용 완료) · ⑤`버전 매트릭스` ✅(**§1.1** — 2026-07-29 기록, Kafka 전제 붕괴로 Q6 개정) · ⑥`매니페스트 초안` ✅(**2026-07-29, mealplanning-config#2** — 아래) · ③`nori 이미지` ✅(**2026-07-29 05:34 UTC** — Jenkins 릴리스 런 `:f078bbe9…`+`:8.19.19`+`:latest`·Trivy CRITICAL 0·es 매니페스트 PIN-ME 교체 완료) → **준비 A 전체 종결.**
> 🟢 **§2-C-1~C-4 완료 (2026-07-29)** — 오퍼레이터 5종 가동 · **Kafka 4.3.0 3노드+토픽4 Ready** · **ES 8.19.19 green 3노드**(nori) · **PG replica cluster healthy 2/2**(pg-1@b2 ← `.8` 스트리밍 **lag 0** · pg-2@a1 캐스케이드) · Pooler 2/2 · redis-pgsync 1/1 · mp-pgsync dark.
> - **C-4 dark-deploy** ✅: CronJob **11 전부 suspend**(`timeZone: Asia/Seoul`·KST 원안) · Deployment **4 전부 0/0** · ConfigMap 9키 · `mp-pipeline-secrets` SecretSynced · PVC 2 = `Pending`(**WaitForFirstConsumer 정상**). `.8` 이 계속 정본 — 이중 실행 없음
> - **C-3 사전 재색인** ✅(10초): 소스 = K8s PG(replica, `.8` 과 recipe **8,556 동일**) → **servable strict 5,639건 오류 0 · item_id 매칭 5,639/5,639** → ES `recipes` **docs.count 5,639 일치**. ⚠️ `.8` 의 `recipes` 는 5,551 로 **88건 적다** — DR 폴백 인덱스라 마지막 주기 재색인 이후 신규분이 반영 안 된 것(서빙은 `recipes_pgsync` 8,556). K8s 쪽이 더 최신이며 본번 기준은 §4-5.5 창 내 재실행본
> - 이미지 핀: 파이프라인 트랙 **1.1.11**(`:5b4e66c7…` — data-pipeline·crawler-kurly·pgsync 3종, config#4)
> - ⓑ·ⓓ·ⓔ·ⓐ 해소. 밟은 함정 = §9-19~24. **남은 것 = ⓒ REDIS_URL(Q3 분기)** — C-5 리허설은 완주(§7.1)
> 🟢 **게이트 ① 종결 (2026-07-29)** — barman-cloud 백업→S3→복원 왕복을 **리허설과 분리해 단독 검증**(39/40 테이블 완전 일치, 상세·함정 = §2-B 마지막 항목).
> 🟢 **PG 클러스터 최종 상태 (2026-07-29 08:35 UTC)** — replica·타임라인 1·lag≈0 · **41테이블 654,180행 VM 과 완전 일치** · bootstrap `database: foodbudget`/`owner: fbapp`(§9-25 해소분) · ArgoCD `pg` Synced/Healthy. ⚠️ **S3 barman 체인은 비어 있다** — 리허설 잔재 제거로 purge 했고(§9-23), **체인 재시드는 컷오버 promote 이후**에 한다(§9-24 — replica 상태 백업은 완료 상한이 없다). 컷오버까지 정본은 `.8` 이고 사전 안전망(`pg-premigration/`·`etcd/`·`secrets/`·`tfstate/`)은 그대로 있다.
> 🟢 **리허설 1회 완주 (2026-07-29)** — promote 4초 · REINDEX 7초 · 재색인 7초 · 재구축 116초 · 복귀 후 **41테이블 630,889행 VM 과 완전 일치**. **게이트 ③(A↔B 집계 대역) = go**(최대 부하 = 재-basebackup 59.7MB/s = 1GbE 의 50%). 🔴 **§9-1 이 실측으로 확정**(REINDEX 전 btree 103개 중 **13개 손상** — UNIQUE 5·PK 2 포함, REINDEX 후 0). 전체 = **§7.1**.
> - ⬜ **securityContext 부채**(2026-07-29 발견): 파이프라인 워크로드에 `securityContext` 가 없어 `pipeline` ns 의 warn/audit=restricted 가 경고를 낸다(enforce=baseline 이라 지금은 통과). restricted 로 조이면 전부 막히므로 별건 PR 로 4종(`allowPrivilegeEscalation:false`·`capabilities.drop:[ALL]`·`runAsNonRoot`·`seccompProfile:RuntimeDefault`) 추가
> 🟢 **platform-root 배선 완료**(2026-07-29, A-3) — Ansible 적용 + config 레포 머지 + **root 인수 확인**(loki·tempo·alloy Synced). 남은 꼬리 = `k8s_platform_apps` 은퇴(별건 PR).
> 🟢 **⑥ 매니페스트 초안 = mealplanning-config#2** (2026-07-29) — 오퍼레이터 child 5(automated·SSA) + 데이터 CR 5·pipelines(**manual sync**) · 32파일 · kustomize 19 오브젝트 검증. 🔴 **sync 전 사람 손 5건**(PR 본문·파일 주석에 위치 명시): ⓐ이미지 sha 3종 PIN-ME(nori=③ · mp-data-pipeline·mp-pgsync 는 mealplanning/ 트랙 릴리스 런 필요 여부 확인 — 현행 `.8` 은 구 food-budget/·로컬빌드) ⓑfb-secrets 적재 2건(`data-secrets`·`pipeline-secrets` — platform/pg/README.md) ⓒ`REDIS_URL` placeholder(Q3 분기) ⓓpg_hba `.20` 줄 확인 ⓔES 기동 후 elastic 비번 1회 복사(cross-ns ESO 불가).
> 🔴 **worker-a1 IP = `.20` 확정**(2026-07-28 ARP 실측 — `.20`·`.21` 둘 다 응답 없음, 대조군 `.17` 은 MAC 응답. DHCP 클라이언트는 `.167`·`.182` 대역).

**A. 지금 가능 (P1 과 무관):**
1. **Redis 오퍼레이터 실물 검증** (Q3 — 반나절): OT RedisReplication+Sentinel 임시 배포 → master kill → Service 갱신·소요시간·클라이언트 에러 형태 기록 → 분기 결정(A/C) → 철거
2. **nori 이미지**: `infra/images/elasticsearch-nori/Dockerfile`(elastic 공식 **8.19.19** + `elasticsearch-plugin install analysis-nori` — ES 버전은 §1.1 과 **한 글자까지 일치**해야 한다) → Jenkins CATALOG 추가(15번째 · infra 트랙 태깅 = Q5) → 빌드·push
3. **config 레포 구조 + platform-root 배선** (Q1·Q2) — 🟢 **Ansible 쪽 적용 완료(2026-07-29, PR #351)**
   - ✅ **platform AppProject 3종 동시 확장**(Q1·§9-8): sourceRepos 6(차트 5 + config 레포) · destinations 7(+`data`+오퍼레이터 ns 4) · 클러스터 스코프 5종. **화이트리스트 kind 는 `helm template --include-crds` 실렌더링으로 확정** — 핀 5개 산출 = CRD 38·ClusterRole 15·CRB 7·**Validating 2**(cnpg·eck)·**Mutating 1**(cnpg). 그 외 클러스터 스코프(ns·PriorityClass·SC)는 계속 Ansible 소관
   - ✅ **오퍼레이터 ns 4개**(`cnpg-system`·`elastic-system`·`strimzi-system`·`redis-operator-system`, PSS baseline) = `k8s_cluster_base`. 목록은 `group_vars/k8s_nodes.yml` 공유 — **ns 생성 롤과 AppProject destinations 가 어긋나면 조용히 배포 거부**된다
   - ✅ **platform-root + `platform-root` AppProject** 생성. 🔴 root 를 `platform` 프로젝트에 넣지 않는다(argocd ns 를 열면 전역 화이트리스트 탓에 모든 child 가 argocd ns 에 아무거나 만든다 — 앱 트랙 `mealplanning-root` 와 같은 판단) · 🔴 **root 는 `prune: false`**(앱 트랙 root 와 의도적으로 다름 — child yaml 삭제가 데이터 CR 삭제로 번지는 경로 차단, child 제거는 사람이 명시 삭제)
   - ⬜ 남은 것 = **config 레포 `platform/argocd/` 머지**(mealplanning-config#1) → **root 인수 확인** → 같은 날 `k8s_platform_apps` 은퇴
   - 🔴 **LGTM 이사 순서 고정**: git 추가 → root 인수 확인 → **같은 날 `k8s_platform_apps` 태스크 은퇴** (정본 이원화 창 최소화)
4. **VM PG 준비** (Q7, data_tier 롤): `streaming_replica` user · pg_hba replication(우선 `.17/.18/.19` — a1 줄은 §2-C-0 에서 확정 IP 로 추가, 롤 재실행 멱등) · `wal_keep_size=1GB` · 검증 = 노드에서 `psql "host=192.168.0.8 user=streaming_replica replication=1"`
4-1. **노드 sysctl `vm.max_map_count=262144`** (`k8s_node` 롤): ECK 기본은 특권 initContainer 인데 **data ns PSS baseline 이 거부**(istio-init 사고와 동형) — 노드 레벨 선반영 + ES 매니페스트에서 init 비활성(§9-9)
5. **오퍼레이터 4종 child Application 작성**: 버전 핀은 **§1.1 로 확정 완료**(더 고르지 않는다 — 표의 값을 그대로 박는다). 남은 실작업 = **AppProject 확장 kind 목록(웹훅이 어느 오퍼레이터에서 나오는지 포함)을 차트 실렌더링으로 확정**(Q1) — `helm template` 산출물에서 CRD·Validating/MutatingWebhookConfiguration 을 뽑아 §9-8 의 3종 확장에 반영
6. **ES basic_auth 코드 4파일** (Q13): env 하위호환(`ES_USER`/`ES_PASSWORD` 없으면 무인증 폴백) — 인프라 작성·앱 리뷰 · **데드라인 = P1 이 핀할 앱 이미지 확정 전**
7. **매니페스트 초안 작성**: 데이터 CR(pg·pooler·es·kafka[+KafkaTopic 4]·pgsync[**replicas 0**]) · `pipelines/` kustomize(CronJob 11 열거표 = §1 · `spec.timeZone: Asia/Seoul` · suspend·replicas 0) — redis CR 은 A-1 분기 대기
8. **ResourceQuota+LimitRange 매니페스트** (Q14, `k8s_cluster_base`): 작성만 — **적용은 §2-C-0**

**B. S3 게이트 준비물:** ✅ **전부 완료 (2026-07-29)** — 버킷+IAM 키(기존) + 아래 2건.
- ✅ **tfstate → S3 백엔드 이관** (Q4): `backend "pg"` → `backend "s3"`. 잠금 = **S3 네이티브 락파일**(`use_lockfile`, TF 1.15.4 — DynamoDB 불요로 확정). 좌표 = `s3://mp-backup-ap2/tfstate/proxmox.tfstate`(이관 직전 사본 = `tfstate/pre-migration/serial26.json` — 버킷 버전관리 OFF 보완). **E2E 검증 = 새 디렉토리에서 init → 8 리소스 복구 → 실 Proxmox 2대 대조 `terraform plan` = No changes.** 복구 준비물 = repo + backend.conf + credentials.env + ~/.aws(mp-backup). VM PG 의 terraform_state DB 는 이제 미참조(§4.1-⑤ DROP 대기).
- ✅ **사전 백업 세트 + E2E 복구 검증** (2026-07-29, 전건 S3 왕복·복원까지):
  | 대상 | S3 | 검증 |
  |---|---|---|
  | PG 3 DB + globals | `pg-premigration/20260729/` | 🔴 **스냅샷 정합법**: `pg_export_snapshot()` 세션에서 행수 + `pg_dump --snapshot` 동일 스냅샷 → 스크래치 PG16 복원 → **40테이블 350,850행 diff 완전 일치**. (라이브 DB 라 일반 덤프+사후 카운트는 3~33행 어긋난다 — 컨슈머·K8s 앱이 쓰는 중. 재검증 시 반드시 이 방법으로) |
  | etcd | `etcd/` ×3세대(preram·premtest·**postswap** rev 385770) | a1(정상 램)에서 etcdutl CRC 통과 |
  | 비밀 묶음 | `secrets/secrets-20260729.tar.gz.enc` | AES-256(PBKDF2 60만) — secrets.yml·credentials.env·로컬 CA·.env 2종(.9 앱+.8 파이프라인)·fb-secrets ns 2종·AWS 키. **복호 왕복 해시 일치.** 🔴 passphrase = 워크스테이션 `~/backups/SECRETS-PASSPHRASE-20260729.txt` — **오프라인 별도 보관 필수**(S3 만 남으면 못 연다) |
  | JENKINS_HOME | `jenkins/jenkins-home-20260729.tar.gz.enc` (157MB, workspace·캐시 제외) | 복호 후 3,026 엔트리 스캔 + config.xml·credentials.xml·mealplanning-ci 잡 추출 확인. 🔴 secrets/ 마스터키 포함이라 **암호화 필수**(평문 업로드 금지) |
  | ES·Kafka·Redis | 백업 안 함 — **의도** | ES=PG 재파생(Q5)·Kafka=드레인 후 전환(잔여는 7d 보존 큐)·Redis=비영속 캐시 설계(§3) |

  ⚠️ 위 표는 **"사전 안전망"이지 게이트 ① 이 아니다** — 게이트 ① 은 **CNPG barman-cloud 경로**의 왕복이다. ↓

- ✅ **게이트 ① 왕복 증명 완료** (2026-07-29 07:07–07:22 UTC · **리허설과 분리해 단독 선검증**):
  `Backup` CR(`method: plugin`) → S3 → **별도 스크래치 `Cluster` 로 `bootstrap.recovery`** → 행수 대조 → 스크래치 파괴.

  | 단계 | 실측 |
  |---|---|
  | 백업 | **11.6분** (07:07:35 → `backup.info` 최종 07:19:13). 실행 파드 = **pg-2(스탠바이)** — CNPG 가 primary 부하를 피해 자동 선택. PGDATA 275MB → `data.tar.gz` **50.7MiB**(gzip). `beginWal=endWal=…006C`. ⚠️ **CR 의 `stoppedAt`(07:08:54, 79초)은 완료 시각이 아니다** — 이유는 아래 ⚠️ 항목 |
  | 복원 | **54초** (CR apply → `Cluster in healthy state`). full-recovery Job → WAL `…006C` 취득 → `…006D` 부재로 아카이브 끝 판정 → **타임라인 2** 승격 |
  | 정합 | **40테이블 중 39개 행수 완전 일치.** 유일한 차이 = `public.recipe_review_sentiment`(복원 57,350 / 라이브 61,110) — `.8` 컨슈머가 계속 쓰는 테이블이라 **단조 증가분**이며(같은 창에서 라이브도 59,830→61,110 증가 관측) 복원 손실이 아니다. `recipe` 8,556 · `recipe_ingredient` 81,706 · `item_master` 461 · `account.*` 전건 일치 |

  🔴 **"S3 만으로" 의 증명 방식** — 복원 클러스터는 `bootstrap.recovery.source` + `externalClusters[].plugin`(`barmanObjectName`+`serverName`)만 참조한다. **`Backup` CR 이름을 일절 거치지 않는다**(복구 로그에 CR 이름 0회 등장) → CR 을 지우고 하는 복원과 동치. 그래서 CR 을 실제로 삭제하지 않고도 게이트가 닫힌다.

  🔴 **스크래치 클러스터에 `spec.plugins` 를 넣지 않는다** — 넣으면 같은 `serverName: pg` 경로로 WAL 을 아카이브해 **라이브 백업 체인이 오염**된다. 검증 후 S3 에 타임라인 2(`00000002…`) WAL 이 0건임을 확인해 격리를 실증했다. 매니페스트는 일회성이라 git 에 남기지 않는다(레시피는 이 항목).

  🔴 **백업 소요를 지배하는 것은 업로드가 아니라 "필요한 WAL 이 아카이브되기를 기다리는 시간"이다** — 함정 §9-24. 게이트 ① 에서 `data.tar.gz` 업로드는 **07:08:35 에 이미 끝나 있었는데** `backup.info` 최종 기록은 **07:19:13**, 그리고 이 백업이 필요로 한 `…006C.gz` 의 S3 착지도 **07:19:13**(초 단위 일치). 10.6분은 순수 대기였다. 그러므로 백업창을 DB 크기·업링크로 추정하면 안 된다.

**C. P1 후 — 트리거 체인(Q15) 순서대로:**
0. P1 완료 신호(`.9` 정지+`.env` 백업) → **`.9`·구 fb-ci-harbor VM 해체** → **IP 실점유 확인**(후보 `.20`) → **Terraform worker-a1(확정 IP·12GB) 생성**(⚠️ 템플릿 소재 — 9002 는 B 로 이동됨: A 재이관 or 9001+agent 택일) → `k8s.yml` 조인 → **게이트 ③ A↔B iperf** → **ResourceQuota 적용**(Q14) + pg_hba a1 줄 추가(§2-A-4)
1. 데이터 CR 배포(manual sync — **KafkaTopic 4 선생성 포함**(Q6) · **PGSync 는 replicas 0 dark**(Q11))
2. CNPG replica 구축·복제 확인
3. ES 사전 재색인 Job(standby 정합 실증·예열·리허설용 — 본번 서빙분은 §4-5.5 재실행)
4. 파이프라인 dark-deploy
5. **풀 리허설(§7 — S3 왕복 증명·집계 대역 판정 포함)** → 전환창 일정 확정

## 3. 매니페스트 구조 (config 레포)

```
platform/
  argocd/            # child Application 들 — platform-root 가 자동으로 집음 · 오퍼레이터·데이터 CR = project=platform (Q1)
    cnpg-operator.yaml  eck-operator.yaml  strimzi-operator.yaml  redis-operator.yaml
    loki.yaml  tempo.yaml  alloy.yaml            # LGTM 이사분
    pg.yaml  pooler.yaml  es.yaml  kafka.yaml  redis.yaml  pgsync.yaml   # 데이터 CR 앱 (manual sync!)
  pg/  pooler/  es/  kafka/  redis/  pgsync/     # CR·values 본문 — kafka/ 에 KafkaTopic 4 포함(Q6) · pgsync 는 replicas 0(Q11) · pooler 는 P2 배포만·무트래픽(Q8)
pipelines/           # 컨슈머 4 + CronJob 11 + retrain (kustomize · dark-deploy · spec.timeZone: Asia/Seoul) — child 는 project=mealplanning
```
*(ResourceQuota·LimitRange·오퍼레이터 ns 는 config 레포가 아니라 Ansible `k8s_cluster_base` 소관 — Q1·Q14)*

## 4. 전환창 순서 (예산 15분 · 평일 09:00 KST)

> **예산 재보정 (2026-07-29 리허설 §7.1 실측)** — 4·5·5.5 를 합쳐 **1분 미만**(promote 4초 + REINDEX 7초 + 재색인 7초, 여기에 CNPG 가 2/2 로 안정되는 30초). 15분 예산의 병목은 이 스텝들이 **아니다**. 남는 불확실성은 리허설이 건드리지 않은 쪽 — **1·2(VM 파이프라인 정지·Kafka 드레인)** 과 **7·8(앱 ConfigMap 롤아웃·스모크)**, 그리고 **10(PGSync 초기 동기화)**. 다음 예행이 필요하면 거기다.
> 🔴 **백업은 전환창 안에서 찍지 않는다** — 백업 완료는 "필요한 WAL 이 아카이브될 때까지" 걸리고 replica 상태에선 상한이 없다(§9-24). T-1 의 `.8` 스냅샷이 안전망이고, K8s 쪽 base backup 은 **promote 이후·관찰창 밖**에서 찍는다.

```
T-1일   리허설 완료 상태 확인 · 팀 공지(+ platform/pg/ 동결) · 🔫 promote 커밋(replica.enabled=false) 사전 머지 = 장전(Q8) · .8 스냅샷(안전망)
0. 사전: replica lag≈0 확인 · KafkaTopic 4 describe(§2-C 선생성분 — 토픽 4·파티션 3/3/3/2·RF=3) · 검증 스크립트 준비 · ArgoCD 데이터 앱 전부 manual 확인
1. VM 파이프라인 정지 — 두 동작(Q11): 크론탭 마커 블록 주석(8줄) + 상주 루프 컨테이너 3개 stop(deal-pruner·user-data-pruner·chat-insights)
2. Kafka 드레인: 4개 그룹 lag=0 확인 → 컨슈머 정지
3. 🔒 쓰기 봉인: VM PG default_transaction_read_only=on + reload  ← 열화 시계 시작
3.5 봉인 후 replica 최종 lag=0 확인 (봉인 시점까지의 WAL 재생 완료 — "유실 0"의 전제, Q11)
4. CNPG promote = ArgoCD manual sync 1클릭 (T-1 장전분 반영 · 폴백: ArgoCD 불능 시만 kubectl patch 후 git 사후 정합, Q8)
   🔴 **누르기 전에 리비전 확인** — `.status.sync.revision` 이 장전 커밋 SHA 와 다르면 **옛 리비전이 배포되고 promote 는 일어나지 않는다**(§9-26, 리허설에서 실제로 밟음). 안 맞으면 `refresh=hard` 후 재확인, sync 는 revision 명시해서 건다
   🔴 승격 직후 **`cnpg_collector_up=1` 확인**(§9-25 — 롤 생성이 여기서 일어난다)
5. REINDEX DATABASE foodbudget  (§9-1 — 필수. **리허설 실측 7초**. dev·tfstate 는 DROP 예정이라 제외 — 그전 접속 금지)
   🔴 ~~collation version refresh~~ = **불가**(2026-07-29 실측 — `ERROR: invalid collation version change`). 스텝에서 뺐다. 근거·수칙 = §9-1
5.5 ES 재색인 Job 재실행 (소스 = 승격된 K8s PG, REINDEX 완료 후 — §5-② 완전 일치의 전제, Q11)
6. 정합 검증 §5-①(행 수 전수 대조)·②(ES) — 불일치 시 여기서 중단·원복(비용 최소 지점)
7. 앱 ConfigMap 좌표 갱신(PG→pg-rw[Q8] · ES basic_auth env · ES_INDEX=recipes · Kafka bootstrap · Redis chat·price[형태는 Q3 분기]) → 롤아웃
8. 앱 스모크 §5-⑤ → 통과 시 열화 종료 (목표 10분 — 3.5·5.5 포함 실소요는 리허설에서 재보정)
9. 파이프라인 기동: CronJob unsuspend·컨슈머 replicas up + price-matview 크론 1회 수동 실행(price 캐시 사이클 즉시 확인, Q4·2차)
10. PGSync: 슬롯 생성 → replicas 0→1 → 초기 동기화 → recipes_pgsync 반영 확인 → ES_INDEX 플립
11. cnpg_*·PGSync 계열 신규 규칙 반영 — 켜는 것만(⚠️ §9-5 경로). .8 스크레이프 제거는 §4.1 로(Q9)
12. 관찰창 60분 (§6 — 앱→.8 롤백 경로와 .8 감시를 온전히 유지) → 종료 선언
```

### 4.1 정리 체크리스트 (🔴 roll-forward 확정 후에만 — "켜는 건 빨리, 끄는 건 롤백 소멸 후", Q11)

① 앱 egress `.8` ipBlock 제거 → ② data ns egress `.8` 제거(복제 종료) → ③ `.11` 의 `.8` 스크레이프 잡·구 PG 규칙 제거(§9-4 알람 폭풍 방지 — 정지 직전에) → ④ `.8` 정지(P4 까지 보존 — VM PGSync 는 봉인 후 유휴 상태였고 여기서 함께 내려감) → ⑤ K8s PG 에서 `DROP DATABASE foodbudget_dev_team6;` + `DROP DATABASE terraform_state;`(🔴 **실 DB 이름은 `dev` 가 아니라 `foodbudget_dev_team6`** — 2026-07-29 실측. `DROP DATABASE` 는 한 번에 하나만 받으므로 두 문장이다. **tfstate S3 이관 완료 재확인 후** — Q4)

## 5. 검증 (리허설·본번 공용 — 스크립트화)

> 스크립트 = **`infra/scripts/pg-rowcount.sql`**(§5-①) · **`infra/scripts/pg-amcheck.sql`**(§9-1 collation 손상 전수 검사). 사용법은 각 파일 머리주석.

1. **PG 행 수 전수 대조**: foodbudget 전 스키마·전 테이블 count 를 VM·K8s 양쪽에서 뽑아 diff — 쓰기 봉인 후라 **완전 일치가 정상**
   · 테이블 수는 고정값으로 박지 말 것 — 리허설 중에도 `.8` 에 새 테이블이 하나 생겼다(`pantry.pantry_expire_backfill_log`, 40→41). 물리 복제라 DDL 도 따라온다. 대조는 **양쪽에서 뽑은 목록끼리** 한다
2. **ES 재파생 정합**: PG servable 레시피 count = ES `docs.count` — **창 내 재실행본(§4-5.5) 기준 완전 일치**
3. **Kafka 구조**: 토픽 4·파티션 3/3/3/2·RF=3 describe (§2-C 선생성분 — 본번에선 스텝 0 에서 수행)
4. **PGSync CDC 왕복**: 테스트 레코드 INSERT → `recipes_pgsync` 반영 → 삭제
5. **앱 스모크**: 전 서비스 헬스 + 검색 1 + 쓰기 플로우 1(밀플랜 저장)

## 6. 롤백 기준

- **관찰창 = 60분.** Sev-1(정합 깨짐·주요 플로우 불능)이면: 앱 ConfigMap 을 VM 좌표로 원복 + VM read_only 해제. **그간 K8s 쓰기는 유실 수용**(역복제 없음 — 그래서 60분으로 짧게). **전제 = §4.1 을 관찰창 전에 실행하지 않았을 것**(앱 egress·`.8` 감시 온전 — Q11)
- **60분 경과 후 = roll-forward 원칙** — 쌓인 쓰기가 롤백 비용을 역전시킨다. 평시에 정한 이 기준을 장애 중에 재논쟁하지 않는다
- 스텝 6(행 수 대조) 불일치 = 그 자리에서 중단·원복이 최저비용 — 앱 전환 전이라 유실도 0

## 7. 리허설 (1회 필수 — DB 141MB 라 가능한 사치) = 전환창 예행 + 집계 대역 판정

> ✅ **게이트 ①(S3 왕복)은 여기서 분리해 2026-07-29 에 단독 종결** — 실측·함정은 **§2-B 마지막 항목**. 리허설을 기다리게 하면 게이트가 리허설 실패에 묶여서, 먼저 떼어 닫았다.

replica 구축 → **promote(T-1 장전 + manual sync 방식 그대로 예행)** → REINDEX → **재색인 재실행(§4-5.5)** → 검증 §5-①② → **barman-cloud 백업 1회 재실행**(promote 후 타임라인에서도 아카이빙이 도는지 확인. 왕복 자체는 이미 증명됨 — 여유 시 PITR 1회는 사치 항목) → **재-basebackup 재구축**("망하면 지우고 재구축" 경로 검증 + 최종 상태 복귀).
산출: 스텝별 실소요(→ §4 예산 보정) · promote/REINDEX/재색인 실동작 · **A↔B NIC 피크 기록 → 집계 대역 go/no-go**(지속 ~70% 초과 시 배치 조정·본딩 검토 — 게이트 ③ 후속, status §1.0.1 의 "P2 직전 집계 측정" 해소처) · 리허설 중 VM 은 무영향(읽기만).

### 7.1 리허설 실행 결과 (2026-07-29 07:40–08:0x UTC · **1회 완주**)

**스텝별 실소요** — 예산 대비 전 항목이 빨랐다. 전환창 15분 예산의 병목은 이 스텝들이 아니다.

| 스텝 | 실측 | 비고 |
|---|---|---|
| promote (§4-4, ArgoCD manual sync) | ArgoCD op **2초** · `pg_is_in_recovery=f` **4초** · healthy 2/2 **30초** | `kubectl cnpg promote` 안 씀. 장전 커밋 머지 → sync 1회 |
| REINDEX DATABASE (§4-5) | **7초** | 원 추정 ~2분 |
| ES 재색인 Job 재실행 (§4-5.5) | **7초** · servable 5,639 · 오류 0 · item_id 5,639/5,639 | |
| §5-① 행수 대조 | 39/40 일치 | 차이 1건은 리허설 특성 — 아래 |
| §5-② ES 정합 | PG servable **5,639** = ES `recipes` **5,639** | 게이트 SQL 로 독립 재계산 |
| 타임라인 2 백업 | **302초** | = `archive_timeout` (§9-24) |
| **재구축**: Cluster 삭제 → PVC 회수 | 즉시 (data·wal PVC 4개 동반 삭제) | |
| **재구축**: `pg_basebackup` Job | **45초** (275MB, `.8`→b2) | |
| **재구축**: sync → healthy 2/2 | **116초** / S3 purge 포함 전체 **238초** | |
| 재구축 후 §5-① | **41테이블 630,889행 — VM 과 완전 일치** | |

**§5-① 의 차이 1건은 리허설이라서 나온 것** — 리허설엔 쓰기 봉인(§4-3)이 없어 `.8` 이 계속 쓴다. 어긋난 유일한 테이블 `public.recipe_review_sentiment`(+6,200)는 그 창에서 `.8` 자체도 늘어난 것을 관측했다. **본번에서는 봉인 후이므로 완전 일치가 기준**이고, 리허설은 "봉인 없이도 그 한 테이블만 어긋난다" 를 확인한 셈이다.

**게이트 ③ (A↔B 집계 대역) = go.** 물리 링크 `nic0` 1GbE 양단(호스트 A `.12` ↔ B `.22`)에서 5초 간격 샘플링:
- 리허설 전 구간 피크 **7.5 MB/s = 6.3%**
- **최대 부하 = 재-basebackup 구간 59.7 MB/s = 50.0%** (A tx 59.61 ↔ B rx 59.69 로 양방향 대칭 — 측정 정합)
- 판정 기준(지속 ~70%)에 닿지 않는다. 다만 **단일 스트림이 이미 절반을 쓴다** — basebackup 이 Kafka RF=3 복제·ES 샤드 리커버리와 겹치면 합산이 선을 넘을 수 있으므로 **동시 실행을 피한다**

**부수 확인**
- **Pooler 는 클러스터가 통째로 없는 118초 동안 Running 을 유지**했고, 재생성 후 사람 손 없이 복구됐다. (트래픽은 P3 라 무영향)
- 물리 복제가 **DDL 도 따라온다** — 리허설 중 `.8` 에 생긴 `pantry.pantry_expire_backfill_log` 가 재구축본에 그대로 있었다(§5-① 주의사항의 근거)
- 리허설이 새로 깐 지뢰 2개 = **§9-23**(아카이브 오염 → purge) · **§9-24**(백업 소요의 정체)

## 8. 관측·알림 조정 (Q9)

- CNPG `enablePodMonitor` · Strimzi `kafkaExporter`(동일 exporter=지표명 보존) · OT `redisExporter` 사이드카 · ES exporter 차트 1개(basic_auth)
  ✅ **CNPG `cnpg_*` 복구 완료(2026-07-29, §9-25)** — 13→86 패밀리. 단 **롤 생성이 promote 시점에 일어나므로 §4-4 직후 `cnpg_collector_up=1` 재확인**이 필요하다. ⚠️ `enablePodMonitor` 는 deprecated — P3 에 수동 PodMonitor 이관.
- P2 규칙 손질 = **PG·PGSync 계열만** `.11` 위에서 `cnpg_*`/K8s 표현식으로 — 전면 이관은 P4 그대로 · **반영 시점 = 켜기 §4-11 / 끄기 §4.1 분리**(Q11)
- CNPG 공식 Grafana 대시보드 = `grafana_dashboard` 라벨 CM (sidecar 자동 로드)

## 9. 함정 목록 (이 계획이 밟고 지나간 지뢰 — 실측 근거)

1. 🔴 **collation** — 2026-07-29 리허설에서 **추정이 아니라 측정으로 확정**. VM 은 musl 빌드인데 `datcollate=en_US.utf8` 이고, 물리 복제로 glibc(CNPG, 실측 **2.31**)에 옮기면 텍스트 인덱스가 조용히 오작동한다. **promote 직후 `REINDEX DATABASE foodbudget` 필수**(§4-5, 실측 **7초**). dev·tfstate 는 REINDEX 대신 DROP(§4.1-⑤) — DROP 전 접속 금지
   - **실측(`amcheck.bt_index_check`, heapallindexed)**: REINDEX 전 btree **103개 중 13개 손상** → REINDEX 후 **0개**. 손상 목록에 **UNIQUE 5개·PK 2개**가 포함된다 — `account.app_user_email_key` · `public.item_master_canonical_name_key` · `public.retail_product_source_product_id_key` · `recipebook.{shared,user}_recipe_share_token_key` · `public.item_alias_pkey` · `public.item_unit_weight_pkey`. **email UNIQUE 가 깨진 채로 컷오버하면 같은 이메일로 계정이 중복 생성될 수 있다** — "인덱스가 좀 이상해진다" 수준의 문제가 아니다
   - 🔴 **PG 는 이걸 경고해 주지 못한다**: `pg_database.datcollversion` 이 **NULL**(musl 쪽에서 기록된 적이 없다)이라 불일치 감지 로직 자체가 발동하지 않는다. `pg_database_collation_actual_version()` 은 2.31 을 돌려주는데도 조용하다
   - 🔴 **`ALTER DATABASE … REFRESH COLLATION VERSION` 은 실행 불가** — `ERROR: invalid collation version change`. PG 는 `datcollversion` 의 **NULL → 값** 전이를 코드 레벨에서 거부한다. 따라서 이 DB 는 **앞으로도 영구히 NULL** 이고, 미래에 libc 가 바뀌어도 경고가 없다
   - **결정(2026-07-29) = (a) 스텝을 빼고 수칙으로 막는다**: CNPG 이미지가 `postgresql:16.14` 로 핀돼 있어 libc 가 저절로 바뀌지 않고, 이미지 상향은 의도적 행위다. → 🔴 **수칙: CNPG 이미지의 base(glibc) 가 바뀌는 상향을 할 때는 반드시 `REINDEX DATABASE` + `amcheck` 재검사를 세트로 한다.** 카탈로그 직접 기록(`UPDATE pg_database SET datcollversion=…`)은 비지원 경로라 채택하지 않았다(하더라도 전환창 밖에서 별건으로)
   - 재현 스크립트 = **`infra/scripts/pg-amcheck.sql`**
2. 🔴 **pg_hba**: `host all all all` 은 있어도 **replication 은 localhost 전용** — 원격 복제는 별도 라인 필요 (§2-A-4)
3. 🔴 **ArgoCD selfHeal vs promote**: automated 면 전환창의 수동 CR 조작이 몇 초 만에 리버트된다 — 데이터 앱은 P2 기간 manual (§0-Q8). promote 를 T-1 장전+sync 로 하면 git=실상태 정합도 자동 유지된다(Q8)
4. 🔴 **`.8` 정지 = 알람 폭풍**: `.11` 이 보던 VM exporter 가 전부 down — 정리 순서(§4.1 ③→④) 없이 정지하면 진짜 장애가 묻힌다
5. 🔴 **`.11` 규칙 수정 지뢰**: `--limit monitoring` 플레이는 Slack 웹훅을 지운다 — 파일복사+재생성 경로로만
6. **WAL 보존**: 슬롯 대신 `wal_keep_size=1GB` — 고아 슬롯의 디스크 잠식(PGSync 슬롯 사고 계열)보다 재-basebackup(분)이 싼 실패 모드
7. **Jenkins 쓰기 자격증명**(P2 개통 시): config 레포 전체에 닿는다 — platform/ 도 사정거리. 수용 리스크, ArgoCD diff·커밋 이력으로 탐지
8. 🔴 **platform AppProject 는 3종이 다 막혀 있다**(2026-07-28 실측): 클러스터 스코프(RBAC 2종뿐) + sourceRepos(grafana 차트 1개뿐) + destinations(observability·kube-system 뿐) — **셋 다 확장해야** child sync 가 산다 (§2-A-3, Q1)
9. 🔴 **ECK 특권 init vs baseline**: `vm.max_map_count` 를 노드 sysctl 로 선반영 + init 비활성 (§2-A-4-1)
10. **PriorityClass 실이름**(실측): 앱 급 = `app-normal`(100000) · 데이터 = `data-critical`(1000000) · 파이프라인 = `pipeline-low`(1000) — 매니페스트에 이 이름 그대로(없는 이름 = 스케줄 거부). PGSync = `app-normal`

11. **P2 시점 RAM = requests 기준 ~78%**(4노드 30Gi 중 23.5Gi — 기반·LGTM 5 + P1 5.1 + 데이터 13.4): 예산 내지만 빡빡 — P4(5노드)에서 해소, 그전까지 **ResourceQuota(Q14)가 앱·파이프라인 몫을 캡**. 🔴 **KSM off 예비안(워커 11→10GB, status §1.0.2) 발동 시 분모(30Gi)부터 재계산할 것** · worker-a1 VG 150G 는 템플릿 동일 가정 — **생성 시 확인**
12. 🔴 **mealplan 프로듀서는 best-effort**(`except: return` — 요청은 성공하고 이벤트만 증발): 토픽 부재가 **조용한 유실**로 나타나 스모크로 못 잡는다. 그래서 KafkaTopic 은 선생성(Q6)이 원칙
13. **`kubectl cnpg promote` 는 replica cluster 승격 명령이 아니다**(클러스터 내 인스턴스 스위치오버용) — 승격 = Cluster CR `replica.enabled=false` (Q8)
14. **상주 루프 3개(deal-pruner·user-data-pruner·chat-insights)는 크론 정지로 안 죽는다** — 스텝 1 은 반드시 두 동작(Q11)
15. 🔴 **P1 핸드오프의 "여유 ≈15GiB" 안내는 3노드 시절 실측** — P2 예산상 P1 몫 ≈5.1Gi. ResourceQuota 적용 전까지는 문서 안내가 유일한 방어선(P1 핸드오프 정정 = 별도 PR)
16. 🔴 **ResourceQuota 캡은 "전체 앱 동시 롤아웃"을 수용해야 한다**(2026-07-28 실측): LimitRange 기본값 주입 후 app ns requests = 2816Mi 인데, 전환창 스텝 7(ConfigMap 갱신 → 롤아웃)이 정확히 2배를 요구한다. 처음 4Gi 로 잡았다가 창 안에서 막힐 구조라 **6Gi 로 상향**. 플랜 §2.2 의 앱 3.1Gi 추정은 사이드카·LimitRange 반영 전 값이라 이미 초과 — 예산표를 실측으로 갱신할 것
17. **Ansible `command` 모듈로 `docker exec sh -c "... >> file"` 을 쓰지 말 것**(2026-07-28 실측): 인자 분해에 걸려 **rc=0 으로 아무것도 안 하고 ok 로 끝난다** — 실패로도 안 잡히는 유형이다. 볼륨의 호스트 경로에 `lineinfile` 을 쓰면 멱등성이 모듈 책임이 된다(pg_hba 편집이 이 경우였다)
18. **컨테이너 설정 파일을 *교체*하면 reload 로 안 먹는다**(2026-07-28 실측): bind mount 가 옛 inode 를 계속 가리킨다. `.11` prometheus.yml 을 바꾸고 `/-/reload` 했더니 로드된 설정에 구 타깃이 그대로 남아 있었다 → **컨테이너 재생성**이 필요하다
19. 🔴 **소스 PG 에 `postgres` 롤이 없다 → CNPG 가 "HTTP communication issue" 로 멈춘다**(2026-07-29 §2-C-1 실측): VM PG 는 superuser=`terraform` 으로 초기화돼 물리 복제본에 `postgres` 롤이 없는데, CNPG 인스턴스 매니저는 `postgres` 로 로컬 접속해 상태를 뽑는다 → pg-1 상태 추출 실패로 **2번째 인스턴스 생성으로 못 넘어간다**(phase `Instance Status Extraction Error` · instances 1/2 고착). 해소 = **VM primary 에 `CREATE ROLE postgres SUPERUSER LOGIN;` 1줄**(무비밀번호 = scram 원격 로그인 불가라 노출 없음) — WAL 로 replica 에 흘러 즉시 수렴. 재-basebackup·재구축 때 재발 조건이므로 §7 전 확인
20. 🔴 **오퍼레이터 설치 = ArgoCD 컨트롤러 OOM 트리거**(2026-07-29 실측): CRD 37개(CNPG 11·ECK 12·Strimzi 10·redis 4) 유입으로 컨트롤러 클러스터 캐시가 1Gi 한도를 넘어 **OOMKilled 루프**(재시작 8회) — 증상 = "sync 오퍼레이션 조용한 스톨 + 신규 앱 reconcile 불능"이라 원인이 안 보인다. 해소 = limits 2Gi(k8s_argocd values). ⚠️ STS RollingUpdate 는 크래시루프 파드 앞에서 교착 — limit 반영엔 **파드 수동 삭제** 필요
21. 🔴 **data·pipeline ns 에 Harbor pull 인증이 없었다**(2026-07-29 실측): P1 이 app ns 에만 `harbor` dockerconfigjson+SA 배선을 만들어 nori(ES)·mp-* 이미지가 ImagePullBackOff 날 상태였다. 임시 해소 = secret 복제 + default SA patch(수동). 🔴 **IaC 편입 필요**(`k8s_cluster_base` 또는 ESO — 별건)
22. 🔴 **관측 브리지가 `namespace="app"` 만 전달한다**(2026-07-29 실측): in-cluster Prometheus 의
    `remoteWrite[0].writeRelabelConfigs` = `keep namespace=app` 하나뿐이라, **`data`·`pipeline` ns 지표는
    `.11` 에 아예 도달하지 않는다**(실측: `.11` 의 `up{job="kube-state-metrics"}` 없음, `kube_pod_info` 12개뿐).
    → **Q9 의 "cnpg_*·PGSync 규칙을 `.11` 위에서 재작성"은 지금 상태로는 성립하지 않는다** —
    새 규칙이 조용히 아무것도 평가하지 않는다. **§4-11(켜는 것) 전에 keep 규칙 확장이 선행**돼야 하고,
    확장은 전량 개방이 아니라 **필요한 시리즈만 추가 keep** 으로(볼륨 폭증 방지). 상세 = status §1.0.3
20. 🔴 **호스트 C docker(containerd 스토어)의 blob 증발 → 빌드는 되는데 스캔·push 가 죽는다**(2026-07-29 실측): nori 릴리스 런이 Trivy 단계에서 `blobs not found in tar` 로 사망. 원인 = 이미지가 참조하는 **베이스 레이어 blob 1개가 content 스토어에서 GC 로 증발**(스냅샷만 남아 실행·캐시 히트는 됨 — b1 사건과 동형의 "스냅샷 ≠ blob"). 해소 = `sudo ctr -n moby content fetch <베이스 이미지>` 로 누락 blob 재페치(누락분만 받아진다) 후 재실행. 같은 증상이 다른 CATALOG 이미지에서 나도 이 절차다
21. 🔴 **버전 핀 함정 5종 = §1.1 표**(차트 기본값을 믿으면 조용히 "틀린 물건"이 선다). 그중 **매니페스트 모양 자체를 바꾸는 2개**를 여기 다시 적는다 — ① **Strimzi `KafkaNodePool`**: 웹 예제의 `Kafka.spec.kafka.replicas`·`storage` 는 CRD `v1` 에서 사라졌다(붙여넣으면 CR 이 거부되거나 브로커가 서지 않는다) · ② **CNPG 백업**: `spec.backup.barmanObjectStore` 는 1.31.0 에서 제거 — 플러그인 + `ObjectStore` CR 로 처음부터 작성한다(게이트 ① 이 이 경로를 실증했다 — §2-B)
22. 🔴 **복원 검증용 임시 클러스터에 `spec.plugins` 를 넣으면 라이브 백업 체인을 오염시킨다**(게이트 ① 에서 회피): 같은 `barmanObjectName` 을 백업용으로 달면 복원본이 **같은 `serverName` 경로에 자기 타임라인 WAL 을 아카이브**한다. 복원본은 승격하면서 타임라인이 갈리므로(실측 = 2) 원본 아카이브에 남의 타임라인이 섞이고, 이후 PITR 이 어느 타임라인을 따라갈지가 모호해진다. **복원 검증 클러스터는 `externalClusters[].plugin` 만**(읽기 전용 소스) — 검증 후 S3 에 `00000002…` WAL 이 0건인지 확인해서 격리를 증명한다

23. 🔴 **리허설 promote 는 실 백업 아카이브를 오염시킨다 — 재구축 시 `pg/pg/` purge 가 세트다**(2026-07-29 리허설에서 실제로 찍힘): promote 하면 클러스터가 **타임라인 2** 로 갈라지고 `00000002.history.gz` + 타임라인 2 WAL 이 `serverName: pg` 경로에 올라간다(실측 = history 1 + WAL 5). 그 상태로 재-basebackup 해서 타임라인 1 로 돌아가면, **본번 promote 가 이름은 같고 내용은 다른 `00000002.history` 를 만든다.** 리허설 잔재 WAL(`…006E`–`0073`)이 본번 타임라인 2 구간과 섞여 PITR 이 잘못된 분기점을 읽는다. → **재구축 순서 = ① Cluster 삭제 → ② `aws s3 rm s3://mp-backup-ap2/pg/pg/ --recursive` → ③ 재생성(sync) → ④ 새 base backup 으로 체인 재시드.** 🔴 **`pg/` 가 아니라 `pg/pg/`** — 같은 `pg/` 아래에 사전 덤프(`pg/2026-07-28/`)가 있어서 한 글자 차이로 안전망이 날아간다
24. 🔴 **백업 소요를 지배하는 것은 업로드가 아니라 "필요한 WAL 이 아카이브될 때까지의 대기"다**(2026-07-29 실측 3회). barman 은 base 데이터를 다 올린 뒤 그 백업이 요구하는 WAL 세그먼트가 아카이브되기를 기다렸다가 `backup.info` 를 최종 기록한다.
    - 게이트 ①(standby): `data.tar.gz` 업로드 완료 **07:08:35** / 필요한 `…006C.gz` 착지 **07:19:13** / `backup.info` 최종 **07:19:13** → **10.6분이 순수 대기**
    - 타임라인 2(promote 후, primary): **302초 ≈ `archive_timeout` 300초** — primary 는 스스로 WAL 전환을 강제할 수 있어 상한이 생긴다
    - 🔴 **replica 인 동안 찍는 백업은 상한이 없다** — 세그먼트를 채우는 주체가 `.8` 이라 한가한 시간대면 무한정 길어진다. 그래서 **CR 의 `stoppedAt` 을 완료 시각으로 믿으면 안 되고**(게이트 ① 에서 79초로 오독했다), 완료 판정은 **S3 `backup.info` 최종 착지**로 한다
    - 운영 함의: 컷오버 백업창을 DB 크기나 업링크로 추정하지 말 것. **백업이 필요하면 promote 후에 찍는다**
25. 🔴 **CNPG 메트릭 수집이 통째로 죽어 있다 — Q9(관측)의 전제가 깨진다**(2026-07-29 리허설 중 발견, 실측):
    `monitoring.enablePodMonitor: true` 로 PodMonitor 는 서지만 **`cnpg_collector_up = 0` · `cnpg_collector_last_collection_error = 1`**, 노출되는 `cnpg_*` 패밀리 **13종뿐**(pg_stat_archiver·replication·database size 등 실제로 보고 싶은 지표가 전부 없다).
    - 근인 = **`bootstrap.pg_basebackup.database: app` / `owner: app`** — 우리가 명시하지 않아 들어간 CNPG 기본값이다. 물리 복제본에는 `app` DB 도 `app` 롤도 없는데 메트릭 익스포터가 `database=app` 으로 붙으러 간다: `FATAL: role "cnpg_metrics_exporter" does not exist … database=app`
    - 게다가 **replica 인 동안은 읽기 전용이라 CNPG 가 그 롤을 만들 수도 없다.** 그래서 promote 만으로는 안 낫는다 — 존재하지 않는 DB 를 계속 겨눈다
    - 🔴 **`bootstrap` 은 생성 시점 1회만 유효하다** → 고치려면 **Cluster 삭제 후 재생성**이 필요하다(실측 116초, §7.1 에서 안전 확인)
    - ✅ **해소 (2026-07-29, mealplanning-config#9)**: `bootstrap.pg_basebackup` 에 **`database: foodbudget` · `owner: fbapp`** 명시 → 삭제·재생성. **실검증 결과 `cnpg_collector_up` 0→1 · 수집오류 1→0 · `cnpg_*` 패밀리 13→86종**(`pg_replication_lag`·`pg_database_size_bytes`·`pg_stat_archiver`·`backends_*` 전부 복귀)
    - 🔴 **검증은 두 단계로 해야 한다** — 재생성만으로는 익스포터 타깃이 `database=app`→`foodbudget` 으로 바뀌는 것까지만 확인된다. **`cnpg_metrics_exporter` 롤 생성은 쓰기가 되는 primary 에서만** 일어나므로, replica 인 동안은 계속 `cnpg_collector_up=0` 이다. 그래서 일회성 promote(`kubectl patch`)로 롤 생성까지 확인한 뒤 다시 삭제·재생성해 replica 로 복귀시켰다. **컷오버 당일에 처음 확인하지 않기 위한 절차이고, 같은 이유로 §4-11 에서 재확인 항목으로 남긴다**
    - ✅ **자격증명 무영향 확인**: `owner` 를 실재 롤로 바꿔도 CNPG 가 비밀번호를 갈지 않는다 — `pg_authid` 해시를 재생성 전후로 대조해 **fbapp 포함 전 롤 무변화**. 애초에 `pg-app` 시크릿 자체가 생성되지 않는다(앱 자격증명 정본은 `.env`)
    - ⚠️ 부수 발견: **`spec.monitoring.enablePodMonitor` 는 이 CNPG 버전에서 deprecated** — 패치 때 경고가 뜬다("Set this field to false and create a PodMonitor resource"). 지금은 동작하지만 **P3 에 수동 PodMonitor 로 이관** 필요
    - 확인 명령: `kubectl -n data run … curl http://<pg-1 IP>:9187/metrics | grep cnpg_collector_up`
26. 🔴 **ArgoCD 가 새 커밋을 아직 못 본 상태에서 sync 를 누르면, 조용히 "옛 리비전"이 배포된다**(2026-07-29 실제로 밟음). `pg` 앱이 `.status.sync.revision` 을 직전 커밋으로 들고 있는 동안 sync 를 걸었더니 **머지한 변경이 반영되지 않은 채 오퍼레이션만 Succeeded** 로 끝났다. `argocd.argoproj.io/refresh=normal` 로 120초를 기다려도 안 올라와서 **`refresh=hard`** 로 강제해야 했다.
    - 🔴 **§4-4(promote)가 정확히 이 모양이다 — "장전 커밋 머지 → manual sync 1클릭".** 리비전 확인 없이 누르면 **promote 가 일어나지 않았는데 일어난 줄 안다.** 열화 시계는 이미 돌고 있다
    - **수칙**: sync 전에 `kubectl -n argocd get application pg -o jsonpath='{.status.sync.revision}'` 가 **장전 커밋 SHA 와 일치**하는지 먼저 확인한다. 안 맞으면 `annotate … refresh=hard` 후 재확인. sync 는 `revision` 을 **명시**해서 건다(`{"operation":{"sync":{"revision":"<sha>"}}}`)
    - sync 후 확인도 리비전으로: `.status.operationState.operation.sync.revision` 이 그 SHA 인지
