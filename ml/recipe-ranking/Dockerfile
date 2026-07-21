# P1 개인화 랭킹 ML 서빙 (serve.py, SERVING.md §2). 빌드 컨텍스트 = ml/recipe-ranking.
#   mealplan이 /rank/personalize 호출 → 규칙 랭킹 위 개인화 재정렬. 모델 없으면 폴백(규칙순).
# Dockerfile 보안 공통 명세서 §3.1 — 비루트 사용자(uid/gid 10001, pantry와 동일 패턴).
FROM python:3.12-slim

RUN groupadd --gid 10001 svc \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin svc

WORKDIR /app
# lightgbm 런타임 의존 — python:slim 엔 OpenMP 런타임(libgomp)이 없어 `import lightgbm` 이
#   `OSError: libgomp.so.1: cannot open shared object file` 로 실패한다(정식 LambdaMART 불가).
#   serve.py(LGBMRanker 언피클)·retrain.py(학습) 양쪽에 필요.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# retrain.py가 RANKING_MODEL_PATH(기본 /models/ranker.pkl)에 모델을 저장 —
# 이 디렉토리를 미리 만들고 소유권을 넘겨둬야, 여기 마운트되는 빈 named volume이
# 처음 생성될 때 이 소유권을 그대로 물려받아 비루트로도 쓰기 가능해짐.
RUN mkdir -p /models && chown 10001:10001 /models

USER 10001:10001
EXPOSE 8009
CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8009"]
