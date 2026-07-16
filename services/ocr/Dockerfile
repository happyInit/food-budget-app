# 영수증 OCR 서비스 이미지 (독립 — 챗봇과 달리 pipelines/ 의존 없음).
# 빌드 컨텍스트 = services/ocr (자기완결). 예: docker build -t ocr-service services/ocr
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app

# 포트는 배포가 결정(12-factor) — 앱은 $PORT를 읽고 기본 8010.
# 배포자가 `-e PORT=<원하는포트>` 또는 `-p <외부>:8010`(매핑)로 override → 앱 코드 불변.
# (챗봇 8001↔8003 mismatch 재발 방지 — 포트를 코드에 박지 않음.)
ENV PORT=8010
EXPOSE 8010
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
