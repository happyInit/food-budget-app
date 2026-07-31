#!/usr/bin/env bash
# mp-ioburst-watch — 디스크 읽기 폭주 감시 + **증거의 원격 송출(급사 생존)**
#
# 배경(사실): 호스트 A(`.12`)가 무흔적 급사 3회(2026-07-19 17:03 · 07-21 18:04 · 07-21 23:49 KST).
#   패닉·OOM·MCE 0건 — 로그가 그냥 끊긴다. 별건으로 정체불명 읽기 폭주 2회(07-21·07-22):
#   390~400 MB/s · 8,700 tps · util 82% 가 28분 지속, 총 ~670GB, 페이지캐시 미증가(O_DIRECT 추정).
#   원인 미규명. 인과관계(폭주 ↔ 급사)도 **미확인**이다.
#
# 🔴 이 스크립트의 존재 이유가 1세대와 다르다.
#   1세대(fb-ioburst)는 덤프를 **로컬 디스크**에만 남겼다. 전원이 끊기는 급사에서는
#   그 로컬 증거가 같이 죽는다 — 정작 필요한 순간에 아무것도 안 남는 구조였다.
#   2세대(이 파일)는 **모든 관측을 즉시 클러스터 밖 호스트 C(`.10`)로 밀어낸다.**
#   로컬 파일은 이제 1순위가 아니라 백업(재부팅은 견디되 디스크 상실은 못 견딤)이다.
#
# 🔴 행선지가 인클러스터 Loki 가 **아니다**(2026-07-31 재설계).
#   Loki·Prometheus·Alertmanager·MinIO 가 전부 호스트 B 에 있어, 호스트 B 가 죽으면
#   기록·수신·발화가 동시에 죽는다 = 증거 0. 그래서 클러스터 **밖** 호스트 C 로 보낸다.
#   전송 = `logger`(util-linux 내장) → UDP syslog. 근거·트레이드오프는 롤 defaults 참조.
#   평시 조회는 호스트 C 의 alloy 가 그 파일을 Loki 로 tail 해 주므로 Grafana 는 그대로다.
#
# 동작
#   ① 비콘  : INTERVAL(기본 15s)마다 /proc/diskstats·loadavg·meminfo·PSI·hwmon 을 읽어
#             logfmt 한 줄로 만든다. 읽기율이 HOT 이상이면 **즉시** 송출,
#             아니면 BEACON_IDLE(기본 60s) 주기로 모아서 송출.
#             → **비콘이 끊긴 시각 = 급사 시각**(해상도: 폭주 중 ≤15s / 유휴 중 ≤60s).
#   ② 덤프  : THRESHOLD(기본 100MB/s) 초과 시 범인 프로세스를 /proc/PID/io 5초 델타로 잡고,
#             **섹션 단위로 쪼개 즉시 송출**한다(캡처 도중 죽어도 앞 섹션은 살아남는다).
#   ③ 토폴로지: 기동 시 + TOPOLOGY_INTERVAL(기본 1h)마다 lsblk·dmsetup·lvs·qm list 를 송출.
#             → 인클러스터 Prometheus 가 이미 갖고 있는 `node_disk_read_bytes_total{device="dm-N"}`
#               (게스트 LV 별 읽기량)을 **어느 VM 인지로 번역**할 수 있게 하는 사전이다.
#               dm-N 번호는 재부팅마다 바뀌므로 사후에 만들 수 없다 — 그래서 미리 보낸다.
#   ④ 종료비콘: SIGTERM/SIGINT 를 받으면 `kind=stop` 을 한 줄 남기고 끝낸다.
#             🔴 이게 오탐 억제의 핵심이다 — **계획된 재부팅·유지보수에는 이 줄이 남고,
#             전원이 끊기는 급사에는 안 남는다.** 호스트 C 의 비콘 감시가 마지막 줄을 보고
#             "계획된 종료"와 "급사"를 구분한다.
#
# ── 줄 포맷 (사람·alloy·감시스크립트 3자가 같은 줄을 쓴다) ────────────────────
#   전부 **logfmt** (key=value, 공백 구분). 모든 줄의 공통 선두 키:
#     ts=<RFC3339 UTC> host=<라벨> kind=<종류> evt=<이벤트ID> seq=<순번>
#   · ts   = 보낸 쪽 시각(UTC). 싱크는 여기에 `recv=`(받은 시각)·`from=`(IP)를 앞에 더 붙인다.
#   · kind = start|stop|sample|burst|topology|deploy
#   · evt  = `<접두>-<epoch>-<pid>`. **UDP 는 순서를 보장하지 않으므로** 한 사건의 줄들을
#            나중에 다시 묶는 유일한 수단이다. seq 로 원래 순서를 복원한다.
#   · 자유 텍스트(덤프 본문)는 **마지막 키 `msg="..."`** 안에 넣는다 → 줄 전체가 계속 logfmt.
#
# ⚠️ Ansible 관리 파일 — 원본 = infra/ansible/roles/ioburst_watch/files/. 서버에서 직접 고치지 말 것.
#    설정값(임계·주기·행선지)은 이 파일이 아니라 롤 defaults 에서 온다(systemd Environment= 주입).
set -uo pipefail

# ── 설정 (systemd Environment= 로 주입, 없으면 아래 기본값) ──────────────────
# 트리거 = **물리 디스크만**. 하이퍼바이저에서 dm-* 는 게스트 LV 라 물리 포화의 지표가 아니다.
TRIGGER_RE="${MP_IOBURST_TRIGGER_RE:-^(sd[a-z]+|vd[a-z]+|nvme[0-9]+n[0-9]+)$}"
# 보고 = 물리 + dm-* (게스트 LV). 어느 게스트가 읽고 있었는지의 유일한 단서다.
REPORT_RE="${MP_IOBURST_REPORT_RE:-^(sd[a-z]+|vd[a-z]+|nvme[0-9]+n[0-9]+|dm-[0-9]+)$}"
INTERVAL="${MP_IOBURST_INTERVAL:-15}"          # 샘플 주기(초). /proc 읽기라 비용 ≈ 0
THRESHOLD="${MP_IOBURST_THRESHOLD:-100}"       # 덤프 발동 MB/s (실측 유휴 0.06 / 7일 최대 10.5 / 폭주 395)
HOT="${MP_IOBURST_HOT:-20}"                    # 이 이상이면 비콘을 모으지 않고 즉시 송출
BEACON_IDLE="${MP_IOBURST_BEACON_IDLE:-60}"    # 유휴 시 비콘 flush 주기(초) = 유휴 증거 손실 상한
COOLDOWN="${MP_IOBURST_COOLDOWN:-300}"         # 연속 덤프 억제(초)
RETAIN_DAYS="${MP_IOBURST_RETAIN_DAYS:-14}"    # 로컬 덤프 보존
TOPO_INTERVAL="${MP_IOBURST_TOPOLOGY_INTERVAL:-3600}"
OUT="${MP_IOBURST_DIR:-/var/log/mp-ioburst}"

# 원격 송출 — 비면 로컬만 남는다(= 급사 생존 없음). 롤이 배포 시점에 assert 로 막는다.
SINK_HOST="${MP_SYSLOG_HOST:-}"
SINK_PORT="${MP_SYSLOG_PORT:-514}"
SYSLOG_PRI="${MP_SYSLOG_PRIORITY:-daemon.info}"
MSG_MAXLEN="${MP_SYSLOG_MAXLEN:-1600}"
LOGGER_MAXSIZE="${MP_SYSLOG_MAXSIZE:-2048}"
HOSTLBL="${MP_HOST_LABEL:-$(hostname)}"

RATELOG="$OUT/rate.log"
RATELOG_MAX=$((5 * 1024 * 1024))

mkdir -p "$OUT"

ts_utc()   { date -u +%Y-%m-%dT%H:%M:%SZ; }
ts_kst()   { TZ=Asia/Seoul date +%Y-%m-%dT%H:%M:%S+09:00; }
uptime_s() { awk '{printf "%d", $1}' /proc/uptime; }

# ── 원격 송출 ───────────────────────────────────────────────────────────────
# 🔴 UDP(`-d`)인 이유: fire-and-forget 이라 **I/O 폭주 중에도 send 가 블록되지 않는다.**
#    TCP 면 디스크가 포화된 바로 그 순간 전송이 밀려 정작 필요한 구간을 잃는다.
#    유실 가능성은 LAN 이라 수용한다(트레이드오프 — group_vars/all.yml 참조).
# 🔴 `--rfc3164` 를 **명시**한다. logger 는 원격일 때 RFC5424 가 기본인데, 그 모드는 MSG 앞에
#    UTF-8 BOM(EF BB BF)을 붙인다. rsyslog 가 BOM 을 벗기는지는 **미확인**이고, 안 벗기면
#    모든 줄이 `﻿ts=...` 로 시작해 logfmt 파싱이 통째로 깨진다. 확인 못 한 것에 기대지 않는다.
# 🔴 TAG(`-t`)가 곧 **호스트 정체**다 — 싱크의 rsyslog 가 이걸 programname 으로 파싱해
#    `<라벨>.log` 파일명으로 쓴다. 그래서 TAG 에 `[`·`:`·공백을 넣으면 안 된다.
# 🔴 한 줄 = 한 syslog 메시지. logger 는 stdin 을 줄 단위로 읽어 각각 보내므로
#    **덤프 전체를 한 번의 fork 로** 내보낼 수 있다(400줄 = 400 fork 가 아니다).
sink_send() {
  [ -z "$SINK_HOST" ] && { cat >/dev/null; return 0; }
  logger --rfc3164 -e -S "$LOGGER_MAXSIZE" \
         -n "$SINK_HOST" -P "$SINK_PORT" -d \
         -t "$HOSTLBL" -p "$SYSLOG_PRI" 2>/dev/null
}

# 🔴 syslog 메시지에 그대로 들어가면 곤란한 것들을 먼저 없앤다.
#    · 제어문자: 개행만 남기고 전부 제거(탭은 공백으로 — 지우면 열이 붙어 못 읽는다).
#    · 길이: MSG_MAXLEN 에서 자른다. 여기서 안 자르면 logger/rsyslog 가 조용히 자른다
#      = 잘린 줄이 logfmt 중간에서 끊겨 파서를 깨뜨린다. **우리가 먼저, 예측 가능하게** 자른다.
#    · iconv -c: cut 이 UTF-8 문자를 반토막 냈을 때 생기는 깨진 바이트를 걷어낸다.
sanitize() {
  if command -v iconv >/dev/null 2>&1; then
    tr '\011' ' ' | tr -d '\000-\010\013-\037' | head -n 2000 | cut -c"1-$MSG_MAXLEN" \
      | iconv -f UTF-8 -t UTF-8 -c 2>/dev/null
  else
    tr '\011' ' ' | tr -d '\000-\010\013-\037' | head -n 2000 | cut -c"1-$MSG_MAXLEN"
  fi
}

# ── 줄 조립 ────────────────────────────────────────────────────────────────
# SEQ 는 evt 안에서 단조 증가한다. 🔴 그래서 emit_* 는 **파이프 오른쪽이 아니라 herestring**
#    으로 호출한다(`emit_text x "$evt" <<<"$buf"`). 파이프면 서브셸이라 SEQ 증가가 사라진다 —
#    이 레포에서 이미 여러 번 물린 함정이다.
SEQ=1

# 자유 텍스트 → `... msg="<이스케이프된 줄>"`.
# 🔴 백슬래시·따옴표 이스케이프는 **sed 로** 한다. awk 의 gsub 치환문자열은 백슬래시를
#    한 번 더 먹어(`"\\\\"` 가 백슬래시 1개가 된다) 조용히 틀린다 — 그 함정을 피한다.
fmt_text() {
  sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' \
    | awk -v pfx="$1" -v s0="$2" '{ printf "%s seq=%d msg=\"%s\"\n", pfx, s0 + NR - 1, $0 }'
}
# 이미 logfmt 인 꼬리 → 공통 선두 키만 붙인다.
fmt_kv() {
  awk -v pfx="$1" -v s0="$2" '{ printf "%s seq=%d %s\n", pfx, s0 + NR - 1, $0 }'
}

# 원격 먼저, 그 다음 로컬 파일.
# 🔴 순서가 중요하다. 이 유닛은 IOSchedulingClass=idle 이라 폭주 중 로컬 쓰기가 수 분 막힐 수
#    있는데, 로컬을 먼저 쓰면 정작 중요한 원격 송출이 그 뒤에서 굶는다.
_ship() {                      # $1=완성된 줄들, $2=로컬 파일(비면 생략)
  [ -z "$1" ] && return 0
  printf '%s\n' "$1" | sink_send
  [ -n "${2:-}" ] && printf '%s\n' "$1" >>"$2" 2>/dev/null
  return 0
}

emit_text() {                  # $1=kind $2=evt $3=로컬파일  / stdin=자유 텍스트
  local kind="$1" evt="$2" file="${3:-}" buf out n
  buf=$(sanitize)
  [ -z "$buf" ] && return 0
  n=$(printf '%s\n' "$buf" | wc -l)
  out=$(printf '%s\n' "$buf" | fmt_text "ts=$(ts_utc) host=$HOSTLBL kind=$kind evt=$evt" "$SEQ")
  SEQ=$((SEQ + n))
  _ship "$out" "$file"
}

emit_kv() {                    # $1=kind $2=evt $3=로컬파일  / stdin=logfmt 꼬리
  local kind="$1" evt="$2" file="${3:-}" buf out n
  buf=$(sanitize)
  [ -z "$buf" ] && return 0
  n=$(printf '%s\n' "$buf" | wc -l)
  out=$(printf '%s\n' "$buf" | fmt_kv "ts=$(ts_utc) host=$HOSTLBL kind=$kind evt=$evt" "$SEQ")
  SEQ=$((SEQ + n))
  _ship "$out" "$file"
}

new_evt() { printf '%s-%s-%s' "$1" "$(date +%s)" "$$"; }

# ── 수집기 ──────────────────────────────────────────────────────────────────
# /proc/diskstats: $3=디바이스 $6=누적 읽기 섹터(512B)
read_all() { awk -v re="$REPORT_RE" '$3 ~ re {print $3, $6}' /proc/diskstats; }

vitals() {
  local load avail psi tmax
  load=$(awk '{print $1}' /proc/loadavg 2>/dev/null)
  avail=$(awk '/^MemAvailable:/{printf "%d", $2/1024}' /proc/meminfo 2>/dev/null)
  psi=$(awk -F'avg10=' '/^some/{split($2,a," "); print a[1]}' /proc/pressure/io 2>/dev/null)
  # hwmon 은 밀리도 단위. 급사 순간 온도가 미상이었던 것이 발열 가설을 못 닫은 이유다.
  tmax=$(cat /sys/class/hwmon/hwmon*/temp*_input 2>/dev/null | sort -rn | head -1)
  [ -n "${tmax:-}" ] && tmax=$(awk -v v="$tmax" 'BEGIN{printf "%.1f", v/1000}')
  printf 'load1=%s mem_avail_mb=%s psi_io_some10=%s temp_max_c=%s' \
    "${load:-NA}" "${avail:-NA}" "${psi:-NA}" "${tmax:-NA}"
}

# 전 프로세스 누적 read_bytes 스냅샷 → "pid readbytes"
snap_io() {
  local p pid r
  for p in /proc/[0-9]*; do
    pid="${p#/proc/}"
    r=$(awk '/^read_bytes:/{print $2; exit}' "$p/io" 2>/dev/null) || continue
    [ -n "$r" ] && printf '%s %s\n' "$pid" "$r"
  done
}

# dm-N ↔ 게스트 LV ↔ VM 이름 사전. 재부팅마다 바뀌므로 **미리** 보내 둬야 한다.
topology_body() {
  echo "----- lsblk -----"
  lsblk -o NAME,KNAME,MAJ:MIN,TYPE,SIZE,MOUNTPOINTS 2>/dev/null || lsblk 2>/dev/null
  echo "----- dmsetup ls (dm-<minor> → LV 이름) -----"
  command -v dmsetup >/dev/null 2>&1 && dmsetup ls 2>/dev/null
  echo "----- lvs -----"
  command -v lvs >/dev/null 2>&1 && lvs --noheadings -o lv_name,vg_name,lv_size 2>/dev/null
  echo "----- 게스트 목록 (Proxmox) -----"
  command -v qm  >/dev/null 2>&1 && qm  list 2>/dev/null
  command -v pct >/dev/null 2>&1 && pct list 2>/dev/null
  return 0
}

send_topology() {
  local evt buf
  evt=$(new_evt topo); SEQ=1
  buf=$(topology_body)
  emit_text topology "$evt" "$OUT/topology.log" <<<"$buf"
}

# 러너 목록 — 하이퍼바이저(qm)·K8s 노드(crictl)·Docker 호스트 어디서든 뭔가는 나온다.
workloads() {
  echo "----- 실행중 워크로드 -----"
  if command -v qm >/dev/null 2>&1; then
    echo "[qm list]"; qm list 2>/dev/null
    echo "[kvm 프로세스]"; pgrep -a kvm 2>/dev/null | cut -c1-200 | head -20
  fi
  if command -v crictl >/dev/null 2>&1; then
    echo "[crictl ps]"; crictl ps 2>/dev/null | head -40
  fi
  if command -v docker >/dev/null 2>&1; then
    echo "[docker ps]"; docker ps --format '{{.ID}}  {{.Names}}  {{.Status}}' 2>/dev/null | head -40
  fi
  return 0
}

# ── 폭주 덤프 ───────────────────────────────────────────────────────────────
# 🔴 섹션마다 즉시 송출한다. 캡처 전체(≈10초)를 다 모으고 한 번에 보내면,
#    그 10초 안에 호스트가 죽었을 때 **증거 전부**를 잃는다.
# 🔴 모든 섹션이 같은 `evt=burst-...` 를 달고 나가므로, UDP 가 순서를 뒤섞어도
#    `grep evt=burst-1785… | sort -t= -k…` 이 아니라 그냥 `seq=` 로 복원된다.
capture() {
  local rate="$1" dev="$2" all="$3" stamp f a b evt buf
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  f="$OUT/burst-$stamp.txt"
  evt=$(new_evt burst); SEQ=1

  # [0] 헤더 — 즉시(0초). 최소한 "언제·어느 장치·얼마나"는 무조건 밖에 남는다.
  buf=$(
    echo "event=start kst=$(ts_kst) dev=$dev read_mbs=$rate threshold=$THRESHOLD file=$f"
    echo "event=vitals $(vitals) uptime_s=$(uptime_s)$all"
  )
  emit_kv burst "$evt" "$f" <<<"$buf"
  buf=$( { echo "----- I/O 압력(PSI) -----"; cat /proc/pressure/io 2>/dev/null; } )
  emit_text burst "$evt" "$f" <<<"$buf"

  # [1] 범인 프로세스 (5초 델타) — 이 덤프의 존재 이유. 두 번째로 보낸다.
  a=$(snap_io); sleep 5; b=$(snap_io)
  buf=$(
    echo "----- [1] 프로세스별 실제 디스크 읽기 (5초 델타, /proc/PID/io) -----"
    join <(sort -k1,1 <<<"$a") <(sort -k1,1 <<<"$b") 2>/dev/null \
      | awk '{d=$3-$2; if (d>0) printf "%s %.1f\n", $1, d/1048576/5}' \
      | sort -k2 -rn | head -15 \
      | while read -r pid mbs; do
          cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | cut -c1-180)
          [ -z "$cmd" ] && cmd="[$(cat "/proc/$pid/comm" 2>/dev/null)]"
          cg=$(head -1 "/proc/$pid/cgroup" 2>/dev/null)
          printf '  %8.1f MB/s  pid=%-8s %s\n' "$mbs" "$pid" "$cmd"
          [ -n "$cg" ] && printf '           └ cgroup: %s\n' "$(cut -c1-180 <<<"$cg")"
        done
  )
  emit_text burst "$evt" "$f" <<<"$buf"

  # [2] 워크로드·토폴로지 — pid 를 VM/컨테이너로 번역하는 재료
  buf=$( { workloads; topology_body; } )
  emit_text burst "$evt" "$f" <<<"$buf"

  # [3] 교차검증 (sysstat 없으면 조용히 비어 나온다 — 없어도 [1] 로 결론은 난다)
  buf=$(
    echo "----- [3] pidstat -d (교차검증) -----"
    pidstat -d 1 3 2>/dev/null | tail -25
    echo "----- [4] iostat -x -----"
    iostat -x 1 2 2>/dev/null | tail -30
  )
  emit_text burst "$evt" "$f" <<<"$buf"

  # [4] 마감
  buf=$(
    echo "----- [5] 상위 CPU/메모리 -----"
    top -bn1 2>/dev/null | head -20
    echo "----- [6] 마운트/여유 -----"
    df -h 2>/dev/null | grep -vE 'tmpfs|overlay'
  )
  emit_text burst "$evt" "$f" <<<"$buf"
  emit_kv burst "$evt" "$f" <<<"event=end file=$f"

  chmod 0644 "$f" 2>/dev/null
  logger -t mp-ioburst "burst captured: ${rate} MB/s on ${dev} -> $f"
}

# ── 메인 ────────────────────────────────────────────────────────────────────
declare -A prev
while read -r d s; do prev["$d"]="$s"; done < <(read_all)
if [ "${#prev[@]}" -eq 0 ]; then
  echo "감시할 디스크 없음 (REPORT_RE=$REPORT_RE)" >&2
  exit 1
fi

RUN_EVT=$(new_evt run)

# 🔴 종료 비콘 — 오탐 억제의 핵심.
#    systemd 는 재부팅·`systemctl stop` 시 SIGTERM 을 보낸다 → 이 줄이 남는다.
#    전원이 끊기는 급사에는 **안 남는다.** 호스트 C 의 비콘 감시가 마지막 줄에
#    `kind=stop` 이 있는지로 "계획된 종료"와 "급사"를 가른다.
#    (이게 없으면 정상 재부팅마다 Slack 이 울려 알람이 늑대소년이 된다.)
on_term() {
  local evt; evt=$(new_evt stop); SEQ=1
  emit_kv stop "$evt" "$RATELOG" \
    <<<"reason=signal uptime_s=$(uptime_s) $(vitals) run_evt=$RUN_EVT msg=\"watcher stopping (SIGTERM/SIGINT)\""
  exit 0
}
trap on_term TERM INT

last_capture=0
last_push=0
last_topo=$(date +%s)
PEND=()
SAMPLE_N=0

SEQ=1
emit_kv start "$RUN_EVT" "$RATELOG" <<<"kst=$(ts_kst) devs=\"${!prev[*]}\" interval_s=$INTERVAL threshold_mbs=$THRESHOLD hot_mbs=$HOT beacon_idle_s=$BEACON_IDLE sink=${SINK_HOST:-none}:${SINK_PORT}"
logger -t mp-ioburst "watcher started (devs=${!prev[*]} interval=${INTERVAL}s threshold=${THRESHOLD}MB/s sink=${SINK_HOST:-none}:${SINK_PORT})"
send_topology

while :; do
  sleep "$INTERVAL"
  now=$(date +%s)

  maxrate=0; maxdev=""; devline=""
  while read -r d s; do
    p="${prev[$d]:-}"
    prev["$d"]="$s"
    [ -z "$p" ] && continue
    [ "$s" -lt "$p" ] && continue                  # 카운터 랩/재부팅 방어
    r=$(awk -v a="$p" -v b="$s" -v i="$INTERVAL" 'BEGIN{printf "%.2f", (b-a)*512/1048576/i}')
    k="dev_${d//-/_}"                              # logfmt 키 — LogQL 파서용으로 '-' 제거
    if [[ "$d" =~ $TRIGGER_RE ]]; then
      devline+=" ${k}=${r}"                        # 물리 디스크는 항상 싣는다
      if awk -v a="$r" -v b="$maxrate" 'BEGIN{exit !(a>b)}'; then maxrate="$r"; maxdev="$d"; fi
    else
      # dm-* 는 유의미할 때만 (18개 전부 실으면 유휴 줄이 길어지기만 한다)
      if awk -v v="$r" 'BEGIN{exit !(v>=0.1)}'; then devline+=" ${k}=${r}"; fi
    fi
  done < <(read_all)

  [ -z "$devline" ] && continue

  SAMPLE_N=$((SAMPLE_N + 1))
  # 🔴 sample 줄은 evt=run-… 하나로 묶이고 seq 는 워처 기동 이후 샘플 번호다.
  #    → Loki/파일에서 `seq` 가 건너뛰면 그 구간이 **UDP 로 유실됐다**는 것을 알 수 있다.
  line="ts=$(ts_utc) host=$HOSTLBL kind=sample evt=$RUN_EVT seq=$SAMPLE_N uptime_s=$(uptime_s) $(vitals) read_mbs_max=$maxrate read_dev=${maxdev:-none}$devline"
  PEND+=("$line")

  # 뜨거우면 즉시(손실 상한 = INTERVAL), 아니면 모아서(손실 상한 = BEACON_IDLE).
  hot=$(awk -v r="$maxrate" -v h="$HOT" 'BEGIN{print (r>=h)?1:0}')
  if [ "$hot" = "1" ] || [ $((now - last_push)) -ge "$BEACON_IDLE" ]; then
    # sanitize 를 거치는 이유 = 길이 상한. dm-* 가 많이 활성이면 devline 이 길어질 수 있고,
    # 우리가 안 자르면 logger/rsyslog 가 조용히 잘라 logfmt 중간에서 끊긴다.
    if [ "${#PEND[@]}" -gt 0 ]; then printf '%s\n' "${PEND[@]}" | sanitize | sink_send; fi
    last_push="$now"
    PEND=()
  fi

  # 로컬 링 — 재부팅은 견딘다(급사 후 복귀 시 mp-postmortem 이 회수해 보낸다).
  echo "$line" >>"$RATELOG" 2>/dev/null
  if [ "$(stat -c%s "$RATELOG" 2>/dev/null || echo 0)" -gt "$RATELOG_MAX" ]; then
    tail -n 20000 "$RATELOG" >"$RATELOG.tmp" 2>/dev/null && mv "$RATELOG.tmp" "$RATELOG"
  fi

  over=$(awk -v r="$maxrate" -v t="$THRESHOLD" 'BEGIN{print (r>=t)?1:0}')
  if [ "$over" = "1" ] && [ $((now - last_capture)) -ge "$COOLDOWN" ]; then
    last_capture="$now"
    capture "$maxrate" "$maxdev" "$devline"
    find "$OUT" -name 'burst-*.txt' -mtime "+$RETAIN_DAYS" -delete 2>/dev/null
  fi

  if [ $((now - last_topo)) -ge "$TOPO_INTERVAL" ]; then
    last_topo="$now"
    send_topology
  fi
done
