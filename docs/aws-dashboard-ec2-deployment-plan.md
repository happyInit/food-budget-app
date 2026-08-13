# FinOps · Operations AI 대시보드 — AWS EC2 통합 배포 계획

> 기준일: 2026-08-13  
> 목표: FinOps 대시보드와 Operations AI 이상징후 대시보드를 AWS EC2 한 대에서 운영한다.

## 1. 최종 구조

```text
운영자 브라우저
        │ HTTPS
        ▼
Cloudflare
 ├─ finops.mealbong.cloud
 └─ ops.mealbong.cloud
        │ HTTPS 443
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

Private EKS 관측 스택
├─ Prometheus
├─ Loki
├─ Tempo
└─ Alertmanager → Operations API webhook

AWS 관리형 서비스
├─ Cognito: FinOps 로그인
└─ Bedrock: Operations RCA
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

FinOps는 Cognito `FinOpsViewer`, `FinOpsAdmin` 그룹으로 인증·인가한다. Operations는 내부 관제 화면이므로
공개 전에 팀 운영자 접근 정책(Cloudflare Access 또는 별도 Cognito 인증)을 반드시 적용한다.

### 3.1 FinOps Cognito 확정 설정

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

FinOps 로그인 흐름은 아래와 같다.

```text
FinOps 접속
→ Nginx auth_request
→ finops-oauth2-proxy
→ Cognito Managed Login
→ /oauth2/callback
→ 보안 세션 쿠키
→ Nginx → finops-api
→ FastAPI가 Cognito JWT 서명·issuer·client_id·만료·그룹을 재검증
```

FinOps 내부 운영자 규모에서는 Cognito Essentials의 월 10,000 MAU 무료 구간을 사용한다.
App Client Secret은 SSM/Secrets Manager에만 저장한다.

## 4. Cloudflare와 EC2

### EC2

| 항목 | 결정값 |
| --- | --- |
| 인스턴스 | `t3.medium` |
| 아키텍처 | x86_64 (Graviton/ARM 아님) |
| 위치 | App VPC Public Subnet |
| 고정 IP | Elastic IP |
| 디스크 | Docker 이미지·로그용 gp3 EBS |
| 관리 | SSH 대신 SSM Session Manager 권장, IMDSv2 강제 |

### Cloudflare

1. `finops.mealbong.cloud`, `ops.mealbong.cloud` A 레코드를 EC2 Elastic IP로 생성한다.
2. 두 레코드의 Cloudflare Proxy를 활성화한다.
3. Cloudflare SSL/TLS 모드는 `Full (strict)`로 설정한다.
4. Cloudflare Origin Certificate를 발급해 공용 Nginx에 설치한다.
5. Nginx는 HTTP 80을 HTTPS 443으로 리다이렉트한다.

## 5. 통신과 보안 그룹

| 출발 | 목적지 | 포트 | 용도 |
| --- | --- | --- | --- |
| Cloudflare | EC2 Nginx | 80, 443 | 두 대시보드 HTTPS |
| EKS Alertmanager | EC2 private IP / Operations API | 8011 | Alert webhook |
| Operations API | 외부 PostgreSQL | 제공 DB 포트 | Alert·Incident·Evidence 저장 |
| FinOps API | 외부 PostgreSQL | 5432 또는 제공 포트 | FinOps 데이터 저장·조회 |
| Operations API | Private EKS Prometheus/Loki/Tempo endpoint | 9090/3100/3200 | Metric·Log·Trace 조회 |
| FinOps API | Kubecost private endpoint | 제공 API 포트 | 비용·효율 조회 |
| FinOps API | Cognito·AWS·GCP API | 443 | 인증·비용 데이터 조회 |
| Operations API | Bedrock Runtime | 443 | RCA 호출 |

외부 인터넷에는 Nginx의 80/443만 연다. `8000`, `8011`, `4180`, DB 포트,
Prometheus/Loki/Tempo 포트는 외부에 공개하지 않는다.

EKS의 Kubernetes `ClusterIP`와 `.svc` DNS는 EC2에서 직접 사용하지 않는다.
EC2에서 접근 가능한 private query endpoint 또는 proxy를 EKS 쪽에 준비한다.

## 6. 환경값과 인증

비밀번호, Cognito Client Secret, PostgreSQL CA, GCP WIF 설정은 Git·이미지·Compose YAML에 넣지 않는다.
EC2의 SSM Parameter Store 또는 Secrets Manager에서 `/opt/mealbong/runtime/` 파일로 주입한다.

```text
/opt/mealbong/runtime/finops.env
  - 학원 제공 PostgreSQL 접속 정보
  - Cognito 설정
  - Kubecost endpoint
  - GCP WIF 설정

/opt/mealbong/runtime/operations.env
  - Operations PostgreSQL 접속 정보
  - Prometheus / Loki / Tempo private endpoint
  - OPERATIONS_RCA_PROVIDER=bedrock
  - BEDROCK_MODEL_ID=apac.amazon.nova-micro-v1:0
```

EC2 Instance Profile에는 다음 최소 권한만 준다.

- FinOps: 실제 사용하는 Cost Explorer·CloudWatch 등 읽기 권한
- Operations: Bedrock Runtime InvokeModel 권한
- ECR: 이미지 pull 권한
- SSM/Secrets Manager: 런타임 비밀값 읽기 권한

### 6.1 FinOps 외부 PostgreSQL·GCP 확정 사항

FinOps 영구 데이터는 EC2 내부 MongoDB가 아니라 **학원 제공 외부 PostgreSQL**을 사용한다.
학원이 제공한 database, schema, table, column, index, 계정 권한, TLS·allowlist 계약을 그대로 따른다.
프로젝트가 DB schema를 임의 생성하거나 변경하지 않는다.

```text
학원 PostgreSQL 접속·schema 계약 수령
→ EC2에서 TLS·권한 검증
→ 제공 schema 기준 FinOps repository mapping
→ MongoDB 데이터 이관 필요 여부·주체 확정
→ staging에서 API 응답·날짜별 비용 합계 회귀 검증
→ PostgreSQL 기반 FinOps 배포
→ 3~7일 롤백 기간 후 MongoDB 컨테이너·기존 K8s 리소스 Retire
```

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
3. Cloudflare DNS, Proxy, Full (strict), Origin Certificate를 설정한다.
4. EC2에 Docker Engine·Docker Compose를 설치하고 `dashboard-net`을 생성한다.
5. ECR 또는 확정된 이미지 배포 방식으로 FinOps·Operations 이미지 준비한다.
6. EKS 관측 query endpoint, Alertmanager → EC2:8011, Kubecost private endpoint, 외부 PostgreSQL 연결을 확인한다.
7. Cognito User Pool·App Client·Callback URL·FinOps 그룹을 설정한다.
8. `finops.env`, `operations.env`를 SSM/Secrets Manager에서 주입한다.
9. `compose-edge.yml`로 Nginx를 기동한다.
10. `compose-finops.yml`로 FinOps API·oauth2-proxy·Kubecost proxy를 기동한다.
11. `compose-operations.yml`로 Operations API를 기동한다.
12. 각 도메인, API health, Cognito 로그인, PostgreSQL, Kubecost, Prometheus/Loki/Tempo, Alertmanager, Bedrock을 순서대로 검증한다.

### 7.1 FinOps Cutover 순서

1. 학원 PostgreSQL의 endpoint, schema, 계정, TLS, allowlist와 이관 책임을 최종 확인한다.
2. 제공 schema 기준 FinOps repository와 API를 구현·검증한다.
3. Cognito Viewer/Admin 로그인을 각각 검증한다.
4. PostgreSQL 데이터와 기존 MongoDB 데이터의 날짜별 비용 합계·중복·주요 API 응답을 비교한다.
5. `finops.mealbong.cloud`을 AWS Nginx로 전환한다.
6. 기존 MongoDB와 Kubernetes 리소스는 최소 3~7일 롤백 가능 상태로 유지한다.
7. 승인 후에만 MongoDB 컨테이너, 기존 Deployment/Service/ConfigMap/NodePort/PVC를 Retire한다.

## 8. 완료 검증과 롤백

| 검증 | 기대 결과 |
| --- | --- |
| `https://finops.mealbong.cloud` | Cognito 로그인 후 FinOps 화면 표시 |
| `https://ops.mealbong.cloud` | 운영자 인증 후 Operations 화면 표시 |
| FinOps `/api/health` | Nginx → FinOps API 응답 |
| Operations `/ops-api/health` | Nginx → Operations API 응답 |
| FinOps | PostgreSQL·Kubecost·AWS/GCP 조회 성공 |
| Operations | Alert → Incident 저장, Prometheus·Loki·Tempo Evidence 조회 성공 |
| Operations RCA | Bedrock 호출 결과 표시 |
| 외부 포트 | 80/443 외 직접 접근 불가 |
| FinOps 권한 | Viewer는 조회만, Admin만 설정·관리 API 사용 |
| FinOps JWT | 다른 User Pool·만료 토큰은 401, Viewer의 Admin API는 403 |
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
