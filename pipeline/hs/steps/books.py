"""Phase 5 开源书（D48）：候选名单 → HN 信号 → 立场标注 → 算分 → 卡片 → 公开站的图书数据。

子命令：
  seed     free-programming-books（CC BY 4.0，固定到一个提交）的英文书单 + 手选名单（pipeline/books_extra.toml）
           → data/build/books/seed.jsonl：一本书一行，合并同书的不同格式（PDF、HTML），记官方链接和许可证
  signal   按官方链接匹配 HN 的 links 表（story 提交 + 评论里的链接；宽口径，不过 ≥100 字过滤）
           → data/build/books/signal.jsonl，打印过 3/3、2/2 的本数和前几十本
  kind-prepare / kind-merge
           过 2/2 的条目交给 Sonnet 子 agent 分成 book / docs / tutorial / essay / other（data/llm/book_kind/），
           再写回 signal.jsonl，按类别重新数
  sample-prepare / sample-agree
           主书架的书的评论提及里抽 200 条，Haiku 和 Sonnet 各标一遍立场和“是不是在说这本书”，
           再算一致率，分歧写进 reports/phase5/sample_review.md

匹配规则（url_prefixes）：链接去掉协议、www、查询串、结尾斜杠后，等于前缀或以“前缀/”开头。
  - 指向 .html / .xhtml / index 的，取所在目录（整本书的网页版）；指向 .pdf / .epub 的只认这个文件。
  - github.com、archive.org、leanpub.com 这类公共站点，前缀至少要有两段路径（github.com/用户/仓库）。
  - 大学站点（.edu、.ac.uk）和 paulgraham.com 这类还有很多别的内容的网站，前缀至少要有一段路径，不会只剩域名。
  label-prepare / label-inc
           全量立场标注（Sonnet + v3）；补了官方链接以后多出来的提及补标（book_stance_inc_<日期>）
  score    重新数人和月份、算分、挑详情页显示的原话 → scored.jsonl、kept_mentions.jsonl
  cards-prepare / why-zh-prepare
           上架的书写卡片（中文导读、读法）；HN 原话下面的中文说明（--sample 先试跑）
  export   公开站的图书数据 → shelf.json；report 上书架清单 → reports/phase5/shelf.md
用法：uv run python -m hs.steps.books <子命令>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

import duckdb

from hs.config import PATHS, PIPELINE_DIR
from hs.steps.build_db import connect

FPB_SHA = "b4c4cc4040b614d2aca81ad5f2bcd92ed3d422ec"  # EbookFoundation/free-programming-books，2026-11-04 取
FPB_DIR = PATHS.raw / "books" / "fpb" / FPB_SHA
FPB_FILES = ["free-programming-books-subjects.md", "free-programming-books-langs.md"]
EXTRA = PIPELINE_DIR / "books_extra.toml"
OUT = PATHS.build / "books"
SKIP_SECTIONS = re.compile(r"meta-lists|^index$", re.I)
GENERIC_HOSTS = {"github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "archive.org", "web.archive.org", "leanpub.com",
                 "gitbook.com", "drive.google.com", "docs.google.com", "sites.google.com", "dropbox.com", "scribd.com",
                 "sourceforge.net", "medium.com", "amazon.com", "youtube.com", "gist.github.com", "raw.githubusercontent.com",
                 "bookdown.org", "notion.site", "lulu.com", "academia.edu", "researchgate.net", "arxiv.org", "zenodo.org",
                 "freecodecamp.org", "infoq.com", "oreilly.com", "springer.com", "link.springer.com", "microsoft.com",
                 "ibm.com", "cs.cmu.edu", "people.csail.mit.edu"}
LICENSE_RE = re.compile(r"\((CC[\s‑-]?[A-Z0-9.\s‑-]*|GFDL[^)]*|MIT[^)]*|Apache[^)]*|Public Domain[^)]*|CC0[^)]*)\)", re.I)
ENTRY_RE = re.compile(r"^\s*[*-]\s+\[(?P<title>[^\]]+)\]\((?P<url>https?://[^)\s]+)\)(?P<rest>.*)$")
# 只有“目录页”才代表整本书的网页版（取所在目录）；chapter1.html、emacs.html 这类只认这一页，免得同一个目录下的几本书互相算进去
INDEX_PAGE = re.compile(r"^(index|contents?|toc|table-of-contents|start)(\.(html?|xhtml|php))?$", re.I)
# 标题像官方文档、手册、规范、教程站，不像一本书（D48 只收书；先标出来，报告里分开数）
DOC_LIKE = re.compile(r"\b(documentation|docs|manuals?|reference|handbook|style ?guides?|guidelines|tutorials?|specifications?|"
                      r"getting started|quick ?start|cheat ?sheets?|api|wiki|faq|official|user guide|guides)\b", re.I)
DOC_HOST = re.compile(r"^(docs?|developer|developers|learn|devdocs|api|wiki|man7)\.|readthedocs\.io$|readthedocs\.org$")


# 靠查询串区分资源的页面（details.aspx?id=…、view.php?id=…）：前缀要带上查询串，不然会匹配到整个站点的所有下载页
QUERY_PAGE = re.compile(r"\.(aspx?|php|cgi|jsp|pl)$|^(details|view|show|download|item)$", re.I)


def norm_url(u: str, keep_query: bool = False) -> str:
    """去掉协议、www、锚点、结尾斜杠（keep_query=False 时也去掉查询串），全部小写。#!/a、#/a 这种前端路由当成路径 /a。"""
    u = re.sub(r"/?#!?/", "/", u.strip())
    try:
        s = urlsplit(u if "://" in u else "http://" + u)
        s.hostname  # 评论里会有坏掉的链接（比如 http://[ 开头），解析不了的不可能是书的链接
    except ValueError:
        return re.sub(r"^[a-z]+://", "", u.lower()).rstrip("/")
    host = (s.hostname or "").lower().removeprefix("www.")
    path = s.path.rstrip("/").lower()
    q = f"?{s.query.lower()}" if keep_query and s.query else ""
    return f"{host}{path}{q}"


# 只有域名不算一本书的链接：网站上还有很多别的东西（paulgraham.com 的文章、大学主页）
MULTI_HOSTS = {"paulgraham.com", "catb.org", "greenteapress.com", "mitpress.mit.edu", "developer.mozilla.org",
               "docs.python.org", "wikibooks.org", "en.wikibooks.org", "learn.microsoft.com", "docs.microsoft.com"}


def min_segments(host: str) -> int:
    if host in GENERIC_HOSTS:
        return 2
    if host in MULTI_HOSTS or host.endswith((".edu", ".ac.uk", ".edu.au", ".ac.jp")):
        return 1
    return 0


def url_prefixes(u: str) -> list[str]:
    n = norm_url(u)
    host, _, path = n.partition("/")
    segs = [s for s in path.split("/") if s]
    min_segs = min_segments(host)
    if segs and QUERY_PAGE.search(segs[-1]) and urlsplit(u.strip()).query:
        return [norm_url(u, keep_query=True)]  # 只认这一个带查询串的链接（匹配时整串相等）
    out = [n]
    if segs and INDEX_PAGE.match(segs[-1]):
        d = segs[:-1]
        if len(d) >= min_segs:
            out.append("/".join([host, *d]))
    return [p for p in dict.fromkeys(out) if len(p.split("/")) - 1 >= min_segs]


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60] or "book"


def norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t.lower())).strip()


def parse_fpb(path: Path) -> list[dict]:
    out, section, sub = [], "", ""
    for line in path.read_text().split("\n"):
        if line.startswith("### "):
            section, sub = line[4:].strip(), ""
            continue
        if line.startswith("#### "):
            sub = line[5:].strip()
            continue
        m = ENTRY_RE.match(line)
        if not m or not section or SKIP_SECTIONS.search(section):
            continue
        rest = m["rest"].strip()
        authors = ""
        if rest.startswith("- "):
            authors = re.split(r"\s\(|\s-\s", rest[2:], maxsplit=1)[0].strip()
        lic = LICENSE_RE.search(rest)
        out.append({"title": m["title"].strip(), "url": m["url"], "authors": authors,
                    "license": re.sub(r"[\s‑-]+", " ", lic.group(1)).strip().upper().replace("CC ", "CC-").replace(" ", "-") if lic else None,
                    "section": section, "subsection": sub, "file": path.name, "notes": rest})
    return out


def merge(entries: list[dict], source: str) -> dict[tuple, dict]:
    """同一本书的不同格式合成一条：标题相同，并且第一作者相同或者有一个没写作者（书单里同一本书有时一条写了作者、一条没写）。"""
    books: dict[tuple, dict] = {}
    for e in entries:
        first = norm_title(e["authors"].split(",")[0]) if e["authors"] else ""
        t = norm_title(e["title"])
        key = (t, first)
        if key not in books:
            same = [k for k in books if k[0] == t and (not k[1] or not first)]
            key = same[0] if same else key
        b = books.setdefault(key, {"title": e["title"], "authors": e["authors"], "urls": [], "license": None,
                                   "sections": [], "source": source, "aliases": e.get("aliases", [])})
        if e["url"] not in b["urls"]:
            b["urls"].append(e["url"])
        b["license"] = b["license"] or e.get("license")
        sec = " / ".join(filter(None, [e.get("section"), e.get("subsection")]))
        if sec and sec not in b["sections"]:
            b["sections"].append(sec)
    return books


def fetch_fpb() -> None:
    """书单固定在 FPB_SHA。本地没有就从 GitHub 下（走统一的 HTTP 客户端和磁盘缓存），放进 data/raw/books/fpb/<提交>/。"""
    missing = [f for f in FPB_FILES if not (FPB_DIR / f).exists()]
    if not missing:
        return
    from hs.http import Http

    http = Http()
    FPB_DIR.mkdir(parents=True, exist_ok=True)
    for f in missing:
        r = http.get(f"https://raw.githubusercontent.com/EbookFoundation/free-programming-books/{FPB_SHA}/books/{f}")
        r.raise_for_status()
        (FPB_DIR / f).write_bytes(r.content)
        print(f"  下载 {f}（{len(r.content) / 1024:.0f} KB）")


def cmd_seed(_args) -> None:
    fetch_fpb()
    fpb = [e for f in FPB_FILES for e in parse_fpb(FPB_DIR / f)]
    books = merge(fpb, "fpb")
    extra = tomllib.loads(EXTRA.read_text()).get("book", []) if EXTRA.exists() else []
    n_extra_new = 0
    for e in extra:
        first = norm_title(e.get("authors", "").split(",")[0]) if e.get("authors") else ""
        key = (norm_title(e["title"]), first)
        hit = books.get(key) or next((b for k, b in books.items() if k[0] == key[0]), None)
        if hit:  # 书单里已经有：补链接、许可证、别名
            hit["urls"] += [u for u in e.get("urls", []) if u not in hit["urls"]]
            hit["license"] = e.get("license") or hit["license"]
            hit["aliases"] = sorted(set(hit["aliases"]) | set(e.get("aliases", [])))
            hit["source"] = "fpb+extra"
        else:
            n_extra_new += 1
            books[key] = {"title": e["title"], "authors": e.get("authors", ""), "urls": list(e.get("urls", [])),
                          "license": e.get("license"), "sections": [e.get("section", "")], "source": "extra",
                          "aliases": e.get("aliases", [])}
    ids: set[str] = set()
    rows = []
    for b in books.values():
        bid = slug(b["title"])
        if bid in ids:
            bid = f"{bid}-{slug(b['authors'].split(',')[0].split()[-1]) if b['authors'].strip() else len(ids)}"
        while bid in ids:
            bid += "-2"
        ids.add(bid)
        prefixes = sorted({p for u in b["urls"] for p in url_prefixes(u)})
        doc_like = bool(DOC_LIKE.search(b["title"])) or any(DOC_HOST.search(p.split("/")[0]) for p in prefixes)
        rows.append({"id": f"book:{bid}", **b, "prefixes": prefixes, "doc_like": doc_like})
    rows, n_dup = dedupe_by_links(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "seed.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    lic = sum(1 for r in rows if r["license"])
    print(f"seed: 书单 {len(fpb):,} 条 → {len(books) - n_extra_new:,} 本；手选名单 {len(extra)} 本（书单里没有的 {n_extra_new}）；"
          f"链接重复、并掉 {n_dup} 条；共 {len(rows):,} 本，书单标了开放许可的 {lic}，"
          f"前缀 {sum(len(r['prefixes']) for r in rows):,} 个 → {OUT / 'seed.jsonl'}")


def dedupe_by_links(rows: list[dict]) -> tuple[list[dict], int]:
    """书单把同一本书列了两次（改过书名、不同版次、副标题不同）：一条的链接前缀全在另一条里，就并进那一条，书名留作别名。"""
    rows = sorted(rows, key=lambda r: (-len(r["prefixes"]), r["source"] == "fpb", len(r["title"])))
    kept: list[dict] = []
    by_prefix: dict[str, list[dict]] = defaultdict(list)
    n = 0
    for r in rows:
        mine = set(r["prefixes"])
        host = next((k for k in by_prefix.get(r["prefixes"][0], []) if mine <= set(k["prefixes"])), None) if mine else None
        if host:
            n += 1
            host["urls"] += [u for u in r["urls"] if u not in host["urls"]]
            host["aliases"] = sorted(set(host["aliases"]) | {r["title"]} | set(r["aliases"]))
            host["license"] = host["license"] or r["license"]
            host["sections"] += [s for s in r["sections"] if s not in host["sections"]]
            host.setdefault("merged", []).append(r["id"])
            continue
        kept.append(r)
        for p in r["prefixes"]:
            by_prefix[p].append(r)
    return kept, n


def cmd_signal(args) -> None:
    rows = [json.loads(x) for x in (OUT / "seed.jsonl").read_text().split("\n") if x.strip()]
    pref = [(r["id"], p, p.split("/")[0]) for r in rows for p in r["prefixes"]]
    con = connect(read_only=True)
    con.execute("CREATE TEMP TABLE pref (book VARCHAR, p VARCHAR, host VARCHAR)")
    con.executemany("INSERT INTO pref VALUES (?, ?, ?)", pref)
    # 规范化和 norm_url 一致。一个链接同时落在几本书的前缀里时，只算最长（最具体）的那个前缀；一样长的几本书各算一次，记成 shared。
    # 同一条 HN 条目里同一本书的多个链接只算一次。
    hits = con.execute(r"""
        WITH l0 AS (
            SELECT id, "by", time, src, host,
                   regexp_replace(lower(regexp_replace(regexp_replace(regexp_replace(link, '^[A-Za-z]+://', ''),
                         '/?#!?/', '/'), '#.*$', '')), '^www\.', '') AS nq
            FROM links WHERE "by" IS NOT NULL AND host IN (SELECT DISTINCT host FROM pref)),
        l AS (SELECT *, rtrim(regexp_replace(nq, '\?.*$', ''), '/') AS n FROM l0),
        m AS (SELECT pref.book, l.id, l."by", l.time, l.src, l.n, length(pref.p) AS plen
              FROM l JOIN pref ON l.host = pref.host AND
                   CASE WHEN contains(pref.p, '?') THEN l.nq = pref.p
                        ELSE l.n = pref.p OR starts_with(l.n, pref.p || '/') END),
        best AS (SELECT * FROM m QUALIFY plen = max(plen) OVER (PARTITION BY id, n)),
        tie AS (SELECT id, n, count(DISTINCT book) AS nb FROM best GROUP BY id, n)
        SELECT DISTINCT best.book, best.id, best."by", best.time, best.src, tie.nb > 1 AS shared
        FROM best JOIN tie USING (id, n)""").fetchall()
    con.close()
    with open(OUT / "link_mentions.jsonl", "w") as f:  # 每条匹配一行，抽样和以后的标注从这里取
        for book, hid, by, t, src, shared in hits:
            f.write(json.dumps({"book": book, "hn_id": hid, "by": by, "time": t.isoformat(), "src": src, "shared": bool(shared)}) + "\n")
    st: dict[str, dict] = defaultdict(lambda: {"ids": set(), "people": set(), "months": set(), "stories": 0, "last12": 0,
                                               "first": None, "shared": 0})
    last = max(h[3] for h in hits)
    cut = last.replace(year=last.year - 1)
    for book, hid, by, t, src, shared in hits:
        s = st[book]
        if hid in s["ids"]:
            continue
        s["shared"] += bool(shared)
        s["ids"].add(hid)
        s["people"].add(by)
        s["months"].add(t.strftime("%Y-%m"))
        s["stories"] += src == "story_url"
        s["last12"] += t > cut
        s["first"] = t if s["first"] is None or t < s["first"] else s["first"]
    out = []
    for r in rows:
        s = st.get(r["id"])
        n_people, n_months = (len(s["people"]), len(s["months"])) if s else (0, 0)
        out.append({"id": r["id"], "title": r["title"], "authors": r["authors"], "license": r["license"], "source": r["source"],
                    "doc_like": r.get("doc_like", False), "sections": r["sections"],
                    "mentions": len(s["ids"]) if s else 0, "stories": s["stories"] if s else 0, "shared": s["shared"] if s else 0,
                    "people": n_people, "months": n_months, "last12": s["last12"] if s else 0,
                    "first_year": s["first"].year if s else None, "core": n_people >= 3 and n_months >= 3,
                    "cand": n_people >= 2 and n_months >= 2})
    out.sort(key=lambda x: (-x["people"], -x["months"]))
    with open(OUT / "signal.jsonl", "w") as f:
        for x in out:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    def part(xs: list[dict]) -> dict:
        core = [x for x in xs if x["core"]]
        return {"n": len(xs), "with_links": sum(1 for x in xs if x["mentions"]), "core_3_3": len(core),
                "cand_2_2": sum(x["cand"] for x in xs), "core_open_license": sum(1 for x in core if x["license"]),
                "link_mentions_core": sum(x["mentions"] for x in core)}

    books = [x for x in out if not x["doc_like"]]
    summary = {"data_end": str(last), "all": part(out), "books": part(books), "doc_like": part([x for x in out if x["doc_like"]])}
    (OUT / "signal_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print("signal:", json.dumps(summary, ensure_ascii=False))
    print(f"\n像书的（不含文档、手册、规范）前 {args.top} 本：")
    print("书 | 许可 | 提及 | 人 | 月 | 近 12 个月 | 最早 | 和别的书共用链接")
    for x in books[: args.top]:
        print(f"{x['title'][:60]} | {x['license'] or '—'} | {x['mentions']} | {x['people']} | {x['months']} | {x['last12']} | "
              f"{x['first_year']} | {x['shared'] or ''}")


KIND_TASK = "book_kind"
KINDS = ("book", "docs", "tutorial", "essay", "other")
KIND_PROMPT = """# 任务：判断书单里每一条是不是“一本书”

输入是开源/免费编程书单（free-programming-books）和我们手选名单里的条目，每条 `{"id", "title", "authors", "sections", "urls", "license"}`：
- `sections`：它在书单里的分类；`urls`：官方免费版的链接；`license`：书单标注的开放许可（可能为空）。

我们要做一个“开源书书架”，只收完整的书（有章节结构、能从头读到尾），不收文档站、教程网站和单篇文章。
对每一条判断 `kind`，五选一：
- `book`：一本完整的书。包括官方免费在线版、开放许可的书、书形式的长篇指南，例如 Pro Git、Crafting Interpreters、Learn You a Haskell、Beej's Guide to Network Programming、The Rust Programming Language。同一本书的不同版次也算 book。
- `docs`：官方文档、手册、参考手册、语言规范、风格指南、API 文档、项目或公司的 handbook，例如 Python 官方文档、GNU Emacs Manual、Google Style Guides、Rails Guides。
- `tutorial`：教程网站、示例集、课程讲义、练习集、速查表，例如 Go by Example、Ruby Koans、Elixir School、某门课的 lecture notes。
- `essay`：单篇长文、论文、学位论文、演讲稿，例如 Magic Ink、What Every Programmer Should Know About Memory、Joe Armstrong 的博士论文。
- `other`：博客、杂志、资源合集、视频、工具，或者看不出是什么。

根据标题、作者、链接和你对它的了解来判断。拿不准时写最可能的那个，confidence 如实反映把握。

每行输出一个 JSON（顺序与输入一致，每个 id 都要有一行）：
```
{"id": <同输入>, "kind": "...", "confidence": 0.0-1.0, "note": "不超过 20 个汉字，说明为什么；book 可以留空"}
```
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
"""


def cmd_kind_prepare(_args) -> None:
    """过 2/2 的条目交给 Sonnet 子 agent 分成 book / docs / tutorial / essay / other（规则只能粗分，书单里混着文档站和博客）。"""
    from hs import llm_batch
    from hs.steps.papers import SONNET

    seed = {r["id"]: r for r in (json.loads(x) for x in (OUT / "seed.jsonl").read_text().split("\n") if x.strip())}
    sig = [json.loads(x) for x in (OUT / "signal.jsonl").read_text().split("\n") if x.strip()]
    items = [{"id": x["id"], "title": x["title"], "authors": x["authors"], "sections": "; ".join(x["sections"]),
              "urls": " ".join(seed[x["id"]]["urls"][:3]), "license": x["license"] or ""} for x in sig if x["cand"]]
    paths = llm_batch.prepare(KIND_TASK, items, KIND_PROMPT, batch_size=100, max_chars=40000,
                              out_fields=["kind", "confidence", "note"], overwrite=True, model=SONNET)
    print(f"kind-prepare: {len(items)} 条（过 2/2）→ {llm_batch.task_dir(KIND_TASK)}（{len(paths)} 批，Sonnet）")


def cmd_kind_merge(args) -> None:
    """把分类写回 signal.jsonl，按类别重新数过 3/3、2/2 的本数，列出像书的前几十本。"""
    from hs import llm_batch

    valid = set(llm_batch.inputs(KIND_TASK))
    kinds = {k: v for k, v in llm_batch.outputs(KIND_TASK).items() if k in valid and v.get("kind") in KINDS}
    missing = len(valid) - len(kinds)
    sig = [json.loads(x) for x in (OUT / "signal.jsonl").read_text().split("\n") if x.strip()]
    for x in sig:
        k = kinds.get(x["id"])
        x["kind"], x["kind_conf"], x["kind_note"] = (k["kind"], k.get("confidence"), k.get("note")) if k else (None, None, None)
    with open(OUT / "signal.jsonl", "w") as f:
        for x in sig:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    summary = json.loads((OUT / "signal_summary.json").read_text())
    by = {}
    for kd in KINDS:
        xs = [x for x in sig if x["kind"] == kd]
        by[kd] = {"cand_2_2": len(xs), "core_3_3": sum(x["core"] for x in xs),
                  "core_open_license": sum(1 for x in xs if x["core"] and x["license"]),
                  "link_mentions_core": sum(x["mentions"] for x in xs if x["core"])}
    summary["by_kind"] = by
    summary["kind_missing"] = missing
    (OUT / "signal_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print("kind-merge:", json.dumps(by, ensure_ascii=False), f"没分类的 {missing} 条")
    books = [x for x in sig if x["kind"] == "book"]
    print(f"\n模型判为 book 的前 {args.top} 本：")
    print("书 | 许可 | 提及 | 人 | 月 | 近 12 个月 | 共用链接")
    for x in books[: args.top]:
        print(f"{x['title'][:60]} | {x['license'] or '—'} | {x['mentions']} | {x['people']} | {x['months']} | {x['last12']} | {x['shared'] or ''}")


# ---------------------------------------------------------------- 200 条样本：立场 + 是不是在说这本书（D48，PLAN Phase 5）
BOOK_STANCE_PROMPT = """# 任务：判断 HN 评论对它链接的那本书是什么立场

输入是 JSONL 的 Markdown 视图，每条“评论 × 书”：
`{"id", "book_title", "book_authors", "story_title", "parent_snippet", "text"}`
- `book_title`、`book_authors`：评论链接的那本书（开放许可或官方免费在线的书）。
- `story_title`：评论所在 HN 讨论串的标题；`parent_snippet`：它回复的那条评论的开头（可能为空）。只用来理解语境。
- `text`：评论全文。指向这本书（整本书或其中某一章、某一页）的链接写成 `[BOOK]`，其他链接写成 `[LINK]`。

先判断 `about_book`：评论里的 [BOOK] 是不是指这本书本身或它的某一章。链接只是碰巧在同一个网站、实际指的是别的东西（作者的博客文章、同站的其他项目、勘误页、讨论区），就是 false。

再判断评论者对**这本书本身**的态度。按下面的顺序判断，第一条符合的就是答案：
1. `joke`：书本身被拿来当笑点、梗或讽刺对象。
2. `critical`：批评这本书本身，比如内容过时、讲错了、写得不好、不适合入门。以下都**不是** critical：反驳别的评论者、批评书里讲的技术或语言、说“书很好但不适合你现在的需要”。
3. `strong_rec`：热情推荐，有明确的强烈措辞：best book on X、must-read、changed how I think、I can't recommend it enough、强烈推荐等。
4. `rec`：认为这本书值得读，满足任意一条：
   - 建议别人去读这本书或其中某一章：“check out” “I recommend” “start with [BOOK]” “you'd enjoy” “read chapter 3 of [BOOK]”。
   - 对书给出正面评价，或说自己读了有收获：“great book” “explains X really well” “the best free resource” “I learned X from it”。
5. `reference`：其余情况。包括只把书或某一章当出处、证据（“[BOOK] covers how X works” 后面没有让人去读的意思）、回答“有没有资料”时贴链接但不评价、“there's a free book on this”、介绍书的内容但不表态。

rec 和 reference 的分界：评论者是在**建议对方去读它**（rec），还是**拿它支撑自己的说法**（reference）。
拿不准时：rec 和 reference 之间选 reference；strong_rec 和 rec 之间选 rec；critical 和 reference 之间选 reference。about_book 为 false 时，stance 写 reference。

每行输出一个 JSON（顺序与输入一致，每个 id 都要有一行）：
```
{"id": <同输入>, "about_book": true, "stance": "...", "confidence": 0.0-1.0, "quote": "评论里最能说明立场的一句原话，逐字摘录，不超过 300 字符", "why": "不超过 15 个英文词：按这条评论，读者能从这本书里得到什么（joke 和 critical 可以留空）"}
```
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
"""
# v2（2026-11-04 夜，样本 v1 的 29 条分歧之后）：讲清楚强推荐的措辞、“给对方指路”算 rec、回答求书算 rec、引用出处算 reference
BOOK_STANCE_PROMPT_V2 = BOOK_STANCE_PROMPT.replace("（v1）", "").replace(
    """3. `strong_rec`：热情推荐，有明确的强烈措辞：best book on X、must-read、changed how I think、I can't recommend it enough、强烈推荐等。
4. `rec`：认为这本书值得读，满足任意一条：
   - 建议别人去读这本书或其中某一章：“check out” “I recommend” “start with [BOOK]” “you'd enjoy” “read chapter 3 of [BOOK]”。
   - 对书给出正面评价，或说自己读了有收获：“great book” “explains X really well” “the best free resource” “I learned X from it”。
5. `reference`：其余情况。包括只把书或某一章当出处、证据（“[BOOK] covers how X works” 后面没有让人去读的意思）、回答“有没有资料”时贴链接但不评价、“there's a free book on this”、介绍书的内容但不表态。

rec 和 reference 的分界：评论者是在**建议对方去读它**（rec），还是**拿它支撑自己的说法**（reference）。""",
    """3. `strong_rec`：热情、强烈的推荐，有明确的强烈措辞：highly recommend、strongly recommend、can't recommend it enough、must-read、the best book on X、my favorite book、changed how I think / my career、强烈推荐。
   只说 great、excellent、good、nice、really helpful 的，算 rec，不算 strong_rec。
4. `rec`：评论者认为这本书值得读，满足任意一条：
   - 让对方去读它、从里面学东西：“check out [BOOK]” “start with [BOOK]” “See [BOOK] for how to do X” “read chapter 3 of [BOOK]” “you'd enjoy [BOOK]”。
   - 有人问“有什么书或资料可以看”，回答里给出了它。
   - 对书给出正面评价，或说自己读了有收获：“great book” “does an excellent job explaining X” “I learned X from it” “I keep coming back to it”。对作者说“写得很好”也算。
5. `reference`：其余情况。包括：
   - 拿书或某一章当事实出处、证据，支撑自己的论点（“as [BOOK] says, …” “according to chapter 5 of [BOOK]”），没有让人去读的意思。
   - 讨论书里的某个细节、提问、指出书里的小错误，但没有评价这本书。
   - “there's a free book on this”、只介绍书的内容、只贴链接不说话。

rec 和 reference 的分界：评论者是在**让对方去读它、学会某样东西**（rec），还是**引用它支撑自己的说法**（reference）。“See [BOOK] for X” 这种给对方指路的算 rec。""")
assert "my favorite book" in BOOK_STANCE_PROMPT_V2 and "See [BOOK] for X" in BOOK_STANCE_PROMPT_V2
# v3（2026-11-05 我看过样本 v2 的分歧后定的，全量用这一版）：多给评论者的 HN 用户名；作者本人贴自己的书一律 reference；
# 叫人去读、去学算 rec，拿某一节当出处或证据算 reference，两条写到最前面
BOOK_STANCE_PROMPT_V3 = BOOK_STANCE_PROMPT_V2.replace(
    '`{"id", "book_title", "book_authors", "story_title", "parent_snippet", "text"}`',
    '`{"id", "book_title", "book_authors", "commenter", "story_title", "parent_snippet", "text"}`').replace(
    "- `story_title`：评论所在 HN 讨论串的标题；",
    "- `commenter`：评论者的 HN 用户名。\n- `story_title`：评论所在 HN 讨论串的标题；").replace(
    "再判断评论者对**这本书本身**的态度。按下面的顺序判断，第一条符合的就是答案：\n",
    """再判断评论者对**这本书本身**的态度。先看两条总规则：
- 叫人去读、去学（整本或其中某一节都算）→ rec；拿某一节当出处或证据，支撑自己的说法 → reference。
- 评论者就是这本书的作者，在贴自己的书（自称 I wrote / my book / author here，或者用户名明显是作者）→ 一律 reference，不管措辞多热情。author_self 写 true。

然后按下面的顺序判断，第一条符合的就是答案：
""").replace(
    '{"id": <同输入>, "about_book": true, "stance": "...",',
    '{"id": <同输入>, "about_book": true, "author_self": false, "stance": "...",')
assert "author_self" in BOOK_STANCE_PROMPT_V3 and "`commenter`" in BOOK_STANCE_PROMPT_V3 and "叫人去读、去学" in BOOK_STANCE_PROMPT_V3
SAMPLE_TASKS = ("book_stance_sample_haiku", "book_stance_sample_sonnet")
PROMPTS = {"": BOOK_STANCE_PROMPT, "_v2": BOOK_STANCE_PROMPT_V2, "_v3": BOOK_STANCE_PROMPT_V3}
LABEL_TASK = "book_stance_core"
STANCE_OUT = ["about_book", "author_self", "stance", "confidence", "quote", "why"]
_URL_IN_TEXT = re.compile(r"https?://\S+")


def link_matches(url: str, prefixes: list[str]) -> bool:
    n, nq = norm_url(url), norm_url(url, keep_query=True)
    return any(nq == p if "?" in p else (n == p or n.startswith(p + "/")) for p in prefixes)


def mask_book_links(text: str, prefixes: list[str]) -> str:
    def rep(m: re.Match) -> str:
        url = m.group(0).rstrip(").,;:!?'\"")
        return ("[BOOK]" if link_matches(url, prefixes) else "[LINK]") + m.group(0)[len(url):]
    return _URL_IN_TEXT.sub(rep, text)


def clip_around(text: str, mark: str = "[BOOK]", limit: int = 2000) -> str:
    """截到 limit 字符；标记落在截断之后时，保留开头和标记前后的一段（同 papers.clip_around_paper）。"""
    if len(text) <= limit or mark in text[:limit]:
        return text[:limit]
    pos = text.find(mark)
    if pos < 0:
        return text[:limit]
    return f"{text[: limit - 700]} …（中间省略）… {text[max(0, pos - 450): pos + 250]}"


def cmd_sample_prepare(args) -> None:
    """主书架的书（模型判为 book、过 3/3）的评论提及里随机抽 200 条（自己文字 ≥100 字），Haiku 和 Sonnet 各标一遍。"""
    import random

    from hs import llm_batch
    from hs.config import cfg
    from hs.steps.papers import HAIKU, SONNET
    from hs.text import own_len, to_text
    from hs.tree import get_items, parent_snippets, root_stories

    seed = {r["id"]: r for r in (json.loads(x) for x in (OUT / "seed.jsonl").read_text().split("\n") if x.strip())}
    core = {x["id"] for x in (json.loads(y) for y in (OUT / "signal.jsonl").read_text().split("\n") if y.strip())
            if x.get("kind") == "book" and x["core"]}
    rows = [json.loads(x) for x in (OUT / "link_mentions.jsonl").read_text().split("\n") if x.strip()]
    rows = [r for r in rows if r["book"] in core and r["src"] != "story_url"]
    random.Random(args.seed).shuffle(rows)
    min_chars = int(cfg()["rules"]["min_own_chars"])
    con = connect(read_only=True)
    picked, seen, k = [], set(), 0
    while len(picked) < args.n and k < len(rows):
        chunk = rows[k: k + 400]
        k += 400
        texts = get_items(con, [r["hn_id"] for r in chunk], "id, text")
        for r in chunk:
            t = texts.get(r["hn_id"])
            key = (r["hn_id"], r["book"])
            if t and t[1] and key not in seen and own_len(t[1]) >= min_chars:
                seen.add(key)
                picked.append((r, t[1]))
            if len(picked) >= args.n:
                break
    ids = [r["hn_id"] for r, _ in picked]
    roots, pars = root_stories(con, ids), parent_snippets(con, ids)
    con.close()
    items = []
    for r, html in picked:
        b = seed[r["book"]]
        items.append({"id": f"{r['hn_id']}:{r['book']}", "book_title": b["title"], "book_authors": b["authors"],
                      "story_title": (roots.get(r["hn_id"]) or (None, ""))[1] or "",
                      "parent_snippet": mask_book_links(pars.get(r["hn_id"], ""), b["prefixes"])[:300],
                      "text": clip_around(mask_book_links(to_text(html), b["prefixes"]))})
    for task, model in zip(SAMPLE_TASKS, (HAIKU, SONNET)):
        llm_batch.prepare(task, items, BOOK_STANCE_PROMPT, batch_size=100, max_chars=60000,
                          out_fields=["about_book", "stance", "confidence", "quote", "why"], overwrite=True, model=model)
    no_mark = sum("[BOOK]" not in x["text"] for x in items)
    print(f"sample-prepare: {len(items)} 条（{len({r['book'] for r, _ in picked})} 本书；可抽的评论提及 {len(rows):,}），"
          f"正文里找不到 [BOOK] 的 {no_mark} 条 → {', '.join(SAMPLE_TASKS)}")


def book_items(picked: list[tuple[dict, str]], seed: dict[str, dict], con) -> list[dict]:
    """(link_mentions 的一行, 评论 HTML) → 给子 agent 的输入：书名、作者、评论者、讨论串标题、父评论开头、去链接的正文。"""
    from hs.text import to_text
    from hs.tree import parent_snippets, root_stories

    ids = [r["hn_id"] for r, _ in picked]
    roots, pars = root_stories(con, ids), parent_snippets(con, ids)
    out = []
    for r, html in picked:
        b = seed[r["book"]]
        out.append({"id": f"{r['hn_id']}:{r['book']}", "book_title": b["title"], "book_authors": b["authors"],
                    "commenter": r["by"], "story_title": (roots.get(r["hn_id"]) or (None, ""))[1] or "",
                    "parent_snippet": mask_book_links(pars.get(r["hn_id"], ""), b["prefixes"])[:300],
                    "text": clip_around(mask_book_links(to_text(html), b["prefixes"]))})
    return out


def cmd_label_prepare(args) -> None:
    """全量立场标注（D48，我 2026-11-05 确认：Sonnet + v3，只按官方链接）→ data/llm/book_stance_core/。
    主书架的书（模型判为 book、过 3/3）的评论提及，自己文字 ≥100 字；每本书每个月最多 --cap 条（先取不同的人，每人最早一条），
    因为分数只看“有推荐的月份数”。story 提交不标（提交者只算人数）。"""
    from hs import llm_batch
    from hs.steps.papers import SONNET

    items, stats = label_picks(args.cap)
    paths = llm_batch.prepare(LABEL_TASK, items, BOOK_STANCE_PROMPT_V3, batch_size=100, max_chars=60000,
                              out_fields=STANCE_OUT, overwrite=args.overwrite, model=SONNET)
    stats["batches"] = len(paths)
    (OUT / "label_prepare.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    print(f"label-prepare: {json.dumps(stats, ensure_ascii=False)} → {llm_batch.task_dir(LABEL_TASK)}")


def label_picks(cap: int) -> tuple[list[dict], dict]:
    """要标立场的评论提及：主书架的书（模型判为 book、过 3/3），自己文字 ≥100 字；每本书每个月最多 cap 条
    （先取不同的人，每人最早一条）。返回给子 agent 的输入和统计。"""
    from hs.config import cfg
    from hs.text import own_len
    from hs.tree import get_items

    seed = {r["id"]: r for r in read_lines(OUT / "seed.jsonl")}
    core = {x["id"] for x in read_lines(OUT / "signal.jsonl") if x.get("kind") == "book" and x["core"]}
    rows = sorted((r for r in read_lines(OUT / "link_mentions.jsonl") if r["book"] in core and r["src"] != "story_url"),
                  key=lambda r: (r["book"], r["time"], r["hn_id"]))
    min_chars = int(cfg()["rules"]["min_own_chars"])
    con = connect(read_only=True)
    texts: dict[int, tuple] = {}
    ids = sorted({r["hn_id"] for r in rows})
    for k in range(0, len(ids), 2000):
        texts.update(get_items(con, ids[k: k + 2000], "id, text"))
    ok = [r for r in rows if (texts.get(r["hn_id"]) or (None, None))[1] and own_len(texts[r["hn_id"]][1]) >= min_chars]
    by_month: dict[tuple, list] = defaultdict(list)
    for r in ok:
        by_month[(r["book"], r["time"][:7])].append(r)
    picked = []
    for _, rs in sorted(by_month.items()):
        seen, first, rest = set(), [], []
        for r in rs:  # 已按时间排序：先每人最早一条，再补同一个人的
            (first if r["by"] not in seen else rest).append(r)
            seen.add(r["by"])
        picked += [(r, texts[r["hn_id"]][1]) for r in (first + rest)[:cap]]
    items = book_items(picked, seed, con)
    con.close()
    return items, {"books": len(core), "comment_mentions": len(rows), "labelable": len(ok), "book_months": len(by_month),
                   "picked": len(items), "cap": cap}


def cmd_label_inc(args) -> None:
    """补标（Sonnet + v3）：补了官方链接以后多出来的、还没有立场标签的提及 → book_stance_inc_<tag>。没有就不建任务。"""
    from hs import llm_batch
    from hs.steps.papers import SONNET

    items, stats = label_picks(args.cap)
    have = set()
    for task in [LABEL_TASK, *llm_batch.tasks_like(LABEL_INC)]:
        have |= set(llm_batch.inputs(task))
    new = [x for x in items if x["id"] not in have]
    task = f"{LABEL_INC}{args.tag}"
    if not new:
        print("label-inc: 没有要补标的")
        return
    paths = llm_batch.prepare(task, new, BOOK_STANCE_PROMPT_V3, batch_size=100, max_chars=60000,
                              out_fields=STANCE_OUT, overwrite=True, model=SONNET)
    by_book = defaultdict(int)
    for x in new:
        by_book[x["id"].split(":", 1)[1]] += 1
    print(f"label-inc: {len(new)} 条（{dict(sorted(by_book.items(), key=lambda kv: -kv[1])[:8])}）→ {llm_batch.task_dir(task)}"
          f"（{len(paths)} 批，Sonnet）")


def cmd_sample_rerun(args) -> None:
    """同样的 200 条（输入原样复制，保证可比）换 prompt 重跑：book_stance_sample_{haiku,sonnet}<suffix>。"""
    from hs import llm_batch
    from hs.steps.papers import HAIKU, SONNET

    items = list(llm_batch.inputs(SAMPLE_TASKS[0]).values())
    for task, model in zip(SAMPLE_TASKS, (HAIKU, SONNET)):
        llm_batch.prepare(f"{task}{args.suffix}", items, PROMPTS[args.suffix], batch_size=100, max_chars=60000,
                          out_fields=["about_book", "stance", "confidence", "quote", "why"], overwrite=True, model=model)
    print(f"sample-rerun: {len(items)} 条 → {', '.join(t + args.suffix for t in SAMPLE_TASKS)}")


def cmd_sample_agree(args) -> None:
    """Haiku 和 Sonnet 在同样 200 条上的一致率，分歧逐条写进 reports/phase5/sample_review<suffix>.md（我抽查用）。"""
    from collections import Counter

    from hs import llm_batch

    sfx = getattr(args, "suffix", "")
    ins = llm_batch.inputs(SAMPLE_TASKS[0] + sfx)
    a, b = (llm_batch.outputs(t + sfx) for t in SAMPLE_TASKS)
    keys = [k for k in ins if k in a and k in b]
    pos = {"strong_rec", "rec"}
    same = sum(a[k]["stance"] == b[k]["stance"] for k in keys)
    same_pos = sum((a[k]["stance"] in pos) == (b[k]["stance"] in pos) for k in keys)
    same_about = sum(bool(a[k].get("about_book")) == bool(b[k].get("about_book")) for k in keys)
    res = {"n": len(keys), "stance_agree": round(same / len(keys), 3), "positive_agree": round(same_pos / len(keys), 3),
           "about_agree": round(same_about / len(keys), 3),
           "haiku": dict(Counter(a[k]["stance"] for k in keys)), "sonnet": dict(Counter(b[k]["stance"] for k in keys)),
           "not_about_haiku": sum(not a[k].get("about_book", True) for k in keys),
           "not_about_sonnet": sum(not b[k].get("about_book", True) for k in keys)}
    print("sample-agree:", json.dumps(res, ensure_ascii=False))
    diff = [k for k in keys if a[k]["stance"] != b[k]["stance"] or bool(a[k].get("about_book")) != bool(b[k].get("about_book"))]
    out = PATHS.reports / "phase5"
    out.mkdir(parents=True, exist_ok=True)
    lines = ["# Phase 5 样本：Haiku 和 Sonnet 标得不一样的条目", "",
             f"{len(keys)} 条里 {len(diff)} 条不一样。立场一致率 {res['stance_agree']:.0%}，“是不是推荐”一致率 {res['positive_agree']:.0%}，"
             f"“是不是在说这本书”一致率 {res['about_agree']:.0%}。原文已去链接（[BOOK] = 这本书）。", ""]
    for k in diff:
        x = ins[k]
        lines += [f"## {x['book_title']}（HN 评论 {k.split(':', 1)[0]}）", "",
                  f"- Haiku：{a[k]['stance']}{'' if a[k].get('about_book', True) else '（不是在说这本书）'}，{a[k].get('confidence')}",
                  f"- Sonnet：{b[k]['stance']}{'' if b[k].get('about_book', True) else '（不是在说这本书）'}，{b[k].get('confidence')}",
                  f"- 讨论串：{x['story_title']}", "", "> " + x["text"][:900].replace("\n", "\n> "), ""]
    (out / f"sample_review{sfx}.md").write_text("\n".join(lines) + "\n")
    (out / f"sample_agree{sfx}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"分歧 {len(diff)} 条 → {out / f'sample_review{sfx}.md'}")


# ---------------------------------------------------------------- 算分（同论文，D48；2026-11-05 晚）
LICENSES = PIPELINE_DIR / "books_licenses.jsonl"
# 同一本书在书单里有两条（11-05 核实许可证时发现）：左边并进右边
MERGE = {
    "book:site-reliability-engineering": "book:site-reliability-engineering-how-google-run-production-syste",
    "book:hitchhiker-s-guide-to-python": "book:the-hitchhiker-s-guide-to-python-best-practices-for-developm",
    "book:programming-languages-application-and-interpretation-2nd-edi": "book:programming-languages-application-and-interpretation",
}
# 书单里的书名、作者、链接有错、缺或过时的，按官方页面改（书架上显示这些；11-05 晚逐个打开核对过链接）
_W = "Wikibooks contributors"
FIX = {
    "book:how-to-design-programs": {"authors": "Matthias Felleisen, Robert Bruce Findler, Matthew Flatt, Shriram Krishnamurthi",
                                    "url": "https://htdp.org/"},
    "book:practical-common-lisp": {"authors": "Peter Seibel", "url": "https://gigamonkeys.com/book/"},
    "book:the-architecture-of-open-source-applications-vol-1-elegance-": {
        "title": "The Architecture of Open Source Applications", "authors": "Amy Brown, Greg Wilson (eds.)",
        "url": "https://aosabook.org/en/index.html"},
    "book:eloquent-javascript-4th-edition": {"title": "Eloquent JavaScript", "url": "https://eloquentjavascript.net/"},
    "book:pro-git": {"url": "https://git-scm.com/book/en/v2"},
    "book:crafting-interpreters": {"authors": "Robert Nystrom", "url": "https://craftinginterpreters.com/contents.html"},
    "book:the-rust-programming-language": {"authors": "Steve Klabnik, Carol Nichols, Chris Krycho",
                                           "url": "https://doc.rust-lang.org/book/"},
    "book:learn-you-some-erlang-for-great-good": {"url": "https://learnyousomeerlang.com/"},
    "book:use-the-index-luke-a-guide-to-sql-database-performance": {"title": "Use The Index, Luke!",
                                                                     "url": "https://use-the-index-luke.com/"},
    # MIT Press 官方全文页（许可证也写在这一页）；书单给的 web.mit.edu 那份 PDF 有 7 MB、很慢
    "book:structure-and-interpretation-of-computer-programs": {
        "authors": "Harold Abelson, Gerald Jay Sussman, Julie Sussman",
        "url": "https://mitp-content-server.mit.edu/books/content/sectbyfn/books_pres_0/6515/sicp.zip/index.html"},
    "book:game-programming-patterns": {"authors": "Robert Nystrom", "url": "https://gameprogrammingpatterns.com/"},
    "book:clojure-for-the-brave-and-true": {"authors": "Daniel Higginbotham", "url": "https://www.braveclojure.com/"},
    "book:digital-signal-processing-for-engineers-and-scientists": {
        "title": "The Scientist and Engineer's Guide to Digital Signal Processing", "url": "https://www.dspguide.com/"},
    "book:thinking-forth": {"url": "https://thinking-forth.sourceforge.net/"},
    "book:beej-s-guide-to-network-programming-using-internet-sockets": {"title": "Beej's Guide to Network Programming",
                                                                         "authors": "Brian “Beej Jorgensen” Hall"},
    # comp.compilers 站长托管的原版（书单给的 stack.nl 那份 PDF 是第三方转的，现在也连不上）
    "book:let-s-build-a-compiler": {"url": "https://compilers.iecc.com/crenshaw/"},
    "book:advanced-bash-scripting-guide": {"authors": "Mendel Cooper"},
    "book:on-lisp": {"authors": "Paul Graham", "url": "https://www.paulgraham.com/onlisp.html"},
    "book:paradigms-of-artificial-intelligence-programming-case-studie": {
        "title": "Paradigms of Artificial Intelligence Programming", "url": "https://norvig.github.io/paip-lisp/"},
    "book:common-lisp-a-gentle-introduction-to-symbolic-computation": {"url": "https://www.cs.cmu.edu/~dst/LispBook/"},
    "book:php-the-right-way": {"authors": "Josh Lockhart, Phil Sturgeon 等", "url": "https://phptherightway.com/"},
    "book:site-reliability-engineering-how-google-run-production-syste": {
        "title": "Site Reliability Engineering: How Google Runs Production Systems"},
    "book:haskell": {"title": "Haskell Wikibook", "authors": _W},
    "book:programming-languages-application-and-interpretation": {
        "authors": "Shriram Krishnamurthi", "url": "https://plai.org/"},
    "book:information-theory-inference-and-learning-algorithms": {"url": "https://www.inference.org.uk/itila/book.html"},
    "book:write-yourself-a-scheme-in-48-hours": {"authors": f"Jonathan Tang, {_W}"},
    "book:the-rustonomicon": {"authors": "The Rust Project", "url": "https://doc.rust-lang.org/nomicon/"},
    "book:shape-up-stop-running-in-circles-and-ship-work-that-matters": {
        "title": "Shape Up: Stop Running in Circles and Ship Work that Matters"},
    "book:zeromq-guide": {"title": "ZeroMQ: The Guide", "authors": "Pieter Hintjens"},
    "book:build-your-own-lisp": {"url": "https://buildyourownlisp.com/"},
    "book:ray-tracing-in-one-weekend": {"authors": "Peter Shirley, Trevor David Black, Steve Hollasch"},
    "book:software-foundations": {"authors": "Benjamin C. Pierce 等", "url": "https://softwarefoundations.cis.upenn.edu/"},
    "book:physically-based-rendering-third-edition-from-theory-to-impl": {
        "title": "Physically Based Rendering: From Theory to Implementation", "url": "https://www.pbr-book.org/"},
    "book:the-nature-of-code": {"url": "https://natureofcode.com/"},
    "book:security-engineering": {"authors": "Ross Anderson", "url": "https://www.cl.cam.ac.uk/archive/rja14/book.html"},
    "book:programming-in-lua-first-edition": {"title": "Programming in Lua (first edition)", "authors": "Roberto Ierusalimschy"},
    "book:why-s-poignant-guide-to-ruby": {"authors": "why the lucky stiff", "url": "https://poignant.guide/"},
    "book:natural-language-processing-with-python": {"authors": "Steven Bird, Ewan Klein, Edward Loper",
                                                     "url": "https://www.nltk.org/book/"},
    "book:software-engineering-for-internet-applications": {"authors": "Eve Andersson, Philip Greenspun, Andrew Grumet"},
    "book:real-world-ocaml": {"authors": "Yaron Minsky, Anil Madhavapeddy"},
    "book:learn-prolog-now": {"authors": "Patrick Blackburn, Johan Bos, Kristina Striegnitz",
                              "url": "https://www.let.rug.nl/bos/lpn/"},
    "book:the-hitchhiker-s-guide-to-python-best-practices-for-developm": {"authors": "Kenneth Reitz, Tanya Schlusser 等",
                                                                           "url": "https://docs.python-guide.org/"},
    "book:readings-in-database-systems-5th-ed": {"title": "Readings in Database Systems (5th Edition)",
                                                 "authors": "Peter Bailis, Joseph M. Hellerstein, Michael Stonebraker",
                                                 "url": "http://www.redbook.io/"},
    "book:the-craft-of-text-editing-or-emacs-for-the-modern-world": {
        "title": "The Craft of Text Editing: Emacs for the Modern World", "authors": "Craig A. Finseth"},
    "book:convex-optimization": {"url": "https://web.stanford.edu/~boyd/cvxbook/"},
    "book:crypto-101-crypto-for-everyone": {"title": "Crypto 101", "authors": "Laurens Van Houtven"},
    "book:dive-into-deep-learning": {"authors": "Aston Zhang, Zachary C. Lipton, Mu Li, Alexander J. Smola"},
    "book:tonc-gba-programming-game-boy-advance-development": {"title": "Tonc: Game Boy Advance Programming",
                                                               "authors": "Jasper Vijn"},
    "book:homotopy-type-theory-univalent-foundations-of-mathematics": {"authors": "The Univalent Foundations Program"},
    "book:bayesian-methods-for-hackers": {"title": "Probabilistic Programming and Bayesian Methods for Hackers"},
    "book:stuff-goes-bad-erlang-in-anger": {"authors": "Fred Hebert"},
    "book:500-lines-or-less": {"title": "500 Lines or Less", "authors": "Michael DiBernardo (ed.)",
                               "url": "https://aosabook.org/en/500L/introduction.html"},
    # 作者博客上的连载是官方版；书单给的是社区整理的 PDF 仓库
    "book:category-theory-for-programmers": {
        "authors": "Bartosz Milewski",
        "url": "https://bartoszmilewski.com/2014/10/28/category-theory-for-programmers-the-preface/"},
    "book:web-browser-engineering": {"url": "https://browser.engineering/"},
    "book:the-internals-of-postgresql-for-database-administrators-and-": {"title": "The Internals of PostgreSQL",
                                                                           "authors": "Hironobu Suzuki",
                                                                           "url": "https://www.interdb.jp/pg/"},
    "book:let-over-lambda-50-years-of-lisp": {"title": "Let Over Lambda", "authors": "Doug Hoyte",
                                              "url": "https://letoverlambda.com/"},
    "book:the-debian-administrator-s-handbook": {"authors": "Raphaël Hertzog, Roland Mas", "url": "https://debian-handbook.info/"},
    "book:composing-programs": {"url": "https://composingprograms.com/"},
    "book:ada-programming": {"title": "Ada Programming Wikibook", "authors": _W},
    "book:linux-inside": {"title": "Linux Insides", "authors": "0xAX（Alexander Kuleshov）"},
    "book:asynchronous-programming-in-rust": {"authors": "Rust Async Working Group", "url": "https://rust-lang.github.io/async-book/"},
    "book:couchdb-the-definitive-guide": {"authors": "J. Chris Anderson, Jan Lehnardt, Noah Slater",
                                          "url": "https://guide.couchdb.org/"},
    "book:latex": {"title": "LaTeX Wikibook", "authors": _W},
    "book:build-your-own-redis-with-c-c": {"authors": "James Smith", "url": "https://build-your-own.org/redis/"},
    "book:neural-networks-and-deep-learning": {"authors": "Michael Nielsen"},
}
STANCES = ("strong_rec", "rec", "reference", "joke", "critical")
KEEP_CLASS = {"strong_rec": 0, "rec": 0, "critical": 0, "reference": 1, "joke": 2}  # 同论文 papers.select_mentions


def read_lines(p: Path) -> list[dict]:
    from hs.llm_batch import read_jsonl

    return read_jsonl(p)


def load_licenses() -> dict[str, dict]:
    return {r["id"]: r for r in read_lines(LICENSES)}


LABEL_INC = "book_stance_inc_"  # 补标：后来补了官方链接、多出来的提及（book_stance_inc_<日期>）


def book_labels() -> dict[str, dict]:
    """立场标注的输出（只认输入里有的 id、立场合法的）：hn_id:book → 标签。全量在前，补标按日期排在后面。"""
    from hs import llm_batch

    out: dict[str, dict] = {}
    for task in [LABEL_TASK, *llm_batch.tasks_like(LABEL_INC)]:
        valid = set(llm_batch.inputs(task))
        out.update({k: v for k, v in llm_batch.outputs(task).items() if k in valid and v.get("stance") in STANCES})
    return out


def cmd_score(args) -> None:
    """主书架的书（模型判为 book、宽口径过 3/3 的 443 本）重新数人和月份、算分 → data/build/books/scored.jsonl。
    - 只数“算一次提及”的：story 提交，或者评论者自己的文字 ≥100 字的评论（同论文）。
    - 去掉：标注为“链接其实不是在说这本书”的；作者本人（标注里 author_self 的用户）对这本书的全部提及，包括他提交的 story。
    - 分数同论文：有推荐的不同月份数 + 0.5 × 有强推荐的月份数，每人最多贡献 2 个月（config 的 score_months_per_person）。
    - 上书架：重新数过还在 3 人 3 个月以上，并且许可证核实通过（books_licenses.jsonl 的 status = ok）。"""
    from collections import Counter

    from hs.config import cfg
    from hs.text import own_len
    from hs.tree import get_items, root_stories

    rules = cfg()["rules"]
    min_chars, cap = int(rules["min_own_chars"]), int(rules.get("score_months_per_person", 0))
    min_people, min_months = int(rules["book_min_people"]), int(rules["book_min_months"])
    seed = {r["id"]: r for r in read_lines(OUT / "seed.jsonl")}
    sig = {r["id"]: r for r in read_lines(OUT / "signal.jsonl")}
    lic = load_licenses()
    labels = book_labels()
    scope = {i for i, x in sig.items() if x.get("kind") == "book" and x["core"]}
    rows = [r for r in read_lines(OUT / "link_mentions.jsonl") if r["book"] in scope]
    con = connect(read_only=True)
    ids = sorted({r["hn_id"] for r in rows})
    texts: dict[int, tuple] = {}
    for k in range(0, len(ids), 2000):
        texts.update(get_items(con, ids[k: k + 2000], "id, text"))
    roots = root_stories(con, ids)
    con.close()
    canon = lambda b: MERGE.get(b, b)  # noqa: E731
    # 作者本人：任何一条标注说他是作者，他对这本书（合并后）的全部提及都不算
    who = {(r["hn_id"], r["book"]): r["by"] for r in rows}
    authors: dict[str, set] = defaultdict(set)
    for k, v in labels.items():
        hid, b = k.split(":", 1)
        if v.get("author_self") and who.get((int(hid), b)):
            authors[canon(b)].add(who[(int(hid), b)])
    drop = Counter()
    per: dict[str, dict[int, dict]] = defaultdict(dict)
    for r in sorted(rows, key=lambda r: r["time"]):
        b = canon(r["book"])
        lab = labels.get(f"{r['hn_id']}:{r['book']}")
        if r["src"] != "story_url":
            t = (texts.get(r["hn_id"]) or (None, None))[1]
            if not t or own_len(t) < min_chars:
                drop["short"] += 1
                continue
        if lab and lab.get("about_book") is False:
            drop["not_about"] += 1
            continue
        if r["by"] in authors[b]:
            drop["author"] += 1
            continue
        if r["hn_id"] in per[b]:
            drop["dup"] += 1
            continue
        per[b][r["hn_id"]] = {**r, "book": b, "orig_book": r["book"], "label": lab if r["src"] != "story_url" else None}
    last = max(r["time"] for r in rows)
    recent_from = f"{int(last[:4]) - 1:04d}-{last[5:7]}"
    out = []
    for b in sorted({canon(i) for i in scope}):
        ms = list(per.get(b, {}).values())
        people, months, threads, by_year = set(), set(), set(), Counter()
        rec, strong, pm_rec, pm_strong = set(), set(), defaultdict(set), defaultdict(set)
        labeled = labelable = 0
        for m in ms:  # 已按时间排序
            mo = m["time"][:7]
            people.add(m["by"])
            months.add(mo)
            by_year[mo[:4]] += 1
            root = roots.get(m["hn_id"])
            threads.add(root[0] if root else m["hn_id"])
            if m["src"] == "story_url":
                continue
            labelable += 1
            lab = m["label"]
            if not lab:
                continue
            labeled += 1
            if lab["stance"] in ("rec", "strong_rec") and (not cap or mo in pm_rec[m["by"]] or len(pm_rec[m["by"]]) < cap):
                pm_rec[m["by"]].add(mo)
                rec.add(mo)
            if lab["stance"] == "strong_rec" and (not cap or mo in pm_strong[m["by"]] or len(pm_strong[m["by"]]) < cap):
                pm_strong[m["by"]].add(mo)
                strong.add(mo)
        s, L = seed[b], lic.get(b) or {}
        fix = FIX.get(b, {})
        core = len(people) >= min_people and len(months) >= min_months
        out.append({
            "id": b, "title": fix.get("title", s["title"]), "authors": fix.get("authors", s["authors"]),
            "url": fix.get("url") or L.get("url") or s["urls"][0], "urls": s["urls"],
            "merged": sorted(k for k, v in MERGE.items() if v == b), "sections": s["sections"],
            "aliases": list(dict.fromkeys(SEARCH_ALIASES.get(b, []) + [x for x in s.get("aliases", []) if len(x) <= 12])),
            "license": L.get("license"), "license_evidence": L.get("evidence"), "license_url": L.get("evidence_url"),
            "license_status": L.get("status", "unchecked"), "unfinished": bool(L.get("unfinished")),
            "http_only": bool(L.get("http_only")), "hold": L.get("hold"), "display_note": L.get("display_note"),
            "people": len(people), "months": len(months), "threads": len(threads),
            "by_year": dict(sorted(by_year.items())), "first": min((m["time"] for m in ms), default=None),
            "last": max((m["time"] for m in ms), default=None), "stories": sum(m["src"] == "story_url" for m in ms),
            "months_rec": len(rec), "months_strong": len(strong), "score": len(rec) + 0.5 * len(strong),
            "active_12m": sum(1 for mo in months if mo > recent_from), "rec_12m": sum(1 for mo in rec if mo > recent_from),
            "labeled": labeled, "labelable": labelable, "has_positive": bool(rec),
            "author_users": sorted(authors.get(b, ())), "core": core,
            "shelf": core and L.get("status") == "ok",
        })
    out.sort(key=lambda x: (not x["shelf"], -x["score"], -x["people"], -x["months"]))
    with open(OUT / "scored.jsonl", "w") as f:
        for x in out:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    # 详情页显示的提及：每本最多 20 条，先推荐和批评、再引用、玩笑、没标注的评论、story 提交；每类先不同的人（同论文）
    keep_cap = int(rules["max_mentions_per_item"])
    shelf = {x["id"] for x in out if x["shelf"]}
    kept = []
    for b in shelf:
        ms = sorted(per[b].values(), key=lambda m: m["time"])
        cls = lambda m: 4 if m["src"] == "story_url" else KEEP_CLASS.get((m["label"] or {}).get("stance"), 3)  # noqa: E731
        sel, seen = [], set()
        for c in range(5):
            first, rest = [], []
            for m in (m for m in ms if cls(m) == c):
                (first if m["by"] not in seen else rest).append(m)
                seen.add(m["by"])
            sel += first + rest
            if len(sel) >= keep_cap:
                break
        kept += sel[:keep_cap]
    with open(OUT / "kept_mentions.jsonl", "w") as f:
        for m in sorted(kept, key=lambda m: (m["book"], m["time"])):
            root = roots.get(m["hn_id"])
            f.write(json.dumps({"book": m["book"], "hn_id": m["hn_id"], "orig_book": m.get("orig_book"), "by": m["by"],
                                "time": m["time"], "src": m["src"], "story_id": root[0] if root else None,
                                "story_title": root[1] if root else None, "label": m["label"]}, ensure_ascii=False) + "\n")
    n = Counter(("shelf" if x["shelf"] else "core" if x["core"] else "below") for x in out)
    st = Counter(x["license_status"] for x in out if x["core"])
    print(f"score: {len(scope)} 本（合并重复后 {len(out)}）；重新数过 3/3 的 {sum(x['core'] for x in out)}，"
          f"其中许可证 {dict(st)}；上书架 {n['shelf']} 本。去掉的提及：{dict(drop)}；作者本人 {sum(len(v) for v in authors.values())} 人次")
    print(f"显示的提及 {len(kept)} 条，其中有立场标注的 {sum(1 for m in kept if m['label'])} 条 → {OUT / 'scored.jsonl'}、kept_mentions.jsonl")
    print("\n上书架的前 30 本：书 | 分 | 人 | 月 | 推荐月 | 强推荐月 | 许可")
    for x in [x for x in out if x["shelf"]][:30]:
        print(f"{x['title'][:56]} | {x['score']:g} | {x['people']} | {x['months']} | {x['months_rec']} | {x['months_strong']} | {x['license']}")


# ---------------------------------------------------------------- 卡片（Sonnet，87 本）和 HN 原话下面的中文说明
CARD_TASK = "book_cards"
WHY_ZH_TASK = "book_why_zh"
SUBJECTS = {  # 图书书架的分类（封面底色见 web/src/lib/cover.ts 的 b- 开头的键）
    "intro": "编程入门", "lang": "编程语言", "plt": "语言实现与理论", "systems": "系统与网络", "data": "数据库",
    "ml": "机器学习与 AI", "math": "数学与信号", "graphics": "图形与游戏", "eng": "软件工程", "security": "安全与密码学",
}
CARD_OUT = ["title_zh", "oneliner_zh", "summary_zh", "why_hn", "how_to_read", "audience_zh", "prerequisites",
            "difficulty", "reading_hours", "subject"]
BOOK_CARD_PROMPT = """# 任务：给开源书书架写中文卡片

输入是 JSONL 的 Markdown 视图，每条一本书：
`{"id", "title", "authors", "url", "license", "sections", "unfinished", "hn", "mentions"}`
- 这些书都能在官方网站免费读全书（开放许可，或作者、出版社官方免费放出）。`url` 是官方免费版的地址，`license` 是许可证。
- `sections`：它在 free-programming-books 书单里的分类，只作参考。
- `unfinished`：true 表示书还没写完，只有一部分章节。
- `hn`：Hacker News 上提到它的统计：不同的人数、月份数、第一次和最近一次被提起、按年的提及数。
- `mentions`：HN 评论里提到这本书的原话（最多 20 条）。`stance` 是评论对书的态度（strong_rec 强烈推荐 / rec 推荐 / critical 批评 / reference 引用 / joke 玩笑），`quote` 是原话摘录（[BOOK] 是这本书的链接），`why` 是一句英文说明。

读者是想自学的中文读者。卡片放在书的详情页上，帮读者判断要不要读、怎么读。每本书输出一行 JSON：
```
{"id": <同输入>,
 "title_zh": "中文书名",
 "oneliner_zh": "一行中文介绍",
 "summary_zh": "导读，3–4 句",
 "why_hn": "一句中文",
 "how_to_read": ["建议读法，2–4 条"],
 "audience_zh": "一句中文",
 "prerequisites": ["0–4 个中文短语"],
 "difficulty": 1-5,
 "reading_hours": 整数,
 "subject": "书架分类 id"}
```
各字段：
- title_zh：中文书名。这本书有广为人知的中文译本时用译本的书名（例如 SICP 写“计算机程序的构造和解释”）；没有就意译。拿不准有没有译本时意译，不要编造“中文版”。
- oneliner_zh：不超过 40 个汉字，这本书讲什么、有什么特点。用在书架列表里，不要以“本书”“这本书”“一本”开头。
- summary_zh：3–4 句中文：讲什么、怎么讲（风格、方法、有没有练习或配套代码）、和同类的书比有什么不同。准确、具体，不写空话。
- why_hn：HN 上的人为什么反复推荐它、拿它说明什么。只依据 mentions 归纳，不要编造。有批评的，可以带一句批评的是什么。
- how_to_read：每条不超过 50 个汉字：从哪里开始、哪些部分先读或可以跳过、要不要做练习、和什么配合着读。依据你对这本书目录的了解和 mentions 里的说法；拿不准章节号就不写章节号。
- audience_zh：适合谁读，不超过 30 个汉字。
- prerequisites：读之前最好会的；专业术语保留英文原词，例如“C 语言指针”“微积分”“递归（recursion）”。入门书可以是空数组。
- difficulty：1 = 零基础能读；2 = 学过一点编程；3 = 有一两年编程经验；4 = 需要扎实的专业基础；5 = 需要研究生水平的数学或专门背景。
- reading_hours：认真读完一遍、做主要练习的大致小时数。
- subject 从下面选一个：
  - intro 编程入门：第一本编程书、程序设计方法（如 How to Design Programs、Learn to Program）
  - lang 编程语言：学一门具体的语言或它的生态（如 Rust、JavaScript、Erlang、Clojure、Haskell、Common Lisp、Prolog、R、Python 实践）
  - plt 语言实现与理论：解释器、编译器、类型系统、形式化证明、程序语言理论（如 SICP、Crafting Interpreters、PLAI、Software Foundations）
  - systems 系统与网络：操作系统、网络编程、Unix 和 Shell、Linux 内核、消息系统
  - data 数据库：数据库原理、SQL 性能、数据库系统
  - ml 机器学习与 AI：深度学习、统计学习、信息论、NLP、概率编程、经典 AI 编程
  - math 数学与信号：线性代数、优化、信号处理、网络科学这类以数学为主的书
  - graphics 图形与游戏：图形学、着色器、光线追踪、游戏编程、创意编程
  - eng 软件工程：架构、工程实践、运维、开源协作、版本控制、产品开发方法
  - security 安全与密码学

要求：
- 只写有把握的事实。不熟悉这本书时，依据书名、作者、mentions 写得保守一些，不要编造章节、页数、版本或作者经历。
- unfinished 为 true 的，在 summary_zh 里说明还没写完。
- 书名、人名、术语可以保留英文。提到作者时直接写名字，不用“他”“她”。
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
"""

# 论文那套已经审过的写法（papers.WHY_ZH_PROMPT），“论文”换成“书”
BOOK_WHY_ZH_PROMPT = """# 任务：把 HN 评论"为什么提这本书"写成一句中文

输入是 JSONL，每行一条 HN 评论对一本书的提及：
`{"id", "book", "stance", "quote", "why"}`
- `stance`：评论对书的立场（strong_rec 强烈推荐 / rec 推荐 / critical 批评 / reference 引用 / joke 玩笑）
- `quote`：评论原话摘录（英文；[BOOK] 是这本书的链接）
- `why`：英文的一句说明，概括这条评论在说这本书什么

为每条写一句中文，放在网页上英文原话的下面，让中文读者一眼看懂这位评论者为什么提它、拿它说什么。
每行输出一个 JSON（顺序与输入一致）：
```
{"id": <同输入>, "why_zh": "一句中文"}
```
要求：
- 不超过 40 个汉字（英文术语按一个词算），一句话，句末不加句号。
- 忠实于 `quote` 和 `why`，不添加原话里没有的信息、数字或评价；`why` 和原话不一致时以原话为准。
- 从评论者的角度写这条评论做了什么，省略主语："推荐…"、"批评…"、"拿它说明…"、"把它当作…"。不要以"评论者"、"该评论"、"这条评论"开头。
- 专业术语保留英文原词，书名不用写全，用常见简称（SICP、OSTEP、PCL）。
- 批评要写清楚批评的是什么；玩笑写清楚在调侃什么。
- 不要用"他""她"指代评论者（不知道性别），需要时省略主语。
- 不要写"贴了链接"这类只描述格式的话，写这本书在评论里起什么作用。
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
"""


def shelf_books() -> list[dict]:
    return [x for x in read_lines(OUT / "scored.jsonl") if x["shelf"]]


def kept_by_book() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for m in read_lines(OUT / "kept_mentions.jsonl"):
        out[m["book"]].append(m)
    return out


def license_text(b: dict) -> str:
    lic = b.get("license") or ""
    return {"free-online": "官方免费在线（没有开放许可）", "unknown": "官方免费（没写许可证）"}.get(lic, lic)


def cmd_cards_prepare(args) -> None:
    """上书架的书 → book_cards（Sonnet）。输入：书名、作者、官方链接、许可证、HN 统计、详情页显示的有标注的原话。"""
    from hs import llm_batch
    from hs.steps.papers import SONNET

    km = kept_by_book()
    have = set(card_outputs()) if args.inc else set()
    task = f"{CARD_TASK}_inc_{args.inc}" if args.inc else CARD_TASK
    items = []
    for b in shelf_books():
        if b["id"] in have:
            continue
        ms = [m for m in km[b["id"]] if m["label"]]
        items.append({
            "id": b["id"], "title": b["title"], "authors": b["authors"], "url": b["url"], "license": license_text(b),
            "sections": "; ".join(b["sections"]), "unfinished": b["unfinished"],
            "hn": {"people": b["people"], "months": b["months"], "first": (b["first"] or "")[:10], "last": (b["last"] or "")[:10],
                   "by_year": b["by_year"]},
            "mentions": [{"stance": m["label"]["stance"], "quote": (m["label"].get("quote") or "")[:300],
                          "why": m["label"].get("why") or "", "year": int(m["time"][:4])} for m in ms],
        })
    if not items:
        print("cards-prepare: 上架的书都有卡片了")
        return
    paths = llm_batch.prepare(task, items, BOOK_CARD_PROMPT, batch_size=args.batch, max_chars=args.max_chars,
                              out_fields=CARD_OUT, overwrite=True, model=SONNET)
    print(f"cards-prepare: {len(items)} 本 → {llm_batch.task_dir(task)}（{len(paths)} 批，Sonnet）")


def cmd_why_zh_prepare(args) -> None:
    """详情页显示的、有立场标注的评论 → 中文一句（Sonnet）。--sample N：按分数从高到低取前几本书，凑够 N 条先试跑。"""
    from hs import llm_batch
    from hs.steps.papers import SONNET

    km = kept_by_book()
    items = []
    for b in shelf_books():  # 已按分数排好
        for m in km[b["id"]]:
            if m["label"]:
                items.append({"id": f"{m['hn_id']}:{m['orig_book'] or b['id']}", "book": b["title"], "stance": m["label"]["stance"],
                              "quote": (m["label"].get("quote") or "")[:400], "why": m["label"].get("why") or ""})
        if args.sample and len(items) >= args.sample:
            break
    task = f"{WHY_ZH_TASK}_sample" if args.sample else WHY_ZH_TASK
    if not args.sample and (llm_batch.task_dir(f"{WHY_ZH_TASK}_sample") / "manifest.json").exists():
        done = set(llm_batch.outputs(f"{WHY_ZH_TASK}_sample"))
        items = [x for x in items if x["id"] not in done]
    paths = llm_batch.prepare(task, items, BOOK_WHY_ZH_PROMPT, batch_size=args.batch, out_fields=["why_zh"],
                              overwrite=True, model=SONNET)
    print(f"why-zh-prepare: {len(items)} 条 → {llm_batch.task_dir(task)}（{len(paths)} 批，Sonnet）")


def license_label(lic: str | None) -> tuple[str, bool]:
    """许可证代码 → 页面上的写法，以及是不是开放许可。"""
    if not lic or lic == "unknown":
        return "官方免费（许可证没写清）", False
    if lic == "free-online":
        return "官方免费在线", False
    if lic == "Public-Domain":
        return "公有领域", True
    if lic == "CC0-1.0":
        return "CC0（公有领域）", True
    if lic.startswith("CC-"):
        m = re.match(r"CC-([A-Z-]+?)(?:-(\d\.\d)(?:-([A-Z]+))?)?$", lic)
        if m:
            return " ".join(filter(None, ["CC", m[1], m[2], m[3]])), True
    return lic.replace("-2.0", " 2.0").replace(" OR ", " / "), True


AUTHOR_SHORT = {"why the lucky stiff": "_why", "Brian “Beej Jorgensen” Hall": "Beej", 'Brian "Beej Jorgensen" Hall': "Beej",
                "Patricio Gonzalez Vivo": "Gonzalez Vivo", "0xAX（Alexander Kuleshov）": "0xAX",
                "The Univalent Foundations Program": "UF Program", "Rust Async Working Group": "Rust 异步工作组",
                "The Rust Project": "Rust 项目", "Wikibooks contributors": "Wikibooks"}
_PARTICLES = {"de", "van", "von", "da", "di", "le", "la", "Van", "Von", "De"}


def author_short(authors: str) -> str:
    """封面右下角的短作者名：第一作者的姓，多人加“等”（"Harold Abelson, Gerald Jay Sussman" → "Abelson 等"）。"""
    a = (authors or "").strip()
    if not a:
        return ""
    if a in AUTHOR_SHORT:
        return AUTHOR_SHORT[a]
    many = bool(re.search(r",|、| and | 等|et al", a))
    first = re.split(r",|、| and ", a)[0]
    first = re.sub(r"\(.*?\)|（.*?）| 等$", "", first).strip()
    if first in AUTHOR_SHORT:
        name = AUTHOR_SHORT[first]
    else:
        words = first.split()
        name = " ".join(words[-2:]) if len(words) >= 3 and words[-2] in _PARTICLES else (words[-1] if words else first)
    return f"{name} 等" if many else name


# 常见简称（搜索用，详情页写“简称 X”）；书单和手选名单里的 aliases 也会并进来
SEARCH_ALIASES = {
    "book:how-to-design-programs": ["HtDP"], "book:practical-common-lisp": ["PCL"],
    "book:the-architecture-of-open-source-applications-vol-1-elegance-": ["AOSA"],
    "book:the-rust-programming-language": ["TRPL", "Rust Book"], "book:learn-you-some-erlang-for-great-good": ["LYSE"],
    "book:you-don-t-know-js": ["YDKJS"], "book:beej-s-guide-to-network-programming-using-internet-sockets": ["Beej", "bgnet"],
    "book:advanced-bash-scripting-guide": ["ABS Guide"], "book:paradigms-of-artificial-intelligence-programming-case-studie": ["PAIP"],
    "book:high-performance-browser-networking": ["HPBN"], "book:programming-languages-application-and-interpretation": ["PLAI"],
    "book:site-reliability-engineering-how-google-run-production-syste": ["SRE"], "book:write-yourself-a-scheme-in-48-hours": ["WYAS"],
    "book:linear-algebra-done-right": ["LADR"], "book:the-rustonomicon": ["Nomicon"], "book:zeromq-guide": ["zguide", "ØMQ"],
    "book:ray-tracing-in-one-weekend": ["RTIOW"], "book:software-foundations": ["SF"],
    "book:physically-based-rendering-third-edition-from-theory-to-impl": ["PBRT"], "book:programming-in-lua-first-edition": ["PiL"],
    "book:natural-language-processing-with-python": ["NLTK Book"], "book:real-world-ocaml": ["RWO"], "book:learn-prolog-now": ["LPN"],
    "book:readings-in-database-systems-5th-ed": ["Red Book"], "book:an-introduction-to-statistical-learning": ["ISL", "ISLR"],
    "book:dive-into-deep-learning": ["D2L"], "book:learn-vimscript-the-hard-way": ["LVTHW"],
    "book:homotopy-type-theory-univalent-foundations-of-mathematics": ["HoTT"], "book:500-lines-or-less": ["500L"],
    "book:mathematics-for-machine-learning-deisenroth": ["MML"], "book:category-theory-for-programmers": ["CTFP"],
    "book:software-engineering-at-google": ["SWE Book"], "book:a-data-centric-introduction-to-computing": ["DCIC"],
    "book:understanding-deep-learning": ["UDL"], "book:asynchronous-programming-in-rust": ["Async Book"],
    "book:digital-signal-processing-for-engineers-and-scientists": ["DSP Guide"],
    "book:neural-networks-and-deep-learning": ["NNDL"], "book:the-art-of-unix-programming": ["TAOUP"],
    "book:learn-you-a-haskell-for-great-good": ["LYAH"],
}


def card_outputs() -> dict[str, dict]:
    """全部卡片任务的输出：book_cards（第一批 87 本），再是后来补上架的书（book_cards_inc_<日期>）。"""
    from hs import llm_batch

    out: dict[str, dict] = {}
    for task in llm_batch.tasks_like(CARD_TASK):
        valid = set(llm_batch.inputs(task))
        out.update({k: v for k, v in llm_batch.outputs(task).items() if k in valid and v.get("oneliner_zh")})
    return out


def why_zh_outputs() -> dict[str, str]:
    from hs import llm_batch

    out: dict[str, str] = {}
    for task in (f"{WHY_ZH_TASK}_sample", WHY_ZH_TASK):
        if (llm_batch.task_dir(task) / "manifest.json").exists():
            valid = set(llm_batch.inputs(task))
            out.update({k: v["why_zh"] for k, v in llm_batch.outputs(task).items() if k in valid and v.get("why_zh")})
    return out


def cmd_export(_args) -> None:
    """公开站的图书数据 → data/build/books/shelf.json（Web 构建时读；可随时重建）：书、卡片、详情页显示的 HN 原话。"""
    import time

    from hs.text import to_text
    from hs.tree import get_items

    books, km = shelf_books(), kept_by_book()
    cards, why_zh = card_outputs(), why_zh_outputs()
    con = connect(read_only=True)
    items = get_items(con, sorted({m["hn_id"] for ms in km.values() for m in ms}), "id, text, title, score")
    con.close()
    meta = json.loads((PATHS.build / "build_meta.json").read_text()) if (PATHS.build / "build_meta.json").exists() else {}
    out_books, out_mentions = [], {}
    for rank, b in enumerate(books, 1):
        c = cards.get(b["id"]) or {}
        label, is_open = license_label(b["license"])
        subject = c.get("subject") if c.get("subject") in SUBJECTS else None
        out_books.append({
            "id": b["id"], "slug": b["id"].removeprefix("book:"), "rank": rank, "title": b["title"],
            "title_zh": c.get("title_zh"), "authors": b["authors"], "author_short": author_short(b["authors"]),
            "url": b["url"], "license": b["license"],
            "license_label": label, "license_open": is_open, "license_url": b["license_url"],
            "license_evidence": b["license_evidence"], "unfinished": b["unfinished"], "http_only": b["http_only"],
            "note": b.get("display_note"),
            "subject": subject, "aliases": b.get("aliases", []),
            **{k: b[k] for k in ("people", "months", "threads", "by_year", "stories", "months_rec",
                                                       "months_strong", "score", "has_positive", "active_12m", "rec_12m")},
            "first": (b["first"] or "")[:10], "last": (b["last"] or "")[:10],
            "card": {k: c.get(k) for k in CARD_OUT if k not in ("title_zh", "subject")} if c else None,
        })
        ms = []
        for m in km[b["id"]]:
            it = items.get(m["hn_id"])
            lab = m["label"] or {}
            story = m["src"] == "story_url"
            ms.append({"comment_id": m["hn_id"], "by": m["by"], "time": m["time"][:19] + "Z", "story_id": m["story_id"],
                       "story_title": (it[2] if story and it else None) or m["story_title"],
                       "quote": lab.get("quote"), "why_zh": why_zh.get(f"{m['hn_id']}:{m['orig_book'] or b['id']}") if lab else None,
                       "text": to_text(it[1])[:2000] if it and it[1] and not story else None,
                       "points": it[3] if story and it else None, "stance": lab.get("stance"),
                       "source": "story_url" if story else "comment_link"})
        out_mentions[b["id"]] = ms
    n_by = defaultdict(int)
    for x in out_books:
        n_by[x["subject"]] += 1
    shelf = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "hn_cutoff": meta.get("hn_cutoff"), "fpb_sha": FPB_SHA,
             "subjects": [{"id": k, "name": v, "n": n_by.get(k, 0)} for k, v in SUBJECTS.items()],
             "books": out_books, "mentions": out_mentions}
    (OUT / "shelf.json").write_text(json.dumps(shelf, ensure_ascii=False))
    n_m = sum(len(v) for v in out_mentions.values())
    print(f"export: {len(out_books)} 本（有卡片 {sum(1 for x in out_books if x['card'])}）、原话 {n_m} 条"
          f"（有中文说明 {sum(1 for v in out_mentions.values() for m in v if m['why_zh'])}）→ {OUT / 'shelf.json'}"
          f"（{(OUT / 'shelf.json').stat().st_size / 1024:.0f} KB）；分类 {dict(n_by)}")


def cmd_report(_args) -> None:
    """上书架清单（推送前给我看）→ reports/phase5/shelf.md：总数、没上架的、按分数的全部书目。"""
    from collections import Counter

    rows = read_lines(OUT / "scored.jsonl")
    lic = load_licenses()
    shelf = json.loads((OUT / "shelf.json").read_text())
    books = shelf["books"]
    names = {s["id"]: s["name"] for s in shelf["subjects"]}
    core = [x for x in rows if x["core"]]
    n_open = sum(1 for b in books if b["license_open"])
    n_free = sum(1 for b in books if b["license"] == "free-online")
    n_unclear = len(books) - n_open - n_free
    by_subj = Counter(names.get(b["subject"], "未分类") for b in books)
    excl = [x for x in lic.values() if x.get("status") == "exclude"]
    hold = [x for x in lic.values() if x.get("status") == "hold"]
    title = {r["id"]: r["title"] for r in rows}
    n_why = sum(1 for ms in shelf["mentions"].values() for m in ms if m["why_zh"])
    n_lab = sum(1 for ms in shelf["mentions"].values() for m in ms if m["stance"])
    lines = [
        "# Phase 5 开源书：上书架清单", "",
        f"由 `uv run --project pipeline python -m hs.steps.books report` 生成（{shelf['generated_at'][:16].replace('T', ' ')}）。"
        "数据在 `data/build/books/shelf.json`，截图在 `reports/phase5/screens/`。", "",
        "## 1. 总数", "",
        f"- 上架 {len(books)} 本：前 100 本里许可证核实通过、重新数过仍在 3 人 3 个月以上的书。",
        f"  - 开放许可 {n_open} 本，官方免费在线（版权保留）{n_free} 本，免费但许可证没写清 {n_unclear} 本。",
        f"  - 分类：{'、'.join(f'{k} {v}' for k, v in by_subj.most_common())}。",
        f"- 重新数过 3 人 3 个月以上的共 {len(core)} 本；前 100 本以外的还没核实许可证，先不上架。",
        f"- 排除 {len(excl)} 本（不是免费全书）：{'、'.join(title.get(x['id'], x['id']) for x in excl)}。",
        f"- 等你定 {len(hold)} 本：", "",
    ]
    for x in hold:
        lines.append(f"  - {title.get(x['id'], x['id'])}：{x.get('note', '')}")
    lines += [
        "", "## 2. 上架清单（按分数）", "",
        "分数 = 有推荐的不同月份数 + 0.5 × 有强推荐的月份数（每人最多算 2 个月），同论文。人、月只数自己文字 ≥100 字的评论和 story 提交，"
        "不算作者本人和“链接其实不是在说这本书”的。", "",
        "| # | 书 | 中文名 | 分类 | 许可证 | 人 | 月 | 分 | 备注 |", "|---|---|---|---|---|---|---|---|---|",
    ]
    for b in books:
        note = "、".join(filter(None, ["未写完" if b["unfinished"] else "", "官网只有 http" if b["http_only"] else "", b.get("note") or "",
                                       f"简称 {b['aliases'][0]}" if b.get("aliases") else ""]))
        lines.append(f"| {b['rank']} | [{b['title']}]({b['url']}) | {b['title_zh'] or ''} | {names.get(b['subject'], '')} | "
                     f"{b['license_label']} | {b['people']} | {b['months']} | {b['score']:g} | {note} |")
    lines += ["", f"详情页显示的 HN 原话 {sum(len(v) for v in shelf['mentions'].values())} 条，其中有立场标注的 {n_lab} 条、"
                  f"已有中文说明的 {n_why} 条。", ""]
    out = PATHS.reports / "phase5" / "shelf.md"
    out.write_text("\n".join(lines))
    print(f"report: {len(books)} 本 → {out}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    s = sub.add_parser("signal")
    s.add_argument("--top", type=int, default=60)
    sub.add_parser("kind-prepare")
    s = sub.add_parser("kind-merge")
    s.add_argument("--top", type=int, default=60)
    s = sub.add_parser("sample-prepare")
    s.add_argument("--n", type=int, default=200)
    s.add_argument("--seed", type=int, default=17)
    s = sub.add_parser("sample-rerun")
    s.add_argument("--suffix", default="_v2", choices=[k for k in PROMPTS if k])
    s = sub.add_parser("sample-agree")
    s.add_argument("--suffix", default="", choices=list(PROMPTS))
    s = sub.add_parser("label-prepare")
    s.add_argument("--cap", type=int, default=3, help="每本书每个月最多标几条")
    s.add_argument("--overwrite", action="store_true", help="重建输入（不会删已有输出）")
    s = sub.add_parser("label-inc")
    s.add_argument("--tag", required=True, help="任务名后缀，比如日期 20261105")
    s.add_argument("--cap", type=int, default=3)
    sub.add_parser("score")
    s = sub.add_parser("cards-prepare")
    s.add_argument("--inc", default="", help="只给还没有卡片的书写（后来补上架的），任务名 book_cards_inc_<这个值>")
    s.add_argument("--batch", type=int, default=6)
    s.add_argument("--max-chars", type=int, default=50000)
    s = sub.add_parser("why-zh-prepare")
    s.add_argument("--sample", type=int, default=0, help="先试跑：按分数取前几本书，凑够这么多条")
    s.add_argument("--batch", type=int, default=100)
    sub.add_parser("export")
    sub.add_parser("report")
    args = ap.parse_args(argv)
    {"seed": cmd_seed, "signal": cmd_signal, "kind-prepare": cmd_kind_prepare, "kind-merge": cmd_kind_merge,
     "sample-prepare": cmd_sample_prepare, "sample-rerun": cmd_sample_rerun, "sample-agree": cmd_sample_agree,
     "label-prepare": cmd_label_prepare, "label-inc": cmd_label_inc, "score": cmd_score, "cards-prepare": cmd_cards_prepare,
     "why-zh-prepare": cmd_why_zh_prepare, "export": cmd_export, "report": cmd_report}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
