"""学习路径（D38）：给一篇目标论文排出“先读哪几篇”。和其他模型任务一样是“脚本准备批次 → Claude Code 子 agent 写输出 → 脚本合并”。

  paths-prepare --target ID …   目标论文的 OpenAlex 参考文献 ∩ 书架（不够时再加一层）→ data/llm/paths_<日期>/
  paths-prepare --all-core      主书架里排得出路径的全部论文（至少一篇参考文献在书架上）；先加 --sample 50 跑样本
  paths-merge --task NAME       子 agent 排好的阅读顺序 → data/build/paths.jsonl（catalog 重建时进 paths 表）

用法：uv run python -m hs.steps.study <子命令>
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from hs import llm_batch
from hs.config import PATHS

PATHS_MODEL = "claude-sonnet-5-5"

PATHS_PROMPT = """# 任务：给一篇目标论文排一条学习路径

输入是 JSONL，每行一篇目标论文和候选的“前置论文”：
`{"id", "target": {...}, "candidates": [...]}`
- `target`：目标论文（标题、中文名、年份、一句话摘要、摘要开头）。
- `candidates`：目标论文的参考文献里、在我书架上的论文（`depth: 1`），不够时加上它们的参考文献（`depth: 2`）。
  每篇有标题、年份、一句话摘要、`cites`（它引用了候选里的哪几篇）、`people`（HN 上提到它的人数）。

从候选里挑 3–8 篇，排出读目标论文之前的阅读顺序：基础的、被别的候选引用的在前，目标论文放在最后一步。
候选不到 3 篇、或者真正相关的不到 3 篇时，有几篇用几篇；一篇真正相关的都没有时，`steps` 里只放目标论文本身，在 `intro` 里说明为什么排不出。
每行输出一个 JSON：
```
{"id": <同输入>, "intro": "一两句中文：这条路径帮我建立哪些前置知识", "steps": [{"id": "arxiv:…", "why": "为什么读它（≤60 字）", "focus": "读哪部分、抓什么（≤80 字）"}, …, {"id": <目标论文的 id>, "why": "…", "focus": "…"}]}
```
要求：
- 只用候选里的论文和目标论文本身，`id` 原样照抄；不要加候选以外的论文。
- 挑和目标论文的核心方法直接相关的；只是顺带引用的（比如优化器、数据集、评测基准）不选，除非理解目标论文离不开它。
- `why` 写清它和目标论文的关系（“Transformer 的编码器-解码器结构来自这里”），不写空话（“这是一篇重要的论文”）。
- `focus` 具体到章节或概念（“第 3 节的缩放点积注意力；跳过实验部分”）；不确定章节号时写概念。
- 中文，术语保留英文原词。
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
"""


def ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------- 学习路径
def _openalex_graph() -> tuple[dict[str, set[str]], dict[str, dict]]:
    from hs.steps.papers import load_openalex
    oa = load_openalex()
    w2a = {}
    for aid, m in oa.items():
        for k in ("openalex_id", "openalex_published_id"):
            if m.get(k):
                w2a[m[k]] = aid
    refs = {aid: {w2a[r] for r in (m.get("references") or []) if r in w2a and w2a[r] != aid} for aid, m in oa.items()}
    return refs, oa


def eligible_core(refs: dict[str, set[str]], cat: sqlite3.Connection) -> list[str]:
    """主书架里排得出路径的论文：至少有一篇参考文献在书架上（D38）。"""
    core = [r[0] for r in cat.execute("SELECT id FROM items WHERE tier='core' ORDER BY rank")]
    return [a for a in core if refs.get(a)]


def cmd_paths_prepare(a) -> None:
    refs, oa = _openalex_graph()
    cat = ro(PATHS.build / "catalog.db")

    def info(aid: str) -> dict | None:
        r = cat.execute("SELECT id, title, title_zh, year, people, tier, cited_by, card, abstract FROM items WHERE id=?", (aid,)).fetchone()
        if not r:
            return None
        card = json.loads(r["card"]) if r["card"] else {}
        return {"id": aid, "title": r["title"], "title_zh": r["title_zh"] or "", "year": r["year"], "people": r["people"],
                "oneliner": card.get("oneliner_zh") or "", "_abstract": (r["abstract"] or "")[:600], "_cited": r["cited_by"] or 0}

    # 已经有路径的（paths.jsonl）和别的批次里已经排过的不再排
    done = {r["item_id"] for r in llm_batch.read_jsonl(PATHS.build / "paths.jsonl")}
    for t in a.exclude_task or []:
        done |= set(llm_batch.inputs(t))
    targets = [t if t.startswith("arxiv:") else f"arxiv:{t}" for t in (a.target or [])]
    if a.all_core:
        targets += eligible_core(refs, cat)
    targets = [t for t in dict.fromkeys(targets) if t not in done or t in (a.target or [])]
    if a.sample:
        import random
        rng = random.Random(a.seed)
        targets = sorted(rng.sample(targets, min(a.sample, len(targets))), key=targets.index)

    items, skipped = [], 0
    for aid in targets:
        tgt = info(aid)
        if not tgt:
            skipped += 1
            continue
        d1 = [x for x in (info(r) for r in refs.get(aid, set())) if x]
        cands = {x["id"]: {**x, "depth": 1} for x in d1}
        if len(cands) < 12:  # 直接参考文献太少：再往下一层
            for x in list(cands):
                for r in refs.get(x, set()):
                    if r != aid and r not in cands and (y := info(r)):
                        cands[r] = {**y, "depth": 2}
        if not cands:
            skipped += 1
            continue
        # 最多 40 篇：一层的优先，再按 HN 人数和被引
        keep = sorted(cands.values(), key=lambda x: (x["depth"], -x["people"], -x["_cited"]))[:40]
        ids = {x["id"] for x in keep}
        for x in keep:
            x["cites"] = sorted(r for r in refs.get(x["id"], set()) if r in ids)
        items.append({"id": aid, "target": {"title": tgt["title"], "title_zh": tgt["title_zh"], "year": tgt["year"], "oneliner": tgt["oneliner"],
                                            "abstract": tgt["_abstract"]},
                      "candidates": [{k: v for k, v in x.items() if not k.startswith("_")} for x in keep]})
        if len(targets) <= 20:
            print(f"  {aid} {tgt['title'][:50]}：候选 {len(keep)}（一层 {sum(1 for x in keep if x['depth'] == 1)}）")
    if not items:
        print("paths-prepare：没有要排的目标")
        return
    task = a.task or f"paths_{time.strftime('%Y%m%d')}"
    paths = llm_batch.prepare(task, items, PATHS_PROMPT, batch_size=a.batch_size, out_fields=["id", "intro", "steps"], overwrite=a.overwrite, max_chars=60000)
    n_c = sorted(len(x["candidates"]) for x in items)
    print(f"paths-prepare：{len(items)} 篇目标 → {task}，{len(paths)} 批（模型 {PATHS_MODEL}）；候选数中位数 {n_c[len(n_c) // 2]}；跳过 {skipped}")


def cmd_paths_merge(a) -> None:
    out_p = PATHS.build / "paths.jsonl"
    old = {r["item_id"]: r for r in llm_batch.read_jsonl(out_p)}
    n_ok = n_bad = n_none = 0
    for task in a.task:
        ins, outs = llm_batch.inputs(task), llm_batch.outputs(task)
        for aid, o in outs.items():
            x = ins.get(aid)
            if not x:
                continue
            allowed = {c["id"] for c in x["candidates"]} | {aid}
            steps = [s for s in (o.get("steps") or []) if s.get("id") in allowed and s.get("why")]
            if not steps or steps[-1]["id"] != aid:
                print(f"  {aid}：输出不合格（没有步骤或最后一步不是目标论文），跳过")
                n_bad += 1
                continue
            if len(steps) == 1:  # 只有目标论文本身：排不出
                n_none += 1
                continue
            old[aid] = {"item_id": aid, "intro": o.get("intro") or "", "steps": [{"id": s["id"], "why": s["why"][:200], "focus": (s.get("focus") or "")[:240]} for s in steps],
                        "model": PATHS_MODEL, "task": task, "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            n_ok += 1
    with open(out_p, "w") as f:
        for r in old.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"paths-merge：{n_ok} 条路径写进 {out_p}（共 {len(old)} 条）；排不出 {n_none}，不合格 {n_bad}。重建 catalog 后上线：uv run python -m hs.steps.papers catalog")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hs.steps.study")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("paths-prepare")
    s.add_argument("--target", nargs="+", help="目标论文（arXiv 编号）")
    s.add_argument("--all-core", action="store_true", help="主书架里排得出路径的全部论文（至少一篇参考文献在书架上）")
    s.add_argument("--exclude-task", nargs="+", help="这些批次里排过的不再排")
    s.add_argument("--sample", type=int, help="随机抽 N 篇（先跑样本）")
    s.add_argument("--seed", type=int, default=20261104)
    s.add_argument("--task")
    s.add_argument("--batch-size", type=int, default=5)
    s.add_argument("--overwrite", action="store_true")
    s = sub.add_parser("paths-merge")
    s.add_argument("--task", nargs="+", required=True)
    a = ap.parse_args(argv)
    {"paths-prepare": cmd_paths_prepare, "paths-merge": cmd_paths_merge}[a.cmd](a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
