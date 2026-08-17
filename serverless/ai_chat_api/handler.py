"""`mp-ai-chat-api` 의 Lambda 진입점 — 챗봇 동기 응답.

🔴 **파일 이름이 `app.py` 가 아닌 이유 = 이름 충돌이다.**
   다른 함수 7종은 진입점이 `app.py` 지만 chat 은 그럴 수 없다. 번들 루트에
   `services/chat/app` 이 **`app/` 패키지로** 들어가는데, 같은 자리에 `app.py` 를 두면
   `import app` 이 **패키지 쪽을 집는다**(실측: 둘 다 두고 import → 패키지가 이겼다).
   그러면 Lambda 핸들러 문자열 `app.handler` 가 «패키지 app 에 handler 가 없다» 로 죽는다.
   ⇒ 진입점은 `handler.py`, **Lambda 핸들러 문자열은 `handler.handler`** 다.
   ⚠️ 패키지 구조인 서비스(chat·ocr)는 전부 이 규칙을 따른다. 평면 함수(batch 5·video 2)는
      `app.handler` 그대로다 — 그쪽엔 `app/` 패키지가 안 들어가므로 충돌이 없다.

🔴 **왜 여기만 ASGI 어댑터(Mangum)를 쓰나 — `video-api` 와 무엇이 다른가.**
   `video-api` 는 경로가 2개(접수·폴링)뿐이라 손으로 짜는 편이 가벼웠다(프레임워크 import 를
   콜드스타트에서 뺐다). chat 은 다르다 — `_handle_chat` 하나가 **320줄**이고 그 안에
   멀티턴 승계 · recipe-focus · recipe_cost 재료 주입 · 제외재료 세션화가 얽혀 있다.
   손으로 옮기면 **그 320줄을 복제**하게 되고, 두 벌이 갈리는 순간 챗봇 동작이 사이트마다
   달라진다. ⇒ 앱을 **통째로 재사용**한다. 어댑터 한 줄이 복제보다 싸다.

🔴 **`lifespan="off"` 다. 이게 이 파일에서 제일 중요한 한 글자다.**
   Mangum 은 `lifespan` 이 auto/on 이면 **호출마다** `LifespanCycle` 을 열고 닫는다
   (adapter.py `__call__` — 매 invoke 마다 startup → shutdown). 그런데 chat 의 lifespan
   **shutdown 은 PG 풀·ES·Redis 를 전부 닫는다**(main.py `finally`). 즉 auto 로 두면
   **매 요청이** 풀을 새로 열고 **gazetteer 를 DB 에서 통째로 다시 읽고** 다 닫는다.
   🔵 off 로 둬도 안전한 이유 = `_handle_chat` 의 **첫 줄이 `_ensure_ready()`** 다.
      준비가 안 됐으면 그 자리에서 1회 초기화하고 결과를 모듈 전역 `state` 에 캐시한다.
      warm 컨테이너에서는 그 `state` 가 그대로 살아 있어 두 번째 요청부터 초기화가 없다.
   🔵 이벤트 루프도 **컨테이너당 하나**로 유지된다 — Mangum 은 `__init__` 에서
      루프가 없을 때만 새로 만들고(`_setup_event_loop`), 이후 `get_event_loop()` 로 **재사용**한다.
      이게 아니었다면 캐시된 async 풀이 «다른 루프에 붙었다» 로 깨졌을 것이다.

🔴 **VPC 안에서만 돈다.** chat 은 PG(Pooler)·ES·Valkey 에 붙는데 앞의 둘이 **K8s 내부 DNS**
   (`pg-pooler.data.svc`·`es-es-http.data.svc`)다. Lambda 는 그 이름을 해석하지 못한다.
   ⇒ 배포 전에 **NodePort + 노드 사설 IP** 배선이 선행이다(설계서 §제약1 ADR). 그때
   `PGHOST`·`ESHOST` 환경변수만 바꾸면 되고 **이 파일은 안 바뀐다.**

🔵 **콜드스타트가 이 함수의 진짜 비용이다.** `_init_pipeline` 이 풀을 열고 gazetteer 를
   DB 에서 전량 로드한다. 그건 위 설계상 **첫 요청**에서 일어난다(INIT 이 아니라).
   계약표의 타임아웃이 «재산정» 인 이유가 이것 — 실측 없이 숫자를 못 적는다.

경로: `POST /api/mealplan/assistant/chat` (ALB → Lambda 타겟 · 기존 `mp-chat-route` 승계)
"""
from __future__ import annotations

import sys
from pathlib import Path

# 번들 루트 = import 루트. build.sh 가 `services/chat/app` 을 `app/` 로 통째로 넣는다.
# 레포에서 직접 돌릴 때(테스트)는 `services/chat` 도 봐야 `app.main` 이 잡힌다.
_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[1], _HERE.parents[2] / "services" / "chat"):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mangum import Mangum  # noqa: E402

from common.runtime import log_start, logger  # noqa: E402

FUNCTION = "mp-ai-chat-api"
log = logger(FUNCTION)

# 🔴 **import 시점에 앱을 만든다 — 의도다.** Lambda 는 이 모듈 import 까지가 INIT 이고,
#    거기서 끝낼 수 있는 준비(라우트 등록·계측 부착)는 끝내야 warm 호출이 빨라진다.
from app.main import app  # noqa: E402

_asgi = Mangum(app, lifespan="off")


def handler(event, context):
    """ALB 가 부른다. 요청 번역·응답 직렬화는 어댑터가 한다.

    🔴 ALB 이벤트인지의 판정은 Mangum 이 `requestContext.elb` 로 한다. 그 키가 없으면
       «핸들러를 못 고르겠다» 로 죽는다 — 콘솔 Test 버튼의 기본 payload 로는 재현이 안 된다.
       로컬 확인은 `serverless/tests/` 의 ALB 이벤트 픽스처를 쓸 것.
    """
    log_start(log, FUNCTION,
              {"path": event.get("path"), "method": event.get("httpMethod")}, context)
    return _asgi(event, context)
