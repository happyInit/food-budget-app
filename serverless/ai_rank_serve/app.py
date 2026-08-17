"""`mp-ai-rank-serve` 의 Lambda 진입점 — 개인화 재랭킹.

🔴 **11종 중 유일하게 zip 이 아니라 «컨테이너 이미지» 다.** 이유는 하나뿐이다:

    lightgbm 은 OpenMP 런타임(`libgomp.so.1`)을 필요로 하는데, 그건 **파이썬 휠이 아니라
    OS 패키지**다. zip 번들에는 OS 패키지를 넣을 자리가 없다. 넣지 않으면
    `import lightgbm` 이 `OSError: libgomp.so.1: cannot open shared object file` 로 죽는다.

   ⚠️ *"그럼 lightgbm 을 빼고 sklearn 폴백만 쓰면 zip 으로 되지 않나"* — 된다. 하지만 그러면
      **정식 LambdaMART 랭커를 못 쓴다**(폴백은 GradientBoosting 이다). 모델 품질을 배포
      방식 때문에 떨어뜨리는 선택이라, 컨테이너 쪽이 맞다.

🔵 **컨테이너로 가면 «마커 함정» 이 사라진다.** zip 은 호스트에서 `pip download --platform`
   으로 받느라 환경 마커가 빌드 기계의 인터프리터로 평가돼 의존성이 조용히 빠졌다
   (2026-08-14 `typing-extensions`). 컨테이너는 **목표 이미지 안에서** 설치하므로 그 문제가
   원천적으로 없다. 그래서 여기 requirements 는 락 파일이 아니라 **범위 핀**이다.

🔴 **모델은 이미지에 굽는다 (C-20).** PVC 를 안 쓴다 — EKS 에서 그 볼륨을 없앴다.
   경로는 `RANKING_MODEL_PATH=/var/task/ranker.pkl`. 🔵 로드는 **모듈 import 시점**에
   `serve.py` 의 `_init_from_env()` 가 한다 = Lambda INIT 에서 끝난다(warm 호출은 0 비용).
   🔴 그리고 **로드 실패는 치명적이 아니다** — 규칙순 폴백으로 계속 서빙한다.
      즉 *"이미지 배선이 틀려도 응답은 200"* 이므로 **`/health` 의 `model_loaded` 를 봐야**
      배선 사고를 알 수 있다(체크리스트 1-21 이 지적한 그 자리다).

🔴 **VPC 안에서만 돈다.** `pg_feature_provider` 가 PG 를 친다 — chat 과 같은 선행 조건
   (NodePort + 노드 사설 IP)이 필요하다. 그때 바뀌는 것은 환경변수뿐이다.

🔵 진입점 이름이 `app.py` 인 것은 여기엔 `app/` **패키지가 없기** 때문이다(`serve.py` 평면).
   chat·ocr-worker 가 `handler.py` 인 것과 갈리는 지점 — `serverless/README.md` 의 표 참조.

경로: `POST /rank/personalize` (mealplan 이 호출) · `GET /health` · `POST /reload`
"""
from __future__ import annotations

import sys
from pathlib import Path

# 컨테이너에서는 `/var/task` 하나에 다 들어간다. 레포에서 돌릴 때만 ml 트리를 더한다.
_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[1], _HERE.parents[2] / "ml" / "recipe-ranking"):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mangum import Mangum  # noqa: E402

from common.runtime import log_start, logger  # noqa: E402

FUNCTION = "mp-ai-rank-serve"
log = logger(FUNCTION)

# 🔴 import 가 곧 모델 로드다(`serve.py` 하단의 `_init_from_env()`). INIT 에서 끝내려고
#    핸들러 밖에 둔다 — 안으로 미루면 **매 요청이 pickle 을 다시 읽는다.**
from serve import app  # noqa: E402

# 🔴 `lifespan="off"` — `serve.py` 에는 lifespan 이 없지만(startup 이 import 시점이다),
#    auto 로 두면 Mangum 이 **invoke 마다** LifespanCycle 을 열고 닫으며 그만큼 낭비한다.
#    chat 처럼 «닫으면 안 되는 자원» 이 걸린 건 아니지만, 켤 이유가 없다.
_asgi = Mangum(app, lifespan="off")


def handler(event, context):
    """ALB 가 부른다. 요청 번역·응답 직렬화는 어댑터가 한다."""
    log_start(log, FUNCTION,
              {"path": event.get("path"), "method": event.get("httpMethod")}, context)
    return _asgi(event, context)
