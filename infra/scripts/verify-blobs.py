#!/usr/bin/env python3
"""containerd 콘텐츠 스토어의 alloy 이미지 blob 무결성 검사 (읽기 전용).

blob 파일명이 곧 sha256 이므로, 다시 해시해서 이름과 다르면 그 blob 이 손상된 것이다.
containerd 는 pull 시점에만 검증하고 이후엔 재검증하지 않으므로 이런 손상은 조용히 남는다.
"""
import hashlib
import json
import subprocess
import sys

B = "/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256"
INDEX = "491b0578c04983fd54fe99b587b6fab4404dc46d0dc16677bd6b00cc1140b308"


def read(digest):
    return subprocess.run(["sudo", "cat", f"{B}/{digest}"], capture_output=True).stdout


def verify(digest, label):
    data = read(digest)
    if not data:
        print(f"  {label:<22} {digest[:16]}… 없음")
        return None
    actual = hashlib.sha256(data).hexdigest()
    ok = actual == digest
    print(f"  {label:<22} {digest[:16]}… {'OK' if ok else '🔴 손상 → ' + actual[:16]}  ({len(data):,}B)")
    return data if ok else None


idx = json.loads(read(INDEX))
target = None
for m in idx["manifests"]:
    p = m.get("platform", {})
    if p.get("architecture") == "amd64" and p.get("os") == "linux":
        target = m["digest"].split(":")[1]
print(f"amd64 매니페스트 = {target[:16]}…")

data = verify(target, "manifest")
if not data:
    sys.exit("매니페스트가 손상돼 레이어를 못 읽는다")

man = json.loads(data)
verify(man["config"]["digest"].split(":")[1], "config")
print(f"레이어 {len(man['layers'])}개:")
bad = 0
for i, layer in enumerate(man["layers"]):
    if verify(layer["digest"].split(":")[1], f"layer[{i}]") is None:
        bad += 1
print(f"\n결과: 손상 blob {bad}개")
