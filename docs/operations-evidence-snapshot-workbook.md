# Operations Evidence Snapshot 작업 워크북

> 작성일: 2026-08-01  
> 작업 브랜치: `feat/operations-evidence-snapshot`  
> 대상 커밋: `d66643a`, `f211ff7`

## 1. 이 작업이 필요한 이유

Operations의 Evidence API는 Incident 하나에 대해 anomaly, Alert, Kubernetes Event·Deployment,
Loki 로그 패턴, Tempo Trace를 조립해 `EvidencePackage` JSON으로 반환한다. 하지만 기존에는
`anomaly`·`alert` 선택 링크만 `operations.incident_evidence`에 남고, log·trace·Kubernetes·deployment
근거는 API 호출 순간에만 존재했다.

이 구조에서는 대시보드에서 6시간 또는 24시간 전 Incident를 다시 열 때 다음 문제가 생긴다.

- Loki 보존·라벨 변경에 따라 당시의 로그 패턴이 사라지거나 달라질 수 있다.
- Tempo의 검색 결과와 Kubernetes Event·Deployment 상태는 조사 시점과 달라질 수 있다.
- 이후 Bedrock RCA가 해석한 입력 근거를 동일하게 재현할 수 없다.

따라서 원본 대량 텔레메트리가 아니라, 이미 Incident 범위로 압축·선택된 `EvidencePackage`를
스냅샷으로 보관해야 대시보드와 RCA가 같은 사실 근거를 사용한다.

## 2. 이번 작업의 목표와 범위

이번 작업은 아래 두 가지를 구현한다.

1. Evidence API가 만든 압축 Evidence JSON을 Incident별로 외부 PostgreSQL의 `operations`
   스키마에 저장한다.
2. 대시보드가 시간 범위로 Anomaly·Incident를 조회하고, Incident의 최신 Evidence Snapshot을
   조회할 수 있는 내부 API를 제공한다.

이번 범위에 포함하지 않은 항목은 다음과 같다.

- 외부 team2 PostgreSQL에 DDL을 실제 적용하는 작업
- Prometheus Collector, Kubernetes/Loki/Tempo Evidence Collector 활성화
- Alertmanager 실제 webhook 라우팅
- Bedrock 호출, RAG, RCA 결과 저장
- 프론트엔드 화면 구현

## 3. 변경 전·후 데이터 흐름

### 변경 전

```text
Incident Evidence API 호출
  → Alert / anomaly 조회
  → K8s / Loki / Tempo 근거 수집
  → EvidencePackage JSON 응답
  → anomaly·alert 링크만 DB에 저장
```

### 변경 후

```text
Incident Evidence API 호출
  → Alert / anomaly 조회
  → K8s / Loki / Tempo 근거 수집
  → EvidencePackage JSON 조립
  → operations.incident_evidence 링크 저장
  → operations.incident_evidence_snapshots에 JSON Snapshot 저장
  → API 응답

대시보드
  → 시간 범위 Anomaly / Incident 조회
  → Incident 최신 Evidence Snapshot 조회
```

스냅샷에는 원본 Loki 로그 전체나 Tempo Trace 전체를 넣지 않는다. 기존 Evidence 형식의
로그 패턴·발생 수·대표 sample, Trace ID·지연·오류 여부, Kubernetes Event·Deployment 메타데이터만
보관한다.

## 4. 변경 파일과 역할

| 파일 | 변경 내용 | 왜 필요한가 |
| --- | --- | --- |
| `services/operations/schema.sql` | `operations.incident_evidence_snapshots` 테이블과 Incident·수집시각 인덱스 추가 | 압축 Evidence를 과거에도 재현할 수 있게 보관한다. |
| `services/operations/app/models.py` | `EvidenceSnapshot` Pydantic 모델 추가 | DB 행과 API 응답의 계약을 고정한다. |
| `services/operations/app/queries.py` | Snapshot 생성·최신 조회, 시간 범위 Anomaly·Incident 조회 쿼리 추가 | raw psycopg3 방식으로 저장·조회 책임을 분리한다. |
| `services/operations/app/main.py` | Evidence 생성 뒤 Snapshot 저장, 내부 조회 API 3개 추가 | Evidence 생성과 대시보드 소비 경로를 연결한다. |
| `services/operations/tests/test_evidence_snapshots.py` | Snapshot 저장/조회와 시간 범위 목록 쿼리 단위 테스트 추가 | DB 없이 SQL 계약과 모델 매핑을 검증한다. |

## 5. DB 설계

새 테이블은 `operations.incident_evidence_snapshots`다.

| 컬럼 | 의미 |
| --- | --- |
| `snapshot_id` | 애플리케이션이 UUID로 만드는 스냅샷 식별자 |
| `incident_id` | `operations.incidents`를 참조하는 Incident 식별자 |
| `captured_at` | EvidencePackage가 생성된 시각 |
| `evidence_package` | Pydantic JSON 직렬화된 압축 EvidencePackage |
| `created_at` | DB 행 생성 시각 |

동일 Incident에 Evidence를 다시 생성하면 기존 Snapshot을 덮어쓰지 않고 새 행을 만든다. 이는
조사 시점별 근거 변화를 남기기 위한 것이다. 최신 화면은 `captured_at DESC, snapshot_id DESC`로
한 건을 조회한다.

아직 보존 기간·삭제 정책은 구현하지 않았다. 24시간 조회가 최소 요구사항이지만, 실제 보존 기간은
운영 데이터 용량과 감사 요구사항을 보고 별도로 확정해야 한다.

## 6. 추가한 API 계약

모든 API는 현재 Operations 서비스의 내부 경로다.

| API | 용도 |
| --- | --- |
| `POST /internal/incidents/{incident_id}/evidence` | EvidencePackage를 만들고 기존 Evidence 링크와 새 Snapshot을 저장한다. 응답 형식은 기존 `EvidencePackage`를 유지한다. |
| `GET /internal/incidents/{incident_id}/evidence/latest` | 해당 Incident의 최신 `EvidenceSnapshot`을 반환한다. Snapshot이 없으면 404다. |
| `GET /internal/anomalies?start_at=…&end_at=…&limit=…` | 1h/6h/24h 등 대시보드가 선택한 범위의 저장된 candidate/anomaly를 최신순으로 반환한다. |
| `GET /internal/incidents?start_at=…&end_at=…&limit=…` | 선택 시간 범위와 겹치는 Incident를 최신순으로 반환한다. |

`limit`은 1~500, 기본 100이다. 시간 범위는 프론트가 1h·6h·24h 선택값을 ISO-8601
`start_at`·`end_at`으로 변환해 전달한다.

## 7. 검증 결과

### 추가한 테스트

- Snapshot 생성 시 `operations.incident_evidence_snapshots` INSERT와 JSON payload 확인
- Incident별 최신 Snapshot SELECT와 Pydantic 역직렬화 확인
- 시간 범위 Anomaly SELECT 확인
- 시간 범위와 겹치는 Incident SELECT 확인

### 실행한 검증

- `python3 -m compileall -q app tests` 통과
- `git diff --check` 통과

현재 작업 환경에는 `pytest`, FastAPI, Pydantic, psycopg 의존성이 설치되어 있지 않아
`pytest -q`는 실행하지 못했다. PR CI 또는 의존성이 설치된 환경에서 Operations 테스트 전체를
반드시 실행해야 한다.

## 8. 운영 적용 전 확인할 사항

코드 머지만으로 외부 DB나 클러스터 상태는 변하지 않는다. 적용 전 다음을 별도로 확인한다.

1. 외부 team2 PostgreSQL에 최신 `services/operations/schema.sql`을 멱등 적용한다.
2. 새 Operations 이미지 SHA를 config 레포 Deployment에 핀하고 ArgoCD Sync한다.
3. 운영 Pod에서 Snapshot INSERT 권한과 DB 연결을 확인한다.
4. 테스트 Incident 하나를 대상으로 Evidence API 호출 후 Snapshot 행과 최신 조회 API를 검증한다.

현재 Collector와 Evidence Collector 설정은 안전을 위해 그대로 비활성이다.

```text
OPERATIONS_COLLECTOR_ENABLED=false
OPERATIONS_KUBERNETES_EVIDENCE_ENABLED=false
OPERATIONS_LOKI_EVIDENCE_ENABLED=false
OPERATIONS_TEMPO_EVIDENCE_ENABLED=false
```

## 9. 다음 작업

1. 이 브랜치의 테스트를 CI에서 통과시키고 PR로 검토한다.
2. 외부 DB DDL 적용 및 Snapshot 저장/조회 실검증을 마친다.
3. 대시보드에서 위 시간 범위 API와 최신 Snapshot API를 연결한다.
4. Collector → Alertmanager → Kubernetes → Loki → Tempo 순으로 실제 수집을 단계적으로 활성화한다.
5. k6로 anomaly → alert → incident → evidence snapshot을 검증한 뒤, AWS EC2 Bedrock RCA 연동으로 진행한다.
