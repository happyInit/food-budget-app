#!/usr/bin/env bash
# 현재 fb-data(192.168.0.8)에서 실행 — 폴러 host cron 설치 + Harbor 이미지 pull + Kafka 토픽 생성(멱등).
# 전제: 이 repo 체크아웃 · repo 루트 .env(KAFKA_BOOTSTRAP·PG*·REDIS_URL) · docker/compose · Harbor 접근.
#   설치:     bash deploy/install-pollers.sh
#   미리보기: bash deploy/install-pollers.sh --dry-run   # 등록될 crontab 블록만 출력
#   제거:     bash deploy/install-pollers.sh --uninstall # fb-pollers 블록만 crontab에서 삭제
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$REPO/deploy/run-poller.sh"
SRC="$REPO/deploy/crontab.fb-pollers"
BEGIN="# >>> fb-pollers (managed by deploy/install-pollers.sh) >>>"
END="# <<< fb-pollers <<<"
MODE="${1:-install}"

# 기존 crontab에서 fb-pollers 블록(BEGIN..END)만 제거한 나머지
strip_block() {
  # crontab 없는 호스트면 'crontab -l'이 exit 1 → set -e+pipefail로 스크립트가 죽음.
  # '|| true'로 방어 (없으면 빈 입력 → awk가 빈 출력).
  { crontab -l 2>/dev/null || true; } | awk -v b="$BEGIN" -v e="$END" '
    $0==b {skip=1} !skip {print} $0==e {skip=0}'
}

# 등록할 블록 생성: crontab.fb-pollers의 __RUN__ → 절대경로 래퍼 호출
render_block() {
  printf '%s\n' "$BEGIN"
  sed "s#__RUN__#bash $RUN#g" "$SRC"
  printf '%s\n' "$END"
}

if [ "$MODE" = "--uninstall" ]; then
  strip_block | crontab -
  echo "== fb-pollers 블록 제거 완료 =="
  exit 0
fi

if [ "$MODE" = "--dry-run" ]; then
  render_block
  exit 0
fi

# ── 프리플라이트 ──
command -v docker >/dev/null            || { echo "✗ docker 없음"; exit 1; }
docker compose version >/dev/null 2>&1  || { echo "✗ docker compose(v2) 플러그인 없음"; exit 1; }
[ -f "$REPO/docker-compose.yml" ]       || { echo "✗ docker-compose.yml 없음: $REPO"; exit 1; }
[ -f "$REPO/.env" ]                     || { echo "✗ .env 없음 ($REPO/.env) — .env.example 복사 후 채우기"; exit 1; }
chmod +x "$RUN"

# ── Harbor 이미지 pull + 토픽 생성(멱등) ──
echo "== Harbor 이미지 pull (poller 프로파일) =="
( cd "$REPO" && docker compose --profile poller pull )
echo "== Kafka 토픽 생성 (멱등) =="
( cd "$REPO" && docker compose --profile tools run --rm create-topics ) || echo "  (토픽 이미 있음/무시)"

# ── crontab 설치 (기존 fb-pollers 블록 교체) ──
{ strip_block; render_block; } | crontab -
echo
echo "== 설치 완료. 등록된 fb-pollers 스케줄: =="
crontab -l | awk -v b="$BEGIN" -v e="$END" '$0==b {p=1} p {print} $0==e {p=0}'
echo
echo "다음: 상주 컨슈머 기동 →  ( cd $REPO && docker compose up -d )"
echo "로그: /var/log/fb-pollers/<svc>.log  (권한 없으면 $REPO/.poller-logs/)"
