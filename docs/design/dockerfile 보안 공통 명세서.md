# Dockerfile 보안 공통 명세서

## 1. 문서 목적

- 모든 서비스 Dockerfile에 적용할 최소 보안 기준을 통일한다.
- 항목을 필수·조건부 필수·선택으로 구분한다.
- 설정 적용이 어려운 경우 PR에 사유를 남긴다.

## 2. 한눈에 보는 적용 기준

| 번호 | 항목 | 적용 | 핵심 기준 |
|---|---|---|---|
| 1 | 비루트 사용자 실행 | 필수 | 최종 프로세스는 UID 0이 아닌 사용자로 실행 |
| 2 | 공식 최소 베이스 이미지 | 필수 | `latest` 금지, 명확한 버전 사용. Digest는 선택 |
| 3 | Secret·민감 파일 미포함 | 필수 | `.dockerignore` 사용, `.env`·Key `COPY` 금지 |
| 4 | 불필요 도구·캐시 제거 | 조건부 필수 | 빌드가 있으면 Multi-stage, 패키지 캐시 삭제 |
| 5 | 의존성·외부 파일 관리 | 조건부 필수 | Lock 파일 사용, 외부 다운로드 시 SHA-256 검증 |
| 6 | 파일 권한 최소화 | 조건부 필수 | `chmod 777` 금지, 필요한 경로만 쓰기 허용 |

## 3. 항목별 적용 방법

### 3.1 비루트 사용자 실행

**도입 이유:** 컨테이너가 침해되더라도 root 권한 사용과 피해 확산을 줄이기 위해 적용한다.

**적용 방법:** 전용 사용자를 만들거나 베이스 이미지가 제공하는 비루트 사용자를 사용하고, 최종 단계에 `USER`를 지정한다.

**확인·예외:** `docker run --rm <이미지명> id` 결과가 `uid=0`이 아니어야 한다.

```dockerfile
USER 10001:10001
```

### 3.2 신뢰 가능한 최소 베이스 이미지

**도입 이유:** 불필요한 패키지와 취약점 수를 줄이고 출처가 불명확한 이미지 사용을 막기 위해 적용한다.

**적용 방법:** 공식 또는 유지관리 주체가 명확한 이미지를 사용한다. `latest`는 금지하고 `python:3.12-slim`, `node:22-alpine`, JRE처럼 명확한 버전을 사용한다.

**확인·예외:** Digest 고정은 관리 부담이 있으므로 운영 중요 이미지에 선택 적용한다. Alpine은 호환성을 확인한 후 사용한다.

```dockerfile
FROM python:3.12-slim
```

### 3.3 Secret·민감 파일 이미지 미포함

**도입 이유:** 비밀번호, 키, 인증서가 이미지 레이어와 저장소에 남는 것을 막기 위해 적용한다.

**적용 방법:** `.dockerignore`에 `.env`, Key, 인증서, credentials 파일을 등록한다. Dockerfile의 `COPY`, `ARG`, `ENV`, `RUN`에 실제 Secret 값을 넣지 않는다.

**확인·예외:** 실행 시점에 Docker Compose, Kubernetes Secret 또는 환경변수로 주입한다.

```dockerignore
.env
.env.*
*.pem
*.key
secrets/
```

### 3.4 불필요한 패키지·빌드 도구·캐시 제거

**도입 이유:** 이미지 크기와 공격자가 사용할 수 있는 도구를 줄이기 위해 적용한다.

**적용 방법:** 빌드 과정이 있는 서비스는 Multi-stage Build를 사용한다. OS 패키지를 설치하면 update와 install을 같은 `RUN`에서 실행하고 캐시를 삭제한다.

**확인·예외:** 별도 빌드가 없고 최종 이미지에 빌드 도구가 남지 않는 서비스는 Multi-stage를 생략할 수 있다.

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends <package> \
    && rm -rf /var/lib/apt/lists/*
```

### 3.5 의존성 및 외부 파일 관리

**도입 이유:** 빌드 시점마다 의존성 버전이 바뀌거나 변조된 외부 파일이 포함되는 것을 막기 위해 적용한다.

**적용 방법:** 언어 의존성을 설치하는 서비스는 Lock 파일을 사용한다. Node는 `package-lock.json`과 `npm ci`, Python은 정확한 버전 또는 `poetry.lock`/`uv.lock`, Java는 Gradle·Maven 잠금 정책을 사용한다.

**확인·예외:** OS 패키지의 정확한 버전 고정은 필수가 아니다. 외부 URL에서 바이너리·압축파일을 직접 받는 경우에만 SHA-256 검증을 필수로 한다.

```dockerfile
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
```

### 3.6 파일 소유권과 권한 최소화

**도입 이유:** 애플리케이션 코드와 설정 파일이 임의로 변경되는 것을 막기 위해 적용한다.

**적용 방법:** `chmod 777`은 금지한다. 코드와 설정 파일은 쓰기 권한을 최소화하고, `output`·`cache`·`tmp`처럼 런타임에 필요한 경로에만 쓰기 권한을 준다.

**확인·예외:** `COPY --chown`, `--chmod`는 필요한 경우에만 사용한다. 유지해야 하는 결과 파일은 Volume 또는 Kubernetes PVC에 저장한다.

```dockerfile
RUN mkdir -p /app/output /app/cache \
    && chown -R 10001:10001 /app/output /app/cache
```

## 4. PR 제출 전 체크리스트

- [ ] 최종 프로세스가 root가 아닌 사용자로 실행되는가?
- [ ] 공식·검증된 베이스 이미지와 명확한 버전을 사용했는가?
- [ ] `.env`, Key, 인증서, Secret이 이미지에 포함되지 않는가?
- [ ] 최종 이미지에 불필요한 패키지와 빌드 도구가 없는가?
- [ ] 언어 의존성을 설치한다면 Lock 파일을 사용했는가?
- [ ] 외부 URL에서 파일을 받는다면 SHA-256을 확인했는가?
- [ ] `chmod 777`을 사용하지 않았는가?
- [ ] 실제로 쓰기가 필요한 경로에만 쓰기 권한을 허용했는가?
- [ ] 적용할 수 없는 항목은 PR에 사유를 작성했는가?

완료 기준은 설정 작성에 그치지 않고 `docker run`, `docker inspect`, `docker history` 등으로 실제 적용 여부까지 확인하는 것이다.
