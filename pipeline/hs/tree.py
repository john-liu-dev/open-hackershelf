"""评论 → 所在 story（沿 parent 往上走），以及父评论片段。依赖 hn.duckdb 里的 tree 表。"""

from __future__ import annotations

import duckdb
import pyarrow as pa

from hs.text import to_text


def root_stories(con: duckdb.DuckDBPyConnection, ids: list[int], max_depth: int = 500) -> dict[int, tuple[int, str | None]]:
    """comment/story id → (story id, story 标题)。断链的不返回。"""
    if not ids:
        return {}
    arr = pa.table({"orig": pa.array(ids, pa.uint64()), "cur": pa.array(ids, pa.uint64())})
    con.register("_fr_src", arr)
    con.execute("CREATE OR REPLACE TEMP TABLE _fr AS SELECT * FROM _fr_src")
    con.unregister("_fr_src")
    result: dict[int, tuple[int, str | None]] = {}
    for _ in range(max_depth):
        con.execute("""CREATE OR REPLACE TEMP TABLE _st AS
                       SELECT f.orig, f.cur, t.type, t.parent, t.title FROM _fr f JOIN tree t ON t.id = f.cur""")
        for orig, cur, title in con.execute("SELECT orig, cur, title FROM _st WHERE type = 1").fetchall():
            result[orig] = (cur, title)
        n = con.execute("SELECT count(*) FROM _st WHERE type <> 1 AND parent IS NOT NULL").fetchall()[0][0]
        if n == 0:
            break
        con.execute("CREATE OR REPLACE TEMP TABLE _fr AS SELECT orig, parent AS cur FROM _st WHERE type <> 1 AND parent IS NOT NULL")
    return result


def get_items(con: duckdb.DuckDBPyConnection, ids: list[int], cols: str = 'id, type, "by", time, text, parent, url, title') -> dict[int, tuple]:
    """按 id 取条目，只读 id 范围覆盖它们的 parquet 文件（HF 优先，取不到再查增量）。返回 id → 行（cols 顺序）。"""
    want = sorted(set(int(i) for i in ids))
    out: dict[int, tuple] = {}
    files = con.execute("SELECT path, kind, min_id, max_id FROM file_ids ORDER BY kind = 'delta', min_id").fetchall()
    for path, _kind, lo, hi in files:
        sel = [i for i in want if lo <= i <= hi and i not in out]
        if not sel:
            continue
        for row in con.execute(f"SELECT {cols} FROM read_parquet('{path}') WHERE id IN ({','.join(map(str, sel))})").fetchall():
            out.setdefault(int(row[0]), row)
    return out


def parent_snippets(con: duckdb.DuckDBPyConnection, ids: list[int], n: int = 300) -> dict[int, str]:
    """comment id → 父评论的纯文本前 n 个字符（父节点是 story 时不返回）。"""
    if not ids:
        return {}
    con.register("_ids_src", pa.table({"id": pa.array(ids, pa.uint64())}))
    con.execute("CREATE OR REPLACE TEMP TABLE _ids AS SELECT * FROM _ids_src")
    con.unregister("_ids_src")
    par = dict(con.execute("""SELECT c.id, t.parent FROM _ids c JOIN tree t ON t.id = c.id
                              JOIN tree p ON p.id = t.parent WHERE p.type = 2""").fetchall())
    rows = get_items(con, list(par.values()), "id, text")
    return {c: to_text(rows[p][1])[:n] for c, p in par.items() if p in rows}
