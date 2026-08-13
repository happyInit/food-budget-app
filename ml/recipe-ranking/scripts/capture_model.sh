#!/usr/bin/env bash
# 랭킹 모델 아티팩트 확보 — 체크리스트 `1-21` 의 "모델 사본 정책" 선행.
#
# 왜 필요한가: `ranker.pkl` 이 **PVC 단 한 곳**에만 있다.
#   git      ❌ gitignored (`ml/recipe-ranking/.gitignore` `*.pkl`)
#   이미지    ❌ 없음 (C-20 으로 굽기 전까지)
#   MinIO    ❌ `models` 버킷 0 바이트 (`1-21` 실측)
# ⇒ **PVC 가 날아가면 모델이 소멸한다.** 그리고 지금은 재생성도 못 한다 —
#    클릭스트림 라벨이 0이라 `retrain.py` 가 콜드스타트 skip 으로 끝난다.
#
# C-20(모델을 이미지에 굽기)의 선행이기도 하다 — 빌드 시점에 파일을 가질 수 있어야 굽는다.
# 🔴 최종 보관처(S3 버킷)는 아직 미정이다 — 계획서 §9 ① (C-68 인벤토리에 자리가 없다).
#    그때까지 이 스크립트는 **꺼내서 해시를 기록**하는 데까지만 한다.
#
# 사용:
#   ./scripts/capture_model.sh                 # 꺼내기 + 해시 출력
#   ./scripts/capture_model.sh --verify        # 매니페스트와 대조만 (변조·드리프트 감지)
#
# 읽기 전용이다 — 클러스터를 바꾸지 않는다.
set -euo pipefail

NS="${RANKING_NS:-app}"
SELECTOR="${RANKING_SELECTOR:-app=ranking-serving}"
REMOTE_PATH="${RANKING_MODEL_PATH:-/models/ranker.pkl}"
OUT_DIR="${OUT_DIR:-artifacts}"
MANIFEST="$(dirname "$0")/../MODEL_MANIFEST.txt"

pod="$(kubectl -n "$NS" get pod -l "$SELECTOR" -o name | head -1)"
[ -n "$pod" ] || { echo "🔴 파드를 못 찾았다 (ns=$NS selector=$SELECTOR)" >&2; exit 1; }
pod="${pod#pod/}"

# 해시는 **파드 안에서** 낸다 — 전송 중 손상을 잡기 위해 원본 쪽 값을 기준으로 둔다.
remote_sha="$(kubectl -n "$NS" exec "$pod" -- python3 -c "
import hashlib,sys
print(hashlib.sha256(open('$REMOTE_PATH','rb').read()).hexdigest())")"
remote_size="$(kubectl -n "$NS" exec "$pod" -- python3 -c "
import os;print(os.path.getsize('$REMOTE_PATH'))")"

if [ "${1:-}" = "--verify" ]; then
  [ -f "$MANIFEST" ] || { echo "🔴 매니페스트가 없다: $MANIFEST" >&2; exit 1; }
  known="$(awk '/^sha256/{print $2}' "$MANIFEST")"
  if [ "$known" = "$remote_sha" ]; then
    echo "✅ 일치 — $remote_sha"
  else
    echo "🔴 불일치 (모델이 바뀌었다)"; echo "  매니페스트 $known"; echo "  라이브     $remote_sha"
    exit 1
  fi
  exit 0
fi

mkdir -p "$OUT_DIR"
local_file="$OUT_DIR/ranker.pkl"
kubectl -n "$NS" exec "$pod" -- cat "$REMOTE_PATH" > "$local_file"

local_sha="$(sha256sum "$local_file" | awk '{print $1}')"
[ "$local_sha" = "$remote_sha" ] || {
  echo "🔴 전송 중 손상 — 원본 $remote_sha / 사본 $local_sha" >&2; exit 1; }

echo "✅ 확보: $local_file"
echo "   sha256 $local_sha"
echo "   bytes  $remote_size"
echo
echo "🔴 이 파일은 gitignored 다. 최종 보관처는 계획서 §9 ① 결정 후 —"
echo "   그때까지 팀 내부 채널로 보관하거나 재실행으로 다시 꺼낸다."
