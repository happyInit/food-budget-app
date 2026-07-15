# Dockerfile 보안 공통 명세서 준수:
#   §3.1 비루트 사용자 · §3.2 핀 베이스(latest 금지) · §3.3 시크릿 미포함(.dockerignore + .env COPY 안 함)
#   §3.4 캐시 제거(--no-cache-dir; psycopg[binary]=휠이라 빌드도구 잔존 없음 → Multi-stage 생략 가능)
#   §3.5 의존성 lock(requirements.txt 버전 고정) · §3.6 코드 read-only(비루트가 소유 아님)
# vendor 심링크 없음 → 빌드 컨텍스트 = 이 디렉터리(chat과 달리 repo root 불요).
FROM python:3.12-slim

# §3.1 전용 비루트 사용자(uid/gid 10001) — 최종 프로세스가 UID 0 이 아니도록.
RUN groupadd --gid 10001 svc \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin svc

WORKDIR /svc
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

USER 10001:10001
EXPOSE 8005
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
