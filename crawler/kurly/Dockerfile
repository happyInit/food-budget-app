# 컬리 크롤러 이미지 (Playwright + chromium 포함) — 메인 이미지와 별도.
# ⚠ 베이스 이미지 태그(vX.Y.Z) == pip playwright 버전. 둘이 어긋나면 브라우저 바이너리가 없어
#   런타임에만 터진다(빌드·--help 는 통과) → 폴러가 매일 조용히 실패. 실장애 발생분:
#   base v1.47 + playwright-stealth 무핀(">=1.0" → 2.x 가 playwright 1.61 견인) = chromium 경로 불일치.
#   버전 올릴 땐 FROM 태그와 아래 pin 을 항상 같이 바꿀 것.
FROM mcr.microsoft.com/playwright/python:v1.61.0-jammy
WORKDIR /app

# boto3 = C-44 의 S3 업로드(--s3). 🔴 메인 이미지엔 pipelines/ingest/requirements.txt 로 이미
#   들어 있지만 **이 이미지는 별개**라 여기 없으면 03:30 런타임에만 터진다(위 함정들과 같은 양식).
#   하한은 pipelines/ingest/requirements.txt 와 맞춘다.
RUN pip install --no-cache-dir \
      "playwright==1.61.0" \
      "playwright-stealth==2.0.3" \
      "confluent-kafka>=2.5" \
      "boto3>=1.35"

# 버전 드리프트 조기경보 — 설치된 playwright 가 베이스의 chromium 을 실제로 띄우는지 빌드 시점에 확인.
# (드리프트는 런타임에만 드러나므로 여기서 막지 않으면 깨진 이미지가 그대로 Harbor 로 올라간다)
RUN python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop(); print('chromium launch OK')"

COPY crawler/kurly/ ./crawler/kurly/
COPY pipelines/stream/_kafka.py ./pipelines/stream/_kafka.py
COPY pipelines/stream/_topics.py ./pipelines/stream/_topics.py
COPY pipelines/stream/_observability.py ./pipelines/stream/_observability.py
# _delivery = Kafka 전달 실패 판정(#558). prototype 이 **모듈 최상단에서** 임포트하므로
# 빠지면 --help 조차 안 뜬다(= 매일 03:30 전멸). 아래 임포트 검사가 그걸 빌드 시점에 잡는다.
COPY pipelines/stream/_delivery.py ./pipelines/stream/_delivery.py
# _s3 = C-44 업로드 싱크. prototype 은 이걸 **--s3 일 때만 지연 임포트**하므로 빠져도 --help 는
# 통과한다 — 즉 빌드가 아니라 03:30 업로드 순간에만 터진다. 아래 임포트 검사가 그걸 앞당겨 잡는다.
COPY pipelines/transport/_s3.py ./pipelines/transport/_s3.py

# 임포트 드리프트 조기경보 — 선택 COPY 라 _kafka 의 의존이 늘면 런타임(매일 03:30)에만 터진다.
# 위 chromium 검사와 같은 취지로 빌드 시점에 잡는다. 실장애 발생분: _topics 분리(834244c) 미반영
# → 03:30 컬리 폴러 ModuleNotFoundError 전멸.
# 🔴 _kafka 만 보면 부족하다 — prototype 자신의 임포트가 늘어난 경우(_delivery)를 못 잡는다.
#    그래서 크롤러 모듈 자체를 임포트해 본다(playwright 는 이 이미지에 실제로 들어 있다).
RUN python -c "import sys; sys.path.insert(0, '/app/pipelines/stream'); import _kafka; print('kafka sink import OK')"
RUN python -c "import sys; sys.path.insert(0, '/app/crawler/kurly'); import prototype; print('crawler import OK')"
# 🔴 지연 임포트라 위 검사에 안 잡힌다 — boto3 까지 실제로 끌어와 본다(업로드 경로의 유일한 사전 검증).
RUN python -c "import sys; sys.path.insert(0, '/app/pipelines/transport'); import _s3, boto3; print('s3 sink import OK', boto3.__version__)"

# 🔴 비루트 실행 (SonarQube S6471). 이 베이스는 기본 USER 가 **root** 다
#    (실측: mcr playwright 이미지의 Config.User 가 비어 있음). K8s CronJob(mp-poller-kurly)에는
#    caps drop ALL·allowPrivilegeEscalation=false 까지만 걸려 있고 runAsUser 가 없어서,
#    지금 파드는 실제로 uid 0 으로 돈다.
#    pwuser(1000)는 베이스가 이미 만들어 두는 계정이고 /ms-playwright 는 0777 이라 chromium
#    기동에 지장이 없다. 위 빌드시점 검증 RUN 들은 root 로 이미 끝난 뒤다.
#    /app 소유권을 넘기는 이유: 운영 경로(CMD --kafka)는 파일을 안 쓰지만
#    (prototype.py: write_file = bool(out) or not kafka), --kafka 없이 수동 실행하면
#    crawler/kurly/output/ 을 만든다. 그 경로도 비루트로 돌 수 있게 해 둔다.
RUN chown -R 1000:1000 /app
USER 1000:1000

# --kafka: 크롤하며 retail.crawl.raw로 직접 produce. 설정은 env(KAFKA_BOOTSTRAP).
CMD ["python", "crawler/kurly/prototype.py", "--kafka"]
