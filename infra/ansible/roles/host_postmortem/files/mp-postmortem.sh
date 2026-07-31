#!/usr/bin/env bash
# mp-postmortem — 부팅 직후 **직전 부팅이 어떻게 끝났는지**를 판정하고 증거를 밖으로 보낸다.
#
# 왜 있나: 호스트 A(`.12`)가 무흔적 급사 3회(2026-07-19 17:03 · 07-21 18:04 · 07-21 23:49 KST).
#   패닉·OOM·MCE 0건 — journal 이 그냥 끊긴다. 지금까지 그 사실은 사람이 손으로 로그를
#   뒤져야만 알 수 있었고, 시간이 지나면 기억에만 남았다.
#
# 이 스크립트가 채우는 구멍은 **비콘(mp-ioburst)이 못 채우는 쪽**이다:
#   · 비콘   = 죽기 직전까지의 실시간 vitals. 호스트가 안 돌아와도 남지만, 마지막 몇 초는 잃는다.
#   · 사후수집 = 호스트가 **돌아온 뒤** 로컬에만 남아 있던 것(직전 부팅 journal·pstore·
#               15초 해상도 rate.log)을 회수해 밖으로 보낸다. 디스크가 살아 있어야 한다.
#   둘을 겹쳐야 "언제 죽었나(비콘 공백) + 죽기 직전 커널이 뭘 말했나(journal 끝)"가 맞춰진다.
#
# 🔴 전원이 끊기는 급사에서는 journal 의 마지막 몇 초가 fsync 전이라 **원래 없다.**
#    "로그가 없다"가 곧 "정상 종료가 아니었다"의 증거다 — 그 사실 자체를 판정해 기록한다.
#
# ⚠️ Ansible 관리 파일 — 원본 = infra/ansible/roles/host_postmortem/files/.
set -uo pipefail

OUT="${MP_POSTMORTEM_DIR:-/var/log/mp-postmortem}"
RATE_LOG="${MP_POSTMORTEM_RATE_LOG:-/var/log/mp-ioburst/rate.log}"
JLINES="${MP_POSTMORTEM_JOURNAL_LINES:-400}"
RATE_LINES="${MP_POSTMORTEM_RATE_LINES:-240}"     # 240 × 15s = 급사 직전 60분
RETAIN_DAYS="${MP_POSTMORTEM_RETAIN_DAYS:-90}"
LOKI_URL="${MP_LOKI_URL:-}"
LOKI_TIMEOUT="${MP_LOKI_TIMEOUT:-10}"
HOSTLBL="${MP_HOST_LABEL:-$(hostname)}"

mkdir -p "$OUT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
F="$OUT/boot-$STAMP.txt"

ts_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
utc_of() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo NA; }
kst_of() { TZ=Asia/Seoul date -d "@$1" +%Y-%m-%dT%H:%M:%S+09:00 2>/dev/null || echo NA; }

# ── Loki push (mp-ioburst-watch.sh 와 동일 구현 — 두 롤이 서로 독립적으로 배포되므로 공유 X) ──
# 🔴 나노초를 awk 산술로 만들지 말 것(double 정밀도 초과). 초/나노초를 분리해 문자열로 잇는다.
# 🔴 리터럴 탭(0x09)이 JSON 문자열에 그대로 들어가면 "Invalid control character" 로 push 가
#    통째로 거부된다(실측으로 걸림). 개행만 남기고 제어문자를 죽인 뒤 보낸다.
#    journalctl·last 출력에는 탭이 흔하다.
sanitize() {
  if command -v iconv >/dev/null 2>&1; then
    tr '\011' ' ' | tr -d '\000-\010\013-\037' | head -n 2000 | cut -c1-2000 \
      | iconv -f UTF-8 -t UTF-8 -c 2>/dev/null
  else
    tr '\011' ' ' | tr -d '\000-\010\013-\037' | head -n 2000 | cut -c1-2000
  fi
}

loki_push() {
  local kind="$1" sec nsec body
  if [ -z "$LOKI_URL" ]; then cat >/dev/null; return 0; fi
  sec=$(date +%s); nsec=$(date +%N)
  body=$(
    sanitize \
      | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' \
      | awk -v sec="$sec" -v nsec="$nsec" '
          {
            n = nsec + NR; s = sec
            while (n >= 1000000000) { s = s + 1; n = n - 1000000000 }
            if (NR > 1) printf ","
            printf "[\"%d%09d\",\"%s\"]", s, n, $0
          }'
  )
  [ -z "$body" ] && return 0
  if printf '{"streams":[{"stream":{"job":"mp-hostwatch","host":"%s","kind":"%s"},"values":[%s]}]}' \
        "$HOSTLBL" "$kind" "$body" \
       | curl -sS --max-time "$LOKI_TIMEOUT" -H 'Content-Type: application/json' \
              --data-binary @- "$LOKI_URL" >/dev/null 2>&1; then
    return 0
  fi
  logger -t mp-postmortem -p daemon.err "loki push failed (kind=$kind url=$LOKI_URL)"
  return 1
}

# **Loki 우선**, 그 다음 로컬 파일.
emit() {
  local buf
  buf=$(cat)
  [ -z "$buf" ] && return 0
  printf '%s\n' "$buf" | loki_push postmortem
  printf '%s\n' "$buf" >>"$F" 2>/dev/null
}

# ── 판정 ────────────────────────────────────────────────────────────────────
now_s=$(date +%s)
up_s=$(awk '{printf "%d", $1}' /proc/uptime)
boot_s=$((now_s - up_s))

# 직전 부팅의 마지막 journal 타임스탬프(초). 영속 journal 이 없으면 빈 값.
prev_last_s=$(journalctl -b -1 -n 1 -o short-unix --no-pager 2>/dev/null | awk 'NF{print int($1)}' | tail -1)

# 🔴 정상 종료 판정은 **구조화되고 로케일 독립적인 것**으로만 한다.
#    "Reached target Power-Off" 같은 사람말 문자열은 로케일·systemd 버전에 따라 달라져
#    조용한 거짓음성을 만든다. 반대로 **유닛 이름**은 안 바뀐다 — 정상 종료 경로는 반드시
#    systemd-poweroff/reboot/halt/kexec.service 중 하나를 지난다.
#
# 🔴 함정 ①(실측으로 걸림): `journalctl` 은 결과가 없을 때 **stdout 으로** `-- No entries --`
#    를 찍는다. `[ -n "$out" ]` 로 판정하면 **언제나 참** = 급사를 영원히 정상 종료로
#    오판정한다. 출력 유무가 아니라 `-o json` 레코드 수를 센다.
# 🔴 함정 ②(실측으로 걸림): 최종 단계 바이너리 `systemd-shutdown` 은 journald 가 이미
#    멈춘 뒤에 돌아 콘솔로만 말한다 → journal 에 안 남는 경우가 있다. 그걸 정상 종료의
#    지표로 쓰면 **정상 재부팅마다 급사로 오판정**한다(=늑대소년이 되어 알람이 무시된다).
shutdown_units=$(journalctl -b -1 --no-pager -o json \
                   -u systemd-poweroff.service -u systemd-reboot.service \
                   -u systemd-halt.service -u systemd-kexec.service 2>/dev/null | grep -c '^{')
[ -n "$shutdown_units" ] || shutdown_units=0

# 🔴 "정상 종료"라고 다 무해한 게 아니다. ACPI 임계온도·전원장애는 커널이 orderly_poweroff()
#    를 부르므로 **정상 종료 경로를 그대로 탄다** → verdict=clean 으로 조용히 넘어가면
#    발열 가설을 확증/기각할 유일한 증거를 그 자리에서 버리게 된다. 하드웨어 사건 흔적이
#    직전 부팅에 있으면 정상 종료라도 전체 수집으로 승격한다.
#    ⚠️ 패턴은 **사건 문자열**이어야 한다. `edac`·`power supply` 같은 서브시스템 이름으로
#       잡으면 부팅 배너(`EDAC MC: Ver: 3.0.0`)에 매번 걸려 정상 재부팅마다 전체 수집이
#       돌아간다(실측으로 걸림 — 이 오탐 하나면 알람이 늑대소년이 된다).
HW_RE='critical temperature|thermal shutdown|\[hardware error\]|machine check|kernel panic|soft lockup|hard lockup|watchdog: bug|clock throttled|uncorrected error|corrected error'
hw_marks=$(journalctl -b -1 -k --no-pager 2>/dev/null | grep -Eic "$HW_RE")
[ -n "$hw_marks" ] || hw_marks=0

if [ -z "$prev_last_s" ]; then
  verdict="unknown_no_prev_boot"          # 첫 부팅이거나 journal 이 휘발성이었다
elif [ "$shutdown_units" -eq 0 ]; then
  verdict="unclean"                       # = 급사(전원 상실·하드행·리셋) 후보
elif [ "$hw_marks" -gt 0 ]; then
  verdict="clean_with_hw_event"           # 절차는 정상인데 하드웨어가 방아쇠였을 수 있다
else
  verdict="clean"
fi

if [ -n "$prev_last_s" ]; then
  downtime_s=$((boot_s - prev_last_s))
  prev_last_utc=$(utc_of "$prev_last_s"); prev_last_kst=$(kst_of "$prev_last_s")
else
  downtime_s=-1; prev_last_utc=NA; prev_last_kst=NA
fi

# ── [0] 판정 헤더 — 가장 먼저 보낸다. 뒤가 다 실패해도 사실 자체는 남는다. ──
{
  # 판정 근거(shutdown_units·hw_marks)를 같이 싣는다 — 판정만 남기면 나중에
  # "왜 그렇게 봤는지"를 재구성할 수 없다.
  printf 'kind=postmortem host=%s verdict=%s boot_utc=%s boot_kst=%s prev_last_utc=%s prev_last_kst=%s downtime_s=%s uptime_s=%s shutdown_units=%s hw_marks=%s\n' \
    "$HOSTLBL" "$verdict" "$(utc_of "$boot_s")" "$(kst_of "$boot_s")" \
    "$prev_last_utc" "$prev_last_kst" "$downtime_s" "$up_s" "$shutdown_units" "$hw_marks"
  echo "===== mp-postmortem $(ts_utc) host=$HOSTLBL verdict=$verdict ====="
  echo "kernel : $(uname -r)"
  echo "boots  :"; journalctl --list-boots --no-pager 2>/dev/null | tail -8
} | emit

logger -t mp-postmortem "previous boot verdict=$verdict downtime_s=$downtime_s"

# 정상 종료였으면 여기서 끝낸다 — 매 재부팅마다 400줄씩 Loki 에 쌓을 이유가 없다.
if [ "$verdict" = "clean" ]; then
  echo "kind=postmortem host=$HOSTLBL msg=\"정상 종료 — 상세 수집 생략\"" | emit
  find "$OUT" -name 'boot-*.txt' -mtime "+$RETAIN_DAYS" -delete 2>/dev/null
  exit 0
fi

# ── 여기부터는 비정상 종료(또는 판정 불가)일 때만 ──────────────────────────
{
  echo "----- [1] 직전 부팅 journal 끝 ${JLINES}줄 (여기가 끊긴 지점 = 급사 시각) -----"
  journalctl -b -1 -n "$JLINES" -o short-iso-precise --no-pager 2>/dev/null \
    || echo "(직전 부팅 journal 없음 — journald 가 휘발성이었을 수 있다)"
} | emit

{
  echo "----- [2] 직전 부팅 커널 메시지 끝 200줄 -----"
  journalctl -b -1 -k -n 200 -o short-iso-precise --no-pager 2>/dev/null
  echo "----- [3] 직전 부팅 err 이상 -----"
  journalctl -b -1 -p err -o short-iso-precise --no-pager 2>/dev/null | tail -200
} | emit

{
  echo "----- [4] pstore (전원 상실을 건너뛰고 살아남는 유일한 커널 흔적) -----"
  # 펌웨어가 ERST/efi-pstore 를 지원해야만 내용이 있다. 비어 있으면 "지원 안 함 또는
  # 커널이 아무 말도 못 하고 죽었다" 둘 중 하나 — 그 자체가 정보다.
  ls -l /sys/fs/pstore 2>/dev/null || echo "(pstore 마운트 없음)"
  for p in /sys/fs/pstore/* /var/lib/systemd/pstore/*/*; do
    [ -f "$p" ] || continue
    echo "--- $p ---"; head -c 8000 "$p" 2>/dev/null; echo
  done
  echo "----- [5] wtmp (last -x) — shutdown 기록 없이 reboot 이면 비정상 -----"
  last -x -n 15 2>/dev/null
} | emit

{
  echo "----- [6] 급사 직전 vitals — mp-ioburst rate.log 끝 ${RATE_LINES}줄 (15초 해상도) -----"
  # 🔴 이게 사후수집의 최고 가치다. 비콘은 유휴 구간을 60초로 뭉쳐 보내지만, rate.log 에는
  #    15초 샘플이 전부 남아 있다 → 디스크가 살아 돌아오면 그 해상도를 회수할 수 있다.
  if [ -f "$RATE_LOG" ]; then
    tail -n "$RATE_LINES" "$RATE_LOG" 2>/dev/null
  else
    echo "(rate.log 없음 — mp-ioburst 가 이 호스트에 없거나 아직 안 돌았다)"
  fi
} | emit

{
  echo "----- [7] Proxmox 작업 로그 (직전 부팅 종료 직전에 무엇이 돌고 있었나) -----"
  if [ -d /var/log/pve/tasks ]; then
    echo "[index tail]"; tail -n 40 /var/log/pve/tasks/index 2>/dev/null
    echo "[active]";     cat /var/log/pve/tasks/active 2>/dev/null | head -20
  else
    echo "(Proxmox 아님 — /var/log/pve 없음)"
  fi
} | emit

{
  echo "----- [8] 현재 부팅의 하드웨어 힌트 (MCE·thermal·EDAC·throttle) -----"
  journalctl -b 0 -k --no-pager 2>/dev/null \
    | grep -i -e 'machine check' -e mce -e thermal -e throttl -e edac -e 'hardware error' -e 'CPU. .. stuck' \
    | head -50
  echo "----- [9] 부팅 시점 온도 -----"
  for t in /sys/class/hwmon/hwmon*/temp*_input; do
    [ -f "$t" ] || continue
    printf '%s %s\n' "$t" "$(awk '{printf "%.1f", $1/1000}' "$t" 2>/dev/null)"
  done | head -20
  echo "kind=postmortem host=$HOSTLBL event=end verdict=$verdict file=$F"
} | emit

chmod 0644 "$F" 2>/dev/null
find "$OUT" -name 'boot-*.txt' -mtime "+$RETAIN_DAYS" -delete 2>/dev/null
exit 0
