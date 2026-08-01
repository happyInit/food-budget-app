#!/usr/bin/env bash
# mp-hostwatch-beacon-check — 물리 하이퍼바이저의 **비콘 끊김**을 잡아 Slack 으로 알린다.
#
# 왜 여기(호스트 C)에서 도나: 인클러스터 Alertmanager 는 호스트 B 에 있다. 호스트 B 가 죽으면
#   알림을 보낼 주체가 같이 죽는다. 그래서 알림도 클러스터 **밖**에서 발화해야 한다.
#   Alertmanager 를 하나 더 세우지 않는 이유 = 호스트 C 의 디스크 여유가 28GB 뿐이고
#   그걸 Harbor 이미지와 공유한다(롤 defaults 참조). curl 한 줄이면 되는 일이다.
#
# 판정
#   up      : 마지막 수신이 MAX_AGE 이내 — 정상
#   planned : 오래됐지만 파일 끝에 `kind=stop` 이 있다 → 계획된 종료(재부팅·유지보수)
#             🔴 이게 오탐 억제의 핵심이다. 워처가 SIGTERM 을 받으면 종료 비콘을 남기고,
#                전원이 끊기는 급사에는 남기지 못한다. 그 차이가 곧 판별식이다.
#   down    : 오래됐고 종료 비콘도 없다 → **급사 의심**
#   nodata  : 파일 자체가 없다 → 한 번도 못 받았거나(배포 미완) 파일이 사라졌다
#
# ⚠️ 한계(문서화된 것):
#   · 계획된 재부팅이라도 워처가 SIGKILL 로 끝나면 종료 비콘이 없어 `down` 으로 보고된다.
#     사전에 조용히 하려면 `mp-hostwatch-silence.sh <호스트|all> <분>`.
#   · 판정의 시각 기준은 **파일 mtime**(= 수신 시각)이다. 발신측 시계가 어긋나도 무관하다.
#   · 네트워크만 끊기고 호스트는 살아 있는 경우도 `down` 이다 — 구분 불가.
#     복귀 후 `mp-postmortem` 의 `verdict=` 가 사후에 그걸 갈라 준다(clean 이면 급사 아님).
#
# ⚠️ Ansible 관리 파일 — 원본 = infra/ansible/roles/hostwatch_sink/files/.
set -uo pipefail

DIR="${MP_HOSTWATCH_DIR:-/var/log/mp-hostwatch}"
HOSTS="${MP_HOSTWATCH_HOSTS:-}"                 # 공백 구분 라벨 목록
MAX_AGE="${MP_HOSTWATCH_MAX_AGE_S:-300}"
REPEAT="${MP_HOSTWATCH_REPEAT_S:-3600}"
STATE_DIR="${MP_HOSTWATCH_STATE_DIR:-/var/lib/mp-hostwatch}"
CONF_DIR="${MP_HOSTWATCH_CONF_DIR:-/etc/mp-hostwatch}"
WEBHOOK_FILE="${MP_HOSTWATCH_WEBHOOK_FILE:-$CONF_DIR/slack-webhook}"
TEXTFILE="${MP_HOSTWATCH_TEXTFILE:-/var/lib/node_exporter/textfile_collector/mp_hostwatch.prom}"
SINK_LABEL="${MP_HOSTWATCH_SINK_LABEL:-$(hostname)}"

mkdir -p "$STATE_DIR"
now=$(date +%s)
MODE="${1:-check}"

log() { logger -t mp-hostwatch-beacon "$*"; }

# 🔴 메시지 안의 줄바꿈은 **진짜 개행문자**로 넣는다(NL). slack_post 가 마지막에 `\n` 으로
#    바꾼다. 처음부터 `\n` 문자열로 쓰면 그 앞의 백슬래시 이스케이프 단계에서 `\\n` 이 되어
#    Slack 에 리터럴 `\n` 이 그대로 찍힌다(실제로 걸린 버그).
NL=$'\n'

# ── Slack ───────────────────────────────────────────────────────────────────
# 🔴 실패를 절대 삼키지 않는다. 이 프로젝트에서 "감시하는 줄 알았는데 안 하고 있었다"가
#    여러 번 났다 — 전송 실패는 journal(daemon.err)과 textfile 메트릭 양쪽에 남긴다.
SLACK_OK=1
slack_post() {
  local text="$1" url code
  if [ ! -s "$WEBHOOK_FILE" ]; then
    SLACK_OK=0
    logger -t mp-hostwatch-beacon -p daemon.err \
      "Slack 웹훅 파일이 비었다($WEBHOOK_FILE) — 알림을 못 보낸다. secrets.yml 의 slack_webhook_url 확인"
    return 1
  fi
  url=$(head -1 "$WEBHOOK_FILE")
  # JSON 안전. 🔴 순서가 중요하다: 백슬래시 → 따옴표 → 개행.
  #   개행을 **마지막에** `\n` 으로 바꿔야 앞 단계가 그걸 `\\n` 으로 망가뜨리지 않는다.
  text=${text//\\/\\\\}
  text=${text//\"/\\\"}
  text=${text//$NL/\\n}
  code=$(printf '{"text":"%s"}' "$text" \
          | curl -sS --max-time 10 -o /dev/null -w '%{http_code}' \
                 -X POST -H 'Content-Type: application/json' --data-binary @- "$url" 2>/dev/null)
  if [ "$code" = "200" ]; then
    log "slack sent (http 200)"
    return 0
  fi
  SLACK_OK=0
  logger -t mp-hostwatch-beacon -p daemon.err "slack post 실패 (http=${code:-none})"
  return 1
}

# 침묵 창. `$CONF_DIR/silence`(전체) 또는 `$CONF_DIR/silence.<호스트>`(개별).
#   파일 내용 = 만료 epoch. 비어 있으면 "지울 때까지 무기한".
silenced() {
  local h="$1" f until
  for f in "$CONF_DIR/silence" "$CONF_DIR/silence.$h"; do
    [ -f "$f" ] || continue
    until=$(head -1 "$f" 2>/dev/null | tr -dc '0-9')
    if [ -z "$until" ] || [ "$now" -lt "$until" ]; then return 0; fi
  done
  return 1
}

# ── 호스트별 상태 산출 ──────────────────────────────────────────────────────
declare -A ST AGE
for h in $HOSTS; do
  f="$DIR/$h.log"
  if [ ! -f "$f" ]; then
    ST["$h"]=nodata; AGE["$h"]=-1
    continue
  fi
  m=$(stat -c %Y "$f" 2>/dev/null || echo 0)
  a=$((now - m)); AGE["$h"]=$a
  if [ "$a" -le "$MAX_AGE" ]; then
    ST["$h"]=up
  elif tail -n 5 "$f" 2>/dev/null | grep -q ' kind=stop '; then
    # 워처가 SIGTERM 을 받고 남긴 종료 비콘 = 계획된 종료.
    ST["$h"]=planned
  else
    ST["$h"]=down
  fi
done

# ── 하트비트 모드 ───────────────────────────────────────────────────────────
# 🔴 침묵이 정상인 감시의 유일한 약점 = "죽었는데 아무도 모른다". 하루 한 번 살아 있음을
#    알려 그 약점을 덮는다. 이게 안 오면 웹훅·타이머·호스트 C 중 하나가 죽은 것이다.
if [ "$MODE" = "--heartbeat" ]; then
  txt=":green_heart: *mp-hostwatch 살아 있음* (관측자=$SINK_LABEL, 클러스터 밖)$NL"
  if [ -z "$HOSTS" ]; then
    txt+="• 감시 대상 0 — 인벤토리 [hypervisor] 가 비었다(설정 오류)$NL"
  else
    for h in $HOSTS; do
      txt+="• \`$h\` — ${ST[$h]} (마지막 수신 ${AGE[$h]}초 전)$NL"
    done
  fi
  txt+="_수신 파일: $DIR/<호스트>.log · 보존 ${MP_HOSTWATCH_RETAIN_DAYS:-90}일_"
  slack_post "$txt"
  exit 0
fi

# ── 전이 판정 + 알림 ────────────────────────────────────────────────────────
changed_any=0
for h in $HOSTS; do
  cur="${ST[$h]}" age="${AGE[$h]}"
  sf="$STATE_DIR/$h.state"; nf="$STATE_DIR/$h.notified"
  prev=$(cat "$sf" 2>/dev/null || echo unknown)
  lastn=$(cat "$nf" 2>/dev/null || echo 0)
  [ -n "$lastn" ] || lastn=0

  want=0
  case "$cur" in
    down|nodata)
      # 상태가 바뀌었거나, 계속 죽어 있고 재알림 간격이 지났으면 보낸다.
      if [ "$prev" != "$cur" ] || [ $((now - lastn)) -ge "$REPEAT" ]; then want=1; fi
      ;;
    planned)
      [ "$prev" != "$cur" ] && want=1
      ;;
    up)
      # 복구 알림은 "죽어 있다고 알린 적이 있을 때"만. 첫 실행에서 조용히 시작한다.
      case "$prev" in down|nodata|planned) want=1 ;; esac
      ;;
  esac

  if [ "$want" = "1" ]; then
    if silenced "$h"; then
      log "host=$h state=$cur age=${age}s — 침묵창이라 Slack 생략"
    else
      case "$cur" in
        down)
          msg=":red_circle: *[급사 의심] \`$h\` 비콘 끊김* — 마지막 수신 ${age}초 전 (임계 ${MAX_AGE}초)$NL"
          msg+="종료 비콘(\`kind=stop\`)이 **없다** → 계획된 재부팅이 아니다. 전원 상실·하드행·리셋 후보.$NL"
          msg+="확인: \`sudo tail -50 $DIR/$h.log\` (마지막 vitals = 죽기 직전 상태)$NL"
          msg+="복귀하면 \`kind=postmortem ... verdict=\` 줄이 같은 파일에 붙는다."
          ;;
        nodata)
          msg=":warning: *[증거 없음] \`$h\`* — 수신 파일 \`$DIR/$h.log\` 가 없다.$NL"
          msg+="한 번도 못 받았거나(하이퍼바이저에 롤 미배포) 파일이 사라졌다. **급사 감시가 꺼진 상태.**"
          ;;
        planned)
          msg=":information_source: *[계획된 종료] \`$h\`* — 비콘이 ${age}초 전 끊겼지만 종료 비콘(\`kind=stop\`)이 있다.$NL"
          msg+="정상 재부팅·유지보수로 본다. 돌아오면 복구 알림이 온다."
          ;;
        up)
          msg=":white_check_mark: *[복구] \`$h\` 비콘 재개* — 마지막 수신 ${age}초 전.$NL"
          msg+="직전 종료의 성격은 \`grep 'kind=postmortem' $DIR/$h.log | tail -1\` 의 \`verdict=\` 로 확인."
          ;;
      esac
      slack_post "$msg" && echo "$now" >"$nf"
    fi
    changed_any=1
  fi

  echo "$cur" >"$sf"
  log "host=$h state=$cur age=${age}s prev=$prev notify=$want"
done

# ── node-exporter textfile 메트릭 ───────────────────────────────────────────
# 🔴 이게 **감시자를 감시하는** 고리다. 인클러스터 Prometheus 는 호스트 C 를 job=vm-node 로
#    이미 긁고 있으므로, 이 파일만 떨궈 두면 클러스터가
#    `time() - mp_hostwatch_last_check_timestamp_seconds > 600` 로 **감시 스크립트 자체의
#    사망**을 잡을 수 있다. (클러스터가 C 를 보고 · C 가 물리 A·B 를 본다 = 상호 감시)
tmp="$TEXTFILE.$$"
{
  echo "# HELP mp_hostwatch_beacon_age_seconds 마지막 비콘 수신으로부터 경과(초). -1 = 수신 파일 없음"
  echo "# TYPE mp_hostwatch_beacon_age_seconds gauge"
  for h in $HOSTS; do echo "mp_hostwatch_beacon_age_seconds{host=\"$h\"} ${AGE[$h]}"; done
  echo "# HELP mp_hostwatch_beacon_up 비콘 수신이 임계 이내면 1"
  echo "# TYPE mp_hostwatch_beacon_up gauge"
  for h in $HOSTS; do
    v=0; [ "${ST[$h]}" = "up" ] && v=1
    echo "mp_hostwatch_beacon_up{host=\"$h\"} $v"
  done
  echo "# HELP mp_hostwatch_beacon_planned_stop 종료 비콘이 관측된 정지면 1(계획된 종료)"
  echo "# TYPE mp_hostwatch_beacon_planned_stop gauge"
  for h in $HOSTS; do
    v=0; [ "${ST[$h]}" = "planned" ] && v=1
    echo "mp_hostwatch_beacon_planned_stop{host=\"$h\"} $v"
  done
  echo "# HELP mp_hostwatch_last_check_timestamp_seconds 이 스크립트가 마지막으로 완주한 시각"
  echo "# TYPE mp_hostwatch_last_check_timestamp_seconds gauge"
  echo "mp_hostwatch_last_check_timestamp_seconds $now"
  echo "# HELP mp_hostwatch_slack_delivery_ok 마지막 실행에서 Slack 전송이 실패하지 않았으면 1"
  echo "# TYPE mp_hostwatch_slack_delivery_ok gauge"
  echo "mp_hostwatch_slack_delivery_ok $SLACK_OK"
} >"$tmp" 2>/dev/null
# 원자적 교체 — node-exporter 가 반쯤 쓰인 파일을 읽으면 파싱 에러로 **스크레이프 전체**가 깨진다.
mv -f "$tmp" "$TEXTFILE" 2>/dev/null || rm -f "$tmp"
chmod 0644 "$TEXTFILE" 2>/dev/null

exit 0
