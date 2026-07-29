#!/usr/bin/env python3
"""Committed 레이어(chainID) 전수 트리해시 — 노드 간 대조용 (읽기 전용).

chainID 는 "이 레이어의 내용"의 신원이라 **어느 노드에서든 같은 내용**이어야 한다.
그래서 노드 간 해시 대조가 곧 무결성 검증이다(레이어 blob 은 unpack 후 버려져 다른 검증 수단이 없다).

매핑 방법: containerd 는 Committed 스냅샷에 mounts 를 주지 않는다(Active 전용).
→ Active 스냅샷의 lowerdir 목록(위→아래 순서)과 PARENT 체인을 정렬해 chainID→디렉토리를 얻는다.
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = "/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots"
OUT = sys.argv[1]
CHUNK = 1 << 20


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout


parent, kind = {}, {}
for line in sh("sudo", "ctr", "-n", "k8s.io", "snapshots", "ls").splitlines()[1:]:
    p = line.split()
    if len(p) >= 3:
        parent[p[0]], kind[p[0]] = p[1], p[2]
    elif len(p) == 2:
        parent[p[0]], kind[p[0]] = "", p[1]

chain_dir = {}
for k, kd in kind.items():
    if kd != "Active":
        continue
    out = sh("sudo", "ctr", "-n", "k8s.io", "snapshots", "mounts", "/tmp/_none", k)
    lowers = []
    for token in out.replace(",", " ").split():
        if token.startswith("lowerdir="):
            lowers = [x for x in token[len("lowerdir="):].split(":") if "/snapshots/" in x]
    cur = parent.get(k, "")
    for d in lowers:  # lowerdir 은 위(자식)→아래(부모) 순서 = 부모 체인과 같은 순서
        if not cur:
            break
        chain_dir.setdefault(cur, d.split("/snapshots/")[1].split("/")[0])
        cur = parent.get(cur, "")

res, errs = {}, 0
for chain, d in chain_dir.items():
    base = os.path.join(ROOT, d, "fs")
    h = hashlib.sha256()
    files = []
    for dirpath, dirnames, filenames in os.walk(base, onerror=lambda e: None):
        dirnames.sort()
        files.extend(os.path.join(dirpath, n) for n in sorted(filenames))
    for path in files:
        rel = os.path.relpath(path, base).encode()
        h.update(len(rel).to_bytes(4, "big") + rel)
        try:
            if os.path.islink(path):
                h.update(b"L" + os.readlink(path).encode())
                continue
            with open(path, "rb") as f:
                while True:
                    b = f.read(CHUNK)
                    if not b:
                        break
                    h.update(b)
        except OSError:
            errs += 1
            h.update(b"?ERR")
    res[chain] = {"hash": h.hexdigest(), "files": len(files)}

json.dump({"layers": res, "read_errors": errs}, open(OUT, "w"))
print(f"Committed 레이어 {len(res)}개 해시 (읽기 실패 {errs}건) → {OUT}")
