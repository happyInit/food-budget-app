# MP K8s 보안 설계·준수사항

> 애플리케이션, Docker 이미지, 컨테이너 런타임, 인프라의 보안 기준을 이 문서 하나에서 관리한다.
> 프로젝트 스택(FastAPI + PostgreSQL/Elasticsearch/Redis/Kafka, Docker 베이스라인)에 적용하며, 보안 기준의 정본은 이 문서다.

적용이 어려운 항목은 미적용 이유·위험·보완책·재검토 시점을 PR 또는 인프라 변경 기록에 남기고 팀 리뷰를 받는다.

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
| 외부 바이너리·압축파일의 SHA-256 검증 | P0 | 외부 URL에서 직접 받을 때 필수 |
| 파일 권한 최소화 | P0 | `chmod 777` 금지, 쓰기 경로만 권한 부여 |

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

추가 적용 기준:

- 공식 또는 유지관리 주체가 명확한 베이스 이미지만 사용한다. Digest 고정은 운영 중요 이미지에 선택 적용한다.
- 빌드 과정이 있으면 멀티스테이지로 빌드 도구를 런타임 이미지에서 제거한다.
- OS 패키지는 `--no-install-recommends`로 설치하고 같은 `RUN`에서 패키지 캐시를 삭제한다.
- Python은 정확한 버전 또는 `poetry.lock`/`uv.lock`, Node는 `package-lock.json`과 `npm ci`를 사용한다.
- `.dockerignore`에 `.env`, 키, 인증서, credentials 파일을 포함하고 Dockerfile의 `COPY`, `ARG`, `ENV`, `RUN`에 실제 시크릿을 넣지 않는다.
- `COPY --chown` 등을 사용해 코드·설정의 쓰기 권한을 최소화하고, 결과물은 볼륨/PVC에 저장한다.
- `docker run ... id`, `docker inspect`, `docker history`로 실제 적용 여부를 확인한다.

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

OWASP Top 10 기준으로 다음을 함께 준수한다.

- **접근 제어(A01):** 보호 API는 인증을 요구한다. 요청의 `user_id`를 신뢰하지 않고 JWT의 사용자 ID를 사용하며, 조회·수정·삭제마다 소유권을 검증한다. 미인증·타 사용자 접근 거부 테스트를 작성한다.
- **보안 설정(A02):** 운영 환경에서 debug와 상세 오류를 끄고 개발/운영 시크릿을 분리한다. 관리자·내부 API와 Grafana 등 관리 화면을 인터넷에 직접 공개하지 않는다.
- **공급망(A03):** 공식 또는 팀 승인 패키지·이미지만 사용하고 의존성 버전을 고정한다. CI/Harbor에서 Trivy를 실행하며, 심각한 취약점을 즉시 해소하지 못하면 사유와 대응 계획을 기록한다.
- **암호화(A04):** 비밀번호는 Argon2id 또는 bcrypt 같은 검증된 비밀번호 해시로 저장한다. 비밀번호·API 키·토큰·영수증 개인정보를 로그에 남기지 않는다.
- **인젝션(A05):** 사용자 입력을 SQL, Elasticsearch 쿼리, OS 명령 문자열에 직접 연결하지 않는다. Pydantic으로 타입·길이·범위를 검증하고 SQLAlchemy의 파라미터 바인딩을 사용한다. OCR 파일은 형식·크기를 검사하고 YouTube URL은 허용 주소만 받는다.
- **인증(A07):** JWT의 서명·만료·토큰 유형을 검증한다. 로그아웃·비밀번호 변경 시 refresh token을 폐기할 수 있어야 한다.

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

CI/CD 자격 증명은 GitHub Actions Secrets에서 관리하고 워크플로에서는 `secrets.NAME`으로만 참조한다. 컨테이너 기동 시 필요한 값은 이미지가 아니라 배포 서버의 gitignored `.env` 또는 배포 단계에서 주입한다. 가공된 시크릿은 자동 마스킹이 깨질 수 있으므로 로그 출력을 금지하고, Harbor는 최소 권한 robot 계정을 사용한다.

Kafka는 K8s 전환 또는 접근 주체 증가 시 SASL/SCRAM이나 상호 TLS를 적용하고 PLAINTEXT 리스너를 제거한다. 프로듀서·컨슈머별 자격 증명을 분리한다. 현재 내부 VLAN 격리를 한시적 보완책으로 사용할 경우 그 사유와 재검토 시점을 기록하며, 새 인증 없는 접근 경로를 추가하지 않는다.

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

## 11. PR·배포 통합 체크리스트

변경과 관련된 항목만 확인하되, 설정 작성에 그치지 않고 실행 결과로 검증한다.

- [ ] 보호 API에서 인증과 리소스 소유권을 확인했는가?
- [ ] 사용자 입력을 SQL·검색·명령 문자열에 직접 붙이지 않았고 길이·범위를 검증했는가?
- [ ] Secret이나 개인정보가 코드·Git·로그·이미지에 포함되지 않는가?
- [ ] 최종 컨테이너가 비루트로 실행되고 공식 최소 베이스 이미지와 고정 버전을 사용하는가?
- [ ] 최종 이미지에 불필요한 패키지·빌드 도구·캐시가 없고 의존성 잠금 파일을 사용하는가?
- [ ] `chmod 777` 없이 실제 쓰기 경로에만 권한을 허용했는가?
- [ ] 서비스가 필요한 네트워크에만 연결되고 DB·Kafka·캐시 포트를 불필요하게 노출하지 않는가?
- [ ] 가능한 서비스에 `read_only`, tmpfs, `cap_drop`, `no-new-privileges`를 적용했는가?
- [ ] CI/CD 자격 증명을 Secrets로 관리하고 로그에 노출하지 않는가?
- [ ] 새 패키지·이미지의 출처와 취약점을 검사했는가?
- [ ] 관련 권한 실패·인증 실패 테스트를 작성했는가?
- [ ] 예외가 있다면 사유·위험·보완책·재검토 시점을 기록했는가?
