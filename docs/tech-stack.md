# 밀플래닝 — 기술 스택 · 용도 · 담당자

> Bravo-Team / food-budget-app · 발표용 정리 (설계 정본 `docs/design.md` 기준)

| 구분 | 기술 | 쉬운 설명 | 우리 서비스 활용 | 담당자 |
|---|---|---|---|---|
| Frontend | React + Vite + TypeScript | 웹 화면 만드는 기본 틀 | 전체 화면 (홈·냉장고·레시피 등) | 김봉수 |
| Frontend | PWA | 반응형 웹 + 홈화면 설치·푸시알림 | 최저가·소비기한 임박 알림 | 김봉수 |
| Frontend | TanStack Query | 서버 데이터 자동 캐시·갱신·로딩표시 | 홈 대시보드·검색·가격조회 데이터 | 김봉수 |
| Frontend | Zustand | 앱 안 공용 값 저장(화면 상태) | 장바구니 개수·선택 필터·로그인 정보 | 김봉수 |
| Frontend | Tailwind | 스타일 빠르게 입히는 CSS 도구 | 카드·버튼 등 공통 디자인 | 김봉수 |
| Backend | FastAPI | 파이썬 API 서버 프레임워크 | 8개 서비스 전부 | 김봉수/윤태현 |
| Backend | API Gateway + PyJWT | 요청 라우팅 + 로그인 토큰 검증 | 모든 API 입구·인증 | 김봉수/윤태현 |
| Backend | psycopg3 (raw SQL) | 생 SQL + `row_factory` dict 매핑 (ORM/Alembic 미사용, 2026-07-15 결정) | PG 접근·마이그레이션=멱등 DDL(`schema-production.sql`) | 김봉수/윤태현 |
| Backend | Pydantic | 요청/응답 데이터 검증 | API 입출력 검증 | 김봉수/윤태현 |
| AI/ML | CRF 재료 NER | 레시피 글에서 재료 추출·표준화 | 레시피→재료→가격 매칭 (핵심) | 이건우/윤태현 |
| AI/ML | z-score 이상탐지 | 가격 급락 통계 감지 | 최저가 알림 | 이건우/윤태현 |
| AI/ML | XGBoost | 소비기한 예측 모델 | 냉장고 신선도·임박 | 이건우/윤태현 |
| AI/ML | LightGBM | 개인화 랭킹 모델 | 레시피 추천 순서 | 이건우/윤태현 |
| AI/ML | RAG 대화형 어시스턴트 | 재고·예산 알고 답하는 챗봇 | 밀플래닝 어시스턴트 | 이건우/윤태현 |
| AI/ML | Gemini (외부 유료) | 유튜브 영상 이해(멀티모달) | YouTube URL → 레시피 추출 | 이건우/윤태현 |
| DB | PostgreSQL | 메인 관계형 DB | 재고·식비·가격이력·유저 | 윤태현 |
| DB | Elasticsearch (nori) | 한국어 검색엔진 | 레시피·상품 검색 | 윤태현 |
| DB | Redis | 초고속 캐시 메모리 | 현재가 캐시·추출 결과 캐시 | 윤태현 |
| 파이프라인 | Python 크롤러/폴러 | 데이터 수집·처리 스크립트 | 마컬·오아시스·만개·OCR 수집 | 현정은 |
| 파이프라인 | Apache Kafka (Strimzi) | 데이터 줄세워 흘리는 파이프 | 수집 처리 + 최저가 알림 뿌리기 | 현정은 |
| 파이프라인 | KEDA | 이벤트 몰리면 자동 증설 | 알림 버스트 대응 | 현정은 |
| 인프라 | Docker | 앱을 통조림으로 포장 | 전 서비스 배포 단위 (현 베이스라인) | 윤태현/김봉수 |
| 인프라 | Proxmox | 물리서버를 가상머신으로 분할 | 온프렘 4-VM | 윤태현/김봉수 |
| 인프라 | Harbor | 사설 도커 이미지 저장소 | 온프렘 레지스트리 | 윤태현/김봉수 |
| 인프라 | GitHub Actions | 코드 올리면 자동 빌드·테스트 | CI 파이프라인 | 윤태현/김봉수 |
| 인프라 | Kubernetes + ArgoCD | 컨테이너 자동 관리·배포(GitOps) | 향후 데모 (오토스케일·자동배포) | 윤태현/김봉수 |
| 인프라 | AWS (EC2·ECR·Terraform) | 클라우드 인프라 | 향후 클라우드 티어 | 윤태현/김봉수 |
| 모니터링 | Prometheus + Loki + Grafana | 상태·로그·그래프 모니터링 | 트래픽·장애 관측 | 임정현 |

> 참고 — 인프라의 Docker·Proxmox·Harbor·GitHub Actions는 **현 배포 베이스라인**, Kubernetes·AWS는 **향후 데모/클라우드 티어** (발표 시 구분).
