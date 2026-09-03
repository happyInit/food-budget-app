#!/usr/bin/env bash
# 일 1회 PG 논리 덤프 → S3. cron 에서 부른다.
#
#   crontab -e
#   15 4 * * * /home/ubuntu/app/deploy/portfolio/backup.sh >> /home/ubuntu/backup.log 2>&1
#
# 🔴 Lightsail 에는 인스턴스 역할이 없어 .env 의 액세스 키로 붙는다.
#    권한은 portfolio-backup/ 프리픽스 PutObject 하나뿐이다 (iam_backup.tf).
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a

BUCKET="${BACKUP_BUCKET:-mp-backup-ap2}"
PREFIX="${BACKUP_PREFIX:-portfolio-backup}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
STAMP=$(date +%Y%m%dT%H%M%S)
OUT="/tmp/foodbudget-${STAMP}.dump"

docker compose exec -T postgres pg_dump -U "${PGUSER}" -d "${PGDATABASE}" -Fc --no-owner --no-acl > "$OUT"
SIZE=$(stat -c%s "$OUT")
# 덤프가 비정상적으로 작으면 올리지 않는다 — 빈 덤프로 정상 백업을 덮는 사고를 막는다.
if [ "$SIZE" -lt 1000000 ]; then
  echo "[$(date -Is)] 덤프가 너무 작다(${SIZE} bytes) — 업로드 중단"; rm -f "$OUT"; exit 1
fi
aws s3 cp "$OUT" "s3://${BUCKET}/${PREFIX}/foodbudget-${STAMP}.dump" --only-show-errors
rm -f "$OUT"
echo "[$(date -Is)] 백업 완료 ${SIZE} bytes → s3://${BUCKET}/${PREFIX}/"

# 로컬 정리만 한다. S3 보존은 버킷 라이프사이클이 맡는다(권한상 DeleteObject 가 없다).
find /tmp -maxdepth 1 -name 'foodbudget-*.dump' -mtime +"$KEEP_DAYS" -delete 2>/dev/null || true
