# 인프라 튜닝 핸드오프 — 워커 · 커넥션 풀 · PG max_connections (부하테스트 후속 #186)

> 대상: 인프라/배포 담당 · 목적: 부하테스트 병목 중 **실서버 설정(compose·PG)** 부분을 협의·적용·재측정.
> 코드 개선(A1~A4·B1·B2)은 별도 PR로 반영됨. 이 문서는 **실서버 값 조정**만 다룬다.

## 0. 왜 "설정을 한 세트로" 조정해야 하나

부하테스트에서 **VM CPU 18%인데 ~200 VUser에서 포화**가 나온 건, 병목이 VM 자원이 아니라
**컨테이너·프로세스 단위 상한**이기 때문이다. 이 상한 3개(워커·풀·CPU)는 서로 얽혀 있어 따로
올리면 오히려 터진다 — 특히 **워커를 늘리면 커넥션이 곱으로 늘어** PG 한도를 넘는다.

```
제약식:  Σ_services (워커수 × 풀max) + 파이프라인 + exporter + 여유  ≤  PG max_connections
```

## 1. 현재 실측 (2026-07-19)

**fb-app-ai(앱 VM): 6 vCPU · 3.8 GiB RAM (가용 ~2.1 GiB) · 컨테이너 11개+**
(account·price·mealplan·chat·pantry·notify·recipe·recipebook·ocr·ranking-serving·ranking-retrain + frontend)

| 항목 | 현재 값 | 비고 |
|---|---|---|
| 컨테이너 CPU 리밋 | `cpus: 0.75` (앱 공통) | **0.75 × 11 ≈ 8.25 > 6 vCPU** — 이미 초과 배정(oversubscribed) |
| 컨테이너 메모리 리밋 | `mem_limit: 256m`(대부분) | 256m × 11 ≈ 2.8 GiB / 총 3.8 GiB — **RAM이 사실상 binding 제약** |
| uvicorn 워커 | **1** (전 서비스) | Dockerfile CMD에 `--workers` 없음 |
| 커넥션 풀 max | account/mealplan/pantry/recipe **10** · price/chat/notify/recipebook **5** | 합 = 60 |
| OTEL 샘플링 | `OTEL_TRACES_SAMPLER_ARG: 1.0` (100%) | 요청당 CPU 세금 |
| 파이프라인 상주 컨슈머 | ~5 커넥션 | consume_retail/deal/recipe/user_event |
| **PG 총 커넥션(피크)** | **≈ 68 / 100** | 헤드룸 얇음 |

**fb-data(PG VM): PostgreSQL `cpus: 1.0` · `memory: 1536M` · `max_connections` 미튜닝(기본 100)**
(tfstate_db/templates/compose.yml.j2)

## 2. 핵심 현실: 이 박스는 이미 꽉 차 있다

6 vCPU · 3.8 GiB 에 11개+ 컨테이너 → **워커·CPU 리밋을 크게 못 올린다.**
- **RAM이 1차 제약**: 워커 1개 추가 ≈ 프로세스 1개 추가(수십~백 MB). 여러 서비스에 워커를 늘리면 OOM.
- **CPU는 이미 초과 배정**: 0.75 리밋 합이 물리 6코어를 넘어, 동시 피크에서 컨테이너별 throttling 발생.

→ **1차 완화는 인프라가 아니라 코드 개선(별도 PR)이다.** 특히 **B1(가격 뷰 물질화)**가 가장 무거운
CPU 작업(윈도우+정규식 재계산)을 제거해 같은 박스가 더 버티게 한다. 아래 설정 튜닝은 **보조**다.

## 3. 권장 조정 (보조 — 코드 개선과 함께)

### 3-1. 커넥션 풀 ↑ (앱 쪽은 값싸다 — RAM/CPU 거의 안 씀. 단 PG 한도와 세트로)
코드에서 이미 **env(`PG_POOL_MAX`)로 튜닝 가능**하게 바꿔둠(기본값=현재값, 무변화). compose에서 값만 준다.

| 서비스 | 현재 | 권장 | 근거 |
|---|---:|---:|---|
| price | 5 | **12** | 부하테스트 1차 병목, 풀=5가 TPS 상한 |
| chat | 5 | **12** | 요청당 커넥션 3개 점유 → 풀=5면 유효동시성 1.6 |
| mealplan | 10 | **15** | 무거운 조인 + 커넥션 점유 김 |
| notify | 5 | **10** | 균형 |
| account/pantry/recipe | 10 | 10 | 유지 |
| recipebook | 5 | 5 | 유지 |

**합 = 12+12+15+10+10+10+10+5 = 84** + 파이프라인 ~5 + exporter ~3 = **≈ 92**.

### 3-2. PG `max_connections` ↑ (풀 올리면 필수)
- 위 조정이면 피크 ~92 → 기본 100의 헤드룸이 거의 없음. **`max_connections` 100 → 150** 권장.
- ⚠️ **PG 메모리 동반 확인**: 커넥션당 ~5~10MB → 150 커넥션 ≈ 0.75~1.5 GiB. PG 컨테이너가 `1536M`이라
  work_mem·shared_buffers 여유가 준다 → **PG `memory` 를 2~3 GiB로, `cpus` 1.0 → 1.5~2** 검토.
- 적용 위치: `infra/ansible/roles/tfstate_db/templates/compose.yml.j2` (command `-c max_connections=150` 등) + PG 재기동.

### 3-3. OTEL 샘플링 ↓ (CPU 제약 박스에서 효과 큼)
- 운영에서 `OTEL_TRACES_SAMPLER_ARG: 1.0 → 0.1`(10%). 요청당 스팬 생성·export CPU를 1/10로.
- 디버깅 필요 시 일시적으로 1.0 환원.

### 3-4. 워커 ↑ (신중 — RAM 제약)
- **전 서비스 일괄 증설 금지**(RAM 초과). 코드 개선 후 재측정에서 특정 서비스가 여전히 CPU-bound면,
  **가장 뜨거운 1~2개만 `--workers 2`** + 그만큼 **풀max를 절반으로 나눠**(워커×풀 유지) PG 한도 보존.
  예) price를 워커2로 → 풀max 12를 6으로(2×6=12 유지).
- account: bcrypt를 스레드로 오프로드(A1)했으니 **워커보다 `cpus` 소폭↑(0.75→1.0)**가 스레드에 유리.

## 4. CPU 리밋 (6 vCPU 안에서 재배분)

일괄 상향은 불가(합이 6 초과). **뜨거운 서비스↑ / 차가운 서비스↓**로 재배분하거나, 코드 개선으로
전체 CPU 수요를 낮춘 뒤 현행 유지. 예시(합 ≈ 6 목표, frontend·PG 제외):

| 서비스 | 현재 cpus | 예시 조정 |
|---|---:|---:|
| price · chat · mealplan | 0.75 | 1.0 |
| account · pantry · notify | 0.75 | 0.75 |
| recipe · recipebook · ocr | 0.75 | 0.5 |
| ranking-serving/retrain | (별도) | 피크 외 스케줄/제한 |

→ 정확한 값은 **재측정 기반**으로. 지금 숫자는 출발점.

## 5. 근본 한계 & 방향

**이 박스(6 vCPU·3.8 GiB)는 11개+ 서비스에 이미 빠듯하다.** 설정 튜닝은 여유를 조금 늘릴 뿐,
수직 확장 여지는 작다. **진짜 스케일 = 수평 확장(K8s 이전 계획, `docs/backup-strategy.md`)** —
앱을 두 노드에 분산해야 근본적으로 풀린다. 데이터 계층 PG는 여전히 단일이므로(SPOF) 별도 과제.

## 6. 적용 순서 (제안)

1. **코드 개선 PR 먼저 머지·배포** (A1~A4·B1·B2) → 재측정. 상당 부분 여기서 해소될 것.
2. B1 **물질화 뷰 마이그레이션**(데이터 담당): `python pipelines/ingest/migrate_price_matview.py` + 크롤 후
   `refresh_price_matview.py` 스케줄(폴 윈도우 뒤).
3. **풀max + PG max_connections + PG 메모리를 한 세트로** 조정(§3-1·3-2) → 재측정.
4. OTEL 샘플링 0.1 (§3-3).
5. 재측정에서 남는 CPU-bound 서비스만 워커/CPU 미세조정(§3-4·4).
6. 남는 포화는 K8s 수평 확장으로(§5).

## 7. 재측정 체크리스트 (개선 전후 동일 조건)

- TPS/RPS · P50·P95·P99 · 오류율·timeout 수
- 컨테이너 CPU throttling · PG pool 사용량·대기시간 · PG active connections vs max_connections
- 느린 요청 Tempo Trace · 종료 후 정상 회복 시간
- 대상 순서: **Price 단독 → Login·MealPlan·Chat → 동일 혼합 시나리오**
