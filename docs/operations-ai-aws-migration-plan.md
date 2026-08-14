# 대시보드 AWS 이관 구축 계획 — Operations AI + FinOps 공용 EC2

> 🔴 **이 문서가 대시보드 이관의 정본이다**(2026-08-14 · 사용자 확정 · C-84 에서 지목).
> 구 `docs/aws-dashboard-ec2-deployment-plan.md` 는 superseded 이지만 **아직 지우면 안 된다** —
> 아래 §0-B 의 승계 대상 5건이 그 문서에만 있다.
> 🔴 **이 문서는 `docs/mp_aws_prep_checklist.md` 의 하위 문서다. 충돌하면 체크리스트가 이긴다**
> (해당 결정 = **C-84** 형상 · **C-85** 내부 접근).
>
> ⚠️ **본문(§0~§7)은 작성자 원문 그대로다.** 아래 §0-A·§0-B 는 정본 대조에서 나온 것이고,
> **본문에는 아직 반영돼 있지 않다** — 읽을 때 §0-A 를 먼저 보고 본문을 보라.

---

## §0-A 🔴 정본 대조 결과 — 본문에서 고쳐야 할 것

2026-08-14 라이브 실측(Terraform `aws-platform` · config `platform/argocd/overlays/eks`) 기준.

### ① 값이 틀린 것 (4건)

| 위치 | 지금 | 고칠 값 |
|---|---|---|
| **B-5** 아웃바운드 PG | `5432` | 🔴 **`15432`** — C-84 가 *"5432 는 오류"* 라고 이미 정정한 값이고, 같은 문서 §5 는 이미 15432 다(**내부 모순**) |
| **B-5** 인바운드 / **§5** 표 첫 줄 | "Cloudflare IP 또는 승인된 운영자 CIDR" | 🔴 **`0.0.0.0/0` 443** — §2 에서 프록시를 껐으므로(회색) **Cloudflare 에서 오는 패킷이 0** 이다. CF IP 로 좁히면 **아무도 접속 못 한다.** 실물 SG 도 전체 개방이고 C-84 가 *"SG 를 CF IP 로 못박을 필요 없다"* 고 적었다. 출발지 표기도 "운영자 브라우저(임의 IP)" 로 |
| **§5** Bedrock | "443(**NAT 경유**)" | **IGW 경유** — 공개 서브넷 + EIP 라 NAT 를 타지 않는다. 🟢 NAT 처리요금도 안 붙고 **NAT 1대 SPOF(C-47) 영향도 없다** |
| **B-2.4** | "별도의 CloudWatch Alarm·Alertmanager·Prometheus 알람은 구성하지 않는다" | 🔴 **이 문장 삭제.** **C-85 가 LB 0개(NodePort)를 *"nginx 502 를 알림에 걸어 조용한 실패를 막는다"* 와 한 묶음으로 승인**했다. 게다가 같은 절의 15분 캐시가 **조용한 실패를 더 조용하게** 만든다(upstream 이 전멸해도 화면은 그럴듯하다) |

### ② 지워도 되는 것 — 이미 환경이 갖춰져 있다 (4건)

| 위치 | 왜 |
|---|---|
| **§6.2 확인필요 #1** 노드 SG 규칙 추가 요청 | ✅ **이미 있다** — `security_groups.tf` 의 `node_nodeport_from_dashboard` 가 대시보드 SG 에 **30000-32767 전 범위**를 열어 뒀다 |
| **B-2.1** 2·4번 "`30090` 만 허용" | 위와 같음. 이미 더 넓게 열려 있고 좁히는 건 별건이다 |
| **B-12 #1** kubecost NodePort 번호 확인 | ✅ **`30090` 확정** — config `platform/argocd/base/kubecost.yaml` 에 박혀 있다 |
| **B-6 · B-8 3번 · B-12 #2** ECR 리포 생성 | **EC2 에서 직접 빌드**하기로 했으므로 ECR 이 경로에 없다(§4 도 "ECR pull" → "EC2 자체 빌드" 로) |

### ③ 새로 해야 하는 것 (3건)

- 🔴 **Prometheus NodePort 를 만들어야 한다.** EKS 는 **ClusterIP 뿐**이다
  (`platform/argocd/overlays/eks/kube-prometheus-stack.yaml` 전체에 `NodePort` **0건**).
  kubecost 만 base 에서 NodePort 로 태어났고 Prometheus 는 EKS 에서 신설(`0-3`)이라 설정이 다르다 ⇒
  ***"kubecost 처럼 하면 되겠지"* 가 성립하지 않는다.** 없으면 **Operations 가 아무것도 못 본다.**
  ⇒ **A-5 확인 #1 이 "번호를 알려달라"가 아니라 "만들어야 한다"** 로 바뀐다. Loki·Tempo 도 같은 상태
  (플래그가 꺼져 있어 급하지 않다). 🟢 노드 SG 는 이미 열려 있어 **config PR 하나로 끝**이다.
- 🔴 **EC2 SG 인바운드 2줄 추가** — 실물은 **443 하나뿐**이다.
  `80`(없으면 **Let's Encrypt HTTP-01 발급·갱신 실패**) · `8011`(없으면 **Alertmanager webhook 이 안 온다**
  = Operations 의 입력 경로 자체).
- 🔴 **IMDS hop limit = 2.** 계획 전체가 *"컨테이너 안 boto3 가 Instance Profile 을 찾는다"* 에 서 있는데
  bridge 컨테이너 → IMDS 는 홉을 하나 더 지난다 ⇒ **hop limit 1 이면 전부 실패**한다.
  ⚠️ **CI 서버(`mp-ci-server`)는 정반대 이유로 1 이다**(컨테이너가 IMDS 에 닿으면 **안 되는** 설계) —
  그대로 베끼면 안 된다. 대가 = 컨테이너 하나가 뚫리면 인스턴스 권한 전부가 넘어간다 ⇒ non-root 실행.

### ④ 서술이 틀린 것 (4건)

- **§6.1-C** *"EC2용 netpol/egress 규칙을 우리가 추가하면 됨"* → 🔴 **netpol 은 K8s 파드에만 걸린다.**
  EC2 는 클러스터 밖이라 **적용 자체가 안 된다.** 실제로 필요한 건 ⓐ EC2 SG 아웃바운드(✅ 이미 전체 허용)
  ⓑ 🔴 **학원 PG allowlist 에 EIP 추가 — 우리가 못 한다**(§6.2 로 옮길 것).
  🟢 **netpol 이 진짜 필요한 곳은 반대 방향이다** — **Alertmanager(EKS) → EC2:8011** 은 나가는 트래픽이라
  `platform/policies-observability` 의 egress 에 EC2 사설 IP 를 넣어야 한다. 빠뜨리면 webhook 이 조용히 안 온다.
- **A-1** *"Prometheus 가 뜬 노드 IP 를 확인하고 그 IP 로 설정"* → **노드를 특정할 필요가 없다.**
  NodePort 는 `externalTrafficPolicy: Cluster`(기본)면 **어느 노드로 들어와도** 전달된다.
  🔴 게다가 EKS 오버레이가 **`nodeSelector` 5건을 제거**해서 파드는 실제로 옮겨 다닌다 ⇒
  노드를 박으면 **파드가 이사할 때마다 끊긴다.** 확인할 것은 `externalTrafficPolicy` 가 `Local` 이 아닐 것 하나.
- **A-2** Loki·Tempo 노드그룹 확정 → 위와 같은 이유로 **걱정이 사라진다.** 남는 건 *"NodePort 를 새로 열어야 한다"* 한 줄.
- **B-3 끝** *"공용 프로파일에 합칠지 분리할지 팀장 확정"* → **선택지가 아니다.** EC2 1대 = 인스턴스
  프로파일 **1개**. ⇒ 권한은 **합집합**이고 **FinOps 컨테이너가 뚫리면 Bedrock 권한도 같이 넘어간다**(사실로 서술할 것).

### ⑤ Bedrock — 새 권한 요청이 아니다

**A-4 의 *"이미 발급받은 상태로 알고 있음"* 을 이렇게 고친다** — 권한(`bedrock:InvokeModel`)은 **이미 승인돼
동작 중**이다(권한요청서 §3 = 로컬 Docker `operations-api` 에서 `apac.amazon.nova-micro-v1:0` 호출 성공).
지금 그게 **IAM 사용자 액세스 키**에 붙어 있고 **EC2 롤에는 없을 뿐**이다(Terraform 의 Bedrock 은
`mp-pipeline-bedrock` **IRSA = EKS 파드용** 하나). ⇒ 요청 문구 = *"장기 키를 없애기 위해 이미 승인된
InvokeModel 을 대시보드 EC2 인스턴스 프로파일에도 붙여달라."*
🔴 **ARN 은 2개**여야 한다 — `apac.` 는 **교차리전 추론 프로파일**이라 **프로파일 ARN + 기반 모델 ARN**
둘 다 허용해야 통과한다(하나면 `AccessDeniedException`).

### ⑥ 한 줄씩 추가할 것 (3건)

- **DNS** — `*.mealbong.cloud` 가 회색으로 `192.168.0.15`(사설 LAN)를 가리킨다. ⇒ `ops.`/`finops.` **명시
  레코드를 만들기 전에** 접속 시험하면 `NXDOMAIN` 이 아니라 **사설 IP 로 간다**(LAN 안이면 404, 밖이면 타임아웃).
  *"전파가 안 됐나"* 로 오진하기 딱 좋다. 명시 레코드를 만들면 와일드카드보다 우선한다.
- **oauth2-proxy 쿠키 도메인을 `.mealbong.cloud` 로 잡지 말 것** — 운영자 세션 쿠키가
  **`app.mealbong.cloud`(일반 사용자 앱)** 까지 전송된다. 도메인별 **호스트-온리 쿠키**로.
- **TLS 발급 방식** — *"Nginx 에 Let's Encrypt"* 한 줄로는 부족하다. HTTP-01 이면 **80 이 상시 필요**하고,
  DNS-01 이면 온프렘의 `*.mealbong.cloud` 발급과 **경합**한다. **갱신 주체와 갱신 실패 알림**도 정해야 한다
  — 인증서 만료는 90일 뒤에 조용히 온다.

---

## §0-B 🔴 구 정본에서 아직 승계되지 않은 확정 결정 (5건)

`docs/aws-dashboard-ec2-deployment-plan.md` 에만 있다. **옮기기 전에는 그 문서를 지우면 안 된다.**

① **학원 PG allowlist 는 교체가 아니라 추가다.** 지금 온프렘 공인 IP 가 등록돼 있고 온프렘은 이관 후에도
   산다(C-72·C-83) ⇒ EC2 EIP 를 **추가**해 **둘 다** 등록된 상태여야 한다. 온프렘 IP 를 빼면 지금 도는
   `mp-operations` 가 죽는다. ⚠️ 어느 층에서 막는지 미확인 — `pg_hba` 면 **명확한 에러**, 앞단 방화벽이면
   **타임아웃**이라 진단이 어렵다(포트가 비표준이라 앞단 가능성이 높다).
② **MongoDB 는 범위 밖**(2026-08-13 확정) — 라이브 클러스터에 워크로드 0개·ns 없음·PVC 없음.
   담당자 **개인 로컬 설치물**이라 프로젝트 인프라가 아니다. ⇒ B-7·B-10·B-12 의 MongoDB 전환·검증·롤백
   절차는 **집행 대상이 아니다.** 처음부터 학원 PG 를 쓴다.
③ **Cognito 기각 근거와 로그인 흐름** — 안 적어두면 *"Cognito 쓰면 되지 않나"* 가 다시 나온다.
④ **회색(DNS 전용)을 고른 근거 3가지** — ⓐ 인증이 오리진에 있어 엣지 프록시가 인증에 기여하지 않는다
   ⓑ 주황이면 EIP 직타로 우회 가능 → SG 를 CF IP 로 못박는 유지 부담 ⓒ `app.mealbong.cloud` 와 같은 패턴.
⑤ **NodePort 선택 근거와 가역성** — *"아프면 내부 NLB(`target-type: ip`)로 올린다. 반대는 불가"* +
   🔴 **상시 `kubectl port-forward` 로 대체 금지**(온프렘에서 감사로그 보존창을 30일 → **52.62시간**으로
   붕괴시킨 주범 · `1-25`. AWS 는 audit→CloudWatch 가 이미 월 ~$59 라 *"무료"* 경로가 더 비싸질 수 있다).

---

> 작성 2026-08-14 · 검토자: 팀장
> 범위: **Operations AI**(이상징후 탐지, 담당: 나)와 **FinOps**(비용 대시보드, 담당: 팀원)를
> **같은 EC2 한 대**에 Docker Compose로 같이 올린다. Nginx·인증·서브넷 등 공용 부분은 하나로
> 합치고, 각자 백엔드가 붙는 데이터 소스(Operations=Bedrock/외부PG/Loki·Tempo,
> FinOps=Kubecost/GCP/CUR)는 팀별 섹션에 따로 정리했다.
>
> 🔴 **아키텍처는 x86_64로 통일한다.** FinOps 초안은 arm64(Graviton)를 검토했으나, 체크리스트
> C-84가 이 EC2를 x86_64로 이미 확정했고(이미지 arm64 가용성 미확인 리스크 회피), 한 EC2에
> 아키텍처를 둘로 섞을 수 없어 x86_64로 맞춘다.
> 🔴 **인증도 공용 oauth2-proxy 하나로 통일한다.** FinOps 초안은 무인증을 검토했으나, 같은
> Nginx·같은 EC2에 두 대시보드가 있으므로 인증도 하나로 묶는 게 맞다.

---

## 0. 공용 배치 — 이 EC2 한 대에 전부 올라간다

```
운영자 브라우저
   │ HTTPS 443
   ▼
Cloudflare (회색 · DNS 전용, 프록시 없음)
   ├─ ops.mealbong.cloud     → EC2 Elastic IP
   └─ finops.mealbong.cloud  → EC2 Elastic IP
        │
        ▼
VPC-A (서비스 VPC, 10.10.0.0/16, AZ 2개)
└─ Public Subnet  AZ-a(10.10.0.0/24) 확정 — NAT Gateway와 같은 AZ, AZ간 전송비 회피
   └─ EC2 (t3.medium, x86_64, Elastic IP, Docker Compose)
      ├─ Nginx (공용, 도메인별 server 블록)
      │   ├─ ops.mealbong.cloud
      │   │   ├─ operations 정적 대시보드
      │   │   └─ /ops-api/*    → operations-api:8011
      │   ├─ finops.mealbong.cloud
      │   │   ├─ finops 정적 대시보드
      │   │   └─ /api/*        → finops-api:8000
      │   └─ /oauth2/*         → oauth2-proxy:4180  (양쪽 도메인 공용)
      ├─ oauth2-proxy (Google OAuth + 이메일 allowlist, 공용)
      ├─ operations-api  (FastAPI, 8011)  ── 담당: 나
      ├─ finops-api      (FastAPI, 8000)  ── 담당: 팀원
      └─ kubecost-proxy  (내부 전용, 31090) ── FinOps 전용
              │
              ├──▶ 같은 VPC-A / EKS 노드 서브넷(Private)
              │      Prometheus / Loki·Tempo(Operations) · Kubecost(FinOps)
              ├──▶ 외부 PostgreSQL (AWS 밖, 팀 공용 서버, 211.46.52.152)
              │      operations 스키마 / finops 스키마
              ├──▶ Amazon Bedrock Runtime (Operations, RCA 호출)
              └──▶ GCP BigQuery via WIF (FinOps, 비용 조회)
```

브라우저는 PostgreSQL·Prometheus·Loki·Tempo·Kubecost·Bedrock·GCP에 직접 안 붙는다. 전부 각자
`/ops-api` 또는 `/api`를 거쳐 해당 FastAPI로만 나간다.

**EC2 하나·Nginx 하나**로 두 대시보드를 서빙하고, 백엔드 컨테이너만 팀별로 분리한다. 한쪽
컨테이너를 재배포해도 다른 쪽은 안 건드린다(`docker compose up -d --no-deps <서비스>`).

---

## 1. 공용 — 인증 (oauth2-proxy, Google)

- `Nginx auth_request → oauth2-proxy → Google OAuth → 이메일 allowlist` — `ops.`/`finops.`
  **양쪽 도메인 공용**으로 하나의 `oauth2-proxy` 컨테이너를 쓴다.
- 🔴 **`mp-account`(앱 서비스) JWT를 재사용하지 않는다** — 대시보드 로그인이 EKS를 지나면,
  EKS가 죽었을 때 그걸 알려줘야 할 대시보드에 로그인을 못 하는 순환의존이 생긴다. 이상징후
  대시보드의 존재 이유와 정면 충돌.
- Cognito·CF Access는 미채택 — 인증을 엣지가 아니라 오리진(EC2)에서 직접 하므로 Cloudflare
  프록시를 켤 이유가 없다(아래 §2).
- Client ID/Secret은 SSM/Secrets Manager에서 주입, Git에 안 넣음.

## 2. 공용 — 외부 노출 (Nginx + Cloudflare)

- `ops.mealbong.cloud`, `finops.mealbong.cloud` 둘 다 EC2 Elastic IP로 연결하고 **Cloudflare
  프록시는 끈다**(회색, DNS만). 이유: 인증이 오리진에 있어 프록시가 인증에 기여하지 않고,
  프록시를 켜면 SG를 Cloudflare IP 대역으로 계속 관리해야 하는 부담만 생긴다.
- Nginx가 TLS를 직접 종단(Let's Encrypt). 도메인별 `server` 블록으로 분리하되 컨테이너는 하나.
- `8011`(operations-api), `8000`(finops-api), `4180`(oauth2-proxy) 포트 자체는 외부에 노출 안
  하고 Docker 내부 네트워크에서만 접근.

## 3. 공용 — EC2 스펙과 서브넷

| 항목 | 값 |
|---|---|
| 인스턴스 | `t3.medium` |
| 아키텍처 | **x86_64**(Graviton 아님 — 이미지 arm64 가용성 미확인 리스크를 월 $5~8로 회피) |
| 위치 | VPC-A 공개 서브넷 AZ-a(`10.10.0.0/24`) 확정 |
| 고정 IP | Elastic IP |
| 태그 | `Component=finops-dashboard` 등 팀 규칙(SSM 세션 접속 권한이 태그 기준으로 갈림) |
| 관리 | SSM Session Manager(SSH 아님) + IMDSv2 강제 |

## 4. 공용 — 배포 방식

- EC2 하나에 Docker Compose로 `nginx` + `oauth2-proxy` + `operations-api` + `finops-api` +
  `kubecost-proxy`를 띄운다. 공용 Docker network(`dashboard-net`)로 묶는다.
- 이미지는 ECR에서 Git SHA 태그로 pull(`:latest` 안 씀). 각자 레포/이미지는 팀별로 따로
  관리(`mp-operations-api`, `mp-dashboard-finops` 등).
- 한쪽만 바꿀 땐 그 컨테이너만 재기동 — 다른 팀 서비스에 영향 없음.

## 5. 공용 — Security Group

| 출발 | 목적지 | 포트 | 용도 |
| --- | --- | --- | --- |
| Cloudflare | EC2 Nginx | 80, 443 | 두 대시보드 HTTPS |
| EKS Alertmanager | EC2 private IP / operations-api | 8011 | Alert webhook (Operations) |
| operations-api / finops-api | 학원 PostgreSQL | 15432 | 각자 스키마 저장·조회 |
| operations-api | 노드 사설 IP:NodePort | NodePort | Prometheus·Loki·Tempo 조회 |
| kubecost-proxy | 노드 사설 IP:NodePort(`30090`) | NodePort | Kubecost Allocation API |
| operations-api | Bedrock Runtime | 443(NAT 경유) | RCA 호출 |
| finops-api | GCP API | 443 | WIF·BigQuery 조회 |

외부 인터넷에는 Nginx의 80/443만 연다. 나머지 전부(백엔드 포트·DB 포트·NodePort)는 EC2 SG
안에서만 도달 가능.

## 6. 공용 — 우리가 정한 것 vs 팀장님 확인이 필요한 것

### 6.1 우리가 정해서 그대로 진행하면 되는 것 (요청 아님, 실행만 하면 됨)

| # | 항목 | 방식 |
|---|---|---|
| A | EC2 스펙·배치 | `t3.medium`, x86_64, VPC-A AZ-a 공개 서브넷(`10.10.0.0/24`), Elastic IP — §0/§3에 확정 |
| B | EC2 Instance Profile에 필요한 권한 목록 | Bedrock(이미 발급됨) + GCP WIF(FinOps 담당) + 필요 시 AWS Cost API. 우리가 목록을 정리해서 인프라 담당에게 **"이 권한들을 이 Instance Profile에 붙여달라"고 전달**하면 됨 — 권한 내용 자체는 우리가 정하는 것 |
| C | 학원(더존비즈온 KDT) PG 접속 — EC2용 netpol/egress 규칙 추가 | 실측 확인됨: 온프렘 클러스터 쪽 `ipBlock 211.46.52.152/32:15432` egress netpol이 우리가 관리하는 규칙이고 지금 실제로 이걸로 접속 중이다. EC2용도 같은 방식으로 **우리가 추가하면 됨** |

### 6.2 팀장님(또는 다른 담당자) 확인이 실제로 필요한 것

다른 사람이 관리하는 리소스라 우리가 결정할 수 없는 것만 남긴다.

| # | 확인 대상 | 왜 우리가 못 정하나 |
|---|---|---|
| 1 | 노드 SG에 EC2 SG를 허용하는 규칙 추가(Prometheus·Loki·Tempo·Kubecost NodePort 공통 전제) | EKS 노드 SG는 인프라 담당의 Terraform 관리 대상 — 우리가 목록(B)을 정해도 실제 반영은 그쪽 apply가 필요 |
| 2 | EC2 인스턴스 자체 생성(Terraform apply) | 스펙(A)은 우리가 정했지만, 실제 생성 실행은 인프라 담당 몫 |
| 3 | 학원 PG 서버 자체의 인바운드 방화벽 유무 | (C)는 우리 쪽 netpol이라 우리가 처리하지만, `211.46.52.152` 서버 자체에 별도 방화벽이 더 있는지는 미확인 — 있다면 더존비즈온 쪽 요청 필요 |
| 4 | 학원 PG의 **교육기간 한정 존속 여부** | 교육 종료 시 폐기되는 임시 자원이라, 이관 계획의 영구 데이터 저장소로 그대로 못박아도 되는지는 팀 차원의 판단 필요(우리 혼자 정할 사안이 아님) |

---

## Part A. Operations AI 전용 — 담당: 나

### A-1. Metric — Prometheus 연결

**방식: NodePort + 노드 사설 IP**로 붙인다. LB는 안 만든다.

- EKS 노드와 EC2가 같은 VPC라 사설 IP로 직접 라우팅이 된다. 다만 ClusterIP(`10.30.0.0/16`)는
  VPC 밖 가상 주소라 EC2에서 못 찾아가고, `*.svc.cluster.local`도 클러스터 안 CoreDNS만 풀어주는
  이름이라 EC2에서는 안 먹힌다 — 그래서 "노드 실제 IP + NodePort 포트번호" 조합으로 붙인다.
- Prometheus가 뜬 노드 IP를 확인하고, 그 IP의 NodePort로 `OPERATIONS_PROMETHEUS_URL`을 설정한다.
- 노드가 여러 대면 Nginx나 API 쪽에서 노드 IP 여러 개를 두고 헬스체크하는 형태로, 노드 1대가
  바뀌어도 안 끊기게 한다.
- **코드 작업**: 이미 `config.py`에 `operations_prometheus_url` 환경변수가 있어서 이 값만
  바꾸면 된다. 코드 수정 불필요, EC2 배포 시 `.env`에 `노드IP:포트`만 넣으면 끝.

### A-2. Log/Trace — Loki·Tempo 연결

**방식은 Prometheus와 동일하게 시도**(NodePort + 노드 사설 IP)하지만, ⚠️ **Prometheus·kubecost와
전제 자체가 다르다** — 그대로 안전하다고 보면 안 된다.

- Prometheus·kubecost가 노드 IP로 안정적으로 붙는 이유는 "PVC(디스크)가 있어서 **MNG 고정
  노드**에 묶여 있고, Karpenter가 그 노드를 함부로 재배치 못 한다"는 전제 때문이다.
- **Loki·Tempo는 이 전제가 확인된 적이 없다.** 지금 라이브 클러스터에 아예 NodePort로도 안
  열려 있는 상태라, 이 서비스들이 실제로 어떤 노드 그룹에 뜰지, 고정 노드인지 Karpenter가
  자유롭게 옮기는 노드인지부터 확정이 안 된 상태다. Karpenter 노드라면 노드가 자주 뜨고
  사라져서 "노드 IP:포트"가 수시로 바뀌고, NodePort 방식이 Prometheus만큼 안정적이지 않을 수
  있다.
- **선행 확인**: `kubectl get svc -n observability`로 Loki·Tempo Service가 NodePort 타입인지,
  아니면 ClusterIP뿐이라 새로 NodePort를 열어야 하는지 확인한다. 이때 **어느 노드 그룹(MNG
  고정 노드 vs Karpenter)에 배치할지도 같이 정해야 한다** — 고정 노드가 아니면 NodePort 대신
  Internal NLB(고정 DNS)로 바로 가는 게 나을 수 있다.
- **코드는 이미 다 있다** — `loki_evidence.py`/`tempo_evidence.py`가 구현·배선 완료 상태고
  `operations_loki_evidence_enabled`/`operations_tempo_evidence_enabled` 플래그만 꺼져 있다.
  NodePort가 뚫리면 URL 넣고 플래그만 켜면 된다. **코드 작업 불필요, 인프라(NodePort 개방)만
  필요.**

### A-3. 외부 PostgreSQL 연결

- 접속 대상: `211.46.52.152:15432`, `operations` 스키마.
  🔴 **이 서버는 우리 인프라가 아니다** — 더존비즈온이 KDT 교육과정용으로 내준 외부 자원이고
  교육 종료 시 폐기 대상이다. 접속은 팀별 계정(`team1`~`team5`)으로 하되, **접근 통제 자체는
  IP 기반**이다(실측: 온프렘 클러스터의 egress netpol이 `ipBlock 211.46.52.152/32:15432`로
  걸려 있고 이걸로 지금 실제 접속 중). EC2용 netpol/규칙 추가는 우리 쪽에서 하면 되지만,
  서버 자체에 별도 인바운드 방화벽이 더 있는지는 미확인 — 있다면 더존비즈온 쪽 요청이
  필요하다(§6-3).
- **코드 작업 불필요** — `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD` 전부 이미 환경변수화돼 있다
  (`config.py`). EC2의 `.env`에 값만 넣으면 된다.

### A-4. Amazon Bedrock 연결

- 지금 모델: `apac.amazon.nova-micro-v1:0` — 🔴 **확정이 아니라 비용 때문에 먼저 시험하는
  모델이다.** 응답 품질이 부족하면 Claude 계열 등 다른 모델로 바꿀 예정이고, `config.py`의
  `BEDROCK_MODEL_ID` 문자열 하나만 바꾸면 되는 구조라 전환 비용은 낮다.
- 인증은 **EC2 Instance Profile**로 한다. Bedrock 권한은 이미 발급받은 상태로 알고 있음.
- **코드 작업 불필요** — `boto3`가 Instance Profile을 자동으로 찾는 표준 방식이라
  `build_bedrock_rca()`(이미 구현·PR #668 완료) 코드는 그대로 쓴다.

### A-5. Operations 전용 확인 필요

| # | 확인 대상 | 왜 필요한가 |
|---|---|---|
| 1 | EKS 클러스터의 Prometheus NodePort 번호 | `OPERATIONS_PROMETHEUS_URL` 값을 정하는 데 필요 |
| 2 | Loki/Tempo가 NodePort로 열려 있는지 + 노드 그룹 | A-2 참고 |
| 3 | EC2 Instance Profile에 Bedrock 권한이 실제로 붙는지 | 배포 시 확인 |

---

## Part B. FinOps 전용 — 담당: 팀원

### B-1. 데이터별 수집 경로

| 화면 데이터 | 실제 원본 | 연결 방식 |
|---|---|---|
| AWS 실제 비용 | CUR S3 + Athena | Instance Profile로 Athena 실행·결과 조회 |
| AWS 빠른 비용 조회 | Cost Explorer | `ce:GetCostAndUsage` |
| AWS 리소스 사양 | 서비스별 Resource API | EC2/EBS/EKS/ECR/ElastiCache `Describe/List` |
| AWS 사용량 | CloudWatch | Metric 조회 |
| EKS Namespace·Workload 비용 | Kubecost Allocation API | MNG 노드 Private IP의 NodePort |
| GCP 비용 | BigQuery Billing Export | AWS 기반 GCP WIF |
| 설정·저장 데이터 | 학원 제공 PostgreSQL | `finops` 스키마, 15432 |

비용과 사양을 하나의 계산으로 섞지 않는다 — 금액은 CUR/Athena 실측 우선, 사양은 Describe API,
성능·사용량은 CloudWatch, EKS 내부 배분은 Kubecost로 역할을 분리.

### B-2. Kubecost 연결

**채택 방식: NodePort + EC2 내부 proxy + 15분 캐시**

Kubecost는 EKS에 이미 설치된 Service를 사용한다. FinOps EC2에서 같은 VPC의 MNG 노드 Private IP와
Kubecost NodePort로 연결하며, NLB·ALB·Kubernetes API Proxy는 사용하지 않는다.

```text
FinOps FastAPI
  → Docker 내부 kubecost-proxy
  → EKS MNG 노드 Private IP 여러 개:30090
  → Kubecost NodePort Service
  → Ready Kubecost Pod
```

Kubecost는 MNG 고정 노드에서 운영되고 Karpenter 임시 노드에 배치하지 않는다. NodePort는 각
MNG 노드의 동일한 포트에서 Kubecost Service의 Ready Endpoint로 요청을 전달한다.

#### B-2.1 네트워크와 Security Group

1. 현재 Kubecost Service의 실제 NodePort를 확인한다. 계획 기준 포트는 `30090`이다.
2. EKS Node Security Group 인바운드에는 `FinOpsDashboardSG → TCP 30090`만 허용한다.
3. 인터넷 CIDR, 공개 IP와 VPC 전체 CIDR에는 `30090`을 허용하지 않는다.
4. FinOps EC2 Security Group 아웃바운드는 EKS Node Security Group의 TCP `30090`을 허용한다.
5. Kubecost Service를 public LoadBalancer 또는 공개 Ingress로 만들지 않는다.

```text
FinOpsDashboardSG
  → TCP 30090
  → EKS MNG Node Security Group
```

#### B-2.2 내부 kubecost-proxy

기존 단일 대상 `socat` 방식은 노드 한 대의 IP만 사용하므로 최종 구성에서 사용하지 않는다.
외부 포트를 열지 않는 전용 NGINX proxy 컨테이너에 현재 MNG 노드 여러 대를 upstream으로 등록한다.

```nginx
upstream kubecost_nodes {
    server <mng-node-private-ip-a>:30090 max_fails=2 fail_timeout=10s;
    server <mng-node-private-ip-b>:30090 max_fails=2 fail_timeout=10s;
}

server {
    listen 31090;

    location / {
        proxy_pass http://kubecost_nodes;
        proxy_connect_timeout 3s;
        proxy_read_timeout 60s;
        proxy_next_upstream error timeout http_502 http_503 http_504;
    }
}
```

- `kubecost-proxy:31090`은 Docker 내부 네트워크에만 노출한다.
- 호스트 포트와 EC2 Security Group 인바운드에는 `31090`을 열지 않는다.
- FastAPI는 `KUBECOST_URL=http://kubecost-proxy:31090`을 사용한다.
- 이 proxy는 Kubecost 연결 전용이며 대시보드 외부 NGINX 경로로 공개하지 않는다.

#### B-2.3 MNG 노드 IP 자동 갱신

MNG 노드는 고정 계층이지만 업그레이드·장애 교체 시 Private IP가 바뀔 수 있다. 노드 IP를
Git·Docker image·일반 `.env`에 고정하지 않는다.

EC2 Instance Profile의 기존 `ec2:DescribeInstances` 권한으로 다음 조건에 맞는 실행 중 노드를
조회한다.

```text
EKS Cluster 태그 = mp-eks
Managed Node Group 태그 = 대상 MNG
Instance State = running
PrivateIpAddress 존재
```

갱신 절차:

```text
현재 MNG 노드 Private IP 조회
→ upstream 설정 임시 파일 생성
→ 설정 문법 검사
→ 기존 설정과 다를 때만 원자적으로 교체
→ kubecost-proxy NGINX reload
```

- EC2 시작과 Docker 배포 시 한 번 실행한다.
- 이후 5분마다 노드 목록을 확인한다.
- 조회 결과가 0개이면 기존 정상 설정을 지우지 않는다.
- 새 설정에 최소 한 개 이상의 노드가 있을 때만 반영한다.

#### B-2.4 백엔드 호출과 캐시

환경값 예시:

```dotenv
KUBECOST_URL=http://kubecost-proxy:31090
KUBECOST_CACHE_TTL_SECONDS=900
KUBECOST_NODEPORT=30090
EKS_CLUSTER_NAME=mp-eks
```

검증 API 예시:

```text
/model/allocation?window=1d&aggregate=namespace
/model/allocation?window=7d&aggregate=deployment
```

- 동일한 기간·Cluster·Namespace·Workload 조건은 15분 동안 캐시한다.
- 연결 실패는 FastAPI 로그에 원인만 기록한다.
- 별도의 CloudWatch Alarm·Alertmanager·Prometheus 알람은 구성하지 않는다.
- Kubecost 연결 실패가 AWS·GCP 비용 조회를 중단시키지 않도록 데이터 소스별로 오류를 분리한다.
- 마지막 정상 캐시가 남아 있으면 캐시 데이터와 갱신 시각을 반환한다.

#### B-2.5 실제 값 확인

EKS/Kubecost 담당자가 다음 값을 전달한다.

```bash
kubectl get nodes -o wide
kubectl get service -A | grep -i kubecost
kubectl -n <namespace> get service <service-name> -o yaml
```

확인할 값:

- Kubecost Namespace
- Kubecost Service 이름
- Service Port와 NodePort
- Kubecost API 경로
- MNG 식별용 Cluster·Node Group 태그

#### B-2.6 선택하지 않은 방식

| 방식 | 제외 이유 |
|---|---|
| Kubernetes API Proxy | 앱의 상시 비용 조회 경로로 사용하지 않으며 EKS Access Entry·RBAC를 추가하지 않음 |
| Internal NLB | 안정적인 DNS를 제공하지만 현재 규모에서는 추가 비용이 불필요함 |
| Internal ALB/Ingress | 여러 HTTP 서비스 라우팅이 없고 내부 Kubecost를 외부 진입점과 결합하지 않음 |
| DB 주기 적재 | 학원 제공 PostgreSQL Schema를 임의로 추가할 수 없음 |
| `kubectl port-forward` | 세션 기반이므로 FinOps의 상시 조회 경로로 사용하지 않음 |

NodePort 운영 부담이 실제로 커지는 경우에만 Internal NLB로 전환한다. 현재 NodePort 구성을
먼저 제거한 뒤 NLB로 바꾸지 말고, NLB 연결을 검증한 후 proxy upstream을 전환한다.

### B-3. AWS 인증과 권한

AWS 배포 후에는 IAM Roles Anywhere 인증서와 개인키 파일을 사용하지 않는다.

1. `FinOpsDashboardReadOnlyRole`을 EC2 Instance Profile에 연결한다.
2. boto3와 AWS SDK에는 Access Key·Secret Key·`AWS_PROFILE`을 설정하지 않는다.
3. SDK가 IMDSv2에서 임시 자격증명을 자동으로 받게 한다.
4. 현재 Role의 기존 정책과 `finops-dashboard-resource-read` 정책은 그대로 사용한다.
5. `rolesanywhere:*` 조회 권한은 EC2 전환 후 기능상 필요하지 않으므로 다음 정책 정리 때 제거한다.

현재 Docker Compose에서 제거할 항목:

```text
AWS_PROFILE
AWS_CONFIG_FILE
AWS_SDK_LOAD_CONFIG
AWS_EC2_METADATA_DISABLED=true
/etc/finops/aws 인증서 mount
aws_signing_helper mount
Roles Anywhere용 aws-config mount
```

EC2 환경에서는 다음처럼 둔다.

```dotenv
AWS_REGION=ap-northeast-2
AWS_EC2_METADATA_DISABLED=false
```

🔴 **공용 Instance Profile에 합칠지, Operations의 Bedrock 권한과 분리할지는 §6의 확인 필요
목록에서 팀장님과 확정한다.**

### B-4. Secrets Manager와 설정

- 비밀값은 `mp/prod/dashboard/finops/*` 경로만 사용한다.
- `.env`, Git, Docker image와 애플리케이션 로그에 비밀번호·인증서를 저장하지 않는다.
- 일반 설정은 SSM Parameter Store `/mp/dashboard/finops/*`에 둔다.

| 종류 | 저장 위치 |
|---|---|
| PostgreSQL 비밀번호·CA | Secrets Manager `mp/prod/dashboard/finops/*` |
| GCP WIF 설정 | Secrets Manager 또는 권한 제한 파일 |
| Kubecost NodePort·MNG 노드 검색 조건 | SSM `/mp/dashboard/finops/*` |
| AWS Region·캐시 TTL | SSM `/mp/dashboard/finops/*` |

EC2 부팅 또는 배포 스크립트가 값을 `/opt/finops/runtime/`의 권한 제한 파일로 가져오고, Docker
Compose에 읽기 전용으로 전달한다.

### B-5. FinOps 전용 Security Group

| 방향 | 출발지/목적지 | 포트 | 목적 |
|---|---|---:|---|
| Inbound | Cloudflare IP 또는 승인된 운영자 CIDR | 443 | 대시보드 HTTPS |
| Inbound | 외부 전체 | 22 | **허용하지 않음** |
| Outbound | 외부 PostgreSQL endpoint | 5432 | TLS DB 연결 |
| Outbound | EKS MNG Node Security Group/private IP | 30090 | Kubecost NodePort 조회 |
| Outbound | AWS API endpoint | 443 | CUR·Athena·CE·CloudWatch·Resource API |
| Outbound | GCP API | 443 | WIF·BigQuery 조회 |

`8000`, `27017`과 Kubecost NodePort는 인터넷에 공개하지 않는다. 서버 관리는 SSH 대신 SSM
Session Manager를 사용한다.

### B-6. FinOps 이미지와 ECR

| 항목 | 값 |
|---|---|
| 아키텍처 | 🔴 **x86_64로 통일**(원안 arm64에서 조정 — 공용 §3 참고) |
| 디스크 | gp3, Docker image·로그 여유 포함 |
| 태그 | `Component=finops-dashboard`, 프로젝트·환경·소유자 태그 |
| 관리 | SSM Agent + Instance Profile + IMDSv2 강제 |

ECR Repository는 `mealplanning/mp-dashboard-finops`를 사용한다. 아직 생성 전이므로 담당자가
Terraform으로 만든 뒤 배포한다.

이미지는 x86_64로 빌드한다(원안의 `--platform linux/arm64`를 아래처럼 조정):

```bash
docker buildx build \
  --platform linux/amd64 \
  -t 689192361171.dkr.ecr.ap-northeast-2.amazonaws.com/mealplanning/mp-dashboard-finops:<sha> \
  --push .
```

태그는 `latest`만 사용하지 않고 Git SHA를 배포 기준으로 사용한다.

### B-7. FinOps Docker Compose 구성

초기 AWS 구성에 포함할 서비스:

```text
nginx (공용)
finops-api
kubecost-proxy
```

- 프론트 정적 파일은 NGINX image에 포함한다.
- 기존 `mongodb`는 PostgreSQL 전환과 데이터 검증이 끝난 뒤 제거한다.
- `kubecost-proxy`는 외부 포트를 열지 않는 내부 전용 NGINX proxy로 실행한다.
- 인증(oauth2-proxy)은 공용 §1 참고 — Operations와 공유.

### B-8. FinOps 이관 순서

1. 담당자가 공개 서브넷에 EC2와 EIP를 만들고 `Component=finops-dashboard` 태그를 적용한다.
2. `FinOpsDashboardReadOnlyRole` Instance Profile, SSM, IMDSv2와 Security Group을 적용한다.
3. ECR `mealplanning/mp-dashboard-finops`를 생성한다.
4. 현재 소스에서 Roles Anywhere mount와 프로필 설정을 제거하고 Instance Profile 방식으로
   검증한다.
5. `linux/amd64` 이미지를 빌드해 ECR에 Git SHA 태그로 push한다.
6. MNG 노드의 Kubecost NodePort와 SG 경로를 적용하고 내부 `kubecost-proxy`를 통해 Allocation
   API를 호출한다.
7. Secrets Manager·SSM에서 PostgreSQL, GCP WIF, Kubecost 설정을 주입한다.
8. EC2에서 NGINX와 FastAPI Compose를 실행한다.
9. 먼저 EIP 또는 임시 호스트로 `/api/health`와 각 데이터 소스를 검증한다.
10. AWS CUR/Athena 실측 비용과 Cost Explorer 합계를 날짜별로 비교한다.
11. Kubecost Namespace·Workload 합계와 Kubecost UI를 비교한다.
12. GCP BigQuery와 PostgreSQL 연결을 검증한다.
13. `finops.mealbong.cloud`를 EIP origin으로 전환하고 HTTPS를 검증한다.
14. 3~7일간 기존 대시보드를 롤백 가능하게 유지한다.
15. 승인 후 기존 Kubernetes 대시보드와 MongoDB를 정리한다.

### B-9. FinOps 완료 기준

| 검증 | 기대 결과 |
|---|---|
| EC2 위치 | VPC-A 공개 서브넷에 있고 EIP 연결 |
| EC2 태그 | `Component=finops-dashboard` 존재 |
| 공개 포트 | 443만 공개 |
| SSM | `jungeun` 사용자가 해당 EC2에만 접속 가능 |
| AWS 인증 | 컨테이너에서 Instance Profile ARN 확인 |
| AWS 실제 비용 | CUR/Athena 또는 Cost Explorer 결과 표시 |
| AWS 사양 | EC2·EBS·EKS·ECR·ElastiCache 상세 표시 |
| Kubecost | Namespace·Workload 비용과 효율 표시 |
| GCP | WIF로 BigQuery 조회 성공 |
| PostgreSQL | 학원 제공 조건으로 TLS 연결 성공 |
| 비밀값 | Git·image·`.env`·로그에 없음 |
| 아키텍처 | 실행 image가 `linux/amd64`(x86_64) |

### B-10. FinOps 롤백

- 애플리케이션 장애: 직전 정상 Git SHA image로 Compose를 되돌린다.
- AWS 인증 장애: Instance Profile 연결과 IMDSv2를 수정하며 Access Key 또는 인증서 파일을
  임시로 넣지 않는다.
- Kubecost 장애: 대시보드의 EKS 상세 영역만 오류 상태로 분리하고 AWS·GCP 비용 화면은 계속
  제공한다.
- PostgreSQL 장애: 전환 기간에는 기존 MongoDB 기반 API 또는 기존 대시보드로 되돌린다.
- DNS 장애: 기존 origin으로 되돌리고 EC2의 8000 포트를 임시 공개하지 않는다.

### B-11. FinOps 담당 구분

| 담당 | 작업 |
|---|---|
| AWS 인프라 담당 | EC2·EIP·SG·Instance Profile·ECR·MNG NodePort 접근 규칙·DNS |
| FinOps 담당 | x86_64 image·Compose·FastAPI 데이터 연결·화면·검증 |
| 학원/DB 담당 | PostgreSQL endpoint·schema·account·TLS·allowlist |
| EKS/Kubecost 담당 | Kubecost NodePort·Service 이름·Port·API 경로·데이터 대조 |

### B-12. FinOps 전용 확인 필요

| # | 확인 대상 | 왜 필요한가 |
|---|---|---|
| 1 | Kubecost 실제 NodePort 번호(계획 기준 `30090`) | `KUBECOST_URL` 값을 정하는 데 필요 |
| 2 | ECR `mealplanning/mp-dashboard-finops` 리포지토리 생성 여부 | 아직 생성 전 |
| 3 | `FinOpsDashboardReadOnlyRole` 정책의 죽은 S3 문장(`mealplanning-*` 버킷 0개, 실제는 `mp-*`) | 정리 필요 |
| 4 | MongoDB → PostgreSQL 전환·검증 완료 시점 | 완료 전까지 기존 MongoDB 기반 API 롤백 경로 유지 |

---

## 7. 지금 상태 vs 이관 후 요약

| | 지금(로컬 검증) | 이관 후(EC2, 공용) |
|---|---|---|
| Prometheus(Operations) | `ssh` + 원격 `kubectl port-forward` | 같은 VPC 사설 IP:NodePort 직접 |
| Loki/Tempo(Operations) | 꺼져 있음(플래그 false) | NodePort 열리면 그대로 켜기 |
| Kubecost(FinOps) | 로컬 미검증 | `kubecost-proxy` 경유 NodePort, 15분 캐시 |
| PostgreSQL(양쪽) | 로컬에서 `.env`로 직접 접속 | 같은 서버, EC2 IP만 allowlist 추가 |
| Bedrock 인증(Operations) | `.env`에 Access Key 직접(임시) | EC2 Instance Profile(장기 키 없음) |
| GCP 인증(FinOps) | 로컬 미검증 | EC2 Instance Profile → GCP WIF |
| 인증(공용) | 없음(로컬 전용) | oauth2-proxy(Google) + allowlist, 양쪽 도메인 공용 |
| 공개 여부 | 없음 | `https://ops.mealbong.cloud`, `https://finops.mealbong.cloud` |
