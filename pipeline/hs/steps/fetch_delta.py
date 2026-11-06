"""步骤 2：用 HN Algolia API 补 HF 存档停更之后的 story 和 comment，转成和 HF 相同的 schema。

- 按 UTC 自然日切片；日内按时间倒序游标翻页（每页 1000 条，上界取本页最早时间，按 objectID 去重），
  绕开单次查询 1000 条的上限。整日窗口的请求 URL 固定，重跑时命中磁盘缓存。
- 每天写一个 data/raw/hn/delta/YYYY-MM-DD.parquet（已存在则跳过，原子改名）。
- Algolia 不收录 dead / deleted 条目，所以 dead=deleted=0；comment 没有 score，story 的 descendants 用 num_comments。
- 默认从 delta.overlap_start（与 HF 重叠，用于核对）抓到昨天（UTC）。

用法：uv run python -m hs.steps.fetch_delta [--start 2026-08-01] [--end 2026-11-01]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, date, datetime, timedelta

import pyarrow as pa
import pyarrow.parquet as pq

from hs.config import PATHS, cfg
from hs.http import Http

API = "https://hn.algolia.com/api/v1/search_by_date"
ATTRS = "objectID,author,created_at_i,comment_text,parent_id,story_id,title,url,points,num_comments,_tags,story_text"

SCHEMA = pa.schema([
    ("id", pa.uint32()), ("type", pa.int8()), ("by", pa.string()), ("time", pa.timestamp("ms", tz="UTC")),
    ("text", pa.string()), ("parent", pa.uint32()), ("url", pa.string()), ("title", pa.string()),
    ("score", pa.int32()), ("descendants", pa.int32()), ("dead", pa.uint8()), ("deleted", pa.uint8()),
])


def query(http: Http, lo: int, hi_incl: int, *, hits: int = 1000) -> dict:
    params = {
        "tags": "(story,comment)", "hitsPerPage": hits,
        "numericFilters": f"created_at_i>={lo},created_at_i<={hi_incl}",
        "attributesToRetrieve": ATTRS, "attributesToHighlight": "[]",
    }
    r = http.get(API, params)
    r.raise_for_status()
    return r.json()


def to_row(h: dict) -> dict:
    tags = h.get("_tags") or []
    is_story = "story" in tags
    return {
        "id": int(h["objectID"]),
        "type": 1 if is_story else 2,
        "by": h.get("author"),
        "time": datetime.fromtimestamp(h["created_at_i"], UTC),
        "text": h.get("story_text") if is_story else h.get("comment_text"),
        "parent": None if is_story else h.get("parent_id"),
        "url": h.get("url") if is_story else None,
        "title": h.get("title") if is_story else None,
        "score": h.get("points") if is_story else None,
        "descendants": h.get("num_comments") if is_story else None,
        "dead": 0, "deleted": 0,
    }


def fetch_day(http: Http, day: date) -> tuple[int, int]:
    """返回 (条数, 请求数)。"""
    lo = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
    hi = lo + 86400 - 1
    seen: dict[int, dict] = {}
    upper, n_req = hi, 0
    while True:
        j = query(http, lo, upper)
        n_req += 1
        hits = j["hits"]
        for h in hits:
            seen.setdefault(int(h["objectID"]), h)
        if len(hits) < 1000:
            break
        new_upper = min(h["created_at_i"] for h in hits)
        if new_upper == upper:  # 同一秒超过 1000 条，理论上不会发生
            raise RuntimeError(f"cursor stuck at {upper} on {day}")
        upper = new_upper
    rows = sorted((to_row(h) for h in seen.values()), key=lambda r: r["id"])
    dest = PATHS.hn_delta / f"{day.isoformat()}.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), tmp, compression="zstd")
    tmp.replace(dest)
    return len(rows), n_req


def count_hits(http: Http, lo: int, hi_incl: int) -> int:
    return int(query(http, lo, hi_incl, hits=0)["nbHits"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default=cfg()["delta"]["overlap_start"])
    ap.add_argument("--end", default=(datetime.now(UTC).date() - timedelta(days=1)).isoformat(), help="含当天")
    args = ap.parse_args(argv)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    http = Http()
    t0, total, d = time.time(), 0, start
    while d <= end:
        dest = PATHS.hn_delta / f"{d.isoformat()}.parquet"
        if not dest.exists():
            n, req = fetch_day(http, d)
            total += n
            print(f"{d} items={n:,} requests={req} elapsed={time.time()-t0:.0f}s", flush=True)
        d += timedelta(days=1)
    print(f"done: {total:,} new items, http={http.stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
