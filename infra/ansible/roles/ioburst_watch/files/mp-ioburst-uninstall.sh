#!/usr/bin/env bash
# mp-ioburst 워처 완전 제거 (Ansible 이 안 닿을 때의 수동 폴백).
#   정식 철수 경로 = `ioburst_enabled: false` 로 커밋 후 롤 실행.
#   수집 덤프(/var/log/mp-ioburst)는 남긴다 — 증거를 명령 하나로 날리지 않기 위해서.
#   덤프까지 지우려면: mp-ioburst-uninstall.sh --purge
set -euo pipefail

# 2세대 (mp-)
systemctl disable --now mp-ioburst-watch.service 2>/dev/null || true
rm -f /etc/systemd/system/mp-ioburst-watch.service

# 1세대 잔재 (fb-) — 기존 실물 이름 그대로 참조해 제거한다.
systemctl disable --now fb-ioburst-watch.service 2>/dev/null || true
rm -f /etc/systemd/system/fb-ioburst-watch.service /usr/local/bin/fb-ioburst-watch.sh \
      /usr/local/bin/fb-ioburst-uninstall.sh

systemctl daemon-reload
rm -f /usr/local/bin/mp-ioburst-watch.sh

if [ "${1:-}" = "--purge" ]; then
  rm -rf /var/log/mp-ioburst /var/log/fb-ioburst
  echo "제거 완료 (덤프 포함)"
else
  echo "제거 완료. 수집 덤프는 /var/log/mp-ioburst (구 /var/log/fb-ioburst) 에 보존."
fi
rm -f /usr/local/bin/mp-ioburst-uninstall.sh
