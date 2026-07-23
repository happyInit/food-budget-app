#!/usr/bin/env bash
# fb-ioburst 워처 완전 제거. 수집한 덤프(/var/log/fb-ioburst)는 남긴다.
#   덤프까지 지우려면: fb-ioburst-uninstall.sh --purge
set -euo pipefail
systemctl disable --now fb-ioburst-watch.service 2>/dev/null || true
rm -f /etc/systemd/system/fb-ioburst-watch.service
systemctl daemon-reload
rm -f /usr/local/bin/fb-ioburst-watch.sh
if [ "${1:-}" = "--purge" ]; then
  rm -rf /var/log/fb-ioburst
  echo "제거 완료 (덤프 포함)"
else
  echo "제거 완료. 수집 덤프는 /var/log/fb-ioburst 에 보존."
fi
rm -f /usr/local/bin/fb-ioburst-uninstall.sh
