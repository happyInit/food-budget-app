# 컬리 크롤러 이미지 (Playwright + chromium 포함) — 메인 이미지와 별도.
# ⚠ 베이스 이미지 태그(vX.Y.Z) == pip playwright 버전. 둘이 어긋나면 브라우저 바이너리가 없어
#   런타임에만 터진다(빌드·--help 는 통과) → 폴러가 매일 조용히 실패. 실장애 발생분:
#   base v1.47 + playwright-stealth 무핀(">=1.0" → 2.x 가 playwright 1.61 견인) = chromium 경로 불일치.
#   버전 올릴 땐 FROM 태그와 아래 pin 을 항상 같이 바꿀 것.
FROM mcr.microsoft.com/playwright/python:v1.61.0-jammy
WORKDIR /app

RUN pip install --no-cache-dir \
      "playwright==1.61.0" \
      "playwright-stealth==2.0.3" \
      "confluent-kafka>=2.5"

# 버전 드리프트 조기경보 — 설치된 playwright 가 베이스의 chromium 을 실제로 띄우는지 빌드 시점에 확인.
# (드리프트는 런타임에만 드러나므로 여기서 막지 않으면 깨진 이미지가 그대로 Harbor 로 올라간다)
RUN python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop(); print('chromium launch OK')"

COPY crawler/kurly/ ./crawler/kurly/
COPY pipelines/stream/_kafka.py ./pipelines/stream/_kafka.py
COPY pipelines/stream/_topics.py ./pipelines/stream/_topics.py
COPY pipelines/stream/_observability.py ./pipelines/stream/_observability.py

# 임포트 드리프트 조기경보 — 선택 COPY 라 _kafka 의 의존이 늘면 런타임(매일 03:30)에만 터진다.
# 위 chromium 검사와 같은 취지로 빌드 시점에 잡는다. 실장애 발생분: _topics 분리(834244c) 미반영
# → 03:30 컬리 폴러 ModuleNotFoundError 전멸.
RUN python -c "import sys; sys.path.insert(0, '/app/pipelines/stream'); import _kafka; print('kafka sink import OK')"

# --kafka: 크롤하며 retail.crawl.raw로 직접 produce. 설정은 env(KAFKA_BOOTSTRAP).
CMD ["python", "crawler/kurly/prototype.py", "--kafka"]
