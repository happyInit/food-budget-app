# 컬리 크롤러 이미지 (Playwright + chromium 포함) — 메인 이미지와 별도.
# ⚠ Playwright 버전은 prototype이 기대하는 것과 맞출 것(playwright-stealth 호환). 태그 확인 후 조정.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy
WORKDIR /app

RUN pip install --no-cache-dir "playwright-stealth>=1.0" "confluent-kafka>=2.5"

COPY crawler/kurly/ ./crawler/kurly/
COPY pipelines/stream/_kafka.py ./pipelines/stream/_kafka.py
COPY pipelines/stream/_observability.py ./pipelines/stream/_observability.py

# --kafka: 크롤하며 retail.crawl.raw로 직접 produce. 설정은 env(KAFKA_BOOTSTRAP).
CMD ["python", "crawler/kurly/prototype.py", "--kafka"]
