# AWS 이관 선행 체크리스트 (온프렘)

> **목적** — AWS 이관을 시작하기 전에 **온프렘에서 끝내야 하는 것**만 모은 추적 문서.
> **사용법** — 항목을 처리하면 `[ ]` → `[x]`. 근거·PR 번호를 옆에 남긴다.
> **성격** — 살아 있는 문서다. 계획이 진행되면서 계속 갱신한다.

- 최초 작성: 2026-08-07
- 근거: 13-에이전트 서비스 감사(205 findings) + DR 등급 실측 워크플로
- 관련 정본: `docs/mp_aws_migration_plan.md`(이관 계획) · `docs/mp_k8s_infra_status.md`(인프라 SSOT)

---

## 0. 확정된 결정 (이 체크리스트의 전제)

🔴 **사용자가 확정한 것만 여기 적는다. 추천은 아래 §0.2 로 분리.**

### 0.1 확정

| # | 결정 | 확정일 | 근거 |
|---|---|---|---|
| C-1 | **완전 이관** — AWS(EKS)를 프로덕션으로. 온프렘 존치는 이관 *후* 옵션이 아니라 병행 설계 | 2026-08-06 | 사용자 |
| C-2 | **CI = EC2 1대에 GitLab** (Jenkins 은퇴) | 2026-08-07 | 사용자 |
| C-3 | **온프렘 = 상시 대기 사이트(Standby Site)** · DR 등급 = **Warm Standby(C)** | 2026-08-07 | 실측(아래) |
| C-4 | **DNS = Cloudflare 유지** (Route 53 미채택) | 2026-08-07 | 사용자 |
| C-5 | **터널(cloudflared) = 온프렘 DR 전용 존치** (Retire 아님) | 2026-08-07 | C-3·C-4 의 귀결 |
| C-6 | **사이트 간 연결 = Tailscale** (복제 전용 최소 구성) | 2026-08-06 | 사용자 |

#### C-3 의 실측 근거
- 자원: **C − 현행 = −880m CPU / −736Mi** → 증설이 아니라 **감축**
- config: 현행 base 가 이미 `replicas: 1` → **C 는 수정 0건**, 반대로 B+ 는 HPA 2·PDB 3·frontend 1 = 6건 동시 커밋 필요
- read-only PG 내성: **기동 실패 0종** (probe 13종 전부 `/health` 정적 응답, DB 미조회)
- 알림: C 의 몫 = **주당 약 8건 · critical 0** (현 클러스터가 이미 C 형상 + 트래픽 0이라 7일 이력이 곧 실적)
- ⚠️ 근거 문구 주의 — "상시 운영이라야 RTO 가 안 는다"는 앱 레이어에서 **약 15초** 이득일 뿐이다.
  C 의 가치는 RTO 단축이 아니라 **"설정·이미지·시크릿·정책이 지금 이 순간 동작함을 상시 증명"** 이다.

#### C-4 의 근거 (비용 아님)
Route 53 비용은 월 $1~4 로 결정 요인이 못 된다. 진짜 근거는:
> 🔴 **페일오버에 필요한 것은 방어 대상과 장애 도메인을 공유하면 안 된다.**
> 이 DR 이 방어하는 시나리오 3개(리전 장애·**계정 잠김**·**과금 사고**) 중 2개에서 Route 53 이 같이 죽는다.

이 원칙이 다른 결정들도 설명한다 — 이미지=Harbor 미러, 매니페스트=Git 미러, 워크로드=standby.

#### D-ing 실측 (2026-08-07) — Cloudflare 프록시 호환성

🔴 **전제 정정**: `app.mealbong.cloud` 는 cloudflared 터널이라 **이미 오늘도 주황 구름 뒤에 있다**(`server: cloudflare`·`cf-ray` 실측).
즉 이건 신규 리스크 도입이 아니라 **현행 유지 여부** 판단이다.

| CF 무료 제약 | 우리 실측 | 판정 |
|---|---|---|
| 100초 타임아웃 | 10일 **828,594건 중 >100s 0건 · >60s 0건**, 최대 38.7s(그것도 k6 부하시험) | 안 깨짐 |
| 업로드 바디 | CF 실측 **99.6MB 통과 / 104.86MB 에서 413**. 우리 체인 최저값은 앱 **8MiB**(`ocr/app/config.py:11`) | 안 깨짐 (CF 가 우리 상한의 12배) |
| WebSocket/SSE/롱폴링 | 코드베이스 grep **0건** | 해당 없음 |
| 정적 캐시 | 해시 자산 `MISS→HIT`, `/api/*` 전부 `DYNAMIC` | 정상 분리 |

OCR·영상은 `status_code=202` + 폴링 구조라 응답이 2~3ms 다(`ocr/app/main.py:132` · `video/app/main.py:176`).
🔴 **이 async 잡 패턴은 계약이다** — sync 로 되돌리면 즉시 524 다(잡 상한 OCR 184s · video 120s).

**CDN 이득 — 요청 수가 아니라 대역폭이다**
- 오리진 **요청 수** 감소 = 초회 방문 10건 중 3건, **정상 사용 구간 0%**(`/api/*` 전부 비캐시 + 재방문 자산은 브라우저 `immutable` 이 먹음)
- 오리진 **대역폭** 감소 = 콜드 방문자당 **443,319B (초회 451KB 의 98.3%)**
- 덤: CF 엣지가 `/api/*` JSON 을 **brotli 압축**(오리진엔 `GZipMiddleware` 0건) → 회색으로 가면 이 이득이 사라진다
- 🔴 **비용 모델 규칙: CDN 이득은 대역폭(GB)·NAT GW 항목에만 반영. ALB 요청수(LCU)엔 반영 금지.**

**채택 조건 (선행 필수)**
1. **ALB `idle_timeout` = 120s** — 기본 60s 면 CF 100초보다 **ALB 가 먼저 문다**. OAuth 산술 최악이 50.4s(`account/app/oauth.py:22`)라 여유가 얇다. 계층을 **ALB 120 > CF 100 > GW 60** 으로 정렬
2. OCR 클라 리사이즈 (1-10) 전까지는 업로드 524 경로가 살아 있다
3. CF 에서 **Cache Everything 금지**를 규칙으로 못 박을 것

**⚖️ 대안으로 남겨둘 것** — ALB 를 아예 빼고 **cloudflared 를 EKS 에 유지**(이미 `mp-ingress` 에서 라이브).
공개 인그레스 0 · SG 관리 0 · ALB 비용 0. 반대 논거는 터널 처리량·ALB 헬스체크 상실 + **prod/DR 구분이 사라진다**는 점.
후자가 C-3·C-5 와 충돌하므로 현재는 비채택이지만, 비용이 블로커가 되면 1순위 재검토 대상.

### 0.2 권고(미확정) — 임의로 확정 처리하지 말 것

| # | 항목 | 권고 | 상태 |
|---|---|---|---|
| D2 | Cilium IPAM | **cluster-pool**(오버레이 유지) | 사용자 확인 대기 |
| D-ing | AWS 유입 | Cloudflare 프록시(주황) → ALB → Istio **(조건부)** | 🟢 호환성 실측 완료 — 아래 |
| D4 | Kafka | Strimzi 유지 (SQS 재설계는 비용 대안) | 미결 |
| D4 | Redis·ES·PG | 전부 오퍼레이터 유지 (RDS 는 DR 물리복제 불가라 배제) | 미결 |
| D6 | 배포 전략 | 클러스터=Blue-Green / 앱=Canary 유지(ADR-0001) | 미결 |
| D7 | 비밀 백엔드 | SSM Parameter Store + 🔴 온프렘 이중 공급 | 미결 |
| D10 | 비용 | 실측 $678/mo → GitLab EC2 포함 시 **~$715~750** (목표 $219 의 3.3~3.4배) | 🔴 목표 재설정 필요 |

---

## Phase 0 — 이게 끝나야 AWS 착수

### 0-A. 차단 — 안 고치면 EKS 에서 앱이 안 뜬다

- [ ] **0-1 config 레포 eks 분기 골격** — services 13종 외 전 트랙(pipelines·platform·monitoring·gateway·argocd 44개)이 분기 수단 자체가 없음 〔감사 #25 #13 #2〕
- [ ] **0-2 ESO 스토어 추상화** — `fb-kubernetes` 23파일 하드코딩, eks 패치 0건 → 시크릿 30종 전건 NotReady 〔#23 #83〕
- [ ] **0-3 Ansible 단독 → config 이관** — PriorityClass 3종(**워크로드 46개 참조**)·ResourceQuota 2·LimitRange 2·ns PSA·kube-prometheus-stack 전체 〔#20 #16〕
- [ ] **0-4 ArgoCD 뿌리 IaC화** — AppProject 3·root Application 2·repo SSH 자격증명이 레포에 없음 〔#87 #77〕
- [ ] **0-5 nodeSelector 온프렘 라벨 제거** — 워크로드 12+ 가 `host-a`/`k8s-worker-*` 하드코딩 → EKS 에서 영구 Pending 〔#6 #21〕
- [ ] **0-6 hard TSC 6종 완화** — 노드 하한을 "워커 4대·AZ당 2대"로 못박아 비용 목표와 정면 충돌 〔#8 #19〕
- [ ] **0-7 `topology.kubernetes.io/zone` 강제 기록 제거** — EBS CSI 볼륨 토폴로지가 깨짐 〔#7〕
- [ ] **0-8 StorageClass 파라미터화** — 하드코딩 5~15건(집계 불일치, 0-21 참조)
- [ ] **0-9 Harbor LAN IP(`192.168.0.10`) → 레지스트리 파라미터화** 〔#9〕
- [ ] **0-10 `validate.py` eks 렌더 대응** + LAN CIDR 제거 〔#3〕

> 🟢 **0-1~0-4 는 사실상 "config 레포 대공사" 한 덩어리**다. 따로 세면 4건이지만 작업 단위로는 하나로 잡는다.

### 0-B. 보안 PoLP — 온프렘에서 먼저여야 하는 이유가 명확한 것

- [ ] **0-11 ⭐ `fb-secrets` 원본 6종 인벤토리 git화** — ESO 전체의 뿌리가 전 IaC 밖 수동 생성이고 **키 이름 목록조차 git 에 없다**. 그 머신이 죽으면 뭐가 있었는지도 모른다 〔#92〕
- [ ] **0-12 ⭐ `jwt_secret` 조용한 폴백 제거** — 커밋된 placeholder(`dev-insecure-change-me`) + pydantic-settings 가 env 누락 시 조용히 폴백 → **토큰 위조 가능 상태로 무증상 기동**. 누락 시 기동 실패로 바꾼다 〔#32〕
- [ ] **0-13 PG 스키마별 롤** (현재 단일 슈퍼유저) — 🔴 **IRSA·IAM 설계의 전제**. 롤이 하나면 나눌 대상이 없다 〔이슈 #546〕
- [ ] **0-14 RBAC verb 단위 커스텀 롤** — 내장 `edit` = Secret 전권 + SA impersonate + `pods/exec`. 🔴 **EKS Access Entries 매핑의 전제** 〔이슈 #550〕
- [ ] **0-15 ES PoLP** — 소비자 5곳 중 4곳이 `elastic` 슈퍼유저 + HTTP TLS 꺼짐 〔이슈 #521〕
- [ ] **0-16 정적 AWS 키 `envFrom` 제거** — pipeline ns 워크로드 22개 전부에 전파. 🔴 **env 가 IRSA 를 가린다** 〔#78〕
- [ ] **0-17 egress 무제한 11 워크로드 닫기** (data·observability) — AWS 에선 **IMDS 를 통한 노드 IAM 롤 탈취 경로** 〔#57〕
- [ ] **0-18 netpol 재작성** — LAN `192.168.0.0/24` 전 포트 ipBlock 7건 + 내부 게이트웨이 전면 개방(`ingress: [{}]`)·와일드카드 SNI. 🔴 **VPC CIDR 로 기계적 치환 금지** 〔이슈 #549 · 감사 #53 #58〕

### 0-C. 리드타임이 있어 착수만 먼저

- [ ] **0-19 🔴 AWS 서비스 쿼터 증액 신청** (vCPU·EIP·NLB) — 승인에 며칠. **일정 블로커**
- [ ] **0-20 🔴 CNPG replica cluster 전환 설계** — `bootstrap` 은 생성 시점 1회만 유효 → **Cluster 삭제·재생성**(PGDATA 20Gi + WAL 10Gi PVC 파기). 현 `externalClusters` 는 죽은 좌표 `192.168.0.8`. `sslmode: prefer` 는 LAN 전제라 크로스사이트면 TLS 필요. **별건 규모**
- [ ] **0-21 숫자 정본화** — 아래 §갱신 필요 수치

---

## Phase 1 — 리허설·컷오버 준비 (조용히 깨지는 것)

- [ ] **1-1 PGSync CDC 복구** — 논리 복제 슬롯 `lost`. 컷오버·DR **양쪽** 경로 〔#17〕
- [ ] **1-2 CNPG egress 에 STS 추가** — 없으면 IRSA 전환 시 WAL 아카이브·백업이 **경고 없이** 전면 실패 〔#14〕
- [ ] **1-3 카나리 AnalysisTemplate 파라미터화** — `kube-prometheus-stack-prometheus.observability:9090` 하드코딩이고 그 스택이 0-3
- [ ] **1-4 docker.io → ECR pull-through cache** 준비 — rate limit
- [ ] **1-5 백업 3종 대체 경로** — etcd·비밀/PKI·신선도 계측이 전부 kubeadm master systemd timer. EKS 엔 그 호스트가 없다 〔#15〕
- [ ] **1-6 이미지 멀티아치** — 전 이미지 amd64 단일. Graviton 노드면 전면 CrashLoop. CI 툴체인의 sonar-scanner-cli 도 amd64 단일 〔#31 #35〕
- [ ] **1-7 JWT_SECRET 이관 체크리스트** — 단일 값을 10개 서비스가 공유. 누락 시 전 유저 세션 무효 〔#80〕
- [ ] **1-8 SSM 4KB 한도 대응** — app-secrets 11키 + GCP SA JSON 이 standard 파라미터 한도 초과 위험 〔#123〕
- [ ] **1-9 🔴 리허설 클러스터 확보** — 12개 영역이 전부 여기서 유보됐다(§미확인 참조)

### 1-B. 유입 경로 관련 (D-ing 실측에서 파생, 2026-08-07 추가)

- [ ] **1-10 🔴 OCR 업로드 클라이언트 리사이즈** — 프론트가 원본 `File` 을 그대로 올린다(`frontend/src/lib/api.ts:535`). 서버는 어차피 1600px 로 줄인다(`ocr/app/vision.py:59-66`).
      게이트웨이 실측: 15,739,985B 업로드가 **60,610ms** 후 413. **CF 100초를 실제로 먹는 유일한 경로**다.
      canvas 리사이즈 1600px 도입 시 실바디가 1MB 미만이 되어 100초·15MiB·8MiB 상한이 전부 무의미해진다.
      최소 조치 = `OcrFlow.tsx:78` 의 10MB 가드를 앱 상한 8MiB 로 정렬(현재 8~10MB 는 브라우저 통과 후 서버 413 왕복)
- [ ] **1-11 HTTPRoute 요청 타임아웃 설정** — 공개 GW Envoy `config_dump` 상 라우트 15개 전부 `timeout=0s`, HTTPRoute 12개 전부 `timeouts` 미설정. **포화 시 아무도 안 끊는다**(k6 에서 price 가 38.7s 까지 감).
      `spec.rules[].timeouts.request: 60s` → CF 524 보다 우리 504 가 진단 가능하다. ⚠️ config 레포 수동 sync 대상
- [ ] **1-12 `index.html` `Cache-Control` 명시** — `frontend/nginx.conf:95` 에 헤더가 아예 없다. 지금은 `DYNAMIC` 이라 무해하나 누가 CF 에서 Cache Everything 을 켜면 **배포 시 구 index.html 이 없어진 해시 청크를 가리켜 앱 전면 로드 실패**.
      `add_header Cache-Control "no-cache"` (no-store 아님 — ETag 재검증 유지). 겸사 `/icons/` 도 명시(현 `max-age=14400` 은 우리 값이 아니라 CF 무료플랜 기본값이라 통제 밖)
- [ ] **1-13 XFF 홉 수 재조정** — CF 1홉 + ALB 1홉이 된다. Istio `meshConfig.gatewayTopology.numTrustedProxies` 를 안 맞추면 접근로그·rate limit 의 클라이언트 IP 가 오염된다

---

## Phase 2 — 컷오버 시점 (standby 전환)

- [ ] **2-1 🔴 `mp-cloudflared` replicas 0 — git 커밋으로** (유일하게 `selfHeal=True` 라 `kubectl scale` 은 되돌려짐).
      안 내리면 DR 이 prod 와 같은 터널로 `app.mealbong.cloud` 를 동시 서빙하고, C 는 앱이 전부 Ready 라 **read-only PG 로 실트래픽을 받는다**
- [ ] **2-2 `OPERATIONS_COLLECTOR_ENABLED=false`** — 외부 PG(team2) 이중 writer 차단(같은 행 `on conflict do update`, 리더 일렉션 없음) + app ns CPU 22.6% 회수. 코드 기본값이 이미 False 라 **env 한 줄**
- [ ] **2-3 pipeline CronJob 13종 suspend** — poller-kurly·oasis×2·deal×2·recipe·recipe-review·price-anomaly·price-matview·pantry-expire·user-data-pruner·score-review-sentiment·summarize-reviews.
      read-only 쓰기 실패 7종 + **외부 이중 크롤 6종(ToS)** + **Bedrock 이중 과금**
- [ ] **2-4 `mp-price-anomaly-notifier` replicas 0** — KEDA 밖 정적 `replicas: 1` 이라 자동으로 0 이 안 된다
- [ ] **2-5 알림 site 분리 + DR 상시 오탐 6종 억제** — 라우팅 축이 severity 뿐(`AlertmanagerConfig` CR 0개, externalLabels 에 site 없음).
      오탐 6종 = `MpPGSyncDown`/`CrashLooping` · `MpPollerStale` · `MpConsumerLagUnobserved` · `MpBackupWalArchivingStalled` · `MpBackupPgOnsiteDumpStale` · `MpPGReplicationLagHigh`
- [ ] **2-6 KEDA 오프셋 부트스트랩 런북** — DR Kafka 에 MirrorMaker 부재로 컨슈머 그룹 오프셋 0건. 4그룹을 잠시 min 1 로 올려 커밋시켜야 한다
- [ ] **2-7 페일오버 = "DR 켜기 + prod 끄기" 쌍 명문화** — 한쪽만 조작하면 이중 크롤·이중 과금. 프로덕션에도 같은 overlay 축이 필요
- [ ] **2-8 `mp-pg-onsite-dump` MinIO 프리픽스 DR 분기** — 같은 경로면 상호 덮어쓰기 + 백업 신선도 판정 오염
- [ ] **2-9 DNS TTL 사전 인하** — 어느 DNS 를 쓰든 실제 RTO 를 지배한다

---

## 상시 — 언제 해도 되지만 방치하면 커지는 것

- [ ] **⚡ 알림 2건 정리** — `cost` ns `TargetDown`(121h 연속) · `KubeJobFailed` ns=pipeline(80h 연속). **주당 약 62 메시지**
  - `TargetDown` 원인 = ServiceMonitor `kubecost-aggregator-clickhouse` 가 포트 `db-metrics`(9363)를 긁는데 ClickHouse 미사용(local-store 모드)이라 아무도 안 듣는다 → 그 ServiceMonitor 삭제
  - `KubeJobFailed` 원인 = `mp-poller-kurly-29763030` 1건이 2026-08-03 18:30 에 실패(`backoffLimit: 0`)한 뒤 **오브젝트가 그대로 남아 있다**. 이후 실행은 전부 성공 → 그 Job 삭제 + `ttlSecondsAfterFinished` 검토
- [ ] **CIS 감사 정책 EKS 대체 설계** — 커스텀 audit policy 를 못 넣고 CloudWatch 과금이 붙는다. 이전 세션에 라이브로 만든 자산이 **이관되지 않는다** 〔#118〕
- [ ] **인증서 만료 감시 신설** — cert-manager·ArgoCD·ESO·istiod·Cilium·MinIO 가 스크레이프 대상에 **전혀 없다**. 현 4장 만료 **2026-10-27~11-04**, cert-manager 파드 10일간 7회 재시작 〔#63〕
- [ ] **Trivy 범위 확대** — CRITICAL + `--ignore-unfixed` 만 차단. secret·misconfig 스캐너와 SBOM 없음 〔#104〕
- [ ] **`mp-ingress` ns 를 Ansible PR 로 정식화** — 2026-08-06 수동 kubectl 생성 상태. 'ns 는 Ansible 이 유일 생산자' 규칙 위반 〔#89〕

---

## 🔴 아직 계획에 통째로 없는 것 — AWS 쪽

이 체크리스트는 **온프렘 선행**만 담는다. 아래는 AWS 이관 계획 문서에서 다뤄야 하는데 **현재 없다**.

- AWS 계정 구조 · IAM Identity Center SSO · MFA · break-glass
- 비용 가드레일 — AWS Budgets · 태깅(`default_tags` 0건)
- Terraform AWS 코드 구조 · state 분리 (AWS provider **0건**, backend 버킷 **버전관리 OFF**)
- VPC 설계 — CIDR 비충돌 · NAT 개수 · S3/ECR/**STS** 엔드포인트
- GuardDuty · Security Hub · Inspector · CloudTrail · KMS
- 컷오버 운영 — 점검창 · 유저 공지 · **abort 기준·결정권자** (계획에 `점검·공지` grep 0건)
- 페일백 절차 (편도가 아님이 확인됨 — CNPG demote/promote + `pg_rewind`. 단 **리허설 필요**)
- 개인정보 리전 — Bedrock `apac.amazon.nova-micro-v1:0` cross-region
- 클라우드발 크롤 ToS — 근거가 "비상업·**비공개** 전제"인데 AWS 상시 가동이면 전제가 약해진다 + 🔴 크롤 3사 egress 가 **NAT 고정 IP(데이터센터 ASN)** 로 바뀐다. 프록시·IP 로테이션 코드 전무 〔#28〕
- GitLab 러너 보안 — privileged DinD + EC2 인스턴스 프로파일 = IAM 탈취. 권고 = **EKS 별도 노드그룹 + IRSA + rootless 빌더**
- 🔴 **EKS 1.34 표준지원 2026-12-02 종료** ↔ Cilium 1.19.6 상한 1.34 ↔ CLAUDE.md "1.35 금지" 락 — **3자 충돌 해소 필요** 〔#27〕

---

## 갱신 필요 수치 (0-21)

| 항목 | 엇갈리는 값 | 조치 |
|---|---|---|
| StorageClass 하드코딩 | 5 / 13 / 15 | 세는 단위 통일 후 확정 |
| **ES 재색인** | **1.0초** vs 계획서 **7초** (7배) | 컷오버 창 산정 입력 |
| CronJob 총수 | 17 vs **22** | DR suspend 목록은 22 기준 |
| 수동 sync 앱 | 15 vs **16** | CLAUDE.md 갱신 대상 |
| docker.io 참조 | 28 / 9(런타임) / 15(빌드 베이스) | **모순이 아니라 다른 표면** — 표기 분리 |
| **DB 크기** | 문서 261MB vs 라이브 **1,510MB** | 🔴 복제 대역·재-basebackup 시간 기준값 |
| 앱 종수 | 문서 "10종" vs 실측 **13 워크로드**(Deployment 11 + Rollout 2) | 전 문서 정정 |
| KEDA 컨슈머 | 문서 "3종" vs 실측 **4종** | 동상 |

---

## 리허설 없이는 확인 불가 (1-9 의 근거)

1. 실제 read-only replica 에서 앱 거동 — 기동은 안 막힌다고 실측했으나 **쓰기 요청 시 사용자에게 보이는 동작**은 미검증
2. CNPG replica cluster 에서 **`pg-pooler`(PgBouncer)가 designated primary 로 라우팅되는지** — 앱 10종이 이 경로
3. **PGSync 가 replica cluster 에서 논리 복제 슬롯을 만들 수 있는지** — 물리 standby 는 제약이 있다. ES 재파생을 DR 에서 돌릴지 결정에 직결
4. **DR 의 Redis/ES 가 쓰기 가능한지** — chat 세션·ocr/video 잡 상태·일일 상한이 전부 Redis 쓰기 → **PG 와 무관한 별도 블로커**
5. Cilium cluster-pool IPAM 실동작 (온프렘에서 재현 불가)
6. 페일오버/페일백 총 소요 — git 2건 + 오프셋 4그룹 + pg 수동 sync ≈ 7단계로 **추정**

---

## 규모

```
Phase 0   21건   ← 이게 끝나야 AWS 착수
Phase 1   13건
Phase 2    9건
상시       5건
──────────────
합계      48건 (5인 · 8~9주)
```

진짜 차단은 Phase 0 중 **0-1~0-4(config 대공사) · 0-6(TSC) · 0-19(쿼터)** 6건이고, 나머지는 병렬 처리 가능하다.
보안 8건(0-11~0-18)은 별도 레인으로 돌릴 수 있다.

---

## 갱신 이력

| 날짜 | 내용 |
|---|---|
| 2026-08-07 | 최초 작성. 감사 205 findings + DR 등급 실측 워크플로 결과 통합. 확정 C-1~C-6 반영 |
| 2026-08-07 | Cloudflare 프록시 호환성 실측 반영 — §0.2 D-ing 갱신 + Phase 1-B(1-10~1-13) 신설. 총 44→48건 |
