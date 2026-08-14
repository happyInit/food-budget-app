# Cloudflare DNS 현황·이관 설계 — `mealbong.cloud`

> **이 문서의 역할** = Cloudflare DNS 의 **현행 SSOT**(실측 2026-08-14) + AWS 이관 목표 형상·컷오버 절차.
> 🔴 **결정의 정본은 `docs/mp_aws_prep_checklist.md`** 다. 이 문서는 그것을 **DNS 축으로 투영**할 뿐이고,
> 여기서 새 결정을 만들지 않는다. 정본에 없는 것은 아래 §0 에 **미결**로 모아 둔다.
>
> 🔴 **이 문서를 쓰는 동안 레코드는 하나도 바꾸지 않았다** — 전부 읽기 전용(GET) 조회다.
> 새 레코드도 만들지 않았다. **가리킬 대상(AWS LB)이 아직 0개**이기 때문이다(2026-08-14 실측).

---

## §0 미결 — 정본에 답이 없어 여기서 정하지 않은 것

| # | 미결 | 왜 지금 못 정하나 | 정본 위치 |
|---|---|---|---|
| ㉠ | **`argocd.mealbong.cloud` 의 이관 후 형상** | 정본에 서술이 **없다.** C-5 로 cloudflared 가 DR 전용(평시 replicas 0)이 되면 이 터널도 멈추는데, EKS ArgoCD 가 웹훅을 어디로 받는지 정해진 바가 없다. 🟡 **C-89(2026-08-14, Jenkins 영구 존치)가 판단을 한쪽으로 기울인다** — 온프렘 CI·ArgoCD 가 계속 도는 이상 이 웹훅도 계속 필요해 보인다. 다만 **정본이 그렇게 말한 적은 없어** 미결로 둔다 | 미기재 |
| ㉡ | **와일드카드 `*` A레코드의 이관 후 처분** | 정본은 와일드카드 **인증서**만 다룬다(1-59). **A레코드**(`*` → `192.168.0.15`)는 언급 0건. 온프렘이 크롤 프로덕션으로 남으므로(C-70) 존치가 자연스러워 보이나 **확정된 바 없다** | 미기재 |
| ㉢ | **`aws.mealbong.cloud` 를 A3 이후 남길지 지울지** | C-78 A2 는 *"내부 검증"* 용도만 규정한다. 검증이 끝난 뒤의 처분은 없다 | C-78 |
| ㉣ | **1-59 와일드카드 DNS-01 경합 해법** | 정본이 *"선택지 = ① 사이트별로 다른 이름을 쓴다…"* 로 **열어 둔 상태** | `1-59` |
| ㉤ | **프록시(주황) 레코드의 TTL 을 300 미만으로 낮출 수 있는가** | **쓰기 없이는 확인 불가**. 실측상 `ttl=1`(auto)·응답 300 인데, 이것이 Free 플랜의 강제인지 단순 기본값인지는 PATCH 를 시도해야 알 수 있다. §3.2 가 이 답에 의존한다 | 미기재 |
| ㉥ | **A2 앱 종수 — 12 인가 13 인가** | C-78 행은 **12종**(C-84 정정 명시), 같은 문서 §A2 표(3235행)는 **13종**. DNS 와 직접 관계는 없으나 같은 창에서 읽히므로 적어 둔다 | C-78 ↔ §A2 표 |

### 🔴 정정 후보 — 정본·`CLAUDE.md` 서술이 실측과 어긋나는 것 2건

| # | 어긋난 서술 | 실측 | 조치 |
|---|---|---|---|
| ⓐ | `CLAUDE.md` 19행 *"외부 LB = **NLB TCP:443 패스스루** — C-26 (**ALB 기각**)"* | C-60(2026-08-11)이 **ALB 로 정정**했고 C-26 행 자신이 `🔄 정정(2026-08-11, C-60)` 머리말을 달고 있다 | 별건 PR (§2.1) |
| ⓑ | C-84 *"현행 **CF Access** 구글 SSO"* · 정본 2331행 *"내부 도구 **Access** 는 전부 그대로"* | **내부 도구 6종은 회색 와일드카드 → `192.168.0.15`(사설 LAN)** 이다. 회색이면 트래픽이 CF 엣지를 **지나지 않으므로 CF Access 가 적용될 수 없다.** 게다가 Zero Trust 는 결제가 막혀 미채택 상태다 | 별건 PR (§4.3) |

---

## §1 현행 실측 (2026-08-14)

### 1.1 존

```
zone        mealbong.cloud     status=active     plan=Free Website
name server kia.ns.cloudflare.com · rocky.ns.cloudflare.com
레코드 총계  5건   (API result_info.total_count = 5)
```

🔴 **apex(`mealbong.cloud`)에는 레코드가 없다.** 조회하면 `NOERROR` + Answer 0 (= NODATA)다.
루트 도메인은 지금 아무것도 서비스하지 않는다.

### 1.2 레코드 전량 — 5건이 전부다

| 이름 | 타입 | 값 | 프록시 | TTL | 무엇인가 |
|---|---|---|---|---|---|
| `*.mealbong.cloud` | A | `192.168.0.15` | ⚪ **회색**(DNS만) | auto(=300) | 내부 게이트웨이 `mp-gw-internal`. CF 메모 = *"mp-gw-internal(.15) LAN wildcard 2026-07-30"* |
| `app.mealbong.cloud` | CNAME | `4c7d83d9-…cfargotunnel.com` | 🟠 **주황**(프록시) | auto(=300) | **실사용자 앱.** 온프렘 인클러스터 cloudflared(`mp-ingress/mp-app-tunnel-creds`) |
| `argocd.mealbong.cloud` | CNAME | `db79b297-…cfargotunnel.com` | 🟠 주황 | auto(=300) | ArgoCD 웹훅 터널(`argocd/argocd-webhook-tunnel-creds` · `k8s_nodes.yml:argocd_webhook_tunnel_id`) |
| `ci.mealbong.cloud` | CNAME | `0ba62307-…cfargotunnel.com` | 🟠 주황 | auto(=300) | Jenkins 웹훅(호스트 C `.10`) · **`/github-webhook/` 경로만** 노출 |
| `gitlab.mealbong.cloud` | CNAME | `88568ee9-…cfargotunnel.com` | 🟠 주황 | auto(=300) | AWS GitLab EC2 · **경로 제한 ingress**(OIDC 2경로만 200 · 루트 404) |

> **터널 UUID 를 적은 근거** — `infra/ansible/secrets.yml.example` 이 *"tunnel_id(비밀 아님)"* 라 명시하고,
> `group_vars/ci.yml`·`group_vars/k8s_nodes.yml` 에 **이미 커밋돼 있다**. 게다가 `dig CNAME` 한 번이면
> 누구나 읽는 공개 DNS 값이다. **비밀은 `TunnelSecret`** 쪽이고 그것은 이 문서에 없다(Ansible vault · K8s Secret).
> 그럼에도 롤백은 UUID 를 손으로 옮겨 적지 말고 **§5.1 스냅샷**을 쓴다 — 사람이 타이핑할 값이 아니다.

### 1.3 왜 주황/회색이 그렇게 돼 있나

**주황 4건은 선택이 아니라 요구사항이다.** `*.cfargotunnel.com` 은 Cloudflare 엣지 **안에서만** 의미가 있는
이름이라, 프록시를 끄면 해석할 대상이 사라진다. 즉 **cloudflared 를 쓰는 한 그 레코드는 주황일 수밖에 없다.**
⇒ 지금 주황인 것은 *"CF 를 엣지로 쓰기로 했다"* 는 판단의 결과가 아니라 **터널을 쓰기로 한 것의 부산물**이다.
이 구분이 §2 에서 중요해진다 — C-60 이 회색으로 내리는 것은 **터널을 떼는 것과 같은 동작**이다.

**회색 1건(와일드카드)은 의도다.** `192.168.0.15` 는 사설 LAN 주소라 프록시할 대상이 못 되고,
내부 도구 6종(grafana·minio 콘솔·loki·jenkins·sonarqube·harbor UI)은 **LAN 에서만** 접근한다
(`docs/mp_k8s_infra_status.md` §4.0). 인증서는 별개로 LE 와일드카드 1장을 **DNS-01** 로 받는다.

🔴 **C-60 이 말하는 "회색"은 이 와일드카드가 아니다.** C-60 의 회색은 **`app` 레코드의 미래 상태**다.
같은 단어가 현행 1건과 목표 1건을 각각 가리키므로 읽을 때 섞지 말 것.

### 1.4 🔴 와일드카드가 앞으로 만들 레코드를 **미리 가로챈다** (신규 발견 · 정본 미기재)

이관에서 만들 이름 3개가 **지금 이미 응답한다** — 없는 이름인데 `NXDOMAIN` 이 아니다:

```
aws.mealbong.cloud       TTL=300 → 192.168.0.15     ← C-78 A2 가 쓸 이름
finops.mealbong.cloud    TTL=300 → 192.168.0.15     ← C-84 대시보드
ops.mealbong.cloud       TTL=300 → 192.168.0.15     ← C-84 대시보드
```

와일드카드 `*` 가 **명시 레코드가 없는 모든 이름**을 받아내기 때문이다.

🔴 **위험한 것은 "안 된다"가 아니라 "조용히 잘못된 곳을 가리킨다"** 는 점이다.
레코드 만드는 것을 잊으면 사용자·검증자는 `NXDOMAIN`(= 명백한 오설정)이 아니라
**사설 주소로의 연결 타임아웃**을 본다. 원인이 DNS 라는 단서가 응답에 하나도 없다.

🟢 **막는 법은 간단하다** — 명시 레코드가 와일드카드를 이긴다(더 구체적인 이름이 우선).
`aws`·`finops`·`ops` 레코드를 만드는 순간 그림자는 걷힌다. **잊지만 않으면 된다.**
⇒ 그래서 §5.2 검증 절차에 *"만들기 전과 후의 응답이 바뀌었는지"* 를 명시적으로 넣었다.

⚠️ 정본은 와일드카드 **인증서**의 경합(1-59)은 알고 있으나 **A레코드의 그림자**는 다루지 않는다
(`192.168.0.15`·"A레코드" 검색 결과 0건). §0 ㉡ 로 올린다.

### 1.5 실측 방법 (재현용)

전부 **읽기 전용**이다. 토큰 값은 한 번도 출력하지 않는다(§4.2).

```bash
# ① 레코드 전량 — 클러스터 안에서 토큰을 꺼내 그대로 curl 에 넘긴다(화면에 안 찍힌다)
ssh ubuntu@192.168.0.17 'bash -s' <<'EOF'
T=$(sudo kubectl -n observability get secret mp-cloudflare-api-token -o jsonpath="{.data['api-token']}" | base64 -d)
Z=$(curl -s -H "Authorization: Bearer $T" \
      "https://api.cloudflare.com/client/v4/zones?name=mealbong.cloud" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"][0]["id"])')
curl -s -H "Authorization: Bearer $T" \
  "https://api.cloudflare.com/client/v4/zones/$Z/dns_records?per_page=200"
EOF

# ② 프록시 상태·TTL 을 바깥에서 교차 확인 (자격증명 불요)
#    주황이면 CF 애니캐스트 IP(104.21.x·172.67.x)가, 회색이면 오리진 주소가 그대로 돌아온다
curl -s -H 'accept: application/dns-json' \
  "https://cloudflare-dns.com/dns-query?name=app.mealbong.cloud&type=A"
```

②가 ①의 **독립 검증**이라는 점이 중요하다 — API 의 `proxied` 필드를 믿지 않고 응답으로 확인한다.
`app` 이 `104.21.81.151`·`172.67.162.63` 을 돌려준 것이 주황의 증거다.

---

## §2 목표 형상

### 2.1 C-60 vs C-26 — **C-60 이 이긴다** (근거 3중)

| | 결정 | 날짜 | 진입 형상 |
|---|---|---|---|
| 구 | **C-26** | 2026-08-09 | Cloudflare(주황) → **NLB TCP:443 패스스루** → Istio GW · ALB 기각 |
| 신 | **C-60** | 2026-08-11 | Cloudflare(**회색**) → **ALB**(ACM 종단 · AWS WAF) → Istio GW |

1. **날짜가 늦은 쪽이 이긴다** — 08-11 > 08-09.
2. **애초에 충돌이 아니다.** C-26 행 자신이 `🔄 정정(2026-08-11, C-60)` 머리말을 달고 있다.
   그 아래 남은 NLB 서술은 **정정 전 본문**이다.
3. **정정된 결정행은 머리말이 본문을 이긴다** — A0 결함 #24 가 정확히 이 함정(C-23 의 SSM/Secrets Manager)에서
   나왔고 같은 실수를 반복하지 않기 위해 규칙으로 남아 있다.

> 🔴 **이 규칙은 지금도 살아 움직인다** — 이 문서를 쓰는 중에 **C-2** 가 같은 모양이었다.
> 본문은 *"CI = GitLab (Jenkins 은퇴)"* 인데 머리말이 `⟳ 정정(2026-08-14, C-89) — 은퇴 철회 · 쌍방 영구 운영` 이다.
> 본문만 읽고 `ci.mealbong.cloud` 를 *"이관 후 은퇴"* 로 적었다가 되돌렸다(§2.2).
> **C-* 를 인용할 때는 행 머리말을 먼저 볼 것.**

C-60 이 ALB 로 간 근거는 성능·비용이 아니라 **엣지를 하나로 만드는 것**이다 — 엣지가 둘(CF 주황 + AWS)이면
*"이 트래픽이 CF 를 거쳤다"* 를 증명하는 장치(CF IP 허용목록 상시 갱신·mTLS·헤더 락)가 영구 운영 부담으로 남는다.
**회색이면 우회라는 개념 자체가 없다.**

🔴 **`CLAUDE.md` 19행이 stale 하다** — *"NLB TCP:443 패스스루 — C-26 (ALB 기각)"*.
이 문서 범위 밖이라 고치지 않았다. **별건 PR 필요**(§0 ⓐ).

### 2.2 레코드별 목표

| 이름 | 현행 | 목표 | 근거 | 언제 | 지금 가능? |
|---|---|---|---|---|---|
| `app.mealbong.cloud` | 🟠 주황 · CNAME→터널 | ⚪ **회색** · **ALB** | **C-60** · 작업 `1-54` | **A3 컷오버** | ❌ ALB 없음 |
| `aws.mealbong.cloud` | (없음 · 와일드카드가 가로챔) | ⚪ 회색 · ALB · **TTL 60** | **C-78 A2** | **A2** | ❌ ALB 없음 |
| `finops.mealbong.cloud` | (없음 · 와일드카드가 가로챔) | ⚪ 회색 · 대시보드 EC2 EIP | **C-84** | 대시보드 EC2 생성 후 | ❌ EC2 없음 |
| `ops.mealbong.cloud` | (없음 · 와일드카드가 가로챔) | ⚪ 회색 · 대시보드 EC2 EIP | **C-84** | 대시보드 EC2 생성 후 | ❌ EC2 없음 |
| `_acme-challenge…` (ACM 검증 CNAME) | (없음) | ⚪ 회색 · ACM 이 지정한 값 | **C-60** · 작업 `1-48` | A2 전 | ❌ ACM 요청 전 |
| `ci.mealbong.cloud` | 🟠 주황 · 터널 | **변경 없음 · 🔴 영구 존치** | **C-89**(2026-08-14) — *"Jenkins 은퇴 **철회** · 쌍방 영구 운영"*. 온프렘 amd64 이미지 공급원이 계속 필요하다 | — | — |
| `gitlab.mealbong.cloud` | 🟠 주황 · 터널 | **변경 없음** | A0.5 라이브 | — | — |
| `argocd.mealbong.cloud` | 🟠 주황 · 터널 | 🔴 **미결** | 없음 | — | **§0 ㉠** |
| `*.mealbong.cloud` | ⚪ 회색 · `.15` | 🔴 **미결**(존치 추정) | 없음 | — | **§0 ㉡** |

### 2.3 🟢 **안 만드는 것** — 내부 도구 6종의 AWS 레코드

**C-85** 가 *"내부 접근 = 로드밸런서 0개 · `kubectl port-forward` · $0 · LB 불요 · **도메인 불요**"* 로 확정했다.
⇒ AWS 쪽에 `grafana.` 류 레코드를 **만들 이유가 없다.** 온프렘 와일드카드는 온프렘 도구용으로 그대로 둔다.

---

## §3 TTL 준비

### 3.1 🔴 주황이면 TTL 은 우리 것이 아니다

실측상 **주황·회색이 모두 300** 으로 나오지만 **의미가 다르다**:

```
app.mealbong.cloud    (주황)  ttl 필드=1(auto)  → 응답 TTL 300   ← CF 가 자기 엣지 IP 를 서빙. 우리 값이 아님
*.mealbong.cloud      (회색)  ttl 필드=1(auto)  → 응답 TTL 300   ← 우리 몫. auto 의 기본값이 300
```

정본 2326행이 이것을 *"회색이면 TTL 이 **우리 몫**이다(주황일 땐 CF 가 관리했다)"* 로 적고 있고, 실측과 맞는다.

### 3.2 🔴 그래서 `app` 은 **"사전 인하"가 성립하지 않는다**

정본 `1-54`·`2-9` 는 *"TTL 을 60초 수준으로 낮춰둘 것"* 이라고 하는데, `app` 에 대해서는 **컷오버 전에 낮출 수 없다.**
지금 주황이라 TTL 필드가 우리 통제 밖이기 때문이다(㉤ 이 이 판단의 유일한 미검증 전제다 — 300 미만으로
설정 가능한지는 **PATCH 를 시도해야** 알 수 있고, 그건 이 세션의 읽기 전용 원칙 밖이다).

**그러면 컷오버 창은 어떻게 되나.** 주황 → 회색 전환 시, 기존 리졸버는 CF 애니캐스트 IP 를 최대 300초 캐시하고 있다.
회색으로 내리는 순간 CF 엣지는 그 호스트를 더 이상 프록시하지 않으므로 **캐시가 만료될 때까지 그 경로는 실패**한다.

```
전환 시점 ──────────────────── +300s
   │  새 리졸버: 즉시 ALB 로 간다 🟢
   │  구 캐시 보유 리졸버: CF 엣지로 간다 → 그 호스트는 이제 프록시 대상이 아님 🔴
   └─ 이 300초가 C-78 의 "다운타임 5~10분" 의 실체다
```

🟢 **전환 시점에 TTL 60 을 함께 넣는 것은 여전히 해야 한다** — 단 그 이득은 **컷오버가 아니라 롤백**에 온다.
회색이 된 뒤에는 TTL 이 우리 몫이므로, 60 이면 **롤백 노출 창이 300 → 60초**로 줄어든다.
컷오버가 실패했을 때 되돌리는 속도가 실제 사고 크기를 정한다는 점에서 이쪽이 더 중요하다.

### 3.3 무엇을 · 언제 · 얼마로

| 시점 | 대상 | 값 | 왜 |
|---|---|---|---|
| **A2** `aws.` 생성 시 | `aws.mealbong.cloud` | **TTL 60** 으로 **처음부터** | 회색이라 처음부터 우리 몫이다. 검증 중 대상을 바꿀 일이 잦다 |
| **A3** 컷오버 **그 순간** | `app.mealbong.cloud` | 회색 + ALB + **TTL 60** 을 **한 번의 편집으로** | 사전 인하가 불가하므로 전환과 동시에 넣는다. 이득은 롤백 속도(§3.2) |
| **A4** 안정화 확인 후 | `app.mealbong.cloud` | **TTL 300~3600 으로 복원** | 60 을 방치하면 상시 질의량만 늘고 얻는 게 없다. 🔴 **되돌리는 것까지가 절차다** |
| 컷오버 **불요** | `ci.` `gitlab.` `argocd.` `*` | **손대지 않는다** | 주황 3건은 TTL 이 무의미하고, 와일드카드는 이관 대상이 아니다 |

🔴 **A4 의 TTL 복원은 잊기 쉬운 항목이다.** 컷오버가 성공하면 아무도 DNS 를 다시 안 보기 때문이다.
`1-54` 에 이 복원 단계가 없으므로 체크리스트 보강 대상으로 남긴다.

---

## §4 자격증명·권한

### 4.1 토큰은 어디에 있나

```
K8s Secret  mp-cloudflare-api-token      key = api-token
  네임스페이스 2곳: mp-ingress · observability
  🟢 같은 토큰이다 (data sha256 동일 — 값을 출력하지 않고 해시로 비교)
  용도 = cert-manager DNS-01 챌린지 (LE 와일드카드·공개 인증서)
```

🔴 **Terraform·Ansible 에는 DNS API 토큰이 없다.** Ansible `secrets.yml` 이 가진 Cloudflare 비밀은
**터널 자격증명 2종**(`cloudflared_tunnel_credentials`·`argocd_webhook_tunnel_credentials`)뿐이고,
이것으로는 DNS 레코드를 읽거나 쓸 수 없다. ⇒ **DNS 를 조작할 수 있는 유일한 자격증명이 클러스터 안에 있다.**
이는 `1-56`(*"Cloudflare DNS 가 IaC 밖 — `cloudflare_record` 0건"*)과 같은 부채의 다른 얼굴이다.

### 4.2 권한 — 확인된 것과 확인 못 한 것

| 권한 | 상태 | 근거 |
|---|---|---|
| 토큰 유효성 | ✅ `active` | `/user/tokens/verify` → *"This API Token is valid and active"* |
| **Zone:Read** | ✅ **보유** | `/zones?name=mealbong.cloud` 성공(zone_id·plan·NS 반환) |
| **DNS 레코드 읽기** | ✅ **보유** | `/zones/<id>/dns_records` 성공(5건 반환) |
| **DNS:Edit** | 🟡 **보유 추정** | cert-manager 가 DNS-01 로 `_acme-challenge` TXT 를 **생성·삭제**하며 실제로 발급이 성공한다(§1.3). 다만 쓰기를 시도하지 않았으므로 **직접 실증은 아니다** |
| 토큰 정책 상세 | ❌ **조회 불가** | `/user/tokens/<id>` 는 `User:API Tokens:Read` 가 필요한데 이 토큰엔 없을 것으로 보인다. **범위를 정확히 알려면 CF 대시보드에서 사람이 봐야 한다** |

🔴 **취급 규칙 (2026-08-03 시크릿 노출 사고의 교훈)**
- **값을 출력하지 않는다.** `kubectl get secret -o jsonpath` 로 화면에 찍지 말고, §1.5 처럼 **셸 변수로 받아 curl 에 바로 넘긴다.**
- 키 목록이 필요하면 `describe` 또는 `go-template` 으로 **키 이름만** 본다.
- 이 문서·PR·커밋에 **토큰 값을 넣지 않는다.** 이 레포는 **공개**다.

### 4.3 🔴 Zero Trust(Cloudflare Access)는 **미채택** — 전제로 쓰지 말 것

국내 카드 결제 문제로 Zero Trust 가 막혀 있다. 그래서 **GitLab 이 Access 대신 "경로 제한 ingress"** 로 갔고
(OIDC 2경로만 200 · 루트 404), **C-84 대시보드도 CF Access 를 기각**하고 오리진 `oauth2-proxy` + Google 로 갔다.

🔴 **그런데 정본 서술 2건이 Access 를 현행처럼 쓴다**(§0 ⓑ):
- C-84 — *"팀의 운영자 신원은 이미 Google 이다(**현행 CF Access 구글 SSO**)"*
- 정본 2331행 — *"존·DNS 권한·`ci.mealbong.cloud` 터널·**내부 도구 Access** 는 전부 그대로"*

**실측이 이 서술을 반증한다.** 내부 도구 6종은 **회색 와일드카드 → `192.168.0.15`(사설 LAN)** 이다.
회색이면 트래픽이 **CF 엣지를 지나지 않으므로 CF Access 가 적용될 여지 자체가 없다.**
지금 내부 도구를 지키는 것은 Access 가 아니라 **"사설 주소라 인터넷에서 라우팅되지 않는다"** 는 사실 하나다.
⇒ 별건 정정 PR 대상. 이 문서는 **Access 를 전제한 설계를 쓰지 않는다.**

---

## §5 컷오버 절차 · 롤백

> 🔴 **아직 실행하지 않는다.** ALB 가 0개라 `app` 을 가리킬 대상이 없다.
> 아래는 대상이 생겼을 때 **그대로 밟을 수 있게** 적어 둔 절차다.

### 5.1 🔴 0단계 — 스냅샷 (모든 것에 선행한다)

```bash
# 존 전체를 파일로 떠 둔다. 롤백은 여기서 값을 읽는다 — 사람이 UUID 를 외우거나 타이핑하지 않는다.
ssh ubuntu@192.168.0.17 'bash -s' <<'EOF' > cf-dns-before-cutover.json
T=$(sudo kubectl -n observability get secret mp-cloudflare-api-token -o jsonpath="{.data['api-token']}" | base64 -d)
Z=$(curl -s -H "Authorization: Bearer $T" "https://api.cloudflare.com/client/v4/zones?name=mealbong.cloud" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"][0]["id"])')
curl -s -H "Authorization: Bearer $T" "https://api.cloudflare.com/client/v4/zones/$Z/dns_records?per_page=200"
EOF
```
🔴 이 파일은 **커밋하지 않는다**(존 구조가 담긴다). 컷오버 창 동안 작업자 로컬에만 둔다.

### 5.2 A2 — `aws.mealbong.cloud` 로 내부 검증

전제 = ALB 존재 · ACM 발급 완료(`1-48`).

1. **만들기 전** 응답을 기록한다 — 지금은 와일드카드 때문에 `192.168.0.15` 가 나온다(§1.4).
2. `aws.mealbong.cloud` = **회색** · ALB DNS 이름으로 CNAME · **TTL 60**.
3. **만든 후** 응답이 ALB 로 바뀌었는지 확인한다.
   ```bash
   curl -s -H 'accept: application/dns-json' \
     "https://cloudflare-dns.com/dns-query?name=aws.mealbong.cloud&type=A"
   ```
   🔴 **여전히 `192.168.0.15` 면 레코드가 안 만들어진 것이다** — 와일드카드가 계속 답하고 있다는 뜻이고,
   이때 증상은 `NXDOMAIN` 이 아니라 **연결 타임아웃**이라 원인을 오해하기 쉽다.
4. 🟢 **온프렘은 무영향** — `app` 은 손대지 않았다.

### 5.3 A3 — 컷오버 (다운타임 5~10분)

선행 = **AWS WAF 가 먼저 서 있어야 한다**(`1-49`). 🔴 회색으로 내리는 순간 그 호스트에 걸린
**CF WAF·DDoS·캐시·레이트리밋이 전부 무효**가 되는데, **대시보드에는 룰이 남아 있어 켜져 있는 것처럼 보인다**(`1-54`).

```
① 온프렘 쓰기 중단
② pg_dump → S3 → pg_restore  ·  ES 재파생  ·  Redis 빈 채로 시작
③ AWS 스모크 테스트 (aws.mealbong.cloud 로)
④ 🔴 DNS 전환 — app.mealbong.cloud 를 한 번의 편집으로:
       proxied: true → false   (주황 → 회색)
       content : <uuid>.cfargotunnel.com → <ALB DNS 이름>
       ttl     : 1(auto)       → 60
⑤ 검증 — §5.5
```

### 5.4 🔴 롤백 = **레코드 1개** — `app.mealbong.cloud`

정본 C-78 의 *"롤백 = 레코드 1개"* 가 가리키는 그 하나를 이름으로 특정하면:

```
대상    app.mealbong.cloud   (오직 이것 하나. 다른 4건은 컷오버에서 건드리지 않는다)

되돌릴 값  proxied : false → true          (회색 → 주황)
          type    : CNAME (변화 없음)
          content : <ALB DNS 이름> → 4c7d83d9-….cfargotunnel.com   ← §5.1 스냅샷에서 읽는다
          ttl     : 60 → 1(auto)

노출 창    최대 60초 (컷오버 때 TTL 60 을 넣어둔 덕분 — §3.2)
```

🟢 **이 되돌리기는 Cloudflare 안에서만 일어난다** — AWS 계정이 잠기거나 과금 사고가 나도 가능하다.
C-4(DNS=Cloudflare 유지)의 원래 목적이 이것이다.

🔴 **롤백이 성립하려면 온프렘이 살아 있어야 한다.** C-72(온프렘 동결)·C-70(축소는 A4 이후)이 그 전제를 지킨다.
**A6 를 A4 완료 없이 하면 이 롤백 경로가 사라진다.**

### 5.5 전환 검증 (`1-55`)

- 응답이 ALB 로 바뀌었는가 (§5.2 3번과 같은 명령, 이름만 `app`)
- 정상 접속 · **AWS WAF 로그에 요청이 실제로 찍히는가**(룰이 붙어만 있고 안 타는 경우를 잡는다)
- 레이트룰 동작 · ALB 접근로그 적재
- 🔴 `numTrustedProxies` — 프록시 사슬이 **CF+오리진 → ALB 1홉**으로 바뀐다. 틀리면 레이트리밋·감사로그가 **조용히** 오작동한다(`1-53`)

---

## §6 관련 체크리스트 항목 색인

이 문서는 아래 항목들의 **DNS 쪽 단면**이다. 작업 자체는 정본에서 관리한다.

| 항목 | 내용 |
|---|---|
| `1-41` | 레이트리밋 — Cloudflare 엣지 → **AWS WAF 레이트룰**로 대상 교체 (C-60) |
| `1-48` | ACM 인증서 발급 + **Cloudflare 에 DNS 검증 CNAME 등록** (C-60) |
| `1-52` | DR 리허설에 **"CF WAF 경로"** 포함 — DR 에서는 앱이 CF WAF 뒤에 놓인다(평시는 AWS WAF) |
| `1-53` | `numTrustedProxies` 재조정 + 클라이언트 IP 실측 |
| `1-54` | 🔴 **DNS 전환** — `app` 을 ALB 로 + 주황 → 회색 |
| `1-55` | 전환 실증 |
| `1-56` | 🔴 **Cloudflare DNS 를 IaC 로 편입** — `cloudflare_record` 0건. 최소선 = DR 런북에 레코드 단위 명시(**이 문서 §5.4 가 그 최소선을 채운다**) |
| `1-58` | cert-manager 는 AWS 에서도 남는다 — DNS-01 + `mp-cloudflare-api-token` 이라 **파드가 Cloudflare API 로 egress** 해야 한다(그 egress 는 지금 어느 netpol 목록에도 없다) |
| `1-59` | 🔴 와일드카드 DNS-01 이 **양 사이트에서 동시에** 돌면 `_acme-challenge` 가 경합 (§0 ㉣) |
| `2-9` | DNS TTL 사전 인하 — 🔴 `app` 에는 성립하지 않는다(§3.2) |

---

## 변경 이력

| 날짜 | 내용 |
|---|---|
| 2026-08-14 | 신설. 존 전량 실측(5건) · 목표 형상 · TTL 절차 · 롤백 대상 특정. **적용 0건**(읽기 전용). 신규 발견 = 와일드카드 A레코드 그림자(§1.4) · CF Access 미적용 실증(§4.3) |
