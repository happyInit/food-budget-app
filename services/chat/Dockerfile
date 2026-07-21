# 빌드 컨텍스트 = 레포 루트 (ci-sample과 다른 지점 — gazetteer.py/_db.py를
# pipelines/ingest/에서 끌어와야 해서). docker build -f services/chat/Dockerfile .
# Dockerfile 보안 공통 명세서 §3.1 — 비루트 사용자(uid/gid 10001, pantry와 동일 패턴).
FROM python:3.12-slim

RUN groupadd --gid 10001 svc \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin svc

WORKDIR /app
COPY services/chat/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# app/vendor/{gazetteer,_db}.py는 로컬 개발에선 심볼릭 링크(레포 안 단일 정본).
# 이미지 안에서는 심볼릭 링크가 아니라 실제 파일로 덮어써서 넣는다(드리프트 없음 — 소스는 한 곳뿐).
COPY services/chat/app app
COPY pipelines/ingest/gazetteer.py app/vendor/gazetteer.py
COPY pipelines/ingest/_db.py app/vendor/_db.py
COPY pipelines/ingest/quantity.py app/vendor/quantity.py

USER 10001:10001
EXPOSE 8003
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
