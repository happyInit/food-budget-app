#!/usr/bin/env bash
# fb-ioburst-watch — 정체불명 디스크 읽기 폭주(2026-07-21·07-22 관측) 발생 시 범인 프로세스를 포착한다.
#
# 배경: fb-data sda 에서 390~400 MB/s · 9,200 IOPS 읽기가 28분간 지속 → 호스트 SSD 포화 → 전 게스트 iowait 폭증
#       → Proxmox 호스트 CPU 78~88°C. 주기적이지 않아(2회만) 사후 로그로는 프로세스 식별 불가.
#
# 동작: /proc/diskstats 를 INTERVAL 초마다 읽어 **전 디스크**(sda·sdb·…) 읽기 MB/s 계산(비용 ≈ 0).
#       어느 하나라도 THRESHOLD 초과 시 프로세스별 I/O·컨테이너 매핑·시스템 상태를 덤프.
#       4-VM(fb-data·fb-app-ai·fb-ci-harbor·fb-monitoring) 공통 배포본.
#
# ⚠️ Ansible 관리 파일 — 원본 = infra/ansible/roles/ioburst_watch/files/. 서버에서 직접 고치지 말 것.
#    설정값(임계·주기·쿨다운)은 이 파일이 아니라 롤 defaults 에서 온다(systemd Environment= 로 주입).
#
# 임시 진단 도구다. 원인 규명되면 제거할 것 — `ioburst_enabled: false` 로 두고
# `ansible-playbook site.yml --tags ioburst` (수동 폴백 = /usr/local/bin/fb-ioburst-uninstall.sh).
set -uo pipefail

# 감시 대상 = 파티션·loop·dm 을 뺀 실제 디스크 전부 (VM 마다 폭주가 sda/sdb 어디서 날지 모른다)
DEV_RE="${FB_IOBURST_DEV_RE:-^(sd[a-z]+|vd[a-z]+|nvme[0-9]+n[0-9]+)$}"
INTERVAL="${FB_IOBURST_INTERVAL:-15}"        # 샘플 주기(초)
THRESHOLD="${FB_IOBURST_THRESHOLD:-100}"     # 발동 임계 MB/s (유휴 0.5, 폭주 395)
COOLDOWN="${FB_IOBURST_COOLDOWN:-300}"       # 연속 발동 억제(초)
RETAIN_DAYS="${FB_IOBURST_RETAIN_DAYS:-14}"
OUT="${FB_IOBURST_DIR:-/var/log/fb-ioburst}"
RATELOG="$OUT/rate.log"
RATELOG_MAX=$((5 * 1024 * 1024))

mkdir -p "$OUT"

ts_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
ts_kst() { TZ=Asia/Seoul date +%Y-%m-%d\ %H:%M:%S\ KST; }

# 디스크별 누적 읽기 섹터 → "dev sectors" (6번째 필드, 섹터=512B)
read_all() { awk -v re="$DEV_RE" '$3 ~ re {print $3, $6}' /proc/diskstats; }

# 전 프로세스의 누적 read_bytes 스냅샷 → "pid readbytes"
snap_io() {
  local p pid r
  for p in /proc/[0-9]*; do
    pid="${p#/proc/}"
    r=$(awk '/^read_bytes:/{print $2; exit}' "$p/io" 2>/dev/null) || continue
    [ -n "$r" ] && printf '%s %s\n' "$pid" "$r"
  done
}

capture() {
  local rate="$1" dev="$2" all="$3"
  local stamp; stamp=$(date -u +%Y%m%dT%H%M%SZ)
  local f="$OUT/burst-$stamp.txt"

  {
    echo "===== fb-ioburst capture ====="
    echo "UTC        : $(ts_utc)"
    echo "KST        : $(ts_kst)"
    echo "host       : $(hostname)"
    echo "device     : $dev  (발동)"
    echo "read rate  : ${rate} MB/s (임계 ${THRESHOLD})"
    echo "all devs   :${all}"
    echo "uptime     : $(uptime)"
    echo

    echo "----- [1] 프로세스별 실제 디스크 읽기 (5초 델타, /proc/PID/io) -----"
    local a b
    a=$(snap_io); sleep 5; b=$(snap_io)
    join <(sort -k1,1 <<<"$a") <(sort -k1,1 <<<"$b") 2>/dev/null \
      | awk '{d=$3-$2; if (d>0) printf "%s %.1f\n", $1, d/1048576/5}' \
      | sort -k2 -rn | head -15 \
      | while read -r pid mbs; do
          local cmd cg ctr
          cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | cut -c1-140)
          [ -z "$cmd" ] && cmd="[$(cat "/proc/$pid/comm" 2>/dev/null)]"
          cg=$(cat "/proc/$pid/cgroup" 2>/dev/null | head -1)
          ctr=$(grep -oE '[0-9a-f]{64}' <<<"$cg" | head -1)
          printf '  %8.1f MB/s  pid=%-8s %s\n' "$mbs" "$pid" "$cmd"
          [ -n "$ctr" ] && printf '           └ container: %s\n' "$ctr"
        done
    echo

    echo "----- [2] pidstat -d (교차검증) -----"
    pidstat -d 1 3 2>/dev/null | tail -25
    echo

    echo "----- [3] iostat -x -----"
    iostat -x 1 2 2>/dev/null | tail -30
    echo

    echo "----- [4] I/O 압력(PSI) -----"
    cat /proc/pressure/io 2>/dev/null
    echo

    echo "----- [5] 실행중 컨테이너 -----"
    docker ps --format '{{.ID}}  {{.Names}}  {{.Status}}' 2>/dev/null | head -40
    echo

    echo "----- [6] 상위 CPU/메모리 프로세스 -----"
    top -bn1 2>/dev/null | head -20
    echo

    echo "----- [7] 마운트/디스크 여유 -----"
    df -h 2>/dev/null | grep -vE 'tmpfs|overlay'
  } >"$f" 2>&1

  chmod 0644 "$f"
  logger -t fb-ioburst "burst captured: ${rate} MB/s on ${dev} -> $f"
  echo "$(ts_utc) BURST ${dev} ${rate} MB/s -> $f" >>"$RATELOG"
}

declare -A prev
while read -r d s; do prev["$d"]="$s"; done < <(read_all)
[ "${#prev[@]}" -eq 0 ] && { echo "감시할 디스크 없음 (DEV_RE=$DEV_RE)" >&2; exit 1; }
last_capture=0

logger -t fb-ioburst "watcher started (devs=${!prev[*]} interval=${INTERVAL}s threshold=${THRESHOLD}MB/s)"

while :; do
  sleep "$INTERVAL"

  maxrate=0; maxdev=""; line=""
  while read -r d s; do
    p="${prev[$d]:-}"
    prev["$d"]="$s"
    [ -z "$p" ] && continue
    [ "$s" -lt "$p" ] && continue          # 카운터 랩/재부팅 방어

    r=$(awk -v a="$p" -v b="$s" -v i="$INTERVAL" 'BEGIN{printf "%.1f", (b-a)*512/1048576/i}')
    line+=" ${d}=${r}"
    if awk -v a="$r" -v b="$maxrate" 'BEGIN{exit !(a>b)}'; then maxrate="$r"; maxdev="$d"; fi
  done < <(read_all)                        # 파이프 대신 프로세스치환 — 배열이 현재 셸에 남아야 한다

  [ -z "$line" ] && continue

  # 레이트 로그(맥락용) — 크기 상한 넘으면 절삭
  echo "$(ts_utc)${line}" >>"$RATELOG"
  if [ "$(stat -c%s "$RATELOG" 2>/dev/null || echo 0)" -gt "$RATELOG_MAX" ]; then
    tail -n 20000 "$RATELOG" >"$RATELOG.tmp" && mv "$RATELOG.tmp" "$RATELOG"
  fi

  over=$(awk -v r="$maxrate" -v t="$THRESHOLD" 'BEGIN{print (r>=t)?1:0}')
  now=$(date +%s)
  if [ "$over" = "1" ] && [ $((now - last_capture)) -ge "$COOLDOWN" ]; then
    last_capture="$now"
    capture "$maxrate" "$maxdev" "$line"
    find "$OUT" -name 'burst-*.txt' -mtime "+$RETAIN_DAYS" -delete 2>/dev/null
  fi
done
