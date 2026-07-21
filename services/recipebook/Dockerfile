# vendor 심링크 없음 → 빌드 컨텍스트 = 이 디렉터리(account와 동일).
# Dockerfile 보안 공통 명세서 §3.1 — 비루트 사용자(uid/gid 10001, pantry와 동일 패턴).
FROM python:3.12-slim

RUN groupadd --gid 10001 svc \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin svc

WORKDIR /svc
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

USER 10001:10001
EXPOSE 8006
CMD ["opentelemetry-instrument", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"]
