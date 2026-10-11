#!/usr/bin/env python3
"""Publish dashboard/diagnostics/**.json to a Hugging Face dataset repo as
zstd-compressed <name>.json.zst, uploading only the files that changed.

Why off GitHub Pages: the diagnostics tree (~10 GB raw, 2.3 GB gzipped) made
every Pages deploy re-upload the whole site (3–6 min). Pages now serves only
index.html + data.json; index.html's diagFetch() reads diagnostics from the
dataset at the commit named in diag_source.json, which this script writes, so
a deploy's data.json and diagnostics always match.

Why zstd -19: 38% smaller than gzip -6 on the large files, and the browser
decodes it with fzstd. Level 19 is slow (~2 MB/s per core), which only matters
on a full rebuild of the mirror — normal deploys compress a few dozen files.

Local state lives in <mirror>: diagnostics/<rel>.json.zst plus manifest.json
{"head": <dataset commit>, "files": {rel: [size, mtime_ns]}}. The manifest is
trusted only while the dataset is still at that commit; otherwise every file
is recompressed and re-uploaded (Xet dedup makes identical content cheap).
It is saved after every upload batch, so an interrupted deploy resumes.

Usage: publish_diagnostics.py <src diagnostics dir> <mirror dir> <repo id> <diag_source.json out>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

BATCH_FILES = 400
BATCH_BYTES = 400 * 2**20


def _zstd(src: Path, dst: Path) -> None:
    # Single-threaded zstd CLI output is byte-identical across runs (same zstd
    # version), so recompressing an unchanged file never creates a new blob.
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    with open(tmp, "wb") as out:
        subprocess.run(["zstd", "-19", "-q", "-c", str(src)], stdout=out, check=True)
    os.replace(tmp, dst)


def _repo_path(rel: str) -> str:
    return f"diagnostics/{rel}.zst"


def publish(src_root: Path, mirror: Path, repo: str, source_out: Path) -> None:
    api = HfApi()
    # Public: the dashboard page fetches these anonymously from the browser.
    api.create_repo(repo, repo_type="dataset", private=False, exist_ok=True)
    head = api.repo_info(repo, repo_type="dataset").sha

    manifest_path = mirror / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        manifest = {}
    if manifest.get("head") == head:
        published: dict[str, list[int]] = manifest["files"]
        remote = set(published)
    else:
        print("  manifest stale or missing: full recompress + upload")
        published = {}
        remote = {p[len("diagnostics/"):-len(".zst")]
                  for p in api.list_repo_files(repo, repo_type="dataset")
                  if p.startswith("diagnostics/") and p.endswith(".zst")}

    wanted: dict[str, list[int]] = {}
    for src in src_root.rglob("*.json"):
        st = src.stat()
        wanted[src.relative_to(src_root).as_posix()] = [st.st_size, st.st_mtime_ns]
    todo = sorted(rel for rel, sig in wanted.items()
                  if published.get(rel) != sig or not (mirror / _repo_path(rel)).exists())
    gone = sorted(remote - set(wanted))

    # Upload set = `todo`; compress only what the mirror lacks or has older than
    # its source (an interrupted run leaves valid .zst files behind).
    def stale(rel: str) -> bool:
        dst = mirror / _repo_path(rel)
        return not dst.exists() or dst.stat().st_mtime_ns < wanted[rel][1]
    to_compress = [rel for rel in todo if stale(rel)]
    print(f"  compressing {len(to_compress)} files (zstd -19), uploading {len(todo)}…")
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        list(pool.map(lambda rel: _zstd(src_root / rel, mirror / _repo_path(rel)), to_compress))

    ops: list[tuple[str, object]] = (
        [(rel, CommitOperationDelete(path_in_repo=_repo_path(rel))) for rel in gone]
        + [(rel, CommitOperationAdd(path_in_repo=_repo_path(rel),
                                    path_or_fileobj=str(mirror / _repo_path(rel)))) for rel in todo])
    batches: list[list[tuple[str, object]]] = []
    size = 0
    for item in ops:
        n = (mirror / _repo_path(item[0])).stat().st_size if isinstance(item[1], CommitOperationAdd) else 0
        if not batches or len(batches[-1]) >= BATCH_FILES or size + n > BATCH_BYTES:
            batches.append([])
            size = 0
        batches[-1].append(item)
        size += n

    for i, batch in enumerate(batches, 1):
        info = api.create_commit(
            repo, repo_type="dataset", operations=[op for _, op in batch],
            commit_message=f"Dashboard diagnostics ({i}/{len(batches)})")
        head = info.oid
        for rel, op in batch:
            if isinstance(op, CommitOperationDelete):
                published.pop(rel, None)
                (mirror / _repo_path(rel)).unlink(missing_ok=True)
            else:
                published[rel] = wanted[rel]
        manifest_path.write_text(json.dumps({"head": head, "files": published}))
        print(f"  uploaded batch {i}/{len(batches)} ({len(batch)} files) → {head[:10]}")
    if not batches:
        manifest_path.write_text(json.dumps({"head": head, "files": published}))

    print(f"  {len(todo)} uploaded, {len(gone)} deleted, {len(wanted) - len(todo)} unchanged")
    source_out.write_text(json.dumps({
        "repo": repo,
        "revision": head,
        "base": f"https://huggingface.co/datasets/{repo}/resolve/{head}/",
    }))


if __name__ == "__main__":
    publish(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
