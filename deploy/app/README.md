# deploy/app — fb-app-ai(192.168.0.9) 앱 스택 (compose)

FastAPI **8개**(chat 포함) + 프론트(**nginx** 리버스 프록시)를 한 compose 스택으로 올린다.
데이터티어(PG·ES·Redis)는 스택 밖 **fb-data(192.168.0.8)** — `.env` 로 주입.

- **포트 노출 = nginx `:80` 하나.** 8개 서비스는 내부망 `fbnet` 에서 서비스명 DNS 로만 접근(호스트 포트 미노출 → §6.1).
- **프론트는 항상 `/api/*` 상대경로** → nginx 가 서비스로 라우팅(`../frontend/nginx.conf`, `vite.config.ts` 와 1:1). 브라우저 진입점 = `http://192.168.0.9/`.
- **chat 포함** — compose 스택의 8번째 서비스(내부 8003). nginx `/api/mealplan/assistant` → `chat:8003`. (standalone chat-service·ci-sample 은퇴됨)

## 구성 파일
| 파일 | 역할 |
|---|---|
| `docker-compose.yml` | 7 서비스 + frontend. `image`(Harbor)+`build`(로컬) 듀얼. `.env` 주입. |
| `.env.example` | `.env` 템플릿 — `PGPASSWORD`·`JWT_SECRET` 채워 `.env` 로 복사(커밋 금지). |
| `../../frontend/Dockerfile` | 멀티스테이지 node→nginx. | 
| `../../frontend/nginx.conf` | SPA + `/api/*` 리버스 프록시. |

## 최초 브링업 (로컬 빌드, Harbor 불요)
소스가 있는 호스트(.9)에서:
```bash
cd ~/foodbudget-app/deploy/app
cp .env.example .env && vi .env          # PGPASSWORD·JWT_SECRET 채우기
docker compose build                     # 7 py + 1 node 이미지 로컬 빌드
docker compose up -d
docker compose ps                         # 전부 healthy 확인
curl -sf http://localhost/healthz         # nginx OK
```

## 정상 경로 (CI/CD, main 머지 후)
`.github/workflows/build-push-app.yml` 가 변경된 서비스/프론트만 빌드→Trivy→Harbor push 후,
`.9` 에서 `docker compose pull && up -d`. **전제: `.9` 에 `.env` 가 이미 존재**(위 브링업에서 생성, 영속).
> CI 가 `.env` 를 시크릿에서 재생성하도록 바꾸려면 `JWT_SECRET` 을 GH Secret 으로 승격(값 고정 필수 — 바뀌면 기존 토큰 무효).

## 운영 커맨드
```bash
docker compose logs -f account            # 서비스 로그
docker compose up -d --build recipe       # 한 서비스만 재빌드·재기동
docker compose pull && docker compose up -d   # Harbor 최신 반영
docker compose down                       # 스택 종료(볼륨 없음 — 상태는 전부 fb-data)
```

## 알려진 것
- **chat degraded 부팅** — 의존성(PG 등) 실패 시 크래시 대신 degraded 로 뜬다(`/health`=degraded, 챗은 정중한 안내 + 요청마다 자가복구). 일시적 PG blip 에 502/재시작 루프 방지.
- CI 정상경로의 `compose pull` 은 **.9 가 Harbor pull 가능**을 전제(기존 파이프라인 배포와 동일 조건).

⚠️ **compose SoT 는 팀 확정 대상**(CLAUDE.md `미정`). 이 디렉토리는 그 후보 구현.
