#!/usr/bin/env bash
# mp-hostwatch-silence — 계획된 재부팅·유지보수 동안 비콘 알림을 잠재운다.
#
# 왜 필요한가: 비콘 감시는 "마지막 수신이 오래됐다"만 본다. 워처의 종료 비콘(`kind=stop`)이
#   대부분의 정상 재부팅을 걸러 주지만, 하이퍼바이저를 강제로 내리거나(SIGKILL·전원 조작)
#   네트워크를 만지는 작업은 급사와 구분이 안 된다. 그때 미리 이걸 건다.
#
# 사용:
#   mp-hostwatch-silence.sh fb-proxmox 30     # 30분간 그 호스트만
#   mp-hostwatch-silence.sh all 60            # 60분간 전체
#   mp-hostwatch-silence.sh --clear [호스트]  # 해제(호스트 생략 시 전부)
#   mp-hostwatch-silence.sh --status
#
# ⚠️ Ansible 관리 파일 — 원본 = infra/ansible/roles/hostwatch_sink/files/.
set -euo pipefail
CONF_DIR="${MP_HOSTWATCH_CONF_DIR:-/etc/mp-hostwatch}"
mkdir -p "$CONF_DIR"

usage() { sed -n '2,16p' "$0"; exit 1; }

case "${1:-}" in
  --status)
    shopt -s nullglob
    found=0
    for f in "$CONF_DIR"/silence "$CONF_DIR"/silence.*; do
      until=$(head -1 "$f" 2>/dev/null || true)
      if [ -z "$until" ]; then
        echo "$(basename "$f"): 무기한 (해제할 때까지)"
      else
        echo "$(basename "$f"): $(date -d "@$until" '+%Y-%m-%d %H:%M:%S %Z') 까지"
      fi
      found=1
    done
    [ "$found" = 0 ] && echo "침묵창 없음 — 알림 정상 발화 상태"
    exit 0
    ;;
  --clear)
    if [ -n "${2:-}" ] && [ "$2" != "all" ]; then
      rm -f "$CONF_DIR/silence.$2"; echo "해제: $2"
    else
      rm -f "$CONF_DIR"/silence "$CONF_DIR"/silence.*; echo "해제: 전체"
    fi
    exit 0
    ;;
  ""|-h|--help) usage ;;
esac

host="$1"; mins="${2:-30}"
[[ "$mins" =~ ^[0-9]+$ ]] || usage
until=$(( $(date +%s) + mins * 60 ))

if [ "$host" = "all" ]; then f="$CONF_DIR/silence"; else f="$CONF_DIR/silence.$host"; fi
echo "$until" >"$f"
chmod 0644 "$f"
echo "침묵: $host — $(date -d "@$until" '+%Y-%m-%d %H:%M:%S %Z') 까지 ($mins 분)"
logger -t mp-hostwatch-beacon "silence set host=$host until=$until by=${SUDO_USER:-$USER}"
