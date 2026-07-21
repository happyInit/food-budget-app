# 빌드 컨텍스트 = 레포 루트 (chat 과 동일 — quantity.py 를 pipelines/ingest/ 에서 COPY).
# docker build -f services/recipe/Dockerfile .
# Dockerfile 보안 공통 명세서 §3.1 — 비루트 사용자(uid/gid 10001, pantry와 동일 패턴).
FROM python:3.12-slim

RUN groupadd --gid 10001 svc \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin svc

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY services/recipe/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/recipe/app app
# app/vendor/quantity.py 는 로컬 개발에선 심볼릭 링크(정본=pipelines/ingest). 이미지엔 실제 파일로 덮어씀(드리프트 없음).
COPY pipelines/ingest/quantity.py app/vendor/quantity.py

USER 10001:10001
EXPOSE 8001
CMD ["opentelemetry-instrument", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
