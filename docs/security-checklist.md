# 컨테이너·서비스 보안 및 운영 점검 사항

> 개발 착수 전 참고용 정리. 현업 기준의 컨테이너/서비스 보안·운영 관행을 프로젝트 스택(FastAPI + PostgreSQL/Elasticsearch/Redis/Kafka, Docker 베이스라인)에 맞춰 정리한다.
> 팀 확정 사항이 아니라 **검토·적용 대상 목록**이다. 각 항목의 실제 채택 여부는 개발하며 결정한다.

## 1. 우선순위 기준

| 등급 | 의미 |
|---|---|
| P0 | 개발 초기부터 반드시 반영 (나중에 넣으면 재작업·사고 위험) |
| P1 | 가능하면 반영 (품질·데모 가치) |
| P2 | 여유 시 / 고급 |

`(있음)` 표기는 이미 설계(design.md 등)에 반영된 항목.

---

## 2. 이미지 하드닝

| 항목 | 등급 | 비고 |
|---|---|---|
| 컨테이너를 non-root 유저로 실행 (`USER appuser`) | P0 | root 실행 시 컨테이너 탈출 위험 확대 |
| 최소 베이스 이미지 (`python:3.x-slim` / distroless) + 멀티스테이지 | P0 | 빌드/런타임 분리 (있음) |
| 이미지 태그 버전 고정, `:latest` 금지 | P0 | 재현성·공급망 안정 |
| `.dockerignore` 로 `.git`·`.env`·키 파일 제외 | P0 | 이미지에 비밀 유출 방지 |
| 이미지에 시크릿을 굽지 않음 (ENV/ARG에 비밀번호·키 금지) | P0 | 레이어에 영구 각인됨 |
| 이미지 취약점 스캔 (Trivy/Grype) | P1 | Harbor에 Trivy 내장 — 활성화만 하면 됨 |
| `HEALTHCHECK` 정의 | P1 | 오케스트레이터 상태 판정 |

Dockerfile 예시(요지):

```dockerfile
FROM python:3.12-slim AS build
# ... 의존성 설치 ...

FROM python:3.12-slim
RUN useradd -m -u 10001 appuser
USER appuser
COPY --from=build /app /app
HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1
```

---

## 3. 컨테이너 런타임 하드닝 (compose / K8s)

| 항목 | 등급 | 비고 |
|---|---|---|
| 리소스 한계 (memory / cpu limit) | P0 | 한 컨테이너가 호스트 자원 독점 방지 (있음, §8.4) |
| `read_only: true` (루트 파일시스템 읽기 전용) + 필요한 경로만 tmpfs | P1 | 변조 방지 |
| `cap_drop: [ALL]` 후 필요한 권한만 추가 | P1 | 리눅스 커널 권한 최소화 |
| `security_opt: [no-new-privileges:true]` | P1 | 권한 상승 차단 |
| `restart` 정책 + `depends_on: condition: service_healthy` | P1 | 기동 순서·복구 |

compose 예시(요지):

```yaml
services:
  recipe:
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    deploy:
      resources:
        limits: { memory: 512m, cpus: "0.5" }
```

---

## 4. 시크릿 관리

가장 사고가 잦은 영역. 대상: DB 비밀번호, JWT 서명키, Gemini API 키, Kakao client secret.

| 항목 | 등급 | 비고 |
|---|---|---|
| 시크릿을 git에 커밋하지 않음 (`.env`는 gitignore) | P0 | 커밋 이력에 남으면 회수 어려움 |
| compose: docker secrets 또는 gitignore된 `.env` 주입 | P0 | 코드/이미지와 분리 |
| K8s 전환 시: Sealed Secrets / External Secrets(Vault) | P1 | 평문 Secret 리소스 지양 |
| Elasticsearch / Redis / Kafka 인증 활성화 | P0 | 기본값이 무인증 — Redis `requirepass`, ES security, Kafka SASL |
| 키 회전 절차 정의 | P2 | 유출 대응 |

주의: Elasticsearch·Redis·Kafka는 기본 설정이 인증 없이 열려 있다. 네트워크로만 가려도 내부 침투 시 무방비이므로 인증을 반드시 켠다.

---

## 5. 애플리케이션·인증 보안 (User 서비스 중심)

| 항목 | 등급 | 비고 |
|---|---|---|
| 비밀번호 해싱: bcrypt 또는 argon2 | P0 | 자체 이메일/비밀번호 로그인. 평문·단순 해시 금지 |
| JWT: 짧은 만료 + refresh 토큰, 서명키는 시크릿 | P0 | HS256이면 키를 충분히 길게, 필요 시 RS256 키쌍 |
| 로그인 rate limiting / 계정 잠금 | P0 | 브루트포스 방어 |
| Kakao OAuth: `state` + PKCE | P1 | CSRF·인가코드 탈취 방어 |
| CORS 화이트리스트 (Gateway) | P0 | 허용 오리진 명시 |
| 입력 검증(Pydantic), ORM 파라미터 바인딩(SQLAlchemy) | P0 | 인젝션 방어 (있음) |
| HTTPS/TLS 종단 (nginx 또는 Gateway) | P0 | 평문 전송 금지 |

---

## 6. 데이터 보안

프로젝트 특성상 개인정보(PII)를 다룬다: 영수증 OCR = 개인 소비·금융 정보.

| 항목 | 등급 | 비고 |
|---|---|---|
| 영수증 원문·파싱 결과의 저장 최소화·접근 제한 | P0 | 로그에 원문 남기지 않기 |
| YouTube 추출 캐시: Redis TTL 30일, 영구 공유 저장 금지 | P0 | (있음, §3.4) |
| 저장소 전송구간 TLS (서비스 ↔ PG/ES/Redis) | P1 | 내부망이라도 권장 |
| PostgreSQL 정기 백업 + retention | P1 | 데이터 손실 대비 |
| 관측 스택 로그·트레이스 retention 상한 | P1 | (있음, §8.4) |

---

## 7. 네트워크

| 항목 | 등급 | 비고 |
|---|---|---|
| 네트워크 티어 분리 (edge / app / data) | P0 | DB는 data 네트워크에만 노출 |
| DB·캐시·Kafka 포트를 호스트에 노출하지 않음 | P0 | `ports:` 대신 네트워크 내부 통신 |
| data 네트워크 `internal: true` | P1 | 외부 아웃바운드 차단 |
| 멀티 호스트(VM 간) 통신 방식 결정 | P0 | compose bridge는 단일 호스트 한정. VM 간은 IP:포트 직접 연결 또는 Swarm overlay/K8s CNI 필요 |

참고: 현재 베이스라인이 VM별 docker-compose이면 VM 내부는 compose 네트워크로 티어를 나누고, VM 간(App↔Data)은 IP:포트로 잇는다. VM 간을 하나의 가상 네트워크로 묶으려면 Swarm overlay 또는 K8s로 승격해야 한다. (design.md §8.4 하이브리드 방향과 연동)

---

## 8. 공급망 및 CI/CD

| 항목 | 등급 | 비고 |
|---|---|---|
| 의존성 버전 고정 + 락파일 (requirements 핀 / poetry.lock) | P0 | 재현성 |
| 의존성 취약점 스캔 | P1 | CI 단계 |
| CI 러너·레지스트리 최소 권한 (Harbor robot 계정) | P1 | 권한 남용 방지 |
| 로그의 시크릿 마스킹 | P1 | CI 로그 유출 방지 |
| 이미지 서명 (cosign) | P2 | 데모/고급 |

---

## 9. 우선 적용 정리

개발 초기에 반드시 잡고 갈 P0 핵심:

- 이미지: non-root 유저, 시크릿 미포함, 버전 고정
- 시크릿: git 제외, Elasticsearch/Redis/Kafka 인증 활성화
- 인증: 비밀번호 해싱, JWT, 로그인 rate limit, CORS, TLS 종단
- 데이터: 영수증(PII) 취급 최소화
- 네트워크: 티어 분리, DB 포트 비노출, VM 간 통신 방식 확정

## 10. 자주 누락되는 항목 (경험칙)

- Elasticsearch/Redis/Kafka를 인증 없이 띄우고 네트워크로만 가린 채 방치
- `.env`나 키 파일을 초기에 실수로 커밋 (이력에서 회수 어려움)
- 비밀번호를 약한 해시로 저장
- 컨테이너를 root로 실행
- compose bridge 네트워크가 호스트를 넘는다고 가정 (실제로는 단일 호스트 한정)
