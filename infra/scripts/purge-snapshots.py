#!/usr/bin/env python3
"""alloy 이미지의 압축해제 스냅샷을 chainID 로 지목해 제거한다.

containerd 는 레이어 blob 이 없어도 **chainID 스냅샷이 있으면 unpack 을 건너뛴다**.
그래서 손상된 스냅샷은 이미지 삭제·재pull 로는 사라지지 않는다(재pull 1.1초의 정체).
chainID = diffID 체인의 누적 해시라, config blob 만 있으면 정확히 계산된다.

기본은 dry-run. 실제 삭제는 --apply.
"""
import hashlib
import json
import subprocess
import sys

B = "/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256"
CONFIG = "fa92e0b416b10f70"  # 앞 16자 — 아래에서 실제 파일명을 찾는다
APPLY = "--apply" in sys.argv


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True).stdout


cfg_name = None
for line in sh("sudo", "ls", B).split():
    if line.startswith(CONFIG):
        cfg_name = line
if not cfg_name:
    sys.exit("config blob 을 못 찾았다")

cfg = json.loads(sh("sudo", "cat", f"{B}/{cfg_name}"))
diff_ids = cfg["rootfs"]["diff_ids"]
print(f"diffID {len(diff_ids)}개")

# chainID 계산: c[0]=d[0] · c[i]=sha256("c[i-1] d[i]")
chain, chains = diff_ids[0], []
chains.append(chain)
for d in diff_ids[1:]:
    chain = "sha256:" + hashlib.sha256(f"{chain} {d}".encode()).hexdigest()
    chains.append(chain)

existing = set()
for line in sh("sudo", "ctr", "-n", "k8s.io", "snapshots", "ls").splitlines()[1:]:
    parts = line.split()
    if parts:
        existing.add(parts[0])

targets = [c for c in chains if c in existing]
print(f"실재하는 alloy 스냅샷 {len(targets)}/{len(chains)}개:")
for c in targets:
    print("  ", c)

if not APPLY:
    print("\n(dry-run — 실제 삭제는 --apply)")
    sys.exit(0)

# 자식(깊은 것)부터 지워야 부모가 지워진다
for c in reversed(targets):
    r = subprocess.run(["sudo", "ctr", "-n", "k8s.io", "snapshots", "rm", c],
                       capture_output=True, text=True)
    print(f"  rm {c[:24]}… {'OK' if r.returncode == 0 else r.stderr.strip()[:90]}")
