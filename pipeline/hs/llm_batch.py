"""Claude Code 子 agent 批量标注的落盘约定（脚本切分输入、合并输出；prompt、输入、输出都在磁盘上）。

    data/llm/<task>/
      prompt.md           给子 agent 的说明（脚本生成）
      manifest.json       任务元信息：条数、批大小、输出字段
      in/0001.jsonl       输入，一行一条，必有 "id"
      out/0001.jsonl      子 agent 写的输出，一行一条，必有 "id"
      runs.jsonl          每批的运行记录（模型、耗时、token），由主会话追加

断点续跑：`pending(task)` 列出还没有完整输出的批次；输出缺条或 JSON 坏了就算没完成，重跑那一批即可。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from hs.config import PATHS


def task_dir(task: str) -> Path:
    return PATHS.llm / task


def _chunks(items: list[dict], batch_size: int, max_chars: int | None) -> list[list[dict]]:
    """按条数切批；给了 max_chars 时，Markdown 视图超过这个字符数也切（Read 工具单次读取有上限）。"""
    out, cur, size = [], [], 0
    for x in items:
        n = len(to_markdown([x]))
        if cur and (len(cur) >= batch_size or (max_chars and size + n > max_chars)):
            out.append(cur)
            cur, size = [], 0
        cur.append(x)
        size += n
    if cur:
        out.append(cur)
    return out


def prepare(task: str, items: list[dict], prompt: str, *, batch_size: int = 50, out_fields: list[str] | None = None,
            overwrite: bool = False, max_chars: int | None = None, model: str | None = None) -> list[Path]:
    """切批落盘。model：这个任务该用哪个模型跑（记进 manifest，合并时据此标注来源；不传就不记）。"""
    d = task_dir(task)
    if (d / "manifest.json").exists() and not overwrite:
        raise FileExistsError(f"{d} 已存在；要重建请传 overwrite=True（不会删除已有输出）")
    (d / "in").mkdir(parents=True, exist_ok=True)
    (d / "out").mkdir(parents=True, exist_ok=True)
    (d / "prompt.md").write_text(prompt)
    paths = []
    for i, chunk in enumerate(_chunks(items, batch_size, max_chars)):
        p = d / "in" / f"{i + 1:04d}.jsonl"
        p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in chunk))
        # 给子 agent 读的版本：每行不超过 ~1000 字符（Read 工具会截断超长行）
        p.with_suffix(".md").write_text(to_markdown(chunk))
        paths.append(p)
    (d / "manifest.json").write_text(json.dumps({
        "task": task, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "n_items": len(items),
        "batch_size": batch_size, "max_chars": max_chars, "n_batches": len(paths), "out_fields": out_fields or [],
        **({"model": model} if model else {}),
    }, ensure_ascii=False, indent=1))
    return paths


def manifest(task: str) -> dict:
    p = task_dir(task) / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else {}


def tasks_like(prefix: str) -> list[str]:
    """data/llm 下名字以 prefix 开头、已经准备好（有 manifest）的任务，按名字排序。
    月度更新的增量任务名带日期（stance_inc_20261104、stance_inc_20261104_review），按名字排就是时间顺序，复核排在它那一批后面。"""
    return sorted(p.parent.name for p in PATHS.llm.glob(f"{prefix}*/manifest.json"))


def _wrap(text: str, width: int = 900) -> str:
    out = []
    for line in str(text).splitlines() or [""]:
        while len(line) > width:
            cut = line.rfind(" ", 0, width)
            cut = cut if cut > width // 2 else width
            out.append(line[:cut])
            line = line[cut:].lstrip()
        out.append(line)
    return "\n".join(out)


def to_markdown(items: list[dict]) -> str:
    """输入批次的 Markdown 视图：每条一个 `## id: ...` 小节，字段逐个列出，长文本折行。"""
    parts = [f"<!-- {len(items)} 条；输出时每条一行 JSONL，id 原样照抄 -->"]
    for x in items:
        parts.append(f"\n## id: {x['id']}")
        for k, v in x.items():
            if k == "id" or k.startswith("_"):  # 下划线开头的是内部字段（如抽样分档），不给模型看
                continue
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            v = "" if v is None else str(v)
            if "\n" in v or len(v) > 200:
                parts.append(f"**{k}**:\n" + _wrap(v))
            else:
                parts.append(f"**{k}**: {v}")
    return "\n".join(parts) + "\n"


def read_jsonl(p: Path) -> list[dict]:
    out = []
    if not p.exists():
        return out
    # 只按 "\n" 切行：str.splitlines() 还会在 U+2028 等字符处切开，把含这些字符的 JSON 行切坏、悄悄丢掉
    for line in p.read_text().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def batch_status(task: str, name: str) -> tuple[int, int]:
    d = task_dir(task)
    want = {str(x["id"]) for x in read_jsonl(d / "in" / name)}
    got = {str(x.get("id")) for x in read_jsonl(d / "out" / name)}
    return len(want), len(want & got)


def pending(task: str) -> list[str]:
    d = task_dir(task)
    out = []
    for p in sorted((d / "in").glob("*.jsonl")):
        want, have = batch_status(task, p.name)
        if have < want:
            out.append(p.name)
    return out


def outputs(task: str) -> dict[str, dict]:
    d = task_dir(task)
    res: dict[str, dict] = {}
    for p in sorted((d / "out").glob("*.jsonl")):
        for x in read_jsonl(p):
            res[str(x.get("id"))] = x
    return res


def inputs(task: str) -> dict[str, dict]:
    d = task_dir(task)
    res: dict[str, dict] = {}
    for p in sorted((d / "in").glob("*.jsonl")):
        for x in read_jsonl(p):
            res[str(x["id"])] = x
    return res


def log_run(task: str, **kw) -> None:
    with open(task_dir(task) / "runs.jsonl", "a") as f:
        f.write(json.dumps(kw, ensure_ascii=False) + "\n")


def runs(task: str) -> list[dict]:
    return read_jsonl(task_dir(task) / "runs.jsonl")
