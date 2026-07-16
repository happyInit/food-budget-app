# vendor 심링크 없음 → 빌드 컨텍스트 = 이 디렉터리(account와 동일).
FROM python:3.12-slim
WORKDIR /svc
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8007
CMD ["opentelemetry-instrument", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8007"]
