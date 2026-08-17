#!/usr/bin/env bash
# Lambda 배포 패키지 빌드 — **목표 환경(py3.12 · aarch64)으로 못박아 받는다.**
#
# 왜 `--platform` 을 쓰는가 = 빌드하는 기계가 x86 이라 그냥 설치하면 **x86 휠**이 들어간다.
# 그대로 올리면 Lambda(arm64)에서 `invalid ELF header` 로 죽고, 그 실패는 **첫 호출에서야** 난다.
#
# 왜 `--python-version` 을 쓰는가 = 빌드 기계의 파이썬이 3.14 여도 Lambda 는 3.12 다.
# 명시하지 않으면 pip 가 3.14 용 휠을 고르거나 "없다"고 거짓 보고한다(실측 2026-08-14 — 처음에
# 전 패키지가 «휠 없음» 으로 나왔는데 원인이 이것이었다).
#
# 사용:  serverless/build.sh <함수디렉터리명>       예) serverless/build.sh ai_shelflife_draft
#        OUT=/tmp/pkg serverless/build.sh ai_shelflife_draft
set -euo pipefail

FN="${1:?함수 디렉터리명이 필요하다 — 예) ai_shelflife_draft}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/serverless/$FN"
OUT="${OUT:-$ROOT/.build/$FN}"

PY_VER="${PY_VER:-3.12}"
WHEEL_TAG="${WHEEL_TAG:-manylinux2014_aarch64}"   # C-29 Graviton 정합

[ -d "$SRC" ] || { echo "❌ $SRC 없음"; exit 1; }

rm -rf "$OUT"; mkdir -p "$OUT"

# ── 의존성 ───────────────────────────────────────────────────────────────────
# 함수 디렉터리에 requirements.txt 가 있으면 그걸, 없으면 배치 공통을 쓴다.
REQ="$SRC/requirements.txt"
[ -f "$REQ" ] || REQ="$ROOT/serverless/requirements-batch.txt"
echo "▶ 의존성 ← $(basename "$REQ")  (해석=py$PY_VER · 휠=$WHEEL_TAG)"

# 🔴 **호스트에서 받는다. 대신 requirements 가 전이 의존성까지 전부 못박은 락 파일이다.**
#    컨테이너 안에서 받는 편이 이론상 정확하지만 이 환경은 컨테이너에 DNS 가 없다(실측).
#    그래서 «해석» 을 pip 에게 맡기지 않는 쪽으로 푼다 — 마커 평가가 개입할 여지가 없어진다.
#    ⚠️ 의존성을 추가할 때는 **그 패키지의 전이 의존성도 같이 적어야 한다.**
pip download --quiet --dest "$OUT/.whl" --no-deps \
    --platform "$WHEEL_TAG" --python-version "$PY_VER" --only-binary=:all: \
    -r "$REQ"

for w in "$OUT/.whl"/*.whl; do python3 -m zipfile -e "$w" "$OUT" ; done
rm -rf "$OUT/.whl"

# ── 코드 ─────────────────────────────────────────────────────────────────────
# 🔴 번들 루트가 곧 import 루트다. 레포 트리를 그대로 옮기지 않고 **평평하게** 넣는다.
#    핸들러의 sys.path 보정 블록이 레포/번들 양쪽에서 도는 이유가 이것이다.
cp "$SRC"/*.py                    "$OUT/"
mkdir -p "$OUT/common"
cp "$ROOT/serverless/common"/*.py "$OUT/common/"

# 🔴 레포 모듈은 **manifest 에 적힌 것만** 넣는다. `pipelines/ingest/*.py` 를 통째로 넣으면
#    쓰지도 않는 20여 개가 딸려오고(크롤·적재 스크립트), 그것들의 import 가 번들에 없는
#    패키지를 요구해 **첫 호출에서 ImportError** 가 난다. 넣는 것을 명시적으로 고른다.
MAN="$SRC/modules.txt"
[ -f "$MAN" ] || { echo "❌ $MAN 없음 — 넣을 레포 모듈을 명시해야 한다"; exit 1; }
# 🔵 **디렉터리도 받는다**(2026-08-17). 배치 5종·video 2종은 평면 파일로 충분했지만,
#    `chat`·`ocr` 은 앱이 **패키지 구조**(`app/pipeline/…`)라 평면으로 풀면 import 가 깨진다.
#    항목이 `services/chat/app` 처럼 디렉터리면 **그 basename 그대로** 번들 루트에 통째로 넣는다
#    → 번들 루트에 `app/` 이 서고 `from app.config import …` 가 그대로 성립한다.
#    ⚠️ 디렉터리를 넣을 때는 그 안에 **쓰지 않는 것이 딸려오지 않는지** 직접 볼 것.
#       평면 파일 방식의 «명시적으로 고른다» 성질이 그만큼 약해진다.
# 🔵 `-` 로 시작하는 줄은 **번들에서 도로 빼는** 경로다(디렉터리를 담을 때만 의미가 있다).
#    디렉터리 통째로 담기의 대가는 «안 쓰는 것이 딸려온다» 인데, 그게 단순한 낭비로만
#    끝나지 않는다 — 안 쓰는 파일이 최상단에서 import 하는 패키지가 의존성 검사에 잡혀
#    «없는 의존성» 으로 보고되고, 그걸 달래려고 **쓰지도 않는 패키지를 번들에 넣게** 된다
#    (실제로 `ocr` 워커의 `app/main.py` 가 fastapi 를 요구했다).
#    ⇒ 담지 않는 편이 정직하다. 실수로 import 하면 조용히 도는 대신 즉시 터진다.
EXCLUDES=""
while read -r m; do
  [ -z "$m" ] && continue; case "$m" in \#*) continue;; esac
  case "$m" in -*) EXCLUDES="$EXCLUDES ${m#-}"; continue;; esac
  src="$ROOT/$m"
  if [ -d "$src" ]; then
    # 🔴 `-L` 이 없으면 안 된다 — **심볼릭 링크를 링크째 복사해서 번들 안에서 끊어진다.**
    #    `services/chat/app/vendor/{_db,gazetteer,quantity}.py` 는 전부
    #    `../../../../pipelines/ingest/*.py` 를 가리키는 링크다(recipe·ocr 도 같은 패턴).
    #    링크로 넣으면 번들에는 그 상대경로가 존재하지 않아 **첫 호출에서**
    #    `ModuleNotFoundError: No module named 'app.vendor.quantity'` 로 죽는다.
    #    빌드는 성공하고 크기도 정상으로 보인다 — 그래서 아래 가드로 한 번 더 막는다.
    cp -RL "$src" "$OUT/$(basename "$m")"
  elif [ -f "$src" ]; then
    cp -L "$src" "$OUT/"
  else
    echo "❌ manifest 항목 없음: $m"; exit 1
  fi
done < "$MAN"

for x in $EXCLUDES; do
  # manifest 는 레포 경로로 적고, 번들에서는 담긴 디렉터리의 basename 아래에 있다.
  # 예) `-services/ocr/app/main.py` → 번들의 `app/main.py`
  rel="${x#*/}"; rel="${rel#*/}"           # services/<svc>/ 두 칸을 벗긴다
  [ -e "$OUT/$rel" ] || { echo "❌ 제외 대상이 번들에 없다: $x (→ $rel)"; exit 1; }
  rm -rf "$OUT/$rel"
  echo "   − 제외: $rel"
done

find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" -name '*.dist-info' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# ── 가드: 번들에 심볼릭 링크가 남으면 실패시킨다 ─────────────────────────────
# 🔴 이 실패는 **배포 후 첫 호출에서야** 드러난다(빌드는 성공하고 크기도 정상이다).
#    그래서 여기서 못 지나가게 한다. `-L` 이 도로 빠지거나, 앞으로 링크를 쓰는 다른
#    서비스(recipe·ocr 도 같은 vendor 패턴이다)를 담을 때 같은 사고를 막는 자리다.
LINKS=$(find "$OUT" -type l)
if [ -n "$LINKS" ]; then
  echo "❌ 번들에 심볼릭 링크가 남았다 — Lambda 에서 import 가 깨진다:"; echo "$LINKS"; exit 1
fi

SIZE=$(du -sb "$OUT" | cut -f1)
printf "✅ %s  압축해제 %.1f MB  (Lambda 상한: 직접 50MB 압축 · S3 경유 250MB 해제)\n" \
       "$FN" "$(echo "$SIZE/1048576" | bc -l)"
echo "   → $OUT"
