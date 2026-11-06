"""Phase 1 书架的离线计算：embedding、聚类 → 主题树（LLM 命名）、相关论文。

子命令（按顺序）：
  embed            title + abstract 用 bge-small-en-v1.5 算 embedding → data/build/embeddings.npy + embedding_ids.json
  cluster          球面 k-means 聚成 ~110 簇 → data/build/papers/clusters.json；
                   并准备 Sonnet 子 agent 的命名任务 → data/llm/taxonomy/
  taxonomy         合并子 agent 的命名结果 → data/build/taxonomy.json + papers/topics.json（论文 → 类目）
  assign-topics    月度更新：新进的论文归到最近的已有类目（不重新聚类），重算类目篇数
  related          共同推荐人 + embedding 余弦 + OpenAlex 引用关系 → data/build/related.jsonl
embed 默认只算新进的论文（已有向量的沿用），--full 全部重算。

用法：uv run python -m hs.steps.shelf <子命令>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

import duckdb
import numpy as np

from hs import llm_batch
from hs.config import PATHS, cfg
from hs.steps.papers import COUNTED, OUT, _db, load_meta, load_openalex

MODEL = "BAAI/bge-small-en-v1.5"
EMB = PATHS.build / "embeddings.npy"
EMB_IDS = PATHS.build / "embedding_ids.json"


def _ids() -> list[str]:
    return [r[0] for r in duckdb.sql(f"SELECT arxiv FROM '{OUT / 'candidates.parquet'}' ORDER BY people DESC, months DESC").fetchall()]


def load_emb() -> tuple[list[str], np.ndarray]:
    return json.loads(EMB_IDS.read_text()), np.load(EMB)


# ---------------------------------------------------------------- embedding
def cmd_embed(args) -> None:
    """已经有向量的论文沿用（月度更新只算新进的），--full 全部重算。"""
    meta = load_meta()
    ids = [a for a in _ids() if a in meta]
    old: dict[str, np.ndarray] = {}
    if not getattr(args, "full", False) and EMB.exists() and EMB_IDS.exists():
        oid, ox = load_emb()
        old = {a: ox[i] for i, a in enumerate(oid)}
    todo = [a for a in ids if a not in old]
    t0 = time.time()
    new: dict[str, np.ndarray] = {}
    if todo:
        # 模型从 Hugging Face 下载（fastembed 自己发请求）：config.toml 的 no_proxy_hosts 里的域名同样直连
        hosts = [h.lstrip("*") for h in cfg()["http"].get("no_proxy_hosts", [])]
        if hosts:
            os.environ["NO_PROXY"] = os.environ["no_proxy"] = ",".join(filter(None, [os.environ.get("NO_PROXY", ""), *hosts]))
        from fastembed import TextEmbedding

        texts = [f"{meta[a]['title']}. {meta[a].get('abstract') or ''}"[:2000] for a in todo]
        model = TextEmbedding(MODEL, cache_dir=str(PATHS.cache / "models"))
        v = np.array(list(model.embed(texts, batch_size=64)), dtype=np.float32)
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        new = dict(zip(todo, v))
    vecs = np.stack([old[a] if a in old else new[a] for a in ids]).astype(np.float32)
    np.save(EMB, vecs)
    EMB_IDS.write_text(json.dumps(ids))
    print(f"embed: {len(ids):,} × {vecs.shape[1]}，新算 {len(todo):,}、沿用 {len(ids) - len(todo):,}（{time.time()-t0:.0f}s）→ {EMB}")


# ---------------------------------------------------------------- 聚类
def spherical_kmeans(x: np.ndarray, k: int, *, iters: int = 60, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # k-means++ 初始化（余弦距离）
    c = [x[rng.integers(len(x))]]
    for _ in range(1, k):
        d = 1 - np.max(x @ np.array(c).T, axis=1)
        p = np.clip(d, 0, None) ** 2
        c.append(x[rng.choice(len(x), p=p / p.sum())])
    c = np.array(c)
    lab = np.zeros(len(x), dtype=int)
    for _ in range(iters):
        new = np.argmax(x @ c.T, axis=1)
        if (new == lab).all():
            break
        lab = new
        for j in range(k):
            m = x[lab == j]
            if len(m):
                v = m.sum(0)
                c[j] = v / np.linalg.norm(v)
    return lab


TAXONOMY_PROMPT = """# 任务：给论文聚类命名，并整理成两级主题树

输入是 {n} 个论文簇（embedding 聚类得到），分在几个 Markdown 文件里。每个簇给出：簇号、论文数、最常见的 arXiv 分类、OpenAlex 主题，以及最有代表性的论文标题（按 HN 上提到的人数排）。
这些论文都是 Hacker News 上被不同的人反复提到的 arXiv 论文，读者是想系统学习的工程师。

请做两件事：
1. 定义 8–14 个一级"领域"（area），覆盖全部簇。名字要让工程师一眼看懂，例如"大模型与生成式 AI""编程语言与形式化方法""物理与宇宙学"。
2. 给每个簇起一个二级"类目"名（中文 ≤ 12 字，英文 ≤ 5 词），并归到一个领域。
   - 两个簇讲的是同一件事，就给它们**相同的类目 id**（会合并）；最终类目总数 60–150 个。
   - 簇里混了几类东西时，按多数论文命名；名字要具体（"扩散模型与图像生成"好过"生成模型"）。

全部读完后，用 Write 工具写一个 JSON 文件到 {out}，格式：
```
{{"areas": [{{"id": "llm", "name_zh": "大模型与生成式 AI", "name_en": "LLMs & Generative AI"}}, ...],
 "clusters": [{{"cluster": 0, "category_id": "diffusion-image-gen", "name_zh": "扩散模型与图像生成", "name_en": "Diffusion & image generation", "area": "llm"}}, ...]}}
```
- `areas[].id`、`category_id` 用小写英文和连字符。
- `clusters` 必须包含全部 {n} 个簇号，每个一行。
只写这一个文件，不要运行命令。写完后回复一行：领域数、类目数。
"""


def cmd_cluster(args) -> None:
    ids, x = load_emb()
    meta = load_meta()
    oa = load_openalex()
    people = {r[0]: r[1] for r in duckdb.sql(f"SELECT arxiv, people FROM '{OUT / 'candidates.parquet'}'").fetchall()}
    lab = spherical_kmeans(x, args.k)
    # 太小的簇并到最近的大簇
    for _ in range(3):
        sizes = Counter(lab.tolist())
        small = [j for j, n in sizes.items() if n < args.min_size]
        if not small:
            break
        big = [j for j in sizes if j not in small]
        cent = {j: x[lab == j].mean(0) for j in big}
        cm = np.array([cent[j] / np.linalg.norm(cent[j]) for j in big])
        for i in np.where(np.isin(lab, small))[0]:
            lab[i] = big[int(np.argmax(cm @ x[i]))]
    # 重新编号 0..K-1（按大小）
    order = [j for j, _ in Counter(lab.tolist()).most_common()]
    remap = {j: n for n, j in enumerate(order)}
    lab = np.array([remap[j] for j in lab])
    clusters = defaultdict(list)
    for a, j in zip(ids, lab):
        clusters[int(j)].append(a)
    (OUT / "clusters.json").write_text(json.dumps({a: int(j) for a, j in zip(ids, lab)}))
    items = []
    for j in sorted(clusters):
        ms = sorted(clusters[j], key=lambda a: -people.get(a, 0))
        cats = Counter(meta[a].get("primary_category") for a in ms)
        tops = Counter((oa.get(a, {}).get("primary_topic") or {}).get("name") for a in ms if oa.get(a, {}).get("primary_topic"))
        items.append({"id": j, "n_papers": len(ms),
                      "arxiv_categories": ", ".join(f"{c} ({n})" for c, n in cats.most_common(4)),
                      "openalex_topics": ", ".join(f"{t} ({n})" for t, n in tops.most_common(4)),
                      "titles": "\n".join(f"- {meta[a]['title']}" for a in ms[:14])})
    out = llm_batch.task_dir("taxonomy") / "out" / "taxonomy.json"
    llm_batch.prepare("taxonomy", items, TAXONOMY_PROMPT.format(n=len(items), out=out), batch_size=1000,
                      max_chars=55000, out_fields=["areas", "clusters"], overwrite=True)
    sizes = sorted((len(v) for v in clusters.values()), reverse=True)
    print(f"cluster: {len(ids):,} papers → {len(clusters)} clusters (sizes {sizes[:5]} … {sizes[-5:]}), "
          f"{len(list((llm_batch.task_dir('taxonomy') / 'in').glob('*.md')))} input files")


def cmd_taxonomy(_args) -> None:
    res = json.loads((llm_batch.task_dir("taxonomy") / "out" / "taxonomy.json").read_text())
    cl = json.loads((OUT / "clusters.json").read_text())
    by_cluster = {int(c["cluster"]): c for c in res["clusters"]}
    missing = sorted(set(cl.values()) - set(by_cluster))
    if missing:
        raise SystemExit(f"taxonomy: 子 agent 漏了这些簇：{missing}")
    areas = {a["id"]: a for a in res["areas"]}
    topic_of = {a: by_cluster[j]["category_id"] for a, j in cl.items()}
    counts = Counter(topic_of.values())
    cats: dict[str, dict] = {}
    for c in res["clusters"]:
        cats.setdefault(c["category_id"], {"id": c["category_id"], "name_zh": c["name_zh"], "name_en": c["name_en"],
                                           "area": c["area"], "count": counts[c["category_id"]]})
    bad = {c["area"] for c in cats.values()} - set(areas)
    if bad:
        raise SystemExit(f"taxonomy: 类目引用了不存在的领域 {bad}")
    tax = {"areas": [{**a, "count": sum(c["count"] for c in cats.values() if c["area"] == a["id"]),
                      "categories": sorted([{k: c[k] for k in ("id", "name_zh", "name_en", "count")}
                                            for c in cats.values() if c["area"] == a["id"]], key=lambda c: -c["count"])}
                     for a in res["areas"]],
           "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "method": "bge-small + spherical k-means + Sonnet naming"}
    tax["areas"].sort(key=lambda a: -a["count"])
    (PATHS.build / "taxonomy.json").write_text(json.dumps(tax, ensure_ascii=False, indent=1))
    (OUT / "topics.json").write_text(json.dumps({a: {"topic": t, "area": cats[t]["area"]} for a, t in topic_of.items()}))
    print(f"taxonomy: {len(areas)} areas, {len(cats)} categories, {len(topic_of):,} papers")


def nearest_topics(ids: list[str], x: np.ndarray, topics: dict[str, dict]) -> dict[str, dict]:
    """还没有类目的论文归到最近的已有类目：类目中心 = 已归类论文 embedding 的均值，比余弦。返回新增的 {arxiv: {topic, area}}。"""
    idx = {a: i for i, a in enumerate(ids)}
    members: dict[str, list[int]] = defaultdict(list)
    for a in ids:
        if a in topics:
            members[topics[a]["topic"]].append(idx[a])
    names = sorted(members)
    cent = np.stack([x[members[t]].mean(0) for t in names])
    cent /= np.linalg.norm(cent, axis=1, keepdims=True)
    area = {v["topic"]: v["area"] for v in topics.values()}
    out = {}
    for a in ids:
        if a not in topics:
            t = names[int(np.argmax(cent @ x[idx[a]]))]
            out[a] = {"topic": t, "area": area[t]}
    return out


def cmd_assign_topics(_args) -> None:
    """月度更新（D47）：新进目录的论文归到最近的已有类目，不重新聚类、不改主题树；再按 topics.json 重算 taxonomy.json 的篇数（顺序不动）。"""
    ids, x = load_emb()
    tp = OUT / "topics.json"
    topics = json.loads(tp.read_text())
    new = nearest_topics(ids, x, topics)
    topics.update(new)
    tp.write_text(json.dumps(topics))
    tax_p = PATHS.build / "taxonomy.json"
    tax = json.loads(tax_p.read_text())
    counts = Counter(topics[a]["topic"] for a in ids if a in topics)
    for area in tax["areas"]:
        for c in area.get("categories", []):
            c["count"] = counts.get(c["id"], 0)
        area["count"] = sum(c["count"] for c in area.get("categories", []))
    tax["recounted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tax_p.write_text(json.dumps(tax, ensure_ascii=False, indent=1))
    top = Counter(v["topic"] for v in new.values()).most_common(5)
    print(f"assign-topics: {len(new)} 篇新论文归入已有类目（最多的：{top}），类目篇数已重算")


# ---------------------------------------------------------------- 相关论文
def cmd_related(args) -> None:
    ids, x = load_emb()
    idx = {a: i for i, a in enumerate(ids)}
    db = _db()
    rows = db.execute(f"""SELECT m.arxiv, m."by" FROM m JOIN '{OUT / 'candidates.parquet'}' c USING (arxiv)
                          WHERE {COUNTED}""").fetchall()
    people: dict[str, set] = defaultdict(set)
    for a, by in rows:
        people[a].add(by)
    by_person: dict[str, set] = defaultdict(set)
    for a, ps in people.items():
        for p in ps:
            by_person[p].add(a)
    oa = load_openalex()
    w2a = {}
    for a, r in oa.items():
        for w in (r.get("openalex_id"), r.get("openalex_published_id")):
            if w:
                w2a[w] = a
    cites: dict[str, set] = defaultdict(set)  # 无向：a 引用 b 或 b 引用 a
    for a, r in oa.items():
        for w in r.get("references") or []:
            b = w2a.get(w)
            if b and b != a:
                cites[a].add(b)
                cites[b].add(a)
    sims = x @ x.T
    out = []
    for a, i in idx.items():
        co = Counter()
        for p in people.get(a, ()):
            if len(by_person[p]) > 200:  # 提过几百篇的人不算"共同推荐"信号
                continue
            for b in by_person[p]:
                if b != a:
                    co[b] += 1
        cand = set(np.argsort(-sims[i])[1:40].tolist())
        cand |= {idx[b] for b, n in co.items() if n >= 2 and b in idx}
        cand |= {idx[b] for b in cites.get(a, ()) if b in idx}
        scored = []
        for j in cand:
            b = ids[j]
            s = float(sims[i, j])
            score = s + 0.04 * min(co.get(b, 0), 5) + (0.08 if b in cites.get(a, ()) else 0)
            if s >= args.min_sim or co.get(b, 0) >= 2 or b in cites.get(a, ()):
                scored.append((score, b, s))
        scored.sort(reverse=True)
        out.append({"item_id": a, "related": [{"id": b, "co_people": co.get(b, 0), "sim": round(s, 3),
                                               "cites": b in cites.get(a, ())} for _, b, s in scored[: args.k]]})
    with open(PATHS.build / "related.jsonl", "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_rel = [len(r["related"]) for r in out]
    print(f"related: {len(out):,} papers, avg {np.mean(n_rel):.1f} related, "
          f"citation pairs {sum(len(v) for v in cites.values()) // 2:,} → {PATHS.build / 'related.jsonl'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("embed")
    s.add_argument("--full", action="store_true", help="全部重算（默认只算新进的）")
    s = sub.add_parser("cluster")
    s.add_argument("--k", type=int, default=110)
    s.add_argument("--min-size", type=int, default=10)
    sub.add_parser("taxonomy")
    sub.add_parser("assign-topics")
    s = sub.add_parser("related")
    s.add_argument("--k", type=int, default=8)
    s.add_argument("--min-sim", type=float, default=0.72)
    args = ap.parse_args(argv)
    {"embed": cmd_embed, "cluster": cmd_cluster, "taxonomy": cmd_taxonomy, "assign-topics": cmd_assign_topics,
     "related": cmd_related}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
