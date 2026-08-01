# Operations AI 구축 현황 및 다음 작업

> 최종 갱신: 2026-07-31
>
> 이 문서는 AI 이상징후 탐지 관제 시스템의 구현 상태, 운영 적용 상태, 결정 사항과
> 다음 작업 순서를 기록한다. 지표별 PromQL과 수집 공백은
> `docs/operations-ai-metric-catalog.md`에서 관리한다.

## 1. 프로젝트 목표

기존 운영 방식은 장애가 발생한 뒤 Metric, Log, Trace, Kubernetes 상태를 각각 열어
원인을 추적해야 했다. 하나의 원인으로 여러 Alert가 발생하면 조사 시작 단계에서
상관관계를 다시 조립해야 하는 문제도 있다.

Operations AI는 다음 두 문제를 해결하는 내부 관제 시스템이다.

1. 고정 임계값에 도달하기 전, 정상 기준선에서 벗어나는 변화와 추세를 조기에 탐지한다.
2. 여러 Alert와 이상 후보를 하나의 Incident 조사 흐름으로 정리하고, 근거 기반 RCA 초안을 제공한다.

이는 미래를 예언하는 모델이 아니다. 정상 범위와 비교해 p95 지연, 요청량, CPU, Kafka Lag 등이
평소와 다르게 변화하는 시점을 먼저 찾는 통계 기반 조기 탐지다.

## 2. 최종 구조

```text
Prometheus / Loki / Tempo / Kubernetes Event / 배포 이력
        ↓
Anomaly Analyzer
- Rolling Z-score, MAD, 변화율, 연속 구간
        ↓
Alertmanager Webhook + Incident Correlator
- Alert 정규화, 저장, 시간·서비스·의존성 기반 후보 그룹화
        ↓
Evidence Package
- Incident와 관련된 Alert, 이상 후보, Log, Trace, K8s Event, 배포 이력
        ↓
Amazon Bedrock RCA + RAG
- 원인 후보, 근거 요약, 전파 경로, 점검 순서, 해결 권고 초안
        ↓
Operations 관리자 대시보드
        ↓
엔지니어 확인·조치·실제 원인·해결 기록
```

### 역할 분리

- **코드 기반 Analyzer/Correlator**: 이상 후보와 Incident 후보를 결정한다.
- **Evidence Builder**: 조사 범위에 맞는 사실 근거만 JSON으로 정리한다.
- **Bedrock**: Evidence와 RAG 문서를 해석해 RCA 초안을 작성한다. Alert를 임의로 묶거나 최종 장애를 판정하지 않는다.
- **엔지니어**: 실제 원인과 조치·해결 상태를 최종 확정한다.

## 3. 현재 구현 완료

### 3.1 Anomaly Analyzer

- Rolling Z-score, MAD, 변화율, 연속 이상 구간 기반 분석 구현
- 순간 Spike를 바로 장애로 처리하지 않고 연속 구간 조건을 적용
- 정상 결과는 저장하지 않고 `candidate`, `anomaly` 결과만 저장하도록 설계

### 3.2 Metric Catalog 및 Prometheus Collector

- Ready Metric Catalog 정의
- Prometheus HTTP API Client와 60초 주기 Collector 구현
- 최근 120분 시계열을 조회해 Analyzer에 전달
- 현재 준비된 대상
  - 서비스 p95 지연 시간
  - 서비스 요청량
  - Pod CPU 사용률, 메모리 Working Set
  - Kafka Consumer Lag
  - Redis 메모리 사용률
  - Pod Restart 증가, OOMKilled 발생
- p95는 유휴 구간 오탐을 막기 위해 최소 요청률 미만이면 분석하지 않음

### 3.3 Alert 및 Incident

- Alertmanager Webhook 수신 API 구현
- Alert 공통 형식 정규화 후 PostgreSQL 저장
- 전후 시간 범위, 서비스, Pod/Container, 의존 관계를 기준으로 Incident 후보 그룹화
- Alert 수신 흐름

```text
Alertmanager Webhook
→ Alert 정규화
→ operations.alerts 저장
→ 주변 firing Alert 조회
→ Incident Correlator
→ operations.incidents 생성 또는 갱신
```

### 3.4 Evidence Package

- Incident 시간 범위와 영향 서비스를 기준으로 이상 후보를 선택
- Incident Alert와 선택된 anomaly를 하나의 조사 JSON으로 생성
- 선택 근거를 `operations.incident_evidence`에 저장
- Kubernetes Evidence 1차 코드 구현
  - OOMKilled, CrashLoopBackOff/BackOff, Unhealthy, FailedScheduling, ReplicaSet/HPA 조정 Event
  - Deployment, ReplicaSet, 컨테이너 이미지 태그, SHA 형식 Git 태그
- Kubernetes Evidence는 기본 비활성 상태이며, 활성화 전 ServiceAccount/RBAC가 필요

### 3.5 검증 완료

- Operations Docker 이미지 빌드 성공
- 로컬 임시 PostgreSQL에 `schema.sql` 적용
- Alertmanager Webhook 입력의 Alert 저장 및 Incident 생성 확인
- Operations 단위 테스트 `24 passed`
- `git diff --check` 및 Kustomize 렌더링 통과

## 4. Git 및 배포 상태

### 4.1 food-budget-app

- `main`에는 Operations 기본 API와 Prometheus Collector가 반영됨
  - Collector PR: `#397`
- 다음 Evidence 코드는 아직 main 병합 전 브랜치에 있음
  - `feat/operations-evidence-package`
  - `feat/operations-kubernetes-evidence`
- Kubernetes Evidence 브랜치는 Evidence Package 브랜치를 기반으로 하므로,
  Evidence Package를 먼저 main에 병합한 뒤 Kubernetes Evidence를 이어서 병합한다.

### 4.2 mealplanning-config

Operations GitOps 매니페스트는 config 레포에 반영됐다.

- 초기 배포 매니페스트 PR: `#47`
- Harbor 이미지 태그 수정 PR: `#49`
- 생성된 구성

```text
argocd/applications/operations.yaml
services/operations/base/deployment.yaml
services/operations/base/service.yaml
services/operations/base/externalsecret.yaml
services/operations/base/kustomization.yaml
services/operations/overlays/onprem/kustomization.yaml
services/operations/overlays/eks/kustomization.yaml
```

규칙 준수 사항:

- `:latest`가 아닌 커밋 SHA 이미지 태그 사용
- 실제 비밀값을 저장하지 않고 ExternalSecret으로 `app-secrets.PGPASSWORD` 참조
- `app` 네임스페이스에 ClusterIP Service로 배포
- 최초 배포는 ArgoCD 수동 Sync 방식

### 4.3 현재 클러스터 상태

`mp-operations`은 실제 클러스터에 배포되어 정상 기동했다.

```text
Deployment: ready 1 / available 1 / updated 1
Pod: 2/2 Running
Restart: 0
Health Probe: HTTP 200
ExternalSecret: SecretSynced
```

현재는 안전한 1차 배포 상태다.

```text
OPERATIONS_DATABASE_ENABLED=true
OPERATIONS_COLLECTOR_ENABLED=false
OPERATIONS_KUBERNETES_EVIDENCE_ENABLED=false
```

따라서 이미지 Pull, Pod 기동, Service, Secret 주입, Health Probe는 검증됐지만,
실제 Prometheus 수집과 PostgreSQL 이상 후보 저장은 아직 활성화하지 않았다.

참고: ArgoCD가 Deployment에 대해 `OutOfSync / Healthy`를 보인 적이 있다. Pod 기동에는
문제가 없었으나, 다음 Sync 전 Diff를 확인해 GitOps 드리프트를 정리한다.

## 5. PostgreSQL 저장 구조

Operations는 기존 식비 서비스 테이블을 바꾸지 않고 별도 `operations` 스키마를 사용한다.

```text
operations.alerts
operations.incidents
operations.anomalies
operations.incident_evidence
```

운영 Collector를 켜기 전, DB 접속 권한이 있는 환경에서 아래 DDL을 한 번 적용해야 한다.

```bash
cd ~/food-budget-app
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction \
  -f services/operations/schema.sql
```

- `CREATE ... IF NOT EXISTS` 기반이라 재실행 가능
- 삭제 구문이 없으며 기존 서비스 데이터는 변경하지 않음
- DB에 생성되므로 Pod 재시작과 무관하게 유지됨

## 6. 아직 없는 관측 데이터

현재 수집 공백은 Analyzer가 실패한 것이 아니라, 원본 Metric 또는 Exporter가 아직 없는 상태다.

| 영역 | 현재 공백 | 보완 방법 |
| --- | --- | --- |
| HTTP 5xx 오류율 | `status` 라벨이 없어 계산 불가 | HTTP Metric 계측에 상태 코드 라벨 추가 |
| Poller 상태 | 실패 수, 마지막 성공 시각 없음 | Poller 성공·실패·완료 시각 Metric 추가 |
| PostgreSQL | 연결률, 느린 쿼리 지연 부족 | PostgreSQL Exporter 또는 OTel Trace 추가 |
| Elasticsearch | Heap 사용률 없음 | Elasticsearch Exporter 추가 |
| Loki | Incident별 오류 패턴 수집 미구현 | Loki Evidence Collector 추가 |
| Tempo | Incident별 Slow Trace 수집 미구현 | Tempo Evidence Collector 추가 |

## 7. 다음 작업 순서

### 1단계: Prometheus Collector 운영 검증

1. `operations` PostgreSQL 스키마 적용
2. `feat/operations-enable-prometheus-collector`에서 Collector만 `true`로 변경
3. config PR 머지 후 ArgoCD 수동 Sync
4. Prometheus 조회 성공과 Operations 로그 확인
5. `operations.anomalies`에 candidate/anomaly만 저장되는지 확인
6. 문제가 생기면 `OPERATIONS_COLLECTOR_ENABLED=false`로 즉시 되돌림

### 2단계: 기준선 및 부하 검증

1. k6로 정상 요청 패턴과 지연 상승 시나리오 생성
2. p95 최소 요청률, Z-score/MAD/변화율/연속 구간 기준 조정
3. 정상 Spike가 Incident로 과도하게 생성되지 않는지 확인

### 3단계: Evidence Package 확장

1. Loki에서 영향 서비스와 시간 범위에 맞는 오류 로그 패턴 집계
   - 원본 전체가 아닌 패턴, 발생 수, 대표 샘플만 포함
2. Tempo에서 Slow Trace, 오류 Span, 서비스 호출 경로 수집
3. Kubernetes Evidence 활성화 준비
   - Operations 전용 ServiceAccount
   - `app` 네임스페이스 최소 읽기 권한: Pod, Event, Deployment, ReplicaSet, HPA
4. 모든 근거를 Incident 단위 JSON으로 통합

### 4단계: Bedrock RCA와 RAG

1. Evidence Package를 Bedrock 입력으로 전달
2. 출력 형식 고정
   - 원인 후보 Top-N
   - 후보별 Metric·Log·Trace·Kubernetes·배포 근거
   - 영향 서비스 및 전파 경로
   - 점검 순서
   - 해결 권고 초안
3. RAG에는 서비스 문서, Runbook, 과거 Incident 해결 기록만 넣음
4. 텔레메트리 원본은 RAG 학습 데이터가 아니라 Evidence Package로 직접 전달

### 5단계: Operations 관리자 대시보드

대시보드는 Grafana 원본 탐색 화면을 대체하지 않는다. 조사 우선순위를 정하고 Incident 근거로
빠르게 이동하는 별도 운영 화면이다.

```text
Overview
Services / APM
Infrastructure
Data Pipeline
Anomalies
Incidents
```

Incident 상세에는 다음 탭을 둔다.

```text
개요
Metric 근거
Log 근거
Trace 근거
Kubernetes·배포 근거
RCA / 해결 권고
```

## 8. 운영 원칙

- Bedrock이 이상 탐지 점수나 Alert 병합을 임의로 결정하지 않는다.
- Alert와 anomaly는 사실 데이터이며, Evidence Package는 그 선택 근거를 남긴다.
- Bedrock 출력은 조사 초안이다. 엔지니어가 최종 원인과 해결을 확인한다.
- 신규 수집기는 기본 비활성으로 배포하고, 연결·저장·오탐을 단계별로 검증한 후 활성화한다.
- 운영 데이터와 RAG 문서를 분리한다. Metric/Log/Trace는 실시간 Evidence, Runbook과 과거 해결 기록은 RAG 컨텍스트다.
