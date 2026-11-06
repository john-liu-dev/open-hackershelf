"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Cover } from "@/components/Cover";
import { PaperLink } from "@/components/PaperLink";
import { withBase } from "@/lib/site";

/** fresh.json（公开仓库的 GitHub Actions 每天写一次；格式见 docs/DATA.md 第 4.1 节，脚本是 deploy/public/scripts/fresh.mjs）。 */
export type FreshJson = {
  v: 1;
  generatedAt: string;
  categories: string[];
  catDay: string | null;
  sources: Record<"hf" | "hn" | "cat", { ok: boolean; n: number; stale?: boolean; error?: string }>;
  sections: { hf: string[]; hn: string[]; cat: Record<string, string[]> };
  items: Record<string, FreshItem>;
};
export type FreshItem = {
  title: string;
  authors: string[];
  nAuthors: number;
  abstract: string | null;
  categories: string[];
  year: number | null;
  /** 在书架目录里：链到详情页，显示中文标题和一句话 */
  inCatalog?: { titleZh: string | null; oneliner: string | null };
  hf?: { upvotes: number; comments: number; day: string };
  hn?: { points: number; comments: number; itemId: number | null; mentions: number };
  cat?: { announce: string; follow: string };
};

const when = (iso: string) =>
  new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })
    .format(new Date(iso));

function FreshRow({ id, x }: { id: string; x: FreshItem }) {
  const inside = !!x.inCatalog;
  const abs = `https://arxiv.org/abs/${id}`;
  const authors = x.nAuthors > 3 ? `${x.authors.slice(0, 3).join(", ")} 等` : x.authors.join(", ");
  const title = inside ? (
    <PaperLink id={id} className="entry-title" data-nav-item>{x.title}</PaperLink>
  ) : (
    <a className="entry-title" href={abs} target="_blank" rel="noreferrer" data-nav-item>{x.title}</a>
  );
  return (
    <article className="entry fresh-entry">
      {inside ? (
        <PaperLink id={id} tabIndex={-1} aria-hidden="true"><Cover paper={{ id: `arxiv:${id}`, area: null, title: x.title, titleZh: x.inCatalog?.titleZh ?? null, year: x.year }} size="list" /></PaperLink>
      ) : (
        <a href={abs} tabIndex={-1} aria-hidden="true" target="_blank" rel="noreferrer"><Cover paper={{ id: `arxiv:${id}`, area: null, title: x.title, titleZh: null, year: x.year }} size="list" /></a>
      )}
      <div className="entry-text">
        <span className="faint" style={{ fontSize: 12 }}>arXiv {id}{x.categories[0] ? ` · ${x.categories[0]}` : ""}</span>
        {title}
        {x.inCatalog?.titleZh && <span className="entry-zh">{x.inCatalog.titleZh}</span>}
        {authors && <span className="faint" style={{ fontSize: 13 }}>{authors}</span>}
        <span className="chips fresh-chips">
          {x.hf && <a className="pill pill-sm" href={`https://huggingface.co/papers/${id}`} target="_blank" rel="noreferrer">▲ {x.hf.upvotes} · Hugging Face ↗</a>}
          {x.hn?.itemId && (
            <a className="pill pill-sm" href={`https://news.ycombinator.com/item?id=${x.hn.itemId}`} target="_blank" rel="noreferrer">
              {x.hn.points ? `HN ${x.hn.points} 分 · ${x.hn.comments} 评论` : `HN 评论里提到 ${x.hn.mentions} 次`} ↗
            </a>
          )}
          {x.cat && <span className="pill pill-sm">{x.cat.follow}{x.cat.announce === "cross" ? " · 交叉列出" : ""}</span>}
          {inside && <PaperLink id={id} className="pill pill-sm pill-pos">已在书架</PaperLink>}
        </span>
        {inside && x.inCatalog?.oneliner ? (
          <span style={{ fontSize: 14, lineHeight: 1.6, color: "var(--ink2)" }}>{x.inCatalog.oneliner}</span>
        ) : x.abstract ? (
          <details className="fresh-abs">
            <summary><span className="abs-text" lang="en">{x.abstract}</span></summary>
          </details>
        ) : null}
        {!inside && <span className="fresh-actions"><a className="faint" href={abs} target="_blank" rel="noreferrer">arXiv 摘要页 ↗</a></span>}
      </div>
    </article>
  );
}

let dataPromise: Promise<FreshJson> | null = null;
function loadFresh(): Promise<FreshJson> {
  // 默认缓存模式：能接上页面里的 preload；GitHub Pages 的缓存是 10 分钟，每天更新一次够用
  dataPromise ??= fetch(withBase("/fresh.json"))
    .then((r) => {
      if (!r.ok) throw new Error(`fresh.json ${r.status}`);
      return r.json() as Promise<FreshJson>;
    })
    .catch((e) => {
      dataPromise = null;
      throw e;
    });
  return dataPromise;
}

/** 新鲜书架（公开站）：运行时读 fresh.json。总览每栏只列前几篇，“看全部”进单栏：?show=hf / ?show=hn / ?show=<分类>。 */
export function FreshClient() {
  const show = useSearchParams().get("show");
  const [data, setData] = useState<FreshJson | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    loadFresh().then(
      (d) => live && setData(d),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, []);

  if (failed) return <p className="muted" style={{ marginTop: 32 }}>今天的新鲜书架没加载出来，稍后刷新再试。</p>;
  if (!data) return <p className="faint" style={{ marginTop: 32 }} aria-live="polite">加载中…</p>;

  const pick = (ids: string[]) => ids.filter((i) => data.items[i]);
  const stale = (k: "hf" | "hn" | "cat") => (data.sources[k]?.stale ? " · 今天没抓到，显示的是上一次的" : "");
  const sections: { key: string; title: string; note: ReactNode; ids: string[]; first: number }[] = [
    { key: "hf", title: "Hugging Face 热门", note: `最近三天的每日论文，按点赞排${stale("hf")}`, ids: pick(data.sections.hf), first: 6 },
    { key: "hn", title: "HN 上在讨论", note: `最近一天半里链接到 arXiv 的帖子，和评论里提到的论文${stale("hn")}`, ids: pick(data.sections.hn), first: 6 },
    ...data.categories.map((c) => ({
      key: c, title: c, note: `${data.catDay ?? ""} 公布的新论文${stale("cat")}`, ids: pick(data.sections.cat[c] ?? []), first: 3,
    })),
  ];
  const one = show ? sections.find((s) => s.key === show) : null;
  const row = (id: string) => <li key={id}><FreshRow id={id} x={data.items[id]} /></li>;
  const head = (
    <span>
      每天早上更新 · 上次 <span className="nowrap">{when(data.generatedAt)}</span>
      {" · "}只有来源给的标题和摘要；已在书架上的论文链到详情页
    </span>
  );

  if (one) {
    return (
      <>
        <div className="home-title" style={{ marginTop: 0 }}>{head}</div>
        <section className="section" style={{ paddingTop: 40 }}>
          <div className="section-head">
            <h2><Link href="/fresh">新鲜</Link> · {one.title} · {one.ids.length} 篇</h2>
            <span className="note">{one.note}</span>
          </div>
          <ol className="entries entries--list">{one.ids.map(row)}</ol>
        </section>
      </>
    );
  }
  const cats = sections.slice(2).filter((s) => s.ids.length);
  return (
    <>
      <div className="home-title" style={{ marginTop: 0 }}>{head}</div>
      {!sections.some((s) => s.ids.length) && <p className="muted" style={{ marginTop: 32 }}>今天还没有数据。</p>}
      {sections.slice(0, 2).filter((s) => s.ids.length).map((s) => (
        <section key={s.key} className="section" style={{ paddingTop: 48 }}>
          <div className="section-head">
            <h2>{s.title}</h2>
            <span className="note">{s.note}</span>
          </div>
          <ol className="entries entries--list">{s.ids.slice(0, s.first).map(row)}</ol>
          {s.ids.length > s.first && <Link className="fresh-all" href={`/fresh?show=${s.key}`}>看全部 {s.ids.length} 篇 →</Link>}
        </section>
      ))}
      {cats.length > 0 && (
        <section className="section" style={{ paddingTop: 48 }}>
          <div className="section-head">
            <h2>关注的分类</h2>
            <span className="note">{data.catDay} 公布的新论文{stale("cat")}</span>
          </div>
          {cats.map((s) => (
            <div key={s.key} className="fresh-cat">
              <h3 className="eyebrow">{s.title} · {s.ids.length} 篇</h3>
              <ol className="entries entries--list">{s.ids.slice(0, s.first).map(row)}</ol>
              {s.ids.length > s.first && <Link className="fresh-all" href={`/fresh?show=${encodeURIComponent(s.key)}`}>看全部 {s.ids.length} 篇 →</Link>}
            </div>
          ))}
        </section>
      )}
    </>
  );
}
