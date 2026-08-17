# 카나리 배포 캡처 가이드 (CI/CD → 카나리)

> **목표**: 카나리 배포(점진 트래픽 전환)를 **캡처 4장**으로. 시작 → 20% → 50% → 100%.
> **대상**: Rollout `mp-recipe` (ns `app`, 컨테이너 `recipe`, 이미지 `192.168.0.10/mealplanning/mp-recipe-service`).
> **핵심 = `get rollout` 헤더**: `Step` · `SetWeight` · `ActualWeight` + `Images (stable)/(canary)` 가 한눈에 보임. 이게 캡처 소스.
> ✅ analysis 하드닝돼 있어 **무트래픽도 통과** → curl·트래픽 준비 불필요. `promote` 로 단계 넘기며 원하는 순간에 캡처.

---

## 0. 실측 스텝
```
setWeight 20% → pause/analysis → setWeight 50% → pause/analysis → setWeight 100%
```
각 단계에서 멈춰 있으니 캡처 시간 넉넉. `promote` 로 즉시 다음 단계로 넘길 수 있음.

---

## 1. 준비 (촬영 전 한 번)
```bash
kubectl argo rollouts version                                  # 플러그인 OK 확인
kubectl argo rollouts get rollout mp-recipe -n app             # 현재 = Stable 100% Healthy 인지
kubectl argo rollouts get rollout mp-recipe -n app -o jsonpath='{..image}{"\n"}'   # 현재 태그 확인
```
`set image` 로 트리거하려면 **현재와 다른 :sha** 가 하나 필요. 모르면 이전 revision 이미지에서 고른다:
```bash
kubectl get rs -n app --sort-by=.metadata.creationTimestamp \
  -o custom-columns=RS:.metadata.name,IMAGE:'.spec.template.spec.containers[*].image' | grep recipe
```

---

## 2. 캡처 순서 — 위에서 아래로 딱딱 치기

```bash
# ── 📸 ① 시작: Stable 100% · Healthy ──────────────────────────
kubectl argo rollouts get rollout mp-recipe -n app
#   보이는 것: Status ✔ Healthy / stable RS 100% / canary 없음

# ── 트리거: 새 이미지로 카나리 시작 ───────────────────────────
kubectl argo rollouts set image mp-recipe -n app \
  recipe=192.168.0.10/mealplanning/mp-recipe-service:<다른-sha>

# ── 📸 ② 카나리 20% ──────────────────────────────────────────
kubectl argo rollouts get rollout mp-recipe -n app
#   보이는 것: Status ॥ Paused / Step 1/x / SetWeight 20 ActualWeight 20
#              Images: :old (stable) + :new (canary) / canary Pod 1개 / AnalysisRun

kubectl argo rollouts promote mp-recipe -n app                 # 다음 단계로

# ── 📸 ③ 카나리 50% ──────────────────────────────────────────
kubectl argo rollouts get rollout mp-recipe -n app
#   보이는 것: SetWeight 50 ActualWeight 50 / canary Pod 늘어남

kubectl argo rollouts promote mp-recipe -n app                 # 마지막 단계로

# ── 📸 ④ 완료: 100% · Healthy ────────────────────────────────
kubectl argo rollouts get rollout mp-recipe -n app
#   보이는 것: ✔ Healthy / 새 버전이 stable 100% / 구 ReplicaSet ScaledDown
```

> `promote` 없이 기다려도 자동 진행됨(analysis count 때문에 단계당 ~1분+). 빨리 캡처하려면 `promote` 로 넘긴다.

---

## 3. (선택) 추가 증거 캡처 — HTTPRoute weight 숫자
트래픽 비율이 실제로 20→50→100 으로 바뀌는 걸 숫자로 보여주고 싶으면, ②③④ 각 단계에서:
```bash
RT=$(kubectl get httproute -n app -o name | grep -i recipe | head -1)
kubectl get $RT -n app -o jsonpath='{.spec.rules[0].backendRefs[*].weight}{"\n"}'
#   → 20  →(promote)→ 50  →(promote)→ 100
```

---

## 4. (선택) 트리거를 실제 CI/CD 로 — 앞단까지 캡처
`set image` 대신 실제 파이프라인을 태우고, 각 단계 캡처를 카나리(§2 ②③④)에 이어 붙임:
```bash
# recipe 코드 한 줄 수정 → push → Jenkins 빌드·Trivy·Harbor push → config 레포 :sha 커밋
git commit -am "demo(recipe): 카나리 시연" && git push
```
- 📸 Jenkins 빌드 초록 (Multibranch, main)
- 📸 config 레포 커밋 (`newTag: <sha>` diff)
- 📸 ArgoCD `mp-recipe` = Synced / Healthy
- → 그 뒤 ArgoCD 가 감지 → 카나리 시작 → §2 ②③④ 이어서 캡처

---

## 5. 제어 / 원복
```bash
kubectl argo rollouts promote mp-recipe -n app        # 다음 단계로
kubectl argo rollouts promote mp-recipe -n app --full # 남은 단계 전부 스킵 → 즉시 100%
kubectl argo rollouts abort   mp-recipe -n app        # 이전 버전으로 롤백
kubectl argo rollouts undo    mp-recipe -n app        # 직전 revision 으로 되돌림
```

---

## 6. 캡처 체크리스트
- [ ] 📸 ① 시작 — Stable 100% Healthy
- [ ] 📸 ② 20% — Paused · SetWeight 20 · canary Pod · AnalysisRun
- [ ] 📸 ③ 50% — SetWeight 50
- [ ] 📸 ④ 완료 — Healthy · 새 버전 stable 100% · 구 RS ScaledDown
- [ ] (선택) HTTPRoute weight 20/50/100 숫자
- [ ] (선택) CI/CD 앞단 3장 (Jenkins·config커밋·ArgoCD Synced)

## 슬라이드 배치 (권장)
`①시작 → [트리거] → ②20% → ③50% → ④100%` 가로로 4~5칸. 자막:
"안정 100% → 새 버전 20%·자동 분석 → 50% → 100% 무중단 완료 — **표준 K8s, EKS 가도 그대로**."

---
정본: 배포전략 = `docs/mp_k8s_infra_object_spec.md §9` · Rollout/AnalysisTemplate = `mealplanning-config platform/rollouts/` · 발표 노트 = `docs/mp_k8s_presentation_bongsu.md §8`.
