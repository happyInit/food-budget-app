# mp-ai-rank-serve — **Lambda 컨테이너 이미지**. 빌드 컨텍스트 = 레포 루트.
#
# 🔴 11종 중 여기만 컨테이너인 이유 = `libgomp.so.1`(OpenMP 런타임)이 **OS 패키지**라
#    zip 번들에 넣을 자리가 없다. 없으면 `import lightgbm` 이 그 자리에서 죽는다.
#    (`ml/recipe-ranking/Dockerfile` 이 같은 이유로 `libgomp1` 을 깐다 — apt/dnf 이름이 다르다.)
#
# 🔴 **arm64 로 굽는다**(C-29 Graviton). 빌드 기계가 x86 이면 `--platform linux/arm64` 를
#    반드시 주어야 한다 — 안 주면 이미지는 만들어지고 **첫 호출에서** exec format error 다.
#      docker build --platform linux/arm64 -f serverless/ai_rank_serve/Dockerfile -t <tag> .
#
# 🔵 컨테이너라서 좋은 점 하나 = **의존성 «마커 함정» 이 없다.** zip 은 호스트에서
#    `pip download --platform` 으로 받느라 환경 마커가 빌드 기계 인터프리터로 평가돼
#    py3.12 전용 의존성이 조용히 빠졌다(2026-08-14 `typing-extensions`). 여기서는 목표
#    이미지 **안에서** 설치하므로 그 문제가 생기지 않는다 — 그래서 락이 아니라 범위 핀이다.
FROM public.ecr.aws/lambda/python:3.12-arm64

# AL2023 기반이라 apt 가 아니라 dnf 다. `libgomp` (뒤에 1 이 안 붙는다 — 데비안과 이름이 다르다)
RUN dnf install -y libgomp && dnf clean all && rm -rf /var/cache/dnf

COPY serverless/ai_rank_serve/requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# 서빙 로직 정본은 그대로 쓴다 — 분할은 «부르는 방법» 만 바꾸는 것이다.
COPY ml/recipe-ranking/serve.py     ${LAMBDA_TASK_ROOT}/
COPY ml/recipe-ranking/features.py  ${LAMBDA_TASK_ROOT}/
COPY serverless/common              ${LAMBDA_TASK_ROOT}/common/
COPY serverless/ai_rank_serve/app.py ${LAMBDA_TASK_ROOT}/

# 🔴 **모델을 이미지에 굽는다 (C-20).** CI 가 빌드 직전에 S3(`mp-ai-model-ap2`)에서
#    받아 이 자리에 둔다. 파드 쪽(`services/ranking-serving`)과 **같은 방식**이다.
#    ⚠️ 없어도 빌드는 성공하고 서비스도 200 을 준다(규칙순 폴백). 그래서 배선 사고가
#       조용하다 — 배포 후 `/health` 의 `model_loaded` 를 반드시 확인할 것.
COPY ranker.pkl ${LAMBDA_TASK_ROOT}/ranker.pkl
ENV RANKING_MODEL_PATH=${LAMBDA_TASK_ROOT}/ranker.pkl

CMD ["app.handler"]
