# mp-rollouts-gatewayapi-plugin — Argo Rollouts Gateway API 트래픽라우터 플러그인 vendoring (ADR-0001 §6.2)
#
# 왜 이 이미지가 필요한가: Rollouts 컨트롤러는 트래픽라우터 플러그인 바이너리가 없으면 **기동하지 않는다**.
#   기본 배선(`location: https://…`)이면 HA 각 pod 가 재기동마다(노드 드레인·페일오버·OOM·차트 업그레이드)
#   GitHub 에서 재다운로드한다 → GitHub blip/rate-limit 시 배포를 게이팅하는 컨트롤러가 안 뜬다.
#   = **장애 중 픽스를 배포하려는 바로 그 순간 배포 게이트가 죽는다.**
#   vendoring 은 그 의존을 **이미 모든 배포의 하드 의존인 Harbor 로** 옮긴다(새 실패 도메인 0개).
#
# 🔴 런타임 hermetic — 네트워크는 빌드타임에만 탄다. 클러스터는 Harbor 만 본다.
#
# ── 🔴 왜 릴리스 바이너리를 안 쓰고 소스에서 빌드하는가 (2026-08-03) ─────────────────────────
# 업스트림 릴리스 바이너리(v0.16.0)를 그대로 담았더니 **Trivy CRITICAL 2건**에 걸렸다(실측):
#   · google.golang.org/grpc v1.75.1 — CVE-2026-33186 (fixed 1.79.3)
#   · Go stdlib 1.24.3            — CVE-2025-68121, crypto/tls 세션재개 시 인증서 검증 결함
#                                    (fixed 1.24.13 / 1.25.7 / 1.26.0-rc.3)
# v0.16.0 이 **최신 릴리스**라(2026-07-13) 버전 업으로 회피할 수 없다. 그리고 이 바이너리는
# https:// 배선 시절부터 **이미 클러스터에서 돌고 있었다** — vendoring 이 위험을 만든 게 아니라
# 처음으로 공급망 게이트에 통과시켜 **보이게** 만든 것이다.
# → 그래서 패치된 툴체인·의존성으로 **우리가 직접 빌드**한다. 예외처리로 게이트에 구멍을 내지 않는다.
#
# 🔴 무결성 근거가 바뀌었다: 구 방식은 릴리스 바이너리 `sha256sum -c` 였다. 지금은
#   ① 소스를 **커밋 sha 로 핀**(태그는 재지정 가능하지만 커밋 sha 는 불변 — 아래 assert 가 강제)
#   ② 모듈은 Go 툴체인이 go.sum·checksum DB 로 자동 검증
#   ③ 빌드가 우리 Jenkins 안에서 일어남
#   이 셋이 대체한다. ADR §6.2 의 "file:// + sha256" 서술은 **두 가지로 부정확**하다 —
#   릴리스 바이너리 전제이고, 애초에 컨트롤러는 file:// 분기에서 sha256 을 검증하지 않는다
#   (v1.9.1 `utils/plugin/downloader.go` — checkShaOfPlugin 호출이 http(s) 분기에만 있다). 정정 대상.
#
# 태깅(infra 트랙 — elasticsearch-nori 와 같은 관례): 우리 코드가 0줄인 재빌드라 릴리스 버전
#   자리에 **업스트림 플러그인 버전**을 그대로 쓴다(0.16.0). 의존성만 올린 재빌드는 `-rN` 리비전.
#   config 레포 핀은 정책대로 `:sha`(CLAUDE.md — `:latest` 금지, ArgoCD 감지·롤백 불가).

# 🔴 1.25.7 이상이어야 stdlib CVE-2025-68121 이 잡힌다. 내리지 말 것.
#
# 🔴 `--platform=$BUILDPLATFORM` — 빌드 스테이지는 **빌더의 네이티브 아키텍처**로 돌린다.
#   이게 없으면 buildx 가 arm64 를 만들 때 golang 이미지까지 arm64 로 당겨와 QEMU 위에서
#   컴파일한다(수분 → 수십분, 간헐 실패). Go 는 크로스컴파일러라 GOARCH 만 바꾸면 되므로
#   에뮬레이션이 순수 낭비다.
#
# 🔴 `:-` 폴백이 붙은 이유 — 맨 `$BUILDPLATFORM` 은 **현행 CI 를 죽인다**(2026-08-10 실측).
#   `BUILDPLATFORM`·`TARGETARCH` 는 **BuildKit 이 채우는** predefined ARG 인데, Jenkins 컨테이너에는
#   buildx 플러그인이 없어 **클래식 빌더**로 떨어진다(docker CLI 29.6.2 인데 `docker buildx` = unknown command).
#   거기선 값이 안 채워져 `--platform=` 이 빈 문자열이 되고 → `failed to parse platform` 로 빌드가 죽는다.
#   `${BUILDPLATFORM:-linux/amd64}` 는 BuildKit 이면 실제 값을, 클래식이면 기본값을 쓴다.
#
#   ⚠️ **`ARG BUILDPLATFORM=linux/amd64` 로 기본값을 주는 방식은 쓰면 안 된다** — 실측하니
#      **사용자 기본값이 BuildKit 주입값을 덮는다**(arm64 타깃인데 `zzz-default` 가 나왔다).
#      그 함정에 빠지면 arm64 매니페스트에 amd64 바이너리가 들어간다. `:-` 는 ARG 선언이 아니라 덮지 않는다.
FROM --platform=${BUILDPLATFORM:-linux/amd64} golang:1.25.12-alpine AS build

RUN apk add --no-cache git

WORKDIR /src

ARG PLUGIN_VERSION=v0.16.0
# v0.16.0 이 가리키는 커밋(2026-08-03 확인). 태그가 재지정되면 아래 assert 가 빌드를 죽인다 —
#   조용히 다른 소스를 빌드하는 것보다 훨씬 싸다.
ARG PLUGIN_COMMIT=716853e84e2968ba3e29c61f649d555f17d0098a
RUN git clone --depth 1 --branch ${PLUGIN_VERSION} \
      https://github.com/argoproj-labs/rollouts-plugin-trafficrouter-gatewayapi.git . \
 && test "$(git rev-parse HEAD)" = "${PLUGIN_COMMIT}"

# grpc 는 **indirect** 의존(argo-rollouts·go-plugin 경유)이라 직접 올릴 수 있다.
#   🔴 최소 수정판만 올린다 — 1.79.3 이 CVE-2026-33186 수정 최소 버전이고, 1.83 까지 점프하면
#      go-plugin v1.6.0 / argo-rollouts v1.6.6 와의 호환 위험만 커진다.
ARG GRPC_VERSION=v1.79.3
RUN go get google.golang.org/grpc@${GRPC_VERSION} && go mod tidy

# GOTOOLCHAIN=local — go.mod 의 `toolchain go1.24.3` 을 보고 툴체인을 내려받지 않게 못박는다
#   (빌드 hermetic + 취약 툴체인으로 되돌아가는 사고 방지. 로컬 1.25.x 가 더 높아 다운로드 불요).
# CGO_ENABLED=0 — static 링크. 업스트림 릴리스 아티팩트와 같은 성질이라 busybox 위에서도,
#   컨트롤러 이미지 위에서도 libc 의존이 없다. + 크로스컴파일이 CGO 없이 성립하는 전제이기도 하다.
#
# TARGETARCH = BuildKit 이 타깃 플랫폼마다 주입하는 predefined ARG(amd64 · arm64 …).
#   위와 같은 이유로 **클래식 빌더에서는 비어 있다**. 그땐 `go env GOARCH`(= 빌더 네이티브)로 떨어뜨린다 —
#   클래식 빌더에는 애초에 "타깃 플랫폼" 개념이 없어 네이티브가 정답이지 추측이 아니다.
#   ⚠️ 기본값을 `ARG TARGETARCH=amd64` 로 주면 안 된다(위 FROM 주석의 덮어쓰기 함정).
#
# 🔴 마지막 줄은 **만든 바이너리 자체를 검사**한다. 변수를 믿는 대신 산출물을 믿는 쪽이 —
#   위 덮어쓰기 함정처럼 값이 조용히 틀어지는 경우까지 잡는다. 안 잡으면 arm64 매니페스트 안에
#   amd64 바이너리가 들어가고, 그건 클러스터에서 `exec format error` 로만 드러난다.
ARG TARGETARCH
RUN ARCH="${TARGETARCH}"; [ -n "$ARCH" ] || ARCH="$(go env GOARCH)"; \
    CGO_ENABLED=0 GOOS=linux GOARCH="$ARCH" GOTOOLCHAIN=local \
      go build -trimpath -o /out/gatewayapi-plugin . \
 && test -s /out/gatewayapi-plugin \
 && go version -m /out/gatewayapi-plugin | grep -q "GOARCH=$ARCH"

FROM busybox:1.37.0

COPY --from=build /out/gatewayapi-plugin /plugin/gatewayapi-plugin

# 🔴 0755 필수 — 컨트롤러 pod 는 `runAsNonRoot: true` 라 initContainer 가 임의 uid 로 돈다.
#    더 좁은 권한(root 소유 0700 등)이면 그 uid 가 **읽지 못해** 복사가 실패하고 컨트롤러가 안 뜬다.
RUN chmod 0755 /plugin/gatewayapi-plugin
