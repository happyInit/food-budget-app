#!/usr/bin/env bash
# food-budget 이미지 → Harbor 푸시. docker 있는 호스트(fb-data VM 등)에서 repo 루트에서 실행.
#   bash deploy/push.sh
# 필수 env: HARBOR_REGISTRY (예: harbor.example.com[:443])  ·  HARBOR_PROJECT (예: food-budget)
# 선택 env: IMAGE_TAG (기본 latest)
set -euo pipefail

: "${HARBOR_REGISTRY:?HARBOR_REGISTRY 필요 — 예: export HARBOR_REGISTRY=harbor.mycompany.com}"
: "${HARBOR_PROJECT:?HARBOR_PROJECT 필요 — 예: export HARBOR_PROJECT=food-budget}"
TAG="${IMAGE_TAG:-latest}"
BASE="${HARBOR_REGISTRY}/${HARBOR_PROJECT}"
PIPELINE="${BASE}/food-budget-pipeline:${TAG}"
KURLY="${BASE}/food-budget-crawler-kurly:${TAG}"

echo "== docker login ${HARBOR_REGISTRY} (Harbor 계정/로봇계정) =="
docker login "${HARBOR_REGISTRY}"

echo "== build + push: ${PIPELINE} =="
docker build -t "${PIPELINE}" -f Dockerfile .
docker push "${PIPELINE}"

echo "== build + push: ${KURLY} (Playwright) =="
docker build -t "${KURLY}" -f crawler/kurly/Dockerfile .
docker push "${KURLY}"

echo
echo "완료:"
echo "  ${PIPELINE}"
echo "  ${KURLY}"
echo "compose 사용: PIPELINE_IMAGE=${PIPELINE} KURLY_IMAGE=${KURLY} docker compose up -d"
