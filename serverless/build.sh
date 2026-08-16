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
while read -r m; do
  [ -z "$m" ] && continue; case "$m" in \#*) continue;; esac
  src="$ROOT/$m"
  [ -f "$src" ] || { echo "❌ manifest 항목 없음: $m"; exit 1; }
  cp "$src" "$OUT/"
done < "$MAN"

find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" -name '*.dist-info' -type d -prune -exec rm -rf {} + 2>/dev/null || true

SIZE=$(du -sb "$OUT" | cut -f1)
printf "✅ %s  압축해제 %.1f MB  (Lambda 상한: 직접 50MB 압축 · S3 경유 250MB 해제)\n" \
       "$FN" "$(echo "$SIZE/1048576" | bc -l)"
echo "   → $OUT"
