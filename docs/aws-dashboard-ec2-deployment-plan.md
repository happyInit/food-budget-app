# FinOps · Operations AI 대시보드 — AWS EC2 통합 배포 계획

> 기준일: 2026-08-13 · **정본 대조 반영 2026-08-13 (C-84·C-85)**
> 목표: FinOps 대시보드와 Operations AI 이상징후 대시보드를 AWS EC2 한 대에서 운영한다.
>
> 🔴 **이 문서는 `docs/mp_aws_prep_checklist.md` 의 하위 문서다.** 충돌하면 **체크리스트가 이긴다**
> (해당 결정 = **C-84** 형상 · **C-85** 내부 접근). 아래 5건은 정본 대조로 **초판에서 바뀐 것**이다:
>
> | 초판 | 확정 |
> |---|---|
> | Cloudflare **Proxy 활성화(주황)** + Full(strict) + Origin Cert | 🔴 **회색(DNS 전용)** — C-60 과 같은 형태 |
> | 인증 = **Cognito** + oauth2-proxy / ops 는 **CF Access** | 🔴 **Cognito·CF Access 둘 다 미채택.** `oauth2-proxy` → **Google** + 이메일 allowlist |
> | 외부 PG 포트 = "5432 또는 제공 포트" | 🔴 **`15432`** (라이브 netpol 실측) |
> | EKS 관측 접근 = "private query endpoint 또는 proxy 를 준비" | 🔴 **NodePort + 노드 사설 IP** (C-85 · **LB 0개**) |
> | §6.1 MongoDB → PostgreSQL 이관·retire 절차 | 🔴 **범위 밖** — 담당자 개인 로컬 설치물. 학원 PG 를 그대로 쓴다 |

## 1. 최종 구조

```text
운영자 브라우저
        │ HTTPS
        ▼
Cloudflare  (🔴 회색 = DNS 전용. 프록시 없음 — C-84)
 ├─ finops.mealbong.cloud  → EC2 Elastic IP
 └─ ops.mealbong.cloud     → EC2 Elastic IP
        │ HTTPS 443  (Nginx 가 TLS 종단)
        ▼
App VPC / Public Subnet
└─ EC2 t3.medium (x86_64) + Elastic IP
   ├─ 공용 Nginx
   │  ├─ finops.mealbong.cloud
   │  │  ├─ FinOps 정적 대시보드
   │  │  ├─ /api/*     → finops-api:8000
   │  │  └─ /oauth2/*  → finops-oauth2-proxy:4180
   │  └─ ops.mealbong.cloud
   │     ├─ Operations 정적 대시보드
   │     └─ /ops-api/* → operations-api:8011
   │
   ├─ finops-api
   ├─ finops-oauth2-proxy
   ├─ kubecost-proxy
   └─ operations-api

외부 PostgreSQL
├─ FinOps 데이터베이스 / 학원 제공 schema
└─ Operations `operations` schema

EKS 관측 스택  (🔴 접근 = NodePort + 노드 사설 IP · C-85)
├─ Prometheus      ← 지금 쓴다
├─ kubecost        ← 지금 쓴다 (C-64 로 인클러스터)
├─ Loki / Tempo    ← 🟡 **신규 기능** (현 netpol 에 없다 = 아직 안 쓴다)
└─ Alertmanager → Operations API webhook  (EKS 에서 나가는 방향 · netpol egress + SG 만)

AWS 관리형 서비스
└─ Bedrock: Operations RCA  (apac.amazon.nova-micro-v1:0)

인증 (🔴 AWS 관리형 아님 — 오리진에서 한다)
└─ oauth2-proxy → Google OAuth + 이메일 allowlist (양 도메인 공용)
```

브라우저는 PostgreSQL, EKS 관측 스택, Kubecost, AWS API, GCP API, Bedrock에 직접 연결하지 않는다.
각 대시보드는 Nginx를 거쳐 각자 FastAPI에만 요청한다.

## 2. 배포 단위

공개 443 포트를 받는 Nginx는 **한 컨테이너만** 운영한다. 도메인별 Nginx `server` 블록으로
FinOps와 Operations를 분리한다.

기존 서비스별 Compose 파일은 유지하고, 공용 Docker network만 공유한다.

```text
compose-edge.yml
└─ nginx

compose-finops.yml
├─ finops-api
├─ finops-oauth2-proxy
└─ kubecost-proxy

compose-operations.yml
└─ operations-api
```

```bash
# 최초 한 번
docker network create dashboard-net

# 각 Compose 파일에 공통 적용
networks:
  dashboard-net:
    external: true
```

각 API 컨테이너는 `dashboard-net`에 자신의 서비스 이름으로 연결한다.
Nginx는 `finops-api:8000`, `operations-api:8011`로 프록시한다.

## 3. 도메인과 Nginx 경로

| 도메인 | 정적 화면 | API 경로 | 인증 |
| --- | --- | --- | --- |
| `finops.mealbong.cloud` | FinOps Dashboard | `/api/*` → `finops-api:8000` | Cognito + oauth2-proxy |
| `ops.mealbong.cloud` | Operations Dashboard | `/ops-api/*` → `operations-api:8011` | 운영자 접근 정책 적용 후 공개 |

Nginx는 API 컨테이너 재배포로 Docker IP가 바뀌어도 서비스 이름을 다시 조회하도록 Docker DNS를 사용한다.

```nginx
resolver 127.0.0.11 ipv6=off valid=10s;

server {
  server_name finops.mealbong.cloud;

  location /api/ {
    set $finops_upstream http://finops-api:8000;
    proxy_pass $finops_upstream;
  }

  location /oauth2/ {
    set $oauth_upstream http://finops-oauth2-proxy:4180;
    proxy_pass $oauth_upstream;
  }
}

server {
  server_name ops.mealbong.cloud;

  location /ops-api/ {
    set $operations_upstream http://operations-api:8011;
    proxy_pass $operations_upstream;
  }
}
```

### 3.1 🔴 인증 확정 — oauth2-proxy → Google (Cognito·CF Access 미채택)

Cloudflare 를 **회색**으로 두므로 CF Access 는 경로에 없다. Cognito 도 미채택이다.
⇒ **인증을 엣지가 아니라 오리진에서 한다.**

| 항목 | 확정값 |
|---|---|
| 프록시 | `oauth2-proxy` (플랜 초판의 `finops-oauth2-proxy` 컨테이너를 그대로 쓴다) |
| IdP | **Google OAuth** — 팀 운영자 신원이 이미 Google 이다(현행 CF Access 구글 SSO) |
| 인가 | `--authenticated-emails-file` 로 **운영자 이메일 allowlist**. 코드 0 |
| 적용 범위 | `finops.` `ops.` **양 도메인** — Nginx `auth_request` 를 두 `server` 블록에 각각 |
| 비밀 | Client ID/Secret 은 SSM/Secrets Manager → `/opt/mealbong/runtime/` |

🟢 **오리진 인증이라 우회 문제가 원리적으로 없다.** 엣지 인증(CF Access)이면 EIP 직타로
인증을 건너뛸 수 있어 SG 를 CF IP 범위로 못박아야 하는데, 그 요구가 사라진다.

🔴 **`mp-account` 의 JWT 를 재사용하지 않는다.** 두 가지 이유다:
① **순환의존** — 대시보드 로그인이 EKS 를 지나면 **EKS 가 죽었을 때 그걸 알려주는 대시보드에
   로그인할 수 없다.** 이상징후 대시보드의 존재 이유와 정면으로 충돌한다.
② `mp-account` 는 최종사용자 인증이라 **앱에 가입한 누구나 JWT 를 받는다** — 운영자 role 개념을
   새로 만들어야 한다.

🔴 **대가 = 회색이라 Cloudflare WAF·DDoS 가 앞에 없다.** 5인용 화면이므로 Nginx `limit_req` 로
받고, 필요하면 나중에 SG 를 좁힌다(가역).

### 3.2 ~~FinOps Cognito 확정 설정~~ — ⛔ 미채택 (2026-08-13)

> 아래는 **집행하지 않는다.** Cognito 미채택이 확정됐다(C-84). 왜 이 안이 있었는지의 기록으로만 남긴다.

| 항목 | 설정 |
| --- | --- |
| 리전 | `ap-northeast-2` |
| User Pool | `finops-dashboard-users` |
| App Client | `finops-dashboard` |
| 로그인 | Cognito Managed Login, Authorization Code Grant |
| Scope | `openid email profile` |
| Callback URL | `https://finops.mealbong.cloud/oauth2/callback` |
| Logout URL | `https://finops.mealbong.cloud/` |
| 가입 방식 | 자체 회원가입 비활성화, 관리자 초대 |
| 권한 그룹 | `FinOpsViewer`, `FinOpsAdmin` |
| MFA | TOTP 인증 앱 권장 |

🔴 **확정된 로그인 흐름** (Cognito 자리에 Google 이 들어간다):

```text
finops. / ops. 접속
→ Nginx auth_request
→ oauth2-proxy
→ Google OAuth 동의
→ /oauth2/callback
→ 보안 세션 쿠키
→ Nginx → finops-api / operations-api
→ FastAPI 가 oauth2-proxy 가 넘긴 이메일 헤더를 allowlist 와 재검증
```

FinOps 내부 운영자 규모에서는 Cognito Essentials의 월 10,000 MAU 무료 구간을 사용한다.
App Client Secret은 SSM/Secrets Manager에만 저장한다.

## 4. Cloudflare와 EC2

### EC2

| 항목 | 결정값 |
| --- | --- |
| 인스턴스 | `t3.medium` |
| 아키텍처 | 🔴 **x86_64 확정** (Graviton/ARM 아님) — 근거는 아래 |
| 위치 | App VPC Public Subnet |
| 고정 IP | Elastic IP |
| 디스크 | Docker 이미지·로그용 gp3 EBS |
| 관리 | 🔴 **`aws ssm send-command`(Run Command)** · IMDSv2 강제 · hop limit 1 |

🔴 **x86_64 를 고른 근거** — C-63 은 CI 서버를 `t4g.xlarge`(Graviton) 로 확정하며 x86 을 기각했다.
여기서 **반대로 가는 것은 의도된 예외**다: FinOps 이미지의 arm64 가용성이 미확인이라
*"ARM 을 구울 수 있을지 불확실하니 무난하게"*(사용자 판단) — 즉 **리스크를 월 $5~8 로 산다**
(`t4g.medium` 대비). 🔴 그 대가로 이 EC2 의 이미지는 **arm64 트랙(`1-6`·#610)에서 빠진다.**

🔴 **`ssm start-session` 을 쓰지 않는다** — 대화형 셸이라 에이전트·스크립트가 못 쓴다.
`send-command` 가 `ssh '<명령>'` 과 동형이다(C-80). Ansible `community.aws.aws_ssm` 도 같은 경로다.

### Cloudflare — 🔴 회색(DNS 전용) 확정

1. `finops.mealbong.cloud`, `ops.mealbong.cloud` A 레코드를 EC2 Elastic IP로 생성한다.
2. 🔴 **두 레코드의 Cloudflare Proxy 를 끈다(회색).** C-60 이 `app.mealbong.cloud` 에 쓴 형태와 같다.
3. 🔴 **TLS 인증서는 ACM 이 아니라 Let's Encrypt 를 Nginx 에 둔다** — ALB 를 안 지나므로 ACM 을 쓸 수 없다.
   (초판의 Cloudflare Origin Certificate 는 **주황 전용**이라 회색에서는 브라우저가 신뢰하지 않는다.)
4. Nginx 는 HTTP 80 을 HTTPS 443 으로 리다이렉트한다.
5. 🔴 **TTL 을 60s 로 둔다** — 회색이면 TTL 이 우리 몫이다(주황일 땐 CF 가 관리했다).

🔴 **회색을 고른 근거** = ① 인증이 오리진에 있으므로 엣지 프록시가 인증에 기여하지 않는다
② 주황이면 EIP 직타로 엣지를 우회할 수 있어 **SG 를 CF IP 범위로 못박는 유지 부담**이 생긴다
③ 서비스(`app.mealbong.cloud`)와 **같은 패턴**이 되어 형상이 하나로 줄어든다.

## 5. 통신과 보안 그룹

| 출발 | 목적지 | 포트 | 용도 |
| --- | --- | --- | --- |
| Cloudflare | EC2 Nginx | 80, 443 | 두 대시보드 HTTPS |
| EKS Alertmanager | EC2 private IP / Operations API | 8011 | Alert webhook — 🟢 EKS **egress netpol** + EC2 SG 만. LB 불요 |
| Operations API | 학원 PostgreSQL | 🔴 **15432** | Alert·Incident·Evidence 저장 |
| FinOps API | 학원 PostgreSQL | 🔴 **15432** | FinOps 데이터 저장·조회 |
| Operations API | 🔴 **노드 사설 IP:NodePort** (Prometheus) | NodePort | Metric 조회 — C-85 |
| Operations API | 🔴 **노드 사설 IP:NodePort** (Loki·Tempo) | NodePort | 🟡 **신규 기능** — 현 netpol 에 없다 |
| FinOps API | 🔴 **노드 사설 IP:NodePort** (kubecost) | NodePort | 비용·효율 조회 (라이브 `30090` 이 이미 이 패턴) |
| FinOps API | Google OAuth · AWS · GCP API | 443 | 인증·비용 데이터 조회 |
| Operations API | Bedrock Runtime | 443 | RCA 호출 |

외부 인터넷에는 Nginx의 80/443만 연다. `8000`, `8011`, `4180`, DB 포트,
Prometheus/Loki/Tempo 포트는 외부에 공개하지 않는다.

### 5.1 🔴 EKS 조회 경로 = NodePort + 노드 사설 IP (C-85 · 로드밸런서 0개)

**왜 ClusterIP 가 안 되는가** — 벽은 공개/사설 서브넷이 **아니다**(같은 VPC 는 로컬 라우트로 통한다):
① ClusterIP `10.30.0.0/16` 은 **노드 eBPF 안의 가상 주소**라 VPC 에 존재하지 않는다
② `*.svc.cluster.local` 은 **CoreDNS** 가 답한다 — EC2 는 클러스터 DNS 를 안 쓴다

🟢 **C-82(Cilium ENI 모드)로 파드는 진짜 VPC IP 를 받는다** ⇒ 라우팅 자체는 이미 된다.
남은 문제는 도달성이 아니라 **주소 지정**(파드 IP 가 재스케줄마다 바뀐다)이다.

**확정 = NodePort.** 근거:
- 🟢 **이미 쓰는 패턴** — 라이브 `cost/kubecost-frontend 9090:30090`
- 🟢 **노드 IP 가 자주 안 바뀐다** — C-64 가 kubecost 를, 스토리지 사유로 Prometheus 도
  **MNG 고정 노드**에 묶었다(Karpenter 노드가 아니다)
- 🟢 Nginx/API 의 `upstream` 에 **노드 3대를 두고 헬스체크**하면 1대 교체는 견딘다
- 🟢 **가역** — 아프면 내부 NLB(`target-type: ip`)로 올린다. 반대 방향은 불가

🔴 **대가와 상쇄 조건** — MNG 롤링 업그레이드로 노드가 **동시에** 교체되면 끊긴다.
⇒ **Nginx 502 / API 조회 실패를 알림에 걸어라.** 관측 도구가 조용히 빈 그래프를 보이는 것이
   최악의 실패 모드다.

🔴 **상시 `kubectl port-forward` 로 대체하지 말 것** — 온프렘에서 감사로그 보존창을
30일 → **52.62시간**으로 붕괴시킨 주범이다(체크리스트 `1-25`). AWS 는 audit → CloudWatch Logs 가
**이미 월 ~$59 추정**(C-66)이라 "무료" 경로가 오히려 비싸진다.

**보안** — NodePort 는 VPC 안에서만 도달한다. 노드 SG 에 **대시보드 EC2 의 SG 만** 허용하는
규칙을 달면 인터넷 노출은 0 이다.

## 6. 환경값과 인증

비밀번호, Cognito Client Secret, PostgreSQL CA, GCP WIF 설정은 Git·이미지·Compose YAML에 넣지 않는다.
EC2의 SSM Parameter Store 또는 Secrets Manager에서 `/opt/mealbong/runtime/` 파일로 주입한다.

```text
/opt/mealbong/runtime/finops.env
  - 학원 제공 PostgreSQL 접속 정보  (🔴 포트 15432)
  - Google OAuth Client ID / Secret  (oauth2-proxy · 🔴 Cognito 아님)
  - Kubecost NodePort endpoint       (🔴 노드 사설 IP:NodePort · C-85)
  - GCP WIF 설정

/opt/mealbong/runtime/operations.env
  - Operations PostgreSQL 접속 정보  (🔴 학원 PG · 포트 15432)
  - Prometheus / Loki / Tempo endpoint  (🔴 노드 사설 IP:NodePort · C-85)
  - OPERATIONS_RCA_PROVIDER=bedrock
  - BEDROCK_MODEL_ID=apac.amazon.nova-micro-v1:0
```

EC2 Instance Profile에는 다음 최소 권한만 준다.

- FinOps: 실제 사용하는 Cost Explorer·CloudWatch 등 읽기 권한
- Operations: Bedrock Runtime InvokeModel 권한 (`apac.amazon.nova-micro-v1:0`)
- ECR: 이미지 pull 권한 — 🔴 리포 경로는 **`mealplanning/`** 를 유지한다(A-46 확정)
- SSM/Secrets Manager: 런타임 비밀값 읽기 권한
- GCP WIF: 이 Instance Profile 이 **Google Cloud Workload Identity Pool 의 AWS Provider** 주체가 된다
- 🔴 **Cognito 권한은 없다** — 미채택(C-84)

### 6.1 FinOps 학원 PostgreSQL·GCP 확정 사항

FinOps 영구 데이터는 **학원 제공 PostgreSQL** 을 사용한다.
학원이 제공한 database, schema, table, column, index, 계정 권한, TLS·allowlist 계약을 그대로 따른다.
프로젝트가 DB schema를 임의 생성하거나 변경하지 않는다.

🔴 **접속 정보 (라이브 netpol 실측)** — `211.46.52.152:15432`.
현행 `mp-operations` 의 netpol 이 `ipBlock: 211.46.52.152/32` · port `15432` 로 잡혀 있다.
초판의 *"5432 또는 제공 포트"* 는 오류다. **SG 규칙에 그대로 들어가는 값이므로 15432 로 적는다.**

🔴 **allowlist 는 교체가 아니라 추가다.** 지금 학원 쪽 allowlist 에는 **온프렘(사무실) 공인 IP** 가
등록돼 있다(현재 `mp-operations` 가 온프렘에서 붙는다). 온프렘은 이관 후에도 살아 있으므로
(C-72·C-83) **대시보드 EC2 의 Elastic IP 를 추가**해서 **둘 다** 등록된 상태여야 한다.
⚠️ 어느 층에서 막는지는 미확인이다 — `pg_hba.conf` 면 틀렸을 때 **명확한 에러**가 나고,
서버 앞 방화벽이면 **타임아웃**이라 진단이 어렵다. 포트가 비표준(15432)이라 **앞단 장비 가능성이 높다.**

### 6.2 ⛔ MongoDB 이관·retire — **범위 밖** (2026-08-13 확정)

> 🔴 **우리 대상이 아니다.** 라이브 클러스터 전수 확인 결과 MongoDB 워크로드 **0개** ·
> `finops`/`operations` 네임스페이스 **없음** · PVC 21개 중 MongoDB **없음** ·
> NodePort 는 `cost/kubecost-frontend 30090` **딱 1개**(MongoDB 무관).
> 담당자가 **개인 로컬에 설치한 것**이라 프로젝트 인프라가 아니다.
>
> ⇒ 초판 §6.1 의 *"MongoDB 컨테이너·기존 Deployment/Service/ConfigMap/NodePort/PVC Retire"* 절차는
> **집행하지 않는다.** 처음부터 학원 PG 를 쓴다. 🟢 부수로 **C-83 우려도 소멸**한다
> (온프렘 K8s 리소스를 지우는 작업이 아니었다).

GCP는 장기 Service Account Key를 사용하지 않는다.

```text
EC2 Instance Profile
→ Google Cloud Workload Identity Pool의 AWS Provider
→ finops-dashboard-reader Service Account
→ BigQuery · Monitoring · Asset · Recommender 읽기
```

GCP WIF credential configuration JSON도 Git에 넣지 않고 컨테이너에 읽기 전용으로 마운트한다.

## 7. 배포 순서

1. App VPC Public Subnet에 x86_64 `t3.medium`, Elastic IP, gp3 EBS를 생성한다.
2. EC2 Instance Profile, Security Group, SSM 접속을 설정한다.
3. 🔴 Cloudflare DNS **A 레코드(회색 · TTL 60s)** 를 만들고, Nginx 에 **Let's Encrypt** 인증서를 둔다.
   (~~Proxy 활성화 · Full(strict) · Origin Certificate~~ 는 주황 전용이라 미채택)
4. EC2에 Docker Engine·Docker Compose를 설치하고 `dashboard-net`을 생성한다.
5. ECR 또는 확정된 이미지 배포 방식으로 FinOps·Operations 이미지 준비한다.
6. 🔴 **NodePort 경로**를 확인한다 — 노드 SG 에 대시보드 EC2 SG 허용 규칙 · 노드 사설 IP:NodePort 로
   Prometheus·kubecost 조회 · Alertmanager → EC2:8011(EKS egress netpol) · 학원 PG `15432` 연결.
7. 🔴 **Google OAuth 클라이언트**를 만들고 Redirect URI(`https://<도메인>/oauth2/callback` ×2)를 등록,
   운영자 이메일 allowlist 파일을 준비한다. (~~Cognito User Pool~~ 미채택)
8. `finops.env`, `operations.env`를 SSM/Secrets Manager에서 주입한다.
9. `compose-edge.yml`로 Nginx를 기동한다.
10. `compose-finops.yml`로 FinOps API·oauth2-proxy·Kubecost proxy를 기동한다.
11. `compose-operations.yml`로 Operations API를 기동한다.
12. 각 도메인, API health, **Google 로그인**, 학원 PostgreSQL, Kubecost, Prometheus, Alertmanager,
    Bedrock 을 순서대로 검증한다.

### 7.1 FinOps Cutover 순서 (🔴 MongoDB 비교·retire 단계 제거 — §6.2)

1. 학원 PostgreSQL 의 endpoint(`211.46.52.152:15432`), schema, 계정, TLS, **allowlist 에 EIP 추가**를 최종 확인한다.
   🔴 온프렘 IP 를 **빼지 않는다** — 추가다(C-72).
2. 제공 schema 기준 FinOps repository 와 API 를 구현·검증한다.
3. 🔴 **Google 로그인**을 allowlist 등재자 / 미등재자 각각으로 검증한다(후자는 403 이어야 한다).
4. `finops.mealbong.cloud` A 레코드(회색)를 EC2 EIP 로 전환한다.
5. 롤백 = **레코드 1개** 되돌리기. 컨테이너는 이미지 SHA 만 직전 정상 SHA 로 되돌린다.

## 8. 완료 검증과 롤백

| 검증 | 기대 결과 |
| --- | --- |
| `https://finops.mealbong.cloud` | **Google 로그인** 후 FinOps 화면 표시 |
| `https://ops.mealbong.cloud` | **Google 로그인** 후 Operations 화면 표시 |
| 🔴 회색 확인 | `dig +short` 가 **EIP** 를 답한다(CF IP 아님) · 응답에 `cf-ray` 헤더 **없음** |
| FinOps `/api/health` | Nginx → FinOps API 응답 |
| Operations `/ops-api/health` | Nginx → Operations API 응답 |
| FinOps | PostgreSQL·Kubecost·AWS/GCP 조회 성공 |
| Operations | Alert → Incident 저장, **NodePort 경유** Prometheus Evidence 조회 성공 |
| Operations RCA | Bedrock 호출 결과 표시 |
| 외부 포트 | 80/443 외 직접 접근 불가 |
| 🔴 인가 | allowlist **미등재 Google 계정은 403** |
| 🔴 NodePort 격리 | 대시보드 EC2 **밖에서** 노드 NodePort 접근 시 **차단**(SG) |
| 🔴 조용한 실패 방지 | 노드를 하나 빼도 조회가 유지되고, 전부 막히면 **Nginx 502 알림이 발화**한다 |
| FinOps GCP | WIF로 BigQuery `SELECT 1` 성공 |

한 서비스를 교체할 때는 다른 서비스를 재시작하지 않는다.

```bash
# Operations만 교체
docker compose -f compose-operations.yml up -d --no-deps operations-api

# FinOps만 교체
docker compose -f compose-finops.yml up -d --no-deps finops-api
```

문제가 생기면 해당 Compose의 이미지 SHA만 직전 정상 SHA로 되돌려 재기동한다.
`docker compose down -v`는 사용하지 않는다.
