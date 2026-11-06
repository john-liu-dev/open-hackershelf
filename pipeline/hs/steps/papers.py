"""Phase 1 论文管线（不调用模型的部分 + 子 agent 批次的准备/合并）。

子命令（按顺序）：
  extract         全量抽 arXiv 提及 → data/build/papers/mentions_all.parquet
  tiers           论文级统计 + 三档阈值（2/2 候选全集、2/3、3/3 核心集）→ candidates.parquet
  meta            arXiv API 给候选全集补元数据 → arxiv_meta.jsonl
  stance-sample   随机 200 条待标注提及 → data/llm/stance_sample_{haiku,sonnet}/
  stance-prepare  核心集全部待标注提及，按月分片 → data/llm/stance_core/
  stance-agree    比较 Haiku 与 Sonnet 在样本上的一致率
  cards-prepare   暂定分数最高的 N 篇写卡片 → data/llm/cards_sample/
  catalog         暂定分数 + items.jsonl / mentions.jsonl / catalog.db / search-index.json

月度更新（D47，由 hs.steps.monthly 按顺序调用；--tag 一般是日期）：
  stance-inc-prepare         主书架里没有立场标签的提及 → data/llm/stance_inc_<tag>/（Haiku + v3）
  stance-inc-review-prepare  其中置信度低的、有“让人去读”线索的 → stance_inc_<tag>_review/（Sonnet + v3）
  cards-inc-prepare          主书架里还没有卡片的论文 → cards_inc_<tag>/（Sonnet）
  why-zh-inc-prepare         会显示、还没有中文说明的评论 → why_zh_inc_<tag>/（Sonnet；要先跑一次 catalog）
  meta 默认只查新进的论文，--full 全部重查。

计数口径（Phase 0 探针后暂定，见 docs/DECISIONS.md D9）：
  一条提及 = 评论或 story 正文里链到论文、且自己文字 ≥ min_own_chars；或论文本身被提交为 story（不受字数限制）。
  人数 = 不同 HN 用户，月份 = 不同 YYYY-MM。纯文本 arXiv:ID 写法暂不计入。
用法：uv run python -m hs.steps.papers <子命令>
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from hs import llm_batch
from hs.arxiv import fetch_meta
from hs.config import PATHS, cfg
from hs.http import Http
from hs.links import arxiv_id
from hs.mentions import ARXIV_SQL_FILTER, arxiv_mentions
from hs.steps.build_db import connect
from hs.text import hrefs, to_text
from hs.tree import get_items, parent_snippets, root_stories

OUT = PATHS.build / "papers"
MIN_CHARS = int(cfg()["rules"]["min_own_chars"])
COUNTED = f"(src = 'story_url' OR (src IN ('comment_link', 'story_text_link') AND own_len >= {MIN_CHARS}))"
LABELABLE = f"(src IN ('comment_link', 'story_text_link') AND own_len >= {MIN_CHARS})"
# 三档门槛（人数, 月份）：core 主书架 3/3，cand 候选层 2/2，mid 只做统计。改 config.toml 的 [rules.tiers]（demo 用 demo/config.toml 把月份降到 1）
TIERS = {k: (int(v[0]), int(v[1])) for k, v in cfg()["rules"].get("tiers", {"core": [3, 3], "mid": [2, 3], "cand": [2, 2]}).items()}
STANCES = ("strong_rec", "rec", "reference", "joke", "critical")
STANCE_FIELDS = ["stance", "confidence", "quote", "why"]
# 月度更新（D47）的增量任务：名字带日期（stance_inc_20261104），按名字排序就是时间顺序（llm_batch.tasks_like）
STANCE_INC, CARDS_INC, WHY_ZH_INC = "stance_inc_", "cards_inc_", "why_zh_inc_"
HAIKU, SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"


def _db() -> duckdb.DuckDBPyConnection:
    db = duckdb.connect()
    db.execute("SET TimeZone='UTC'")
    db.execute(f"CREATE VIEW m AS SELECT *, strftime(time, '%Y-%m') AS month FROM '{OUT / 'mentions_all.parquet'}'")
    return db


# ---------------------------------------------------------------- 1.1 抽取
def cmd_extract(_args) -> None:
    con = connect(read_only=True)
    q = f"""SELECT id, type, "by", time, url, text FROM items
            WHERE coalesce(dead,0)=0 AND coalesce(deleted,0)=0 AND type IN (1,2) AND {ARXIV_SQL_FILTER}"""
    rows = []
    for batch in con.sql(q).to_arrow_reader(100_000):
        d = batch.to_pydict()
        for i in range(batch.num_rows):
            rows.extend(arxiv_mentions(d["id"][i], d["type"][i], d["by"][i], d["time"][i], d["url"][i], d["text"][i]))
    con.close()
    schema = pa.schema([("hn_id", pa.uint32()), ("type", pa.int8()), ("by", pa.string()),
                        ("time", pa.timestamp("ms", tz="UTC")), ("arxiv", pa.string()), ("src", pa.string()),
                        ("form", pa.string()), ("own_len", pa.int32())])
    OUT.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), OUT / "mentions_all.parquet")
    print(f"extract: {len(rows):,} mentions → {OUT / 'mentions_all.parquet'}")


# ---------------------------------------------------------------- 1.2 阈值
def cmd_tiers(_args) -> None:
    db = _db()
    db.execute(f"""CREATE TABLE p AS
        SELECT arxiv, count(DISTINCT "by") AS people, count(DISTINCT month) AS months, count(*) AS n_counted,
               count(*) FILTER (WHERE {LABELABLE}) AS n_labelable, count(*) FILTER (WHERE src='story_url') AS n_story,
               min(time) AS first_mention, max(time) AS last_mention
        FROM m WHERE {COUNTED} GROUP BY arxiv""")
    for name, (pp, mm) in TIERS.items():
        db.execute(f"ALTER TABLE p ADD COLUMN {name} BOOLEAN")
        db.execute(f"UPDATE p SET {name} = people >= {pp} AND months >= {mm}")
    db.execute(f"COPY (SELECT * FROM p WHERE cand ORDER BY people DESC, months DESC) TO '{OUT / 'candidates.parquet'}' (FORMAT parquet)")
    r = db.execute("""SELECT count(*) FILTER (WHERE cand), count(*) FILTER (WHERE mid), count(*) FILTER (WHERE core),
                      sum(n_labelable) FILTER (WHERE cand), sum(n_labelable) FILTER (WHERE mid), sum(n_labelable) FILTER (WHERE core)
                      FROM p""").fetchone()
    summary = {"cand_2_2": r[0], "mid_2_3": r[1], "core_3_3": r[2],
               "labelable_cand": r[3], "labelable_mid": r[4], "labelable_core": r[5]}
    (OUT / "tiers.json").write_text(json.dumps(summary, indent=1))
    print("tiers:", summary)


# ---------------------------------------------------------------- 1.3 元数据
def cmd_meta(args) -> None:
    """候选全集的 arXiv 元数据。已经有的沿用，只查新进的（月度更新时请求很少）；--full 全部重查。"""
    ids = [r[0] for r in duckdb.sql(f"SELECT arxiv FROM '{OUT / 'candidates.parquet'}'").fetchall()]
    old = {} if getattr(args, "full", False) else load_meta()
    todo = [i for i in ids if i not in old]
    t0 = time.time()

    def prog(done, total, cached):
        if done % 1000 < 100 or done == total:
            print(f"  meta {done}/{total} ({time.time()-t0:.0f}s){' cached' if cached else ''}", flush=True)

    http = Http()
    meta = {**old, **(fetch_meta(http, todo, progress=prog) if todo else {})}
    print(f"  meta: 沿用 {len(ids) - len(todo):,}，新查 {len(todo):,}", flush=True)
    with open(OUT / "arxiv_meta.jsonl", "w") as f:
        for i in ids:
            if i in meta:
                f.write(json.dumps(meta[i], ensure_ascii=False) + "\n")
    missing = [i for i in ids if i not in meta]
    (OUT / "arxiv_meta_missing.json").write_text(json.dumps(missing))
    print(f"meta: {len(meta):,}/{len(ids):,} found, {len(missing)} missing, http={http.stats}")


def cmd_openalex(_args) -> None:
    """OpenAlex 补被引数、参考文献、主题 → openalex.jsonl（一行一篇，按 arXiv ID）。"""
    from hs import openalex as oa

    meta = load_meta()
    ids = [r[0] for r in duckdb.sql(f"SELECT arxiv FROM '{OUT / 'candidates.parquet'}'").fetchall()]
    http = Http()
    t0 = time.time()

    def prog(done, total):
        if done % 1000 < 50 or done == total:
            print(f"  openalex {done}/{total} ({time.time()-t0:.0f}s)", flush=True)

    by_doi = oa.lookup_dois(http, [oa.arxiv_doi(a) for a in ids], oa.SELECT_PREPRINT, progress=prog)
    pre = {a: by_doi[oa.arxiv_doi(a)] for a in ids if oa.arxiv_doi(a) in by_doi}
    by_land = oa.lookup_arxiv_landing(http, [a for a in ids if a not in pre], oa.SELECT_PREPRINT)
    pre.update(by_land)
    print(f"  openalex: arXiv DOI {len(by_doi):,}, landing page +{len(by_land):,}", flush=True)
    jdoi = {a: oa.norm_doi((meta.get(a) or {}).get("doi")) for a in ids}
    pub = oa.lookup_dois(http, [d for d in jdoi.values() if d], oa.SELECT_PUBLISHED, progress=prog)
    n_pre = n_pub = 0
    with open(OUT / "openalex.jsonl", "w") as f:
        for a in ids:
            w, p = pre.get(a), pub.get(jdoi[a] or "")
            if p and w and p["id"] == w["id"]:
                p = None
            if not w and not p:
                continue
            n_pre += bool(w)
            n_pub += bool(p)
            # 只有 arXiv 预印本记录（DOI 10.48550/…、没有正式发表版本）：被引数往往偏低，留给 openalex-search 补
            wdoi = oa.norm_doi((w or {}).get("doi"))
            rec = {
                "id": a, "openalex_id": (w or p)["id"].rsplit("/", 1)[-1],
                "preprint_only": bool(w) and not p and (wdoi or "").startswith("10.48550/"),
                "work_doi": wdoi, "work_type": (w or {}).get("type"),
                "openalex_published_id": p["id"].rsplit("/", 1)[-1] if p else None,
                "cited_by": max((w or {}).get("cited_by_count") or 0, (p or {}).get("cited_by_count") or 0),
                "cited_by_preprint": (w or {}).get("cited_by_count"), "cited_by_published": (p or {}).get("cited_by_count"),
                "venue": oa.venue(p) if p else None, "published_doi": jdoi[a] if p else None,
                "references": [r.rsplit("/", 1)[-1] for r in (w or {}).get("referenced_works") or []],
                "primary_topic": oa.slim_topic((w or {}).get("primary_topic")),
                "topics": [oa.slim_topic(t) for t in ((w or {}).get("topics") or [])[:3]],
                "counts_by_year": {str(c["year"]): c["cited_by_count"] for c in (w or {}).get("counts_by_year") or []},
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"openalex: {len(ids):,} papers, preprint found {n_pre:,}, published found {n_pub:,} "
          f"(of {sum(1 for d in jdoi.values() if d)} with journal DOI), http={http.stats}")


def cmd_openalex_search(args) -> None:
    """只有 arXiv 预印本记录的主书架论文：用 OpenAlex search 找正式发表版本，补被引数 → openalex_search.jsonl。
    search 每次 $0.001；每天免费额度 $1。响应头里的剩余额度低于 --reserve 时停下，--wait-reset 则等到额度重置后接着跑。
    已经查过的论文（文件里有记录）跳过，可以断点续跑；HTTP 磁盘缓存保证复跑不再花钱。"""
    from hs import openalex as oa

    meta = load_meta()
    rec = load_openalex(merge_search=False)
    tiers = {r[0]: r[1] for r in duckdb.sql(f"SELECT arxiv, core FROM '{OUT / 'candidates.parquet'}'").fetchall()}
    todo = [a for a, m in rec.items() if m.get("preprint_only") and (tiers.get(a) or args.tier == "all")]
    out_p = OUT / "openalex_search.jsonl"
    done = {r["id"] for r in llm_batch.read_jsonl(out_p)} if out_p.exists() else set()
    todo = sorted(a for a in todo if a not in done)
    print(f"openalex-search: {len(todo):,} 篇待查（已查 {len(done):,}）", flush=True)
    http = Http()
    spent, found, t0 = 0.0, 0, time.time()
    with open(out_p, "a") as f:
        i = 0
        while i < len(todo):
            a = todo[i]
            m = meta.get(a) or {}
            year = int(m["published"][:4]) if m.get("published") else None
            best, r = oa.search_published(http, m.get("title") or "", year, m.get("authors") or [], rec[a]["openalex_id"])
            h = r.headers
            if r.status_code == 429 or (r.status_code != 200 and not r.from_cache):
                left = float(h.get("x-ratelimit-remaining-usd") or 0)
                if not args.wait_reset:
                    print(f"  停下：HTTP {r.status_code}，剩余 ${left:.4f}", flush=True)
                    break
                wait = int(h.get("x-ratelimit-reset") or 3600) + 120
                print(f"  HTTP {r.status_code}：等额度重置 {wait / 3600:.1f} 小时", flush=True)
                time.sleep(wait)
                continue
            if r.status_code == 200:
                row = {"id": a, "found": bool(best)}
                if best:
                    found += 1
                    row.update({"openalex_published_id": best["id"].rsplit("/", 1)[-1], "cited_by_published": best.get("cited_by_count"),
                                "published_doi": oa.norm_doi(best.get("doi")), "type": best.get("type"),
                                "year": best.get("publication_year"), "venue": oa.venue(best), "title": best.get("title")})
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
            i += 1
            if not r.from_cache:
                spent += float(h.get("x-ratelimit-cost-usd") or 0.001)
                left = h.get("x-ratelimit-remaining-usd")
                if i % 100 == 0:
                    print(f"  {i}/{len(todo)} 找到 {found}，本次花费 ${spent:.3f}，剩余 ${left}（{time.time() - t0:.0f}s）", flush=True)
                if left is not None and float(left) < args.reserve:
                    if not args.wait_reset:
                        print(f"  今天的额度只剩 ${float(left):.4f}，停下（明天再跑同一条命令）", flush=True)
                        break
                    wait = int(h.get("x-ratelimit-reset") or 3600) + 120
                    print(f"  今天的额度只剩 ${float(left):.4f}：等 {wait / 3600:.1f} 小时到额度重置再继续", flush=True)
                    time.sleep(wait)
    print(f"openalex-search: 本次查 {i:,} 篇，找到正式版本 {found:,}，花费约 ${spent:.3f}，http={http.stats}", flush=True)


# search 搜到的“正式版本”里，数据集和软件（TIB Data Manager、Zenodo 上的存档）不算发表（D25 第二天补记）
NOT_PUBLISHED = {"dataset", "software"}
# 机构或通用存档库的名字不当作“发表于”显示（被引数照用，它是整条 OpenAlex 记录的）
REPO_VENUE = re.compile(r"zenodo|data manager|discovery \(|infoscience|arkivet|apollo \(|repositor", re.I)


def load_openalex(merge_search: bool = True) -> dict[str, dict]:
    p = OUT / "openalex.jsonl"
    res = {m["id"]: m for m in llm_batch.read_jsonl(p)} if p.exists() else {}
    sp = OUT / "openalex_search.jsonl"
    if merge_search and sp.exists():
        for r in llm_batch.read_jsonl(sp):
            m = res.get(r["id"])
            if not m or not r.get("found") or r.get("type") in NOT_PUBLISHED:
                continue
            venue = r.get("venue") if r.get("venue") and not REPO_VENUE.search(r["venue"]) else None
            # 搜到的正式版本：被引取较大值，期刊/会议名补上
            m.update({"openalex_published_id": r["openalex_published_id"], "cited_by_published": r["cited_by_published"],
                      "cited_by": max(m.get("cited_by") or 0, r.get("cited_by_published") or 0),
                      "venue": m.get("venue") or venue, "published_doi": m.get("published_doi") or r.get("published_doi"),
                      "published_via": "search"})
    return res


def load_meta() -> dict[str, dict]:
    p = OUT / "arxiv_meta.jsonl"
    return {m["id"]: m for m in llm_batch.read_jsonl(p)} if p.exists() else {}


# ---------------------------------------------------------------- 1.4 立场标注
STANCE_PROMPT = """# 任务：判断 HN 评论对它链接的那篇论文是什么立场

输入是 JSONL，每行一条"评论 × 论文"：
`{"id", "paper_title", "story_title", "parent_snippet", "text"}`
- `paper_title`：评论链接的那篇 arXiv 论文的标题。
- `story_title`：评论所在 HN 讨论串的标题；`parent_snippet`：它回复的那条评论的开头（可能为空）。这两项只用来理解语境。
- `text`：评论全文。指向这篇论文的链接写成 `[PAPER]`，指向其他 arXiv 论文的写成 `[OTHER_PAPER]`，其他链接写成 `[LINK]`。

对每一行，判断评论者对**这篇论文（[PAPER]）**的立场，五选一：
- `strong_rec`：热情推荐，明确说值得读（"必读""改变了我的看法""best paper on X"）。
- `rec`：把别人指向这篇论文、建议去看，或正面评价它（"这篇讲得很清楚""see this paper, it covers..."）。
- `reference`：中性引用，拿它当出处、证据或背景，不表达要不要读（"according to [PAPER]""this was shown in [PAPER]"）。
- `joke`：玩梗、讽刺、把它当笑点。
- `critical`：批评、质疑、反驳这篇论文（方法、结论、炒作）。

判断要点：只看对 [PAPER] 本身的态度，不看评论者对话题、对讨论串标题或对其他论文的态度。拿论文当论据去反驳别人、但对论文本身中性 → `reference`。
评论只是贴出论文、附一句介绍内容的话 → `rec`。同时有肯定和批评时，看主要态度。

每行输出一个 JSON（顺序与输入一致，每个 id 都要有一行）：
```
{"id": <同输入>, "stance": "...", "confidence": 0.0-1.0, "quote": "评论里最能说明立场的一句原话，逐字摘录，≤300 字符", "why": "≤15 个英文词：按这条评论，读者能从论文里得到什么（joke/critical 可以留空）"}
```
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
"""

STANCE_PROMPT_V2 = """# 任务：判断 HN 评论对它链接的那篇论文是什么立场（v2）

输入是 JSONL 的 Markdown 视图，每条"评论 × 论文"：
`{"id", "paper_title", "story_title", "parent_snippet", "text"}`
- `paper_title`：评论链接的那篇 arXiv 论文的标题。
- `story_title`：评论所在 HN 讨论串的标题；`parent_snippet`：它回复的那条评论的开头（可能为空）。只用来理解语境。
- `text`：评论全文。指向这篇论文的链接写成 `[PAPER]`，指向其他 arXiv 论文的写成 `[OTHER_PAPER]`，其他链接写成 `[LINK]`。

只判断评论者对**这篇论文（[PAPER] / paper_title）本身**的态度。按下面的顺序判断，第一条符合的就是答案：

1. `joke`：论文本身被拿来当笑点、梗或讽刺对象。评论语气幽默、但论文是被认真引用的 → 不是 joke。
2. `critical`：评论者批评**这篇论文本身**——方法、证据、结论、严谨性、新意、宣传炒作。
   以下都**不是** critical：反驳别的评论者、批评文章/公司/产品/讨论串、论文本身报告的是负面结果、评论者只是说"这不能彻底解决问题"但没有指出论文的毛病。
3. `strong_rec`：热情推荐，有明确的强烈措辞：fantastic / brilliant / must-read / one of the best / changed how I think / no other work comes close / 强烈推荐 等。
4. `rec`：评论者认为这篇论文**值得看**——明确建议别人读（"worth reading" "check out" "I recommend" "read this paper"），或对论文质量给出正面评价（"great/excellent/interesting paper" "explains X really well" "a good overview"）。
5. `reference`：其余所有情况。包括：拿论文当出处或证据（"as shown in [PAPER]"）、给出新闻背后的原始论文、"here's the link / paper"、"there's a paper on this"、"reminds me of [PAPER]"、只引用摘要不评价、"I haven't read it yet"、介绍论文内容但不表态。

拿不准时：rec 和 reference 之间选 reference；strong_rec 和 rec 之间选 rec；critical 和 reference 之间选 reference。confidence 如实反映把握。

每行输出一个 JSON（顺序与输入一致，每个 id 都要有一行）：
```
{"id": <同输入>, "stance": "...", "confidence": 0.0-1.0, "quote": "评论里最能说明立场的一句原话，逐字摘录，≤300 字符", "why": "≤15 个英文词：按这条评论，读者能从论文里得到什么（joke/critical 可以留空）"}
```
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
"""

# v3（2026-11-03 审批）：在 v2 上补一条——明确让别人去读算 rec，只贴链接当论据算 reference。
STANCE_PROMPT_V3 = STANCE_PROMPT_V2.replace("（v2）", "（v3）").replace(
    """4. `rec`：评论者认为这篇论文**值得看**——明确建议别人读（"worth reading" "check out" "I recommend" "read this paper"），或对论文质量给出正面评价（"great/excellent/interesting paper" "explains X really well" "a good overview"）。
5. `reference`：其余所有情况。包括：拿论文当出处或证据（"as shown in [PAPER]"）、给出新闻背后的原始论文、"here's the link / paper"、"there's a paper on this"、"reminds me of [PAPER]"、只引用摘要不评价、"I haven't read it yet"、介绍论文内容但不表态。
""",
    """4. `rec`：评论者认为这篇论文**值得看**，满足下面任意一条：
   - 明确让别人去读、去看它，把它当成帮对方弄懂问题的读物："I'd point you to [PAPER]" "go read [PAPER]" "you'd be interested in [PAPER]" "you might like/enjoy" "check out" "worth reading" "I recommend" "read this paper"。
   - 说这篇论文把某件事讲得好，或对论文质量给出正面评价："[PAPER] explains this well" "a good overview" "great/excellent/interesting paper"。
5. `reference`：其余所有情况。包括：只把链接贴出来当论据或出处，支撑自己的说法（"as shown in [PAPER]" "source: [PAPER]" "see [PAPER]" 后面没有让人去读的意思）、给出新闻背后的原始论文、回答"有没有出处"时贴链接、"here's the link / paper"、"there's a paper on this"、"reminds me of [PAPER]"、只引用摘要不评价、"I haven't read it yet"、介绍论文内容但不表态。

rec 和 reference 的分界：评论者是在**建议对方去读它**（rec），还是**拿它支撑自己的说法**（reference）。
""")
assert "（v3）" in STANCE_PROMPT_V3 and "I'd point you to" in STANCE_PROMPT_V3

# v3 新规则的触发词：v2 里高置信度标成 reference、但文本里有这些说法的，也交给 Sonnet 复核
REC_CUES = re.compile(
    r"point(?:ed|ing)? (?:you|people|folks|them) (?:to|at|towards?)|go read|you(?:'d| would| might| may)?(?: also)? (?:be )?interested in"
    r"|you(?:'d| would| might| may)? (?:also )?(?:like|enjoy)|explains? (?:this|it|that|the \w+)(?: \w+)? (?:really |very |quite )?well"
    r"|worth (?:a |the )?(?:read|look)|check (?:out|this)|recommend|must[- ]read|should read|good (?:read|overview|intro)|great (?:read|paper)",
    re.I)

_URL_IN_TEXT = re.compile(r"https?://\S+")


def mask_links(text: str, aid: str) -> str:
    def rep(m: re.Match) -> str:
        url = m.group(0).rstrip(").,;:!?'\"")
        tail = m.group(0)[len(url):]
        got = arxiv_id(url)
        if got == aid:
            return "[PAPER]" + tail
        if got:
            return "[OTHER_PAPER]" + tail
        return "[LINK]" + tail
    return _URL_IN_TEXT.sub(rep, text)


def build_stance_items(rows: list[tuple], meta: dict[str, dict]) -> list[dict]:
    """rows: (hn_id, arxiv)。返回给子 agent 的输入行。"""
    con = connect(read_only=True)
    ids = sorted({r[0] for r in rows})
    texts = get_items(con, ids, "id, text")
    roots = root_stories(con, ids)
    pars = parent_snippets(con, ids)
    con.close()
    out = []
    for hn_id, aid in rows:
        t = texts.get(hn_id)
        if not t:
            continue
        out.append({
            "id": f"{hn_id}:{aid}", "paper_title": (meta.get(aid) or {}).get("title") or "",
            "story_title": (roots.get(hn_id) or (None, ""))[1] or "",
            "parent_snippet": mask_links(pars.get(hn_id, ""), aid)[:300],
            "text": clip_around_paper(mask_links(to_text(t[1]), aid)),
        })
    return out


def clip_around_paper(text: str, limit: int = 2000) -> str:
    """截到 limit 字符；如果 [PAPER] 落在截断之后，保留开头 + [PAPER] 前后的一段，保证模型看得到链接位置。"""
    if len(text) <= limit or "[PAPER]" in text[:limit]:
        return text[:limit]
    pos = text.find("[PAPER]")
    if pos < 0:
        return text[:limit]
    head = text[: limit - 700]
    tail = text[max(0, pos - 450): pos + 250]
    return f"{head} …（中间省略）… {tail}"


def cmd_stance_sample_v2(_args) -> None:
    """用 v2 prompt 在同样的 200 条上重跑（输入原样复制，保证可比）。"""
    items = list(llm_batch.inputs("stance_sample_haiku").values())
    for model in ("haiku", "sonnet"):
        llm_batch.prepare(f"stance_sample_{model}_v2", items, STANCE_PROMPT_V2, batch_size=50,
                          out_fields=["stance", "confidence", "quote", "why"], overwrite=True)
    print(f"stance-sample-v2: {len(items)} items")


def cmd_stance_sample_v3(_args) -> None:
    """v3 prompt 在同样的 200 对（评论 × 论文）上重跑。输入按现在的截取方式重建（v1/v2 样本有 [PAPER] 被截掉的条目）。"""
    rows = [(int(k.split(":", 1)[0]), k.split(":", 1)[1]) for k in llm_batch.inputs("stance_sample_haiku")]
    items = build_stance_items(rows, load_meta())
    for model in ("haiku", "sonnet"):
        llm_batch.prepare(f"stance_sample_{model}_v3", items, STANCE_PROMPT_V3, batch_size=100, max_chars=60000,
                          out_fields=["stance", "confidence", "quote", "why"], overwrite=True)
    print(f"stance-sample-v3: {len(items)} items, without [PAPER]: {sum('[PAPER]' not in x['text'] for x in items)}")


def cmd_stance_review_prepare(args) -> None:
    """核心集复核（Sonnet + v3 prompt）：最终标签置信度 < 阈值的，加上 v2 高置信度 reference 但文本里有"让人去读"说法的。"""
    labels = stance_labels()
    core = {r[0] for r in duckdb.sql(f"SELECT arxiv FROM '{OUT / 'candidates.parquet'}' WHERE core").fetchall()}
    core_in = llm_batch.inputs("stance_core") | llm_batch.inputs("stance_core_fix") | llm_batch.inputs("stance_core_missing")
    low, cue = [], []
    for k, v in labels.items():
        if k.split(":", 1)[1] not in core:
            continue
        c = v.get("confidence")
        if c is not None and c < args.min_conf:
            low.append(k)
        elif v["stance"] == "reference" and k in core_in and REC_CUES.search(core_in[k]["text"]):
            cue.append(k)
    rows = [(int(k.split(":", 1)[0]), k.split(":", 1)[1]) for k in low + cue]
    items = build_stance_items(rows, load_meta())
    why = {**{k: "low_conf" for k in low}, **{k: "rec_cue" for k in cue}}
    for x in items:
        x["_reason"] = why[x["id"]]  # 下划线字段不给模型看
    paths = llm_batch.prepare("stance_core_review", items, STANCE_PROMPT_V3, batch_size=100, max_chars=60000,
                              out_fields=["stance", "confidence", "quote", "why"], overwrite=True)
    print(f"stance-review-prepare: low_conf={len(low)}, rec_cue={len(cue)} → {len(items)} items, {len(paths)} batches")


def cmd_stance_sample(args) -> None:
    db = _db()
    db.execute(f"CREATE VIEW c AS SELECT arxiv FROM '{OUT / 'candidates.parquet'}'")
    rows = db.execute(f"SELECT hn_id, arxiv FROM m JOIN c USING (arxiv) WHERE {LABELABLE} ORDER BY hn_id, arxiv").fetchall()
    random.Random(args.seed).shuffle(rows)
    sample = rows[: args.n]
    items = build_stance_items(sample, load_meta())
    for model in ("haiku", "sonnet"):
        llm_batch.prepare(f"stance_sample_{model}", items, STANCE_PROMPT, batch_size=50,
                          out_fields=["stance", "confidence", "quote", "why"], overwrite=True)
    print(f"stance-sample: {len(items)} items from {len(rows):,} labelable mentions in the candidate set")


def cmd_stance_prepare(args) -> None:
    """核心集（3/3）全部待标注提及，按月排序后切批（同一个月的尽量在一批里），能断点续跑。"""
    db = _db()
    db.execute(f"CREATE VIEW c AS SELECT arxiv FROM '{OUT / 'candidates.parquet'}' WHERE {args.tier}")
    rows = db.execute(f"SELECT hn_id, arxiv FROM m JOIN c USING (arxiv) WHERE {LABELABLE} ORDER BY time, hn_id, arxiv").fetchall()
    items = build_stance_items(rows, load_meta())
    task = f"stance_{args.tier}"
    paths = llm_batch.prepare(task, items, STANCE_PROMPT_V2, batch_size=args.batch, max_chars=args.max_chars,
                              out_fields=["stance", "confidence", "quote", "why"], overwrite=True)
    print(f"stance-prepare: {len(items):,} items → {llm_batch.task_dir(task)} ({len(paths)} batches)")


def cmd_stance_fix(_args) -> None:
    """核心集里 [PAPER] 被 2000 字截断丢掉的条目，用新的截取方式重新准备（标注结果覆盖 stance_core）。"""
    ins = llm_batch.inputs("stance_core")
    rows = [(int(k.split(":", 1)[0]), k.split(":", 1)[1]) for k, x in ins.items() if "[PAPER]" not in x["text"]]
    items = build_stance_items(rows, load_meta())
    paths = llm_batch.prepare("stance_core_fix", items, STANCE_PROMPT_V2, batch_size=100, max_chars=60000,
                              out_fields=["stance", "confidence", "quote", "why"], overwrite=True)
    still = sum("[PAPER]" not in x["text"] for x in items)
    print(f"stance-fix: {len(items)} items, {len(paths)} batches, still without [PAPER]: {still}")


def cmd_stance_agree(args) -> None:
    sfx = args.suffix
    a, b = llm_batch.outputs(f"stance_sample_haiku{sfx}"), llm_batch.outputs(f"stance_sample_sonnet{sfx}")
    keys = sorted(set(a) & set(b))
    pos = {"rec", "strong_rec"}
    same = sum(a[k].get("stance") == b[k].get("stance") for k in keys)
    same_bin = sum((a[k].get("stance") in pos) == (b[k].get("stance") in pos) for k in keys)
    conf = Counter((a[k].get("stance"), b[k].get("stance")) for k in keys)
    res = {"n": len(keys), "agree_5": same / max(1, len(keys)), "agree_pos_vs_not": same_bin / max(1, len(keys)),
           "haiku": dict(Counter(a[k].get("stance") for k in keys)), "sonnet": dict(Counter(b[k].get("stance") for k in keys)),
           "confusion": {f"{x}|{y}": n for (x, y), n in conf.most_common()},
           "disagreements": [k for k in keys if a[k].get("stance") != b[k].get("stance")]}
    (OUT / f"stance_agreement{sfx}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in res.items() if k != "disagreements"}, indent=1, ensure_ascii=False))


def _review_sheet_path():
    from pathlib import Path
    return Path(__file__).resolve().parents[3] / "reports" / "phase1" / "stance_review_50.md"


def cmd_stance_review_sheet(args) -> None:
    """人工核对表（50 条）：先放 v3 样本里 Haiku/Sonnet 的全部分歧，其余从核心集最终标签里随机抽。"""
    labels = stance_labels()
    core = {r[0] for r in duckdb.sql(f"SELECT arxiv FROM '{OUT / 'candidates.parquet'}' WHERE core").fetchall()}
    a, b = llm_batch.outputs("stance_sample_haiku_v3"), llm_batch.outputs("stance_sample_sonnet_v3")
    disagree = [k for k in sorted(set(a) & set(b)) if a[k].get("stance") != b[k].get("stance")]
    pool = sorted(k for k in labels if k.split(":", 1)[1] in core and k not in disagree)
    random.Random(args.seed).shuffle(pool)
    keys = disagree + pool[: args.n - len(disagree)]
    ins = (llm_batch.inputs("stance_sample_haiku_v3") | llm_batch.inputs("stance_core") | llm_batch.inputs("stance_core_fix")
           | llm_batch.inputs("stance_core_missing") | llm_batch.inputs("stance_core_review"))
    lines = ["# 立场标注人工核对（50 条，v3 prompt，最终标签）", "",
             f"PLAN Phase 1 要求抽 50 条人工核对、一致率 ≥90%。前 {len(disagree)} 条是 v3 样本里 Haiku 和 Sonnet 的全部分歧（难例），"
             f"其余 {len(keys) - len(disagree)} 条从主书架 8,152 条最终标签里随机抽（种子 {args.seed}）。",
             "在「我的判断」后面填 strong_rec / rec / reference / joke / critical；填完运行 "
             "`cd pipeline && uv run python -m hs.steps.papers stance-review-score` 算一致率（随机部分和难例分开算）。",
             "原文已去链接（[PAPER] = 这篇论文）。立场定义见 `data/llm/stance_core_review/prompt.md`（v3）。", ""]
    for i, k in enumerate(keys, 1):
        hn_id, aid = k.split(":", 1)
        x = ins.get(k, {})
        lab = labels.get(k, {})
        tag = "难例" if k in disagree else "随机"
        lines += [f"## {i}. {x.get('paper_title') or aid}", "",
                  f"- 论文：`{aid}`　评论：https://news.ycombinator.com/item?id={hn_id}　讨论串：{x.get('story_title', '')}",
                  f"- 最终标签：**{lab.get('stance')}**（{lab.get('model', '').replace('claude-', '')}，置信度 {lab.get('confidence')}）　[{tag}]"
                  + (f"　v3 样本：Haiku **{a[k]['stance']}** / Sonnet **{b[k]['stance']}**" if k in disagree else ""),
                  "- 我的判断：", ""]
        text = (x.get("text") or "").replace("\n", " ")
        lines += ["> " + (text[:700] + ("…" if len(text) > 700 else "")), ""]
    _review_sheet_path().parent.mkdir(parents=True, exist_ok=True)
    _review_sheet_path().write_text("\n".join(lines))
    print(f"stance-review-sheet: {len(keys)} items ({len(disagree)} hard) → {_review_sheet_path()}")


def cmd_stance_review_score(_args) -> None:
    """读人工核对表里填好的「我的判断」，算一致率。"""
    txt = _review_sheet_path().read_text()
    blocks = re.split(r"\n## \d+\. ", txt)[1:]
    res = {"难例": [0, 0], "随机": [0, 0]}
    pos = {"rec", "strong_rec"}
    pos_same = pos_n = 0
    for blk in blocks:
        final = re.search(r"最终标签：\*\*(\w+)\*\*", blk)
        mine = re.search(r"我的判断：\s*(strong_rec|rec|reference|joke|critical)", blk)
        tag = "难例" if "[难例]" in blk else "随机"
        if final and mine:
            res[tag][0] += final.group(1) == mine.group(1)
            res[tag][1] += 1
            pos_same += (final.group(1) in pos) == (mine.group(1) in pos)
            pos_n += 1
    for tag, (same, n) in res.items():
        print(f"{tag}: {same}/{n}" + (f" = {same / n:.1%}" if n else "（还没填）"))
    tot_same, tot_n = sum(v[0] for v in res.values()), sum(v[1] for v in res.values())
    if tot_n:
        print(f"合计：{tot_same}/{tot_n} = {tot_same / tot_n:.1%}；正向/非正向 {pos_same / pos_n:.1%}（验收线 ≥90%）")


# ---------------------------------------------------------------- 1.5 卡片样本
CARD_PROMPT = """# 任务：给 HN 上被反复推荐的 arXiv 论文写一张卡片

输入是 JSONL，每行一篇论文：
`{"id", "title", "authors", "year", "categories", "abstract", "hn": {"people", "months", "first", "last", "by_year"}, "mentions": [{"stance", "quote", "why", "story_title", "year"}]}`
`mentions` 是 HN 评论者的原话摘录（最多 20 条，带立场标签）。

为每篇论文写一张卡片，每行输出一个 JSON（顺序与输入一致）：
```
{"id": <同输入>,
 "title_zh": "标题的中文译名（术语保留英文，如 Transformer）",
 "summary_zh": "2–3 句中文：这篇论文做了什么、核心结论是什么。准确、具体，不写空话。",
 "summary_en": "2–3 sentences in English, same content.",
 "why_hn": "一句中文：HN 上的人为什么反复提它、拿它说明什么（依据 mentions，不要编造）。",
 "type": "foundational | method | survey | empirical | position | tutorial | other",
 "difficulty": 1-5,
 "prerequisites": ["读懂它需要的前置知识，2–5 个短语，英文术语"],
 "shelf_life": "evergreen | dated",
 "reading_minutes": 整数（认真读一遍正文的时间，按页数和密度估）}
```
- difficulty：1 = 科普读者能读；3 = 本领域研究生；5 = 需要专门方向的深厚背景。
- shelf_life：dated = 结论绑定某个具体模型版本或时间点的评测、很快会过时；其余 evergreen。
- 只根据输入写，不要编造论文里没有的数字或结论；拿不准就写得保守。
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
"""


# v2（2026-11-03 审批）：前置知识改中文、保留英文术语；加一行摘要 oneliner_zh，给首页长青榜用
CARD_PROMPT_V2 = CARD_PROMPT.replace(
    """ "summary_zh": "2–3 句中文：这篇论文做了什么、核心结论是什么。准确、具体，不写空话。",""",
    """ "oneliner_zh": "一行中文摘要，不超过 40 个汉字：这篇论文是什么、讲了什么。用在列表里，不要以“本文”“这篇论文”开头。",
 "summary_zh": "2–3 句中文：这篇论文做了什么、核心结论是什么。准确、具体，不写空话。",""").replace(
    """ "prerequisites": ["读懂它需要的前置知识，2–5 个短语，英文术语"],""",
    """ "prerequisites": ["读懂它需要的前置知识，2–5 个中文短语；专业术语保留英文原词，例如“Transformer 架构”“贝叶斯推断（Bayesian inference）”“λ 演算（lambda calculus）”"],""")
assert "oneliner_zh" in CARD_PROMPT_V2 and "中文短语" in CARD_PROMPT_V2
CARD_FIELDS = ["oneliner_zh", "title_zh", "summary_zh", "summary_en", "why_hn", "type", "difficulty",
               "prerequisites", "shelf_life", "reading_minutes"]


def stance_labels() -> dict[str, dict]:
    """合并所有立场标注任务的输出：comment_id:arxiv → 标签。后面的覆盖前面的：
    样本 v1 → 样本 v2（Sonnet 优先于 Haiku）→ 核心集正式标注（生产配置）→ 每月的增量（D47，按日期，复核排在它那一批后面）。"""
    res: dict[str, dict] = {}
    inc = [(t, llm_batch.manifest(t).get("model") or (SONNET if t.endswith("_review") else HAIKU))
           for t in llm_batch.tasks_like(STANCE_INC)]
    for task, model in [("stance_sample_haiku", HAIKU), ("stance_sample_sonnet", SONNET),
                        ("stance_sample_haiku_v2", HAIKU), ("stance_sample_sonnet_v2", SONNET),
                        ("stance_core", HAIKU), ("stance_core_fix", HAIKU),
                        ("stance_core_missing", HAIKU),
                        # v3 复核（Sonnet）：低置信度 + "让人去读"线索，覆盖上面的 Haiku 标签
                        ("stance_core_review", SONNET), *inc]:
        if not (llm_batch.task_dir(task) / "manifest.json").exists():
            continue
        valid = set(llm_batch.inputs(task))  # 只认输入里存在的 id（防止模型写错或编出 id）
        for k, v in llm_batch.outputs(task).items():
            if k in valid and v.get("stance") in STANCES:
                res[k] = {**v, "model": model}
    return res


def paper_stats(labels: dict[str, dict]) -> tuple[dict[str, dict], dict]:
    """论文级统计：人数、月份、讨论串、按年、months_rec、months_strong、暂定分数。"""
    db = _db()
    rows = db.execute(f"""SELECT m.arxiv, m.hn_id, m."by", m.month, year(m.time), m.src, m.time
                          FROM m JOIN '{OUT / 'candidates.parquet'}' c USING (arxiv) WHERE {COUNTED}""").fetchall()
    con = connect(read_only=True)
    roots = root_stories(con, sorted({r[1] for r in rows}))
    con.close()
    cap = int(cfg()["rules"].get("score_months_per_person", 0))
    # "上升中"：最近 12 个月（相对数据截止月）里活跃 / 有推荐的月份数
    last = max((r[6] for r in rows), default=None)
    recent_from = f"{last.year - 1:04d}-{last.month:02d}" if last else "9999-99"
    st: dict[str, dict] = defaultdict(lambda: {"people": set(), "months": set(), "threads": set(), "by_year": Counter(),
                                               "rec": set(), "strong": set(), "labeled": 0, "labelable": 0,
                                               "first": None, "last": None, "pm_rec": defaultdict(set),
                                               "pm_strong": defaultdict(set)})
    for aid, hn_id, by, month, yr, src, t in sorted(rows, key=lambda r: r[6]):
        s = st[aid]
        s["people"].add(by)
        s["months"].add(month)
        s["by_year"][str(yr)] += 1
        root = roots.get(hn_id)
        if root:
            s["threads"].add(root[0])
        s["first"] = t if s["first"] is None or t < s["first"] else s["first"]
        s["last"] = t if s["last"] is None or t > s["last"] else s["last"]
        if src != "story_url":
            s["labelable"] += 1
            lab = labels.get(f"{hn_id}:{aid}")
            if lab:
                s["labeled"] += 1
                # 每人最多贡献 cap 个月（按时间先后取），防止一个人反复贴同一篇刷分
                if lab["stance"] in ("rec", "strong_rec") and (not cap or month in s["pm_rec"][by] or len(s["pm_rec"][by]) < cap):
                    s["pm_rec"][by].add(month)
                    s["rec"].add(month)
                if lab["stance"] == "strong_rec" and (not cap or month in s["pm_strong"][by] or len(s["pm_strong"][by]) < cap):
                    s["pm_strong"][by].add(month)
                    s["strong"].add(month)
    out = {}
    for aid, s in st.items():
        out[aid] = {"active_12m": sum(1 for mo in s["months"] if mo > recent_from),
                    "rec_12m": sum(1 for mo in s["rec"] if mo > recent_from),
                    "people": len(s["people"]), "threads": len(s["threads"]), "active_months": len(s["months"]),
                    "months_rec": len(s["rec"]), "months_strong": len(s["strong"]),
                    "first_mention": s["first"].date().isoformat(), "last_mention": s["last"].date().isoformat(),
                    "by_year": dict(sorted(s["by_year"].items())), "has_positive": bool(s["rec"]),
                    "labeled": s["labeled"], "labelable": s["labelable"],
                    "score": len(s["rec"]) + 0.5 * len(s["strong"])}
    return out, roots


def core_ids() -> set[str]:
    return {r[0] for r in duckdb.sql(f"SELECT arxiv FROM '{OUT / 'candidates.parquet'}' WHERE core").fetchall()}


def card_outputs() -> dict[str, dict]:
    """全部写卡片任务的输出：arxiv → 卡片。后面的覆盖前面的：样本 → 主书架全量 → 每月的增量（D47）。"""
    cards: dict[str, dict] = {}
    for task in ("cards_sample", "cards_core", *llm_batch.tasks_like(CARDS_INC)):
        if (llm_batch.task_dir(task) / "manifest.json").exists():
            valid = set(llm_batch.inputs(task))
            cards.update({k: v for k, v in llm_batch.outputs(task).items() if k in valid})
    return cards


def cmd_cards_prepare(args) -> None:
    labels = stance_labels()
    stats, _ = paper_stats(labels)
    meta = load_meta()
    cand = {r[0]: r for r in duckdb.sql(f"SELECT arxiv, core FROM '{OUT / 'candidates.parquet'}'").fetchall()}
    # 核心集里、全部提及都已标注的论文，按暂定分数排；没有标注时退回按人数排
    if args.all_core:
        pool = [a for a, s in stats.items() if cand.get(a, (a, False))[1] and a in meta]
    else:
        pool = [a for a, s in stats.items() if cand.get(a, (a, False))[1] and s["labeled"] == s["labelable"] > 0 and a in meta]
        if len(pool) < args.n:
            pool = [a for a, s in stats.items() if cand.get(a, (a, False))[1] and a in meta]
    pool.sort(key=lambda a: (-stats[a]["score"], -stats[a]["people"]))
    top = pool if args.all_core else pool[: args.n]
    items = card_items(top, labels, stats, meta)
    task = args.task
    prompt = CARD_PROMPT_V2 if args.prompt == "v2" else CARD_PROMPT
    paths = llm_batch.prepare(task, items, prompt, batch_size=args.batch, max_chars=args.max_chars,
                              out_fields=CARD_FIELDS, overwrite=True)
    print(f"cards-prepare: {len(items)} papers (pool {len(pool)}) → {llm_batch.task_dir(task)} ({len(paths)} batches)")


def card_items(top: list[str], labels: dict[str, dict], stats: dict[str, dict], meta: dict[str, dict]) -> list[dict]:
    """写卡片的输入：元数据、摘要、HN 统计，加最多 20 条提及（先推荐和批评，没标注的给原文开头）。"""
    db = _db()
    con = connect(read_only=True)
    items = []
    for aid in top:
        ms = db.execute(f"""SELECT hn_id, year(time) FROM m WHERE arxiv = ? AND {LABELABLE} ORDER BY time""", [aid]).fetchall()
        texts = get_items(con, [h for h, _ in ms if f"{h}:{aid}" not in labels], "id, text")
        mlist = []
        for hn_id, yr in ms:
            lab = labels.get(f"{hn_id}:{aid}")
            if lab:
                mlist.append({"stance": lab["stance"], "quote": lab.get("quote", ""), "why": lab.get("why", ""), "year": yr})
            elif hn_id in texts:
                mlist.append({"stance": "unlabeled", "quote": mask_links(to_text(texts[hn_id][1]), aid)[:400], "why": "", "year": yr})
        order = list(STANCES) + ["unlabeled"]
        mlist = sorted(mlist, key=lambda x: order.index(x["stance"]))[:20]
        m = meta[aid]
        s = stats[aid]
        items.append({"id": aid, "title": m["title"], "authors": m["authors"][:8], "year": int(m["published"][:4]),
                      "categories": m["categories"], "abstract": m["abstract"],
                      "hn": {"people": s["people"], "months": s["active_months"], "first": s["first_mention"],
                             "last": s["last_mention"], "by_year": s["by_year"]}, "mentions": mlist})
    con.close()
    return items


# ---------------------------------------------------------------- 月度更新的增量任务（D47）
def unlabeled_core_rows() -> list[tuple[int, str]]:
    """主书架（3/3）里还没有立场标签的可标注提及 (hn_id, arxiv)，按时间排。新进主书架的论文，它以前的提及也在里面。"""
    labels = stance_labels()
    db = _db()
    db.execute(f"CREATE VIEW c AS SELECT arxiv FROM '{OUT / 'candidates.parquet'}' WHERE core")
    rows = db.execute(f"SELECT hn_id, arxiv FROM m JOIN c USING (arxiv) WHERE {LABELABLE} ORDER BY time, hn_id, arxiv").fetchall()
    return [(h, a) for h, a in rows if f"{h}:{a}" not in labels]


def cmd_stance_inc_prepare(args) -> None:
    """没有标签的主书架提及 → stance_inc_<tag>（Haiku + v3 prompt）。没有要标的就不建任务。"""
    rows = unlabeled_core_rows()
    task = f"{STANCE_INC}{args.tag}"
    if not rows:
        print("stance-inc-prepare: 主书架的提及都有标签了，不建任务")
        return
    items = build_stance_items(rows, load_meta())
    paths = llm_batch.prepare(task, items, STANCE_PROMPT_V3, batch_size=args.batch, max_chars=args.max_chars,
                              out_fields=STANCE_FIELDS, model=HAIKU)
    papers = len({a for _, a in rows})
    print(f"stance-inc-prepare: {len(items):,} 条（{papers} 篇论文；正文取不到、跳过 {len(rows) - len(items)} 条）"
          f" → {llm_batch.task_dir(task)}（{len(paths)} 批，Haiku）")


def cmd_stance_inc_review_prepare(args) -> None:
    """增量标注的复核（Sonnet + v3）：置信度低于 --min-conf 的、输出无效的，加上标成 reference 但文本里有“让人去读”说法的。"""
    base = f"{STANCE_INC}{args.tag}"
    ins, outs = llm_batch.inputs(base), llm_batch.outputs(base)
    picked: dict[str, str] = {}
    for k, x in ins.items():
        v = outs.get(k) or {}
        c = v.get("confidence")
        if v.get("stance") not in STANCES:
            picked[k] = "invalid"
        elif isinstance(c, (int, float)) and c < args.min_conf:
            picked[k] = "low_conf"
        elif v["stance"] == "reference" and REC_CUES.search(x["text"]):
            picked[k] = "rec_cue"
    task = f"{base}_review"
    if not picked:
        print("stance-inc-review-prepare: 没有要复核的，不建任务")
        return
    items = [{**ins[k], "_reason": r} for k, r in picked.items()]  # 下划线字段不给模型看
    paths = llm_batch.prepare(task, items, STANCE_PROMPT_V3, batch_size=100, max_chars=60000,
                              out_fields=STANCE_FIELDS, model=SONNET)
    print(f"stance-inc-review-prepare: {dict(Counter(picked.values()))} → {llm_batch.task_dir(task)}（{len(paths)} 批，Sonnet）")


def cmd_cards_inc_prepare(args) -> None:
    """主书架里还没有卡片的论文（多是这个月新进的）→ cards_inc_<tag>（Sonnet + 卡片 v2）。要在立场标注之后跑。"""
    labels = stance_labels()
    stats, _ = paper_stats(labels)
    meta = load_meta()
    have = card_outputs()
    core = core_ids()
    todo = sorted((a for a in stats if a in core and a in meta and a not in have),
                  key=lambda a: (-stats[a]["score"], -stats[a]["people"]))
    no_meta = sum(1 for a in core if a not in meta)
    task = f"{CARDS_INC}{args.tag}"
    if not todo:
        print(f"cards-inc-prepare: 主书架都有卡片了（没有 arXiv 元数据、写不了的 {no_meta} 篇），不建任务")
        return
    items = card_items(todo, labels, stats, meta)
    paths = llm_batch.prepare(task, items, CARD_PROMPT_V2, batch_size=args.batch, max_chars=args.max_chars,
                              out_fields=CARD_FIELDS, model=SONNET)
    print(f"cards-inc-prepare: {len(items)} 篇 → {llm_batch.task_dir(task)}（{len(paths)} 批，Sonnet）")


WHY_ZH_PROMPT = """# 任务：把 HN 评论"为什么提这篇论文"写成一句中文

输入是 JSONL，每行一条 HN 评论对一篇论文的提及：
`{"id", "paper", "paper_zh", "stance", "quote", "why"}`
- `stance`：评论对论文的立场（strong_rec 强烈推荐 / rec 推荐 / critical 批评 / reference 引用 / joke 玩笑）
- `quote`：评论原话摘录（英文）
- `why`：英文的一句说明，概括这条评论在说这篇论文什么

为每条写一句中文，放在网页上英文原话的下面，让中文读者一眼看懂这位评论者为什么提它、拿它说什么。
每行输出一个 JSON（顺序与输入一致）：
```
{"id": <同输入>, "why_zh": "一句中文"}
```
要求：
- 不超过 40 个汉字（英文术语按一个词算），一句话，句末不加句号。
- 忠实于 `quote` 和 `why`，不添加原话里没有的信息、数字或评价；`why` 和原话不一致时以原话为准。
- 从评论者的角度写这条评论做了什么，省略主语："推荐…"、"批评…"、"拿它说明…"、"把它当作…"。不要以"评论者"、"该评论"、"这条评论"开头。
- 专业术语保留英文原词（Transformer、LLM、RL、backprop），论文名不用写全，必要时用 `paper_zh` 里的简称。
- 批评要写清楚批评的是什么；玩笑写清楚在调侃什么。
- 不要用"他""她"指代评论者（不知道性别），需要时省略主语。
- 不要写"列为第 2 条参考"这类只描述贴链接格式的话，写这篇论文在评论里起什么作用。
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
"""


def why_zh_items() -> list[dict]:
    """主书架里会显示的、有英文 why 的已标注评论（按 catalog 的 20 条保留规则选出），需要先跑过 catalog。"""
    items = {i["id"]: i for i in llm_batch.read_jsonl(PATHS.build / "items.jsonl")}
    out = []
    for m in llm_batch.read_jsonl(PATHS.build / "mentions.jsonl"):
        it = items.get(m["item_id"])
        if not it or it["tier"] != "core" or m["source"] != "comment_link" or not m.get("stance") or not m.get("why"):
            continue
        out.append({"id": f"{m['comment_id']}:{m['item_id']}", "paper": it["title"], "paper_zh": it.get("title_zh") or "",
                    "stance": m["stance"], "quote": (m.get("quote") or "")[:400], "why": m["why"]})
    return out


def cmd_why_zh_prepare(args) -> None:
    items = why_zh_items()
    if args.sample:
        rng = random.Random(args.seed)
        items = rng.sample(items, min(args.sample, len(items)))
    elif args.exclude_sample:
        done = set(llm_batch.inputs("why_zh_sample")) if (llm_batch.task_dir("why_zh_sample") / "manifest.json").exists() else set()
        items = [x for x in items if x["id"] not in done]
    paths = llm_batch.prepare(args.task, items, WHY_ZH_PROMPT, batch_size=args.batch, out_fields=["why_zh"], overwrite=True)
    print(f"why-zh-prepare: {len(items):,} 条 → {llm_batch.task_dir(args.task)}（{len(paths)} 批）")


def cmd_why_zh_inc_prepare(args) -> None:
    """详情页会显示、还没有中文“为什么”的主书架评论 → why_zh_inc_<tag>（Sonnet）。要先跑一次 catalog。"""
    have = why_zh_labels()
    items = [x for x in why_zh_items() if x["id"] not in have]
    task = f"{WHY_ZH_INC}{args.tag}"
    if not items:
        print("why-zh-inc-prepare: 都有中文说明了，不建任务")
        return
    paths = llm_batch.prepare(task, items, WHY_ZH_PROMPT, batch_size=args.batch, out_fields=["why_zh"], model=SONNET)
    print(f"why-zh-inc-prepare: {len(items):,} 条 → {llm_batch.task_dir(task)}（{len(paths)} 批，Sonnet）")


def why_zh_labels() -> dict[str, str]:
    """comment_id:arxiv → 中文"为什么"。后面的任务覆盖前面的（最后是每月的增量，D47）。"""
    res: dict[str, str] = {}
    for task in ("why_zh_sample", "why_zh_sample_sonnet", "why_zh_core", *llm_batch.tasks_like(WHY_ZH_INC)):
        if not (llm_batch.task_dir(task) / "manifest.json").exists():
            continue
        valid = set(llm_batch.inputs(task))
        for k, v in llm_batch.outputs(task).items():
            if k in valid and isinstance(v.get("why_zh"), str) and v["why_zh"].strip():
                res[k] = v["why_zh"].strip().rstrip("。")
    return res


# ---------------------------------------------------------------- 1.6 暂定 catalog
AI_CATS = {"cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.NE", "cs.IR", "cs.RO", "cs.MA", "stat.ML"}


def field_of(cats: list[str], primary: str | None) -> str:
    p = primary or (cats[0] if cats else "")
    if p in AI_CATS:
        return "ai"
    if p.startswith("cs.") or p.startswith("eess."):
        return "cs"
    if p.startswith("math") or p.startswith("stat"):
        return "math"
    if p.split(".")[0] in {"physics", "astro-ph", "cond-mat", "quant-ph", "hep-th", "hep-ph", "hep-ex", "hep-lat",
                           "gr-qc", "nucl-th", "nucl-ex", "nlin", "math-ph"}:
        return "physics"
    if p.startswith("q-bio"):
        return "bio"
    if p.startswith("econ") or p.startswith("q-fin"):
        return "econ"
    return "other"


def thread_quotes(need: set[str], mentions_out: list[dict], per_paper: int = 3) -> list[dict]:
    """need 里每篇论文：在它被提交的 story 讨论串里，取回复最多、自己文字 ≥ MIN_CHARS 的顶层评论，最多 per_paper 条。"""
    from hs.text import own_len

    stories: dict[str, list[tuple[int, str | None]]] = defaultdict(list)
    for mm in mentions_out:
        if mm["item_id"] in need and mm["source"] == "story_url":
            stories[mm["item_id"]].append((mm["comment_id"], mm["story_title"]))
    sids = sorted({sid for v in stories.values() for sid, _ in v})
    if not sids:
        return []
    con = connect(read_only=True)
    top = con.execute(f"SELECT id, parent FROM tree WHERE type = 2 AND parent IN ({','.join(map(str, sids))})").fetchall()
    tids = [t for t, _ in top]
    replies = dict(con.execute(f"SELECT parent, count(*) FROM tree WHERE parent IN ({','.join(map(str, tids))}) GROUP BY parent").fetchall()) if tids else {}
    rows = get_items(con, tids, 'id, "by", time, text')
    con.close()
    by_story: dict[int, list] = defaultdict(list)
    for t, sid in top:
        r = rows.get(t)
        if r and r[3] and own_len(r[3]) >= MIN_CHARS:
            by_story[sid].append((replies.get(t, 0), r))
    out = []
    for aid, sts in stories.items():
        cands = sorted(((n, r, sid, title) for sid, title in sts for n, r in by_story.get(sid, [])), key=lambda x: -x[0])
        seen = set()
        for n, r, sid, title in cands:
            if r[1] in seen:
                continue
            seen.add(r[1])
            out.append({"comment_id": r[0], "item_id": aid, "by": r[1], "time": r[2].strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "story_id": sid, "story_title": title, "quote": None, "why": None, "why_zh": None, "text": to_text(r[3])[:2000],
                        "points": None, "stance": None, "stance_confidence": None, "source": "thread_comment", "model": None})
            if len(seen) >= per_paper:
                break
    return out


# 保留顺序：推荐和批评 → 引用 → 玩笑 → 没有标签的评论 → story 提交
KEEP_CLASS = {"strong_rec": 0, "rec": 0, "critical": 0, "reference": 1, "joke": 2}


def select_mentions(rs: list[tuple], labels: dict[str, dict], cap: int) -> list[tuple]:
    """rs：一篇论文的提及 (arxiv, hn_id, by, time, src)。按 KEEP_CLASS 分类，每类先不同的人、再按时间，取前 cap 条。"""
    def cls(r) -> int:
        if r[4] == "story_url":
            return 4
        lab = labels.get(f"{r[1]}:{r[0]}")
        return KEEP_CLASS.get((lab or {}).get("stance"), 3)

    out, seen = [], set()
    for c in range(5):
        group = sorted((r for r in rs if cls(r) == c), key=lambda r: r[3])
        first, rest = [], []
        for r in group:
            (first if r[2] not in seen else rest).append(r)
            seen.add(r[2])
        out.extend(first + rest)
        if len(out) >= cap:
            break
    return out[:cap]


def cmd_catalog(args) -> None:
    import sqlite3

    tiers = {r[0]: ("core" if r[1] else "cand")
             for r in duckdb.sql(f"SELECT arxiv, core FROM '{OUT / 'candidates.parquet'}'").fetchall()}
    # 立场标签只用于 3/3 主书架；2/2 候选层一律显示"被提及"（2026-11-03 审批）
    labels = {k: v for k, v in stance_labels().items() if tiers.get(k.split(":", 1)[1]) == "core"}
    stats, roots = paper_stats(labels)
    why_zh = why_zh_labels()
    meta = load_meta()
    oa = load_openalex()
    topics = json.loads((OUT / "topics.json").read_text()) if (OUT / "topics.json").exists() else {}
    taxonomy = json.loads((PATHS.build / "taxonomy.json").read_text()) if (PATHS.build / "taxonomy.json").exists() else {"areas": []}
    related = {r["item_id"]: r["related"] for r in llm_batch.read_jsonl(PATHS.build / "related.jsonl")}
    cards = card_outputs()

    # 提及：每篇最多 20 条（2026-11-03 审批）。先留推荐和批评，再用引用补满，然后是玩笑、没有标签的评论、story 提交；
    # 每一类里都先取不同的人（每人最早一条），再按时间补同一个人的其他评论。统计数字仍用全部提及。
    db = _db()
    rows = db.execute(f"""SELECT m.arxiv, m.hn_id, m."by", m.time, m.src
                          FROM m JOIN '{OUT / 'candidates.parquet'}' c USING (arxiv) WHERE {COUNTED}
                          ORDER BY m.arxiv, m.time""").fetchall()
    per: dict[str, list] = defaultdict(list)
    for r in rows:
        per[r[0]].append(r)
    con = connect(read_only=True)
    keep = []
    cap = int(cfg()["rules"]["max_mentions_per_item"])
    for aid, rs in per.items():
        keep.extend(select_mentions(rs, labels, cap))
    texts = get_items(con, [r[1] for r in keep], "id, text, title, score")
    con.close()

    # 参考文献里有几篇在书架上（学习路径排不排得出，D38）：OpenAlex 的 W id（预印本和正式版）映射回 arXiv 编号
    w2a = {}
    for a2, m2 in oa.items():
        for k in ("openalex_id", "openalex_published_id"):
            if m2.get(k):
                w2a[m2[k]] = a2
    shelf = set(stats)

    items_out, mentions_out = [], []
    for aid, s in stats.items():
        m = meta.get(aid, {})
        plain = aid.removeprefix("arxiv:")
        card = cards.get(aid)
        item = {
            "id": aid, "kind": "paper", "title": m.get("title") or aid,
            "title_zh": (card or {}).get("title_zh"), "authors": m.get("authors", []),
            "year": int(m["published"][:4]) if m.get("published") else None,
            "abstract": m.get("abstract"),
            "links": {"abs": f"https://arxiv.org/abs/{plain}", "html": f"https://arxiv.org/html/{plain}",
                      "pdf": f"https://arxiv.org/pdf/{plain}", "alphaxiv": f"https://www.alphaxiv.org/abs/{plain}"},
            "license": "unknown", "can_redistribute": False,
            "categories": m.get("categories", []), "primary_category": m.get("primary_category"),
            "topics": [topics[aid]["topic"]] if aid in topics else [], "area": (topics.get(aid) or {}).get("area"),
            "field": field_of(m.get("categories", []), m.get("primary_category")),
            "tier": tiers.get(aid, "cand"),
            "hn": {k: s[k] for k in ("people", "threads", "active_months", "months_rec", "months_strong",
                                     "first_mention", "last_mention", "by_year", "has_positive", "labeled", "labelable",
                                     "active_12m", "rec_12m")},
            "score": s["score"],
            "card": ({k: card.get(k) for k in CARD_FIELDS if k != "title_zh"} if card else None),
            "metrics": ({"cited_by": oa[aid]["cited_by"], "openalex_id": oa[aid]["openalex_id"],
                         "venue": oa[aid].get("venue"), "openalex_topic": (oa[aid].get("primary_topic") or {}).get("name"),
                         "n_references": len(oa[aid].get("references") or []),
                         "refs_on_shelf": len({w2a[r] for r in (oa[aid].get("references") or []) if w2a.get(r) in shelf and w2a[r] != aid})}
                        if aid in oa else {}),
            "thumb": None,  # catalog.db 的列留着；公开仓库不生成 PDF 缩略图
        }
        items_out.append(item)
    # 主书架在前（按分数），候选层在后（没有标签，按人数、月份）
    items_out.sort(key=lambda x: (x["tier"] != "core", -x["score"], -x["hn"]["people"], -x["hn"]["active_months"]))
    for aid, hn_id, by, t, src in keep:
        tx = texts.get(hn_id)
        root = roots.get(hn_id)
        lab = labels.get(f"{hn_id}:{aid}") if src != "story_url" else None
        mentions_out.append({
            "comment_id": hn_id, "item_id": aid, "by": by, "time": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "story_id": root[0] if root else None, "story_title": root[1] if root else None,
            "quote": (lab or {}).get("quote"), "why": (lab or {}).get("why"),
            "why_zh": why_zh.get(f"{hn_id}:{aid}") if lab else None,
            "text": to_text(tx[1])[:2000] if tx and src != "story_url" else None,
            "points": tx[3] if tx and src == "story_url" else None,
            "stance": (lab or {}).get("stance"), "stance_confidence": (lab or {}).get("confidence"),
            "source": src if src == "story_url" else "comment_link", "model": (lab or {}).get("model"),
        })

    build = PATHS.build
    with open(build / "items.jsonl", "w") as f:
        for it in items_out:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    with open(build / "mentions.jsonl", "w") as f:
        for mm in mentions_out:
            f.write(json.dumps(mm, ensure_ascii=False) + "\n")
    # 只靠 story 提交进入主书架的论文没有"评论原话"：从它的讨论串里挑回复最多的顶层评论补上（不计入统计、不标立场）
    with_quote = {mm["item_id"] for mm in mentions_out if mm["source"] == "comment_link"}
    need = {i["id"] for i in items_out if i["id"] not in with_quote}  # 主书架和候选层都补
    mentions_out.extend(thread_quotes(need, mentions_out))
    n_core = sum(i["tier"] == "core" for i in items_out)
    n_cards = sum(1 for i in items_out if i["card"])
    with_quote = {mm["item_id"] for mm in mentions_out if mm["source"] in ("comment_link", "thread_comment")}
    no_quote = sum(1 for i in items_out if i["tier"] == "core" and i["id"] not in with_quote)
    no_quote_cand = sum(1 for i in items_out if i["tier"] == "cand" and i["id"] not in with_quote)
    (build / "taxonomy.json").exists() or (build / "taxonomy.json").write_text(json.dumps(taxonomy))
    con2 = duckdb.connect()
    hn_end = connect(read_only=True).execute("SELECT data_end FROM meta").fetchone()[0]
    build_meta = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "hn_cutoff": str(hn_end),
        "sources": {"hf_dataset_sha": cfg()["hn"]["hf_revision"], "algolia_delta_from": cfg()["delta"]["overlap_start"]},
        "thresholds": {"paper": {"min_people": TIERS["cand"][0], "min_months": TIERS["cand"][1]},
                       "core": {"min_people": TIERS["core"][0], "min_months": TIERS["core"][1]}},
        "models": {"stance": "claude-haiku-5-5 (v2) + claude-sonnet-5-5 (v3 复核低置信度)；每月增量 haiku v3 + sonnet v3 复核",
                   "cards": "claude-sonnet-5-5",
                   "embedding": "BAAI/bge-small-en-v1.5", "taxonomy": "claude-sonnet-5-5"},
        "counts": {"papers": len(items_out), "papers_core": n_core, "why_zh": sum(1 for mm in mentions_out if mm.get("why_zh")), "papers_cand": len(items_out) - n_core,
                   "mentions": len(mentions_out), "labeled_papers": sum(i["hn"]["labeled"] == i["hn"]["labelable"] > 0 for i in items_out),
                   "cards": n_cards, "core_without_comment_quote": no_quote, "cand_without_comment_quote": no_quote_cand,
                   "openalex": sum(1 for i in items_out if i["metrics"]), "topics": sum(len(a.get("categories", [])) for a in taxonomy["areas"])},
        "tentative": n_cards < n_core, "attribution": "HN data: open-index/hacker-news (ODC-By 1.0) + HN Algolia API",
    }
    (build / "build_meta.json").write_text(json.dumps(build_meta, indent=1, ensure_ascii=False))
    del con2

    # SQLite：先写临时文件再原子替换
    tmp = build / "catalog.db.tmp"
    tmp.unlink(missing_ok=True)
    sq = sqlite3.connect(tmp)
    sq.executescript("""
        CREATE TABLE items (id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, title_zh TEXT, authors TEXT,
            year INTEGER, abstract TEXT, links TEXT, license TEXT, can_redistribute INTEGER, categories TEXT,
            primary_category TEXT, topics TEXT, field TEXT, tier TEXT, people INTEGER, threads INTEGER,
            active_months INTEGER, months_rec INTEGER, months_strong INTEGER, first_mention TEXT, last_mention TEXT,
            by_year TEXT, has_positive INTEGER, labeled INTEGER, labelable INTEGER, score REAL, card TEXT,
            metrics TEXT, thumb TEXT, rank INTEGER, area TEXT, topic TEXT, cited_by INTEGER, oneliner TEXT,
            difficulty INTEGER, shelf_life TEXT, active_12m INTEGER, rec_12m INTEGER);
        CREATE TABLE related (item_id TEXT, related_id TEXT, pos INTEGER, co_people INTEGER, sim REAL, cites INTEGER,
            PRIMARY KEY (item_id, related_id));
        CREATE TABLE areas (id TEXT PRIMARY KEY, name_zh TEXT, name_en TEXT, n INTEGER, pos INTEGER);
        CREATE TABLE topics (id TEXT PRIMARY KEY, area TEXT, name_zh TEXT, name_en TEXT, n INTEGER, n_core INTEGER, pos INTEGER);
        CREATE INDEX items_topic ON items(topic);
        CREATE INDEX items_area ON items(area);
        CREATE TABLE mentions (comment_id INTEGER, item_id TEXT, by TEXT, time TEXT, story_id INTEGER, story_title TEXT,
            quote TEXT, why TEXT, text TEXT, points INTEGER, stance TEXT, stance_confidence REAL, source TEXT, model TEXT,
            why_zh TEXT, PRIMARY KEY (comment_id, item_id));
        CREATE INDEX mentions_item ON mentions(item_id, time);
        CREATE INDEX items_score ON items(score DESC);
        CREATE INDEX items_last ON items(last_mention DESC);
        CREATE TABLE build_meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE paths (item_id TEXT PRIMARY KEY, intro TEXT, steps TEXT, model TEXT, built_at TEXT);
        CREATE VIRTUAL TABLE items_fts USING fts5(id UNINDEXED, title, title_zh, authors, abstract, summary,
            tokenize = 'unicode61 remove_diacritics 2');
    """)
    for rank, it in enumerate(items_out, 1):
        h = it["hn"]
        card = it["card"] or {}
        sq.execute("INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            it["id"], it["kind"], it["title"], it["title_zh"], json.dumps(it["authors"], ensure_ascii=False), it["year"],
            it["abstract"], json.dumps(it["links"]), it["license"], int(it["can_redistribute"]),
            json.dumps(it["categories"]), it["primary_category"], json.dumps(it["topics"]), it["field"], it["tier"],
            h["people"], h["threads"], h["active_months"], h["months_rec"], h["months_strong"], h["first_mention"],
            h["last_mention"], json.dumps(h["by_year"]), int(h["has_positive"]), h["labeled"], h["labelable"],
            it["score"], json.dumps(it["card"], ensure_ascii=False) if it["card"] else None, json.dumps(it["metrics"]),
            it["thumb"], rank, it["area"], (it["topics"] or [None])[0], it["metrics"].get("cited_by"),
            card.get("oneliner_zh"), card.get("difficulty"), card.get("shelf_life"), h["active_12m"], h["rec_12m"]))
        sq.execute("INSERT INTO items_fts VALUES (?,?,?,?,?,?)", (
            it["id"], it["title"], it["title_zh"] or "", " ".join(it["authors"]), it["abstract"] or "",
            " ".join(filter(None, [card.get("summary_zh"), card.get("summary_en"), card.get("why_hn")]))))
    sq.executemany("INSERT OR IGNORE INTO mentions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (m["comment_id"], m["item_id"], m["by"], m["time"], m["story_id"], m["story_title"], m["quote"], m["why"],
         m["text"], m["points"], m["stance"], m["stance_confidence"], m["source"], m["model"], m.get("why_zh")) for m in mentions_out])
    sq.executemany("INSERT OR IGNORE INTO related VALUES (?,?,?,?,?,?)", [
        (a, r["id"], pos, r["co_people"], r["sim"], int(r.get("cites", False)))
        for a, rs in related.items() if a in stats for pos, r in enumerate(rs)])
    # 学习路径（Phase 3，hs.steps.study paths-merge 写的 data/build/paths.jsonl）：只收两头都在书架上的
    paths = llm_batch.read_jsonl(build / "paths.jsonl")
    sq.executemany("INSERT OR REPLACE INTO paths VALUES (?,?,?,?,?)", [
        (r["item_id"], r.get("intro"), json.dumps([st for st in r["steps"] if st["id"] in stats], ensure_ascii=False), r.get("model"), r.get("built_at"))
        for r in paths if r["item_id"] in stats])
    core_ids = {i["id"] for i in items_out if i["tier"] == "core"}
    n_core_topic = Counter((topics[a]["topic"]) for a in core_ids if a in topics)
    for ai, a in enumerate(taxonomy["areas"]):
        sq.execute("INSERT INTO areas VALUES (?,?,?,?,?)", (a["id"], a["name_zh"], a.get("name_en"), a.get("count"), ai))
        for ci, c in enumerate(a.get("categories", [])):
            sq.execute("INSERT INTO topics VALUES (?,?,?,?,?,?,?)",
                       (c["id"], a["id"], c["name_zh"], c.get("name_en"), c.get("count"), n_core_topic.get(c["id"], 0), ci))
    sq.executemany("INSERT INTO build_meta VALUES (?,?)", [(k, json.dumps(v, ensure_ascii=False)) for k, v in build_meta.items()])
    sq.commit()
    sq.close()
    tmp.replace(build / "catalog.db")

    # 前端即时搜索索引：字段短、体积小
    idx = [{"id": it["id"], "t": it["title"], "z": it["title_zh"] or "", "a": ", ".join(it["authors"][:4]),
            "y": it["year"], "f": it["field"], "s": it["score"], "p": it["hn"]["people"],
            "c": 1 if it["tier"] == "core" else 0, "o": (it["card"] or {}).get("oneliner_zh") or "",
            "r": it["area"] or "", "h": 1 if it["tier"] == "core" and it["hn"]["has_positive"] else 0,  # 封面底色、"被推荐/被提及"
            # 关键词只放分类和前置知识（中文摘要太长，索引会翻倍；一行摘要已在 "o" 里）
            "k": " ".join(filter(None, [" ".join(it["categories"]), " ".join((it["card"] or {}).get("prerequisites") or [])]))}
           for it in items_out]
    (build / "search-index.json").write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")))
    print(f"catalog: {len(items_out):,} papers, {len(mentions_out):,} mentions, cards={build_meta['counts']['cards']}, "
          f"labeled_papers={build_meta['counts']['labeled_papers']} → {build / 'catalog.db'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("extract")
    sub.add_parser("tiers")
    s = sub.add_parser("meta")
    s.add_argument("--full", action="store_true", help="全部重查（默认只查新进的）")
    sub.add_parser("openalex")
    s = sub.add_parser("openalex-search")
    s.add_argument("--tier", default="core", choices=["core", "all"])
    s.add_argument("--reserve", type=float, default=0.03, help="剩余额度（美元）低于这个数就停")
    s.add_argument("--wait-reset", action="store_true", help="额度用完后等到重置再继续（分天跑）")
    s = sub.add_parser("stance-sample")
    s.add_argument("--n", type=int, default=200)
    s.add_argument("--seed", type=int, default=7)
    s = sub.add_parser("stance-prepare")
    s.add_argument("--tier", default="core", choices=list(TIERS))
    s.add_argument("--batch", type=int, default=100)
    s.add_argument("--max-chars", type=int, default=60000, help="每批 Markdown 最多这么多字符")
    s = sub.add_parser("stance-agree")
    s.add_argument("--suffix", default="", help="例如 _v2")
    sub.add_parser("stance-sample-v2")
    sub.add_parser("stance-fix")
    sub.add_parser("stance-sample-v3")
    s = sub.add_parser("stance-review-sheet")
    s.add_argument("--n", type=int, default=50)
    s.add_argument("--seed", type=int, default=11)
    sub.add_parser("stance-review-score")
    s = sub.add_parser("stance-review-prepare")
    s.add_argument("--min-conf", type=float, default=0.6)
    s = sub.add_parser("cards-prepare")
    s.add_argument("--n", type=int, default=30)
    s.add_argument("--all-core", action="store_true", help="核心集全部论文")
    s.add_argument("--task", default="cards_sample")
    s.add_argument("--prompt", default="v2", choices=["v1", "v2"])
    s.add_argument("--batch", type=int, default=10)
    s.add_argument("--max-chars", type=int, default=50000)
    s = sub.add_parser("why-zh-prepare")
    s.add_argument("--task", default="why_zh_sample")
    s.add_argument("--sample", type=int, default=0)
    s.add_argument("--seed", type=int, default=13)
    s.add_argument("--exclude-sample", action="store_true", help="全量时跳过样本里已经写过的")
    s.add_argument("--batch", type=int, default=100)
    # 月度更新（D47）的增量任务；--tag 一般是开始这次更新的日期，例如 20261104
    s = sub.add_parser("stance-inc-prepare")
    s.add_argument("--tag", required=True)
    s.add_argument("--batch", type=int, default=100)
    s.add_argument("--max-chars", type=int, default=60000)
    s = sub.add_parser("stance-inc-review-prepare")
    s.add_argument("--tag", required=True)
    s.add_argument("--min-conf", type=float, default=0.6)
    s = sub.add_parser("cards-inc-prepare")
    s.add_argument("--tag", required=True)
    s.add_argument("--batch", type=int, default=10)
    s.add_argument("--max-chars", type=int, default=50000)
    s = sub.add_parser("why-zh-inc-prepare")
    s.add_argument("--tag", required=True)
    s.add_argument("--batch", type=int, default=100)
    sub.add_parser("catalog")
    args = ap.parse_args(argv)
    {"extract": cmd_extract, "tiers": cmd_tiers, "meta": cmd_meta, "openalex": cmd_openalex, "openalex-search": cmd_openalex_search, "stance-sample": cmd_stance_sample,
     "stance-prepare": cmd_stance_prepare, "stance-agree": cmd_stance_agree, "stance-sample-v2": cmd_stance_sample_v2, "stance-fix": cmd_stance_fix, "cards-prepare": cmd_cards_prepare,
     "stance-sample-v3": cmd_stance_sample_v3, "stance-review-prepare": cmd_stance_review_prepare,
     "stance-review-sheet": cmd_stance_review_sheet, "stance-review-score": cmd_stance_review_score,
     "why-zh-prepare": cmd_why_zh_prepare, "catalog": cmd_catalog,
     "stance-inc-prepare": cmd_stance_inc_prepare, "stance-inc-review-prepare": cmd_stance_inc_review_prepare,
     "cards-inc-prepare": cmd_cards_inc_prepare, "why-zh-inc-prepare": cmd_why_zh_inc_prepare}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
