# ADR-0001: 배포전략 — 핵심 서비스 카나리 (Argo Rollouts)

- **상태**: 제안(Proposed) — 팀 합의 대기
- **날짜**: 2026-08-02
- **결정자**: 인프라(팀장 제안) → 팀 합의 대상
- **관련 문서**: [`mp_k6_부하테스트.md §7`](../mp_k6_부하테스트.md) (배포전략 비교·예산 근거) · [`mp_k6_stage3_peak_viral.md`](../mp_k6_stage3_peak_viral.md) (recipebook HPA 반증) · config 레포 `mealplanning-config`

> 이 문서는 우리 레포의 **첫 ADR**이다. 이후 설계 결정은 `docs/adr/NNNN-<slug>.md` 로 이어 기록한다. 지금까지의 인프라 결정·근거는 ADR 이전이라 [`mp_k8s_infra_migration_plan.md`](../mp_k8s_infra_migration_plan.md) 에 인라인으로 남아 있다.

---

## 1. 맥락 (Context)

부하테스트(Stage1~3, 2026-08-01~02)가 완료되며 **HPA·리소스 설정이 라이브가 되고 예산 baseline이 실측으로 확정**됐다(config PR #81·#82). 그 결과 "새 이미지 버전을 클러스터에 어떻게 전환하느냐"(= 배포전략)를 *감이 아니라 숫자로* 고를 수 있는 상태가 됐다.

현재 배포는 전 서비스가 **K8s Deployment 기본 롤링업데이트**(ArgoCD sync, `maxSurge 25%`)다. 즉:
- 새 `:sha` 가 config 레포에 들어오면 ArgoCD 가 sync → 새 버전 pod 를 25% 더 띄우고 준비되면 옛 pod 교체.
- **점진 전개·배포 중 메트릭 자동분석·자동롤백이 전무.** 나쁜 버전이 준비 즉시 100% 유저에게 노출되고, 롤백은 수동(ArgoCD 이전 sync)이다.

이 프로젝트는 **AI 해커톤 + 인프라 캡스톤 겸용**이라, 배포전략의 *발표가치*도 정당한 결정 동인에 포함된다.

## 2. 결정 동인 (Decision Drivers)

- 실측 용량 제약 (§3) — 특히 메모리가 바인딩.
- 배포 안전망(배포 중 자동 롤백) 유무.
- 도입·운영 비용.
- **이미 라이브인 선행조건(Istio, Prometheus)의 활용도** — 카나리의 두 하드 의존성이 이미 있다.
- 캡스톤 발표가치.
- DAU 500 규모 적합성(과잉설계 회피).

## 3. 측정된 제약 (부하테스트 §7)

| 자원 | 정상 상태 | 최악(HPA max) | 천장 |
|---|---|---|---|
| app 쿼터 CPU | 3.08 / 6 코어 | 4.7 / 6 | 6 (self-imposed) |
| app 쿼터 MEM | 4.0Gi (66%) | **5.2Gi (84%)** | 6Gi |
| 노드 | 5노드(master + 워커 4×6CPU) | 워커 CPU 43~49% | CPU 여유 ~13.7코어 / **MEM 워커 63~82%(빡빡)** |

- **CPU는 여유**(클러스터 ~13.7코어 남음) → surge 감당 가능.
- **메모리가 진짜 병목**(워커 RAM 63~82%) → **2벌 동시 기동 불가.** ← 여기서 블루그린이 죽는다.
- **HPA 대상은 account·recipe 둘뿐**으로 확정. recipebook 은 Stage3 통제 scale-test 에서 HPA 반증됨(병목이 pod CPU 아닌 다운스트림 PG enrich) → "3번째 HPA가 6코어 쿼터를 먹는다"는 우려 소멸 → **카나리 surge 예산이 덜 빡빡**.

## 4. 검토한 옵션 (Considered Options)

| 축 | **A. 롤링(현행)** | **B. 카나리(Argo Rollouts)** | **C. 블루그린** |
|---|---|---|---|
| 도입비용 | **0**(라이브) | Rollouts + Deploy→Rollout 전환 + AnalysisTemplate | Rollouts + 전환 |
| 점진/게이트 | ❌ 새버전 즉시 100% | ✅ 10→50→100%·메트릭 자동분석·자동롤백 | ⚠️ 스위치 원샷 |
| 쿼터 CPU | +25% → ~3.9 ✓ | +부분 surge → ~3.9~5.5 ✓(타이트) | **2× → 6.16 초과 ✗** |
| 메모리 | 여유 | 관리가능 | **2배 불가**(워커 RAM 부족) |
| Istio 궁합 | — | ✅ 트래픽분할 네이티브(이미 있음) | ○ |
| 롤백 | 수동(ArgoCD 이전 sync) | 자동(분석 실패 시) | 즉시 스위치백 |
| 캡스톤 가치 | 낮음 | 높음(프로그레시브 딜리버리) | 중 |

## 5. 결정 (Decision)

**B — 카나리(Argo Rollouts). 단 전면이 아니라 blast-radius 큰 `account`·`recipe` 2개만 카나리로 전환하고, 나머지 7개 서비스는 롤링을 유지한다.**

### 근거
1. **캡스톤 정통 쇼케이스이면서 한계비용이 비정상적으로 낮다.** 카나리의 두 하드 의존성(Istio 트래픽분할 + Prometheus 자동분석)이 우리 클러스터에 **이미 라이브**다. 보통 카나리 도입이 무거운 건 이 둘을 깔아야 해서인데 우리는 그게 공짜다. 남는 일은 Deployment→Rollout 전환 + AnalysisTemplate 작성뿐.
2. **부하테스트가 account·recipe 를 유일한 진짜 병목으로 실증**했다(account = 로그인 bcrypt·모든 서비스가 의존 / recipe = 메인 브라우징 경로). 딱 그 둘만 카나리하면 비용·예산 최소로 최대 가치.
3. **전면 카나리는 오버**다 — DAU 500 규모에서 나머지 7개는 롤링으로 충분하고, 9개 전부 Rollout 전환·유지하는 비용이 정당화되지 않는다.
4. **C(블루그린)는 실측 메모리 제약으로 배제**(§7). 하려면 노드 RAM 증설 선행 필요(별건).

> A(롤링 유지)도 정당한 선택이었다 — DAU 500 엔 기능적으로 충분하고 운영 단순성 이점이 있다. B 로 기운 이유는 **배포 자동 안전망 + 캡스톤 발표가치 + 선행조건이 공짜**의 조합이며, 이는 팀 가치판단(발표가치 ↔ 운영단순성)이라 숫자로만 안 떨어진다. 그래서 상태를 "제안"으로 두고 팀 합의를 받는다.

## 6. 구현 방침 (별도 실행 — config 레포)

### 6.1 트래픽 라우팅 = Gateway API 플러그인

우리 north-south 라우팅은 **Gateway API(HTTPRoute)** 다(`gatewayClassName: istio`, Gateway `mp-gw-public` @ `.14`, `mp-account-route`·`mp-recipe-route`). Istio VirtualService 가 아니다.

- Argo Rollouts 는 Gateway API 가중치를 네이티브로 못 나눈다 → **`argoproj-labs/gatewayAPI` 트래픽라우터 플러그인** 필요.
- 🔴 **왜 플러그인인가(replica-based 카나리 아님)**: 플러그인 없이도 replica 비례 카나리가 되지만 그건 트래픽%가 pod 수에 묶인다. 대상 account·recipe **둘 다 HPA** 라 replica 가 부하 따라 움직이면 카나리%가 오염된다. **트래픽라우터는 카나리 가중치를 HPA replica 수와 분리**해준다 → HPA'd 서비스엔 플러그인이 정답. 즉 플러그인은 회피 대상이 아니라 크리티컬 패스.
- `weight` 는 Gateway API **표준채널(v1)** 이고 우리 HTTPRoute 가 이미 `gateway.networking.k8s.io/v1` 이라 experimental 채널 불요.

### 6.2 🔴 플러그인 바이너리 = vendoring(`file://`), egress 허용 아님

플러그인 `location` 은 `https://`(기동 시 다운로드)와 `file://`(로컬 바이너리) 둘 다 지원한다. **우리는 `file://` vendoring 을 택한다.**

**근거(SPOF 재구성)**: 컨트롤러는 플러그인이 없으면 **기동하지 않는다**(공식 문서). `https://` 면 HA 각 pod 가 재기동마다(노드 드레인·페일오버·OOM·차트 업그레이드) GitHub 에서 재다운로드한다 → GitHub blip/rate-limit 시 **배포를 게이팅하는 컨트롤러가 안 뜬다 = 장애 중 픽스를 배포하려는 바로 그 순간 배포 게이트가 죽는다.** 컨트롤 플레인이 취해선 안 될 공중망 런타임 의존이다.

vendoring 은 그 의존을 **이미 모든 배포의 하드 의존인 Harbor 로 옮긴다**(모든 이미지가 Harbor 에서 pull). **새 실패 도메인 0개**, egress 구멍 0개, 버전핀+sha256, 우리가 이미 돌리는 Jenkins→Harbor 경로 그대로.

**모양**:
```
tiny image:  FROM busybox
             COPY gatewayapi-plugin-linux-amd64 /plugin/
  → Jenkins 빌드(빌드타임에만 GitHub 릴리스 1회 fetch, 런타임 hermetic)
  → Harbor: mealplanning/mp-rollouts-gatewayapi-plugin:vX.Y.Z (:latest 금지)
Helm(argo-rollouts):
  controller.initContainers  →  이 이미지가 emptyDir 로 바이너리 복사
  controller.volumes/Mounts  →  emptyDir 를 /plugins 에 마운트
  argo-rollouts-config CM    →  location: file:///plugins/gatewayapi  + sha256
  → 업스트림 컨트롤러 이미지는 미변경(Helm 차트 업그레이드 그대로 유효)
```

### 6.3 RBAC

argo-rollouts ClusterRole 에 `gateway.networking.k8s.io` **httproutes** `get/list/update/patch` 추가(차트 기본엔 Gateway API RBAC 없음). ClusterRole 이라 app ns 의 HTTPRoute 편집 가능.

### 6.4 Rollout 변환 (account·recipe 각각)

- `kind: Deployment` → `kind: Rollout`(argoproj.io/v1alpha1). template·topologySpreadConstraints·Istio 사이드카 그대로 + `spec.strategy.canary`.
- `canary`: `stableService`(기존 Service 재사용) + `canaryService`(신규 `<svc>-canary`) + `trafficRouting.plugins.argoproj-labs/gatewayAPI`(HTTPRoute 참조) + `steps`(setWeight 10 → pause{analysis} → 50 → pause{analysis} → 100).
- **HPA 재타겟**: `scaleTargetRef` → `kind: Rollout`(Rollouts 는 HPA 지원, min2/max4 그대로).
- **HTTPRoute**: 해당 rule 의 `backendRefs` 를 stable + canary 2개로(weight 100/0). 플러그인이 이 가중치를 굴린다.
- **PDB**: `app:<svc>` 라벨 셀렉트 → Rollout pod 도 이 라벨 → 그대로 유효.
- **ArgoCD `ignoreDifferences`**: Rollouts 가 HTTPRoute 가중치·Rollout status 를 라이브로 바꾸므로 그 필드에 ignoreDifferences 미설정 시 배포 중 OutOfSync(표준 패턴). ArgoCD 앱은 이미 `selfHeal:false·prune:false` 라 revert 위험은 없음.

### 6.5 AnalysisTemplate

kube-prometheus-stack + Istio 사이드카 텔레메트리(`istio_requests_total`·`istio_request_duration_*`) 를 질의:
- 5xx 비율 `< 0.05` + p95 `< 2000ms` (부하테스트 abortOnFail 임계값과 정렬).
- 분석 실패 → **자동 abort + 롤백**.

### 6.6 예산 체크 (§7)

카나리 surge = 카나리 pod. setWeight 10·min2 → **+1 pod**. account(request 500m) + recipe(300m) 동시라도 +0.8 코어. HPA 최악(4.7) + surge = **5.5/6 CPU — 감당**. 메모리는 타이트하나 account/recipe pod 는 작아 OK. → §7 "타이트하나 감당" 그대로.

### 6.7 시퀀싱 — recipe 파일럿 먼저

account 는 auth 관문(전부가 의존)이라 blast radius 최대 + AnalysisTemplate 오설정 시 좋은 배포를 오롤백할 위험. 그래서:
1. **recipe 로 파일럿** — 브라우징 경로(위험 낮음)·이미 HPA 실증됨. Rollouts + GatewayAPI 플러그인 + Analysis 기계 전체를 여기서 검증.
2. 검증되면 **account 로 확대** — 같은 패턴 복붙 + 임계값 조정.
3. (선택) 검증 후 §4 Stage2(딜 골든아워 경합)로 배포 중 경합까지 확인.

## 7. 결과 (Consequences)

**긍정**
- 배포 중 회귀가 10~50% 트래픽·짧은 노출에서 메트릭으로 잡히고 자동 롤백된다(account = 전 서비스 의존이라 특히 값짐).
- 프로그레시브 딜리버리 = 인프라 캡스톤 발표 자산.
- 이미 있는 Istio·Prometheus 재사용 → 신규 인프라 최소.

**부정 / 비용**
- Argo Rollouts 컨트롤러 + Gateway API 플러그인(vendored image) + AnalysisTemplate 신규 유지 대상.
- 운영 복잡도 상승(Rollout 상태·분석 실패 대응 학습).
- 카나리 surge 가 HPA max 와 6코어 쿼터를 놓고 경쟁(타이트하나 감당 범위 실측).
- tiny plugin 이미지 = Jenkins/Harbor 유지 대상 1건 추가(플러그인·Rollouts 업그레이드 시 재빌드, 드묾).

**중립**
- 나머지 7개 서비스는 롤링 유지 → 배포 경로가 2종(Rollout·Deployment)으로 갈림. 의도된 범위 한정.

## 8. 거부한 대안 상세

- **C 블루그린**: 5노드지만 메모리가 바인딩(워커 63~82%, 쿼터 84% 최악) → 2벌 동시 RAM 부족. 노드 RAM 증설 선행 시 재검토 가능(별건).
- **전면 카나리(9개 전부)**: DAU 500 엔 오버. 전환·유지 비용 대비 이득 없음.
- **egress-allow 플러그인(`https://`)**: §6.2 SPOF 논리로 거부 — 배포 게이트에 공중망 런타임 의존 신설.
- **replica-based 카나리(플러그인 없이)**: §6.1 — HPA'd 서비스에서 카나리%가 replica 수에 오염됨.

## 9. 참조

- 부하테스트 정본 [`mp_k6_부하테스트.md`](../mp_k6_부하테스트.md) §7 (예산·비교표)
- [`mp_k6_stage3_peak_viral.md`](../mp_k6_stage3_peak_viral.md) 부록 A (recipebook HPA 반증)
- [Argo Rollouts — Traffic router plugins](https://argo-rollouts.readthedocs.io/en/stable/features/traffic-management/plugins/) (`file://` vs `https://`, sha256, HA 재다운로드)
- [Argo Rollouts Gateway API plugin](https://rollouts-plugin-trafficrouter-gatewayapi.readthedocs.io/en/latest/) (설치·RBAC)
- config 레포: `gateway/gateway.yaml`, `gateway/httproutes.yaml`, `services/{account,recipe}/base/`, `platform/argocd/`
