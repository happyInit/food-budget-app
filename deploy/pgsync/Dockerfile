# amd64 PGSync 이미지 — 공식 toluaina1/pgsync 는 arm64 전용이라 x86_64(.8)에서 못 씀 → 자체 빌드.
# PGSync 7.1.0 = PyPI 최신. 의존이 psycopg2-binary(휠 번들) → gcc/libpq-dev 등 빌드툴 불필요.
FROM python:3.12-slim

RUN pip install --no-cache-dir pgsync==7.1.0

# 플러그인 로딩: PGSync 는 'plugins' 패키지를 walk → /app 을 PYTHONPATH 에 둬야
# 런타임 마운트된 /app/plugins(=`plugins` 패키지)를 import 할 수 있다.
WORKDIR /app
ENV PYTHONPATH=/app

# schema.json · plugins/ 는 compose 볼륨으로 /app 에 마운트(이미지에 COPY 안 함).
ENTRYPOINT ["pgsync"]
