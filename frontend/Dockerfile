# frontend 멀티스테이지 — node 빌드(Vite) → nginx 정적 서빙 + /api 리버스 프록시.
#   build 스테이지는 slim(glibc): tailwind v4/lightningcss/oxide·oxlint 네이티브 바이너리가
#   musl(alpine) 비호환 → 빌드는 glibc, 서빙만 alpine(정적 파일이라 무관).
#   Dockerfile 보안 명세: 핀 베이스(latest 금지) · 시크릿 미포함(.dockerignore) · 산출물 정적(비루트 nginx 워커).

# ---- build ----
FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci                              # lock 기준 재현빌드(dev+devDep 포함 — vite/tsc 필요)
COPY . .
RUN npm run build                       # tsc -b && vite build → /app/dist

# ---- serve ----
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
# nginx:alpine 기본 CMD(nginx -g 'daemon off;') 사용
