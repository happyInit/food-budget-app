# mp-rollouts-gatewayapi-plugin — Argo Rollouts Gateway API 트래픽라우터 플러그인 vendoring (ADR-0001 §6.2)
#
# 왜 이 이미지가 필요한가: Rollouts 컨트롤러는 트래픽라우터 플러그인 바이너리가 없으면 **기동하지 않는다**.
#   기본 배선(`location: https://…`)이면 HA 각 pod 가 재기동마다(노드 드레인·페일오버·OOM·차트 업그레이드)
#   GitHub 에서 재다운로드한다 → GitHub blip/rate-limit 시 배포를 게이팅하는 컨트롤러가 안 뜬다.
#   = **장애 중 픽스를 배포하려는 바로 그 순간 배포 게이트가 죽는다.**
#   vendoring 은 그 의존을 **이미 모든 배포의 하드 의존인 Harbor 로** 옮긴다(새 실패 도메인 0개).
#
# 🔴 런타임 hermetic — GitHub fetch 는 **빌드타임 1회**뿐이다. 클러스터는 Harbor 만 본다.
#
# 🔴 sha256 은 **여기서만** 검증된다. 컨트롤러의 sha256 체크는 http(s) 분기 안에만 있고
#    file:// 분기엔 없다(argo-rollouts v1.9.1 `utils/plugin/downloader.go` — file 분기는
#    copyFile + chmod 만 한다). 즉 vendoring 경로에서 이 `sha256sum -c` 가 **유일한 무결성 게이트**다.
#    지우면 무결성 검증이 0이 된다 — 지우지 말 것.
#
# 태깅(infra 트랙 — elasticsearch-nori 와 같은 관례): 우리 코드가 0줄인 재패키징이라 릴리스 버전
#   자리에 **업스트림 플러그인 버전**을 그대로 쓴다(0.16.0). 같은 버전 재빌드는 `-rN` 리비전.
#   config 레포 핀은 정책대로 `:sha`(CLAUDE.md — `:latest` 금지, ArgoCD 감지·롤백 불가).
#
# 🔴 PLUGIN_VERSION 과 PLUGIN_SHA256 은 반드시 같이 움직인다 — 따로 고치면
#    "v0.17.0 이라 적힌 v0.16.0" 이 되거나 빌드가 sha 불일치로 죽는다.
FROM busybox:1.37.0

ARG PLUGIN_VERSION=v0.16.0
# 실측 2026-08-03 — gatewayapi-plugin-linux-amd64 v0.16.0 (78,004,004 B · static ELF x86-64).
#   static 이라 busybox 위에서도, 컨트롤러 이미지 위에서도 libc 의존이 없다.
ARG PLUGIN_SHA256=3f129e6a1ea948932f440b16dfb9eae636a065857eb27311928e5790593103c1

# ADD 의 원격 fetch 는 빌더 내장이라 curl 스테이지가 필요 없다(모드 0600 으로 떨어진다 → 아래에서 chmod).
ADD https://github.com/argoproj-labs/rollouts-plugin-trafficrouter-gatewayapi/releases/download/${PLUGIN_VERSION}/gatewayapi-plugin-linux-amd64 /plugin/gatewayapi-plugin

# 무결성 게이트(위 주석) + 권한.
#   0755 인 이유: 컨트롤러 pod 는 `runAsNonRoot: true` 라 initContainer 가 임의 uid 로 돈다.
#   ADD 기본 0600(root 소유)이면 그 uid 가 **읽지 못해** 복사가 실패하고 컨트롤러가 안 뜬다.
RUN echo "${PLUGIN_SHA256}  /plugin/gatewayapi-plugin" > /tmp/plugin.sha256 \
 && sha256sum -c /tmp/plugin.sha256 \
 && rm /tmp/plugin.sha256 \
 && chmod 0755 /plugin/gatewayapi-plugin
