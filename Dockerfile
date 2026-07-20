# food-budget 수집 파이프라인 이미지 (컨슈머·오아시스 크롤러·레시피 프로듀서·pruner 공용).
# Kafka/PG/Redis는 이미지 밖(fb-data VM 도커). 설정은 전부 env(compose env_file).
# ⚠ 컬리 크롤러(Playwright)는 브라우저 필요 → 별도 이미지. 이 이미지엔 미포함.
# 싱글스테이지 의도 — 전부 wheel(psycopg[binary]=libpq·confluent-kafka=librdkafka·lxml)이라
# 컴파일러/빌드툴이 없어 버릴 builder 스테이지가 없음(AGENTS.md 멀티스테이지 관례의 대상 아님).
FROM python:3.12-slim
WORKDIR /app

# 의존성 = 각 컴포넌트 requirements.txt 단일 정본(인라인 재선언 제거 → 버전 드리프트 방지).
# 코드보다 먼저 COPY → requirements 안 바뀌면 이 레이어 캐시 재사용.
COPY pipelines/stream/requirements.txt  /tmp/req/stream.txt
COPY crawler/oasis/requirements.txt     /tmp/req/oasis.txt
COPY pipelines/ingest/requirements.txt  /tmp/req/ingest.txt
RUN pip install --no-cache-dir \
    -r /tmp/req/stream.txt -r /tmp/req/oasis.txt -r /tmp/req/ingest.txt

COPY pipelines/ ./pipelines/
COPY crawler/ ./crawler/
# 대화분석 배치(리포트·선호·의도) — psycopg만으로 코어 동작(intent/LLM은 dep 있을 때만).
# ⚠️ 주석은 반드시 자체 줄에 — COPY 뒤 인라인 주석은 Docker가 소스 인자로 오인해 빌드 실패.
COPY ml/chat-insights/ ./ml/chat-insights/

# 각 컴포넌트는 compose의 command로 지정 (consume_retail / consume_deal / … / prune_deals).
CMD ["python", "-c", "print('food-budget-pipeline: compose command로 컴포넌트 지정')"]
