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
| C-12 | **MM2 복제 정책 = `DefaultReplicationPolicy` · 소스 별칭 `onprem`** (Identity 미채택) | 2026-08-07 | 아래 (가-1 해소) |
| C-13 | **MM2 = 정방향 1개만 · AWS 배치 · replicas 1** · **역방향은 MM2 말고 크로스터널 consume** | 2026-08-07 | 아래 (가-3 해소 → **D4-a 완결**) |
| C-14 | **Redis = ElastiCache for Valkey `cache.t4g.micro` Multi-AZ 2노드** · **온프렘은 단일 Redis 로 단순화**(Sentinel 제거) | 2026-08-09 | 아래 (D4-b 해소) |
| C-15 | **PG = CNPG 유지 · ES = ECK 유지** (RDS·Aurora·OpenSearch Service 전부 미채택) | 2026-08-09 | 아래 (D4-d 해소 → **D4 전체 완결**) |
| C-16 | **스토리지 총량 = PVC 352 → 125 GiB** · **노드 EBS 60Gi × N 을 산정에 편입**(종전 계획서에서 통째로 누락) | 2026-08-09 | 아래 (D5 ①) |
| C-17 | **EFS 미도입** — 전량 EBS + S3 | 2026-08-09 | 아래 (D5 ①) |
| C-18 | **MinIO 삭제 → S3** · 🔴 **온사이트 덤프 목적지는 barman 과 다른 버킷/계정**(선행) | 2026-08-09 | 아래 (D5 ①) |
| C-19 | **kubecost = 클러스터 밖 EC2 분리** (디스크 20 GiB · agent 만 클러스터 잔류) | 2026-08-09 | 아래 (D5 ①) |
| C-20 | **PVC 소거 3종** — `ranker.pkl`(이미지에 굽기) · pipeline 2종(온프렘 잔류) · Redis(볼륨 0, C-14 귀결) | 2026-08-09 | 아래 (D5 ①) |
| C-21 | 🔴 **정족수 배치 = AZ 당 1개** — ES master-eligible · Kafka 브로커 · **PG 인스턴스 2 → 3** | 2026-08-09 | 아래 (D5 ②) |
| C-22 | **관측 = 양 사이트 모두 kube-prometheus-stack 자체 유지** (AMP·AMG 전부 미채택) · 사이트 구분은 `externalLabels.site` | 2026-08-09 | 아래 (D8 해소) |
| C-23 | **비밀 = 양 사이트 독립.** AWS = **SSM standard 번들 6 + IRSA** / 온프렘 = **현행 K8s provider 유지**. 🔴 **PushSecret·자동복제 미채택** — 동기화는 "같아야 하는 17키"에 한해 수동 | 2026-08-09 | 아래 (D7 해소) |
| C-24 | **사람 신원 = EKS Access Entry `kubernetesGroups` + 우리 커스텀 ClusterRole**(관리형 access policy 미채택) · 파드 신원 = **Pod Identity**(IRSA 미채택) · break-glass = **Identity Center 밖** | 2026-08-09 | 아래 (S4 해소) |
| C-25 | **보안 서비스 = 최소 + GuardDuty + Security Hub Essentials** (CloudTrail org trail · KMS · IdC/SCP 포함) · **AWS Config·Runtime Monitoring 미채택** | 2026-08-09 | 아래 (S4 해소) |
| C-26 | **AWS 유입 = Cloudflare(주황) → NLB(TCP:443 패스스루) → Istio Gateway → 앱** · TLS 종단은 **Istio Gateway 유지**(cert-manager Let's Encrypt = 온프렘과 동일) · target-type **`instance`** · 🔴 **ALB 미채택** | 2026-08-09 | 아래 (D-ing 해소) |

#### C-26 의 근거 — 뜯어서 얻을 게 없는데 뜯는 대가만 치른다 (D-ing 해소)

##### ⭐ 한 문장 답 (발표에서 이걸 말한다)

> **ALB 가 주는 건 L7 라우팅·WAF·접근로그인데, 우리는 그 셋을 Istio·Cloudflare·Istio 에서 이미 얻고 있다.
> 그래서 ALB 를 쓰면 얻는 건 없고 TLS 를 두 번 끊는 대가만 남는다 —
> SNI 가 사라져 재암호화가 불가능해지고, 평문 구간이 생기고, 리다이렉트 루프가 생긴다.**

##### ⚠️ C-9 를 뒤집는 것이 아니다 — 뜻을 명확히 한 것

```
   C-9 원문  "진입점 = 공개 ALB 1개만. 내부 도구 6종은 ALB 없이 Tailscale 로만"
   ⇒ 이 결정의 핵심은 **"1개만"** 과 **"내부 도구는 안 노출"** 이다.
     ALB/NLB 는 그 아래 **구현 선택**이다.
   ⇒ C-9 를 "공개 진입점은 **1개만**"으로 읽고, 그 1개를 NLB 로 구현한다.
```

##### 왜 ALB 면 502 가 나는가 — TLS 는 봉인된 봉투다

```
   봉투 겉면 = SNI (평문. 서버가 봉투를 열기 **전에** 어느 인증서를 꺼낼지 알아야 하니까)
   봉투 내용 = HTTP (암호문)

   ALB (Application = L7) — 봉투를 **뜯는다**. 안 뜯으면 경로 라우팅을 못 하니 존재 이유가 없다
     ① 뜯어서 "GET /api/prices" 를 읽는다
     ② 백엔드로 보낼 때 **새 봉투**를 쓴다 → 🔴 새 봉투 겉면에 원래 수신처를 안 쓴다
     ③ 우리 GW 실측: `server_names: [app.mealbong.cloud]` · `default_filter_chain` **없음**
        = "겉면이 app.mealbong.cloud 인 것만 받는다. 그 외 규칙 없음"
     ④ ⇒ 매칭 실패 ⇒ 🔴 **전 요청 502**  (블로커 ②)
     ⑤ 그래서 :80 평문으로 보내면 502 는 사라지지만
        GW 의 `mp-https-redirect`(PathPrefix `/` → 301)가 걸려
        CF→ALB→GW→301→CF **무한 루프**  (블로커 ③) + ALB↔GW 구간 평문

   NLB (Network = L4) — 봉투를 **안 뜯는다**. TCP 를 그대로 흘린다
     ⇒ 클라이언트 SNI 가 GW 까지 그대로 도착 ⇒ ②③ 이 **발생할 여지가 없다**
     ⇒ 평문 구간도 없다
```

##### 🔴 LB 는 라우팅 장비가 아니라 **입구**다 (자주 헷갈리는 지점)

```
   ALB/NLB 가 실제로 하는 일
     ① 인터넷에서 닿는 **공인 진입점** — EKS 노드는 프라이빗 서브넷이라 직접 못 닿는다
     ② 여러 **노드**에 분산
     ③ 헬스체크로 죽은 노드 제외
   ⇒ "어느 서비스로 갈지"(라우팅)는 셋 다 아니다. 그건 뒤의 Istio 가 한다.

   🔴 그리고 온프렘의 MetalLB 는 AWS 에서 **동작하지 않는다**
      (L2 모드 = ARP 로 IP 를 주장 / VPC 는 그런 L2 브로드캐스트 도메인이 아니다)
   ⇒ AWS LB 는 **MetalLB 가 하던 그 자리를 채우는 대체재**다. 기능 추가가 아니다.
```

##### 결정이 2단이라는 점

```
   1단  LB 를 살까 말까?   ← 여기가 prod/DR 분기 문제
        산다(A/A'')  → AWS prod = LB · 온프렘 DR = cloudflared ⇒ **물리적으로 다른 물건**
        안 산다(B)   → 양쪽 다 cloudflared ⇒ 구분이 `2-1`(replicas 0 git 커밋) **하나**에 걸린다 🔴
   2단  ALB 냐 NLB 냐?     ← **TLS 문제**. prod/DR 분기와 무관 (둘 다 똑같이 얻는다)
```

##### 선택지 비교

| 안 | 블로커 | 판정 |
|---|---|---|
| A. ALB → GW `:80` | ①③④⑤ | ❌ 얻는 게 없다 |
| A'. ALB → GW `:443` 재암호화 | 🔴 **②로 불가** | ❌ 전 요청 502 |
| **A''. NLB TCP:443 패스스루** | ①⑤ | ★ **채택** |
| B. cloudflared 유지(LB 없음) | 전부 소멸 | ❌ prod/DR 구분이 `2-1` 하나에 걸린다 → C-3·C-5 와 충돌 |

⟳ **정정**: 조사 초안은 *"NLB 면 블로커 ①②③ 이 동시에 소멸"* 이라 했으나 **①은 소멸하지 않는다**.
오버레이 CNI 인 한 `instance` 타깃 강제는 ALB·NLB **공통 제약**이다. 소멸하는 건 **②③** 이다.

##### 🔴 결정 0 — target-type = `instance` (ALB·NLB 공통, 최상위 제약)

```
   AWS 문서: ip 타깃 = ENI 기반 CNI  /  instance 타깃 = **오버레이 CNI**
   우리는 C-7 로 Cilium cluster-pool(오버레이) + 파드 10.20.0.0/16
     ⇒ 파드 IP 가 VPC 라우팅 대상이 아니다 ⇒ `ip` 타깃 불가
   ✅ NodePort 는 이미 열려 있다: 15021:30810 · 80:30816 · 443:31095
   🔴 이 한 줄이 없으면 리허설에서 "등록은 되는데 전부 unhealthy" 로 하루를 태운다
```

##### 실측 — 형상이 온프렘과 같아진다

```
   현재 공개 Gateway (2026-08-09 실측)
     mp-gw-public
       http  HTTP:80
       https HTTPS:443  hostname=app.mealbong.cloud  tls.certRef=mp-gw-public-tls
     인증서 = Let's Encrypt (cert-manager · issuer mp-letsencrypt-prod) · Ready

   ⇒ TLS 종단·인증서가 **이미 Istio Gateway 몫**이다
   ⇒ NLB = 이 형상 **그대로 유지**
   ⇒ ALB = ACM 인증서를 하나 더 만들고 이 LE 인증서는 공개 경로에서 안 쓰이게 된다
           🔴 **온프렘(LE) ↔ AWS(ACM) 인증서 체계가 갈린다** = C-3 상시증명에서 한 겹 더 빠진다
```

##### ALB 논거 최종 검사 — 남는 게 없다

| ALB 논거 | 검사 |
|---|---|
| "EKS 표준 경로라 자료가 많다" | ⚠️ 약하다 — NLB 는 `Service type: LoadBalancer` + 어노테이션이면 끝이라 **더 단순**(Ingress·TargetGroupBinding 불필요). Gateway API + Istio 엔 NLB 가 더 자연스럽다 |
| "AWS WAF 부착" | ❌ **Cloudflare 가 한다**(C-4). CF 우회 방어는 어느 쪽이든 **SG 로 막는 것**이라 동일 |
| "L7 경로 라우팅" | ❌ **Istio HTTPRoute 12개**가 한다 |
| "요청 단위 접근로그" | ❌ **Istio 가 남긴다** |
| "ACM 으로 인증서 일원화" | ❌ **오히려 이원화된다**(위 실측) |

##### 비용 — 사실상 동일

| | ALB | NLB |
|---|---|---|
| 시간당 | $0.0225/h → $16.43/월 | **동일** |
| 사용량 | $0.008/LCU | **$0.006/NLCU** (더 쌈) |
| 퍼블릭 IPv4 | $0.005/h × 3 AZ = $10.95/월 | 동일 |
| **합계** | **$27.38/월 (하한)** | **동일** |

실트래픽 **0.959 req/s** 라 LCU 는 사실상 0.
🔴 **"총액의 3.7%" 같은 비율은 쓰지 않는다** — 분모($678)가 미검증이고(§0.2 D10 경고),
$678 안에 LB·IPv4 가 이미 들어 있는지도 알 수 없다. **"$27.38/월(하한)"까지만 확정으로 쓴다.**
⟳ "고정비"가 아니라 **하한**이다 — 부하·서브넷 IP 소진 시 AZ 당 노드가 늘고 IP 를 더 먹는다.

##### 🔴 포기하는 것

| 포기 | |
|---|---|
| **AWS WAF 부착점** | Cloudflare 가 대신한다. 🔴 **CF 를 우회당하면 그 방어가 통째로 없다** → SG 게이트(아래)가 그래서 중요 |
| **L7 경로 라우팅·요청 단위 접근로그** | Istio 가 한다 |
| **$27.38/월 (하한)** | |
| **"공개 인그레스 0" 상태** | SG·리스너·타깃그룹이라는 새 관리면 |
| **Cloudflare IP 대역 화이트리스트 운영 부담** | 대역이 바뀌므로 자동 갱신 필요 |
| 🔴 **C-3 "상시 증명"의 일부** | **가장 큰 포기다.** 온프렘=cloudflared / AWS=NLB 로 **입구만 서로 다른 코드경로**가 된다. C-3 의 가치가 *"설정·이미지·시크릿·정책이 지금 이 순간 동작함을 상시 증명"* 인데 **입구가 그 증명 밖으로 빠진다** = 페일오버 당일 처음 쓰는 경로가 생긴다. 완화 = 온프렘도 같은 HTTPRoute 형상 유지 + 리허설에서 주기 검증 |

##### 되돌리기 비용이 낮다는 점

```
   실제로 바뀌는 것 = Istio Gateway **Service 어노테이션 몇 줄**
     service.beta.kubernetes.io/aws-load-balancer-type: external
     ...-nlb-target-type: instance · ...-scheme: internet-facing
   앱 13종 · HTTPRoute 12개 · Gateway · 인증서 → 전부 **안 바뀐다**
   ⇒ 리허설 클러스터(1-9)에서 ALB 도 실측 가능. 확정이 곧 영구 락은 아니다
```

#### C-24 · C-25 의 근거 — RBAC 의 구멍이 EKS 에서 AWS 권한으로 번역된다 (S4 해소)

##### ⭐ 한 문장 답

> **K8s RBAC 과 IRSA 는 충돌하지 않는다 — 서로 다른 API 를 지배하니 우선순위 개념 자체가 없다.
> 문제는 충돌이 아니라 *다리*다: `serviceaccounts/token create` 권한이 곧 그 SA 의 IAM 롤이 된다.
> 그래서 EKS 에서는 "K8s edit 권한 = 그 네임스페이스의 모든 AWS 권한"이 된다.**

##### 🔴 라이브 보안 구멍 2건 — AWS 안건이 아니라 *지금 온프렘* 에 뚫려 있다

**(1) ESO 우회 탈취** (2026-08-09 실측 — 경로 전 구간 확인)
```
   edit 티어 3명 (건우·정현·정은)
     └ aggregate-to-edit ClusterRole 11개 자동 흡수  ✅실측
        └ external-secrets-edit → externalsecrets CREATE
           └ ClusterSecretStore `fb-kubernetes`
                🔴 spec.conditions = 비어 있음  ✅실측 → 어느 ns 에서든 참조 가능
              └ 백엔드 SA `fb-secrets/eso-reader`
                   rules: secrets [get,list,watch] · resourceNames 없음  ✅실측
                 └ 🔴 ExternalSecret 하나로 fb-secrets 6종 전량이 자기 ns 로 복사된다
                      harbor-pull(레지스트리) · repo-food-budget-config(config 레포 **쓰기** SSH 키)
                    ⇒ 시크릿 유출 = 배포 파이프라인 장악
```
⚠️ **경계**: 스토어 capabilities 는 `ReadWrite` 지만 `eso-reader` Role 이 `[get,list,watch]` 뿐이라 **PushSecret 은 RBAC 에서 실패**한다. → 현재 위험은 **탈취(읽기) 한정, 원본 오염(쓰기) 아님.** 과잉·과소 대응을 둘 다 피하려면 이 경계를 적어야 한다.

**(2) 🔴 RBAC → IAM 권한 상승 다리** (2026-08-09 실측)
```
   K8s RBAC 쪽 (실측: edit 티어 = 전부 yes)      AWS IAM 쪽 결과
   ───────────────────────────────────────────────────────────────
   serviceaccounts/token  create   ──►  그 SA 의 OIDC 토큰 발급
                                        = AssumeRoleWithWebIdentity 입력
                                   ──►  🔴 그 SA 의 IRSA 롤을 그대로 획득
   serviceaccounts        create   ──►  새 SA + 임의 IAM 어노테이션
   pods                   create   ──►  그 SA 로 파드 기동 → Pod Identity 경로

   ⇒ 오늘(온프렘): edit 3명이 딸 수 있는 건 K8s 리소스뿐
     EKS 로 가면 : edit 3명이 그 ns 의 **모든 IRSA/Pod Identity 롤**을 딸 수 있다
     = 폭발 반경이 K8s 에서 **AWS 계정으로 확장**된다
```

##### 우선순위 3종은 설계 선택으로 이미 비껴갔다

| # | 우선순위 문제 | 우리 상태 |
|---|---|---|
| ① | **자격증명 체인** — `AWS_ACCESS_KEY_ID` env 가 IRSA/Pod Identity 보다 **앞선다** | ✅ **0-16 4단 순서**가 이것이다. 22개가 envFrom 으로 정적 키를 받으므로 롤만 붙이면 **조용히 옛 키를 계속 쓴다** |
| ② | **파드 신원** — 같은 SA 에 IRSA 어노테이션 + Pod Identity association 을 둘 다 걸면 **Pod Identity 우선**(🔴 미검증) | ✅ **Pod Identity 단일**로 정했으므로 발생하지 않는다 |
| ③ | **인증 경로** — `aws-auth` ConfigMap ↔ Access Entries 공존(`API_AND_CONFIG_MAP`) | ✅ 신규 클러스터라 **`authenticationMode: API`** 로 시작하면 문제 자체가 없다. `aws-auth` 는 기존 클러스터 마이그레이션 이슈 |

##### 🔴 RBAC 세분화만으로는 완전히 안 막힌다 — 2층 방어

```
  제거 가능한 다리                       제거 불가능한 다리
  serviceaccounts/token create  ✅빼면됨   pods create  🔴 개발자한테서 못 뺀다
  serviceaccounts create        ✅               └ 그 SA 로 파드를 띄우면
  serviceaccounts impersonate   ✅                 Pod Identity 가 credential 을 준다

  ┌ 층1 · K8s (0-14) ─ serviceaccounts 계열 3종 제거
  └ 층2 · AWS (S4-2) ─ ① association 을 **특정 SA 에만**(ns·default SA 금지)
                       ② 그 IAM 롤 자체를 최소권한
                       ⇒ 파드를 띄워도 **딸 게 별로 없다**
```

##### 신원 — 왜 관리형 정책이 아닌가 (C-24)

| 안 | 판정 |
|---|---|
| **A. AWS 관리형 access policy** | ❌ `AmazonEKSEditPolicy` 가 **secrets r/w + serviceaccounts impersonate + pods/exec** 포함 = **내장 `edit` 과 똑같은 결함**. 🔴 그런데 원문이 *"You can't modify the contents of an access policy. You can't create your own access policies"* → **이 다리를 영원히 못 끊는다** |
| **B. `kubernetesGroups` + 커스텀 롤** ★ | 온프렘·EKS 가 **같은 ClusterRole 공유** → C-3 "상시 증명"이 권한 레이어까지 확장 · 권한 정의가 **git 에 남아 diff 가능** · AWS 가 안내하는 정식 경로 |

⚠️ **정확히**: A 가 "0-14 를 되살리는 꼴"이라는 건 과장이다 — Access Entry 는 access scope 를 namespace 로 좁힐 수 있고 오늘의 건우도 이미 *namespace 로 좁힌 내장 edit* 이다. → **퇴행이 아니라 현상 고착**. B 를 고르는 이유는 **수정도 생성도 못 한다**는 제약 하나다.

**권한 세트 6종 ↔ K8s 그룹 5종**

| 권한 세트 | 대상 | K8s 그룹 |
|---|---|---|
| MPAdmin | 봉수 · 태현 | `mp:cluster-admin` |
| MPAppDev | 건우 | `mp:app-dev` |
| MPObservability | 정현 | `mp:observability` |
| MPDataDev | 정은 | `mp:pipeline-dev` |
| MPSecurityAudit | 전원 (security 계정 read-only) | `mp:viewer` |
| MPBilling | 봉수 (management) | — |

**Pod Identity 를 고른 이유** = 신뢰정책이 클러스터별 OIDC 발급자 URL 에 안 묶인다. C-8 의 *"PG 데이터 넣기 전까진 언제든 destroy"* 워크플로라 IRSA 면 **재생성마다 전 롤의 신뢰정책을 갈아야 한다**.
**break-glass 는 Identity Center 밖** = 확정 원칙(*"페일오버에 필요한 것은 방어대상과 장애도메인을 공유하지 않는다"*)의 직접 적용. ① 각 계정 root 봉인(하드웨어 MFA + 비밀번호 오프라인 분할) ② prod `mp-breakglass` IAM 롤(평시 SCP 차단 · 사용 시 CloudTrail→Slack).

##### 보안 서비스 (C-25)

| 안 | 월 | 판정 |
|---|---|---|
| A. 최소 (CloudTrail+KMS+IdC/SCP) | $6 | ❌ **탐지가 없다.** 0-17(egress 무제한 11 워크로드 = **IMDS 경유 노드 IAM 롤 탈취**)이 사는 동안 특히 아프다 |
| **B. 최소 + GuardDuty + Security Hub Essentials** ★ | **$34 ~ $111+** | ★ 채택 |
| C. 풀 (+Runtime +Config +CloudWatch) | +$100↑ | ❌ Config 는 CI 폭증(AWS 자체 예시 월 $95) · 🔴 **Runtime eBPF DaemonSet ↔ Cilium 공존이 문서에 언급 없음(미검증)** — C-7 로 네트워크가 Cilium 단일 의존이라 리스크 비대칭 |

🔴 **비용 추정 2건을 크게 고쳤다:**
```
  GuardDuty EKS Protection
    초안 $12.96(점추정) → 실제 $13 ~ $82.  초안 값은 **하한**이다.
    8.10M events/월 은 우리 온프렘의 **축소 audit policy**(level:None 으로 읽기 제외) 기준인데
    🔴 EKS 는 커스텀 audit policy 를 못 넣는다 → 실제 API 요청 19.839 req/s = 51.42M/월 → 상한 $82.28
  Security Hub Essentials
    초안 $15~23(레포 18종) → 🔴 성립하지 않는다.
    공식 비율은 "ECR container **images** 18개 = 1유닛" = **이미지 아티팩트 수**.
    `:sha` 불변 태그라 레포 18개에 수백 아티팩트 → 수십 배 과소평가.
    🔴 **ECR lifecycle policy 없이는 범위 자체가 미정** (S4-8)
```
확정: CloudTrail 관리이벤트 **$0**(첫 사본 무료) · Identity Center·SCP **$0** · KMS CMK 6개 $6.
🔴 GuardDuty **30일 무료체험은 종료 후 자동 비활성되지 않는다** → 2개월차에 요금 첫 노출 (S4-9).
**AWS Config 미채택**은 C-8 의 *"Control Tower 미사용 — Config 를 켜서 조용히 비싸진다"* 와 정합. 🔴 **단 Security Hub Essentials 가 Config 를 요구하는지 공개 페이지에 서술이 없다 → 착수 전 확인이 게이트**(S4-10).

##### 🔴 근거에서 뺀 것 — 유령 drain 이 통계를 오염시켰다

워크플로는 *"감사로그의 `kubernetes-admin` 3,629건(6.3%) = 사람 접근이 전부 admin.conf 로 나간다"* 로 결론지었는데 **틀렸다**:
```
   verb = create 하나뿐 · objectRef = 전부 pods/eviction · userAgent 단일값
   ⇒ 사람의 대화형 작업이 아니라 **축출 재시도 루프**
   ⇒ 2026-08-09 에 정지시킨 유령 drain(--dry-run=server, 2일 1시간 가동)이었다
   ⇒ 그 창에 사람 형태 verb 는 0건
```
**admin.conf 회수 필요성은 `cluster-admin → Group system:masters` 바인딩이 실재한다는 사실만으로 충분히 선다.** 이 통계는 근거에서 뺀다.

##### 🔴 포기하는 것

| 포기 | |
|---|---|
| **런타임 침해 탐지 전부** | 침해가 K8s API 나 AWS API 를 안 거치면 못 본다 |
| **설정 드리프트 탐지** | Config 미채택 — 콘솔에서 SG 를 열어도 알림 없음 |
| **K8s 감사로그의 우리 손 안 보관** | 🔴 CloudTrail 로는 **안 된다**(AWS API 감사만). GuardDuty finding 이 알려주는 만큼만 안다 (S4-7) |
| **온프렘·AWS 신원 체계의 동형성** | Pod Identity 는 온프렘에서 재현 불가 → **정적 키가 온프렘에 영구 잔류**(0-16 은 AWS 쪽만 해결) |
| **`mp-users` 무기한 토큰 5개의 소멸** | 온프렘 존치 확정이라 cluster-admin 토큰 2개 포함 5개가 계속 산다 |
| **Security Hub 비용 예측 가능성** | ECR lifecycle policy 전까지 상한 불명 |
| 🔴 **Object Lock 을 COMPLIANCE 가 아닌 GOVERNANCE 로** | SCP 는 **관리계정 장악 시 제거 가능**하다. COMPLIANCE 는 root 도 못 지운다. → **"관리계정을 장악한 공격자에 대한 로그 불변성"을 되돌림 가능성과 맞바꾼 거래.** COMPLIANCE 를 피하는 이유는 보존기간 내 삭제 경로가 **"계정 삭제"뿐**이라 학생 예산에서 실수로 대용량이 들어가면 못 되돌린다는 것 |
| 🔴 **EKS 콘솔의 권한 가시성** | Access Entry 엔 `kubernetesGroups` 문자열만 보이고 실권한은 클러스터 안 ClusterRole 을 봐야 안다. **K8s API 가 안 닿을 때 권한을 파악하는 상황**(Access Entries 의 셀링포인트)에서 이점이 반감 |

#### C-23 의 근거 — 새 부품을 들이지 않는 쪽이 이겼다 (D7 해소)

##### ⭐ 한 문장 답

> **비밀은 데이터만큼 급하지 않다. 34키·4KB·저빈도 변경에 자동 복제 기계를 들이면 기계가 문제보다 커진다.
> 양 사이트를 독립으로 두면 순환 의존도, 새 부품도, 새 정적 키도 전부 발생하지 않는다.**

##### 🔴 기각한 내 초기 권고 (기록 — 같은 실수를 반복하지 않기 위해)

초기 권고는 **"흐름을 뒤집는다 — 온프렘 = 쓰기 정본 / PushSecret 으로 SSM 에 단방향 복제"** 였다.
사용자가 기각했고, **그 판단이 옳다.** 근거는 초기 권고 자신의 "포기하는 것" 목록이다:

```
   초기 권고가 새로 들여오는 것                    채택안
   ─────────────────────────────────────────────────────────
   PushSecret (라이브 사용 0건 · 미검증)      →    없음
   온프렘 정적 IAM 키 (PutParameter 쓰기 권한) →   없음
     ← 초기 권고 자신이 "기각한 설계(읽기전용)보다
        폭발반경이 크다"고 적고 있었다
   "온프렘이 죽으면 EKS 가 새 시크릿을 못 받는다"  없음
     = 신규 배포 불가 · 사고대응 자격증명 발급 불가 (두 사이트가 독립)
```
게다가 순환 의존도 **채택안에서 더 깨끗하게 사라진다** — 초기 권고는 "읽는 방향만" 뒤집어 **쓰기 결합**을 남겼는데, 채택안은 **양쪽이 서로를 아예 참조하지 않는다**.

##### 실측 — 배선

| 항목 | 값 |
|---|---|
| 원본 | `fb-secrets` ns **6종 / 37키 / 값 합계 4,055 B** |
| 🔴 출처 | 6종 전부 `managedFields=[]` · labels 없음 → **손으로 apply. git·IaC 에 인벤토리 0** (= 0-11) |
| ClusterSecretStore | **1개** `fb-kubernetes` (provider=kubernetes · remoteNamespace=`fb-secrets` · Ready) |
| ExternalSecret | **30개 / 7 ns** · 전건 SecretSynced · 정책 **(Owner, Retain) × 30** |
| remoteRef 엔트리 | **70개** · refreshInterval 전건 1h |
| 매니페스트 위치 | 앱 레포 2 / **config 레포 27** |
| 주입 형태 | 🔴 **전부 `envFrom.secretRef`** · 체크섬 어노테이션 없음 → **값을 바꿔도 도는 파드는 옛 값을 쓴다** |
| fan-out | `PGPASSWORD` **11개** · `JWT_SECRET` **10개** · `harbor-pull` 각 5 ns |
| 번들 크기 | **app-secrets 3,385 B = standard 4,096 B 의 82.6%(여유 711 B)** · 나머지 5종은 550 B 이하 |
| 4KB 초과 개별 키 | **0개** (최대 `GCP_SA_KEY_JSON` 2,460 B) |

##### 🔴 37키 분류 — 동기화 대상은 37이 아니라 **17**이다

```
 ① 두 사이트가 같아야 하는 것 ── 17키
     JWT_SECRET · PGPASSWORD · PGSYNC_PG_PASSWORD
     STREAMING_REPLICA_PASSWORD · OPERATIONS_EXTERNAL_PGPASSWORD
     GOOGLE_CLIENT_ID/SECRET · KAKAO_CLIENT_ID/SECRET
     CLOUDFLARE_API_TOKEN · CLOUDFLARE_TUNNEL_CREDS
     GEMINI_API_KEY · CHAT_GEMINI_API_KEY · REPORT_GEMINI_API_KEY
     GCP_SA_KEY_JSON · DATA_GO_KR_SERVICE_KEY · pipeline PGPASSWORD

 ② 사이트별로 **달라야** 하는 것 ── 17키
     harbor-pull 3        온프렘=Harbor / AWS=ECR
     PG_BACKUP_AWS_* 2 · pipeline AWS_ACCESS_KEY_ID/SECRET 2
                          → AWS 는 IRSA 로 소멸 (= 0-16)
     PG_ONSITE_MINIO_* 2  → AWS 는 C-18 로 MinIO 삭제
     ES 비밀번호 3        → ES 는 사이트별 독립(재색인으로 재파생, C-15)
     alertmanager-slack 2 → 사이트 분리 예정 (2-5)
     argocd repo key 3    → 사이트별 다른 키가 오히려 낫다

 ③ 죽은 키 3 — 어떤 ExternalSecret 도 참조하지 않는다
     app-secrets/ES_PASSWORD · pipeline-secrets/ES_PASSWORD
     · pipeline-secrets/AWS_REGION
```

##### 🔴 그리고 17키 중에서도 진짜 관리 대상은 **조용히 갈리는 7키**다

| | 드리프트가 드러나는 방식 |
|---|---|
| PG 계열 4 · 외부 API 키 5 · pipeline PGPASSWORD | ✅ **즉시 접속 실패** → 바로 안다 |
| 🔴 **JWT_SECRET** | **조용하다. 페일오버하는 그 순간에만 드러난다 = 전 유저 로그아웃** |
| 🔴 OAuth 4 (Google·Kakao ID/SECRET) | 조용하다 — DR 로 넘어간 뒤 로그인 시도해야 드러난다 |
| 🔴 Cloudflare 2 (API_TOKEN · TUNNEL_CREDS) | 조용하다 — 페일오버 시 터널이 안 뜬다 |

##### 🔴 `app-secrets` 의 blast radius — 앱만 받치는 게 아니다

```
   app-secrets (3,385 B · 여유 711 B)
     ├── app           13개 ExternalSecret
     ├── mp-ingress     2개  ← mp-app-tunnel-creds · mp-cloudflare-api-token
     └── observability  1개  ← mp-cloudflare-api-token
                       ─────  16객체 / 3 ns
   ⇒ 이 번들이 깨지면 앱뿐 아니라 **공개 유입 경로(cloudflared)까지 동시에 죽는다** → D-ing 접점
```

##### AWS 쪽 이식 비용이 싼 이유 (SSM 번들 6 = A안)

- AWS Parameter Store provider 가 **gjson property 추출**을 지원한다
- 30개 property 이름을 전수 스캔해 **gjson 메타문자(`. * ? # [ ]`) 0건** 확인
- → **`remoteRef` 70엔트리가 한 글자도 안 바뀌고 옮겨진다**

🔴 **단 논리 구멍 하나 — 이걸 명시 안 하면 구현자가 70엔트리를 다시 쓰기 시작한다:**
```
   "remoteRef 무수정"        → 파라미터 이름이 리터럴 `app-secrets`
   "IAM 경로 /mp/prod/* 최소권한" → 경로 접두사가 필요
   해법 = ClusterSecretStore 의 spec.provider.aws.prefix: /mp/prod/
          (v1·v1beta1 CRD 양쪽에 존재)
```

##### 비용 — 결정 변수가 아니다

| 안 | 월 |
|---|---|
| **채택 (SSM standard 번들 6)** | **$0.09 ~ 0.31** (KMS 요청만) 🟡 SecureString 사용·KMS 무료티어 배분 두 가정 미검증 |
| SSM advanced | $0.26 · 🔴 되돌릴 수 없다 |
| Secrets Manager 번들 6 | $2.66~2.91 |
| Secrets Manager 키별 34 | **$13.60** |

> 가장 비싼 안(월 $13.60)조차 D10 실측선 $678 의 **2.0%** 다. **돈으로 고를 안건이 아니다.**

##### 🔴 포기하는 것 — 채택안의 정직한 대가

| 포기 | 완화 |
|---|---|
| 🔴 **정본이 둘 → 드리프트 가능** | 17키 목록 명문화 + **조용한 7키** 별도 표시 (0-27) |
| 🔴 **JWT_SECRET 이 갈리면 페일오버 순간 전 유저 로그아웃** | 최악이자 유일하게 아픈 시나리오. **0-11(SOPS)이 실질 완화책** |
| 자동 화해·알림 없음 | 🔴 *"변화가 있을 때마다 갱신"* 의 약한 고리 = **변화를 어떻게 아나**. 지금은 **사람 기억**이 유일한 메커니즘 → **0-11 이 붙으면 PR 이 변경 신호가 된다** |
| **4KB 천장을 안고 간다** | 여유 711 B — **SA JSON 하나 더 넣으면 초과**. CI 가드(0-28) + Intelligent-Tiering |
| 키 단위 최소권한 | 번들이라 IAM 경로는 **번들 단위까지만**. app-secrets 하나가 16객체를 받친다 |
| ESO 스토어 페일오버 없음 | 라이브 CRD 확인 — `secretStoreRef` 는 `{kind,name}` 객체다. **배열도 fallback 필드도 없다** |

#### C-22 의 근거 — 관리형은 부담을 없애지 않고 이중화한다 (D8 해소)

##### ⭐ 한 문장 답

> **AMP 는 메트릭 전용이다. 옮겨도 Alertmanager·Loki·Tempo·Alloy 는 그대로 우리가 운영한다.
> 게다가 온프렘 물리계층 9룰은 어차피 남아야 한다 — 관리형은 운영 주체를 하나에서 둘로 늘린다.**

##### 선택지가 지워지는 순서

```
   우리 관측 스택은 5종이다
     메트릭   Prometheus    ← AMP 가 대신할 수 있는 유일한 것
     알림     Alertmanager  ← AMP 밖
     로그     Loki          ← AMP 밖
     트레이스 Tempo         ← AMP 밖
     수집     Alloy         ← AMP 밖
   ⇒ (b)·(c) 어느 쪽을 골라도 4종은 자체운영이 남는다
```

| | 선택지 | 판정 |
|---|---|---|
| **(a)** | **양 사이트 자체 유지** | ★ **채택** |
| (b) | AMP + AMG 전면 | ❌ 확정 단가만 월 $367 · 메트릭 전용 · **알림 두뇌가 AWS 에 있으면 DR 을 감시 못 함** |
| (c) | 혼합 (룰 로컬 + AMP 장기보관) | ❌ **수집 과금은 그대로**(지배축 77.9%) · remote_write 경로가 지금 아예 없다 |
| (d) | AMG 만 | ❌ **Grafana 실사용이 11m / 354Mi 뿐** — 월 $33 으로 살 부담이 아니다 |

##### 실측

| 항목 | 값 |
|---|---|
| 24h 평균 CPU / 메모리 피크 | **0.180 코어** / **약 4.24 GiB** (요청 0.90 CPU = 실사용의 **5배**) |
| 활성 시계열 | 172,064 현재 / **12일 최대 220,683** — 사이징은 피크로 |
| 수집률 | **6,224.68 샘플/초** → 월 161.3억 |
| 룰 | CR 44 / 그룹 49 / **알림 199 + 레코딩 89 = 288** |
| 유효 발화 | 15일 내 고유 30종 → **28종 = 14.1%** (미발화 ≠ 무용) |
| 관측 데이터 총량 | 약 **8.4 GB** (Prometheus 7.77 + Loki 451MB + Tempo 137MB) |
| 대시보드 | **33장** (수작업 13 + 차트 기본 20) |
| 쿼리 출처 | 룰 평가 **9.04회/초** vs HTTP API **0.148회/초** → 룰 1회당 ~79,700 샘플 |

##### 🔴 AWS 로 "옮기면 안 되는" 것 — 도달성이 아니라 장애도메인

```
   job          타깃   대상
   hypervisor     2   Proxmox 물리 2대 (fb-proxmox · mp-proxmox-b)
   vm-node        1   호스트 C
   vm-cadvisor    1   호스트 C
   vm-alloy       1   호스트 C
   → mp-physical-layer 알림 9룰이 직접 참조 · 15일 내 4건 실발화
     (TempCritical · TempHigh · DiskReadBurst · MpHostCDown)
```
⚠️ **"AWS 에서 못 본다"는 틀린 서술이다** — C-6(Tailscale) 이 확정돼 있어 **도달은 된다**.
정확히는 **"보면 안 된다"** 이고, 근거는 **Tailscale·AWS 가 죽는 국면이 바로 이 감시가 필요한 국면**이라는 것이다.

##### 비용 — AMP 는 수집에서 돈을 받는다

```
  수집  6,225 샘플/s → 월 161.3억   ████████████████████ 77.9%  $674.69
  쿼리  720,565 샘플/s              █████                21.6%  $186.73
  저장  ~2 B/샘플                   ▏                     0.5%  $  4.51
                                                         ──────────────
                                                               $865.93
```
| 항목 | 값 | 검증 |
|---|---|---|
| **AMP 확정 부분** | 수집 1티어 $180 + 쿼리 $186.73 = **월 $367** | ✅ 요율 확인 · 🔴 리전 미검증 |
| AMP 상위 티어분 | $494.69 (**총액의 57%**) | 🔴 **미검증** (공식은 "Volume tiering applies" 문장뿐) |
| AMP 프리티어 | 쿼리 2,000억 무료 → $186.73 → **$166.73** | ✅ 확인 · 계정 3개 신규라 적용 가능성 실재 |
| AMG 5인 | 월 **$33** | ✅ 확인 |

🔴 **`$4.16 vs $899` 로 비교하면 안 된다 — 사과와 오렌지다.** (a) 의 정직한 원가에는 **상시 컴퓨트 예약(0.90 vCPU / 3.78 GiB)** 이 들어간다.
그리고 **"증분 노드 0"은 측정이 아니라 가정**이다 — 워커 4대 미요청 메모리 여유 합계 **10.52 GiB** 중
관측(3.775) + kubecost(3.804) = **7.579 GiB = 여유의 72%**. 네 워커 모두 메모리 limits 초과커밋 **94/112/154/127%**. → **D10 과 함께 재계산**.

##### 🔴 철회한 근거 3개 (반증 검증에서 깨진 것)

- ❌ "쿼리가 지배축이다" → **지배축은 수집(77.9%)**. AWS 문서도 *"metric ingestion contributes the majority of costs"*
- ❌ "$4.16 vs $899" → 기준선이 다르다(컴퓨트 미계상)
- ❌ "실측 소비가 작으니 운영부담이 없다" → **자원 소비는 운영부담의 척도가 아니다.** 업그레이드·PV 리사이징·인증·온콜이 부담이다
- ※ "Prometheus 가 12일간 6회 재시작" 도 오독이었다 — `RESTARTS` 는 파드 내 **전 컨테이너 합**(prometheus 3 + config-reloader 3)이고
  **실제 파드 재시작은 3회, 전부 생애 첫 27시간(컷오버 창) 안, 이후 11일 무재시작**. 종료 로그도 정상 종료였다(구 `.11` remote_write 철거)

##### 🔴 포기하는 것

| 포기 | |
|---|---|
| 장기 보존 | 메트릭 15일 / 로그·트레이스 7일 |
| 관측 스택 HA | 전부 replica 1 |
| 🔴 **관측 데이터가 단일 노드와 운명을 같이한다** | Prometheus 30Gi + Alertmanager 2Gi + MinIO 50Gi 가 전부 `worker-b2`. **AMP 였다면 메트릭이 클러스터 장애도메인 밖에 있었을 것이다.** ← 이게 (a)가 실제로 내주는 것 |
| Prometheus 운영 책임 | 업그레이드 · PV 사이징 · 인증 |
| 교차사이트 단일 창구 | `externalLabels` 로 직접 만든다 |

#### C-16 ~ C-21 의 근거 — 스토리지 (D5 해소)

##### ⭐ 한 문장 답

> **프로비저닝 352 GiB 중 실사용은 13.5 GiB(3.8%)다. EBS 는 산 만큼 청구하므로 이관 시점이 유일한 무비용 리사이즈 창이고,
> `storageClassName` 과 STS `volumeClaimTemplates` 가 둘 다 immutable 이라 이 창을 놓치면 이후 축소는 STS 재생성 수술이 된다.**

##### 🔴 종전 계획서의 결함 2건 (정정)

```
① PVC 만 세고 있었다
     계획서    PVC 352 GiB                      ← 이게 EBS 청구서의 전부인 줄 알았다
     실측      + 워커 4대 × 90 GiB = 360 GiB    ← 🔴 통째로 누락
                 ├ /            48 GiB (실사용 3.7~4.9)
                 └ containerd   40 GiB (실사용 16~21 = 43~56%)
               합계 712 GiB · 실사용 106.9 GiB · 배수 6.7×
     → `mp_aws_migration_plan.md:71` 의 "$32.01/월" 은 A 를 약 $33 과소평가한다

② 프로비저닝 정본이 1 GiB 틀렸다
     §1.2 표가 `app/mp-ranking-model` 1Gi 를 빠뜨렸다 — 하필 사본이 0개인 유일한 볼륨.
     정본 = 351 → **352 GiB**
```

##### 항목별 크기 (C-16)

| # | 데이터 | 현행 | **목표** | 실사용 | 근거 유형 |
|---|---|---:|---:|---:|---|
| 1 | PG 데이터 | 20Gi×2 | **10Gi×3** | 856 MiB | 성장 — DB 848MB 중 **549MB 가 사체** → VACUUM FULL 후 ~277MB |
| 2 | PG WAL | 10Gi×2 | **4Gi×3** | 1,106 MiB | 🔴 **설정 천장** — `wal_keep_size 1GB`+`max_slot_wal_keep_size 1GB`+churn ≈ 2~3 GiB |
| 3 | ES | 10Gi×3 | **8Gi×3** | 15 MiB | 재파생 — 인덱스 24.2mb · **재색인 1.0초** |
| 4 | Kafka | 20Gi×3 | **10Gi×3** | 110 MiB | 실측 완료 — 아래 |
| 5 | Prometheus | 30Gi | **20Gi** | 7,731 MiB | 🔴 **정상상태** — 15일 = 10.19 GiB (여유 1.96×) + `retentionSize` 설정 |
| 6 | Alertmanager | 2Gi | **1Gi** | 0.53 MiB | 안전마진(더 줄여도 절감 $0.05) |
| 7 | Loki 로컬 | 10Gi | **4Gi** | 11.9 MiB | 재파생 — 청크 정본은 S3 |
| 8 | Tempo 로컬 | 10Gi | **4Gi** | 3.6 MiB | 재파생 — 블록 정본은 S3 |
| 9 | MinIO | 50Gi | **0 · 삭제** | 658 MiB | C-18 |
| 10 | kubecost | 97Gi | **0 · EC2** | 930 MiB | C-19 |
| 11 | ranker.pkl | 1Gi | **0** | 0.95 MiB | C-20 |
| 12 | pipeline ×2 | 2Gi | **0** | ~2.1 MiB | C-20 — 온프렘 잔류 |
| 13 | Redis | — | **0** | — | C-20 — 🔴 6/6 파드가 볼륨 자체가 0개 |
| 14 | 노드 루트/imagefs | — | **60Gi × N** | 16.5+77 GiB | imagefs 16~21 GiB + **상한 없는 emptyDir 160개**가 여기 얹힌다 |
| | **PVC 합계** | **352 GiB** | **125 GiB** | 13.5 GiB | |

**Kafka 실측 (2026-08-09)** — `retention.ms` 미측정 상태를 해소했다:
```
  메인 5종  604,800,000 ms = 7일   ·  DLQ 5종  2,592,000,000 ms = 30일
  retention.bytes = <none>  🔴 무제한 (크기 상한 없음)

  브로커가 보존기간(7일)을 3일 넘겨 돌았다 → 현재 110 MB 는 "쌓인 양"이 아니라 **정상상태**
  내역   __cluster_metadata 49 MB(45%, KRaft·retention 무관) + retail.crawl.raw 57 MB(52%) + 나머지 4 MB
  30일 환산 ≈ 356 MB  →  10Gi 에서 여유 29×.  ✅ retention 30일 결정과 무관하게 10Gi 안전
```

##### 왜 EFS 를 안 사는가 (C-17)

```
  · PVC 21 / 21 이 RWO (RWX 요청 0건)
  · 🔴 그보다 강한 근거 — 21개 전부 **실제 소비자가 정확히 1개**다(파드 전량 파싱)
      pipeline 2건이 "파드 2개"로 보인 것은 CronJob 잡 이력(`successfulJobsHistoryLimit=2`)이고
      둘 다 `concurrencyPolicy: Forbid` → 경합 구조 자체가 없다
  · 단가 gp3 대비 ~3.3배 + 마운트 타깃/보안그룹 복잡도
  · PG 를 EFS 에 올리지 않는다 — fsync/파일락 의미가 달라 손상 위험
```

##### MinIO 삭제 (C-18) — 이득은 돈이 아니다

| | |
|---|---|
| 실사용 | 658 MiB = 50Gi 의 **1.3%** |
| 형상 | `replicas=1` · host-b 고정 → **SPOF** |
| 프로토콜 | 🔴 Loki·Tempo 는 **이미 S3 API**(`store: s3`) — endpoint 만 교체 |
| 앱 코드 | S3 클라이언트 **0줄** (`boto3` 4곳은 전부 Bedrock) |
| 소거 IaC | `k8s_minio` 롤 151 + 관련 = 약 **200줄** |
| 비용 차이 | EBS 50Gi $4.56 → S3 $1.92 = **월 $2.6** (오차 수준) |

🔴 **선행 조건** — 내용물의 **35%(318 MiB)가 `mp-pg-onsite` = PG 온사이트 덤프**다. barman(`s3://mp-backup-ap2/pg`)·tfstate 가 이미 같은 버킷이라, 온사이트까지 넣으면 **PG 백업 3트랙이 단일 장애·권한 도메인**이 된다. → **다른 버킷/계정 + 사이트 프리픽스**. 0-23·2-8 의 상위 결정.
부수: MinIO 콘솔 Service + HTTPRoute(`minio.mealbong.cloud`) 도 함께 사라진다 → **C-9 의 "내부 도구 6종" → 5종**.

##### kubecost EC2 분리 (C-19) — 비용 절감이 아니다

```
  프로비저닝 97 GiB (전체의 27.6%) / 실사용 930 MiB (0.97%)
    aggregator-db 64Gi → 🔴 마운트가 /var/configs/waterfowl/duckdb **와** /var/lib/clickhouse
       실측: clickhouse-serv 프로세스 가동 중 · /var/lib/clickhouse = 202M
       (kubecost 3.x 가 ClickHouse+DuckDB 를 번들한다. 우리 데이터 티어의 ClickHouse 드롭과는 별건)

  EC2 로 빼면 사라지는 것 = AZ 핀 · 드레인 차단 · PDB 공백 · PVC immutable 결합
  EC2 로 빼도 안 사라지는 것 = 과대 사이징 → 🔴 거기서도 **20 GiB** 로 잡는다
  🔴 돈은 오른다 — aggregator 가 메모리 3Gi 요구(t3.medium 급 상시). EBS 97 GiB($8.85/월)보다 비싸다
  클러스터 잔류 = finopsagent 1종(클러스터를 긁는 주체)
```

##### 정족수 배치 (C-21) — AZ 3개를 사는 이유

```
  ▸ 3개를 2 zone 에 (현재)          ▸ 3개를 3 AZ 에 (목표)
      zone A │ ●   zone B │ ● ●         AZ a │ ●   AZ b │ ●   AZ c │ ●
      B 사망 → 1/3 = 과반 아님 🔴       어느 하나 사망 → 2/3 = 과반 ✅
      A 사망 → 2/3 = 과반    ✅
      = 비대칭. 어느 쪽이 죽느냐에 운을 건다   = 대칭
```

**현재 실측 — 정족수 2/3 이 host-b 에 몰려 있다:**

| 컴포넌트 | 배치 | host-b 상실 시 |
|---|---|---|
| **ES** | master 3개 중 **2개가 host-b** (master = `es-es-b-1`) | 🔴 정족수 1/3 → **클러스터 전면 무응답**. `recipes`(replica 0)도 그쪽 → 챗봇 검색 사망 |
| **Kafka** | combined 3개 중 **2개가 host-b** | 🔴 KRaft 정족수 1/3 + **ISR 1 < minISR 2** → **프로듀서 전면 차단** |
| **PG** | instances **2** (pg-1 host-a primary / pg-2 host-b) | 페일오버는 되나 그 순간부터 **HA=0**. 3 AZ 중 2개만 사용 |

> ⚠️ **비대칭 주의** — ES 는 host-a(1노드) 상실은 견디고 host-b(2노드) 상실은 못 견딘다.
> "복제본이 분산돼 있으니 zone 1개는 견딘다"는 **내구성** 진술이지 **가용성** 진술이 아니다.

**완화 비용 — Prometheus 를 빼면 전부 0이다:**

| 완화 | EBS 증분 |
|---|---:|
| PG 2 → 3 (AZ당 1) | +14 GiB (C-16 에 이미 반영) |
| ES nodeSet 을 AZ당 1개씩 3개 · master 1/AZ | **0** (재색인 1.0초라 재구성 무비용) |
| Kafka 3 브로커 AZ당 1 · hostname 축만 soft | **0** (RF=3/minISR=2 는 이미 3 AZ 형상) |
| `mp-gw-internal-istio` replicas 2 + zone TSC | **0** (현재 무보호 SPOF) |
| 노드그룹을 AZ 당 1개 ASG 로 | **0** |
| ~~Prometheus replicas 2 across AZ~~ | +20 GiB → 🔴 **D8(관측)로 이관** |

##### AZ 실패 모드 — "느려짐"이 아니라 "안 뜸"

```
  EBS PV 에 nodeAffinity: topology.ebs.csi.aws.com/zone 이 박힌다
    → 스케줄러가 바인딩된 PVC 의 PV 토폴로지로 노드를 필터링
    → AZ 상실 시 **결정론적 Pending**(volume node affinity conflict). 자동 복구 없음
  ※ 온프렘에서 PV 21/21 이 특정 워커에 파드를 못박는 것과 같은 메커니즘이다
```

**🟢 D5 ① 결정이 AZ 문제를 6개 지웠다** — 원래 "AZ 상실 시 못 뜨는 단일 인스턴스"는 10개였다.
MinIO(C-18) · kubecost×2(C-19) · ranker.pkl(C-20) · pipeline×2(C-20) = **149 GiB / 6 워크로드가 소멸**.
**남은 4개는 전부 관측 스택**(Prometheus·Alertmanager·Loki·Tempo)이고, 재파생 불가는 **Prometheus 하나뿐**(메트릭 약 12일치).

##### 총량·비용

| | PVC | 노드 EBS | kubecost EC2 | **총 EBS** | 월(조건부) |
|---|---:|---:|---:|---:|---:|
| **A. 그대로** | 352 | 360 (4×90) | — | **712 GiB** | $64.93 |
| **B. 실소비** | 13.5 | 93.5 | — | 106.9 GiB | — |
| **C. 권고 (워커 4)** | **125** | 240 (4×60) | 20 | **385 GiB** | **$35.11** |
| C, 워커 5 | 125 | 300 | 20 | 445 GiB | $40.58 |
| **A → C 절감** | | | | **−327 GiB** | **−$29.82** |

C 의 PVC 125 GiB 내역: PG 3×(10+4)=42 · ES 3×8=24 · Kafka 3×10=30 · Prometheus 20 · Alertmanager 1 · Loki 4 · Tempo 4.
**절감의 78% 가 3줄에서 나온다** — kubecost 97 + MinIO 50 + Kafka 30 = 177 / 227 GiB. 나머지 9줄은 합쳐 50 GiB.
🔴 **단가 `$0.0912/GB-월` 은 재검증 미완**(이번 조사 3세션 전부 재조회 실패 — 0-25). S3 ≈ 0.7 GB / 월 $1.92 도 요율 미검증.

##### 🔴 포기하는 것

| 포기 | 크기 | 왜 대안을 안 사나 |
|---|---|---|
| **Prometheus 메트릭 약 12일치** (AZ 상실 시) | 7.7 GiB / 290.6h | replicas 2 = +20 GiB(월 $1.82). **재파생 불가** → D8 에서 AMP 와 함께 결정 |
| kubecost 의 파드/ns 단위 비용 가시성 | — | Cost Explorer/CUR 은 **AWS 자원 단위**다. 단 C-19(EC2)를 택했으므로 가시성 자체는 유지 |
| **볼륨 레벨 온프렘 ↔ AWS 복제** | — | 🔴 **원리상 불가.** 온프렘 LVM **21/21 이 thick**(`thinProvision: no`) + `lvm-driver` 바이너리에 `only thin restores supported today.` → 이관은 **전부 논리 경로**(PG=barman · ES=재색인 · Kafka=드레인) |
| 컷오버 시점의 Loki/Tempo 7일 창 | 340 MiB | 보존이 168h 라 어차피 만료된다 → **mirror 하지 않기를 권고** |
| "온사이트" 백업의 온사이트 성질 | 318 MiB | S3 단일화 시 사이트 로컬 사본 소멸 → C-18 의 선행 조건이 이것이다 |
| 온프렘 DR 의 동일 용량 | b2 VFree **37 GiB** | AWS→온프렘 복제 시 b2 가 먼저 막힌다. LVM 은 노드 로컬이라 b2 고정 PVC 를 못 옮긴다 → **DR 은 축소본**이거나 워커 `sdb` 증설 |
| PVC 를 안 줄이는 편의 | — | `storageClassName`·STS `volumeClaimTemplates` **둘 다 immutable**. 21 PVC 중 **9개가 STS vct 파생**(STS 7개) → 이관 후 축소는 `--cascade=orphan` 삭제+재생성(Prometheus 7.7 GiB 이력 포함) |

#### C-15 의 근거 — 정본은 자체운영, 파생은 비용이 정한다 (D4-d 해소)

##### ⭐ 한 문장 답 (발표에서 이걸 말한다)

> **우리 DR 컨셉이 "온프렘 active-standby" 인데, RDS 는 외부 self-managed PG 로 물리복제를 못 한다.
> 그래서 RDS 를 고르는 순간 C-3 이 무너진다. 대가는 PG 운영 책임 전부를 우리가 지는 것이다.**

##### 3단 논증

```
① 요구  C-3 — 온프렘은 DR 대기 사이트다. AWS 가 죽으면 여기가 서비스를 받는다
                → 그러려면 PG 데이터가 온프렘에 상시 따라와 있어야 한다
② 제약  RDS/Aurora → 외부 self-managed PG 로 **물리 스트리밍 복제 불가**(AWS 공식)
                → 대안은 논리복제뿐인데, 논리복제는 아래 4개를 못 나른다
③ 결론  RDS 를 고르면 ①이 성립하지 않는다. → CNPG 유지 (선택지가 지워진다)
```

##### 논리복제로 DR 을 하면 무너지는 4가지

| | 안 따라오는 것 | 우리에게 뭘 뜻하나 |
|---|---|---|
| ① | **시퀀스** | 우리 PK 가 `bigserial` → 페일오버 후 **PK 충돌**. 수동 `setval` 이 절차에 들어간다 |
| ② | **DDL** | `schema-production.sql` 을 양쪽에 따로 적용. 어긋나면 조용히 깨진다 |
| ③ | **롤·권한** | 0-13(서비스별 PG 롤)이 들어오면 더 아파진다 |
| ④ | **슬롯 안정성** | 🔴 **우리는 이미 당했다** — #555(2026-08-06) mock 300만행 WAL 버스트로 **논리 슬롯 2개 무효화** → PGSync CDC 정지. **DR 을 논리복제에 걸면 그 사고가 곧 DR 상실이다** |

##### 🔴 그래서 RDS 대신 CNPG 를 골라 **포기하는 것** (정직한 전수)

| # | RDS 가 주는 것 | 우리 상태 | 판정 |
|---|---|---|---|
| 1 | **자동 마이너 패치 + 유지보수 창** | PG `16.14` 를 우리가 올린다. **"언제 올릴지" 정하는 프로세스가 없다** | 🔴 **CVE 방치 경로.** 인증서 만료 감시 부재와 같은 종류의 갭 |
| 2 | **자동 failover (검증된 초 단위)** | CNPG 도 자동 failover 를 한다. 그러나 **우리 환경에서 failover 리허설 기록이 없다** | 🔴 **가장 위험.** 믿고는 있는데 재본 적이 없다 |
| 3 | **스토리지 자동 확장** | WAL PVC **10Gi** 에 WAL 이 **361 MB/일** → 아카이빙이 막히면 **약 27일치**. 차면 **PG 가 선다** | 🔴 **알림 필요** |
| 4 | **콘솔 PITR** | 🟢 **왕복 복원은 증명됨**(P2 게이트① 2026-07-29 — barman→S3→복원, 40테이블 350,850행 완전 일치). 🔴 다만 **임의 시점 PITR 은 리허설 안 함**이고 절차가 무겁다(새 Cluster bootstrap, 분 단위) | 🟡 절반 확보 |
| 5 | **Performance Insights** (쿼리 단위) | Prometheus + exporter 는 있으나 **쿼리 레벨 인사이트는 없다** | 🟡 감수 |
| 6 | **AWS 지원 티켓** | 장애 시 **우리가 원인을 찾는다** | 🟡 5인 학생팀엔 실질 차이. CNPG 문서·커뮤니티가 완화 |
| 7 | **스토리지 AZ 추상화** | EKS 에서 PVC = **EBS 이고 EBS 는 AZ 에 묶인다**. 0-7(`topology.kubernetes.io/zone` 강제 기록)이 정확히 이 지점 | 🟡 CNPG 는 인스턴스마다 자기 PVC 라 볼륨 이동이 불필요 — 다만 **인스턴스가 2개뿐** |
| 8 | **크기별 파라미터 그룹** | CNPG 기본값 + 우리 판단 | 🟡 829MB DB 라 당장 무해 |
| 9 | **메이저 버전 업그레이드 도구** (블루/그린) | PG 16→17 은 `pg_upgrade` 또는 논리복제로 우리가 한다 | 🟡 이관 범위 밖 |
| 10 | **지식의 표준화 (bus factor)** | CNPG 를 아는 인원이 몇 명인가 | 🔴 5인 팀·9주 |

**🔴 진짜 위험한 것은 3개다 — 1(패치 프로세스) · 2(failover 리허설) · 3(WAL PVC).** 나머지는 감수 가능하다.
→ 이 3개를 **체크리스트 항목으로 신설**했다(1-17 · 1-18 · 상시).

##### 🟢 반대로 CNPG 가 RDS 보다 나은 것 (DR 말고도)

- **AWS 달러 $0** — 노드 자원 `26m CPU / 1.0Gi` 만 쓴다 (참고: RDS `db.t4g.micro` Multi-AZ ~$50/mo 추정·미검증)
- **진짜 superuser 접근** — RDS 는 `rds_superuser` 로 제한된다. **0-13(서비스별 롤 격리) 설계에 유리**
- **확장·버전 자유** — 지금은 확장이 `plpgsql` 하나뿐이라 체감은 없지만 제약이 없다
- **왕복 복원이 이미 증명됐다** — 관리형으로 옮기면 이 증명을 처음부터 다시 해야 한다
- 🟢 **프로젝트 목적 그 자체** — 이건 인프라 캡스톤이고, **K8s 위에서 데이터 티어를 운영하는 것이 애초의 학습 목표**였다. 관리형으로 옮기면 그 목표가 사라진다

##### ES 는 다른 이유로 같은 결론 (파생 데이터)

ES 는 **PG 에서 다시 만들 수 있다** → **DR 복제 논거가 아예 안 걸린다.** 여기선 비용과 코드가 막는다.

```
실측: ES 8.19.19 · 3노드(b:2+a:1) · green · 커스텀 이미지 mp-elasticsearch-nori (한국어 형태소)
      인덱스 4개 총 약 24 MB
        recipes_v2 9,280docs/8.2MB · recipes_pgsync 8,963/13.9MB
        recipes 6,107/2.1MB · user_recipes_v1 12/23KB
      클라이언트 elasticsearch[async]>=8.15,<9  (chat · recipe · pipelines/ingest)
      자원 30m CPU / ~4Gi (요청 500m·1536Mi ×3)
```

| | ECK 유지 🟢 | OpenSearch Service |
|---|---|---|
| 코드 변경 | **0** | 🔴 `opensearch-py` 로 교체 — 3곳 + 매핑·API 차이 |
| 엔진 계보 | ES 8.19 그대로 | 🔴 **ES 7.10 포크로 갈아탄다** |
| 한국어 nori | 커스텀 이미지 유지 | 🟢 내장(`analysis-nori`) |
| AWS 달러 | **$0** | 🔴 **~$79/mo 추정**(t3.small.search ×3 · 미검증) |
| DR | 🟢 재파생 | 🟢 재파생 |

🔴 **24 MB 인덱스에 월 $79 + 코드 교체는 균형이 안 맞는다.** → ECK 유지.

##### 🟢 D4 전체를 설명하는 원칙 하나

```
Redis  = 캐시(파생) · DR 요구 없음 · 운영이 이미 아팠다   → 관리형    (C-14)
ES     = 파생 · 재파생 가능 · 비용/코드가 막는다          → 자체운영  (C-15)
PG     = 정본 · DR 물리복제가 필수                       → 자체운영  (C-15, 선택지 없음)
Kafka  = 전송 · 온프렘 크롤 운반이 필요                   → 자체운영  (C-10·C-11)
```
**정본일수록 자체운영, 파생일수록 관리형.** 판단이 취향이 아니라 데이터 성격에서 나온다.

##### 🔴 딸려오는 선행 (이미 등재된 것)

- **0-20** — 현 `bootstrap` 이 `pg_basebackup from vm-pg(192.168.0.8)` 인데 **그 VM 은 파괴됐다**(2026-08-09 라이브 재확인). `bootstrap` 은 생성 시점 1회만 유효 → **Cluster 삭제·재생성**(PGDATA 20Gi + WAL 10Gi PVC 파기). **별건 규모**
- **0-23** — 양 사이트 Cluster 이름이 둘 다 `pg` 라 `pg/pg/wals` 가 겹쳐 **WAL 이 서로를 덮는다**. standby 구축 전에 잡는 게 압도적으로 싸다
- `sslmode: prefer` 는 LAN 전제 → 크로스사이트면 **TLS 필수**
- 🟡 **ES heap 재검토(별건)** — 24 MB 인덱스에 `1536Mi × 3`. **D10 노드 수에 직접 영향**
- 커스텀 nori 이미지를 계속 빌드해야 한다 → **ECR 이관 + CI 유지**(0-9 와 같은 트랙)

#### C-14 의 근거 — 판단 축은 비용이 아니라 운영 부담 (D4-b 해소)

**실측 (2026-08-07~09)**
```
앱 Redis (mp-redis)                        자체운영 실물 = 5 파드
  used_memory   2.89 MB (피크 2.98MB)        mp-redis-0 (master)  4m /  14Mi
  keys          6 (그중 4개 TTL)              mp-redis-1 (replica) 4m /  12Mi
  ops/s         6                            mp-redis-s-0/1/2     3m / ~29Mi ×3
  clients       9                                                ─────────────
  aof_enabled   0  ← 영속성 없음                                  17m / 114Mi
  version       7.2.3 (standalone)
```
실제 키 = `video:recipe:<youtube-url>`×4(Gemini 추출 캐시) · `retail:deals:active`·`:detail`(딜 캐시).
코드상 패턴 = `ocr:job:{}` `video:job:{}`(잡 상태) · **`video:lock:{}`(락)** · `price:current:{}` `price:hotdeals:{}`.
쓰는 서비스 5종 = `chat` `ocr` `operations` `price` `video`. 명령은 **GET·SET·EXPIRE·TTL·DELETE·RPUSH·pipeline** 뿐(전부 코어).

→ 🔴 **내용물이 전부 재생성 가능한 캐시 + 단기 잡상태다.** 예외는 `video:lock` — 잃으면 **중복 Gemini 호출 = 중복 과금**.

**결정 축 = Sentinel 을 계속 안고 갈 것인가**
> 이 Sentinel 은 이미 우리를 한 번 물었다 — *"master **Service** 는 노드 상실 국면에서 갱신되지 않는다(오퍼레이터가 ordinal-0 고집)"* (실측 4라운드). 그 우회 코드가 **프로덕션에 남아 있다**(`chat/app/db.py:48-51` · `price/app/db.py:35-38`).
> 자체운영 유지의 비용은 "파드 5개"가 아니라 **이미 아팠고 흉터가 코드에 있는 컴포넌트를 계속 운영하는 것**이다.

**🟢 코드 변경 0줄** — 비-Sentinel 폴백이 **이미 기본값**이다:
`chat/db.py:50-53` · `price/db.py:37-40` · `pipelines/stream/_redis.py:25-29` · `ingest/refresh_price_matview.py:27-40` 전부 `if settings.redis_sentinels: … else Redis(host, port)`. **`video`·`ocr` 은 애초에 Sentinel 미사용**(`video/store.py:24`).
→ ConfigMap 에서 `REDIS_SENTINELS` 를 비우고 **`rollout restart`**(🔴 `envFrom.configMapRef` 는 파드 기동 시 주입).

**엔진 = Valkey 인 이유** — ElastiCache 는 *서비스*(그릇), Valkey/Redis OSS/Memcached 는 *엔진*(내용물)이다. Valkey 는 2024년 라이선스 변경 때 Redis 7.2.4 에서 갈라진 포크(리눅스 재단)로 **프로토콜·코어 명령 호환**이다. 우리 온프렘이 **7.2.3** 이고 쓰는 명령이 전부 코어라 위험이 없다. **Redis OSS 대비 20% 저렴**하고 AWS 가 미는 방향이다.
🟡 대가 = **사이트별 엔진이 갈린다**(온프렘 Redis 7.2.3 / AWS Valkey). 온프렘은 DR 전용이고 내용물이 캐시라 문제 지점이 없다.

**💰 비용 — ⚠️ 추정. 서울 리전 단가 미검증**(AWS API 호출 금지)
| 구성 | 월 | 근거 |
|---|---|---|
| `cache.t4g.micro` Valkey 1대 | ~$10~11 | $0.0128/hr(us-east-1) × 730h = $9.34 + 서울 프리미엄 10~20% |
| **Multi-AZ 2대 (채택)** | **~$21~22** | 위 × 2 |
| (Redis OSS 로 갈 경우) | ~$26~27 | Valkey 대비 +20% |

D10 실측 $678/mo 대비 **3.2%** — 비용은 지배 요인이 아니다.

**2노드를 고른 이유** — 단일 노드면 월 $11 을 아끼지만 노드 장애 시 **진행 중 OCR·video 잡 상태와 `video:lock` 이 통째로 날아간다**(유저는 폴링하다 404). `video:lock` 소실은 **중복 Gemini 과금**이라 그 차액을 상쇄할 수 있다. 게다가 온프렘 현행이 이미 HA 라 **가용성을 낮추는 결정에는 $11 로는 정당화가 부족**하다.

🔴 **선행 = 1-14 (선택 아님)**
`video/app/store.py:33-39` `put_job`/`get_job` 에 **try/except 가 없다**(docstring:7 *"실패해야 정직하다"* = 의도). 호출부 `main.py:202`(POST)·`main.py:210`(GET) 무방비 →
> **Multi-AZ 자동 failover 는 "장애를 자동으로 넘긴다"는 뜻이지 "클라이언트가 아무것도 못 느낀다"는 뜻이 아니다.** 전환 순간 연결은 끊긴다. 1-14 를 안 고치면 **관리형으로 옮긴 대가로 하드 500 을 얻는다.**

🟡 함께 볼 것 = **1-15**(`chat/db.py:51-53`·`price/db.py:38-40` 소켓 타임아웃 미설정 — video/ocr 은 3s, pipelines 5s).

🟢 **부수 효과** — C-8④ quorum-3 컴포넌트가 **3개 → 2개**(Kafka·ES)로 준다. **AZ 3 결정 자체는 안 바뀌지만 Redis 가 AZ 배치 제약에서 빠진다.**

🔴 **포기하는 것**
- **온프렘 DR Redis 에 HA 가 없어진다**(5파드 → 1파드). 그 파드가 죽으면 DR 중 chat·ocr·video 가 열화된다 — **degraded 사이트라 감수**한다는 판단이다
- **encryption-in-transit·AUTH 는 꺼진 채로 간다.** 켜려면 **8파일 50~70줄**(지원 코드 0건, 별건). VPC 안 평문이고 보호는 **보안그룹**이 맡는다 — 온프렘 netpol 역할의 대체다. 0-15(ES PoLP)와 같은 성격의 부채가 하나 남는다
- **AWS 락인** — 다만 Redis 프로토콜 호환이라 강도는 약하다(엔드포인트만 바꾸면 되돌아온다)
- **`mp-redis-pgsync` 는 대상 밖** — **383 ops/s** 로 앱 Redis(6)의 **64배**다. 관리형에 얹으면 비용·AZ 홉만 는다 → **자체운영 유지**
- 비용이 **추정치**다

#### C-12 의 근거 — 루프를 **구조로** 막는다 (가-1 해소)

접두사는 미관이 아니라 **출처 표시**다. MM2 는 *"접두사가 붙어 있다 = 남이 복제해 온 것"* 으로 보고 되돌려 보내지 않는다.

⚠️ **2026-08-07 근거 정정** — 아래 루프 논거는 **C-13 이후 부차적**이 됐다. C-13 으로 MM2 가 **단방향 1개**가 되면서 루프는 구조적으로 불가능해졌기 때문이다.
남은 주 근거는 **출처 표시**(AWS 브로커에서 자생/복제분 구분)와 **되돌리기 비용**(토픽명 변경 = 컨슈머 오프셋 초기화)이다. 그래도 유지한다 — 나중에 역방향 MM2 가 필요해져도 구조적으로 안전한 상태로 남는다.

🔴 **(당시 논거) #557 이 역방향을 만든 순간 루프는 실현 가능한 사고가 됐다.**
토픽 집합이 겹치지 않아 Identity 로도 *이론상* 되지만, 역방향 패턴을 `recipe.review.*` 로 쓰는 순간(**누구나 쓸 법한 형태다**) 정방향이 만든 `recipe.review.raw` 까지 집어가 무한 루프가 된다.

```
Identity + 패턴 실수                    Default(접두사) — 같은 실수를 해도
 [온프렘] recipe.review.raw              [온프렘] recipe.review.raw
    ▲            ↓ 정방향                            ↓ 정방향
    │      [AWS] recipe.review.raw       [AWS] onprem.recipe.review.raw
    └── 역방향이 이것도 집어감                  ↑ 접두사 있음 → MM2 가 제외
        🔴 무한 루프 · 양쪽 디스크 폭주          🟢 루프 없음
```

**안전이 어디 걸려 있나** — Identity = 설정을 정확히 쓰는 사람 / Default = 도구의 구조. **MM2 는 팀이 처음 운영하는 컴포넌트**라 후자를 고른다.

**비용 실측 — 사실상 0**
| | |
|---|---|
| 앱 코드 | 🟢 **0줄** — `_topics.py` 가 전부 `os.environ` 조회라 ConfigMap 값만 바뀐다 |
| 알림 규칙 | 🟢 **0건** — PrometheusRule 에 토픽 이름 등장 **0회**(컨슈머 그룹 기준으로 짜여 있다) |
| DLQ 이름 | 🟢 **자동** — `_dlq.py:112` `dlq_topic() = f"{topic}.dlq"` 파생 |
| KEDA ScaledObject | 🟡 4개 (`retail.crawl.raw`·`recipe.crawl.raw`·`retail.deal.raw` + 신규 review-refiner). `events.user.activity` 는 AWS 자생이라 그대로 |
| KafkaTopic CR (AWS) | 🟡 8개 (복제 4 + DLQ 4) · ConfigMap `mp-pipeline-env` |

🟢 **부수 이득 — 이름이 문서가 된다.** AWS 브로커 목록에서 자생/복제분이 한눈에 갈린다(`events.user.activity` vs `onprem.retail.crawl.raw`). 장애 대응 때 출처를 이름만 보고 안다.

🔴 **함정 3건**
1. **Strimzi 기본값이 위험한 쪽이다** — `topicsPattern` 미지정이면 사실상 전부 복제 → 루프. **어느 안이든 패턴은 반드시 명시**
2. **Topic Operator 와의 관계** — MM2 가 타깃에 토픽을 자동 생성하는데 우리는 `KafkaTopic` CR 로 선언 관리 중이다(`kafka-entity-operator` 가동). 자동생성분을 선언에 넣을지 방치할지 정할 것
3. **MM2 내부 토픽** — `heartbeats` · `onprem.checkpoints.internal` · offset/config/status 3종이 자동 생성된다

🔴 **포기하는 것**
- 양쪽 이름이 다르다 → 런북·대시보드에 `retail.crawl.raw (온프렘) / onprem.retail.crawl.raw (AWS)` 병기 필요
- ~~역방향도 접두사가 붙는다~~ → **C-13 으로 무효**. 역방향은 복제하지 않으므로 온프렘 크롤러는 **AWS 원본 토픽 `recipe.review.requested` 를 그대로** 구독한다
- 🔴 **사실상 편도 결정** — 나중에 Identity 로 바꾸면 토픽명이 전부 바뀌어 **컨슈머 오프셋이 초기화**된다

#### C-13 의 근거 — MM2 는 단방향 1개 (가-3 해소 · D4-a 완결)

**근거의 출발점 = 클러스터에 설치된 CRD 스키마 실물**(Strimzi `1.1.0` · API `v1` · Kafka `4.3.0`). 문서 추론이 아니다.

```
spec.required      = [replicas, target, mirrors]
spec.target        ← 단수다. 리스트가 아니다
spec.mirrors[].source   각 미러는 source 만 가진다 — per-mirror targetCluster 가 없다
```
`spec.target` 공식 설명: *"The target Kafka cluster **is used by the underlying Kafka Connect framework for its internal topics**."*
필수 하위 = `alias · bootstrapServers · groupId · configStorageTopic · statusStorageTopic · offsetStorageTopic`

**이게 확정하는 것 2가지**
1. **하나의 MM2 = 타깃 하나, 소스 N개.** 양방향은 **CR 2개가 강제**된다 — 추측이 아니라 API 모양이다
2. 🔴 **Connect 의 내부 토픽(offset·status·config)이 `target` 에 산다** → 워커가 타깃에서 멀면 데이터뿐 아니라 **자기 부기(bookkeeping)가 전부 터널을 건넌다**. **워커는 타깃 옆에 있어야 한다**

**→ ① 정방향 MM2 는 AWS 에 둔다**(target=AWS). *"온프렘이 여유로우니 거기 두자"* 는 성립하지 않는다 — 뇌를 몸에서 떼는 구조가 된다.

**→ ② 역방향은 MM2 를 안 쓴다.** CR 2개가 강제되면 역방향에 **Connect 클러스터가 통째로** 드는데, 역방향 볼륨은 **월 2,000건 남짓·수백 KB**(신규 164~407/회차 + 갱신 ~692/월)다. JVM 1Gi 는 균형이 안 맞는다.

**대신 크로스터널 consume** — 온프렘 크롤러가 **AWS 브로커의 `recipe.review.requested` 를 직접 소비**한다.
```
[AWS] refiner·picker → recipe.review.requested (AWS Kafka)
                              ▲ ① consume (주 2회 CronJob · 잠깐만 붙는다)
[온프렘] poller-recipe-review ─┘
            └ 만개 크롤 → ② produce (LAN) → recipe.review.raw → MM2 → [AWS]
```
🟢 **읽기는 터널을 건너도 안전하다** — 메시지도 오프셋도 AWS 브로커에 있어, 끊기면 그 회차 쉬고 다음에 이어 읽는다. **유실 0**.
🟢 **덤** — 크롤러의 컨슈머 그룹 오프셋이 AWS 브로커에 생겨 **기존 kafka-exporter 가 그대로 랙을 본다**. 관측 배선 0.

**사이징**
| | 값 | 근거 |
|---|---|---|
| replicas | **1** (v1 에서 **필수 필드**라 명시해야 함) | 유실 0 · 공백 수 분 · 크롤은 일 1~2회 배치. D-rep 의 비동기 6종과 같은 논리 |
| 자원 | `requests: 100m / 1Gi` · `limits: memory 1Gi` (CPU limit 없음 — 프로젝트 관행) | 🔴 처리량이 아니라 **JVM 베이스라인**이 정한다. 실측 평균 **0.09 KB/s**(53MB/7일) · 피크 **~12 KB/s** |
| autoRestart | `mirrors.sourceConnector.autoRestart.{enabled,maxRestarts}` | 🔴 **spec 최상위가 아니라 커넥터별**이다(CRD 확인) |

**AWS 증분** = `0.1 core / 1Gi` = 클러스터 수요(9.86 core / 26.26GiB) 대비 **CPU +1.0% · 메모리 +3.8%**. 💰 달러는 **미검증**(D10 노드 사이징 선행 — 기존 노드 여유에 흡수되면 $0).

🔴 **감수·후속**
- **복제 랙 알림 신설 = 필수.** MM2 는 진행 관점의 단일 실패점이고, 죽으면 조용히 멈춘다
- *"크롤러는 로컬 브로커만 본다"* 는 규칙이 깨진다 → **크롤 잡 실패 원인에 "터널"이 추가**된다. 장애 대응 문서에 반영. ⚠️ 범위는 좁다 — 7종 중 1종, 그것도 **읽기에서만**
- `_kafka.py` 가 producer·consumer 에 같은 `BOOTSTRAP` 을 쓴다 → **consumer 에 bootstrap 주입 필요(5~10줄)** + ConfigMap `KAFKA_BOOTSTRAP_REQUESTS`
- 🟡 **이 컨슈머의 DLQ 를 어느 브로커에 둘지 미결** — `_dlq.py` 는 producer 를 쓰므로 기본값이면 온프렘에 떨어진다
- 1Gi 는 **추정**이다. 라이브 후 실측으로 조인다

🟢 **덤 (별건 권장)** — 온프렘 retention **7일 → 30일**. 실측 53MB/7일이라 30일이어도 **~227MB**, 프로비저닝 20Gi 의 약 1%다. **터널 단절 내성이 4배가 되는데 비용이 사실상 0**이다.

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

✅ **가-1·가-3 도 해소** — C-12(복제 정책) · C-13(사이징·배치). **D4-a 완결.**
🟡 **"페일오버 후 파이프라인까지 온프렘에서 돌릴지"는 지금 안 정한다** — Kafka 를 남기면 그 선택지가 열린 채 유지되므로 DR 런북(2-6·D6) 때 정한다.

#### C-10 의 귀결
온프렘·AWS 양쪽이 같은 오퍼레이터(Strimzi)를 쓰므로 **MirrorMaker 2(Kafka↔Kafka 전용)가 선택지로 열린다** — MSK 였다면 설정이 달라지고, SQS 였다면 MM2 자체가 성립하지 않는다.
MM2 채택·사이징은 **C-13 으로 확정**됐다.

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
| ~~**Redis Sentinel**~~ | ~~3~~ | ~~2/3~~ | — | ⚠️ **C-14 로 제외** — ElastiCache 전환으로 quorum-3 대상이 아니다. AZ 3 결정 자체는 Kafka·ES 로 유지 |
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
| ~~D-ing~~ | ~~AWS 유입~~ | → **C-26 으로 확정** (2026-08-09) — Cloudflare(주황) → **NLB TCP:443 패스스루** → Istio GW · ALB 미채택 | ✅ |
| ~~D4-a~~ | ~~파이프라인 배치~~ | → **C-11·C-12·C-13 으로 확정** (2026-08-07) — 온프렘 7 / AWS 16 · 운반 = MM2 단방향 | ✅ |
| ~~D4-b~~ | ~~Redis~~ | → **C-14 로 확정** (2026-08-09) — ElastiCache for Valkey `cache.t4g.micro` Multi-AZ 2노드 | ✅ |
| ~~D4-c~~ | ~~Kafka~~ | → **C-10 으로 확정** (2026-08-07) | ✅ |
| ~~D4-d~~ | ~~ES·PG~~ | → **C-15 로 확정** (2026-08-09) — CNPG·ECK 유지 | ✅ |
| ~~D5~~ | ~~스토리지~~ | → **C-16 ~ C-21 로 확정** (2026-08-09) — PVC 352→125 GiB · EFS 불채택 · MinIO 삭제 · kubecost EC2 · AZ당 1개 | ✅ |
| D6 | 배포 전략 | 클러스터=Blue-Green / 앱=Canary 유지(ADR-0001) | 🔴 **질문 자체가 미정의** — 아래 |
| ~~D7~~ | ~~비밀 백엔드~~ | → **C-23 으로 확정** (2026-08-09) — 양 사이트 독립 · AWS=SSM+IRSA / 온프렘=현행 유지 · PushSecret 미채택 | ✅ |
| ~~D8~~ | ~~관측 스택~~ | → **C-22 로 확정** (2026-08-09) — 양 사이트 자체 유지 · AMP·AMG 미채택 | ✅ |
| **D8-r** | **Prometheus replicas (AWS 쪽)** | 🔴 **잠정 = 1 유지.** 이관 전 재결정 — 아래 | 🔴 **이관 전 결정** |

##### D8-r 배경 (2026-08-09) — 왜 지금 확정하지 않았나

C-22 의 "포기하는 것" 중 **가장 아픈 항목(관측 데이터가 단일 노드와 운명을 같이한다)** 을 지울 수 있는 유일한 수단이다.
사용자 결정 = **일단 1 로 두고 이관 전에 확실히 정한다.**

```
  ▸ Prometheus 는 정족수형이 아니다 — ES·Kafka 와 다르다
      각 replica 가 73 타깃 **전부를 독립적으로** 긁어 완전한 사본을 만든다.
      리더도 투표도 없다 ⇒ replica 하나하나가 이미 완전본
      ⇒ AZ 1개 상실 대비에는 **2 면 충분하고 3 은 낭비**다
        (3 은 "AZ 2개 동시 상실" 만 추가로 막는데 우리 설계 기준점이 아니다)
```

🔴 **replicas 만 2 로 올리면 작동하지 않는다 — 셋이 같이 바뀌어야 한다** (라이브 CR 실측):
```
  현재  replicas: 1
        nodeSelector: { topology.kubernetes.io/zone: host-b }   ← 둘 다 여기로 간다
        affinity: podAntiAffinity **preferred**(soft) · topologyKey **hostname**(zone 아님)
        retentionSize: 없음 · externalLabels: 없음
  필요  ① replicas 2  ② nodeSelector 제거(= 0-5)  ③ zone 축 TSC(maxSkew 1 · DoNotSchedule)
  ※ Alertmanager 도 같은 nodeSelector 다 — 함께 처리한다(gossip 지원)
```

🔴 **비용을 처음에 과소평가했다 — `+20 GiB` 가 아니다.** replica 는 완전본이라 **전부가 2배**다:

| | 1 replica | 2 replicas |
|---|---|---|
| PVC | 20 GiB | **40 GiB** (+$1.82/월, 단가 미검증) |
| 메모리 피크 | 1.61 GiB | 🔴 **약 3.2 GiB** |
| 스크레이프 | 73 타깃 × 1 | 🔴 **73 타깃 × 2** (대상 파드 CPU 도 함께) |

→ **온프렘은 replicas 1 을 유지한다**(메모리 limits 가 이미 94/112/154/127% 초과커밋 · DR 이라 손실이 프로덕션보다 작다).
→ **AWS 는 노드를 새로 사므로 D10 사이징의 입력값**이다. **D10 확정 시 같이 판정한다.**
| ~~S4~~ | ~~AWS 계정 보안~~ | → **C-24·C-25 로 확정** (2026-08-09) — 신원-B(Access Entry kubernetesGroups + 커스텀 롤 · Pod Identity) · 보안-B | ✅ |
| D10 | 비용 | 실측 $678/mo → GitLab EC2 포함 시 **~$715~750** (목표 $219 의 3.3~3.4배) | 🔴 **분모 근거 소실 — 아래** |

##### 🔴 D10 경고 (2026-08-09) — 이 문서의 비용 논거 전체가 검증 불가 상태다

```
   grep '678'  → 1건 (checklist:152 그 줄뿐)
   grep '219'  → 1건 (동상)
   라인아이템  → 🔴 어느 문서에도 없다

   이 분모에 기대는 안건:  D6(클러스터 2벌 +$607~730) · D8(AMP 전환) · D-ing(ALB vs NLB) · D-rep(노드 사이징)
```
**D10 은 "아직 안 쟀다"가 아니라 "쟀다고 적혀 있는데 근거가 없다"** 이다. 두 조각으로 나눠 처리한다 —
**수량**(인스턴스·EBS GiB·전송량)은 클러스터 실측 + C-16 으로 **지금 확정 가능**하고,
**단가**는 🔴 이번 조사 3세션이 전부 재조회에 실패했다(가격 페이지 JS 렌더 / calculator JSON 404 / Bulk API 는 자격증명 필요) → **0-25**.
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
                                            │
                                    정방향   │  ╌╌ Tailscale ╌╌
                                            ▼
                              [ MirrorMaker 2 · 단방향 1개 ]  🔴 AWS 배치 (C-13)
                                            │      Connect 내부 토픽이 target 에 살아서다
                                            ▼
[AWS] Kafka(정본 · Strimzi C-10) ──→ 리파이너 6종 → PG·ES·Redis
        │
        └ recipe.review.requested ←── 온프렘 크롤러가 **직접 consume** (C-13)
                                       MM2 역방향 없음 · 주 2회 CronJob 이 잠깐 붙는다
```

- **비대칭 원칙** — *produce 는 로컬에서, consume 은 터널 너머로.* 컨슈머는 오프셋이 브로커(서버)에 있어 끊겨도 그 자리에서 이어간다.
  ⚠️ **MM2 자체에는 이 원칙이 약하게만 적용된다** — MM2 는 Connect 라 produce 실패 시 소스 오프셋을 전진시키지 않고 task 가 FAILED 로 죽는다(**시끄럽고 유실 없음**). MM2 를 AWS 에 두는 진짜 이유는 **Connect 내부 토픽이 target 에 살기 때문**이다(C-13).
  🔴 반면 **크롤러에는 이 원칙이 그대로 적용된다** — 원본이 웹페이지라 이미 사라졌고 delivery 콜백도 없어 조용히 유실된다(0-24)
- 🟢 **온프렘 신규 컴포넌트 0** — 브로커는 이미 있고 MM2 는 AWS 쪽이다. 역방향도 컴포넌트 없이 크로스터널 consume 으로 푼다(C-13)
- **온프렘 경유 토픽 4종** = `retail.crawl.raw` · `retail.deal.raw` · `recipe.crawl.raw` · 🆕 `recipe.review.raw`. AWS 자생(`events.user.activity` · `price.anomaly.detected`)은 온프렘을 안 거친다
- 🔴 **복제지 이동이 아니다** — 원본은 온프렘에 7일 남는다. AWS 쪽이 잘못돼도 그 안이면 다시 흘릴 수 있다

🔴 **포기·감수**
- MM2 는 **진행 관점의 단일 실패점** — 죽으면 조용히 멈춘다. **복제 랙 알림 신설 필수**(선택 아님)
- 온프렘 Kafka 3 브로커 부양 — 달러 비용 0이나 **DR 용 존치 전제**가 깨지면 계산이 바뀐다
- 🔴 **0-24(#558)가 선행** — MM2 를 넣어도 크롤러→로컬 브로커 구간의 produce 실패는 그대로 조용하다

#### D4-a 전체 흐름도 (C-11 확정 반영)

```
                        ┌─────────── 외부 사이트 ───────────┐
                        │ 마켓컬리 · 오아시스 · 만개의레시피 │
                        └───────────────┬───────────────────┘
                                        │ 가정용 IP ← 온프렘 잔류의 유일한 근거
╔═══════ 온프렘 (C-3 ② 크롤 프로덕션 · C-11) ═╪══════════════════════════════╗
║                                        ▼                                    ║
║  외부 크롤 CronJob 7종 (23 중 7)                                            ║
║  ├ mp-poller-kurly          03:30 매일  ─┐                                 ║
║  ├ mp-poller-oasis-dawn     04:10 매일   ├→ retail.crawl.raw               ║
║  ├ mp-poller-oasis-noon     13:10 매일  ─┘                                 ║
║  ├ mp-poller-deal-timesale  15:05 매일  ─┐                                 ║
║  ├ mp-poller-deal-closesale 17:05 매일  ─┴→ retail.deal.raw                ║
║  ├ mp-poller-recipe         05:00 일·수 ──→ recipe.crawl.raw               ║
║  └ mp-poller-recipe-review  06:00 일·수 ──→ recipe.review.raw    (#557)    ║
║         ▲                                                                   ║
║         └── consume ──→ [AWS Kafka] recipe.review.requested   (C-13)        ║
║              터널 너머로 직접 읽는다 · MM2 역방향 없음 · 주 2회 CronJob      ║
║                                                                             ║
║  ┌──── Kafka 3 브로커 (Strimzi · RF=3 · 49m CPU / 2.4Gi / 실사용 81MB) ──┐ ║
║  │  🟢 모든 produce 가 LAN. acks=all·RF=3 → 이 시점에 내구성 확보         │ ║
║  │  🟢 원본은 retention 7일 유지 (복제지 이동이 아니다)                   │ ║
║  └────────────────────────────┬──────────────────────────────────────────┘ ║
╚═══════════════════════════════╪═════════════════════════════════════════════╝
                                │ Tailscale · 4.7 MB/일
              ┌─────────────────┴──────────────────┐
              │   MirrorMaker 2 · 단방향 1개       │  🔴 AWS 배치 (C-13)
              │   ↓ 수집결과 4종만                  │  Connect 내부토픽이 target 에 산다
              └─────────────────┬──────────────────┘
╔═══════ AWS prod (EKS · ap-northeast-2) ══╪═════════════════════════════════╗
║  ┌──── Kafka 3 브로커 = 정본 (Strimzi 자체운영 · C-10 · AZ 3분산) ───────┐ ║
║  │  ← 복제분 4종        │  AWS 자생 2종: events.user.activity            │ ║
║  │                      │                price.anomaly.detected          │ ║
║  └──┬────────┬─────────┬────────┬──────────┬────────────────────────────┘ ║
║     │        │         │        │          │                              ║
║  retail-  recipe-  review-  user-event-  deal-      price-anomaly-        ║
║  refiner  refiner  refiner🆕  sink       notifier   notifier              ║
║  KEDA0-3  KEDA0-3  KEDA0-3   KEDA0-3     KEDA0-2    static 1              ║
║     └────────┴─────────┴────────┴──────────┴────────→  PG · ES · Redis    ║
║                                                            ▲              ║
║  내부 배치 CronJob 10종 (외부망 불요 · PG/ES 옆) ──────────┘              ║
║  price-matview 매시 · price-anomaly 04:40 · user-data-pruner 04:30        ║
║  pantry-expire 일 05:30 · chat-insights 06:00 · data-invariants 월 06:00  ║
║  deal-pruner 10분 · es-recipes 일·수 · score-review-sentiment 07:00       ║
║  summarize-reviews 08:00                    └ 뒤 2종은 Bedrock nova-micro ║
║                                                                           ║
║  review-refresh-picker 🆕 (PG 조회 → recipe.review.requested 발행)         ║
║        └ 이 토픽은 복제되지 않는다. 온프렘 크롤러가 여기로 읽으러 온다     ║
╚═══════════════════════════════════════════════════════════════════════════╝

  배치 요약   온프렘 7 (크롤만)  /  AWS 16 (리파이너·컨슈머 6 + 내부배치 10)
  원칙        PG 를 읽고 쓰는 코드는 PG 옆에, 크롤하는 코드는 IP 가 필요한 곳에
              그 둘을 Kafka 가 잇는다
```

🔴 **확정 전 필요한 결정 3건**
| | 내용 |
|---|---|
| ~~가-1~~ | → **C-12 로 확정** (2026-08-07) — `DefaultReplicationPolicy` · 별칭 `onprem` |
| ~~가-2~~ | → **C-11 로 확정** (2026-08-07) — 3 브로커 RF=3 존치 |
| ~~가-3~~ | → **C-13 으로 확정** (2026-08-07) — 정방향 1개·AWS·replicas 1·100m/1Gi. 역방향은 크로스터널 consume |

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

> 🔴 **이 그림이 확정 결정(§0.1)의 시각적 정본이자 설계도다.**
> 새 결정이 나오면 **지우고 다시 그리지 말고 얹는다.** 각 요소 옆 `(C-n)` 이 근거 결정이다.
> 반영 범위 = **C-1 ~ C-26** (2026-08-09).

```
                                    ┌─────────────┐
                              유저 ─┤ Cloudflare  │  DNS(C-4) + 프록시(D-ing)
                                    │ WAF·DDoS·CDN│  · CNAME flattening
                                    └──────┬──────┘
════ AWS Organizations ══════════════════  │  ═══════════════════════════════
                                           │
 ┌─ management 계정 ─┐  ┌─ security 계정 ─┐ │
 │ SSO · SCP        │  │ CloudTrail 로그 │ │   (C-8②) 계정 3개
 │ Budgets · 결제   │  │ S3 Object Lock  │ │
 └──────────────────┘  └─────────────────┘ │
                                           │
 ┌─ prod 계정 ═ VPC 10.10.0.0/16 (ap-northeast-2) ═══════════════════════┐
 │                             [IGW]                                     │
 │                               │                                       │
 │   ┌──── NLB 1개 TCP:443 패스스루 (internet-facing) ──┐  (C-9·C-26)    │
 │   │  ENI●(AZ-a)     ENI●(AZ-b)     ENI●(AZ-c)      │  🔴 SG=CF 대역   │
 │   └───────────────────────┬─────────────────────────┘  target=instance│
 │                           │  ※ LB 는 1개. AZ 마다 "발"만 있다         │
 │                           │  🔴 봉투를 안 뜯는다 → SNI 가 GW 까지 간다│
 │                           │     TLS 종단 = Istio GW (온프렘과 동일)   │
 │                           │     ALB 미채택 — 뜯어서 얻을 게 없다      │
 │  ┌─ AZ-a ─────────┐ ┌─ AZ-b ─────────┐ ┌─ AZ-c ─────────┐           │
 │  │ public /24     │ │ public /24     │ │ public /24     │           │
 │  │  NAT GW ●      │ │                │ │                │  (C-8⑥)   │
 │  │  rt: 0/0 → IGW │ │  rt: 0/0 → IGW │ │  rt: 0/0 → IGW │  NAT 1개   │
 │  ├────────────────┤ ├────────────────┤ ├────────────────┤           │
 │  │ private /24    │ │ private /24    │ │ private /24    │           │
 │  │  EC2 노드 ●    │ │  EC2 노드 ●    │ │  EC2 노드 ●    │           │
 │  │   └ Istio GW   │ │                │ │                │           │
 │  │   └ 파드10.20.x│ │   └ 파드10.20.x│ │   └ 파드10.20.x│  (C-7)     │
 │  │                │ │                │ │                │  overlay   │
 │  │  kafka-0  10Gi │ │  kafka-1  10Gi │ │  kafka-2  10Gi │  🔴 정족수 │
 │  │  es-0      8Gi │ │  es-1      8Gi │ │  es-2      8Gi │  AZ당 1개  │
 │  │  pg-1  10+4Gi  │ │  pg-2  10+4Gi  │ │  pg-3  10+4Gi  │  (C-21)    │
 │  │   └ CNPG(C-15) │ │   └ CNPG       │ │   └ CNPG       │  PG 2→3    │
 │  │   └ ECK (C-15) │ │   └ ECK        │ │   └ ECK        │           │
 │  │  노드EBS 60Gi  │ │  노드EBS 60Gi  │ │  노드EBS 60Gi  │  (C-16)    │
 │  │  rt: 0/0 → NAT │ │  rt: 0/0 → NAT │ │  rt: 0/0 → NAT │           │
 │  └────────────────┘ └────────────────┘ └────────────────┘           │
 │   ※ EBS 는 한 AZ 에만 존재한다 → AZ 상실 = 결정론적 Pending (0-7)   │
 │                                                                       │
 │  ═══ 데이터 티어 — 정본은 자체운영 / 파생은 비용이 정한다 (C-15) ═══  │
 │                                                                       │
 │  PG    = CNPG 자체운영   (C-15)                                       │
 │          ← RDS 는 외부 self-managed 로 물리복제 불가 → C-3 이 무너짐  │
 │  ES    = ECK  자체운영   (C-15)  · 커스텀 nori 이미지                 │
 │          ← 파생(24MB). OpenSearch 는 코드교체 + ~$79/mo               │
 │  Redis = ElastiCache for Valkey 관리형  (C-14)                        │
 │          t4g.micro · Multi-AZ 2노드 · 파드 없음 · Sentinel 없음       │
 │          ← 캐시(파생) · DR 요구 없음 · Sentinel 운영이 아팠다         │
 │  Kafka = Strimzi 자체운영  (C-10) · MM2 1개 replicas1 100m/1Gi (C-13) │
 │     자생 2종  events.user.activity · price.anomaly.detected           │
 │     복제 4종  onprem.retail.crawl.raw · onprem.retail.deal.raw        │
 │              onprem.recipe.crawl.raw · onprem.recipe.review.raw       │
 │              └ `onprem.` 접두사 = DefaultReplicationPolicy  (C-12)    │
 │     비복제    recipe.review.requested → 온프렘이 읽으러 온다 (C-13)   │
 │                                                                       │
 │  ═══ 스토리지 — 352 → 125 GiB (C-16) · EFS 미도입 (C-17) ═══════════  │
 │                                                                       │
 │  EBS gp3   PVC 125 GiB   PG 42 · ES 24 · Kafka 30 · Prom 20           │
 │                          · AM 1 · Loki 4 · Tempo 4                    │
 │            노드 60 GiB × N   ← 🔴 종전 계획서에서 누락돼 있던 항목    │
 │            총 385 GiB(워커 4) ← A 그대로면 712 GiB. 실사용은 106.9    │
 │  S3        Loki 청크 · Tempo 블록 · barman WAL · 온사이트 덤프        │
 │            🔴 온사이트 덤프는 barman 과 다른 버킷/계정   (C-18)      │
 │  ❌ MinIO  삭제 (C-18) — 실사용 1.3% · SPOF · 앱 코드 0줄             │
 │  ❌ kubecost 클러스터 밖 EC2 (C-19) — 디스크 20 GiB · agent 만 잔류   │
 │  ❌ EFS    미도입 (C-17) — RWX 0건 · PVC 21/21 이 소비자 1개          │
 │  ranker.pkl → 이미지에 굽는다 (C-20) · pipeline PVC → 온프렘 잔류     │
 │                                                                       │
 │  ═══ 관측 — 양 사이트 자체 유지 (C-22) · AMP·AMG 미채택 ═══════════   │
 │                                                                       │
 │  kube-prometheus-stack 87.20.0 + Loki + Tempo + Alloy                 │
 │     Prometheus replicas 1 (잠정) — 🔴 D8-r 로 이관 전 재결정          │
 │     externalLabels.site = aws  ← 두 번째 사이트 생기기 전에 필수      │
 │     ← AMP 는 메트릭 전용. 옮겨도 알림·로그·트레이스는 우리 몫         │
 │     ← 확정 단가만 월 $367 · 알림 두뇌가 AWS 면 DR 을 못 감시          │
 │                                                                       │
 │  ═══ 비밀 — 양 사이트 독립 (C-23) · PushSecret 미채택 ═════════════   │
 │                                                                       │
 │  ESO → SSM standard 번들 6 (/mp/prod/*) · 인증 = IRSA                 │
 │     remoteRef 70엔트리 무수정 (gjson property · 메타문자 0건)         │
 │     🔴 스토어에 spec.provider.aws.prefix: /mp/prod/ 필수              │
 │     정적 AWS 키 = 0  (0-16 과 한 묶음)                                │
 │                                                                       │
 │  ═══ 신원·보안 (C-24 · C-25) ══════════════════════════════════       │
 │                                                                       │
 │  사람  IAM Identity Center ─ 권한세트 6종 ─ EKS Access Entry          │
 │          kubernetesGroups: [mp:app-dev …] ─► 우리 커스텀 ClusterRole  │
 │          ★ 온프렘과 **같은 정의** (C-3 상시증명이 권한까지)           │
 │          🔴 관리형 access policy 미채택 — 수정·자체생성 불가라        │
 │             serviceaccounts impersonate·pods/exec 를 영원히 못 뺀다   │
 │  파드  Pod Identity (IRSA 미채택 — OIDC URL 에 안 묶임 · C-8 destroy) │
 │          🔴 association 은 **특정 SA 에만** · 롤 자체도 최소권한      │
 │             ∵ pods create 는 못 뺀다 → 띄워도 딸 게 없게 (2층 방어)   │
 │  break-glass  🔴 Identity Center **밖** — root 봉인 + mp-breakglass 롤│
 │  보안  CloudTrail org trail(첫 사본 $0) · KMS · SCP · GuardDuty       │
 │          · Security Hub Essentials    ❌ Config · Runtime 미채택      │
 │                                                                       │
 │  [VPC 엔드포인트]  S3(Gateway·무료) · ECR api/dkr · STS               │
 │  [EC2] GitLab (CI) (C-2)  ·  kubecost (C-19)                          │
 │  [ECR]  [S3 백업·Loki·Tempo]  [SSM 파라미터]                          │
 └───────────────────────────────────────────────────────────────────────┘
     ↕                  ▲                  ▼                  ▼
     │ Tailscale (C-6)  │ MM2 정방향       │ 크롤 요청         │ CNPG 물리복제
     │ · 내부도구 6종    │ 수집결과 4종      │ recipe.review.   │ (WAL) · 상시
     │   (C-9)          │ onprem.* 접두사   │ requested        │
     │ · 팀원 kubectl   │ (C-11·C-12·C-13) │ 크롤러가 AWS 로   │ (C-3 ①)
     │                  │ 4.7 MB/일        │ 직접 consume     │
     ▼                  │                  │ (C-13)           │
 ┌─ 온프렘 = ① DR 대기 + ② 크롤 상시 프로덕션 (C-3 이중역할) ───────────┐
 │  LAN 192.168.0.0/24 · 파드 10.244.0.0/16 · svc 10.96.0.0/12          │
 │                                                                      │
 │  ② 현역 — 평시에도 돈다. AWS 가 대신 못 한다            (C-11)       │
 │     크롤 CronJob 7종  kurly · oasis×2 · deal×2 · recipe              │
 │                       · recipe-review (#557)                         │
 │        └ 전부 LAN produce (acks=all·RF=3) → 코드 변경 0              │
 │        └ recipe-review 만 읽기를 AWS 에서 한다 (C-13)                │
 │     Kafka 3 브로커 (Strimzi · 실측 49m CPU / 2.4Gi / 로그 53MB)      │
 │        retail.crawl.raw · retail.deal.raw · recipe.crawl.raw         │
 │        · recipe.review.raw   (+ DLQ 4)   retention 7일 → 30일 검토   │
 │                                                                      │
 │  ① 대기 — 트래픽 0                                                   │
 │     앱 13종 상시 가동 (replica 1) · PG replica cluster (read-only)   │
 │     Redis 단일 파드 — Sentinel 제거 · HA 없음(degraded 감수) (C-14)  │
 │     cloudflared 터널 (평시 replicas 0 · 페일오버 시 기동)   (C-5)    │
 │     Harbor = ECR 미러 (DR 이미지 공급)                               │
 │                                                                      │
 │  ③ 관측 — 자체 유지 (C-22) · externalLabels.site = onprem            │
 │     Prometheus replicas 1 유지 (메모리 초과커밋 · DR 이라 손실 작다) │
 │     🔴 물리계층 9룰은 여기서만 볼 수 있다 — 도달성 아니라 장애도메인  │
 │        hypervisor 2(Proxmox) · 호스트 C 3(node·cadvisor·alloy)       │
 │                                                                      │
 │  ④ 비밀 — 현행 K8s provider 그대로 (C-23)                            │
 │     fb-secrets 6종 / 34키 / ESO 30 ExternalSecret                    │
 │     🔴 AWS 를 읽지도 쓰지도 않는다 — 두 사이트가 서로 무참조         │
 │     동기화 = "같아야 하는 17키" 수동 · 조용히 갈리는 7키 주의        │
 │        JWT_SECRET · OAuth 4 · Cloudflare 2  ← 페일오버 때만 드러난다 │
 │                                                                      │
 │  🔴 "standby 니까 꺼도 된다"로 읽으면 크롤이 통째로 멈춘다            │
 └──────────────────────────────────────────────────────────────────────┘

  CIDR 비충돌 (C-8③)
    AWS    VPC 10.10/16 · 파드 10.20/16 · svc 10.30/16
    온프렘  192.168.0.0/24 · 파드 10.244/16 · svc 10.96/12
    터널    Tailscale 100.64.0.0/10
```

**아직 이 그림에 없는 것** (결정되면 얹는다 — 남은 안건 2건)

| 안건 | 그림의 어디에 얹힐지 |
|---|---|
| **D6** 배포 전략 (클러스터 Blue-Green / 앱 Canary) | NLB ~ Istio GW 사이 |
| **D10** 노드 사이징 · 인스턴스 타입 | AZ 박스의 `EC2 노드 ●` |
| ↳ **D-rep** 앱 replica 정책 · **D8-r** Prometheus replicas | 동상 (둘 다 D10 확정 후) |

🟡 **파이프라인 워크로드 23종의 AWS 쪽 배치**(리파이너 6 + 내부 배치 CronJob 10)는 D4-a 로 확정됐지만 이 그림엔 요약만 있다. 전체 흐름도는 **§0.2 D4-a** 참조.

---

## Phase 0 — 이게 끝나야 AWS 착수

### 0-A. 차단 — 안 고치면 EKS 에서 앱이 안 뜬다

- [ ] **0-1 config 레포 eks 분기 골격** — services 13종 외 전 트랙(pipelines·platform·monitoring·gateway·argocd 44개)이 분기 수단 자체가 없음 〔감사 #25 #13 #2〕
- [ ] **0-2 ESO 스토어 추상화** — `fb-kubernetes` 23파일 하드코딩, eks 패치 0건 → 시크릿 30종 전건 NotReady 〔#23 #83〕
      🔴 **C-23 확정으로 범위가 좁아졌다(2026-08-09)** — `secretStoreRef.name` **한 필드만** 오버레이 분기하면 된다.
      `remoteRef` 70엔트리는 **한 글자도 안 바꾼다**(AWS provider 의 gjson property 지원 + property 이름에 메타문자 0건 확인).
      🔴 **AWS 스토어에 `spec.provider.aws.prefix: /mp/prod/` 를 반드시 명시할 것** — 안 그러면
      "remoteRef 무수정"과 "IAM 경로 최소권한"이 양립하지 않아 **구현자가 70엔트리를 다시 쓰기 시작한다**.
      ⚠️ 이 작업량 추정은 **파일 레벨 미검증**(config 레포 클론이 이 머신에 없다) — C-23 비용 케이스의 최대 미검증 가정
- [ ] **0-3 Ansible 단독 → config 이관** — PriorityClass 3종(**워크로드 46개 참조**)·ResourceQuota 2·LimitRange 2·ns PSA·kube-prometheus-stack 전체 〔#20 #16〕
      🔴 **목록에 3종이 빠져 있었다** (2026-08-09 D8 실측) — ArgoCD **밖**(순수 Helm)인 것은 **4종**이다:
      `kube-prometheus-stack` · `observability/minio` · `kube-system/node-exporter` · **`kube-system/metrics-server`**.
      🔴 **특히 metrics-server** — EKS 가 기본 제공하지 않는데 **라이브 account HPA 가 여기 의존**한다.
      누락하면 **이관일에 HPA 가 조용히 죽는다**(파드는 뜨고 스케일만 안 된다)
- [ ] **0-3b 🔴 `externalLabels: {site: onprem|aws}` — 두 번째 사이트가 생기기 전에** (2026-08-09 신설)
      실측 **키 자체가 부재(ABSENT)** — "비어 있음"보다 나쁘다. `AlertmanagerConfig` CR **0개** · `remoteWrite` 도 ABSENT.
      C-22(양 사이트 자체 유지)를 골랐으므로 **두 사이트의 시계열을 구분할 축이 이것뿐**이다.
      🔴 사이트가 둘이 된 **뒤에** 붙이면 그 전 데이터는 site 없이 남아 영원히 섞인다. **어느 선택지를 골랐든 선행이었다**
- [ ] **0-3c 🔴 `mp-physical-layer` 9룰 + job 4종을 "온프렘 전용" 오버레이로 분리** (2026-08-09 신설)
      `hypervisor`(Proxmox 물리 2대) · `vm-node` · `vm-cadvisor` · `vm-alloy`(호스트 C). 현재 **사이트 구분 없이** 있어
      EKS 오버레이로 새면 **영구 TargetDown**. 15일 내 4건 실발화(TempCritical·TempHigh·DiskReadBurst·MpHostCDown)
- [ ] **0-4 ArgoCD 뿌리 IaC화** — AppProject 3·root Application 2·repo SSH 자격증명이 레포에 없음 〔#87 #77〕
- [ ] **0-5 nodeSelector 온프렘 라벨 제거** — 하드코딩 **13건**(실측) → EKS 에서 영구 Pending 〔#6 #21〕
      🔴 **성격별 3분류** (2026-08-09 정정 — "12+ 대공사"로 읽으면 부담이 실제보다 크게 잡힌다):
      **실작업 7** = zone 6(minio·es-es-a·es-es-b·prometheus·alertmanager·tempo) + hostname 1(loki) ·
      **온프렘 잔류 2** = bitrot-canary · **드롭 4** = kubecost(→ C-19 로 EC2 이동)
- [ ] **0-6 hard TSC 완화** — 노드 하한을 "워커 4대·AZ당 2대"로 못박아 비용 목표와 정면 충돌 〔#8 #19〕
      🔴 **목록에 `kafka-combined` 가 빠져 있었다** (2026-08-09 정정). Strimzi 는 StatefulSet 이 아니라
      **StrimziPodSet** 으로 파드를 만들어 `kubectl get deploy,sts` 계열 스캔에서 **구조적으로 사라진다** —
      하필 **정족수가 TSC 에 걸린 유일한 워크로드**였다. → 이런 집계는 앞으로 **파드 레벨**로 한다(CNPG 도 동일).
      실측 hard TSC = account(2)·recipe(2)·frontend(2)·gw-public(2)·**kafka-combined(3)**. Redis 2종은 C-14 로 소멸.
      🔴 **목표를 정확히**: `hostname` 축 hard→soft(`ScheduleAnyway`) · **`zone` 축은 soft 로 남기되 유지**.
      hard 를 풀면서 분산 의도는 보존해야 한다 — zone 축을 아예 지우면 replica 2 가 같은 AZ 에 뜬다(D-rep).
      C-8 ④(AZ 3) 와 D-rep 양쪽의 선행 조건이다.
- [ ] **0-7 `topology.kubernetes.io/zone` 강제 기록 제거** — EBS CSI 볼륨 토폴로지가 깨짐 〔#7〕
- [ ] **0-8 StorageClass 파라미터화** — 🔴 **집계 확정(2026-08-09)**: **필드 22 / 파일 13 / 라이브 오써링 오브젝트 12**.
      종전의 `5`·`13`·`15` 는 폐기한다. `5` 는 `mp_aws_migration_plan.md:372·434·459·488` + `mp_multicloud_plan.md:212`
      **5곳에 복제**돼 있어 함께 고쳐야 한다(하나만 고치면 다시 불일치)
      🔴 **SC 정의 파일 자체가 대상에서 빠져 있었다** — `k8s_storage/templates/storageclass.yaml.j2:13,28` 이
      SC 이름을 하드코딩하고 라이브 apply 된다. EKS 는 EBS CSI 애드온이라 `local.csi.openebs.io` SC 2종을 만들면 안 된다.
      **이 파일이 온프렘/AWS 오버레이의 분기점이다**
      🔴 **단일 패치가 성립하지 않는다 — SC 키가 스키마마다 다르다**:
      PVC·STS vct·Prometheus/Alertmanager CR·ECK = `spec.storageClassName` / CNPG = `spec.storage.storageClass`+`spec.walStorage.storageClass` /
      **Strimzi = `spec.storage.class`**(정규식 `storageclass` 에 안 걸림) / Loki = `singleBinary.persistence.storageClass` /
      Tempo = `persistence.storageClassName` / kubecost = `global.defaultStorageClass`
      🔴 **실행 비용이 무중단이 아니다** — PVC `storageClassName` 과 STS `volumeClaimTemplates` 는 **둘 다 immutable**.
      21 PVC 중 **9개가 STS vct 파생**(STS 7) → SC 를 바꾸면 `--cascade=orphan` 삭제 후 재생성이 필요하다
      (**Prometheus 7.7 GiB 이력**·Alertmanager·kubecost×2·ES×2·Loki·Tempo). **이관 시점이 유일한 무비용 창**
- [ ] **0-8b 🔴 PV reclaimPolicy 정책 실구현 — 의도와 실물이 다르다** (2026-08-09 신설)
      **라이브 21/21 이 `Delete`** 이고 `openebs-lvm-retain`(Retain) SC 는 **만들어져 있는데 소비자가 0** 이다.
      IaC 의도는 `storageclass.yaml.j2:2-4` 주석에 명시돼 있다 — *"PG·ES·Kafka = Retain. CR 을 실수로 지워도
      데이터가 즉사하지 않는 마지막 방어선"*. **방어선을 만들고 배선을 안 했다.**
      원인 = `openebs-lvm`(Delete)이 **default class** 라 `storageClassName` 을 명시하지 않으면 자동으로 위험한 쪽이 붙는다.
      🔴 **노출도가 비대칭**: Kafka 는 `deleteClaim:false` 로 오퍼레이터가 막아준다 / **ES 는 `volumeClaimDeletePolicy` 미설정**
      (ECK 기본 = DeleteOnScaledownAndClusterDeletion) · **CNPG 도 노출**. EKS 에서 이 비대칭을 재현할지 명시할 것.
      ※ 참고 — **기존 PV 의 `reclaimPolicy` 는 `kubectl patch` 로 바꿀 수 있다**(mutable). SC 의 것은 immutable
- [ ] **0-8c 🔴 `observability/loki` STS 의 PVC 보존 정책 `Delete/Delete` 제거** (2026-08-09 신설)
      **STS 11개 중 유일하다** (나머지 10개 전부 Retain/Retain — 실측). 우리가 설정한 게 아니라 **Loki Helm 차트 기본값**이다
      (라이브 `valuesObject` 에 해당 항목 없음). 여기에 Application `loki` = `{prune:true, selfHeal:true}` 와
      PV `reclaimPolicy: Delete` 가 겹쳐 **replica 0 만으로 PVC→PV→디스크가 연쇄 삭제되는 3단 체인**이 된다.
      **이 템플릿을 EBS 로 복제하면 안 된다**
- [ ] **0-8d 🔴 상한 없는 디스크 emptyDir 160개** (2026-08-09 신설) — emptyDir 197개 중 `medium=Memory` 33 ·
      `sizeLimit` 있음 **4** · **무제한 160**. 전부 노드 루트 볼륨에 얹힌다(argocd repo-server `helm-working-dir`,
      es `elasticsearch-logs`, mp-pgsync `checkpoint`, grafana `storage` 등). **노드 EBS 사이징(C-16)과 eviction 정책을
      동시에 결정하는 항목**이다
- [ ] **0-9 Harbor LAN IP(`192.168.0.10`) → 레지스트리 파라미터화** 〔#9〕
- [ ] **0-10 `validate.py` eks 렌더 대응** + LAN CIDR 제거 〔#3〕

> 🟢 **0-1~0-4 는 사실상 "config 레포 대공사" 한 덩어리**다. 따로 세면 4건이지만 작업 단위로는 하나로 잡는다.

### 0-B. 보안 PoLP — 온프렘에서 먼저여야 하는 이유가 명확한 것

- [ ] **0-11 ⭐ `fb-secrets` 원본 6종 인벤토리 git화 (SOPS/age)** — ESO 전체의 뿌리가 전 IaC 밖 수동 생성이고 **키 이름 목록조차 git 에 없다**. 그 머신이 죽으면 뭐가 있었는지도 모른다 〔#92〕
      🔴 **C-23 이 이걸 두 번째 이유로 승격시킨다(2026-08-09)** — 양 사이트 독립을 택했으므로 **드리프트를 막을 구조적 수단이 이것뿐**이다.
      *"secret 변경 시 양쪽 갱신"* 의 약한 고리 = **변화가 있었다는 걸 어떻게 아나** → 지금은 **사람 기억**이 유일하다.
      SOPS 로 커밋하면 **PR 이 곧 변경 신호**가 되고, 두 사이트 값이 같은 파일에 있어 **조용한 드리프트가 구조적으로 불가능**해진다.
      🔴 현 복구 경로 = **etcd 스냅샷 + aescbc 키 조합 단 하나**. `secrets_backup` 묶음에 **fb-secrets Secret 자체가 안 들어간다**.
      **etcd 보존 14일 = 시크릿의 실질 RPO** 다. age 개인키는 `secrets_backup` 묶음 + 오프라인 2곳
      (2026-07-29 passphrase 소실 전례가 있어 같은 묶음 단독 보관은 SPOF 를 상속한다)
- [ ] **0-11b 🔴 "두 사이트에서 같아야 하는 17키" 목록 명문화 — 특히 조용히 갈리는 7키** (2026-08-09 신설, C-23)
      37키를 실측 분류했다: **같아야 17 / 사이트별로 달라야 17 / 죽은 키 3**.
      🔴 **조용히 갈리는 7키** = `JWT_SECRET` · OAuth 4(`GOOGLE_CLIENT_ID/SECRET`·`KAKAO_CLIENT_ID/SECRET`) · Cloudflare 2(`API_TOKEN`·`TUNNEL_CREDS`).
      나머지 10키는 갈리면 **즉시 접속 실패**로 드러나지만, 이 7키는 **페일오버하는 그 순간에만** 드러난다
      (JWT_SECRET = **전 유저 로그아웃** · OAuth = 로그인 불가 · Cloudflare = 터널 미기동)
- [ ] **0-11c 죽은 키 3개 정리 — SSM 에 충실히 복제하기 전에** (2026-08-09 신설)
      `app-secrets/ES_PASSWORD` · `pipeline-secrets/ES_PASSWORD` · `pipeline-secrets/AWS_REGION` — **어떤 ExternalSecret 도 참조하지 않는다**.
      앞 둘은 per-role ES 계정(0-15)으로 대체된 잔재로 보인다. → **이관 대상은 37키가 아니라 34키**
- [ ] **0-11d 🔴 SSM 번들 4KB 가드 + `Tier: Intelligent-Tiering`** (2026-08-09 신설)
      `app-secrets` JSON **3,385 B = standard 4,096 B 의 82.6%, 여유 711 B**. **SA JSON 하나 더 넣으면 초과**한다.
      ① CI 가드 — 번들 JSON 3,600 B 초과 시 실패
      ② `PutParameter` 에 **Intelligent-Tiering** — 4KB 초과 시 **실패 대신 자동 advanced 승격** →
         실패 모드가 "조용한 갱신 정지"에서 "월 $0.05 추가"로 바뀐다
      🔴 **①은 그래도 유지한다** — advanced 는 **되돌릴 수 없어서** 넘기 전에 알아야 한다
- [ ] **0-12 ⭐ `jwt_secret` 조용한 폴백 제거** — 커밋된 placeholder(`dev-insecure-change-me`) + pydantic-settings 가 env 누락 시 조용히 폴백 → **토큰 위조 가능 상태로 무증상 기동**. 누락 시 기동 실패로 바꾼다 〔#32〕
- [ ] **0-13 PG 스키마별 롤** (현재 단일 슈퍼유저) — 🔴 **IRSA·IAM 설계의 전제**. 롤이 하나면 나눌 대상이 없다 〔이슈 #546〕
- [ ] **0-14 ⭐🔴 RBAC verb 단위 커스텀 롤 — 초안 확정(2026-08-09)** 〔이슈 #550〕
      **🔴 Phase 0 차단급으로 승격.** 종전 근거는 *"내장 `edit` 이 Secret 전권을 준다"* 하나였는데,
      **C-24 로 근거가 둘 늘었다** — ① EKS 에서 그 결함이 **AWS 계정 권한으로 번역**된다(`serviceaccounts/token`)
      ② **신원-B 의 하드 블로커**(관리형 정책은 수정 불가라 A 를 고르면 이 다리를 영원히 못 끊는다).

      **설계 원칙 — GitOps 라서 PoLP 가 자연스럽다**
      ```
        ArgoCD 가 정본이고 selfHeal 이 도는 앱도 있다
        ⇒ 클러스터에서 직접 "만들기·고치기"는 되돌려지거나 drift 가 된다
        ⇒ 사람이 클러스터에서 실제로 필요한 건 **보기 + 운영 액션**(재시작·로그·디버깅)뿐
        ★ create/update 를 빼도 잃는 게 거의 없다 — 그건 git 으로 가는 경로다
      ```

      **1단계 = `edit` 만 교체한다** (내장 `view` 는 그대로 둔다 — core secrets 를 안 주므로 위험이 낮고,
      변경 범위가 작아 되돌리기 쉽다. `view` 커스텀화는 2단계 선택 사항)

      **🅐 `mp:app-dev`** (건우 · app ns)
      · 읽기 = `pods` `pods/log` `pods/status` · `deployments` `replicasets` `statefulsets`
        · **`rollouts` `analysisruns` `analysistemplates`**(카나리 진행 확인, ADR-0001)
        · `services` `endpoints` `configmaps` `events` · `hpa` `pdb` · `httproutes` → get list watch
      · 운영 = `deployments`·`rollouts` **patch**(rollout restart · 카나리 promote/abort) ·
        `pods` **delete** · `pods/exec`·`pods/portforward` **create**
      · 🔴 제거 = **`secrets` 전부**(ESO 가 만든다·사람이 읽을 이유 0) · **`serviceaccounts`+`serviceaccounts/token` 전부**(IRSA 다리) ·
        `configmaps`/`services`/`pvc` **쓰기**(GitOps) · **aggregate 라벨 자동 흡수**(지금 11개 — 오퍼레이터 깔 때마다 아무도 결정 안 한 채 늘어난다)

      **🅑 `mp:pipeline-dev`** (건우·정은 · pipeline ns) = 🅐 읽기 + `cronjobs`·`jobs` 읽기
      · 운영 = `jobs` **create**(🔴 CronJob 수동 트리거 `--from=cronjob/…` — 크롤 재실행 필수) ·
        `jobs` **delete**(실패 Job 정리 — 현 `KubeJobFailed` 129h 가 이것) · `cronjobs` **patch**(suspend/resume — 🔴 **2-3 컷오버 절차에 필요**) ·
        `scaledobjects` 읽기

      **🅒 `mp:observability`** (정현 · observability ns) = 🅐 읽기 + `prometheusrules`·`servicemonitors`·`podmonitors` 읽기
      · 운영 = `deployments`·`statefulsets` **patch** · `pods` **delete** · `pods/exec`·`pods/portforward` **create**
      · ⚠️ 판단 = 룰 CR **create/patch 허용**(실험 없이 알림 룰을 못 만든다. 정본은 git — ArgoCD 가 되돌린다)

      **🅓 `mp:cluster-admin`** (봉수·태현) = `cluster-admin` 유지 → AWS 는 `MPAdmin` 권한세트

      🔴 **초안 기본값 3건**(재검토 가능):
      ① **`data` ns 는 admin 유지** — PG·ES·Kafka 는 CR 하나로 데이터가 죽는다.
         ⚠️ **CLAUDE.md 의 "정은=data-dev" 는 실물과 다르다**(실제 바인딩 = pipeline edit) → **문서를 실물에 맞춰 정정**
      ② **`pods/exec` 는 준다** — 없으면 디버깅이 불가능하고 그러면 admin.conf 를 계속 쓰게 된다(더 나쁨). 대신 **감사로그에 남는 유일한 위험 액션**으로 표시
      ③ **관측 룰 create/patch 허용**

      🔴 **함정 — 최소권한을 실사용 기반으로 설계할 수 없다**: 감사로그의 `mp-users:*` 가 0건이고,
      게다가 policy 의 catch-all `level: None`+`get/list/watch` 때문에 **읽기의 84%가 애초에 기록되지 않는다**(1-26).
      → 관측으로 "무엇이 필요한지"를 정할 수 없다. **좁게 시작하고 막힐 때마다 PR 로 넓히는 방식**을 채택한다(사용자 결정).

      **넓히는 절차** ①본인이 `kubectl auth can-i` 로 확인 → ②이슈에 **명령 원문**을 적어 요청(그래야 최소 규칙만 추가) →
      ③config 레포 PR → **권한 변경 이력이 git diff 로 남는다**(지금은 아무 데도 안 남는다) →
      ④급할 땐 admin 2명이 대신 실행. 🔴 **"임시 승격"은 하지 않는다 — 임시가 영구가 된 게 지금 admin.conf 상태다**

      **적용 순서** 1)커스텀 롤 4종을 config 레포에 작성(바인딩 전) → 2)`auth can-i --list` 로 현행 edit 과 diff 문서화 →
      3)🔴 **`S4-1`(ClusterSecretStore conditions)이 먼저** — 안 하면 롤을 좁혀도 ESO 우회로 fb-secrets 전량이 샌다 →
      4)RoleBinding 을 한 사람씩 교체 → 5)1~2주 관찰·수집 → 6)AWS 에서 같은 롤을 Access Entry `kubernetesGroups` 로 매핑
- [ ] **0-14b 🔴 S4-1 `ClusterSecretStore fb-kubernetes` 에 `spec.conditions`(namespaceSelector) 추가 — 0-14 보다 먼저** (2026-08-09 신설)
      실측: `spec.conditions` **비어 있음** · `eso-reader` Role = `secrets [get,list,watch]` **resourceNames 없음** ·
      `external-secrets-edit` 가 **aggregate-to-edit 11개에 포함**. → edit 티어가 ExternalSecret 하나로 **fb-secrets 6종 전량**을 자기 ns 로 복사할 수 있다
      (`harbor-pull` 레지스트리 자격증명 · `repo-food-budget-config` **config 레포 쓰기 SSH 키** 포함).
      🔴 **이걸 안 하면 0-14 를 끝내도 우회 경로가 남아 효과가 0이다.**
      ⚠️ 현재 위험은 **읽기 한정**(PushSecret 은 eso-reader Role 이 막는다) — 과잉·과소 대응을 피하려면 함께 적을 것
- [ ] **0-14c 🔴 S4-2 워크로드별 ServiceAccount 신설 — 0-16 의 진짜 선행** (2026-08-09 신설)
      실측: **app 14 + pipeline 22 워크로드가 전부 `default` SA**(ns 당 SA 1개. data ns 만 CNPG 가 `pg`·`pg-pooler` 로 분리).
      🔴 **①을 건너뛰고 Pod Identity association 을 걸면 롤이 `default` SA 에 붙어 22개 전부가 Bedrock 권한을 갖는다**
      = 폭발 반경 불변. **"0-16 완료" 체크하고도 실제 보안 개선이 0일 수 있다.**
      또한 C-24 의 **층2 방어**(association 을 특정 SA 에만 + 롤 자체를 최소권한)가 이것 없이는 성립하지 않는다.
      부수: `pipeline` 22/22 가 `automountServiceAccountToken` **미설정**(app 은 14/14 false) → 함께 처리
- [ ] **0-14d S4-3 `mp-pipeline-secrets` 를 db용/aws용 2개로 분리** (2026-08-09 신설)
      `envFrom.secretRef` 는 **통째 주입**이라 AWS 키만 뺄 수 없다. 매니페스트 **22개**(CronJob 17 + Deployment 5) +
      🔴 **런타임 Job 오브젝트 36개**가 추가로 살아 있어 실제 보유 객체는 **58개** → 전환 중 Job 처리(TTL·수동 정리) 절차 필요.
      실측 대비: **자격증명 보유 22 : 실제 boto3 사용 2**(Bedrock)
- [ ] **0-15 ES PoLP** — 소비자 5곳 중 4곳이 `elastic` 슈퍼유저 + HTTP TLS 꺼짐 〔이슈 #521〕
- [ ] **0-16 정적 AWS 키 `envFrom` 제거** — pipeline ns 워크로드 22개 전부에 전파. 🔴 **env 가 자격증명 체인에서 Pod Identity 보다 앞선다** 〔#78〕
      🔴 **순서를 지켜야 한다 — 역순이면 개선이 0이다** (2026-08-09, C-24):
      ① 워크로드별 SA 신설(**0-14c**) → ② `mp-pipeline-secrets` 분리(**0-14d**) → ③ Pod Identity association 생성
      *(여기까지 무중단 — env 가 체인에서 앞서므로 동작이 안 바뀐다)* → ④ **env 제거 + rollout restart** ← 여기서 전환
      🔴 **범위 정정(S4-4)**: 정적 AWS 키는 **2세트** — `pipeline/mp-pipeline-secrets` + **`data/mp-pg-backup-s3`(CNPG barman)**.
      체크리스트가 pipeline 만 세고 있었다. ⚠️ 반대로 `data/mp-pg-onsite-minio` · `observability/lgtm-minio-creds` 는
      **MinIO 자격증명이라 AWS 가 아니다** → Pod Identity 로 대체 불가. **범위에서 명시적으로 빼지 않으면 "정적 키 0" 목표가 영원히 미달성으로 보인다**
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
- [ ] **0-25 🔴 ap-northeast-2 실단가 재검증** (2026-08-09 신설) — **D10 의 분모가 여기 걸려 있다**.
      `mp_aws_migration_plan.md:128` 의 gp3 **$0.0912/GB-월** 은 2026-08-02 Bulk API 조회 주장(발효 2026-07-01)이지만
      **이번 조사 3세션이 전부 재조회에 실패**했다(가격 페이지 JS 렌더 / calculator JSON 404 / Bulk API 는 자격증명 필요).
      문서 자신이 `:86` 에서 *"인용 전 재조회할 것"* 이라 적고 있다.
      미검증 목록 = **S3 저장/PUT/GET 요율** · **EBS 스냅샷 요율(리전 미표기)** · **EC2 인스턴스 요율**.
      🔴 EBS 스냅샷은 **블록 단위 과금**이라 파일시스템 used(13.5 GiB)는 **추정치가 아니라 하한(floor)** 이다 —
      실측은 AWS 에서 첫 스냅샷을 떠야 가능
- [ ] **0-26 🔴 `lgtm-apps.yaml.j2` 이중 소유 해소 — S3 컷오버(C-18)의 선행** (2026-08-09 신설)
      라이브 `loki`·`tempo` Application 은 **`platform-root`(config 레포 · `selfHeal:true`) 소유**인데
      `k8s_platform_apps/tasks/main.yml:56-63` 이 **여전히 Ansible 템플릿을 `kubectl apply`** 한다.
      두 소스는 **이미 갈라져 있다**(템플릿 `zone: host-b` vs 라이브 `hostname: k8s-worker-b1`, tempo probe 유무).
      🔴 S3 컷오버를 config 레포에서 하면 **Ansible 실행이 MinIO endpoint 를 되살리고 ArgoCD 가 되돌리는 왕복**이 생긴다.
      0-3 과 인접하나 **별건**(중복 소유). ⚠️ 이 롤은 지울 수 없다 — `lgtm-minio-creds`·`minio` 시크릿의 유일한 공급원이다

---

## Phase 1 — 리허설·컷오버 준비 (조용히 깨지는 것)

- [ ] **1-1 PGSync CDC 복구** — 논리 복제 슬롯 `lost`. 컷오버·DR **양쪽** 경로 〔#17〕
- [ ] **1-2 CNPG egress 에 STS 추가** — 없으면 IRSA 전환 시 WAL 아카이브·백업이 **경고 없이** 전면 실패 〔#14〕
- [ ] **1-3 카나리 AnalysisTemplate 파라미터화** — `kube-prometheus-stack-prometheus.observability:9090` 하드코딩이고 그 스택이 0-3
- [ ] **1-4 docker.io → ECR pull-through cache** 준비 — rate limit
- [ ] **1-5 백업 3종 대체 경로** — etcd·비밀/PKI·신선도 계측이 전부 kubeadm master systemd timer. EKS 엔 그 호스트가 없다 〔#15〕
- [ ] **1-6 이미지 멀티아치** — 전 이미지 amd64 단일. Graviton 노드면 전면 CrashLoop. CI 툴체인의 sonar-scanner-cli 도 amd64 단일 〔#31 #35〕
- [ ] **1-7 JWT_SECRET 이관 체크리스트** — 단일 값을 10개 서비스가 공유. 누락 시 전 유저 세션 무효 〔#80〕
- [ ] **1-8 SSM 4KB 한도 대응** 〔#123〕 — 🔴 **2026-08-09 실측 정정**: app-secrets 는 11키가 아니라 **13키**이고,
      **4KB 를 넘는 개별 키는 0개**다(최대 `GCP_SA_KEY_JSON` 2,460 B). 진짜 제약은 개별 키가 아니라
      **번들 JSON 3,385 B = 한도의 82.6%(여유 711 B)** 다. → 조치는 **0-11d** 로 이관. 이 항목은 근거만 교체
- [ ] **1-29 🔴 `JWT_SECRET`·`PGPASSWORD` 로테이션 절차 신설** (2026-08-09 신설, C-23)
      주입이 **전부 `envFrom.secretRef`** 이고 체크섬 어노테이션이 없다 → **값을 바꿔도 도는 파드는 옛 값을 쓴다**.
      로테이션 = 값 교체 + **`rollout restart` 10~11건**이 한 묶음이다. fan-out = `PGPASSWORD` 11 · `JWT_SECRET` 10.
      🔴 C-23(양 사이트 독립)이라 **양쪽에서 각각** 해야 한다
- [ ] **1-30 온프렘 전손 런북 — "SSM 임시 정본 승격 → 재건 후 원복"** (2026-08-09 신설, C-23)
      양 사이트 독립이므로 온프렘이 전손되면 **AWS 는 계속 돈다**(초기 권고안과 달리 신규 배포도 막히지 않는다).
      다만 **온프렘 재건 시 34키를 어디서 가져올지**가 정해져 있어야 한다 — 0-11(SOPS 커밋)이 그 답이면 런북에 그렇게 적는다
- [ ] **1-31 default SA 4개의 `imagePullSecrets: harbor` 처리** (2026-08-09 신설) — EKS 는 ECR 이다.
      `harbor-pull` 3키는 **사이트별로 달라야 하는 17키**에 속한다(C-23 ② 분류)
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
- [ ] **1-14 🔴🔴 `video` Redis 재시도 추가 — C-14(ElastiCache)의 명시적 선행. 선택 아님** — `video/app/store.py:33-39` `put_job`/`get_job` 에 **try/except 없음**(docstring:7 "실패해야 정직하다" = 의도).
      호출부 `main.py:202`(POST 추출)·`main.py:210`(GET 조회) 무방비 → **ElastiCache failover 순간 두 엔드포인트가 하드 500**. D4-b 의 선행
- [ ] **1-15 `chat`·`price` Redis 소켓 타임아웃 설정** — `chat/db.py:51-53`·`price/db.py:38-40` 미설정(video/ocr 은 3s, pipelines 5s).
      사이트 간 지연이 생기는 AWS 구성에서 무한 대기
- [ ] **1-16 🔴 PGSync 체크포인트가 emptyDir** — `CHECKPOINT_PATH=/app/checkpoint` 가 emptyDir 위 8 B 파일 2개 → **파드 재시작 시 소멸**.
      이관 중 파드는 반드시 죽는다. Redis 를 어떻게 하든 남는 별건 결함
- [ ] **1-17 🔴 CNPG 자동 failover 리허설** — C-15 로 자체운영을 확정했으므로 **RDS 가 대신 해주던 것을 우리가 증명해야 한다**.
      CNPG 는 자동 failover 를 하지만 **우리 환경에서 재본 기록이 없다**. primary 파드 강제 종료 → 승격 시간 · `pg-pooler` 재라우팅 ·
      앱 10종 재연결까지 측정한다. 🔴 **왕복 복원은 증명됐지만(P2 게이트① 2026-07-29) failover 는 별개다**
- [ ] **1-18 🔴 WAL PVC 포화 알림** — WAL 전용 PVC **10Gi** 에 WAL 이 **361 MB/일** → 아카이빙이 막히면 **약 27일치**.
      차면 **PG 가 선다**. barman 아카이빙 실패는 이미 알림이 있으나(`MpBackupWalArchivingStalled`) **PVC 사용률 자체의 알림이 없다**.
      C-15(자체운영)의 대가로 생기는 항목 — RDS 라면 스토리지 자동 확장이 덮었을 자리
- [ ] **1-13 XFF 홉 수 재조정 = `numTrustedProxies: 2`** — 실측: `meshConfig.gatewayTopology` **키 자체가 없고** Envoy `xff_num_trusted_hops` 도 **부재(=0)**.
      정답값 근거 = Istio 공식 문서 원문 *"if you have a cloud based Load Balancer and a reverse proxy in front of your Istio gateway, set `numTrustedProxies` to `2`"* — **우리와 똑같은 조합을 예시로 든다**.
      🔴 **`1-20`(LB SG = Cloudflare 대역 전용)과 한 세트다** — SG 를 안 잠그면 XFF 를 신뢰할 근거가 사라진다
- [ ] **1-32 🔴 결정 0 — LB target-type = `instance` 확정** (2026-08-09 신설, C-26 · **최상위 제약**)
      AWS 문서: `ip` 타깃 = ENI 기반 CNI / `instance` 타깃 = **오버레이 CNI**. 우리는 C-7 로 Cilium cluster-pool +
      파드 10.20.0.0/16 이라 **파드 IP 가 VPC 라우팅 대상이 아니다** → `ip` 불가.
      ✅ NodePort 는 이미 열려 있다(15021:30810 · 80:30816 · 443:31095).
      🔴 **이 한 줄이 없으면 리허설에서 "등록은 되는데 전부 unhealthy" 로 하루를 태운다**
- [ ] **1-33 🔴 게이트 — NLB 에 보안그룹을 붙일 수 있는지 확인** (2026-08-09 신설, C-26 의 전제)
      `1-20`(SG = Cloudflare 대역 전용)은 **CF 우회 차단의 유일한 수단**인데, C-26 으로 WAF 부착점을 포기했으므로 더 중요해졌다.
      NLB 보안그룹 지원은 나중에 추가된 기능이고 **생성 시점에만 지정 가능**한 것으로 알려져 있다 — 🔴 **미검증, 착수 전 확인**.
      못 붙이면 CF 우회 차단 수단을 다른 방식으로 마련해야 한다
- [ ] **1-34 NLB 헬스체크 + 노드 SG** (2026-08-09 신설) — `HealthCheckPort` 15021(NodePort 30810) 또는 `Matcher` **200-399**
      (AWS 문서: *"You can specify... a range of values"* · HealthCheckPort 기본값은 트래픽 포트지만 **변경 가능**).
      🔴 **노드 SG 가 LB SG 를 NodePort 대역에 대해 허용**해야 한다 — 선행작업 어디에도 없었다
- [ ] **1-35 🔴 SNAT ↔ CiliumNetworkPolicy 재작성 검토** (2026-08-09 신설)
      `externalTrafficPolicy: Cluster` + `instance` 타깃이면 파드가 보는 출발지가 `world` 가 아니라 `host`/`remote-node` 일 수 있다.
      → **헬스체크(15021)뿐 아니라 데이터 경로(80/443) netpol 도** 재작성 대상일 수 있다.
      🟡 NLB 는 노드까지 클라이언트 IP 를 보존하므로 완화 여지가 있으나 **노드→파드 구간은 `externalTrafficPolicy` 에 달렸다**.
      **미검증 — 리허설에서 `cilium-dbg endpoint list` / conntrack 으로 확인**
- [ ] **1-36 GW 타임아웃 차등 — 🔴 일괄 60s 금지** (2026-08-09 신설)
      계층 = **LB idle 120 > CF 100 > GW ≤75**. 지금 GW 쪽이 **3중으로 전무**(라우트 15개 `timeout: 0s` · HCM `stream_idle_timeout: 0s` · HTTPRoute 12개 `timeouts` 미설정) → **1-11 과 같이 한다**.
      🔴 **OAuth 산술 최악이 60.4s** 라 일괄 60s 면 지금도 넘는다:
      `oauth.py:22` `httpx.Timeout(5.0, connect=10.0)` → token POST 30.2s(시도0 connect10 + backoff0.2 + 시도1 connect10+write5+read5) +
      userinfo GET 30.2s, **`:124`·`:132` 가 직렬** = 60.4s. *(체크리스트 종전 50.4s 도 최악이 아니라 하한이다)*
      권고 = **기본 30s + `/api/auth` 75s + `/api/prices` 45s**. ✅ 다른 서비스는 안 잘린다(chat gemini/bedrock 3.0s · es 3.0s · pg 8s · mealplan→ranking 0.3s).
      ⚠️ Envoy `retry_policy(num_retries 2)` 가 이미 붙어 있어 `timeouts.request` 는 **재시도 포함 총예산**이다
- [ ] **1-37 🔴 chat rate-limit 이 오늘도 이미 우회 가능하다 — 별건** (2026-08-09 신설)
      `services/chat/app/main.py:563-566` 이 `xff.split(",")[0]` = **최좌측**을 읽는다.
      **Cloudflare 도 Envoy 도 XFF 를 append 하지 그 앞을 지우지 않는다** → 공격자가 보낸 값이 끝까지 최좌측에 남는다
      ⇒ **rate-limit identity 를 공격자가 마음대로 바꿀 수 있다.**
      🔴 **`numTrustedProxies`·SG 를 뭘로 하든 안 바뀐다** — 1-13/1-20 과 묶으면 *"SG 만 잠그고 방어됐다"* 고 오판한다.
      고침 = `cf-connecting-ip` 또는 `x-envoy-external-address` 를 읽는다
- [ ] **1-38 `mp-https-redirect` 는 AWS 오버레이에서 미부착** (2026-08-09 신설, C-26)
      NLB TCP:443 패스스루라 **`:80` 경로 자체를 안 쓴다** → 리다이렉트 루프가 발생할 여지가 없다.
      `:80` 유입이 필요하면 **Cloudflare "Always Use HTTPS"** 로 처리한다(코드 변경 0).
      ⚠️ 온프렘은 현행 유지 — **오버레이로 갈리는 지점**이라 명시할 것

### 1-C. 스토리지 관련 (D5 실측에서 파생, 2026-08-09 추가)

- [ ] **1-19 🔴 Loki·Tempo 에 `region` 키 추가 + `insecure`/`forcepathstyle` 뒤집기** — 실측 **region 0건**
      (loki cm · tempo cm · 라이브 valuesObject 전부). MinIO endpoint 만 지우면 **SDK 가 기본 리전으로 붙어 버킷을 못 찾는다**.
      2026-08-02 에 이미 밟은 함정이다(Prometheus rule 주석에 기록됨). C-18 과 한 묶음
- [ ] **1-20 `data/mp-pg-onsite` egress 를 S3(443)로 여는 CNP 추가** — 현재 DNS·5432·**9000(MinIO)만** 허용.
      정답 패턴이 이미 있다 — CNP `data/mp-pg-instance-egress` 의 `toFQDNs: s3.ap-northeast-2.amazonaws.com` + 443.
      2-8 은 프리픽스 분기만 다루므로 별건
- [ ] **1-21 🔴 랭킹 모델 로드 실패가 조용하다** 〔이슈 #561〕 — `ml/recipe-ranking/serve.py:157-169` 가 파일 부재·pickle
      실패를 **로그 없이** 삼키고 `model=None` 으로 기동. `:198-200` `/health` 는 `status: ok` 반환 →
      readiness·liveness 둘 다 통과. `model_loaded` 를 노출은 하는데 **알림 규칙 0건**(실측).
      🔴 **모델 사본 0개**(MinIO `models` 버킷 = 0 바이트) · **클러스터 내 재생성 경로 0**(`retrain.py` 미배포).
      C-20(PVC 제거)을 실행하면서 **모델 사본 정책을 같이 정해야 한다** — 안 그러면 이미지/S3 배선이 틀려도 드러나지 않는다
- [ ] **1-22 EBS CSI 는 VolumeGroupSnapshot 미지원 — PG 는 barman 을 정본으로 유지** —
      `aws-ebs-csi-driver` README 기능 목록 확인. **data(10Gi)+WAL(4Gi) 원자 스냅샷이 불가**하므로
      스냅샷 기반 PG 복구는 **시점 불일치로 조용히 손상된다**. "AWS 가면 스냅샷으로 PG 복구" 유혹을 명시적으로 차단할 것
- [ ] **1-23 온프렘 스냅샷 갭은 이관 갭이 아니다 — 두 과제를 섞지 말 것** —
      VolumeSnapshotClass 만 없고 사이드카·CRD 는 가동 중(csi-snapshotter·snapshot-controller v7.0.0).
      그러나 **온프렘 LVM 21/21 이 thick**(`thinProvision: no`)이고 `lvm-driver 1.9.1` 바이너리에
      `only thin restores supported today.` 가 박혀 있다 → **클래스를 만들어도 온프렘 백업이 개선되지 않는다**
- [ ] **1-24 CNPG `wal_keep_size` spec 512MB vs 런타임 1024MB 불일치** — 실행 인스턴스 유효값이 spec 과 다르다.
      **C-16 의 WAL 사이징(4Gi)이 이 값을 전제로 계산됐다**

### 1-D. 관측 관련 (D8 실측에서 파생, 2026-08-09 추가)

- [ ] **1-25 🔴 감사로그 보존창이 30일이 아니라 52.62시간이다** 〔#118〕 —
      `--audit-log-maxage=30` 이 **`maxsize 100MB × maxbackup 10 = 1GB` 상한에 가려 무효**다.
      실측 **501.3 MB/일 · 월 15.04 GB**. #118 을 *"이관 시 소실"* 만이 아니라 **"지금도 30일이 아니다"** 로 정정할 것
- [ ] **1-26 🔴 감사로그가 읽기의 84%를 기록하지 않는다 — S4 의 탐지 설계 전제** —
      `/etc/kubernetes/audit/policy.yaml` 에 catch-all `level: None` + `verbs:[get,list,watch]` 가 있다.
      apiserver 는 **19.839 req/s** 를 처리하는데 감사로그엔 **3.127 ev/s** 만 남는다.
      🔴 **"누가 Secret 을 읽었는지"가 감사로그에 없다.** S4(계정 보안)와 직결
- [ ] **1-27 Prometheus `retentionSize` 미설정** — `retention: 15d` 만 있고 크기 상한이 없다.
      C-16 이 30→20Gi 로 줄이므로 **카디널리티 급증 시 상한이 필요**하다.
      헤드룸 재산정 근거 = 12일 최대 시계열 **220,683**(현재보다 28% 높음) · 컨테이너 24h 최대 working set 1.61 GiB / limit 2.44 GiB = **66%**
- [ ] **1-28 알림 룰 199개 중 유효 발화 28종(14.1%) — 이관 전 정리 기회** —
      단 **미발화 ≠ 무용**이다(안 터진 게 정상인 룰이 대부분). 삭제가 아니라 **분류**가 목적

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

- [ ] **⚡ 알림 2건 정리** — `cost` ns `TargetDown` **170.3h 연속** · `KubeJobFailed` ns=pipeline **129.3h + 33.3h 짜리 2번째 건**. **주당 약 62 메시지**
      *(2026-08-09 실측 정정 — 종전 표기 121h/80h 는 이 문서 본문 재인용이고 실측이 아니었다)*
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
- [ ] **🔴 PG·ES 마이너 버전 패치 프로세스 신설** — C-15 의 대가. 현재 PG `16.14` · ES `8.19.19` 를 **누가 언제 올릴지 정하는 절차가 없다**.
      RDS 였다면 유지보수 창이 덮었을 자리다. 인증서 만료 감시 부재와 **같은 종류의 갭**(둘 다 "아무도 안 보고 있으면 방치된다")
- [ ] **`mp-ingress` ns 를 Ansible PR 로 정식화** — 2026-08-06 수동 kubectl 생성 상태. 'ns 는 Ansible 이 유일 생산자' 규칙 위반 〔#89〕

### 감시 공백 (D5 실측에서 파생, 2026-08-09 추가)

- [ ] 🔴 **PGSync 논리 슬롯 2개가 여전히 inactive** — `foodbudget_recipes_live`·`foodbudget_user_recipes_live`,
      각 **16 MB retained** · `wal_status=reserved` · `active=f` (2026-08-09 실측). #555 의 잔재이자 **1-1 의 실측 근거**다.
      🔴 **죽은 슬롯이 WAL 을 붙잡는다** — 지금은 작지만 슬롯은 원래 그렇게 디스크를 채워 터진다(#555 가 정확히 그 사고).
      **이관 전 정리 대상**
- [ ] 🔴 **pipeline PVC 2개가 용량 알림 영구 사각지대** — 마운트 파드가 없어 `kubelet_volume_stats_*` 가 **아예 안 나온다**
      (21개 중 19개만 보고). 현행 MinIO 알람과 같은 방식의 PVC 알람은 이 둘을 **구조적으로 못 본다**.
      C-20 으로 온프렘에 잔류하므로 계속 유효한 항목
- [ ] **Grafana = PVC 0 + 무제한 디스크 emptyDir** — SQLite(UI 로 만든 대시보드·유저·annotation)가 **재시작마다 소멸**.
      대시보드가 config 레포로 프로비저닝되는지 확인 필요 — 아니면 **이관 시점이 PVC 를 붙일 기회**
- [ ] **descheduler `defaultDisabled: [PodsWithLocalStorage]`** — emptyDir 파드 보호가 꺼져 있다.
      현재 `namespaces.include: [app]` 라 범위 밖이지만 **이 include 가 넓어지면 evict = 데이터 소실**.
      유지할 불변식으로 명문화할 것
- [ ] **bitrot canary 가 b1·b2 에만** — 워커 4대 중 2대만 디스크 무결성 감시.
      **온프렘이 DR + 크롤 프로덕션으로 존속하는데(C-3) host-a 쪽이 무감시**다
- [ ] 🔴 **온프렘 b2 VFree 37 GiB = DR 용량 상한** — MinIO 50Gi + Prometheus 30Gi 를 동시에 안고 있다.
      AWS 가 primary 가 되어 온프렘으로 복제해 오면 **여기가 먼저 막힌다**. OpenEBS LVM 은 노드 로컬이라
      b2 고정 PVC 6개(113 GiB 할당)를 다른 노드로 못 옮긴다 → **DR 을 축소본으로 잡거나 워커 `sdb`(150GB) 증설**
- [ ] **MinIO ServiceMonitor 0개** — 79개 메트릭 계열을 방출 중이고 `MINIO_PROMETHEUS_AUTH_TYPE=public` 도 설정돼 있다.
      감시 공백의 원인이 "익스포터 부재"가 아니라 **ServiceMonitor 1개 부재**다. C-18 로 삭제되므로 **존치 기간 한정** 항목
- [ ] **`observability/mp-gw-internal-istio` replicas=1 · nodeSelector/TSC 둘 다 없음** — **내부 게이트웨이 SPOF**.
      공개 GW 는 replicas 2 + hard TSC 로 보호돼 있어 대비된다. 🔴 **C-9 가 내부 도구를 Tailscale 뒤로 몰았는데
      그 뒤의 문이 홑겹**이다. 완화 비용 0(C-21 표 참조)

---

## AWS 쪽 — S4 확정(C-24·C-25)으로 항목화된 것

> 2026-08-09 신설. 종전엔 *"계획에 통째로 없다"* 로만 적혀 있던 것 중 **S4 로 설계가 정해진 것**을 항목으로 옮겼다.
> 아래는 **AWS 착수 시점**의 작업이다(온프렘 선행이 아니다).

- [ ] **A-1 🔴 K8s 감사로그를 security 계정으로 보내는 경로 설계** — **CloudTrail 로는 안 된다**(AWS API 감사만).
      control plane logging → CloudWatch → S3 export, 또는 Loki 수집이 필요하고 **계획 0건**.
      🔴 C-8②(security 계정에 감사 집중)의 근거와 정면 충돌하는 갭이다
- [ ] **A-2 🔴 ECR lifecycle policy 를 클러스터 생성과 *동시에*** — Security Hub Essentials 유닛이
      **이미지 아티팩트 수**에 비례한다(18 images = 1 unit). `:sha` 불변 태그라 레포 18개에 수백 아티팩트가 쌓인다.
      **lifecycle policy 없이는 C-25 의 비용 범위 자체가 미정**이다
- [ ] **A-3 🔴 GuardDuty 30일 체험 종료일 캘린더 + AWS Budgets 알림** — **종료 후 자동 비활성되지 않는다**.
      체험 창이 **foundational 볼륨을 실측할 유일한 기회**다
- [ ] **A-4 🔴 게이트 — Security Hub Essentials 가 AWS Config 를 요구하는가** — 공개 페이지에 서술 없음(미검증).
      요구한다면 C-25 의 "Config 미채택"과 충돌하므로 **착수 전 확인**
- [ ] **A-5 CloudTrail 버킷 = 버전관리 ON + Object Lock **GOVERNANCE** 90일 + SCP 로 bypass 차단**
      (COMPLIANCE 미채택 trade-off 는 C-25 "포기하는 것" 참조)
- [ ] **A-6 break-glass 절차 문서화 + 연 1회 훈련** — ① 각 계정 root 봉인(하드웨어 MFA + 비밀번호 오프라인 분할)
      ② prod `mp-breakglass` IAM 롤(평시 SCP 차단 · 사용 시 CloudTrail→Slack). 🔴 **Identity Center 밖**이어야 한다
- [ ] **A-7 Terraform AWS provider 골격** — 현재 AWS provider 코드 **0건**.
      Access Entries · permission set · Object Lock · `default_tags` 를 포함시킨다
- [ ] **A-8 S3 암호화 기본값** — 고객체 버킷은 SSE-S3 또는 SSE-KMS + **S3 Bucket Keys**(KMS 요청 최대 99% 감소, 공개 문서)
- [ ] **A-9 Runtime Monitoring 보류 결정 기록** — eBPF DaemonSet ↔ **Cilium 공존이 문서에 언급 없음(미검증)**.
      채택하려면 **리허설 클러스터(1-9) 선행**
- [ ] **A-10 Amazon Inspector 채택/기각 판정** — 🔴 5종(GuardDuty·Security Hub·Inspector·CloudTrail·KMS) 중 **Inspector 만 판정이 없다**.
      Security Hub Essentials 설명에 "vulnerability management"가 포함돼 **번들 관계 미확인**이고,
      **CI 에 Trivy CRITICAL 차단 게이트가 이미 있어 기능이 겹친다** — 이 트레이드오프가 어디에도 없다
- [ ] **A-11 `mp-users` 무기한 SA 토큰 5개의 온프렘 존치 정책** — 온프렘 존치 확정이라
      **cluster-admin 토큰 2개 포함 5개가 계속 산다**. 만료 없음·취소 = 삭제

---

## 🔴 아직 계획에 통째로 없는 것 — AWS 쪽

이 체크리스트는 **온프렘 선행**만 담는다. 아래는 AWS 이관 계획 문서에서 다뤄야 하는데 **현재 없다**.

- ~~AWS 계정 구조 · IAM Identity Center SSO · MFA · break-glass~~ → **C-24 로 확정** (권한 세트 6종 · A-6)
- 비용 가드레일 — AWS Budgets · 태깅(`default_tags` 0건) *(A-3·A-7 에 일부 포함)*
- Terraform AWS 코드 구조 · state 분리 (AWS provider **0건**, backend 버킷 **버전관리 OFF**) *(A-7)*
- VPC 설계 — CIDR 비충돌 · NAT 개수 · S3/ECR/**STS** 엔드포인트
- ~~GuardDuty · Security Hub · Inspector · CloudTrail · KMS~~ → **C-25 로 확정** (Inspector 만 미판정 = A-10)
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
| ~~StorageClass 하드코딩~~ | ~~5 / 13 / 15~~ | ✅ **확정(2026-08-09)** = **필드 22 / 파일 13 / 라이브 오써링 오브젝트 12**. `5`·`13`·`15` 폐기. 🔴 `5` 는 5곳에 복제(0-8 참조) |
| **스토리지 프로비저닝** | 351 vs **352 GiB** | ✅ **352 가 정본.** §1.2 표가 `app/mp-ranking-model` 1Gi 누락 — 하필 **사본 0인 유일한 볼륨** |
| 🔴 **EBS 총량** | 계획서 **PVC 만** 352 | ✅ **노드 EBS 360 GiB(4×90) 가 통째로 누락**. 총 **712 GiB** · 실사용 106.9 · 배수 **6.7×**(PVC 층만 보면 26×) |
| 🔴 **EBS 월 비용** | `migration_plan.md:71` **$32.01** | ✅ 위 누락으로 **A 를 약 $33 과소평가**. A=**$64.93** / C(워커4)=**$35.11**. 단, 단가 자체가 미검증(0-25) |
| ArgoCD Application 총수 | CLAUDE.md **41** vs 실측 **46** | prune=true 13 / prune=false automated 17 / **수동 16** |
| 🔴 **감사로그 보존창** | 문서·설정 **30일** | ✅ **실측 52.62시간.** `maxage=30` 이 `maxsize 100MB × maxbackup 10 = 1GB` 에 가려 무효. 501.3 MB/일 · 월 15.04 GB (1-25) |
| 🔴 **감사로그 커버리지** | — | ✅ **읽기의 84%가 미기록.** apiserver 19.839 req/s vs 감사 3.127 ev/s. policy 에 catch-all `level: None`+`get/list/watch` (1-26) |
| ArgoCD 밖(순수 Helm) 워크로드 | "kube-prometheus-stack" | ✅ **4종** — + `observability/minio` · `kube-system/node-exporter` · **`kube-system/metrics-server`** (0-3) |
| 관측 자원 소비 | `kubectl top` 스냅샷 0.156 코어 | ✅ **24h 평균 0.180 코어**(15% 높음) · **메모리 피크 4.24 GiB** — 사이징은 저점이 아니라 피크로 |
| 상시 발화 지속시간 | 121h / 80h | ✅ **TargetDown 170.3h · KubeJobFailed 129.3h(+33.3h 2번째)** |
| `recipes` 인덱스 종속 노드 | `migration_plan.md:400` **worker-b2** | ✅ 실측 primary = `es-es-b-1` = **`k8s-worker-b1`** |
| 🔴 **`recipes` 인덱스 성격** | "단일 사본 → 폐기 후보" | ✅ **폐기 불가** — `mp-chat` 이 `search.py:57` 하드코딩으로 라이브 조회 중 〔이슈 #560〕. servable=true 는 `recipes`·`recipes_v2` 양쪽 **정확히 6,107 로 일치**(어긋남 없음) |
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
Phase 0   37건   ← 이게 끝나야 AWS 착수   (0-A 15 · 0-B 14 · 0-C 8)
Phase 1   38건                            (1-A 12 · 1-B 16 · 1-C 6 · 1-D 4)
Phase 2    9건
상시      17건                            (기존 9 · 감시공백 8)
──────────────
온프렘 선행 101건 (5인 · 8~9주)

AWS 착수  11건   ← 온프렘 선행이 아니다 (S4 확정 산출물 A-1~A-11)
──────────────
합계     112건
```

⚠️ **2026-08-07 재집계 정정** — 종전 표기 `21/13/9/5 = 48` 은 실제와 어긋나 있었다. 08-07 에 추가된 6건(0-22·0-23·1-14~1-16·상시 3건)이 본문에만 들어가고 이 블록에 반영되지 않았던 것이 원인이다.
위 숫자는 본문 `- [ ]` 개수를 기계적으로 센 값이다(0-24 추가분 포함). **앞으로 항목을 늘리면 이 블록도 같이 고친다.**

진짜 차단은 Phase 0 중 **0-1~0-4(config 대공사) · 0-6(TSC) · 0-19(쿼터)** 6건이고, 나머지는 병렬 처리 가능하다.
보안 8건(0-11~0-18)은 별도 레인으로 돌릴 수 있다.

---

## 갱신 이력

| 날짜 | 내용 |
|---|---|
| 2026-08-09 | **C-26 확정 — AWS 유입 = Cloudflare(주황) → NLB TCP:443 패스스루 → Istio Gateway**(D-ing 해소, **ALB 미채택**). 한 문장 근거 = **"ALB 가 주는 L7 라우팅·WAF·접근로그를 우리는 Istio·Cloudflare·Istio 에서 이미 얻고 있다. 그래서 ALB 는 얻는 건 없고 TLS 를 두 번 끊는 대가만 남는다."** 🔴 **메커니즘** — TLS 는 봉인된 봉투이고 겉면(SNI)은 평문이다. ALB(L7)는 경로 라우팅을 하려면 봉투를 **뜯어야** 하고, 백엔드로 보낼 땐 **새 봉투**를 쓰면서 SNI 를 안 붙인다 → 우리 GW 는 `server_names:[app.mealbong.cloud]` + `default_filter_chain` 부재라 **전 요청 502**(블로커②) → `:80` 평문으로 우회하면 `mp-https-redirect` 가 걸려 **무한 루프**(블로커③) + 평문 구간. NLB(L4)는 안 뜯으므로 **②③ 이 발생할 여지가 없다**. 🔴 **실측 확인** — 현재 `mp-gw-public` 이 이미 Let's Encrypt(cert-manager)로 TLS 를 종단한다 → NLB 면 이 형상 그대로, ALB 면 ACM 이 추가되어 **온프렘(LE)↔AWS(ACM) 인증서 체계가 갈린다**(C-3 상시증명에서 한 겹 더 빠짐). ⚠️ **C-9 를 뒤집지 않는다** — C-9 의 핵심은 "1개만"과 "내부 도구 미노출"이고 ALB/NLB 는 그 아래 구현 선택이다. ⟳ **정정**: 조사 초안의 *"NLB 면 ①②③ 동시 소멸"* 은 틀렸다 — **①(target-type `instance` 강제)은 오버레이 CNI 공통 제약이라 소멸하지 않는다**. 비용은 시간당 동일·LCU 는 NLB 가 쌈 → **$27.38/월(하한)**, 🔴 총액 대비 비율은 쓰지 않는다(분모 미검증). 체크리스트 7건 신설(1-32~1-38) + 1-13 정답값 확정 → 105 → **112건**. 🔴 **게이트 = NLB 보안그룹 지원 확인**(WAF 를 포기했으므로 CF 우회 차단이 SG 하나에 걸린다) · 🔴 **별건 = chat rate-limit 이 XFF 최좌측을 신뢰한다 — 오늘도 이미 우회 가능하고 SG·numTrustedProxies 로는 안 고쳐진다** |
| 2026-08-09 | **C-24·C-25 확정 — 신원 = Access Entry `kubernetesGroups` + 커스텀 롤 · 파드 = Pod Identity · 보안 = 최소+GuardDuty+Security Hub**(S4 해소). 🔴 **핵심 발견 = K8s RBAC 과 IRSA 는 충돌하지 않는다(서로 다른 API 를 지배하므로 우선순위 개념 자체가 없다). 문제는 *다리* 다** — `serviceaccounts/token create`(내장 `edit` 에 포함, **실측 edit 티어 3명 전부 yes**)가 곧 그 SA 의 IAM 롤이 된다 ⇒ **EKS 에서 "K8s edit = 그 ns 의 모든 AWS 권한"**. 🔴 **라이브 보안 구멍 2건 실측** — ① **ESO 우회 탈취**(`ClusterSecretStore.spec.conditions` 비어 있음 + `eso-reader` 가 resourceNames 없는 secrets r → ExternalSecret 하나로 `fb-secrets` 6종 전량 복사 가능. **config 레포 쓰기 SSH 키 포함**. 단 PushSecret 은 RBAC 이 막으므로 **읽기 한정**) ② 위 권한 상승 다리. 🔴 **RBAC 세분화만으로는 안 막힌다**(`pods create` 는 개발자한테서 못 뺀다) → **2층 방어**(층1 K8s serviceaccounts 계열 제거 / 층2 association 을 특정 SA 에만 + 롤 자체 최소권한). **0-14 를 Phase 0 차단급으로 승격하고 초안(4롤 verb 표·초안 기본값 3건·넓히는 절차·적용 순서)을 확정**. 우선순위 3종(자격증명 체인·IRSA↔PodIdentity·aws-auth↔AccessEntries)은 설계 선택으로 전부 회피됨을 명시. 🔴 **비용 2건 정정** — GuardDuty $12.96 은 점추정이 아니라 **하한**($13~82, EKS 는 커스텀 audit policy 불가) · Security Hub "$15~23"은 **성립하지 않는다**(유닛이 레포 수가 아니라 **이미지 아티팩트 수**). 🔴 **근거 1건 철회** — "감사로그 `kubernetes-admin` 6.3% = 사람 접근이 admin.conf 로 나간다"는 **오늘 정지시킨 유령 drain 통계**였다. 체크리스트 P0 4건 + **AWS 착수 섹션 신설 11건(A-1~A-11)** → 91 → **105건**(온프렘 선행 94 + AWS 11) |
| 2026-08-09 | **C-23 확정 — 비밀 = 양 사이트 독립**(D7 해소). AWS=SSM standard 번들 6 + IRSA / 온프렘=현행 K8s provider 유지 / **PushSecret·자동복제 미채택**. 🔴 **내 초기 권고("흐름을 뒤집어 온프렘=쓰기 정본 + PushSecret 단방향 복제")를 사용자가 기각했고 그 판단이 옳다** — 초기 권고는 ①PushSecret(라이브 사용 0건) ②온프렘 정적 IAM 키(PutParameter 쓰기 권한, **초기 권고 자신이 "기각한 설계보다 폭발반경이 크다"고 적었다**) ③"온프렘이 죽으면 EKS 가 새 시크릿을 못 받는다"는 새 결합을 들여왔는데 **채택안엔 셋 다 없다**. 순환 의존도 채택안이 더 깨끗하다(양쪽 무참조). **37키 실측 분류** = 같아야 17 / 사이트별로 달라야 17 / 죽은 키 3 → 🔴 **동기화 대상은 17키뿐이고, 그중 "조용히 갈리는 7키"**(JWT_SECRET·OAuth 4·Cloudflare 2)만이 진짜 관리 대상이다(나머지는 갈리면 즉시 접속 실패로 드러난다). 이식 비용 = `remoteRef` **70엔트리 무수정**(gjson property·메타문자 0건) — 🔴 단 스토어에 `prefix: /mp/prod/` 를 명시해야 "무수정"과 "IAM 경로 최소권한"이 양립한다. 비용은 결정 변수가 아니다(최고안조차 $678 의 2.0%). 체크리스트 8건 신설(0-11b~0-11d · 1-29~1-31) + 0-2·0-11·1-8 근거 교체 → 85 → **91건** |
| 2026-08-09 | **C-22 확정 — 관측 = 양 사이트 자체 유지**(D8 해소, AMP·AMG 미채택). 핵심 = **AMP 는 메트릭 전용**이라 옮겨도 Alertmanager·Loki·Tempo·Alloy 4종은 그대로 자체운영이 남는다 → **관리형은 부담을 없애는 게 아니라 이중화한다**. 여기에 확정 단가만 월 $367 + **온프렘 물리계층 9룰은 어차피 남아야 함** + **알림 두뇌가 AWS 면 DR 을 감시 못 함**(확정 원칙 위배)이 겹친다. 🔴 **Prometheus replicas 는 D8-r 로 분리 — 잠정 1 유지, 이관 전 재결정**(사용자 결정). Prometheus 는 정족수형이 아니라 복제형이라 2 면 충분하지만, **replicas 만 올리면 `nodeSelector: zone=host-b` 가 둘 다 같은 zone 으로 보낸다**(anti-affinity 는 soft·hostname 축) — ①replicas ②nodeSelector 제거 ③zone TSC 가 한 묶음이고, 비용도 `+20 GiB` 가 아니라 **메모리 2배 + 스크레이프 2배**라 D10 사이징 입력값이다. 🔴 **철회한 근거 3개**(쿼리 지배축·$4.16 vs $899·"소비가 작으니 부담 없다") 명시. 체크리스트 6건 신설(0-3b·0-3c·1-25~1-28) + 0-3 에 **metrics-server 등 3종 누락 정정**(EKS 미제공인데 account HPA 가 의존) → 79 → **85건**. 🔴 **감사로그 2건** — 보존창이 30일이 아니라 **52.62시간** · **읽기의 84%가 미기록**("누가 Secret 을 읽었는지"가 없다 → S4 직결) |
| 2026-08-09 | **C-16 ~ C-21 확정 — D5(스토리지) 전체 해소.** 11에이전트 5축 실측 + 반증검증(정정 5건). **PVC 352 → 125 GiB**(−64.5%) · EFS 미도입(RWX 0건 + 21/21 PVC 소비자 1개) · MinIO 삭제 → S3 · kubecost = 클러스터 밖 EC2 · **정족수 AZ당 1개**(PG 2→3). 🔴 **계획서 결함 2건 정정** — ① **노드 EBS 360 GiB 가 통째로 누락**돼 있었다(총 712 GiB · `$32.01` → **$64.93**) ② 프로비저닝 351 → **352 GiB**. 🔴 **D5 ① 결정이 AZ 문제를 6개 지웠다**(149 GiB / 6 워크로드) — 남은 재파생 불가는 **Prometheus 하나뿐**이고 그건 D8 로 이관. Kafka `retention.ms` 미측정 해소(7일/30일 · **110 MB 는 이미 정상상태** · 30일로 늘려도 356 MB). 신규 체크리스트 **19건**(0-8b~0-8d · 0-25 · 0-26 · 1-19~1-24 · 감시공백 8) → 총 60→**79건**. 신규 이슈 **#560**(chat ES 인덱스 하드코딩) · **#561**(랭킹 모델 로드 조용한 실패). 🔴 부수 발견 = `retention.bytes` 무제한 · SC `openebs-lvm-retain` 은 만들어져 있는데 **소비자 0** |
| 2026-08-07 | 최초 작성. 감사 205 findings + DR 등급 실측 워크플로 결과 통합. 확정 C-1~C-6 반영 |
| 2026-08-07 | Cloudflare 프록시 호환성 실측 반영 — §0.2 D-ing 갱신 + Phase 1-B(1-10~1-13) 신설. 총 44→48건 |
| 2026-08-07 | **C-7(Cilium cluster-pool)** · **C-8(VPC/Landing Zone 6항목)** 확정. D-rep(앱 replica 정책) 미결로 신설. 0-6 목표를 zone 축 보존으로 구체화 |
| 2026-08-07 | **C-9(진입점 = 공개 ALB 1개 · 내부 도구는 Tailscale)** 확정. **§1 목표 아키텍처 다이어그램 신설** — 결정이 늘 때마다 여기에 얹는다 |
| 2026-08-07 | **D4 실측 반영**(파이프라인 배치·Redis ElastiCache·PG 백업 2갈래). 신규 위험 6건 추가(0-22 Jenkins백업부재 · 0-23 barman경로충돌 · 1-14~1-16 · 상시 3건). DB 크기 1,510MB→**848MB** 정정 |
| 2026-08-07 | **0-24 신설 — Kafka 프로듀서 전달 실패 미관측**(이슈 #558). D4-a 예외의 구조 통일을 이슈 #557 로 등재(사용자 선택 = ① 완전 Kafka 화, 시점은 이관 전). **규모 블록 재집계 정정** 48→**57건**(종전 표기가 08-07 추가분을 반영하지 않고 있었다) |
| 2026-08-09 | **C-15 확정 — PG = CNPG · ES = ECK 유지**(D4-d 해소 → **D4 전체 완결**). 핵심 = **RDS 는 외부 self-managed 로 물리복제 불가**(AWS 공식) → C-3 이 무너진다. 논리복제 대안은 시퀀스·DDL·롤을 못 나르고 **슬롯 무효화는 #555 로 이미 겪었다**. ES 는 파생이라 DR 논거가 없지만 **코드교체 + ~$79/mo** 가 막는다. 🔴 **자체운영의 대가를 항목화** — 1-17(failover 리허설) · 1-18(WAL PVC 알림) · 상시(패치 프로세스) 신설 |
| 2026-08-09 | **§1 다이어그램 정비 — 설계도로 승격.** C-14 반영 과정에서 AZ 3열 박스 정렬이 깨져 있었고 **C-12(`onprem.` 접두사)가 그림에 아예 없었다**. 결정은 하나도 지우지 않고 레이아웃만 재구성 — 이제 **C-1~C-14 전부 그림에 표기**되고 각 요소 옆에 근거 결정 번호가 붙는다. '아직 없는 것' 목록도 **남은 8건이 그림의 어디에 얹힐지**까지 표로 명시 |
| 2026-08-09 | **C-14 확정 — Redis = ElastiCache for Valkey `cache.t4g.micro` Multi-AZ 2노드**(D4-b 해소). 판단 축은 비용($21~22/mo ≈ D10 의 3.2%)이 아니라 **Sentinel 운영 부담**(오퍼레이터 결함 우회 코드가 프로덕션에 있다). 코드 0줄(비-Sentinel 폴백이 기본값). 온프렘은 단일 Redis 로 단순화(5파드→1). 🔴 **1-14 를 명시적 선행으로 승격**. 부수 = C-8④ quorum-3 대상 3→2 |
| 2026-08-07 | **C-13 확정 — MM2 = 정방향 1개·AWS 배치·replicas 1 · 역방향은 크로스터널 consume**(가-3 해소 → **D4-a 완결**). 근거 = 설치된 CRD 스키마 실물(Strimzi 1.1.0 v1): `spec.target` 이 단수라 양방향은 CR 2개 강제 + Connect 내부토픽이 target 에 살아 워커는 타깃 옆이어야 한다. 역방향 볼륨(월 ~2,000건)에 Connect 클러스터는 과해서 크로스터널 consume 으로 대체. C-12 의 루프 논거는 부차적으로 강등 |
| 2026-08-07 | **C-12 확정 — MM2 복제 정책 = DefaultReplicationPolicy · 별칭 `onprem`**(가-1 해소). 근거 = #557 역방향으로 루프가 실현 가능해졌고, `recipe.review.*` 같은 패턴 실수를 구조로 막는다. 비용 실측 = 앱 코드 0줄·알림 0건·DLQ 자동 파생, 바뀌는 건 KEDA 4 + ConfigMap + KafkaTopic CR 8 |
| 2026-08-07 | **C-11 확정 — 온프렘 Kafka 존치**(가-2 해소, 3 브로커 RF=3 · 근거는 크롤 운반 단 하나 · DR 용도는 실측상 불필요). 🔴 **C-3 성격 정정 — "상시 대기 사이트" → "① DR 대기 + ② 크롤 상시 프로덕션" 이중역할**. §1 다이어그램 온프렘 박스 갱신 |
| 2026-08-07 | **C-10 확정 — AWS Kafka = Strimzi 자체운영**(D4-c 해소). **D4-a 운반 설계 신설**(온프렘 Kafka + MM2, 비대칭 원칙, 미확정 3건 가-1~가-3). #557 을 **신규·갱신 단일 경로**로 갱신 — 대안 2건(로컬 토픽 재사용 · 크롤러 병합) 검토 후 기각, 후기 롱테일 실측 추가 |
