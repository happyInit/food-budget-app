# P1 개인화 랭킹 ML 서빙 (serve.py, SERVING.md §2). 빌드 컨텍스트 = ml/recipe-ranking.
#   mealplan이 /rank/personalize 호출 → 규칙 랭킹 위 개인화 재정렬. 모델 없으면 폴백(규칙순).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8009
CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8009"]
