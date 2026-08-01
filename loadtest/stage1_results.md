# k6 부하테스트 — Stage1 결과 로그 (진행 중)

> 기록 시작 2026-08-01. 세션 결과 누적. 정본 설계=`docs/mp_k6_부하테스트.md`, 방법론=memory `mp-k6-loadtest-hpa-framework`.
> ⚠️ **초안 결과 로그(정본 아님).** Stage1 다 끝나면 4분류·HPA 결정표를 정본 문서에 반영.

## 실행 환경
- 생성기: 이 PC = **Win10 → WSL2 mirrored 불가**. **Windows `k6.exe`(v2.1.0)를 WSL interop으로 실행** → Windows 네트워크(`.177`)로 Gateway `.14` 직타.
  `cp loadtest/<x>.js /mnt/c/temp/ && /mnt/c/temp/k6.exe run 'C:\temp\<x>.js'`
- 타깃: `.14` + k6 `hosts`로 SNI/Host=`app.mealbong.cloud` (CF 터널 우회) + `insecureSkipTLSVerify`.
- 관측 게이트: `kubectl.exe`(interop) + `~/mp-kubeconfigs/junghyun.kubeconfig`(observability) → `.17` API. 부하 중 6~8초 간격 hpa/top 샘플링.
- 안전: 모든 런 `abortOnFail`(오류율·p95) + 유한·점진 램프 + off-peak.

## 방법 (2-스테이지)
- **Stage1** = 서비스별 포화 스윕 → knee(→target)·peak replica(→max)·4분류.
- **Stage2** = 딜 골든아워 경합(유저×파이프라인, Δp95).

---

## 결과

### 하네스 셰이크아웃 — hotdeals (검증용)
2250 req · 100% · p95 **6.5ms**(캐시) · abortOnFail 정상. **하네스+게이트 검증 완료.**

### account (로그인) — ✅ Stage1 완료
스크립트: `stage1_account_login.js`(램프) · `stage1_account_knee.js`(knee). 유저풀 50 = `loadtest-pool-0001..0050`.

| 유입 | p95 | replicas | 비고 |
|---|---|---|---|
| 35 logins/s | **231ms** | 3→4 (t+72s 스케일) | 깨끗이 흡수 |
| 90 logins/s(램프) | **5.3s** | 4 (max, util 1532%) | 붕괴 → abortOnFail 중단, dropped 481 |

- **knee ≈ 50 logins/s** (안전 지속 ~35~40/s).
- **병목 = HPA max=4 상한.** pod는 ~4.9 core까지 버스트(throttle 아님) — 4 pod 병렬로 부족.
- **0% 에러**(느려질 뿐 실패·크래시 없음). 복원력 양호.
- **CPU request 과소**(~250m 추정) → util% 무의미(1532%). request 상향 필요.
- 구 P0(단일 VM 붕괴)가 **HPA로 해소**됨을 실증 → 정본 문서 한계 #7 해소.

**account HPA 결정(초안)**: 분류=**HPA-CPU** / **max=4가 ~50/s 상한** / target 70% 반응 OK / 손볼것 = **request 상향** + max↑는 6Gi quota 트레이드오프 + 로그인 **rate-limit** 병행.

### 동시 N명 혼합 저니 (recipe검색 + hotdeals + budget, think 1~3s) — ✅
스크립트: `stage1_journey.js`. VU = 동시접속 유저. 로그인 1회 후 반복 브라우징.

| 동시 | req/s | 성공 | recipe p95 | hotdeals p95 | budget p95 | login p95 | 병목 |
|---|---|---|---|---|---|---|---|
| **500** | 606 | 99.99% | 73ms | 36ms | 20ms | 272ms | 없음(여유) |
| **1000** | 738 | 99.99% | **2.7s** | 71ms | 21ms | 291ms | **recipe(ES)** |
| **2000** | (abort t+28s) | 100% | 457ms* | 192ms | **4.0s** | **4.2s** | **account 로그인버스트** |

\* 2000은 램프 초반(673 VU) abort라 recipe 미포화.

- **500명**: 전부 여유. account 로그인 버스트로 2→4 스케일 후 ~0.3core/pod 안정.
- **1000명**: **recipe 검색이 첫 병목** — `mp-recipe` 단일 pod ~1.2core plateau(HPA 없음), p95 2.7s. 나머지 멀쩡.
- **2000명**: 병목이 **account로 뒤집힘** — 2000명이 30초 램프에 몰려 로그인(≈66/s > 50/s knee) → account 포화(util 680%/4replica) → login·budget p95 4s+ → recipe 로드 전에 abort.

### 🔑 핵심: 천장은 "유입 패턴"에 달림
| 유입 패턴 | 병목 | 천장 |
|---|---|---|
| 정상 브라우징(점진) | **recipe 검색**(ES 단일 pod) | ~700~800 동시 |
| 로그인 몰림(fan-out) | **account bcrypt**(HPA max=4) | ~50 logins/s ≈ 30초에 ~1500명 |

→ 멘토의 fan-out(알림→동시 로그인) 시나리오 프리뷰. **둘 다 잡아야**: account max↑/로그인 rate-limit + recipe HPA/replica. **단 DAU 500엔 둘 다 무관(과잉 여유).**

### mealplan (HPA-무용) — ✅
스크립트: `stage1_mealplan_propagation.js` (account 로그인 압박 + cart 동시).

| account 압박 | cart p95 | mealplan pod CPU | account pod CPU |
|---|---|---|---|
| 로그인 40/s | 24ms | 133m (바닥) | ~2.2 core/pod |
| 로그인 58/s | **157ms** | 145m (바닥) | ~3.5 core/pod |

- **mealplan CPU는 부하와 무관하게 바닥(133~145m)** = thin proxy(자체 연산 없음).
- **cart 지연은 account 부하를 추종**: 24→157ms. cart = account budget 대기.
- → **HPA-무용 확정**: mealplan replica/HPA 늘려도 무의미. 처방 = account 보호 + cart의 budget 호출에 **timeout/캐시/서킷브레이커**.

### 🔬 recipe scale 검증 (1→4 replica, 1000명 동일 조건) — ✅ 가설 확정
`kubectl scale deploy/mp-recipe --replicas=4`(taehyun admin) 후 `stage1_journey.js` VUS=1000·NUSERS=50 재실행. **recipe replica만 바꾼 통제 대조**(control = 위 1000명 런).

| 지표 | 1 pod (대조) | **4 pod (실험)** | 판정 |
|---|---|---|---|
| **recipe_search p95** | **2.7s** | **45.6ms** | **59× ↓ — 병목 소멸** |
| recipe pod CPU | 단일 pod ~1.2core plateau | 4 pod 각 **380~525m 균등**(합 ~1.9core) | 완전 분산 |
| 성공률 | 99.99% | 99.94% | 유지(붕괴 없음) |

- ✅ **가설1 확정**: recipe 용량 늘리면 브라우징 천장 급상승. 단일 pod CPU가 유일 병목이었음.
- ✅ **가설2 확정(ES/PG 2차병목 아님)**: recipe 쿼리가 46ms로 떨어짐 = 뒤단 ES 여유. 스케일로 안 풀리는 문제였다면 여기서 안 떨어졌을 것.
- 🔑 **병목 이동 → account 로그인**: recipe 치우니 다음 병목 노출 — **login p95 291ms→3.22s**(1000명 30초 램프 로그인 몰림 → account HPA max=4 포화). = **"account 로그인 rate-limit / max↑"가 진짜 남은 레버**임을 실증.
- ⚠️ hotdeals max 32.7s·58건(0.05%) 실패 = 버스트 순간 게이트웨이/커넥션 일시 튐. p95 736ms로 통과.
- **정리**: recipe→1 원복·ArgoCD Synced 복귀·시드 유저 51개 삭제 완료. **auto-sync(selfHeal:false)라 수동 scale이 revert 안 됨**(첫 시도의 즉시 revert는 겹친 sync 사이클 일회성).
- ✅ **정식 반영 = mealplanning-config PR #81**(`feat/mp-recipe-hpa`, **머지 완료**·main `bbf73ad`): hpa.yaml(ContainerResource·min2/max4·target70%) + pdb.yaml(minAvailable1) + deployment(replicas 제거·request 100→300m). account 패턴. ArgoCD 자동 sync → Synced/Healthy, recipe 상시 ≥2.

### ✅ 재검증 (HPA 라이브, 1000명 동일 조건) — 루프 닫힘
머지 후 ArgoCD 자동 반영된 HPA로 재실행. **자동 HPA가 수동 scale과 동일 결과를 냄을 실증.**

| 지표 | 1 pod (원래) | 수동 scale=4 | **HPA 라이브** |
|---|---|---|---|
| **recipe_search p95** | 2.7s | 45.6ms | **72.0ms** ✓ |
| login p95 | 291ms | 3.22s | **1.55s** ✓ |
| 성공률 | 99.99% | 99.94% | 99.91% |
| k6 exit | — | 99(login 초과) | **0(전부 통과)** |

- **HPA 동작 실증**: 초기 min 2 pod가 ~900m 포화 → HPA 즉시 **2→4 확장** → 4 pod ~400~530m 균등(수동 scale 판박이).
- login도 1.55s 통과(account warm) — recipe 병목 제거로 1000 동시가 편안. 부하 종료 후 HPA 300s창 뒤 4→2 자연 축소.
- ⚠️ hotdeals max 38.7s·92건(0.08%) 재현 = 버스트 순간 스파이크(price 후속 관찰). p95 979ms로 통과.

---

## HPA 4분류 (✅ Stage1 완료)
| 서비스 | 분류 | knee / peak | 근거 |
|---|---|---|---|
| **account** | **HPA-CPU** | ~50 logins/s · max=4 상한 | 로그인 램프·knee |
| **recipe(검색)** | **HPA-CPU 확정** | ~700 동시서 saturate·4 pod서 46ms | 단일 pod 1.2core plateau·p95 2.7s@1000 → **4 pod서 45.6ms(실증)** |
| **price** | **고정** | 1000 동시서 0.7core 여유 | 캐시로 CPU 낮음 |
| **mealplan** | **HPA-무용** | CPU 바닥(145m)·account 종속 | cart 24→157ms(account추종) |

### HPA 결정 요약 (초안)
- **account**: CPU request 상향(util% 정상화) + max=4 상한 인지(fan-out엔 max↑/rate-limit).
- **recipe**: **HPA-CPU 신규 확정**(scale 1→4 실증: p95 2.7s→46ms). request 100→300m + HPA min2/max4·target70%. ES 최적화는 불요(46ms).
- **price**: HPA 불필요, min 고정.
- **mealplan**: HPA ❌ → account 보호 + budget 호출 timeout/캐시.
- 공통: 이 모든 튜닝은 **피크(fan-out) 대비**. **DAU 500엔 현 구성으로 과잉 여유.**

---

## Stage2 — 딜 골든아워 경합 (유저 × 파이프라인)

### A. matview refresh × price 부하 — ✅ (격리 확인)
유저축 = `stage2_price_load.js`(price 200/s, hotdeals+recommend). 파이프라인축 = matview refresh 3회 주입(taehyun admin, `kubectl create job --from=cronjob/mp-poller-price-matview`).

| | recommend p95 | hotdeals p95 | max | pg-1 CPU |
|---|---|---|---|---|
| 대조(refresh 없음) | 19.6ms | 7.6ms | 422ms | ~640m |
| 실험(refresh ×3) | 26.2ms | 7.9ms | 586ms | 640→**851m**(refresh 순간) |

- **Δp95 ≈ +6ms** (recommend +33% 상대, 절대는 무시 수준·SLO 한참 아래) → **matview refresh 경합 잘 격리됨(H1 PASS)**.
- 이유: `REFRESH MATERIALIZED VIEW CONCURRENTLY`(읽기 non-block) + 캐시 빠른 재생성 → 우려한 **스탬피드 미미**.
- pg-1 refresh 순간 640→851m(여유), pg-2(replica)·pooler 안정. 0 에러.
- ⚠️ 이 결론은 **price 200/s 규모** 한정. 더 높은 부하 / 딜 write 경합은 B에서.
- 참고: 잡 생성 시 PodSecurity **warn**(runAsNonRoot) — pipeline ns=enforce baseline이라 admit됨(refresh 정상 실행, pg-1 스파이크로 확인).

### B. 합성 TEST- 딜 → Kafka → KEDA 컨슈머 — ⏳

---

## 리소스·HPA 결정 (실측 근거)

### 현재 상태 (실측)
| 서비스 | req cpu | limit cpu | 부하 시 실측 CPU | 판정 |
|---|---|---|---|---|
| account | 250m | **없음** | 1.4~4.9 core/pod | req **6~20배 과소** → util% 무의미(1532%) |
| recipe | 100m | 없음 | ~1.2 core (단일 pod) | HPA 없음·단일 replica → ~700 동시서 병목 |
| price | 100m | 없음 | 0.5~0.7 core | req 과소(무해, 캐시로 안정) |
| mealplan | 100m | 없음 | ~145m | 적정(thin proxy) |

- app ResourceQuota: **requests.cpu 2080m/6** (여유 ~3.9 core), requests.memory 4160Mi/6Gi.
- ⚠️ **CPU limit 전무** → 버스트 무제한(account 4.9 core 관측). requests+PriorityClass로 스케줄 공정성은 유지되나 노이즈-네이버 여지.

### 권장 → 반영 상태 (쿼터 6코어 내)
| 서비스 | req cpu | limit cpu | HPA | 반영 |
|---|---|---|---|---|
| **account** | 250→**500m** | 없음 유지 | 2/4·target 70% 유지 | **✅ PR #82 머지·라이브** |
| **recipe** | 100→**300m** | 없음 | **신규 2/4·target 70%** | **✅ PR #81 머지·라이브 재검증됨** |
| **price** | 100→**300m** | 없음 | 없음(고정) | **✅ PR #82 머지·라이브** |
| **mealplan** | 100→**150m** | 없음 | 없음(HPA-무용) | **✅ PR #82 머지·라이브** |

- 반영 완료: recipe = PR #81(머지·라이브·재검증). account·price·mealplan = **PR #82**(머지·라이브, main `2aa9e69`). cpu limit 은 계속 없음(버스트 CFS 스로틀 회피).
- 라이브 확인(2026-08-01): account 500m·price 300m·mealplan 150m 반영·롤링 완료·3앱 Synced/Healthy. 정상상태 쿼터 requests.cpu 3080m/6·mem 4032Mi/6(66%).
- **쿼터 실측(2026-08-01)**: bump 후 최악(account·recipe 둘 다 max 4) requests.cpu ≈ **4.7/6 core**(여유 ~1.3). ⚠️ **requests.memory 5184/6144Mi(84%)** = CPU보다 메모리가 먼저 조이는 구조(별건 주목).
- **account 후속**: fan-out(로그인 몰림)은 max↑/쿼터가 아니라 **로그인 rate-limit**(코드)이 정답 — 재검증서 login 병목 재확인.

- **쿼터 체크**: 상향 후 requests.cpu ≈ account 2.0(4×500m) + recipe 1.2(4×300m) + price·mealplan·기타 → **6코어 근접**. max를 더 올리려면 **쿼터/노드 확장 필요**(= HPA·배포전략 공용 예산).
- **CPU limit 방침**: bcrypt(account)는 tight limit이 CFS throttle로 지연 악화 → **limit 없음 or 넉넉(2~3×req)** 권장. requests로 스케줄, PriorityClass로 축출 순서.
- **DAU 500 관점**: 예상 피크 동시 수십 명 → 현 구성으로도 충분. 위 상향은 **fan-out/피크 대비 여유**용.

---

## 🧹 테스트 데이터 정리 — ✅ 완료
- 테스트 유저 51개(`loadtest-smoke` id 64 + `loadtest-pool-0001..0050`) **삭제 완료**(2026-08-01, `cleanup_users.js`, 검증: 재로그인 401).
- Stage2A matview 잡·파드: 정리 완료. Stage2B(합성 딜): 미실행(스킵) → retail TEST- write 없음.
