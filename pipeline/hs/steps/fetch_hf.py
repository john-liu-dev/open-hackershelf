"""步骤 1：下载 open-index/hacker-news 的月度 parquet，校验后只保留需要的列。

- 文件清单、大小、sha256 取自 huggingface.co 官方 API（revision 固定在 config.toml）。
- 文件本体从 download_base（默认 hf-mirror.com，直连更快）分段并发下载，逐个校验 sha256；
  不符则改从官方地址重下一次。完整文件留在 data/cache/hf/<revision>/（可删，可重下）。
- 投影到 config.hn.columns，写 data/raw/hn/hf/YYYY-MM.parquet（原子改名，已存在则跳过）。

用法：uv run python -m hs.steps.fetch_hf [--months 2024-01 ...] [--files 2] [--segments 6]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pyarrow.parquet as pq

from hs.config import PATHS, cfg
from hs.http import Http


def month_range(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    ly, lm = map(int, last.split("-"))
    out = []
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def official_listing(http: Http) -> dict[str, dict]:
    c = cfg()["hn"]
    url = f"{c['official_base']}/api/datasets/{c['hf_repo']}/revision/{c['hf_revision']}?blobs=true"
    r = http.get(url)  # 固定 revision，缓存永久有效
    r.raise_for_status()
    return {s["rfilename"]: s for s in r.json()["siblings"]}


def resolve_url(base: str, rfilename: str) -> str:
    c = cfg()["hn"]
    return f"{base}/datasets/{c['hf_repo']}/resolve/{c['hf_revision']}/{rfilename}"


def project(src, dest) -> int:
    pf = pq.ParquetFile(src)
    cols = [c for c in cfg()["hn"]["columns"] if c in pf.schema_arrow.names]
    table = pf.read(columns=cols)
    tmp = dest.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd", compression_level=6, row_group_size=256_000)
    tmp.replace(dest)
    return table.num_rows


def _take_lock(lock) -> bool:
    """同一个月只允许一个进程下载（两个下载进程并行时用）。锁文件里写 pid，进程不在了就接管。"""
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            os.kill(int(lock.read_text() or 0), 0)
            return False
        except (ProcessLookupError, ValueError):
            lock.write_text(str(os.getpid()))
            return True
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def fetch_month(http: Http, listing: dict, month: str, segments: int, source: str) -> dict:
    c = cfg()["hn"]
    dest = PATHS.hn_raw / f"{month}.parquet"
    if dest.exists():
        return {"month": month, "rows": pq.ParquetFile(dest).metadata.num_rows, "skipped": True}
    rf = f"data/{month[:4]}/{month}.parquet"
    meta = listing[rf]
    size, sha = meta["size"], meta.get("lfs", {}).get("sha256")
    full = PATHS.cache / "hf" / c["hf_revision"] / rf
    lock = full.with_name(full.name + ".lock")
    if not _take_lock(lock):
        return {"month": month, "rows": 0, "skipped": True, "busy": True}
    try:
        t0 = time.time()
        try:
            http.download_segmented(resolve_url(source, rf), full, size=size, sha256=sha, workers=segments)
        except Exception as e:  # noqa: BLE001 — 镜像失败或校验不符，改走官方
            if source == c["official_base"]:
                raise
            print(f"  {month}: 镜像下载失败（{e!r}），改从官方重下", flush=True)
            source = c["official_base"]
            http.download_segmented(resolve_url(source, rf), full, size=size, sha256=sha, workers=segments)
        dest.parent.mkdir(parents=True, exist_ok=True)
        rows = project(full, dest)
    finally:
        lock.unlink(missing_ok=True)
    return {"month": month, "rows": rows, "bytes": size, "sha256": sha, "source": source,
            "secs": round(time.time() - t0, 1), "skipped": False}


def main(argv: list[str] | None = None) -> int:
    c = cfg()["hn"]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--months", nargs="*", help="只拉这些月（YYYY-MM）；默认全部")
    ap.add_argument("--files", type=int, default=2, help="同时下载几个文件")
    ap.add_argument("--segments", type=int, default=6, help="每个文件几段并发")
    ap.add_argument("--min-free-gb", type=float, default=30.0, help="磁盘空闲低于这个值就停止下载")
    ap.add_argument("--source", choices=["mirror", "official"], default="mirror")
    ap.add_argument("--order", choices=["desc", "asc"], default="desc", help="desc = 新的先下")
    args = ap.parse_args(argv)
    months = args.months or month_range(c["first_month"], c["last_month"])
    months = sorted(months, reverse=args.order == "desc")  # 默认新的先下：增量核对要先用到 2026-08
    source = c["download_base"] if args.source == "mirror" else c["official_base"]
    http = Http()
    listing = official_listing(http)
    stats_dest = PATHS.hn_raw / "stats.csv"
    if not stats_dest.exists():
        stats_dest.parent.mkdir(parents=True, exist_ok=True)
        http.download(resolve_url(c["official_base"], "stats.csv"), stats_dest)

    results, failed = [], []
    t0 = time.time()
    with ThreadPoolExecutor(args.files) as ex:
        futs = {}
        for m in months:
            futs[ex.submit(fetch_month, http, listing, m, args.segments, source)] = m
        for i, fut in enumerate(as_completed(futs), 1):
            m = futs[fut]
            try:
                r = fut.result()
                results.append(r)
                if r.get("busy"):
                    print(f"[{i}/{len(months)}] {m} 另一个进程在下，跳过", flush=True)
                elif not r["skipped"]:
                    mb = http.stats["bytes"] / 1e6
                    print(f"[{i}/{len(months)}] {m} rows={r['rows']:,} {r['bytes']/1e6:.0f}MB {r['secs']}s "
                          f"total={mb:,.0f}MB avg={mb/(time.time()-t0):.2f}MB/s", flush=True)
            except Exception as e:  # noqa: BLE001
                failed.append((m, repr(e)))
                print(f"[{i}/{len(months)}] {m} FAILED {e!r}", flush=True)
            free_gb = shutil.disk_usage(PATHS.data).free / 1e9
            if free_gb < args.min_free_gb:
                print(f"磁盘空闲 {free_gb:.1f} GB < {args.min_free_gb} GB，停止下载", flush=True)
                for f in futs:
                    f.cancel()
                break
    manifest = PATHS.hn_raw / "_manifest.json"
    old = json.loads(manifest.read_text()) if manifest.exists() else {}
    files = old.get("files", {})
    for r in results:
        if r.get("busy"):
            continue
        if not r["skipped"]:
            files[r["month"]] = {k: r[k] for k in ("rows", "bytes", "sha256", "source")}
        else:
            files.setdefault(r["month"], {"rows": r["rows"]})
    manifest.write_text(json.dumps({
        "repo": c["hf_repo"], "revision": c["hf_revision"], "columns": c["columns"],
        "files": dict(sorted(files.items())), "failed": failed,
    }, indent=1))
    print(f"done: {len(results)} ok, {len(failed)} failed, http={http.stats}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
