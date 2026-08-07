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
| C-3 | **온프렘 = ① DR 대기 사이트(Warm Standby, 등급 C) + ② 크롤 상시 프로덕션** — 🔴 **이중 역할** | 2026-08-07 | 실측(아래) |
| C-4 | **DNS = Cloudflare 유지** (Route 53 미채택) | 2026-08-07 | 사용자 |
| C-5 | **터널(cloudflared) = 온프렘 DR 전용 존치** (Retire 아님) | 2026-08-07 | C-3·C-4 의 귀결 |
| C-6 | **사이트 간 연결 = Tailscale** (복제 전용 최소 구성) | 2026-08-06 | 사용자 |
| C-7 | **Cilium IPAM = `cluster-pool`** (오버레이 유지, ENI 모드 미채택) | 2026-08-07 | 아래 |
| C-8 | **VPC / Landing Zone** — 리전·계정 3개·CIDR·AZ 3개·서브넷·NAT (6항목) | 2026-08-07 | 아래 |
| C-9 | **진입점 = 공개 ALB 1개만. 내부 도구 6종은 ALB 없이 Tailscale 로만** | 2026-08-07 | 아래 |
| C-10 | **AWS Kafka = Strimzi 자체운영** (MSK·SQS 미채택) | 2026-08-07 | 사용자 |
| C-11 | **온프렘 Kafka 존치**(3 브로커·RF=3) · **크롤 운반 = 온프렘 produce → MM2 → AWS** | 2026-08-07 | 아래 (가-2 해소) |

#### C-11 의 근거 — 온프렘 Kafka 존치 (가-2 해소)

**존치의 근거는 "크롤 운반" 하나다. DR 은 근거가 못 된다** — 실측이 그렇게 나왔다.

**용도 A(DR) = 불필요** — 앱 13종 중 Kafka 를 쓰는 건 `mealplan` 하나(ADD_CART 클릭스트림)뿐이고,
- **플래그가 꺼져 있다** (`services/mealplan/app/config.py:42` `event_produce_enabled: bool = False`, 클러스터 override **0건**) → 발행량 `events.user.activity` **0 msgs/24h**
- 켜도 **완전 fail-open** (`events.py:50` — *"Kafka 부재/발행오류 무엇이든 담기를 막지 않음"*)
→ 🔴 **DR 사이트에 Kafka 가 없어도 유저는 아무것도 못 느낀다.**

**용도 B(크롤 운반) = 필수** — 철거하면 크롤러가 터널 너머로 직접 produce 하게 되고, 내구성 경계가 **7일 → 5분**으로 회귀한다(§0.2 D4-a 운반 설계).

**비용 실측** — `49m CPU`(16+18+15) · `2.4Gi RAM`(828+789+808Mi) · 디스크 20Gi×3 프로비저닝에 **실사용 81MB(0.4%)** · 달러 **$0**.
🟢 warm standby 전환 자체가 자원을 **−880m CPU / −736Mi** 줄이므로 이 49m 은 그 여유 안에 들어간다.
🔴 축소안(1 브로커 RF=1)은 절감이 **33m CPU / 1.6Gi** 뿐인데 내구성 경계가 **단일 디스크**가 된다 → 기각.

🔴 **감수하는 것**
- "이관하면 온프렘이 단순해진다"가 **아니다**. Kafka 3 브로커 + Strimzi 오퍼레이터를 계속 패치·감시해야 한다
- **Strimzi 버전을 양쪽에서 맞춰야 한다** — 갈리면 MM2 호환성 문제. Cilium 1.19.6 ↔ K8s 1.34 와 같은 종류의 버전 제약이 하나 는다
- 20Gi × 3 PVC 를 계속 잡는다(실사용 81MB — 축소는 별건)

🟡 **가-1(MM2 복제 정책)·가-3(MM2 자원·비용)은 여전히 미결** — §0.2 D4-a 참조.
🟡 **"페일오버 후 파이프라인까지 온프렘에서 돌릴지"는 지금 안 정한다** — Kafka 를 남기면 그 선택지가 열린 채 유지되므로 DR 런북(2-6·D6) 때 정한다.

#### C-10 의 귀결
온프렘·AWS 양쪽이 같은 오퍼레이터(Strimzi)를 쓰므로 **MirrorMaker 2(Kafka↔Kafka 전용)가 선택지로 열린다** — MSK 였다면 설정이 달라지고, SQS 였다면 MM2 자체가 성립하지 않는다.
🔴 단 **MM2 채택 여부는 아직 미확정**이다(§0.2 D4-a). MM2 자원·비용도 미검증.

#### C-9 의 근거
온프렘은 LB 가 2개다 — `.14` 공개(`app.mealbong.cloud`) · `.15` 내부(Grafana·ArgoCD 등 6종).
AWS 에서 이 둘을 어떻게 나눌지가 논점이었고, **내부용 ALB 를 만들지 않는 쪽**을 골랐다.

- 🔴 내부 도구를 인터넷 쪽 ALB 에 얹는 안은 **감사 #58 이 이미 경고**한 위험이다
  (*"내부 게이트웨이 netpol 이 의도적 전면 개방 + 와일드카드 SNI — scheme 을 틀리면 그대로 인터넷 노출"*)
- **Tailscale 은 이미 확정(C-6)** 이라 추가 인프라가 0 이다
- ALB 요금 1개분으로 끝난다 (내부 ALB 별도면 ~$16~20/mo 추가)

🔴 **포기하는 것 — 팀 합의 필요**: 지금은 브라우저에서 `https://grafana.mealbong.cloud` 만 치면 되지만,
앞으로는 **tailnet 에 붙어 있어야** 내부 도구를 볼 수 있다. 5명이 Tailscale 을 상시 켜둘 수 있어야 성립한다.

⚠️ ALB 관련 사실 정정 — **ALB 는 AZ 마다 하나가 아니라 1개가 여러 AZ 에 ENI(발)를 두는 구조**다.
요금도 1개분. 단 **최소 2개 AZ 의 서브넷을 요구**하고, **고정 IP 가 없어 반드시 DNS 이름으로 가리켜야 한다**
(zone apex 는 Cloudflare 의 CNAME flattening 으로 해결 — C-4 가 여기서도 편하다).

#### C-7 의 근거
- **온프렘 standby 와 동형성** — 네트워크 모델이 다르면 C-3 이 약속한 "상시 증명"의 범위가 줄어든다
- **AWS API 의존 0** — ENI 모드는 CNI 가 IRSA 에 의존해 IAM 사고 = 전면 네트워크 장애가 된다. C-4 와 같은 원칙
- **파드 밀도 실측 최대 36/노드** → ENI 면 인스턴스 타입을 강제당하고 그건 곧 비용
- 🔴 **포기한 것**: ENI 였다면 가능했을 **파드별 보안그룹**(AWS 쪽 통제 한 겹). 네트워크 격리가 전부 Cilium netpol 하나에 걸린다.
  감수 근거 = app ns 양방향 default-deny 가 이미 라이브·실증됨(#532). 확대 대상은 0-17·0-18
- 실작업은 Helm values 의 ipam 모드 + 풀 CIDR 지정뿐. **리스크는 전부 EKS 기본 애드온 제거 순서에 있다**(감사 #11) → 리허설 필요(1-9)

#### C-8 상세

```
① 리전     ap-northeast-2 (서울)
② 계정     management · security · prod        ← 3계정
③ CIDR     VPC 10.10.0.0/16
           EKS 파드 10.20.0.0/16 (cluster-pool)
           EKS Service 10.30.0.0/16 (명시 지정 — 기본 10.100/16 회피)
④ AZ       3개
⑤ 서브넷   public × 3 · private × 3 (각 /24)
⑥ NAT      1개 (AZ 3개가 공유) + VPC 엔드포인트 S3(무료)·ECR·STS
```

**② 계정 3개의 근거** — 각 상자가 방어하는 게 실제로 존재한다.
`management` = C-4 의 "계정 잠김" 시나리오 / `security` = #118(CIS 감사로그가 EKS 로 안 넘어감)의 대체 자리 / `prod` = VPC 가 하나라 network·platform 계정은 방어 대상이 없다.
🔴 `sandbox` 미채택 — 쿼터 증액(0-19)을 계정마다 신청해야 하고, **Terraform 으로 destroy/apply 를 반복하는 게 원래 워크플로**라 첫 prod 클러스터가 리허설을 겸한다.
경계 규칙 = **"PG 데이터를 넣기 전까지는 언제든 destroy 가능"**.
⚠️ Control Tower 미사용 — AWS Config 를 켜서 조용히 비싸진다.

**④ AZ 3개의 근거** — quorum 3 이 필요한 컴포넌트가 **3개**다(실측 2026-08-07).

| 컴포넌트 | 개수 | quorum | AZ 2 면 | 죽으면 |
|---|---|---|---|---|
| Kafka (KRaft combined) | 3 | 🔴 2/3 | 2/1 → 50% | 크롤·알림 (유저 경로 아님) |
| **Elasticsearch** (b:2+a:1) | 3 | 🔴 2/3 | 2/1 → 50% | 🔴 **레시피 검색** |
| **Redis Sentinel** | 3 (`quorum: 2`) | 🔴 2/3 | 2/1 → 50% | 🔴 **chat · OCR · 영상** |
| PG (CNPG) | 2 | ❌ primary-standby | 무관 | — |
| Redis 데이터 | 2 | ❌ master-replica | 무관 | — |

🟢 **추가 비용은 cross-AZ 전송료 월 $1~5 뿐이다** — AZ 는 구매 대상이 아니라 배치 구획이고,
서브넷은 무료, NAT 는 1개 공유, 노드 수는 AZ 가 아니라 **리소스 수요**(9.86 core / 26.26GiB)가 정한다.
🔴 단 **0-6(TSC 완화) 선행** — 현 hard TSC 가 "AZ당 2대"를 강제해 그대로 두면 AZ 3 = 노드 6대가 된다.

**⑥ 는 미완** — Interface 엔드포인트(ECR·STS, 각 ~$7~8/mo) vs NAT 데이터 처리 절감의 손익이
이미지 pull 볼륨에 달렸다. S3 Gateway 는 무료라 무조건 채택.

#### 🔴 C-3 성격 정정 (2026-08-07) — "대기"가 아니다

종전 서술은 온프렘을 **"상시 대기 사이트(Standby)"** 라고만 했다. **그 표현은 틀렸다.**
C-11 로 크롤 7종이 온프렘에 상시 잔류하기로 확정되면서, 온프렘은 **평시에도 현역**이 됐다.

| 역할 | 평시 | 페일오버 시 |
|---|---|---|
| ① **DR 대기** — 앱 13종·PG replica·cloudflared | 대기(트래픽 0) | 승격 |
| ② **크롤 프로덕션** — 크롤 CronJob 7종 + Kafka 3 브로커 | 🔴 **현역. 이 일은 AWS 가 대신 못 한다** | 그대로 |

🔴 **이걸 "standby" 로만 읽으면 사고가 난다** — *"대기 사이트니까 꺼도 되겠지"* 로 판단하면 **크롤이 통째로 멈춘다.**
온프렘 정지 = DR 능력 상실 **+ 데이터 수집 중단** 두 가지다.

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

> 🔴 **2026-08-07 사용자 명시**: *"아직 D4 확정 아니야. 저거 결정해야 할 게 많이 남은 것 같고 **내가 일단 이해가 다 간 상태가 아니야**."*
> → **D4 는 실측만 끝났고 결정은 안 났다.** 다음 세션은 **확정을 묻기 전에 먼저 설명**해야 한다.
> 설명 방식은 메모리 `decision-presentation-style` 참조 — 용어 → ASCII 다이어그램 → 선택지별 장·단점 → **비용** → 권고 + 포기하는 것.

| # | 항목 | 권고 | 상태 |
|---|---|---|---|
| ~~D2~~ | ~~Cilium IPAM~~ | → **C-7 로 확정** (2026-08-07) | ✅ |
| D-ing | AWS 유입 | Cloudflare 프록시(주황) → ALB → Istio **(조건부)** | 🟢 호환성 실측 완료 — 아래 |
| D4-a | 파이프라인 배치 | **외부 크롤 7종 = 온프렘**(23중 7) / 리파이너·컨슈머 6 + 내부배치 10 = AWS · 운반 = C-11 | 🟡 **배치·운반 구조 확정(C-11). 남은 것 = 가-1 복제정책 · 가-3 MM2 비용** |
| D4-b | Redis | 🟢 **ElastiCache `cache.t4g.micro`** (1단계 무코드) | 🟡 실측 완료, 확정 대기 |
| ~~D4-c~~ | ~~Kafka~~ | → **C-10 으로 확정** (2026-08-07) | ✅ |
| D4-d | ES·PG | 오퍼레이터 유지 (RDS 는 DR 물리복제 불가라 배제) | 미결 |
| D6 | 배포 전략 | 클러스터=Blue-Green / 앱=Canary 유지(ADR-0001) | 미결 |
| D7 | 비밀 백엔드 | SSM Parameter Store + 🔴 온프렘 이중 공급 | 미결 |
| D10 | 비용 | 실측 $678/mo → GitLab EC2 포함 시 **~$715~750** (목표 $219 의 3.3~3.4배) | 🔴 목표 재설정 필요 |
| **D-rep** | **prod 앱 replica 정책** | 유저 경로 7종(frontend·account·recipe·mealplan·pantry·price·recipebook) = **2** / 비동기 6종 = 1 | 🔴 **노드 사이징(D10) 확정 후** |

#### D-rep 배경 (2026-08-07)

실측: app ns 13 워크로드 **16 파드** — `account`·`recipe`·`frontend` 만 2 이고 **나머지 10종이 replica 1** 이다.
🔴 **AZ 를 몇 개 쓰든 그 10종은 HA 가 아니다.** 가용성은 최약 링크가 정한다.

| | AZ 2 + replica 1 | AZ 3 + replica 1 | AZ 3 + replica 2 |
|---|---|---|---|
| Kafka·ES·Sentinel | 🔴 50% | 🟢 100% | 🟢 100% |
| 앱 | 🔴 재스케줄 대기 | 🔴 재스케줄 대기 | 🟢 즉시 |

**두 축은 독립이다** — AZ 수는 quorum 이, replica 는 앱 HA 가 정한다.
AZ 를 2로 내려도 replica 1 문제는 그대로 남고 quorum 까지 같이 약해지므로, C-8 ④ 와 별개로 결정한다.

- 앱은 대부분 stateless 라 재스케줄이 빠르다(수십 초~수 분). 🔴 예외 = `ranking-serving`(**model PVC** → EBS AZ 핀)
- 비동기 6종(notify·chat·ocr·video·ranking·operations)은 **202+폴링** 구조라 잠깐의 부재를 감수할 수 있다
- 🔴 **replica 2 만으로는 부족** — TSC 없이는 둘 다 같은 AZ·같은 노드에 뜰 수 있다. 0-6 참조

#### D4-a 실측 (2026-08-07) — 파이프라인 배치

🔴 **멘토 제안("파이프라인 온프렘 존치")의 비용 근거는 무너졌다. 논거를 교체해야 한다.**

| 근거 | 실측 | 판정 |
|---|---|---|
| AWS 컴퓨트 절약 | 파이프라인 **상시 3m CPU / 56 MiB** · 동시 피크 **0.6 vCPU / 1.05 GiB**(`poller-kurly` 단독) | 🔴 붕괴. 기존 노드 여유에 흡수 |
| NAT 데이터 처리료 | 수신 2.29 GB/일 → 월 ~69 GB ≈ **$4~5/월** | 🔴 판단을 뒤집을 크기 아님 |
| **크롤 egress IP** | 프록시·IP 로테이션 코드 **0건** · 회피는 kurly `playwright_stealth` 하나 · **가정용 IP 로도 8일 중 1일 실패**(`Page.goto: Timeout 50000ms`) | 🟢 **유일하게 강한 근거** |
| 증폭비 | 외부 **2.29 GB/일** 수신 → **4.7 MB/일** 만 적재 = **490:1** | 🟢 터널 대역폭은 논점이 아님 |

**분할선 = ns 가 아니라 Kafka.** `pipeline` ns 22개 중 PG writer 12개이고 그중 9개가 크롤이 아니라 유저/OLTP 트랙이라,
ns 로 자르면 유저 이벤트가 AWS→온프렘→AWS 로 역주행한다.

```
[온프렘] 외부 크롤 CronJob 7종 (23 워크로드 중 7)
   kurly · oasis-dawn · oasis-noon · deal-timesale · deal-closesale · recipe · recipe-review
     └ 전부 `--kafka`. psycopg 0 · PG 쓰기 0  → 코드 변경 0 (recipe-review 는 #557 로 편입)
     └ produce 는 전부 **LAN**(온프렘 Kafka) — 터널을 안 건넌다
[AWS]   리파이너·컨슈머 6종(신규 review-refiner 포함) + 내부 배치 CronJob 10종
        └ 그중 Bedrock 2종(score-review-sentiment · summarize-reviews)
```

#### D4-a 운반 설계 (2026-08-07) — 🟡 **권고, 미확정**

🔴 **문제**: 크롤러가 터널 너머로 직접 produce 하면 **`delivery.timeout.ms` 기본 300초(5분)** 가 유실 경계가 된다.
반면 브로커에 들어간 데이터는 **retention 7일**을 기다려준다 — **2,016배** 차이. → **터널을 건너는 주체를 프로듀서가 아니라 브로커로 바꾼다.**

⚠️ **대역폭은 논점이 아니다** — 터널을 건널 양은 **4.7 MB/일**인데, 온프렘은 이미 barman WAL 로 **361 MB/일**(77배)을 인터넷으로 보내고 있다. 위험은 속도가 아니라 **단절 내성**이다.

```
[온프렘] 크롤러 7종 ─LAN(acks=all·RF=3)→ Kafka(이미 존재·실측 49m CPU/2.4Gi)
                                            │  ▲
                                    정방향   │  │ 역방향(요청 이벤트 · #557)
                                            ▼  │
                    ╌╌ Tailscale ╌╌ [ MirrorMaker 2 ] ╌╌  🔴 AWS 에서 돌린다
                                            │              (원격 consume / 로컬 produce)
[AWS] Kafka(정본 · Strimzi C-10) ───────────┘ → 리파이너 6종 → PG·ES·Redis
```

- **비대칭 원칙** — *produce 는 로컬에서, consume 은 터널 너머로.* 컨슈머는 오프셋이 브로커(서버)에 있어 끊겨도 그 자리에서 이어간다. 이 원칙이 **MM2 를 AWS 에 두는 이유**이기도 하다(온프렘에 두면 produce 가 터널을 건너 5분 문제가 재발)
- 🟢 **온프렘 신규 컴포넌트 0** — 브로커는 이미 있고 MM2 는 AWS 쪽이다
- **온프렘 경유 토픽 4종** = `retail.crawl.raw` · `retail.deal.raw` · `recipe.crawl.raw` · 🆕 `recipe.review.raw`. AWS 자생(`events.user.activity` · `price.anomaly.detected`)은 온프렘을 안 거친다
- 🔴 **복제지 이동이 아니다** — 원본은 온프렘에 7일 남는다. AWS 쪽이 잘못돼도 그 안이면 다시 흘릴 수 있다

🔴 **포기·감수**
- MM2 는 **진행 관점의 단일 실패점** — 죽으면 조용히 멈춘다. **복제 랙 알림 신설 필수**(선택 아님)
- 온프렘 Kafka 3 브로커 부양 — 달러 비용 0이나 **DR 용 존치 전제**가 깨지면 계산이 바뀐다
- 🔴 **0-24(#558)가 선행** — MM2 를 넣어도 크롤러→로컬 브로커 구간의 produce 실패는 그대로 조용하다

🔴 **확정 전 필요한 결정 3건**
| | 내용 |
|---|---|
| 가-1 | **MM2 복제 정책** — #557 이 역방향을 요구하므로 루프 방지에 **접두사 정책**이 필요할 전망(단방향이면 Identity 로 이름 동일 가능). 토픽명은 `_topics.py` 가 전부 `os.environ` 조회라 **ConfigMap 값만 바뀌고 코드는 안 바뀐다** |
| 가-2 | **온프렘 Kafka 존치 확정** — 2-6 이 "DR Kafka"를 전제하나 C-3 warm standby 범위에 명시가 없다. 이 설계 전체의 토대 |
| 가-3 | **MM2 자원·비용** — Kafka Connect 파드. AWS 쪽이라 실비용 발생. ~0.5~1 vCPU **추정(미검증)** → D10 에 얹힘 |

**원칙**: PG 에 쓰는 코드는 PG 옆에, 크롤하는 코드는 IP 가 필요한 곳에. 그 둘을 Kafka 가 잇는다.
근거 = `load_retail.py:94/102/114/120` 이 레코드당 개별 `execute` → 3~4 왕복/레코드 × 7,300건/일 ≈ **29,200 왕복/일**.
PG writer 를 PG 옆에 두면 이 왕복이 전부 로컬이 된다. (🔴 Tailscale RTT 미실측 — 20ms 초과면 배치화가 선결)

🔴 **예외 1건 — `mp-poller-recipe-review`**

| | psycopg | PG 쓰기 | kafka |
|---|---|---|---|
| kurly/prototype.py | 0 | 0 | 16 |
| oasis/oasis_crawler.py | 0 | 0 | 13 |
| 10k_recipe/10k_recipe_crawler.py | 0 | 0 | 18 |
| **10k_recipe/review_crawler.py** | **4** | **2** | **0** |

- 이유는 정제가 아니라 **입력 구조**다 — 대상 선정을 PG 에서 한다(`:221-232` `select r.id … left join recipe_review_crawl … where c.recipe_id is null`).
  다른 크롤러는 대상을 인자(`--categories`)나 외부 목록에서 얻는다.
- 접촉 패턴: 대상 조회 `fetchall` **1회** + 저장 `executemany`(`:248`) + 상태 `execute`(`:261`). 스케줄 **주 2회(일·수) 06:00 KST**.
  → `load_retail.py` 와 성격이 다르다. 터널 너머여도 부담이 작다.
  🟡 다만 `save_reviews`·`save_crawl_status` 가 매번 `with db_connect()` 로 **새 연결**을 연다 → 연결 재사용 개선 권장(수 줄)
- ⚠️ 담당자 증언 *"최초에만 PG, 이후 Kafka"* 는 **`10k_recipe_crawler.py`(레시피 본문)** 의 설계다(`:117` 주석 + 실제 `--kafka` 로 가동 중).
  **`review_crawler.py`(요리후기)에는 그 전환이 안 됐다** — Kafka 코드 0건, argparse 설명이 *"입력·출력 모두 PG"*.

**권고 = 트랙 분리**
- AWS 이관 트랙 → **그대로 온프렘 잔류(코드 0)**. 이관을 리팩터링에 묶지 않는다
- 설계 일관성 트랙 → **별도 이슈 = #557**(2026-08-07 등재·갱신). 사용자 선택 = **① 완전 Kafka 화 · 신규와 갱신을 단일 경로로**.
  발행자 둘(`recipe-refiner`=신규 / 신규 `review-refresh-picker` CronJob=갱신) → 같은 토픽 `recipe.review.requested` → 온프렘 크롤러가 소비 → `recipe.review.raw` → AWS `review-refiner` → PG.
  실측 — 미크롤 **0건**(7,444 전량 `ok`)이라 **백필 불요** · 요청 이벤트 회차당 **164~407건** · 신규 ~310줄/개조 ~130줄/파일 7개 · netpol 추가 0.
  🔴 **선행 = 0-24(#558)** — 크롤러를 프로듀서로 바꾸는 작업이라 전달실패 미관측 결함 위에 얹힌다.
  🔴 이관 트랙과 분리하되 **시점은 이관 전** — 백필 불요 조건은 나빠지기만 하고, **이관 전에는 Kafka 가 하나라 MM2 가 무관**하며(구조를 먼저 완성해 두면 그대로 MM2 위에 얹힌다), 지금은 크롤러·Kafka·PG 가 같은 클러스터 안이다.

  **검토 후 기각 2건** (근거는 #557 코멘트)
  - ~~온프렘 로컬 `recipe.crawl.raw` 재사용~~ — MM2 단방향으로 끝낼 수 있어 매력적이었으나 🔴 **후기 갱신 대상을 못 고른다**. 지금은 `review_crawler.py:220` 이 PG 조회라 조건 한 줄로 재방문이 켜지는데, 그 능력을 잃는다
  - ~~레시피 크롤러에 후기 수집 병합~~ — 두 크롤러가 **같은 URL 을 각각 fetch** 하는 게 실측됐다(`10k_recipe_crawler.py:194` ↔ `review_crawler.py:238`). 합치면 요청 절반·크롤러 6종. 🔴 그러나 위와 같은 문제 + **절감 크기가 작다**(주 330~810건 = 전체 크롤의 1.4~3.4%)

  **후기 분포 실측** — 최소 1 · 중앙값 3 · 평균 19.1 · 최대 739. **후기 ≥50 인 692건(9.3%)이 전체 후기의 67.5%**(95,746/141,883). 하위 4,003건(53.8%)은 3.8%뿐.
  → 갱신은 상위 티어 한정으로 충분(월 1회면 **일 ~23요청**). 🟡 임계·주기는 미결 파라미터.
- 🔴 담당자 확인 2건 — (a) 만개의레시피 IP 차단/429 경험이 있나 (b) Kafka 전환이 원래 로드맵인가

#### D4-b 실측 (2026-08-07) — Redis ElastiCache

| | 실측 | `cache.t4g.micro`(0.5 GiB) 대비 |
|---|---|---|
| 데이터셋 | **0.91 MiB** | 0.18% |
| 15일 피크 | **6.75 MiB** | 1.32% |
| 키 개수 | 6 (피크 47) | — |

⚠️ 그 피크는 **k6 부하 창**이다. 실사용자 트래픽은 `events.user.activity` **0 msgs/24h** — "실사용 피크를 쟀다"고 쓰면 거짓이다. 다만 100배여도 0.5 GiB 안.

🟢 **코드 변경 0줄** (encryption-in-transit OFF 시) — 비-Sentinel 폴백이 **이미 기본값**이다:
`chat/app/db.py:46-53` · `price/app/db.py:32-40` · `pipelines/stream/_redis.py:25-29` · `ingest/refresh_price_matview.py:27-40`
전부 `if settings.redis_sentinels: … else Redis(host,port)`. 단위테스트도 있다. `video`·`ocr` 은 애초에 Sentinel 미사용.
→ ConfigMap 2개(`REDIS_SENTINELS` 를 빈 값) + `rollout restart` (🔴 `envFrom.configMapRef` 는 파드 기동 시 주입).

🔴 **TLS/AUTH ON 은 별건** — 지원 코드 0건. config 4파일 + 생성지점 8곳 = **8파일 50~70줄 추정**(실측 아님).

🔴 **"온프렘 동형성" 논거는 무효였다** — 온프렘 Redis 도 영속성이 없다(`aof_enabled:0`, StatefulSet 에 `volumeClaimTemplates` 없음).
게다가 앱 4종 중 `video`·`ocr` 은 온프렘에서도 이미 비-Sentinel 직결이라 **이미 분열돼 있고, ElastiCache 로 가면 오히려 통일**된다.

🔴 **`mp-redis-pgsync` 는 대상 밖** — **385 ops/s**(앱 Redis 5 ops/s 의 48배). 매니지드로 얹으면 비용·AZ 홉만 는다.
부수 발견: PGSync 는 Redis 를 체크포인트로 **안 쓴다**. `CHECKPOINT_PATH=/app/checkpoint` 가 **emptyDir** → 파드 재시작 시 소멸(별건 결함, 1-16).

💰 **비용 미검증** — AWS API 호출을 금지시켜 달러 환산을 못 냈다. 확정된 건 "최소 노드로 충분"뿐.

---

## 1. 목표 아키텍처 (🔄 결정이 늘 때마다 여기에 얹는다)

> 이 그림이 확정 결정(§0.1)의 시각적 정본이다. **새 결정이 나오면 지우고 다시 그리지 말고 얹는다.**

```
                                    ┌─────────────┐
                              유저 ─┤ Cloudflare  │  DNS(C-4) + 프록시(D-ing)
                                    │ WAF·DDoS·CDN│  · CNAME flattening
                                    └──────┬──────┘
═══ AWS Organizations ═══════════════════  │  ═══════════════════════════════
                                           │
 ┌─ management 계정 ─┐  ┌─ security 계정 ─┐│
 │ SSO · SCP        │  │ CloudTrail 로그  ││   (C-8 ②)
 │ Budgets · 결제    │  │ S3 Object Lock  ││
 └──────────────────┘  └─────────────────┘│
                                           │
 ┌─ prod 계정 ═ VPC 10.10.0.0/16 (ap-northeast-2) ═══════════════════════┐
 │                             [IGW]                                      │
 │                               │                                        │
 │   ┌──────────── ALB 1개 (internet-facing) ──────────────┐   (C-9)      │
 │   │   ENI●(AZ-a)      ENI●(AZ-b)      ENI●(AZ-c)        │              │
 │   └────────────────────────┬─────────────────────────────┘             │
 │                            │  ※ ALB 는 1개. AZ 마다 "발"만 있다        │
 │  ┌─ AZ-a ──────────┐ ┌─ AZ-b ──────────┐ ┌─ AZ-c ──────────┐         │
 │  │ public /24      │ │ public /24      │ │ public /24      │         │
 │  │  NAT GW ●       │ │                 │ │                 │  (C-8⑥) │
 │  │  rt: 0/0 → IGW  │ │  rt: 0/0 → IGW  │ │  rt: 0/0 → IGW  │         │
 │  ├─────────────────┤ ├─────────────────┤ ├─────────────────┤         │
 │  │ private /24     │ │ private /24     │ │ private /24     │         │
 │  │  EC2 노드 ●      │ │  EC2 노드 ●      │ │  EC2 노드 ●      │         │
 │  │   └ Istio GW    │ │                 │ │                 │         │
 │  │   └ 파드 10.20.x│ │   └ 파드 10.20.x│ │   └ 파드 10.20.x│  (C-7)  │
 │  │  kafka-0        │ │  kafka-1        │ │  kafka-2        │ Strimzi │
 │  │                 │ │                 │ │                 │ 자체운영│
 │  │                 │ │                 │ │                 │ (C-10)  │
 │  │  es-0           │ │  es-1           │ │  es-2           │   3     │
 │  │  sentinel-0     │ │  sentinel-1     │ │  sentinel-2     │  (C-8④)│
 │  │  pg-primary     │ │  pg-standby     │ │                 │  ← 2개  │
 │  │  rt: 0/0 → NAT  │ │  rt: 0/0 → NAT  │ │  rt: 0/0 → NAT  │         │
 │  └─────────────────┘ └─────────────────┘ └─────────────────┘         │
 │                                                                        │
 │  [VPC 엔드포인트]  S3(Gateway·무료) · ECR api/dkr · STS                │
 │  [EC2]  GitLab (CI)                              (C-2)                 │
 │  [ECR] [S3 백업·Loki·Tempo] [SSM Parameter Store]                      │
 └────────────────────────────────────────────────────────────────────────┘
        ▲                                          │
        │ Tailscale (C-6)          │ MirrorMaker 2  │ CNPG 물리복제 (WAL)
        │ · 내부 도구 6종 (C-9)     │ (AWS 에서 당김) │ · 상시
        │ · 팀원 kubectl            │  ↓ 수집결과     │
        │                          │  ↑ 갱신요청     │   (C-11)
        ▼                          ▼  (#557)        ▼
 ┌─ 온프렘 = ① DR 대기 + ② 크롤 상시 프로덕션 (C-3 이중역할) ────────────┐
 │  LAN 192.168.0.0/24 · 파드 10.244.0.0/16 · svc 10.96.0.0/12           │
 │                                                                        │
 │  ② 현역 — 평시에도 돈다. AWS 가 대신 못 한다          (C-11)          │
 │     크롤 CronJob 7종  kurly·oasis×2·deal×2·recipe·recipe-review        │
 │        └ 전부 LAN produce (acks=all·RF=3) → 코드 변경 0                │
 │     Kafka 3 브로커 (Strimzi · 실측 49m CPU / 2.4Gi / 81MB)             │
 │        retail.crawl.raw · retail.deal.raw · recipe.crawl.raw           │
 │        · recipe.review.raw · recipe.review.requested(역방향 수신)      │
 │                                                                        │
 │  ① 대기 — 트래픽 0                                                     │
 │     앱 13종 상시 가동(replica 1) · PG replica cluster(read-only)        │
 │     cloudflared 터널 (평시 replicas 0 · 페일오버 시 기동)  (C-5)        │
 │     Harbor = ECR 미러 (DR 이미지 공급)                                  │
 │                                                                        │
 │  🔴 "standby 니까 꺼도 된다"로 읽으면 크롤이 통째로 멈춘다              │
 └────────────────────────────────────────────────────────────────────────┘

  CIDR 비충돌 (C-8③)
    AWS  VPC 10.10/16 · 파드 10.20/16 · svc 10.30/16
    온프렘 192.168.0.0/24 · 파드 10.244/16 · svc 10.96/12
    터널  Tailscale 100.64.0.0/10
```

**아직 이 그림에 없는 것** (결정되면 얹는다)
- 🟡 **MM2 세부** — 복제 정책(가-1)·자원 배치와 비용(가-3). 구조는 C-11 로 확정돼 위에 얹었고, 남은 건 설정값이다
- 🟡 **파이프라인 워크로드 23종의 AWS 쪽 배치** — 리파이너 6 + 내부 배치 CronJob 10. §0.2 D4-a 에 목록은 있으나 그림엔 아직 안 얹었다
- D4-b Redis — 관리형(ElastiCache)으로 갈지 (Kafka 는 C-10·C-11 로 자체운영 확정)
- D5 스토리지 — EBS/EFS · MinIO→S3 · PV 이관
- D7 비밀 — SSM ↔ 온프렘 이중 공급 경로
- D8 관측 — kube-prometheus-stack 자체 유지 여부
- D10 노드 사이징 · 인스턴스 타입 → D-rep(앱 replica)
- S4 AWS 계정 보안 — SSO 권한 세트 · GuardDuty · CloudTrail 배선

---

## Phase 0 — 이게 끝나야 AWS 착수

### 0-A. 차단 — 안 고치면 EKS 에서 앱이 안 뜬다

- [ ] **0-1 config 레포 eks 분기 골격** — services 13종 외 전 트랙(pipelines·platform·monitoring·gateway·argocd 44개)이 분기 수단 자체가 없음 〔감사 #25 #13 #2〕
- [ ] **0-2 ESO 스토어 추상화** — `fb-kubernetes` 23파일 하드코딩, eks 패치 0건 → 시크릿 30종 전건 NotReady 〔#23 #83〕
- [ ] **0-3 Ansible 단독 → config 이관** — PriorityClass 3종(**워크로드 46개 참조**)·ResourceQuota 2·LimitRange 2·ns PSA·kube-prometheus-stack 전체 〔#20 #16〕
- [ ] **0-4 ArgoCD 뿌리 IaC화** — AppProject 3·root Application 2·repo SSH 자격증명이 레포에 없음 〔#87 #77〕
- [ ] **0-5 nodeSelector 온프렘 라벨 제거** — 워크로드 12+ 가 `host-a`/`k8s-worker-*` 하드코딩 → EKS 에서 영구 Pending 〔#6 #21〕
- [ ] **0-6 hard TSC 6종 완화** — 노드 하한을 "워커 4대·AZ당 2대"로 못박아 비용 목표와 정면 충돌 〔#8 #19〕
      🔴 **목표를 정확히**: `hostname` 축 hard→soft(`ScheduleAnyway`) · **`zone` 축은 soft 로 남기되 유지**.
      hard 를 풀면서 분산 의도는 보존해야 한다 — zone 축을 아예 지우면 replica 2 가 같은 AZ 에 뜬다(D-rep).
      C-8 ④(AZ 3) 와 D-rep 양쪽의 선행 조건이다.
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
- [ ] **0-22 🔴 Jenkins 백업 신설 — GitLab 이관 전 선행** — systemd 유닛 **없음**, `s3://mp-jenkins-backup-ap2` **NoSuchBucket**.
      그런데 `backup_strategy.md §7` 은 *"롤·버킷 준비 완료"* 라고 적고 있다. **마스터키 상실 = credentials 전량 복호 불가**
- [ ] **0-23 🔴 barman S3 경로 사이트 분기** — 현 경로 `s3://mp-backup-ap2/pg` 에 사이트 축이 없고 **양 사이트 Cluster 이름이 둘 다 `pg`** →
      `pg/pg/wals` 가 동일해 **WAL 이 서로를 덮는다**. `pg-prod` / `pg-dr` 로 분리.
      🔴 **standby 구축(0-20) 전에 잡는 게 압도적으로 싸다**
- [ ] **0-24 🔴 Kafka 프로듀서 전달 실패 미관측 — 유실을 성공으로 마감** 〔이슈 #558〕
      `on_delivery` 콜백이 **코드베이스 전체 0건**이고, 크롤 프로듀서 3종(`produce_retail.py:65`·`produce_recipe.py:48`·`10k_recipe_crawler.py:1322`)은
      `flush()` 반환값까지 버린다. `delivery.timeout.ms` **기본 300초** 만료로 영구 실패한 메시지는 **큐에서 빠지므로 `flush()` 로도 안 잡힌다**
      → 잡은 `FB_POLLER_RECORDS` 에 **`produce()` 호출 수**를 찍고 `result: "success"` 로 끝난다.
      🔴 **지금은 브로커가 같은 LAN 이라 실현 조건이 거의 없다. 이관 후엔 터널 5분 단절이 곧 그 회차 통째 유실이다** — 크롤은 일 1~2회 배치다.
      🔴 **D4-a·D4-c(터널을 어떻게 건널지)의 선행 조건** — 어느 안을 골라도 실패가 조용하면 실패했는지조차 모른다.
      09037b4(컬리 조용한 절단)와 같은 계열이며, 종료코드 전달까지 같은 고리다

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
- [ ] **1-14 🔴 `video` Redis 재시도 추가** — `video/app/store.py:33-39` `put_job`/`get_job` 에 **try/except 없음**(docstring:7 "실패해야 정직하다" = 의도).
      호출부 `main.py:202`(POST 추출)·`main.py:210`(GET 조회) 무방비 → **ElastiCache failover 순간 두 엔드포인트가 하드 500**. D4-b 의 선행
- [ ] **1-15 `chat`·`price` Redis 소켓 타임아웃 설정** — `chat/db.py:51-53`·`price/db.py:38-40` 미설정(video/ocr 은 3s, pipelines 5s).
      사이트 간 지연이 생기는 AWS 구성에서 무한 대기
- [ ] **1-16 🔴 PGSync 체크포인트가 emptyDir** — `CHECKPOINT_PATH=/app/checkpoint` 가 emptyDir 위 8 B 파일 2개 → **파드 재시작 시 소멸**.
      이관 중 파드는 반드시 죽는다. Redis 를 어떻게 하든 남는 별건 결함
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
- [ ] 🔴 **이미지 백업 알림이 영원히 안 울린다** — 식이 `count == 0` 이라 발화 불가. 실제 버킷 `mp-image-backup-ap2` 에
      앱 이미지 **0건**(플러그인 tar 1개뿐). **나이 기반**(`mp_backup_last_object_timestamp_seconds`)으로 교체
- [ ] 🔴 **온사이트 덤프 저장소는 DR 이 아니다** — MinIO **단일 replica · worker-b2 고정 · RWO openebs-lvm(노드 로컬)**.
      b2 디스크 사망 = 7일치 소멸. **"백업 2중화"로 계산하지 말 것.** 실제 DR 은 barman 단일 트랙
- [ ] **정본 문서 정정 4건** — ① `backup_strategy.md:163` "at-rest 암호화 꺼짐" ↔ 실물 **aescbc 켜짐**(`kube-apiserver.yaml:42`)
      ② §7 "버킷 준비 완료" ↔ NoSuchBucket ③ `secrets_backup/defaults:46-49` terraform 2종 ↔ 실물 부재
      ④ 🔴 **secrets 백업 묶음에 terraform `credentials.env`·`backend.conf` 가 빠져 있다** (온프렘 존치면 Proxmox 자격증명이 계속 필요)
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
| **DB 크기** | 문서 261MB · 이 문서 1,510MB vs **실측 848 MB** | 🔴 **848 MB 가 정본.** 그중 **549 MB 가 사체** → `VACUUM FULL` 후 실이전 **~277 MB** |
| WAL 볼륨 | — | **361 MB/일** (S3 3,031객체/3.25GB) |
| 온사이트 덤프 | — | 23~25 MiB → **08-07 169 MiB 급증** (원인 미특정 · `activity` 블로트 549MB) |
| 파이프라인 실사용 | requests 3 vCPU/3GiB | **상시 3m CPU / 56 MiB** · 피크 0.6 vCPU/1.05 GiB (1/30) |
| Redis 사용량 | — | 데이터셋 **0.91 MiB** · 15일 피크 6.75 MiB |
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
Phase 0   24건   ← 이게 끝나야 AWS 착수   (0-A 10 · 0-B 8 · 0-C 6)
Phase 1   16건                            (1-1~1-9 9 · 1-B 7)
Phase 2    9건
상시       8건
──────────────
합계      57건 (5인 · 8~9주)
```

⚠️ **2026-08-07 재집계 정정** — 종전 표기 `21/13/9/5 = 48` 은 실제와 어긋나 있었다. 08-07 에 추가된 6건(0-22·0-23·1-14~1-16·상시 3건)이 본문에만 들어가고 이 블록에 반영되지 않았던 것이 원인이다.
위 숫자는 본문 `- [ ]` 개수를 기계적으로 센 값이다(0-24 추가분 포함). **앞으로 항목을 늘리면 이 블록도 같이 고친다.**

진짜 차단은 Phase 0 중 **0-1~0-4(config 대공사) · 0-6(TSC) · 0-19(쿼터)** 6건이고, 나머지는 병렬 처리 가능하다.
보안 8건(0-11~0-18)은 별도 레인으로 돌릴 수 있다.

---

## 갱신 이력

| 날짜 | 내용 |
|---|---|
| 2026-08-07 | 최초 작성. 감사 205 findings + DR 등급 실측 워크플로 결과 통합. 확정 C-1~C-6 반영 |
| 2026-08-07 | Cloudflare 프록시 호환성 실측 반영 — §0.2 D-ing 갱신 + Phase 1-B(1-10~1-13) 신설. 총 44→48건 |
| 2026-08-07 | **C-7(Cilium cluster-pool)** · **C-8(VPC/Landing Zone 6항목)** 확정. D-rep(앱 replica 정책) 미결로 신설. 0-6 목표를 zone 축 보존으로 구체화 |
| 2026-08-07 | **C-9(진입점 = 공개 ALB 1개 · 내부 도구는 Tailscale)** 확정. **§1 목표 아키텍처 다이어그램 신설** — 결정이 늘 때마다 여기에 얹는다 |
| 2026-08-07 | **D4 실측 반영**(파이프라인 배치·Redis ElastiCache·PG 백업 2갈래). 신규 위험 6건 추가(0-22 Jenkins백업부재 · 0-23 barman경로충돌 · 1-14~1-16 · 상시 3건). DB 크기 1,510MB→**848MB** 정정 |
| 2026-08-07 | **0-24 신설 — Kafka 프로듀서 전달 실패 미관측**(이슈 #558). D4-a 예외의 구조 통일을 이슈 #557 로 등재(사용자 선택 = ① 완전 Kafka 화, 시점은 이관 전). **규모 블록 재집계 정정** 48→**57건**(종전 표기가 08-07 추가분을 반영하지 않고 있었다) |
| 2026-08-07 | **C-11 확정 — 온프렘 Kafka 존치**(가-2 해소, 3 브로커 RF=3 · 근거는 크롤 운반 단 하나 · DR 용도는 실측상 불필요). 🔴 **C-3 성격 정정 — "상시 대기 사이트" → "① DR 대기 + ② 크롤 상시 프로덕션" 이중역할**. §1 다이어그램 온프렘 박스 갱신 |
| 2026-08-07 | **C-10 확정 — AWS Kafka = Strimzi 자체운영**(D4-c 해소). **D4-a 운반 설계 신설**(온프렘 Kafka + MM2, 비대칭 원칙, 미확정 3건 가-1~가-3). #557 을 **신규·갱신 단일 경로**로 갱신 — 대안 2건(로컬 토픽 재사용 · 크롤러 병합) 검토 후 기각, 후기 롱테일 실측 추가 |
