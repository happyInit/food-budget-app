# 빌드 컨텍스트 = 레포 루트 (chat 과 동일 — quantity.py 를 pipelines/ingest/ 에서 COPY).
# docker build -f services/recipe/Dockerfile .
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY services/recipe/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/recipe/app app
# app/vendor/quantity.py 는 로컬 개발에선 심볼릭 링크(정본=pipelines/ingest). 이미지엔 실제 파일로 덮어씀(드리프트 없음).
COPY pipelines/ingest/quantity.py app/vendor/quantity.py

EXPOSE 8001
CMD ["opentelemetry-instrument", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
