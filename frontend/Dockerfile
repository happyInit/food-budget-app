# frontend 멀티스테이지 — node 빌드(Vite) → nginx 정적 서빙 + /api 리버스 프록시.
#   build 스테이지는 slim(glibc): tailwind v4/lightningcss/oxide·oxlint 네이티브 바이너리가
#   musl(alpine) 비호환 → 빌드는 glibc, 서빙만 alpine(정적 파일이라 무관).
#   Dockerfile 보안 명세: 핀 베이스(latest 금지) · 시크릿 미포함(.dockerignore) · 산출물 정적 · §3.1 비루트(master부터).

# ---- build ----
FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci                              # lock 기준 재현빌드(dev+devDep 포함 — vite/tsc 필요)
COPY . .
RUN npm run build                       # tsc -b && vite build → /app/dist

# ---- serve ----
FROM nginx:1.27-alpine
# 베이스 알파인 패키지 보안 패치 — openssl(libcrypto3/libssl3) 등 fixable CRITICAL 제거.
# (nginx:1.27-alpine=alpine 3.21.x 는 openssl 3.3.3-r0 고정 → CVE-2026-31789. apk upgrade 로 3.3.7-r0+ 반영 → Trivy 게이트 통과)
RUN apk upgrade --no-cache
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
# §3.1 — master 프로세스부터 비루트(이미지 내장 nginx 유저, uid/gid 101).
# 8080(비특권 포트) 리슨이라 NET_BIND_SERVICE 조차 불필요 → capability 전부 drop 가능(K8s PSS restricted 준수).
# 캐시·pid 디렉토리는 기본이 root 소유라 미리 넘겨줘야 함(로컬 실행 검증 완료).
RUN chown -R nginx:nginx /var/cache/nginx /run
USER nginx
# nginx:alpine 기본 CMD(nginx -g 'daemon off;') 사용
