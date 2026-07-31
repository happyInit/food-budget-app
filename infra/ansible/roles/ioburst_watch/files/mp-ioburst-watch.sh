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
#   2세대(이 파일)는 **모든 관측을 즉시 호스트 B 의 인클러스터 Loki 로 밀어낸다.**
#   로컬 파일은 이제 1순위가 아니라 백업(재부팅은 견디되 디스크 상실은 못 견딤)이다.
#
# 동작
#   ① 비콘  : INTERVAL(기본 15s)마다 /proc/diskstats·loadavg·meminfo·PSI·hwmon 을 읽어
#             logfmt 한 줄로 만든다. 읽기율이 HOT 이상이면 **즉시** push,
#             아니면 BEACON_IDLE(기본 60s) 주기로 모아서 push.
#             → **비콘이 끊긴 시각 = 급사 시각**(해상도: 폭주 중 ≤15s / 유휴 중 ≤60s).
#   ② 덤프  : THRESHOLD(기본 100MB/s) 초과 시 범인 프로세스를 /proc/PID/io 5초 델타로 잡고,
#             **섹션 단위로 쪼개 즉시 push** 한다(캡처 도중 죽어도 앞 섹션은 살아남는다).
#   ③ 토폴로지: 기동 시 + TOPOLOGY_INTERVAL(기본 1h)마다 lsblk·dmsetup·lvs·qm list 를 push.
#             → 인클러스터 Prometheus 가 이미 갖고 있는 `node_disk_read_bytes_total{device="dm-N"}`
#               (게스트 LV 별 읽기량)을 **어느 VM 인지로 번역**할 수 있게 하는 사전이다.
#               dm-N 번호는 재부팅마다 바뀌므로 사후에 만들 수 없다 — 그래서 미리 보낸다.
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
HOT="${MP_IOBURST_HOT:-20}"                    # 이 이상이면 비콘을 모으지 않고 즉시 push
BEACON_IDLE="${MP_IOBURST_BEACON_IDLE:-60}"    # 유휴 시 비콘 flush 주기(초) = 유휴 증거 손실 상한
COOLDOWN="${MP_IOBURST_COOLDOWN:-300}"         # 연속 덤프 억제(초)
RETAIN_DAYS="${MP_IOBURST_RETAIN_DAYS:-14}"    # 로컬 덤프 보존
TOPO_INTERVAL="${MP_IOBURST_TOPOLOGY_INTERVAL:-3600}"
OUT="${MP_IOBURST_DIR:-/var/log/mp-ioburst}"
LOKI_URL="${MP_LOKI_URL:-}"                    # 비면 원격 송출 없이 로컬만 (급사 생존 X)
LOKI_TIMEOUT="${MP_LOKI_TIMEOUT:-5}"
HOSTLBL="${MP_HOST_LABEL:-$(hostname)}"

RATELOG="$OUT/rate.log"
RATELOG_MAX=$((5 * 1024 * 1024))

mkdir -p "$OUT"

ts_utc()   { date -u +%Y-%m-%dT%H:%M:%SZ; }
ts_kst()   { TZ=Asia/Seoul date +%Y-%m-%dT%H:%M:%S+09:00; }
uptime_s() { awk '{printf "%d", $1}' /proc/uptime; }

# ── Loki push ───────────────────────────────────────────────────────────────
# stdin 의 각 줄을 한 엔트리로 만들어 한 번의 요청으로 보낸다.
# 🔴 나노초 타임스탬프를 awk 산술로 만들지 말 것 — 1.78e18 은 double(53bit) 정밀도를 넘겨
#    같은 ts 로 뭉개진다. 초/나노초를 **분리해서** 문자열로 이어 붙인다.
# JSON 이스케이프는 awk 가 아니라 sed 로 한다(awk 의 gsub 치환문자열 백슬래시 규칙은 함정).

# 🔴 JSON 문자열에 그대로 들어가면 파싱이 깨지는 것들을 먼저 없앤다.
#    실측으로 걸린 사고 — `top`·`iostat` 출력의 **리터럴 탭(0x09)** 이 그대로 실려
#    "Invalid control character" 로 push 가 통째로 거부됐다. 개행(0x0A)만 남기고
#    나머지 제어문자는 전부 죽인다(탭은 공백으로 치환 — 지우면 열이 붙어 읽기 어렵다).
#    iconv -c 는 cut 이 UTF-8 문자를 반토막 냈을 때 생기는 깨진 바이트를 걷어낸다.
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
  # 실패는 journal 에만 남는다(로컬). 배포 시점 도달성은 롤이 uri 태스크로 단언한다.
  logger -t mp-ioburst -p daemon.err "loki push failed (kind=$kind url=$LOKI_URL)"
  return 1
}

# stdin → **Loki 우선**, 그 다음 로컬 파일.
# 🔴 순서가 중요하다. 이 유닛은 IOSchedulingClass=idle 이라 폭주 중 로컬 쓰기가 수 분 막힐 수
#    있는데, 로컬을 먼저 쓰면 정작 중요한 원격 송출이 그 뒤에서 굶는다.
emit() {
  local kind="$1" file="$2" buf
  buf=$(cat)
  [ -z "$buf" ] && return 0
  printf '%s\n' "$buf" | loki_push "$kind"
  printf '%s\n' "$buf" >>"$file" 2>/dev/null
}

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
topology() {
  echo "kind=topology host=$HOSTLBL utc=$(ts_utc)"
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
# 🔴 섹션마다 즉시 push 한다. 캡처 전체(≈10초)를 다 모으고 한 번에 보내면,
#    그 10초 안에 호스트가 죽었을 때 **증거 전부**를 잃는다.
capture() {
  local rate="$1" dev="$2" all="$3" stamp f a b
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  f="$OUT/burst-$stamp.txt"

  # [0] 헤더 — 즉시(0초). 최소한 "언제·어느 장치·얼마나"는 무조건 밖에 남는다.
  {
    echo "kind=burst event=start host=$HOSTLBL utc=$(ts_utc) kst=$(ts_kst) dev=$dev read_mbs=$rate threshold=$THRESHOLD file=$f"
    echo "kind=burst event=vitals host=$HOSTLBL $(vitals) uptime_s=$(uptime_s)$all"
    echo "----- I/O 압력(PSI) -----"
    cat /proc/pressure/io 2>/dev/null
  } | emit burst "$f"

  # [1] 범인 프로세스 (5초 델타) — 이 덤프의 존재 이유. 두 번째로 보낸다.
  a=$(snap_io); sleep 5; b=$(snap_io)
  {
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
  } | emit burst "$f"

  # [2] 워크로드·토폴로지 — pid 를 VM/컨테이너로 번역하는 재료
  { workloads; topology; } | emit burst "$f"

  # [3] 교차검증 (sysstat 없으면 조용히 비어 나온다 — 없어도 [1] 로 결론은 난다)
  {
    echo "----- [3] pidstat -d (교차검증) -----"
    pidstat -d 1 3 2>/dev/null | tail -25
    echo "----- [4] iostat -x -----"
    iostat -x 1 2 2>/dev/null | tail -30
  } | emit burst "$f"

  # [4] 마감
  {
    echo "----- [5] 상위 CPU/메모리 -----"
    top -bn1 2>/dev/null | head -20
    echo "----- [6] 마운트/여유 -----"
    df -h 2>/dev/null | grep -vE 'tmpfs|overlay'
    echo "kind=burst event=end host=$HOSTLBL utc=$(ts_utc) file=$f"
  } | emit burst "$f"

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

last_capture=0
last_push=0
last_topo=$(date +%s)
PEND=()

printf 'kind=start host=%s utc=%s kst=%s devs="%s" interval_s=%s threshold_mbs=%s hot_mbs=%s beacon_idle_s=%s loki=%s\n' \
  "$HOSTLBL" "$(ts_utc)" "$(ts_kst)" "${!prev[*]}" "$INTERVAL" "$THRESHOLD" "$HOT" "$BEACON_IDLE" "${LOKI_URL:-none}" \
  | loki_push start
logger -t mp-ioburst "watcher started (devs=${!prev[*]} interval=${INTERVAL}s threshold=${THRESHOLD}MB/s loki=${LOKI_URL:-none})"
topology | emit topology "$OUT/topology.log"

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

  line="ts=$(ts_utc) host=$HOSTLBL kind=sample uptime_s=$(uptime_s) $(vitals) read_mbs_max=$maxrate read_dev=${maxdev:-none}$devline"
  PEND+=("$line")

  # 뜨거우면 즉시(손실 상한 = INTERVAL), 아니면 모아서(손실 상한 = BEACON_IDLE).
  hot=$(awk -v r="$maxrate" -v h="$HOT" 'BEGIN{print (r>=h)?1:0}')
  if [ "$hot" = "1" ] || [ $((now - last_push)) -ge "$BEACON_IDLE" ]; then
    if [ "${#PEND[@]}" -gt 0 ]; then printf '%s\n' "${PEND[@]}" | loki_push sample; fi
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
    topology | emit topology "$OUT/topology.log"
  fi
done
