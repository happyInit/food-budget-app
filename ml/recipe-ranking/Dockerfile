# P1 개인화 랭킹 ML 서빙 (serve.py, SERVING.md §2). 빌드 컨텍스트 = ml/recipe-ranking.
#   mealplan이 /rank/personalize 호출 → 규칙 랭킹 위 개인화 재정렬. 모델 없으면 폴백(규칙순).
FROM python:3.12-slim
WORKDIR /app
# lightgbm 런타임 의존 — python:slim 엔 OpenMP 런타임(libgomp)이 없어 `import lightgbm` 이
#   `OSError: libgomp.so.1: cannot open shared object file` 로 실패한다(정식 LambdaMART 불가).
#   serve.py(LGBMRanker 언피클)·retrain.py(학습) 양쪽에 필요.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8009
CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8009"]
