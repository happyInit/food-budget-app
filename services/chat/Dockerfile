# 빌드 컨텍스트 = 레포 루트 (ci-sample과 다른 지점 — gazetteer.py/_db.py를
# pipelines/ingest/에서 끌어와야 해서). docker build -f services/chat/Dockerfile .
FROM python:3.12-slim
WORKDIR /app
COPY services/chat/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# app/vendor/{gazetteer,_db}.py는 로컬 개발에선 심볼릭 링크(레포 안 단일 정본).
# 이미지 안에서는 심볼릭 링크가 아니라 실제 파일로 덮어써서 넣는다(드리프트 없음 — 소스는 한 곳뿐).
COPY services/chat/app app
COPY pipelines/ingest/gazetteer.py app/vendor/gazetteer.py
COPY pipelines/ingest/_db.py app/vendor/_db.py
COPY pipelines/ingest/quantity.py app/vendor/quantity.py
EXPOSE 8003
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
