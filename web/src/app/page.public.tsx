import Link from "next/link";
import { Cover } from "@/components/Cover";
import { Entry } from "@/components/Entry";
import { Footer, Header } from "@/components/Header";
import { PaperLink } from "@/components/PaperLink";
import { TopShelf } from "@/components/public/TopShelf";
import { Shelf } from "@/components/Shelf";
import { allBooks, bookCover, subjectNames } from "@/lib/books";
import { areaNames, areaShelf, bestQuote, buildMeta, shelf, taxonomy } from "@/lib/catalog";
import { cleanQuote, recLabel, ym } from "@/lib/labels";
import { topShelfBooks } from "@/lib/topshelf";

/** 公开站首页（D46，和旧站同一套版式）：没有“放进书架”，“开始阅读”去 arXiv。
 * 首页（B1）：一排真书（长青榜前 N 篇）和开场一句话 → 长青榜 → 聚光 No.1 → 书架 No.2–7 → 开源书一排（Phase 5，D48）→ 篇数最多的两个领域
 * → 最近被提起 → 隐藏宝藏 → 全部领域。 */
export default function Home() {
  const meta = buildMeta() as { counts?: { papers_core?: number; papers_cand?: number }; hn_cutoff?: string };
  const cutoff = String(meta.hn_cutoff ?? "").slice(0, 10);
  const names = areaNames();
  const top = shelf("evergreen", 7);
  const [no1, ...rest] = top;
  const quote = no1 ? bestQuote(no1.id) : null;
  const qText = quote?.quote && no1 ? cleanQuote(quote.quote, no1.title) : "";
  const lab1 = no1 ? recLabel(no1) : null;
  const areas = taxonomy()
    .map((a) => ({ ...a, nCore: a.topics.reduce((n, t) => n + t.nCore, 0) }))
    .sort((a, b) => b.nCore - a.nCore);
  const recent = shelf("recent", 6);
  const gems = shelf("gems", 7);
  const recentFrom = recent.length ? recent[recent.length - 1].lastMention : cutoff;
  const books = allBooks();
  // 一排真书（2026-11-06）：长青榜前 72 篇，构建时算好；浏览器按宽度取前 N 篇
  const shelfBooks = topShelfBooks();
  const nCore = meta.counts?.papers_core ?? 0;
  const bookAreas = Object.fromEntries(Object.entries(subjectNames()).map(([k, v]) => [`b-${k}`, v]));

  return (
    <>
      <Header active="papers" />
      <main>
        <section className="wrap" style={{ paddingTop: 8, display: "flex", flexDirection: "column", gap: 40 }}>
          {/* 一排真书 + 开场一句话（2026-11-06，替换原来页头下面的空白；1,800 根书脊的版本在 Skyline.tsx，留给关于页） */}
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <TopShelf books={shelfBooks} />
            <p className="home-lede">
              Hacker News 二十年里，被不同的人在不同月份反复推荐的 {nCore.toLocaleString()} 篇论文。
              <Link href="/about" className="faint home-lede-more">怎么选的 →</Link>
            </p>
          </div>
          <div className="home-title">
            <h1>长青榜</h1>
            <span>
              主书架 {meta.counts?.papers_core?.toLocaleString()} 篇 · 按有推荐的不同月份数排序 · <span className="nowrap">截至 {cutoff}</span>
            </span>
          </div>

          {no1 && lab1 && (
            <div className="spot">
              <PaperLink id={no1.id} className="spot-cover" tabIndex={-1} aria-hidden="true">
                <Cover paper={no1} areaZh={no1.area ? names[no1.area] : null} size="spot" />
              </PaperLink>
              <div className="spot-text">
                <div className="eyebrow acct" style={{ fontSize: 13 }}>No.1 · {no1.area ? names[no1.area] : "论文"} · {no1.year}</div>
                <h2><PaperLink id={no1.id} data-nav-item>{no1.title}</PaperLink></h2>
                <div className="spot-zh">
                  {no1.titleZh}{no1.titleZh && no1.authors[0] ? " · " : ""}{no1.authors.length > 2 ? `${no1.authors[0]} 等` : no1.authors.join("、")}
                </div>
                {no1.card?.oneliner_zh && <p style={{ margin: 0, fontSize: 17, lineHeight: 1.8, color: "var(--ink2)" }}>{no1.card.oneliner_zh}</p>}
                {quote && qText && (
                  <blockquote style={{ margin: "6px 0 0", display: "flex", flexDirection: "column", gap: 8 }}>
                    <div className="spot-quote">“{qText.length > 160 ? `${qText.slice(0, 157)}…` : qText}”</div>
                    <div style={{ fontSize: 13, color: "var(--ink3)" }}>
                      {quote.by} · <span className="nowrap">{ym(quote.time)}</span> ·{" "}
                      <a href={`https://news.ycombinator.com/item?id=${quote.commentId}`} target="_blank" rel="noreferrer">HN 评论 ↗</a>
                    </div>
                  </blockquote>
                )}
                <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "center", marginTop: 4 }}>
                  <span className={lab1.positive ? "pill pill-pos" : "pill"}>{lab1.text}</span>
                  <span style={{ fontSize: 14, color: "var(--ink2)" }}>{no1.activeMonths} 个月 · {no1.threads} 个讨论串</span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 8 }}>
                  <a href={no1.links.abs} className="btn btn-primary" target="_blank" rel="noreferrer">开始阅读 ↗</a>
                  <PaperLink id={no1.id} className="btn">导读和 HN 书评</PaperLink>
                </div>
              </div>
            </div>
          )}

          <div style={{ marginTop: 24 }}>
            <Shelf row areaNames={names} items={rest.map((p, i) => {
              const l = recLabel(p);
              return { paper: p, label: <><span className="shelf-rank">No.{i + 2}</span><span className="shelf-note">{l.positive ? "被推荐" : "被提及"} · {p.people} 人</span></> };
            })} />
          </div>
        </section>

        {!!books.length && (
          <section className="wrap section">
            <div className="section-head">
              <h2>开源书</h2>
              <span className="note">{books.length} 本 · 只收开放许可或官方免费的完整版 · 按有推荐的不同月份数排序</span>
              <Link href="/books" className="more">整面书架 →</Link>
            </div>
            <Shelf seven row size="area" areaNames={bookAreas} items={books.slice(0, 7).map((b) => ({
              paper: bookCover(b), href: `/books/${b.slug}/`,
              label: <span className="shelf-note">{b.hasPositive ? "被推荐" : "被提及"} · {b.people} 人</span>,
            }))} />
          </section>
        )}

        {areas.slice(0, 2).map((a) => (
          <section key={a.id} className="wrap section">
            <div className="section-head">
              <h2>{a.nameZh}</h2>
              <span className="note">主书架 {a.nCore} 篇</span>
              <Link href={`/browse?area=${a.id}`} className="more">整面书架 →</Link>
            </div>
            <Shelf seven row size="area" areaNames={names} items={areaShelf(a.id, 7).map((p) => ({ paper: p }))} />
          </section>
        ))}

        <section className="wrap section">
          <div className="section-head">
            <h2>最近被提起</h2>
            <span className="note">按最近一次在 HN 上被提起排序 · <span className="nowrap">{recentFrom} 至 {cutoff}</span></span>
            <Link href="/browse?sort=recent" className="more">更多 →</Link>
          </div>
          <ul className="entries">
            {recent.map((p) => (
              <li key={p.id}>
                <Entry paper={p} top={<><span className="nowrap">{p.lastMention.slice(5)}</span>{p.area ? ` · ${names[p.area]}` : ""}</>} />
              </li>
            ))}
          </ul>
        </section>

        <section className="wrap section">
          <div className="section-head">
            <h2>隐藏宝藏</h2>
            <span className="note">提的人不多（≤ 5 人），但跨了很多个月</span>
            <Link href="/browse?sort=gems" className="more">更多 →</Link>
          </div>
          <Shelf seven row size="area" areaNames={names} items={gems.map((p) => ({
            paper: p, label: <span className="shelf-note">{p.people} 人 · 跨 {p.activeMonths} 个月</span>,
          }))} />
        </section>

        <section className="wrap section">
          <div className="section-head">
            <h2>全部领域</h2>
            <span className="note">{areas.length} 个领域、{areas.reduce((n, a) => n + a.topics.length, 0)} 个类目</span>
          </div>
          <div className="chips">
            {areas.map((a) => (
              <Link key={a.id} href={`/browse?area=${a.id}`} style={{ fontSize: 14, padding: "8px 14px" }}>
                {a.nameZh} <span className="faint">{a.nCore}</span>
              </Link>
            ))}
          </div>
        </section>
      </main>
      <Footer cutoff={cutoff} />
    </>
  );
}
