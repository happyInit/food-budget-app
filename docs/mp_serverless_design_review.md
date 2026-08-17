# AI 서버리스 설계서 검토 — 상위 AWS 이관 설계 대조 결과

> **작성** 인프라 파트 · 2026-08-11
> **대상** `00_설계서.md` · `01_배치설계_이상안과현실안.md` (AI 파트, 2026-08-11) + 이슈 #590
> **대조 기준** `docs/mp_aws_prep_checklist.md` — 🔴 **PR #586 브랜치 기준**(`docs/mp-aws-prep-checklist`, C-1 ~ C-53).
> `main` 은 **C-29 까지만** 반영돼 있어 C-30~C-53 은 아직 없습니다. 아래 C-번호는 전부 #586 브랜치 원문입니다.
> **검증** 온프렘 라이브 클러스터 조회(읽기 전용) + 체크리스트 전문 grep. 재현 명령은 §부록.

---

## 0. 한 문장 요약

> **설계서 자체의 완성도는 높습니다. 상위 결정을 실제로 읽고 대조한 흔적이 분명하고, 제약 7("상위 설계에 Lambda 가 없다")을 스스로 찾아내 미결 등록으로 처리한 절차는 체크리스트 §0 규칙 그대로입니다.
> 다만 실제 파급은 "미결 1건 추가"보다 넓어서, 확정 결정 6건의 재검토를 요구합니다. 그리고 인프라가 만들 수 없는 리소스 요청이 1건 섞여 있어 이대로면 착수가 막힙니다.**

| 구분 | 건수 | 성격 |
|---|:--:|---|
| **A. 상위 확정 결정과 충돌** | 6 | 상위에서 판단해야 해소 |
| **B. 문서 내부 모순** | 3 | AI 파트가 정정하면 끝 |
| **C. 설계에 빠진 항목** | 6 | 추가 설계 필요 |
| **D. 이미 답이 있어 안 해도 되는 일** | 2 | 🎁 **약 1.5일 절약** |
| **E. 정합 — 그대로 진행** | 6 | 확인만 |

**우선 3건** — ① B-1(존재하지 않는 리소스 요청, 즉시 정정) ② A-1·A-3(일정·진입점, 답이 와야 NLB 판단 가능) ③ A-2(DR, 상위 결정 사항).
그리고 **D 는 오늘·내일 마감으로 잡혀 있는 항목**이라 먼저 확인하시길 권합니다.

---

## A. 상위 확정 결정과 부딪히는 것

### A-1 🔴 일정 — 웨이브 1(8/13~8/19)이 지금 형상에서 성립하지 않습니다

**문서 안에서 두 축이 어긋납니다.**

| 위치 | 웨이브 1의 위치 |
|---|---|
| `00_설계서.md` §4 로드맵 그림 | **8/13 ~ 8/19** (발표 전) |
| `00_설계서.md` §9 | **PHASE 1**(릴리스 준비) 에 배치 |

**그리고 체크리스트 기준으로 PHASE 0 차단이 8건 남아 있습니다.**

```
0-1 ~ 0-4   config 대공사
0-6         TSC (zone 축 보존)
0-19        AWS 서비스 쿼터 증액   ← 승인에 며칠, 명시적 "일정 블로커"
0-27        CPU 요청 재조정        ← C-45(노드 2대)의 전제
0-28        크롤 Kafka 이탈
```

게다가 **`10.10.0.0/16` VPC 가 아직 없습니다** — 이슈 #590 §2-4 가 스스로 확인한 사실입니다(계정에 기본 VPC `172.31.0.0/16` 만 존재).
즉 8/13 시점에 **Lambda 를 올릴 EKS·VPC·internal NLB 가 존재하지 않습니다.**

> **필요한 답** — 웨이브 1 은 **어느 인프라 위에서** 시작합니까? 이게 정해지지 않으면 §7 의 인프라 요청 5건은 실행 순서를 가질 수 없습니다.

---

### A-2 🔴 C-3(온프렘 이중 역할) — 두 문서에 DR 이 한 번도 나오지 않습니다

**C-3** = 온프렘은 이관 후 **① DR 대기 사이트(Warm Standby) + ② 크롤 상시 프로덕션** 이중 역할.
**C-51 ③** = 리전 전체 장애 시 **수동 · 온프렘 승격**.

여기서 두 가지가 걸립니다.

1. **AI 4종이 Lambda 가 되면 온프렘 DR 에 대체물이 없습니다.**
   `chat` · `ocr` · `video` · `ranking-serving` 은 오늘 온프렘 `app` ns 에 실재하는 워크로드입니다(§부록 A 실측). Lambda 로 옮기면 **리전 장애 시 온프렘으로 넘어가도 AI 기능은 따라오지 못합니다.**

2. **`00_설계서.md` §9 PHASE 2 가 온프렘 AI CronJob suspend 를 컷오버 항목으로 넣었습니다.**
   이중 실행 차단이라는 목적은 맞습니다. 다만 그 결과 **DR 자산이 소거**됩니다.

C-26 이 *"입구만 서로 다른 코드경로가 되는 것"* 을 이관에서 가장 큰 포기로 기록해 두었는데, 여기서는 **기능 자체가 한쪽에만 존재**하게 됩니다. 성격이 한 단계 더 무겁습니다.

> **필요한 답** — 상위 결정 사항입니다. AI 파트가 단독으로 정할 수 없고, **C-3 의 DR 범위를 앱 13종에서 9종으로 줄일 것인지**를 먼저 확정해야 합니다.

---

### A-3 🔴 C-9(공개 진입점 1개) — "트리거 = HTTP" 라고만 적혀 있고, 그 HTTP 를 누가 받는지가 없습니다

**실측** — `chat` · `ocr` · `video` 는 오늘 이미 공개 라우트를 가지고 있습니다.

```
mp-chat-route     /api/mealplan/assistant     → chat    (= mp-ai-chat-api,   W3)
mp-ocr-route      /api/pantry/ocr             → ocr     (= mp-ai-ocr-worker, W2)
mp-video-route    /api/recipes/extract        → video   (= mp-ai-video-worker, W2)
```

브라우저가 `app.mealbong.cloud/api/…` 로 직접 때리는 경로입니다.
`00_설계서.md` §6 계약표는 `mp-ai-ocr-api` · `mp-ai-video-api` · `mp-ai-chat-api` · `mp-ai-rank-serve` 의 트리거를 **"HTTP"** 로만 적었고, **그 엔드포인트의 정체가 없습니다.**

선택지는 셋인데 전부 대가가 다릅니다.

| 방식 | C-9 | 비고 |
|---|:--:|---|
| Function URL / API Gateway (공개형) | 🔴 **위반** | 공개 진입점이 2개가 됨 + Cloudflare 뒤가 아니라 C-46 의 CF 엣지 방어를 못 받음 |
| 클러스터 내 프록시 파드 → Lambda invoke | ✅ 유지 | "전면 서버리스"가 아니게 되고 홉이 하나 늘어남 |
| 프론트가 Lambda 직접 호출 | 🔴 위반 | CORS·인증·CF 밖. 권장하지 않음 |

#### 🔴 그리고 설계서가 이미 답을 흘리고 있습니다 — API Gateway 가 미등록 신규 서비스입니다

`00_설계서.md` §6 의 `mp-ai-chat-api` **타임아웃 = 29초**. 이건 **API Gateway 통합 타임아웃 상한값**입니다.
즉 설계는 암묵적으로 API Gateway 를 전제하고 있는데, **§0 의 신규 도입 3건(Lambda · EventBridge Scheduler · CloudWatch) 목록에 API Gateway 가 없습니다.**

> **참고** — 체크리스트 전문 grep 결과 `Lambda` · `서버리스` · `EventBridge` · `Scheduler` 는 **전부 0회** 등장합니다.
> `API Gateway` 는 C-46 의 *"AWS WAF 부착 가능 대상"* 나열에만 나오고 채택 맥락이 아닙니다.
> ⇒ **신규 도입은 3건이 아니라 4건**이고, 그중 하나가 C-9 를 직접 건드립니다.

---

### A-4 🔴 C-46(WAF) — chat 이 Cloudflare 뒤에서 빠지면 이미 알려진 급소가 악화됩니다

C-46(AWS WAF 미채택)의 성립 조건 3건 중 하나가 **"레이트리밋을 CF 엣지로"** 입니다.
그리고 같은 결정문에 이렇게 적혀 있습니다.

> 🔴 별건 = chat rate-limit 이 XFF 최좌측을 신뢰한다 — **오늘도 이미 우회 가능**하고 SG·numTrustedProxies 로는 안 고쳐진다

`chat-api` 가 API Gateway 경유가 되면 그 경로는 **CF 엣지 뒤가 아닙니다.**
C-46 이 *유일한 근본 해결책*으로 지목한 수단이 이 함수에는 적용되지 않고, **알려진 취약점이 한 겹 더 벗겨집니다.**

> **필요한 판단** — chat 을 Lambda 로 옮긴다면 레이트리밋을 어디서 걸 것인지(API Gateway 사용량 계획 / WAF / 함수 내부)가 함께 정해져야 합니다.

---

### A-5 🟡 C-45(노드 2대) · C-27(전 서비스 Blue-Green) 재판정 대상

**C-45** 의 재집계 **6.24 vCPU / 18.81 GiB** 는 "사라지는 것" 목록이
`Kafka · Redis · kubecost · MetalLB · MinIO · 마스터 컴포넌트 · DaemonSet` 뿐입니다 — 즉 **AI 파드가 클러스터에 남는다는 전제**로 계산돼 있습니다.

AI 4종이 빠지면 숫자는 **유리한 쪽**으로 바뀝니다. 다만 C-45 는 *"0-27 미적용이면 104% 로 2대에 안 들어간다"* 는 아슬아슬한 판정이라, **입력이 바뀌면 재계산 대상**입니다(줄어드는 쪽이라도 근거표는 갱신돼야 합니다).

같이 움직이는 것 — **C-27 "전 서비스 Blue-Green"의 '전 서비스'가 13종 → 9종**이 됩니다.
실측 앱 워크로드 13개 중 `mp-chat` · `mp-ocr` · `mp-video` · `mp-ranking-serving` 이 빠지기 때문입니다. **ADR-0002 의 범위 정의**에 반영이 필요합니다.

---

### A-6 🟡 C-15 재론 — PG 관리형은 이미 닫힌 결정입니다

`00_설계서.md` §10 #3·#9 와 `01` §1 #1 의 *"PG 를 관리형(RDS·Aurora)으로 = 이상안 · 장기 후보 등재"* 는
**C-15 에서 이미 미채택으로 확정**된 사안입니다(RDS · Aurora · OpenSearch Service **전부**).

AI 파트가 *"인프라 소관이라 우리가 선택하지 않는다"* 고 선을 그은 것 자체는 정확합니다.
다만 체크리스트 §0 이 **"결정을 새로 지어내지 말 것 — §0.1 에 있으면 확정"** 이므로, **"장기 후보"가 아니라 "C-15 로 종결"** 로 표기하는 편이 맞습니다. 실무 영향은 없고 문구 정리 건입니다.

---

## B. 문서가 스스로 모순되는 것 — AI 파트에서 정정하면 끝납니다

### B-1 🔴 "ElastiCache Valkey Gateway 엔드포인트" — 그런 리소스가 존재하지 않습니다

**네 군데에 같은 요청이 있습니다** — `00_설계서.md` §0 제약3 해법 · §1 표 · §2 그림 1 캡션 · §10 요청 #2.

> *"추가 요청은 **ElastiCache Valkey Gateway 엔드포인트 1종**만 — S3 와 같은 **무료** Gateway 타입이라 비용 논거가 성립합니다"*

두 가지가 사실과 다릅니다.

1. **Gateway 엔드포인트는 S3 와 DynamoDB 둘뿐입니다.** ElastiCache 용 Gateway 엔드포인트는 없습니다.
2. **애초에 필요가 없습니다.** ElastiCache 는 VPC 서브넷의 ENI 라 같은 VPC 안이면 그대로 닿습니다.

#### 🔴 그리고 같은 문서가 다른 자리에서 정확히 그렇게 씁니다

> §0 *"「그러면 ElastiCache Valkey 는 왜 NLB 가 필요 없나 — 서브넷이 다른데도 괜찮은 이유」*
> *같은 VPC 안 서브넷끼리는 라우트 테이블에 `10.10.0.0/16 → local` 이 **자동으로 있고 지울 수도 없어서**, NAT·게이트웨이·피어링 없이 그대로 닿습니다. … **필요한 건 보안그룹 한 줄뿐입니다**"*

앞뒤가 서로를 부정하고 있습니다. **§0 뒷부분이 맞습니다.**

> **조치** — 요청 목록에서 삭제하고, Valkey 는 **"SG 인바운드 6379 에 AI 전용 SG 를 소스로 추가"** 한 줄로 대체.
> (참고: C-31 이 *"S3 Gateway 만 채택"* 으로 확정한 것과도 이 쪽이 일치합니다.)

---

### B-2 🟡 인프라 요청 목록이 세 가지 버전으로 갈립니다

| 위치 | 요청 내용 |
|---|---|
| `00` §0 제약3 마무리 | *"인프라 요청은 internal NLB 하나만 남습니다"* |
| `00` §10 요청 #2 | NLB **+ ElastiCache Valkey Gateway EP 1종** |
| `00` §12 대조 #1 | **EP 6종** — `bedrock-runtime` · `secretsmanager` · `sqs` · **`dynamodb`** · `logs` · `monitoring` 채택 여부 |

§12 는 **DynamoDB 가 §0 에서 철회된 것**을 반영하지 않은 stale 입니다.
결과적으로 **인프라가 결국 무엇을 만들어야 하는지가 확정되지 않은 상태**입니다.

> **조치** — 요청 목록을 한 곳(§10)으로 단일화하고 §0·§2·§12 는 그것을 참조만 하도록.

---

### B-3 🟡 NodePort 탈락 근거의 "정정"이 오히려 부정확합니다

`01` §5-3 및 `00` §0 ADR 표 각주:

> *"※ 초기 근거였던 「Karpenter 노드 교체」는 정확하지 않습니다 — PG·ES 는 taint 로 고정 노드 2대에 묶여 있어 Karpenter 영향을 받지 않습니다"*

**taint 는 "PG 파드가 Karpenter 노드에 뜨지 않는다"는 뜻이지, "그 노드에 NodePort 가 안 열린다"는 뜻이 아닙니다.**
NodePort 는 **모든 노드**에서 열리고, `externalTrafficPolicy: Cluster` 면 어느 노드로 보내도 kube-proxy/eBPF 가 파드까지 넘겨줍니다.

⇒ **원래 근거(노드 IP 를 함수 환경변수에 박으면 노드 교체 시 조용히 끊긴다)가 맞았습니다.**
결론(NLB 채택)은 바뀌지 않으므로 실무 영향은 없지만, 근거를 잘못 고쳐 두면 다음 사람이 같은 자리를 다시 되짚습니다.

---

## C. 설계에 빠진 항목

### C-1 🔴 네트워크 정책 — "매니페스트 2개면 끝"이 아닙니다

**실측** — `data` ns 의 `mp-pg-pooler` · `mp-es` NetworkPolicy 가 허용하는 ingress 는 **딱 둘**입니다.

```yaml
# data/mp-pg-pooler  (podSelector: cnpg.io/podRole=pooler)
ingress:
  - from: [{ namespaceSelector: {kubernetes.io/metadata.name: app},
             podSelector:       {tier: backend} }]
    ports: [{port: 5432, protocol: TCP}]
  - from: [{ ipBlock: {cidr: 192.168.0.0/24} }]      # 온프렘 LAN — AWS 엔 없는 대역
```

`mp-es` 도 같은 구조입니다(app tier=backend / pipeline ns / exporter / pgsync / elastic-system + 같은 LAN ipBlock).

**NLB → NodePort 경로는 `externalTrafficPolicy: Cluster`(설계서 권장값)면 노드 IP 로 SNAT 되어 도착합니다.**
→ 위 두 규칙 **어디에도 걸리지 않습니다.** 그리고 LAN 규칙은 AWS 에서 죽은 규칙이 됩니다(이슈 #549 가 그 규칙을 손보라는 건입니다).

**부수 효과가 하나 더 있습니다** — SNAT 때문에 **netpol 층에서는 Lambda 와 다른 VPC 트래픽을 구분할 수 없습니다.**
즉 통제가 **SG 하나에만** 걸립니다. C-46 이 *"WAF 를 포기했으므로 CF 우회 차단이 SG 하나에 걸린다"* 고 적어둔 것과 **같은 형태의 단일 의존이 하나 더** 생기는 셈입니다.

> **조치** — `00` §7-1 인프라 요청(5건) · §10(6건) 어디에도 netpol 이 없습니다. **요청 항목으로 추가**가 필요하고,
> "어느 소스를 어떤 식별자로 허용할 것인가"(노드 CIDR? 전용 서브넷 CIDR?)는 설계 판단이 필요합니다.

---

### C-2 🔴 클러스터 → Lambda 방향이 설계에 없습니다

`mp-ai-rank-serve` 는 `recipe` / `mealplan` 이 부르는 내부 호출이고, `chat-api` 도 같은 성격입니다.
그런데 `01` §4-3 의 "외부 트래픽 원천" 표에는 **S3 · SQS · Secrets · STS · CloudWatch · Bedrock · Gemini** 만 있고
**`lambda:Invoke`(파드 → Lambda)가 없습니다.**

파드가 Lambda 를 부르면 → **NAT(C-47, 1대) 경유 + AZ 교차 전송료**.
**경로도 비용도 미설계**입니다. (Interface EP 는 C-31 로 미채택이라 NAT 가 유일 경로입니다.)

---

### C-3 🔴 PG 롤 격리(#546)가 선행이어야 합니다

현재 **앱 9종이 `fbapp` 단일 계정**을 씁니다(이슈 #546, OPEN — *"롤 정의는 IaC 밖"*).
여기에 Lambda 10개가 같은 계정으로 붙으면 **최소권한이 더 나빠집니다.** Lambda 는 클러스터 밖이라 사고 시 회수 경로도 다릅니다.

Secrets Manager 에 DSN 을 넣기 **전에** 정해야 하는 항목인데 두 문서에 없습니다.

> 참고: ES 쪽은 #521(슈퍼유저 PoLP)이 이미 CLOSED 라 롤·유저 체계가 있습니다. **`chat-api` 용 ES 계정 추가**만 별도로 필요합니다.

---

### C-4 🟡 Lambda 동시성 쿼터가 `0-19` 에 없습니다

체크리스트 **`0-19`(AWS 서비스 쿼터 증액 — 승인에 며칠, 명시적 "일정 블로커")** 의 대상은 **vCPU · EIP · NLB** 뿐입니다.

`01` §4-1 의 예약 동시성 합계 **71** 은 일반적인 계정 기본 한도 안에 들어가지만,
- 신규 계정은 기본값이 낮게 시작하는 경우가 있고,
- 예약 동시성을 쓰면 **미예약 풀의 최소 유지분**을 침범할 수 없습니다.

`00` §10 요청 #1(IAM ReadOnlyAccess 부재)로 **확인 자체가 막혀 있는 상태**입니다.

> **조치** — `0-19` 에 **Lambda 동시성** 항목을 추가해 vCPU·EIP·NLB 와 **같이 신청**. 리드타임이 있으므로 늦으면 그대로 일정에 물립니다.

---

### C-5 🟡 Grafana → CloudWatch 는 "추가 인프라 0" 이 아닙니다

`00` §0 제약4 의 해법(Grafana 에 CloudWatch 데이터소스 추가)에서 빠진 것 3가지.

| 항목 | 내용 |
|---|---|
| **자격증명** | Grafana SA 에 **IRSA(C-30)** 부여 필요. 🔴 **온프렘 Grafana 는 IRSA 불가** → 정적 키가 생기고, 열린 항목 ③ 이 *"이 설계의 유일한 보안 후퇴"* 라 부르는 항목이 **둘**이 됩니다 |
| **알림 경로** | *"알림은 기존 Alertmanager 로 통일"* 이라 했으나, Prometheus rules → Alertmanager 경로와 Grafana 알림 경로는 다릅니다. C-22 가 *"알림 파이프를 늘리지 않는다"* 를 원칙으로 삼았으므로 **여기가 예외가 되는지 확인** 필요 |
| **과금** | CloudWatch `GetMetricData` 는 요청 과금입니다. 대시보드 자동 새로고침이 이걸 지속적으로 호출합니다. §14 C-1 비용 모델에 항목이 없습니다 |

> 참고: 체크리스트에는 이미 *"control plane logging → CloudWatch → S3 export, 또는 Loki 수집이 필요하고 **계획 0건**"* 이라는 미해결 항목이 있습니다. **같은 계열이므로 묶어서 설계하면 한 번에 끝납니다.**

---

### C-6 🟡 총액 비교의 분모가 무효 상태입니다

`00` §0 이 인용한 *"$16.43/월은 확정 절감분 −$238.06 의 6.9%"* 에서,
**C-31 의 총액 $857.26 은 전제 6개(AZ 2 · Kafka 0 · 터널 0 · VPC 3 · 노드 2 · NAT 1)가 바뀌어 이미 무효**이고 **열린 항목 ⑨(총액 재산정)로 열려 있습니다.**

여기에 서버리스가 **새 입력 4종**을 더합니다 — Lambda 실행비 · API Gateway 요청비(§6-1 폴링이 접수 1건당 **20~40배**를 곱합니다) · NAT 데이터 처리 · CloudWatch 수집.

> **조치** — §14 C-1(비용 모델, 3h)의 산출물을 **열린 항목 ⑨ 의 입력으로 제출**하는 형태로 맞추면 두 작업이 하나가 됩니다.

---

## D. 🎁 이미 답이 있어서 **안 해도 되는 일** 2건 — 약 1.5일 절약

설계서가 마감을 걸어둔 항목 중 둘은 체크리스트에 **이미 실측 결과가 있습니다.**

### D-1 `G-02 aarch64 휠 미확인` (마감 8/11 · §11-1 제안 ④ 40분) → **전수 실측 완료됨**

체크리스트 `1-6` 레인 기록:

- **aarch64 휠 없는 파이썬 패키지 0건** — requirements 19개 + pgsync 7.1.0 전부 해석, **해석된 패키지·버전 집합이 amd64 와 완전히 동일(106개, diff 0줄)**
- **`python-crfsuite` 명시 확인** — 정확히 이것이 *"requirements 에 이름이 없는 전이 의존이라 `pip download --no-deps` 로는 통째로 놓친다"* 고 기록돼 있습니다
- **lightgbm 은 실동작까지** — arm64 컨테이너를 QEMU 로 실제 기동해 `ranking-serving` 의 **lightgbm 학습·예측 / sklearn fit score 0.985 / scipy BLAS** 를 돌렸습니다
- **`confluent-kafka`** 는 C-44(Kafka 전면 제거)로 **의존 자체가 소멸** — 설계서 §13 판단과 동일

⇒ 남은 것은 **Lambda 런타임(`provided.al2023` / 파이썬 런타임)과 EKS 컨테이너의 차이 확인**뿐이고, **새로 조사할 항목이 아닙니다.**

### D-2 `A-3 MinIO 모델 아티팩트` (§14 · *"이관 전 유실 가능성이 있는 유일한 저장소"* · 1h) → **이미 비어 있습니다**

체크리스트 실측 기록:

> **"모델 사본 0개(MinIO `models` 버킷 = 0 바이트) · 클러스터 내 재생성 경로 0(`retrain.py` 미배포)"**

즉 **MinIO 에 잃을 것이 없습니다.**
진짜 위험은 설계서가 스스로 최상위로 꼽은 **G-01(CRF 모델 단일 사본 · gitignored · 복구 불가)** 이고, 그 판단은 정확합니다.

덧붙여 **`ranker.pkl` 은 C-20 에서 "이미지에 굽기"로 이미 확정**돼 있어 설계서 §7 의 패키징 방침(git 정본 + 이미지 COPY + S3 보존)과 방향이 같습니다. **PVC 소거 대상**이기도 해서 §3 의 Rehost 판단과도 맞습니다.

---

## E. 정합 — 그대로 진행하면 되는 것

| # | 항목 | 확인 |
|:--:|---|---|
| 1 | **제약 7 을 스스로 발견해 "미결 등록"으로 처리** | 체크리스트 §0 규칙 그대로. 절차가 정확합니다 |
| 2 | **C-44(Kafka 제거)를 반영해 `price-detect` → SQS 발행** | `confluent-kafka`(librdkafka) 의존이 사라져 **이미지 → zip** 으로 내려왔습니다. 상위 결정이 하위 설계를 실제로 단순화한 사례라 **발표 소재로 적합**합니다 |
| 3 | **DynamoDB 철회 → Valkey 재사용** | *"대안이 있는 것은 신규 도입하지 않는다"* + C-14 재사용. 판단 기준이 우리 것입니다 |
| 4 | **C-31 수용 + Gemini 실측** | *"Vertex AI Gemini 는 AWS 밖이라 VPC 엔드포인트가 존재하지 않는다 → EP 를 몇 개 깔아도 가장 무거운 트래픽은 그대로 NAT"* — 정확하고, C-31 을 반박이 아니라 **근거로 강화**합니다 |
| 5 | **Tailscale 경로에 데이터를 태우지 않음**(후보 F 탈락) | C-53 의 경계선(*"데이터는 S3, 사람은 Tailscale · ACL 로 강제"*)을 정확히 지켰습니다 |
| 6 | **arm64 · VPC 내부 배치 · Secrets Manager(C-36) · 키리스** | C-29/C-45 · C-36 · C-30 방향과 전부 정합 |

**그리고 internal NLB(target=instance) 채택 자체는 타당합니다** — 진단이 맞고(C-7 오버레이 → 파드가 VPC 주소를 안 받음, C-53 이 같은 사실을 이미 기록), C-26 의 유입 NLB 와 동일 패턴이며, 되돌리기가 Service 삭제 한 줄입니다. **위 A·B·C 가 정리되면 승인에 걸리는 것은 없습니다.**

---

## F. 정리 — "미결 1건 등록"이 아니라 확정 결정 6건의 재검토입니다

| 건드리는 확정 결정 | 무엇이 갈리나 | 누가 정하나 |
|---|---|---|
| **C-9** 공개 진입점 1개 | chat·ocr·video·rank 의 HTTP 앞단 (**API Gateway = 미등록 4번째 신규 서비스**) | 상위 |
| **C-3 / C-51** 온프렘 DR | AI 4종이 DR 에서 사라짐 + CronJob suspend 로 자산 소거 | 상위 |
| **C-45** 노드 2대 | 사이징 입력 변경 → 근거표 재계산 | 인프라 |
| **C-27** 전 서비스 Blue-Green | 대상 13종 → 9종 (**ADR-0002 범위**) | 인프라 |
| **C-46** WAF · 레이트리밋 | chat 이 CF 엣지 밖으로 → 알려진 XFF 급소 악화 | 상위 |
| **열린 항목 ⑨** 총액 | 입력 4종 추가 | 인프라 |

### 회신 요청 — AI 파트에서 처리 가능한 것

- [ ] **B-1** ElastiCache Gateway EP 요청 **삭제**, SG 한 줄로 대체 (§0·§1·§2·§10 네 군데)
- [ ] **B-2** 인프라 요청 목록 **§10 하나로 단일화** (§12 의 EP 6종 stale 제거)
- [ ] **B-3** NodePort 탈락 근거 각주 원복 (원래 근거가 맞음)
- [ ] **A-3** `mp-ai-*-api` 4종의 **HTTP 앞단 명시** + API Gateway 를 §0 신규 도입 목록에 추가
- [ ] **A-6** C-15 표기를 "장기 후보" → "C-15 로 종결"
- [ ] **C-2** 클러스터 → Lambda 호출 경로·비용 추가
- [ ] **C-4** `0-19` 에 Lambda 동시성 항목 추가 요청
- [ ] **C-5** Grafana↔CloudWatch 자격증명·알림 경로 보완
- [ ] **D-1 / D-2** 마감 걸린 두 항목 **취소 또는 축소** (체크리스트 1-6 · MinIO 실측 결과 확인)

### 상위(인프라·팀) 판단 대기

- [ ] **A-1** 웨이브 1 이 어느 인프라 위에서 시작하는가 (PHASE 0 차단 8건 · VPC 미생성)
- [ ] **A-2** C-3 의 DR 범위를 앱 13종 → 9종으로 줄일 것인가
- [ ] **A-4** chat 의 레이트리밋을 어디서 걸 것인가
- [ ] **C-1** netpol 에서 NLB 경로를 어떤 식별자로 허용할 것인가
- [ ] **C-3** #546(PG 롤 격리)을 Lambda 착수의 선행으로 둘 것인가

---

## 부록 — 재현 명령

### A. 앱 워크로드 · 공개 라우트 (온프렘 라이브, 읽기 전용)

```bash
kubectl -n app get deploy,rollout -o custom-columns=NAME:.metadata.name,REPLICAS:.spec.replicas
# → 13종. chat · ocr · video · ranking-serving 실재

kubectl -n app get httproute \
  -o custom-columns=NAME:.metadata.name,PATHS:.spec.rules[*].matches[*].path.value,BACKEND:.spec.rules[*].backendRefs[*].name
# → mp-chat-route / mp-ocr-route / mp-video-route 가 공개 라우트를 보유
```

### B. 네트워크 정책 (C-1 근거)

```bash
kubectl -n data get netpol mp-pg-pooler mp-es -o yaml
# → ingress = (app ns tier=backend) + (ipBlock 192.168.0.0/24) 둘뿐
```

### C. 체크리스트 대조 (PR #586 브랜치)

```bash
git fetch origin docs/mp-aws-prep-checklist
git show origin/docs/mp-aws-prep-checklist:docs/mp_aws_prep_checklist.md > /tmp/checklist586.md

grep -n "Lambda\|서버리스\|serverless\|EventBridge\|Scheduler\|Function URL" /tmp/checklist586.md
# → 0건 (API Gateway 는 C-46 의 WAF 부착 대상 나열에만 등장)

grep -n "0-19" /tmp/checklist586.md          # 쿼터 대상 = vCPU·EIP·NLB
grep -n "ranker.pkl" /tmp/checklist586.md    # C-20 = 이미지에 굽기
grep -n "MinIO .models" /tmp/checklist586.md # models 버킷 0 바이트 · retrain.py 미배포
```

### D. CronJob 실물

```bash
kubectl get cronjobs -A
# → 총 22종. AI 관련은 pipeline ns 의
#   mp-summarize-reviews · mp-score-review-sentiment · mp-poller-price-anomaly (3종)
#   ner-backfill · shelflife-draft 는 CronJob 이 아니라 수동 실행 — 설계서 §6 과 일치
# ⚠️ §9 의 "AI CronJob 4종" 은 4번째가 무엇인지 확인 필요 (mp-chat-insights?)
```

---

**이 문서는 검토 결과이지 결정이 아닙니다.** 확정 결정은 전부 `docs/mp_aws_prep_checklist.md`(C-1 ~ C-53)에 있고,
새 결정이 필요한 항목은 그 문서의 **"열린 항목" 표에 등재**하는 것이 절차입니다 — 설계서 §0 제약 7 의 판단과 같습니다.
