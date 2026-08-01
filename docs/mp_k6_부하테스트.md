# mp k6 부하테스트 — 진행·결과·적용 (정본)

> **문서 상태**: 정본. Stage1(서비스별 포화 스윕)·Stage2A(matview 경합)·적용(HPA/리소스 라이브) **완료(2026-08-01)**. 배포전략(§7)·Stage2B(§4.6)는 **미확정**.
> **상세 런 로그**(스크립트별·런별 원수치) = [`loadtest/stage1_results.md`](../loadtest/stage1_results.md) · 스크립트 = [`loadtest/`](../loadtest/).
> **계보**: 구 정본 [`mp_k8s_loadtest_design.md`](mp_k8s_loadtest_design.md)(nGrinder · **K8s 이전 단일 VM `.9`**, 2026-07-19~21)가 스스로 남긴 **한계 #7 = "K8s 수평 확장 효과 미측정"** 을 메꾸는 후속. 도구 nGrinder→**k6**, 대상 VM→**K8s(Gateway `.14`)**.
> **핵심 관점**: 부하테스트 = *검증*이 아니라 **HPA·리소스 설정값을 실측으로 산출하는 도구**.
> **후속**: [`mp_k6_stage3_peak_viral.md`](mp_k6_stage3_peak_viral.md) — Stage3(피크 몰림 × 바이럴 핫키). §3.7 이 "경계(미검증)"로 남긴 **recipebook·pantry·notify** 실측 + §8.2 의 **유저 피크 도착률** 산출(DAU 500 → λ 0.4 세션/s)을 그쪽에서 다룬다.

---

## 1. 실행 환경

### 1.1 부하 생성기 — Windows `k6.exe`를 WSL interop으로
- 🔴 **클러스터 노드·호스트 C(`.10`)·하이퍼바이저에 부하 생성기를 두지 않는다.** 생성기가 SUT의 CPU를 뺏으면 결과 오염 — 이 클러스터는 CPU 바운드라 특히 치명적.
- 이 개발 PC = **Windows 10**(19045) → WSL2 **mirrored networking 불가**(Win11 22H2+ 전용). WSL2는 NAT라 `.14`·클러스터 LAN에 **직접 못 닿음.**
- ✅ **해법 = Windows용 `k6.exe`를 WSL interop으로 실행.** exe가 Windows 프로세스로 돌아 Windows 네트워크(`.177`)에서 Gateway VIP `.14`에 직접 닿는다. WSL 셸에서 그대로 구동:
  `cp loadtest/<x>.js /mnt/c/temp/ && /mnt/c/temp/k6.exe run 'C:\temp\<x>.js'`

### 1.2 타깃 라우팅
- **Gateway VIP `.14` 직타** + k6 `hosts`로 SNI/Host=`app.mealbong.cloud` 오버라이드 + `insecureSkipTLSVerify`.
- 🔴 **Cloudflare 터널 우회**: `app.mealbong.cloud`(공인)로 때리면 cloudflared 파드 1개 + CF 무료티어가 병목이 된다. LAN에서 `.14` 직접 호출로 그 변수를 제거.

### 1.3 관측 게이트
- WSL은 클러스터 API(`.17`)도 못 닿음 → kubectl도 **interop(`kubectl.exe`)** 로 구동.
- 팀별 kubeconfig(`~/mp-kubeconfigs/`): observability(junghyun)로 읽기, 관리 작업(scale·job)은 admin(taehyun).
- 부하 중 6~12초 간격으로 `hpa`/`top pods` 샘플링 — 포화·스케일·분산을 실시간 확인.

### 1.4 안전장치 (공유·라이브 클러스터 필수)
- 모든 런에 **`abortOnFail` 임계값**(오류율·p95) → 유저 SLO를 깨기 전 자동 중단.
- **유한·점진 램프** + **off-peak**(피크 17-18시 회피).
- **LLM 경로 제외**(OCR·chat·video = Bedrock/Vertex/Gemini **실과금**).
- 합성 데이터는 `TEST-` 접두(정리 가능) — 단 Stage2B 미실행이라 실제 `TEST-` write는 없음(§4.6).

---

## 2. 방법 — 2-스테이지

부하테스트를 **HPA 산출 도구**로 격상한 프로그램.

- **Stage1 — 서비스별 포화 스윕**: 각 서비스를 단독으로 `ramping-arrival-rate`/`ramping-vus`로 밀어 **knee(→HPA target%)·peak replica(→max)·병목 원인**을 뽑고 **4분류**(HPA-CPU / 고정 / HPA-무용 / KEDA)한다.
- **Stage2 — 딜 골든아워 경합**(§4): 정한 설정을 넣고 **유저 × 파이프라인 간섭**을 대조 실험(Δp95)으로 검증.

**HPA 5질문** (각 서비스에 적용): ①필요?(부하 시 포화하나) ②메트릭(CPU vs 다운스트림 대기 vs Kafka lag) ③target(지연 knee 아래) ④min/max(**max는 app 6코어/6Gi Quota 상한**) ⑤behavior(유입속도 vs HPA 반응속도 gap).

---

## 3. Stage1 — 서비스별 포화 스윕 (→ HPA 4분류)

### 3.1 하네스 셰이크아웃 (검증용)
캐시된 저위험 read(`hotdeals`)로 하네스·게이트 검증: 2250 req · 100% · **p95 6.5ms**(캐시) · abortOnFail 정상. → 하네스 신뢰 확보.

### 3.2 account (로그인) — HPA-CPU
스크립트 `stage1_account_login.js`(램프)·`stage1_account_knee.js`. 유저풀 50(`loadtest-pool-0001..0050`).

| 유입 | login p95 | replicas | 비고 |
|---|---|---|---|
| 35 logins/s | **231ms** | 3→4 (t+72s 스케일) | 깨끗이 흡수 |
| 90 logins/s(램프) | **5.3s** | 4 (max, util 1532%) | 붕괴 → abortOnFail 중단, dropped 481 |

- **knee ≈ 50 logins/s** (안전 지속 ~35~40/s). **병목 = HPA max=4 상한** — pod가 ~4.9 core까지 버스트(throttle 아님)해도 4 pod 병렬로 부족.
- **0% 에러**(느려질 뿐 실패·크래시 없음) → 복원력 양호. 구 정본의 P0(단일 VM 붕괴)가 **HPA로 해소**됨을 실증.
- request 250m 기준 **util% 1532%**(무의미) → request 상향 필요(§5.2).

### 3.3 동시 N명 혼합 저니 — 브라우징 천장
스크립트 `stage1_journey.js`(closed / `ramping-vus`). VU = 동시접속 유저 1명: 로그인 1회 → [레시피검색 + 핫딜 + 예산조회] 반복 + think-time 1~3s.

| 동시 | req/s | 성공 | recipe p95 | hotdeals p95 | budget p95 | login p95 | 병목 |
|---|---|---|---|---|---|---|---|
| **500** | 606 | 99.99% | 73ms | 36ms | 20ms | 272ms | 없음(여유) |
| **1000** | 738 | 99.99% | **2.7s** | 71ms | 21ms | 291ms | **recipe(ES 단일 pod)** |
| **2000** | (abort) | 100% | 457ms* | 192ms | **4.0s** | **4.2s** | **account 로그인 버스트** |

\* 2000은 램프 초반(673 VU) abort라 recipe 미포화.

### 3.4 🔑 동시 천장은 "유입 패턴"이 좌우
| 유입 패턴 | 병목 | 천장 |
|---|---|---|
| 정상 브라우징(점진) | **recipe 검색**(ES 단일 pod) | ~700~800 동시 |
| 로그인 몰림(fan-out) | **account bcrypt**(HPA max=4) | ~50 logins/s ≈ 30초에 ~1500명 |

→ 멘토의 fan-out(알림→동시 로그인) 시나리오 프리뷰. **둘 다 잡아야** 한다: account(로그인 rate-limit) + recipe(HPA). ⚠️ 단 **DAU 500엔 둘 다 과잉 여유**(피크 동시 수십 명).

### 3.5 mealplan — HPA-무용
스크립트 `stage1_mealplan_propagation.js`(account 로그인 압박 + cart 동시).

| account 압박 | cart p95 | mealplan pod CPU | account pod CPU |
|---|---|---|---|
| 로그인 40/s | 24ms | 133m (바닥) | ~2.2 core/pod |
| 로그인 58/s | **157ms** | 145m (바닥) | ~3.5 core/pod |

- mealplan CPU는 부하와 무관하게 **바닥(133~145m)** = thin proxy(자체 연산 없음). **cart 지연은 account 부하를 추종**(24→157ms) = cart가 account budget 응답 대기.
- → **HPA-무용 확정**: mealplan replica/HPA 늘려도 무의미. 처방 = account 보호 + budget 호출에 **timeout/캐시/서킷브레이커**(앱 레벨).

### 3.6 🔬 recipe scale 검증 (1→4 통제 대조)
`kubectl scale deploy/mp-recipe --replicas=4`(admin) 후 저니 VUS=1000 재실행 — **recipe replica만 바꾼 통제 대조**(control = §3.3의 1000명).

| 지표 | 1 pod (대조) | **4 pod (실험)** | 판정 |
|---|---|---|---|
| **recipe_search p95** | **2.7s** | **45.6ms** | **59× ↓ — 병목 소멸** |
| recipe pod CPU | 단일 pod ~1.2core plateau | 4 pod 각 **380~525m 균등**(합 ~1.9core) | 완전 분산 |
| 성공률 | 99.99% | 99.94% | 유지(붕괴 없음) |

- ✅ **가설1**: recipe 용량 늘리면 브라우징 천장 급상승 — 단일 pod CPU가 유일 병목이었음.
- ✅ **가설2(ES/PG 2차병목 아님)**: recipe 쿼리가 46ms로 떨어짐 = 뒤단 ES 여유. 스케일로 안 풀리는 문제였다면 여기서 안 떨어졌을 것.
- 🔑 **병목 이동**: recipe 치우니 다음 병목이 **account 로그인**으로 노출(login p95 291ms→3.22s). = §5의 "account rate-limit이 진짜 남은 레버"를 실증.

### 3.7 HPA 4분류 (Stage1 종합)
| 서비스 | 분류 | knee / peak | 근거 |
|---|---|---|---|
| **account** | **HPA-CPU** | ~50 logins/s · max=4 상한 | 로그인 램프·bcrypt CPU 포화 |
| **recipe(검색)** | **HPA-CPU (신규)** | ~700 동시서 saturate·4 pod서 46~72ms | 단일 pod 1.2core plateau·p95 2.7s@1000 → 4 pod 실증 |
| **price** | **고정** | 1000 동시서 0.7core 여유 | 캐시로 CPU 낮음 |
| **mealplan** | **HPA-무용** | CPU 바닥(145m)·account 종속 | cart 24→157ms(account 추종) |

*경계(미검증, 추정)*: recipebook·pantry·notify = HPA-CPU 경계 / chat = HPA-무용(account 전파 + ILIKE 미인덱스) / 딜·retail 컨슈머 = **KEDA(lag)**.

---

## 4. Stage2 — 딜 골든아워 경합 (간섭 실험)

### 4.1 왜 이 시나리오인가
17-24시엔 세 부하가 **한 시간대에 겹친다**: *딜이 싸지는 시간 = 크롤이 도는 시간 = 유저가 몰리는 시간.*
- **파이프라인**: 크롤 → Kafka 딜 이벤트 → KEDA 컨슈머 scale-up + `refresh_price_matview` 캐시 flush + recipe ingest(PGSync→ES)
- **유저**: 알림 fan-out → account HPA scale-up + hotdeals/예산 read 폭증
- **공유 substrate**: 같은 CPU · 같은 PG(A primary) · 같은 ES · 같은 1GbE

순수 HTTP 부하가 아니라 **간섭 실험** — 핵심 측정 = *유저 단독(대조)* 대비 *유저+파이프라인(실험)*의 **Δp95**. 격리 장치(PriorityClass·KEDA·HPA·Pooler·Quota)가 유저 응답을 지켜내는지 본다.

### 4.2 가설
| # | 가설 | 깨지면 의미 |
|---|---|---|
| **H1** 격리 | 겹침 중에도 유저 p95가 SLO 안(**Δp95 < 20%**) | `pipeline-low`·Quota가 유저를 못 지킴 |
| **H2** KEDA | 딜 lag가 주입 후 **≤60s 내 0 복귀**·컨슈머 scale-up | scale-to-zero 콜드스타트가 딜 골든타임에 못 따라감 |
| **H3** Pooler | PG waiting 커넥션 ≈ 0(write+refresh+read 동시) | P3 증거(12/100)가 write 부하에서 무너짐 |
| **H4** 신선도 | 새 레시피가 PGSync로 N초 내 검색 노출 | CDC lag → stale 검색 |
| **H5** 회복 | 파이프라인 멈추면 유저 p95 **≤60s 내** 복귀 | 경합이 시스템을 stuck으로 |

### 4.3 부하 2축
**축 A · 유저** (k6, **open 모델 `ramping-arrival-rate`** — fan-out은 서버가 느려져도 초당 N명 유입되므로 closed-VU가 붕괴를 숨기는 걸 방지): 딜 임펄스 + 딜-브라우징 고원 믹스.
**축 B · 파이프라인** (합성 `TEST-` 주입): 딜 이벤트 Kafka produce(레이트 R) + matview refresh 주기 트리거 + 바운드 recipe ingest. *실제 외부 크롤 대신 합성 이벤트로 실제 컨슈머 코드 경로를 태워* KEDA·PG·ES CPU를 진짜로 유발.

### 4.4 타임라인 (대조 → 겹침)
```
   P1 대조군          P2 겹침(★핵심)        P4 회복
   유저 단독 15~20m   유저+파이프 20~30m     파이프 stop, 유저 유지
유저 ──╱▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔╲──
파이프 ────────────▁▂▃▅▇▇▇▇▇▇▅▃▁──────
       [p95_control]  [p95_treatment]   → Δp95 = treatment − control
```

### 4.5 A. matview refresh × price 부하 — ✅ 격리 확인 (H1 PASS)
유저축 = `stage2_price_load.js`(price 200/s, hotdeals+recommend). 파이프라인축 = matview refresh 3회 주입(admin, `kubectl create job --from=cronjob/mp-poller-price-matview`).

| | recommend p95 | hotdeals p95 | pg-1 CPU |
|---|---|---|---|
| 대조(refresh 없음) | 19.6ms | 7.6ms | ~640m |
| 실험(refresh ×3) | 26.2ms | 7.9ms | 640→**851m**(refresh 순간) |

- **Δp95 ≈ +6ms** (절대는 무시 수준·SLO 한참 아래) → **matview refresh 경합 잘 격리됨(H1 PASS)**.
- 이유: `REFRESH MATERIALIZED VIEW CONCURRENTLY`(읽기 non-block) + 캐시 빠른 재생성 → 우려한 **스탬피드 미미**. pg-2(replica)·pooler 안정, 0 에러.
- ⚠️ 이 결론은 **price 200/s 규모** 한정. 더 높은 부하 / 딜 write 경합은 B에서 봐야 함.

### 4.6 B. 합성 딜 → KEDA 컨슈머 콜드스타트 — ⏸ 스킵
`produce_test_deals.py`로 `TEST-` 딜을 Kafka `retail.deal.raw`에 발행 → KEDA lag → 딜 컨슈머 콜드스타트(H2·H5) 측정 예정이었으나 **미실행(사용자 결정)**. 파드 안에서의 코드 주입 경로가 프로덕션 안전장치에 막혀, 1차 마무리에선 제외. §4 시나리오·스크립트는 유효 — 입력값(§8.2) 확정 시 실행.

### 4.7 관측·판정
- **★ 주 결과 = 엔드포인트별 Δp95**(control vs treatment). SLO(구 정본 §11): 단순조회 p95<500ms · 검색/집계<1s · login<1s · chat<2s · 공통 오류율<1%.
- 오토스케일러 타임라인(HPA replica ↔ KEDA replica ↔ 노드 CPU) · Pooler active/waiting(H3) · 노드별 CPU(A=PG primary 포화? pipeline-low evict?) · 캐시 hit율(flush 스탬피드) · ES 지연·PGSync lag(H4) · Kafka lag·컨슈머 scale 지연(H2) · 1GbE NIC.

---

## 5. 적용 (config 레포 `mealplanning-config` = ArgoCD 정본)

### 5.1 recipe HPA·PDB — PR #81 (머지·라이브·재검증 ✅)
- `hpa.yaml`: **ContainerResource**(container: recipe, 사이드카 노이즈 배제) · cpu **70%** · **min 2 / max 4**
- `pdb.yaml`: minAvailable 1 (상시 ≥2 → drain 중 검색 무중단)
- `deployment`: `replicas` 필드 제거(HPA 소유) · cpu request **100→300m**
- **머지 후 재검증**(HPA 라이브, 1000명): 초기 min2 pod가 ~900m 포화 → HPA **즉시 2→4** → 4 pod 균등, **recipe_search p95 72ms · login 1.55s · k6 exit 0(전부 통과)**. = 자동 HPA가 수동 scale과 동일 결과를 냄을 실증.

### 5.2 리소스 request 튜닝 — PR #82 (머지·라이브 ✅)
| 서비스 | request | 근거 |
|---|---|---|
| account | 250→**500m** | 로그인시 pod당 ~400~900m(bcrypt)·util% 1532%→0~100%+로 판독 (hpa 코멘트 175→350m) |
| price | 100→**300m** | Stage2서 0.5~0.7 core·과소예약(오버커밋) 해소 |
| mealplan | 100→**150m** | thin proxy ~145m 바닥 |
- **cpu limit은 계속 없음** — 버스트(account bcrypt·recipe 검색)에 CFS 스로틀이 지연을 악화(object_spec §13.7).

### 5.3 쿼터 예산 (실측)
- app ResourceQuota = **6 core / 6Gi**(requests). 정상상태 **3.08 core / 4.0Gi(66%)**.
- **최악**(account·recipe 둘 다 HPA max 4): requests.cpu ≈ **4.7/6 core**. requests.memory ≈ **5.2/6Gi(84%)**.
- ⚠️ **CPU보다 메모리가 먼저 조이는 구조** — 단 84%는 "양쪽 HPA 동시 풀가동" 국면의 최악값이고 정상상태는 66%.

---

## 6. 근거·교훈 (핵심 발견)
1. **부하테스트 = 설정값 산출 도구.** "일단 전부 HPA"가 아니라 **실측 포화 근거가 있는 서비스만**(account·recipe) HPA. price=고정, mealplan=HPA-무용을 숫자로 갈랐다.
2. **병목은 하나씩 드러난다.** recipe(단일 pod CPU) 해소 → 다음 병목이 account 로그인으로 이동. 스케일이 안 통하는 병목(다운스트림 대기=mealplan)과 통하는 병목(pod CPU=recipe)을 구분해야 함.
3. **천장은 절대 수가 아니라 유입 패턴 함수.** 브라우징 ~700 vs 로그인몰림 ~1500/30s — "동접 N명"만으론 용량을 못 정한다.
4. **HPA는 배포전략의 선행조건.** HPA max headroom·블루그린 2배·카나리 surge가 **같은 6코어/6Gi 예산**을 다툰다(§7). 오토스케일 baseline이 안정돼야 카나리 자동분석이 성립.
5. **cpu limit 신중.** 버스트가 본질인 서비스에 tight limit = CFS 스로틀로 지연 악화. requests로 스케줄, limit은 메모리만.
6. **DAU 500 현실감.** 위 모든 튜닝은 fan-out/피크 대비 여유이지, 평시 용량 문제 해결이 아니다(평시 과잉 여유).

---

## 7. 배포전략 (⚠️ 미확정 — 비교·팀 합의 대기)

> **정한 게 아니다.** HPA/리소스가 라이브가 되어 **예산 baseline이 확정**됐으므로, 이제 선택할 수 있게 된 결정. 아래는 실측 제약에 근거한 비교이며 §6.4 원칙대로 **팀이 정한다.**

### 7.1 측정된 제약
| 자원 | 정상 | 최악(HPA max) | 천장 |
|---|---|---|---|
| app 쿼터 CPU | 3.08 / 6 | 4.7 / 6 | 6 (self-imposed) |
| app 쿼터 MEM | 4.0Gi (66%) | **5.2Gi (84%)** | 6Gi |
| 노드 | 5노드(master + 워커 4×6CPU) | 워커 CPU 43~49%만 사용 | **CPU 여유 ~13.7코어 / MEM 워커 63~82%(빡빡)** |

- **CD 현황**: 전 서비스 **ArgoCD 롤링업데이트(maxSurge 25%)**. **Argo Rollouts 미설치** → 점진배포·자동분석·자동롤백 전무.

### 7.2 3옵션 비교
| 축 | **A. 롤링(현행)** | **B. 카나리(Argo Rollouts)** | **C. 블루그린** |
|---|---|---|---|
| 도입비용 | **0**(라이브) | Rollouts + Deploy→Rollout 전환 + AnalysisTemplate | Rollouts + 전환 |
| 점진/게이트 | ❌ 새버전 즉시 100% | ✅ 10→50→100%·메트릭 자동분석·자동롤백 | ⚠️ 스위치 원샷 |
| 쿼터 CPU | +25% → ~3.9 ✓ | +부분 surge → ~3.9~5.5 ✓(타이트) | **2× → 6.16 초과 ✗** |
| 메모리 | 여유 | 관리가능 | **2배 불가**(워커 RAM 부족) |
| Istio 궁합 | — | ✅ 트래픽분할 네이티브(이미 있음) | ○ |
| 롤백 | 수동(ArgoCD 이전 sync) | 자동(분석 실패 시) | 즉시 스위치백 |
| 캡스톤 가치 | 낮음 | 높음(프로그레시브 딜리버리) | 중 |

### 7.3 결론 방향 (제안 — 결정 아님)
- **C 블루그린 = 사실상 배제.** 5노드지만 **메모리가 병목**(워커 63~82%, 쿼터 84% 최악) → 2벌 동시는 RAM 부족. 하려면 노드 RAM 증설 선행.
- 실질 선택 = **A 롤링 유지**(무료·단순, DAU 500엔 충분) vs **B 카나리**(도입비용 있으나 자동분석·자동롤백 + Istio 궁합 + 안정 baseline 확보 + 캡스톤 발표가치).
- 다음 스텝 = 팀 합의로 A/B 택 → 선택 시 §4 Stage2로 배포 중 경합까지 검증.

---

## 8. 후속 & 미확정 입력값

### 8.1 후속 (부하테스트 밖)
- **account 로그인 rate-limit** — fan-out 몰림 붕괴 방어. max↑/쿼터가 아니라 **앱 코드**(services/account)가 정답. 별도 트랙.
- **mealplan/chat** — budget 호출 timeout/서킷브레이커(HPA-무용 처방).

### 8.2 미확정 입력값 (Stage2 실행 전 확정 필요 — 임의 확정 금지)
| 입력 | 설명 | 기본값 제안 |
|---|---|---|
| 유저 피크 도착률 | 관심유저 × 오픈률 ÷ 압축창 | DAU 500 기준 산출(미정) |
| 딜 이벤트 레이트 R | 오아시스 딜/마감세일 규모 | 초기 50/s burst + 지속 10/s |
| matview refresh 간격 | 실제 일1~2회 → 압축 | 5~10분 |
| 겹침(P2) 지속 | | 20~30분 |

---

## 부록 A. 관련 인프라 사실 (SSOT: `mp_k8s_infra_object_spec.md` / `mp_k8s_infra_status.md`)
- **HPA = account + recipe**(2026-08-01) — 나머지 앱 서비스는 Quota 안에서 고정 replica.
- **KEDA scale-to-zero** — 컨슈머 3종 min 0(딜 컨슈머 콜드스타트 = H2 관건).
- **CNPG Pooler** 경유(PgBouncer transaction) — P3 실증 = account 4 replica서도 PG 12/100. recipe 4 pod 재검증서 0.05% 에러로 재확인.
- **PGSync = `public.recipe`만** — H4 신선도는 레시피 검색 한정(가격 신선도는 matview 경로로 별개).
- **PriorityClass** `pipeline-low`(1000) < `app-normal`(100000) < `data-critical`(1000000) — 압박 시 파이프라인 먼저 밀림.
- 배치 원칙 = PG·Redis primary는 A, master·quorum·Prometheus·MinIO는 B.

## 부록 B. 스크립트 목록 (`loadtest/`)
| 스크립트 | 용도 |
|---|---|
| `smoke.js` | 하네스 스모크(signup→login→me) |
| `seed_users.js` / `cleanup_users.js` | 테스트 유저 풀 시드/정리(멱등) |
| `stage1_hotdeals.js` | 하네스 셰이크아웃(캐시 read) |
| `stage1_account_login.js` / `stage1_account_knee.js` | account 로그인 램프·knee |
| `stage1_journey.js` | 동시 N명 혼합 저니(브라우징 천장) |
| `stage1_recipe_search.js` | recipe 검색 단독 |
| `stage1_mealplan_propagation.js` | mealplan HPA-무용(다운스트림 전파) |
| `stage2_price_load.js` | Stage2 유저축(price 캐시 read) |
| `produce_test_deals.py` | Stage2B 합성 딜 producer(미실행) |
| `stage3_peak_journey.js` | **Stage3-A** 점심·저녁 피크 몰림(1인가구 믹스 11 req/세션 · open 모델 · `-e MULT` 로 한계 탐색) |
| `stage3_viral_spike.js` | **Stage3-B** 바이럴 — 등록(진짜 write) → publish 노출 → 단일 `share_token` 핫키 read 폭증(순차 3단계) |
| `cleanup_test_recipes.js` | **Stage3** `TEST-` 유저 레시피 멱등 정리(계정 스코프 + 제목 접두 이중 셀렉터) |

*Stage3 스크립트 3종의 시나리오·가정·관측 절차 = [`mp_k6_stage3_peak_viral.md`](mp_k6_stage3_peak_viral.md).*
