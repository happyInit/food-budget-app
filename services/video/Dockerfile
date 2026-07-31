# 영상→레시피 추출 서비스 이미지.
# ⚠️ 빌드 컨텍스트 = **레포 루트**(ml/video-recipe 라이브러리를 함께 넣어야 함).
#    예: docker build -f services/video/Dockerfile -t video-service .
# Dockerfile 보안 공통 명세서 §3.1 — 비루트(uid/gid 10001).
FROM python:3.12-slim

RUN groupadd --gid 10001 svc \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin svc

WORKDIR /app
COPY services/video/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/video/app app
# 추출·검증 로직 원본(복제하지 않고 그대로 싣는다 — 로직 이중화 금지)
COPY ml/video-recipe /opt/video-recipe
ENV VIDEO_LIB_PATH=/opt/video-recipe

# 포트는 배포가 결정(12-factor) — 앱은 $PORT를 읽고 기본 8011.
ENV PORT=8011
USER 10001:10001
EXPOSE 8011
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
