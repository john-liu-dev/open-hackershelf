"""月度更新（D47）：拉 HN 增量 → 重建目录 → 增量的模型任务 → 重建 catalog。每月初跑一次，能断点续跑。

  start [--tag YYYYMMDD] [--skip-fetch] [--force]
        备份当前产物到 data/backups/monthly-<tag>/，刷新数据（不调模型），再准备第一个模型任务
  next  看进度、准备下一步。有没跑完的批次就列出来（交给 Claude Code 子 agent），跑完后再运行一次 next
  status
  log-run --task T --batch 0001 --model haiku [--tokens N] [--ms N]
        子 agent 跑完一批后，主会话记一下用量（写进 data/llm/<task>/runs.jsonl）

刷新数据：fetch-delta → build-db --rebuild-links → papers extract / tiers / meta / openalex / openalex-search
        → shelf embed / assign-topics / related。都是已有命令，这里只是按顺序跑；meta 和 embed 只处理新进的论文。
模型任务（D2，都在 Claude Code 里用子 agent 跑），按顺序：
  stance_inc_<tag>（Haiku）→ stance_inc_<tag>_review（Sonnet）→ cards_inc_<tag>（Sonnet）
  → catalog → why_zh_inc_<tag>（Sonnet）→ catalog
  没有要处理的就不建任务，直接进下一步。每批：读 data/llm/<task>/prompt.md 和 in/<批>.md，结果写到 out/<批>.jsonl。
  怎么派子 agent、什么时候停下来等我确认，见 .claude/skills/monthly-update/SKILL.md。
最后在 reports/monthly/<tag>.md 写一页小结。不提交、不推送：公开站用 deploy/public/build.sh 构建，看过清单再发布。
用法：uv run hs monthly <子命令>
"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from hs import llm_batch
from hs.config import PATHS
from hs.steps import papers as P

STATE = PATHS.build / "monthly.json"
REPORTS = PATHS.reports / "monthly"
# 开始前备份。这些都能重建，备份是为了出问题时直接换回去，以及最后对比前后
BACKUP = ["catalog.db", "items.jsonl", "mentions.jsonl", "build_meta.json", "search-index.json", "related.jsonl",
          "taxonomy.json", "embeddings.npy", "embedding_ids.json", "papers/candidates.parquet", "papers/tiers.json",
          "papers/topics.json", "papers/arxiv_meta.jsonl", "papers/openalex.jsonl", "papers/openalex_search.jsonl"]
REFRESH = [
    ("fetch-delta", "hs.steps.fetch_delta", []),
    ("build-db", "hs.steps.build_db", ["--rebuild-links"]),
    ("extract", "hs.steps.papers", ["extract"]),
    ("tiers", "hs.steps.papers", ["tiers"]),
    ("meta", "hs.steps.papers", ["meta"]),
    ("openalex", "hs.steps.papers", ["openalex"]),
    # 新进主书架、只有预印本记录的论文，用 OpenAlex search 找正式发表版本（每篇约 $0.001，查过的跳过）
    ("openalex-search", "hs.steps.papers", ["openalex-search"]),
    ("embed", "hs.steps.shelf", ["embed"]),
    ("assign-topics", "hs.steps.shelf", ["assign-topics"]),
    ("related", "hs.steps.shelf", ["related"]),
]
STAGES = ["stance", "review", "cards", "why", "done"]
PREPARE = {"stance": "stance-inc-prepare", "review": "stance-inc-review-prepare",
           "cards": "cards-inc-prepare", "why": "why-zh-inc-prepare"}
COUNT_ROWS = [("papers", "目录里的论文"), ("papers_core", "主书架（3/3）"), ("papers_cand", "候选层（2/2）"),
              ("mentions", "保留的提及（每篇最多 20 条）"), ("labeled_papers", "提及全部标过立场的论文"),
              ("cards", "卡片"), ("why_zh", "有中文说明的评论"), ("openalex", "有 OpenAlex 数据的论文")]


def task_of(stage: str, tag: str) -> str:
    return {"stance": f"{P.STANCE_INC}{tag}", "review": f"{P.STANCE_INC}{tag}_review",
            "cards": f"{P.CARDS_INC}{tag}", "why": f"{P.WHY_ZH_INC}{tag}"}[stage]


def load() -> dict:
    if not STATE.exists():
        raise SystemExit("还没有开始的月度更新：先运行 uv run hs monthly start")
    return json.loads(STATE.read_text())


def save(st: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1))
    tmp.replace(STATE)


def run(name: str, module: str, argv: list[str]) -> None:
    t0 = time.time()
    print(f"\n== {name} ==", flush=True)
    rc = importlib.import_module(module).main(argv) or 0
    if rc:
        raise SystemExit(f"{name} 失败（rc={rc}）。修好后运行 uv run hs monthly next 接着做")
    print(f"== {name} 完成（{time.time() - t0:.0f}s）", flush=True)


def backup(tag: str) -> str:
    d = PATHS.data / "backups" / f"monthly-{tag}"
    if not d.exists():  # 已经备份过就不动：保留的是开始前的状态
        for rel in BACKUP:
            src = PATHS.build / rel
            if src.exists():
                (d / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, d / rel)
    return str(d)


def refresh(st: dict) -> None:
    for i in range(st["refresh_done"], len(REFRESH)):
        name, module, argv = REFRESH[i]
        if name == "fetch-delta" and st.get("skip_fetch"):
            print("\n== fetch-delta：跳过（--skip-fetch）", flush=True)
        else:
            run(name, module, argv)
        st["refresh_done"] = i + 1
        save(st)


def show_pending(task: str, pend: list[str]) -> None:
    m = llm_batch.manifest(task)
    model = (m.get("model") or "").removeprefix("claude-").split("-")[0] or "?"
    rel = llm_batch.task_dir(task).relative_to(PATHS.root)
    names = " ".join(p.removesuffix(".jsonl") for p in pend)
    print(f"\n== 待跑子 agent：{task}（模型 {model}，{m.get('n_items')} 条、{m.get('n_batches')} 批），没跑完的 {len(pend)} 批：{names}")
    print(f"   每批一个子 agent：读 {rel}/prompt.md 和 {rel}/in/<批>.md，结果写到 {rel}/out/<批>.jsonl")
    print("   都跑完后再运行：uv run hs monthly next", flush=True)


def advance(st: dict) -> None:
    """接着刷新数据（如果上次断在半路），然后准备下一个模型任务；有没跑完的批次就列出来后返回。全部完成后重建 catalog、写小结。"""
    if st["refresh_done"] < len(REFRESH):
        refresh(st)
    tag = st["tag"]
    while st["stage"] != "done":
        stage = st["stage"]
        task = task_of(stage, tag)
        if stage == "why" and "before_why" not in st["catalogs"]:
            run("catalog（准备中文说明之前）", "hs.steps.papers", ["catalog"])
            st["catalogs"].append("before_why")
            save(st)
        if stage not in st["prepared"]:
            run(PREPARE[stage], "hs.steps.papers", [PREPARE[stage], "--tag", tag])
            st["prepared"].append(stage)
            save(st)
        if (llm_batch.task_dir(task) / "manifest.json").exists():
            pend = llm_batch.pending(task)
            if pend:
                show_pending(task, pend)
                return
        st["stage"] = STAGES[STAGES.index(stage) + 1]
        save(st)
    if "final" not in st["catalogs"]:
        run("catalog", "hs.steps.papers", ["catalog"])
        st["catalogs"].append("final")
        st["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        save(st)
    path = write_report(st)
    print(f"\n月度更新 {tag} 完成。小结：{path.relative_to(PATHS.root)}")
    print("下一步：deploy/public/build.sh 构建公开站、看清单，确认没问题再发布", flush=True)


def write_report(st: dict) -> Path:
    tag = st["tag"]
    after = json.loads((PATHS.build / "build_meta.json").read_text())
    before, now = st["before"]["counts"], after["counts"]
    old = {x["id"]: x for x in llm_batch.read_jsonl(Path(st["backup"]) / "items.jsonl")}
    new = {x["id"]: x for x in llm_batch.read_jsonl(PATHS.build / "items.jsonl")}
    up_core = sorted((x for i, x in new.items() if x["tier"] == "core" and (old.get(i) or {}).get("tier") != "core"),
                     key=lambda x: -x["score"])
    added = [x for i, x in new.items() if i not in old]
    lines = [f"# 月度更新 {tag}", "",
             f"- HN 数据截止：{st['before'].get('hn_cutoff')} → {after.get('hn_cutoff')}",
             f"- 开始 {st['started_at']}，完成 {st.get('finished_at')}；开始前的产物备份在 `{Path(st['backup']).relative_to(PATHS.root)}/`",
             "", "| 项 | 之前 | 之后 |", "|---|---|---|"]
    lines += [f"| {label} | {before.get(k, '—'):,} | {now.get(k, '—'):,} |" if isinstance(now.get(k), int) and isinstance(before.get(k), int)
              else f"| {label} | {before.get(k, '—')} | {now.get(k, '—')} |" for k, label in COUNT_ROWS]
    lines += ["", "## 模型任务（Claude Code 子 agent，走订阅额度）", "", "| 任务 | 模型 | 条数 | 批数 | 记录到的 token |", "|---|---|---|---|---|"]
    for stage in PREPARE:
        t = task_of(stage, tag)
        m = llm_batch.manifest(t)
        if not m:
            lines.append(f"| {t} | — | 0（不需要） | 0 | — |")
            continue
        tok = sum(r.get("tokens") or 0 for r in llm_batch.runs(t) if r.get("batch"))
        lines.append(f"| {t} | {m.get('model', '?')} | {m['n_items']:,} | {m['n_batches']} | {tok:,} |")
    lines += ["", f"## 新进主书架（{len(up_core)} 篇）", ""]
    lines += [f"- {x.get('title_zh') or x['title']}（{x['title']}）— {x['hn']['people']} 人、{x['hn']['active_months']} 个月，"
              f"分数 {x['score']:g}，https://arxiv.org/abs/{x['id'].removeprefix('arxiv:')}" for x in up_core] or ["- 没有"]
    lines += ["", f"新进目录（候选层或直接进主书架）共 {len(added)} 篇。",
              "", "要换回开始前的版本：把备份目录里的文件按相对路径拷回 `data/build/`。"]
    REPORTS.mkdir(parents=True, exist_ok=True)
    p = REPORTS / f"{tag}.md"
    p.write_text("\n".join(lines) + "\n")
    return p


def cmd_start(args) -> None:
    if STATE.exists():
        old = json.loads(STATE.read_text())
        if old.get("stage") != "done" and not args.force:
            raise SystemExit(f"上一次月度更新（{old['tag']}）还没做完：运行 uv run hs monthly next 接着做；要放弃它重新开始，加 --force")
    tag = args.tag or datetime.now().strftime("%Y%m%d")
    used = [t for t in (task_of(s, tag) for s in PREPARE) if llm_batch.task_dir(t).exists()]
    if used:
        raise SystemExit(f"tag {tag} 已经用过（{', '.join(used)}），换一个，比如 --tag {tag}b")
    before = json.loads((PATHS.build / "build_meta.json").read_text())
    st = {"tag": tag, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "skip_fetch": args.skip_fetch,
          "backup": backup(tag), "before": {"hn_cutoff": before.get("hn_cutoff"), "counts": before.get("counts", {})},
          "refresh_done": 0, "stage": "stance", "prepared": [], "catalogs": []}
    save(st)
    print(f"月度更新 {tag}：开始前的产物已备份到 {st['backup']}", flush=True)
    advance(st)


def cmd_status(_args) -> None:
    st = load()
    print(f"月度更新 {st['tag']}：开始于 {st['started_at']}，刷新数据 {st['refresh_done']}/{len(REFRESH)} 步，当前阶段 {st['stage']}")
    for stage in PREPARE:
        t = task_of(stage, st["tag"])
        m = llm_batch.manifest(t)
        if m:
            pend = llm_batch.pending(t)
            print(f"  {t}：{m['n_items']} 条、{m['n_batches']} 批，没跑完 {len(pend)} 批 {' '.join(pend)}")
        elif stage in st["prepared"]:
            print(f"  {t}：不需要（没有要处理的）")


def cmd_log_run(args) -> None:
    llm_batch.log_run(args.task, batch=args.batch, model=args.model, tokens=args.tokens, duration_ms=args.ms,
                      at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--tag", help="默认今天的日期，例如 20261201")
    s.add_argument("--skip-fetch", action="store_true", help="不拉 HN 增量（数据已经是新的）")
    s.add_argument("--force", action="store_true", help="上一次没做完也重新开始")
    sub.add_parser("next")
    sub.add_parser("status")
    s = sub.add_parser("log-run")
    s.add_argument("--task", required=True)
    s.add_argument("--batch", required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--tokens", type=int)
    s.add_argument("--ms", type=int)
    args = ap.parse_args(argv)
    {"start": cmd_start, "next": lambda _a: advance(load()), "status": cmd_status, "log-run": cmd_log_run}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
