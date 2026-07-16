#!/usr/bin/env bash
# food-budget 이미지 → Harbor 푸시. docker 있는 호스트(fb-data VM 등)에서 repo 루트에서 실행.
#   docker login 192.168.0.10  &&  bash deploy/push.sh
# 기본값 = fb Harbor(192.168.0.10) / food-budget 프로젝트. env로 오버라이드 가능. TAG 기본 1.1.1(릴리스 핀).
# ⚠ Harbor가 self-signed HTTPS → docker daemon.json에 "insecure-registries":["192.168.0.10"] 필요
#    (또는 Harbor CA를 /etc/docker/certs.d/192.168.0.10/ca.crt 로 신뢰).
set -euo pipefail

HARBOR_REGISTRY="${HARBOR_REGISTRY:-192.168.0.10}"
HARBOR_PROJECT="${HARBOR_PROJECT:-food-budget}"
TAG="${IMAGE_TAG:-1.1.1}"   # 기본=릴리스 핀(app 과 동일). 임시 태그는 IMAGE_TAG=latest 등으로 오버라이드.
BASE="${HARBOR_REGISTRY}/${HARBOR_PROJECT}"
PIPELINE="${BASE}/data-pipeline:${TAG}"
KURLY="${BASE}/crawler-kurly:${TAG}"

echo "== docker login ${HARBOR_REGISTRY} (Harbor db_auth 계정) — 로그인 안 돼있으면 =="
docker login "${HARBOR_REGISTRY}" || true

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
echo "compose 사용: IMAGE_TAG=${TAG} docker compose up -d   # (registry/project 는 compose 에 baked — app 과 동일)"
