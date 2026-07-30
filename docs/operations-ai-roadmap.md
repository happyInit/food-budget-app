# Operations AI 구축 로드맵

## 목적

이 문서는 통합 관측 기반 AI 이상징후 탐지 시스템의 진행 상태, 결정 사항, 다음 작업을
관리한다. 지표별 PromQL과 수집 공백은 `operations-ai-metric-catalog.md`에서 관리한다.

## 최종 흐름

```text
Prometheus / Loki / Tempo / Kubernetes Event / 배포 이력
→ Anomaly Analyzer
→ Alertmanager Webhook + Incident Correlator
→ Evidence Package
→ Amazon Bedrock RCA + RAG
→ Operations 관리자 대시보드
→ 엔지니어 확인 및 해결 기록
```

## 완료

- [x] Rolling Z-score, MAD, 변화율, 연속 구간 기반 Anomaly Analyzer 구현
- [x] Alertmanager Webhook 수신 및 공통 Alert 형식 정규화
- [x] Alert PostgreSQL 저장
- [x] 시간, 서비스, 의존 관계 기반 Incident 후보 그룹화 및 저장
- [x] Ready Metric Catalog 정의
- [x] Prometheus HTTP API Client 구현
- [x] Prometheus Collector 구현
  - p95, 요청량, Pod CPU/메모리, Kafka Lag, Redis 메모리 비율 분석
  - Pod Restart, OOMKilled 이벤트 분석
  - 정상값을 제외하고 이상 후보만 `operations.anomalies`에 저장
- [x] Operations 대시보드 목업 작성
- [x] Operations GitOps 배포 초안 작성
  - `mp-operations` Deployment 및 ClusterIP Service
  - PostgreSQL 비밀번호 ESO 참조
  - Prometheus Collector 환경 변수 설정
  - ArgoCD child Application 추가
- [x] 로컬 컨테이너 검증
  - Operations Docker 이미지 빌드 및 `/health` 확인
  - 임시 PostgreSQL에 Operations 스키마 적용
  - Alertmanager Webhook 입력의 Alert 저장 및 Incident 생성 확인
- [x] Evidence Package 1차 구현
  - Incident 시간·서비스·Pod 기준 anomaly 선택
  - Incident Alert와 선택된 anomaly를 조사 JSON으로 생성
  - 선택 근거를 `operations.incident_evidence`에 저장

## 현재 단계

Prometheus Collector 코드는 구현 및 단위 테스트를 마쳤다. GitOps 배포 YAML도 작성했고,
로컬 PostgreSQL 저장까지 검증했다. 다만 `mp-operations-service` 이미지가 Harbor에 아직
빌드되지 않아 ArgoCD 동기화와 클러스터 Prometheus/실제 PostgreSQL 연동 검증은 진행하지 않았다.

## 다음 작업 순서

1. Operations 이미지 빌드 및 Collector 운영 배포
   - Jenkins 서비스 카탈로그에서 `operations` 이미지 빌드
   - Harbor에 커밋 SHA 태그 이미지가 생성된 것 확인
   - ArgoCD에서 `mp-operations`을 수동 동기화
2. 실제 데이터 검증
   - `operations.anomalies` 테이블 생성
   - Collector 환경 변수와 Prometheus 내부 주소 설정
   - 수동 실행 API로 실제 저장 결과 확인
3. k6 부하 테스트 및 기준선 조정
   - p95 최소 요청률 확정
   - 서비스별 정상 패턴과 이상 탐지 임계값 검토
4. Evidence Collector 확장
   - Loki Log 패턴, Tempo Slow Trace, Kubernetes Event, 배포 이력 수집
   - Evidence Package에 원본 조회 링크와 근거 추가
5. Bedrock RCA 및 RAG 연동
   - 원인 후보, 근거 요약, 전파 경로, 점검 순서, 해결 권고 생성
   - Runbook, 서비스 문서, 과거 해결 기록을 RAG 검색 근거로 추가
6. Operations 관리자 대시보드 API 및 화면 연동
   - Anomalies 목록, Incidents 목록, Incident 상세 근거 및 RCA 표시
7. 관측 공백 보완
   - HTTP 상태 코드 라벨 기반 5xx 오류율
   - Poller 성공/실패 메트릭
   - PostgreSQL, Elasticsearch Exporter 또는 OTel 계측

## 현재 관측 공백

- 5xx 오류율: 현재 HTTP 메트릭에 `status` 라벨이 없다.
- Poller 실패 수와 마지막 성공 시각: 애플리케이션 메트릭이 없다.
- PostgreSQL 연결률 및 쿼리 지연: PostgreSQL Exporter 또는 Trace 지표가 필요하다.
- Elasticsearch Heap 사용률: Elasticsearch Exporter 지표가 필요하다.

## 운영 원칙

- 코드가 이상 후보와 Incident 후보를 결정한다.
- Bedrock은 관측 근거 기반 RCA 초안을 생성하며 최종 장애 판정 권한이 없다.
- 엔지니어가 실제 원인, 조치, 해결 상태를 최종 확인하고 기록한다.
- 원본 Metric, Log, Trace는 Incident 상세의 근거 화면에서 다시 조회 가능해야 한다.
