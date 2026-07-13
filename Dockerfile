# food-budget 수집 파이프라인 이미지 (컨슈머·오아시스 크롤러·레시피 프로듀서·pruner 공용).
# Kafka/PG/Redis는 이미지 밖(fb-data VM 도커). 설정은 전부 env(compose env_file).
# ⚠ 컬리 크롤러(Playwright)는 브라우저 필요 → 별도 이미지. 이 이미지엔 미포함.
FROM python:3.12-slim
WORKDIR /app

# 전부 wheel 제공(빌드툴 불필요): psycopg[binary]=libpq · confluent-kafka=librdkafka · lxml
RUN pip install --no-cache-dir \
    "psycopg[binary]>=3.2,<4" "python-dotenv>=1.0" "requests>=2.31" \
    "confluent-kafka>=2.5" "redis>=5.0" "beautifulsoup4>=4.12" "lxml>=5.0"

COPY pipelines/ ./pipelines/
COPY crawler/ ./crawler/

# 각 컴포넌트는 compose의 command로 지정 (consume_retail / consume_deal / … / prune_deals).
CMD ["python", "-c", "print('food-budget-pipeline: compose command로 컴포넌트 지정')"]
