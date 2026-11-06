"""步骤 3：建本地分析库 data/hn.duckdb（可随时删掉重建）。

- 视图 hf / delta：直接读 data/raw/hn/{hf,delta}/*.parquet。
- 视图 items：HF 全部 + Algolia 中晚于 HF 截止时间（hf_cutoff）的部分，同一 schema。
- 表 meta：hf_cutoff、delta_end、行数。
- 表 links：每条 story 的 url（src='story_url'）和每条 story/comment 正文里的 href（src='text'），
  带 host（去掉 www.），只收 dead=0 且 deleted=0 的条目。论文、图书、其他域名的统计都从这里出发。

用法：uv run python -m hs.steps.build_db [--rebuild-links]
"""

from __future__ import annotations

import argparse
import sys
import time

import duckdb

from hs.config import PATHS


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(PATHS.hn_db), read_only=read_only)
    con.execute("SET TimeZone='UTC'")
    return con


# HN 正文里常见的 HTML 实体（只为抽 host；Python 侧会再用 html.unescape 精确处理）
UNESCAPE_SQL = "replace(replace(replace(replace({x}, '&#x2F;', '/'), '&amp;', '&'), '&#x3D;', '='), '&#x27;', '''')"


def build(rebuild_links: bool = False) -> dict:
    hf_glob = str(PATHS.hn_raw / "*.parquet")
    delta_glob = str(PATHS.hn_delta / "*.parquet")
    con = connect()
    t0 = time.time()
    con.execute(f"CREATE OR REPLACE VIEW hf AS SELECT * FROM read_parquet('{hf_glob}', union_by_name=true)")
    has_delta = any(PATHS.hn_delta.glob("*.parquet"))
    if has_delta:
        con.execute(f"CREATE OR REPLACE VIEW delta AS SELECT * FROM read_parquet('{delta_glob}', union_by_name=true)")
    cutoff = con.execute("SELECT max(time) FROM hf").fetchone()[0]
    cols = "id, type, \"by\", time, text, parent, url, title, score, descendants, dead, deleted"
    if has_delta:
        con.execute(f"""
            CREATE OR REPLACE VIEW items AS
            SELECT {cols}, 'hf' AS src FROM hf
            UNION ALL
            SELECT {cols}, 'algolia' AS src FROM delta WHERE time > TIMESTAMPTZ '{cutoff.isoformat()}'
        """)
    else:
        con.execute(f"CREATE OR REPLACE VIEW items AS SELECT {cols}, 'hf' AS src FROM hf")
    delta_end = con.execute("SELECT max(time) FROM items").fetchone()[0]
    con.execute("CREATE OR REPLACE TABLE meta AS SELECT ?::TIMESTAMPTZ AS hf_cutoff, ?::TIMESTAMPTZ AS data_end",
                [cutoff, delta_end])

    exists = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='links'").fetchone()[0]
    if rebuild_links or not exists:
        u = UNESCAPE_SQL.format(x="h")
        con.execute(f"""
            CREATE OR REPLACE TABLE links AS
            WITH live AS (
                SELECT id, type, "by", time, parent, url, text FROM items
                WHERE coalesce(dead, 0) = 0 AND coalesce(deleted, 0) = 0 AND type IN (1, 2)
            ),
            story_urls AS (
                SELECT id, type, "by", time, parent, 'story_url' AS src, url AS link FROM live
                WHERE type = 1 AND url IS NOT NULL AND url <> ''
            ),
            text_links AS (
                SELECT id, type, "by", time, parent, 'text' AS src, {u} AS link
                FROM (SELECT id, type, "by", time, parent,
                             unnest(regexp_extract_all(text, 'href="([^"]+)"', 1)) AS h
                      FROM live WHERE text LIKE '%href=%')
            )
            SELECT *, regexp_replace(lower(regexp_extract(link, '^[A-Za-z]+://([^/:?#]+)', 1)), '^www\\.', '') AS host
            FROM (SELECT * FROM story_urls UNION ALL SELECT * FROM text_links)
        """)
    exists = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='tree'").fetchone()[0]
    if rebuild_links or not exists:
        # 回溯评论所在 story 用：只存 id / parent / type，story 带标题
        con.execute("""CREATE OR REPLACE TABLE tree AS
                       SELECT id, parent, type, CASE WHEN type = 1 THEN title END AS title FROM items""")
    # 每个 parquet 文件的 id 范围：按 id 取正文时只读相关文件
    files_sql = f"SELECT filename AS path, 'hf' AS kind, min(id) AS min_id, max(id) AS max_id FROM read_parquet('{hf_glob}', filename=true) GROUP BY ALL"
    if has_delta:
        files_sql += f" UNION ALL SELECT filename, 'delta', min(id), max(id) FROM read_parquet('{delta_glob}', filename=true) GROUP BY ALL"
    con.execute(f"CREATE OR REPLACE TABLE file_ids AS {files_sql}")
    stats = {
        "hf_cutoff": str(cutoff), "data_end": str(delta_end),
        "items": con.execute("SELECT count(*) FROM items").fetchone()[0],
        "links": con.execute("SELECT count(*) FROM links").fetchone()[0],
        "secs": round(time.time() - t0, 1),
    }
    con.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild-links", action="store_true")
    args = ap.parse_args(argv)
    print(build(args.rebuild_links))
    return 0


if __name__ == "__main__":
    sys.exit(main())
