"use client";

import type MiniSearch from "minisearch";
import { useEffect, useMemo, useRef, useState } from "react";
import { newEngine, runSearch, type Hit } from "@/lib/search-engine";
import { Cover } from "./Cover";
import { PaperLink } from "./PaperLink";
import { withBase } from "@/lib/site";

export type { Hit };

const FIELD_NAMES: Record<string, string> = {
  ai: "AI 与机器学习", cs: "计算机科学", math: "数学与统计", physics: "物理", bio: "生物", econ: "经济与金融", other: "其他", book: "开源书",
};

// 索引只下载、建一次（离开搜索页再回来不重复）；失败了下次再试
let enginePromise: Promise<{ engine: MiniSearch<Hit>; total: number }> | null = null;
function getEngine(indexUrl: string) {
  enginePromise ??= (async () => {
    const r = await fetch(indexUrl);
    if (!r.ok) throw new Error(`搜索索引 ${r.status}`);
    const docs: Hit[] = await r.json();
    const engine = newEngine();
    // 分块建索引，每块之间让出主线程，不出现长任务
    await engine.addAllAsync(docs, { chunkSize: 50 });
    return { engine, total: docs.length };
  })().catch((e) => {
    enginePromise = null;
    throw e;
  });
  return enginePromise;
}

/**
 * 搜索框 + 结果。首屏是服务端用同一套引擎算好的结果（page.tsx 传进来的 initialHits），改了搜索词之后才换成前端即时搜索。
 * 索引（约 1.5 MB）在浏览器空闲时才下载（开始输入时立刻下载）；不改搜索词就一直用服务端结果，
 * 索引建好时列表不会整块换掉（以前 CLS 0.6、主线程卡 1 秒）。
 * 公开站（静态导出）没有服务端结果：queryFromUrl 时打开页面先读地址栏的 ?q=，有搜索词就立刻下载索引；索引是静态文件 indexUrl。
 */
export function SearchClient({ initialQuery, initialHits, initialTotal, areaNames, indexUrl, queryFromUrl = false }: {
  initialQuery: string; initialHits: Hit[]; initialTotal: number; areaNames: Record<string, string>; indexUrl: string; queryFromUrl?: boolean;
}) {
  const [q, setQ] = useState(initialQuery);
  const [engine, setEngine] = useState<MiniSearch<Hit> | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [field, setField] = useState<string>("");
  const input = useRef<HTMLInputElement>(null);

  function load() {
    getEngine(indexUrl).then(
      (r) => {
        setEngine(r.engine);
        setTotal(r.total);
      },
      () => setTotal(0),
    );
  }

  useEffect(() => {
    if (!queryFromUrl) return;
    const fromUrl = new URLSearchParams(window.location.search).get("q")?.trim();
    // 地址栏是外部状态：只在打开页面时读一次，之后由输入框接管（下面的 effect 再写回地址栏）
    if (fromUrl) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setQ(fromUrl);
      load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (h: number) => void };
    if (w.requestIdleCallback) {
      const h = w.requestIdleCallback(load, { timeout: 3000 });
      return () => w.cancelIdleCallback?.(h);
    }
    const t = setTimeout(load, 1500);
    return () => clearTimeout(t);
  }, []);

  const touched = q !== initialQuery;
  const { hits, total: matched } = useMemo(() => {
    if (!q.trim()) return { hits: [] as Hit[], total: 0 };
    // 没改搜索词：一直用服务端结果（同一套引擎，排序一致）；改了但索引还没好：先空着，状态栏显示“加载索引…”
    if (!touched) {
      if (!field) return { hits: initialHits, total: initialTotal };
      const f = initialHits.filter((h) => h.f === field);
      return { hits: f, total: f.length };
    }
    if (!engine) return { hits: [] as Hit[], total: 0 };
    return runSearch(engine, q, field);
  }, [engine, q, field, initialHits, initialTotal, touched]);

  useEffect(() => {
    const u = new URL(window.location.href);
    if (q) u.searchParams.set("q", q);
    else u.searchParams.delete("q");
    window.history.replaceState(null, "", u.toString());
  }, [q]);

  const fields = Array.from(new Set(hits.map((h) => h.f)));
  return (
    <div>
      <input ref={input} data-search-input autoFocus value={q} onChange={(e) => { setQ(e.target.value); if (!engine) load(); }}
        placeholder="标题、作者、主题，中英文都行" aria-label="搜索论文" type="search"
        style={{ width: "100%", boxSizing: "border-box", fontSize: 22, padding: "16px 18px", fontFamily: "var(--f-display)", border: 0,
          borderRadius: 8, background: "var(--bg2)", color: "var(--ink)", outline: "none" }} />
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginTop: 14, fontSize: 13 }}>
        <span className="faint">
          {q.trim() && (!touched || engine)
            ? matched > hits.length ? `${matched.toLocaleString()} 条结果，显示前 ${hits.length} 条` : `${hits.length} 条结果`
            : total ? `${total.toLocaleString()} 篇可搜` : "加载索引…"}
        </span>
        <span style={{ flex: 1 }} />
        <div className="chips">
          <a href="#" role="button" aria-current={field === ""} onClick={(e) => { e.preventDefault(); setField(""); }}>全部</a>
          {fields.map((f) => (
            <a key={f} href="#" role="button" aria-current={field === f} onClick={(e) => { e.preventDefault(); setField(f); }}>{FIELD_NAMES[f] ?? f}</a>
          ))}
        </div>
      </div>
      <ol className="entries entries--list" style={{ marginTop: 18 }}>
        {hits.map((h) => {
          // 开源书（Phase 5）：id 是 "book:<slug>"，链到 /books/<slug>/，第一行写“开源书 · 分类”
          const book = h.id.startsWith("book:");
          const body = (
            <>
              <Cover paper={{ id: h.id, area: h.r || null, title: h.t, titleZh: h.z || null, year: h.y }} size="list" />
              <span className="entry-text">
                <span className="faint" style={{ fontSize: 12 }}>
                  {book ? <>开源书{h.r && areaNames[h.r] ? ` · ${areaNames[h.r]}` : ""}</>
                    : <>{h.y}{h.r && areaNames[h.r] ? ` · ${areaNames[h.r]}` : ""} · <span className="nowrap">arXiv:{h.id.replace(/^arxiv:/, "")}</span></>}
                </span>
                <span className="entry-title">{h.t}</span>
                {h.z && <span className="entry-zh">{h.z}</span>}
                {h.o && <span style={{ fontSize: 14, lineHeight: 1.6, color: "var(--ink2)" }}>{h.o}</span>}
                <span className="faint" style={{ fontSize: 13 }}>
                  {h.c && h.h ? "被推荐" : "被提及"} · {h.p} 人{h.c ? "" : " · 候选"} · {h.a}
                </span>
              </span>
            </>
          );
          return (
            <li key={h.id}>
              {book ? <a href={withBase(`/books/${h.id.slice(5)}/`)} data-nav-item className="entry">{body}</a>
                : <PaperLink id={h.id} data-nav-item className="entry">{body}</PaperLink>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
