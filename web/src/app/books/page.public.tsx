import Link from "next/link";
import { Cover } from "@/components/Cover";
import { Footer, Header } from "@/components/Header";
import { Shelf } from "@/components/Shelf";
import { allBooks, bookCover, bookMentions, bookSubjects, booksMeta, cleanBookQuote, subjectNames, type Book } from "@/lib/books";
import { ym } from "@/lib/labels";
import { PUBLIC_SITE_URL, withBase } from "@/lib/site";

const SHARE_TITLE = "开源书 · HackerShelf";
const DESCRIPTION = "Hacker News 上被不同的人在不同月份反复推荐的开源书：只收开放许可或官方免费的完整版，每本配中文导读和读法。";
const SHARE_IMAGE = `${PUBLIC_SITE_URL}/og.png`;

// 分享卡片：og 和 twitter 用同一套标题、说明和图（twitter 不写的话会沿用根布局里论文那套）
export const metadata = {
  title: "开源书",
  description: DESCRIPTION,
  openGraph: { type: "website", siteName: "HackerShelf", locale: "zh_CN", url: `${PUBLIC_SITE_URL}/books/`, title: SHARE_TITLE,
    description: DESCRIPTION, images: [{ url: SHARE_IMAGE, width: 1200, height: 630 }] },
  twitter: { card: "summary_large_image", title: SHARE_TITLE, description: DESCRIPTION, images: [SHARE_IMAGE] },
};

const bookHref = (b: Book) => `/books/${b.slug}/`;
const label = (b: Book, rank = true) => (
  <>
    {rank && <span className="shelf-rank">No.{b.rank}</span>}
    <span className="shelf-note">{b.hasPositive ? "被推荐" : "被提及"} · {b.people} 人{b.unfinished ? " · 未写完" : ""}</span>
  </>
);

/**
 * 开源书书架（Phase 5，D48）：只收开放许可或作者、出版社官方免费放出的完整版，链接到官方免费版，不托管全文。
 * 版式同首页：开场一句话 → No.1 聚光 → No.2–7 一排 → 按书架分类，每类一面书架（分数从高到低）。
 */
export default function BooksPage() {
  const books = allBooks();
  const meta = booksMeta();
  const names = subjectNames();
  const areaNames = Object.fromEntries(Object.entries(names).map(([k, v]) => [`b-${k}`, v]));
  const subjects = bookSubjects();
  const [no1, ...rest] = books;
  const quote = no1 ? bookMentions(no1.id).find((m) => m.source === "comment_link" && m.quote && m.quote.length >= 40) : null;
  const qText = quote?.quote && no1 ? cleanBookQuote(quote.quote, no1.title) : "";

  return (
    <>
      <Header active="books" />
      <main>
        <section className="wrap" style={{ paddingTop: 56, display: "flex", flexDirection: "column", gap: 40 }}>
          <p className="home-lede">
            Hacker News 二十年里，被不同的人在不同月份反复推荐的开源书。只收开放许可或作者、出版社官方免费放出的完整版，每本配中文导读和读法。链接指向官方免费版，个别原站失效的会注明。
            <Link href="/about#books" className="faint home-lede-more">怎么选的</Link>
          </p>
          <div className="home-title">
            <h1>开源书</h1>
            <span>
              {books.length} 本 · 按有推荐的不同月份数排序 · <span className="nowrap">截至 {meta.cutoff}</span>
            </span>
          </div>

          {no1 && (
            <div className="spot">
              <a href={withBase(bookHref(no1))} className="spot-cover" tabIndex={-1} aria-hidden="true">
                <Cover paper={bookCover(no1)} areaZh={no1.subject ? names[no1.subject] : null} size="spot" />
              </a>
              <div className="spot-text">
                <div className="eyebrow acct" style={{ fontSize: 13 }}>No.1 · {no1.subject ? names[no1.subject] : "开源书"} · {no1.licenseLabel}</div>
                <h2><a href={withBase(bookHref(no1))} data-nav-item>{no1.title}</a></h2>
                <div className="spot-zh">{no1.titleZh}{no1.titleZh && no1.authors ? " · " : ""}{no1.authorShort}</div>
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
                  <span className={no1.hasPositive ? "pill pill-pos" : "pill"}>{no1.hasPositive ? "被推荐" : "被提及"} · {no1.people} 人</span>
                  <span style={{ fontSize: 14, color: "var(--ink2)" }}>{no1.months} 个月 · {no1.threads} 个讨论串</span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 8 }}>
                  <a href={no1.url} className="btn btn-primary" target="_blank" rel="noreferrer">免费阅读 ↗</a>
                  <a href={withBase(bookHref(no1))} className="btn">导读和 HN 书评</a>
                </div>
              </div>
            </div>
          )}

          <div style={{ marginTop: 24 }}>
            <Shelf row areaNames={areaNames} items={rest.slice(0, 6).map((b) => ({ paper: bookCover(b), href: bookHref(b), label: label(b) }))} />
          </div>

          <nav aria-label="书架分类" className="chips" style={{ marginTop: 8 }}>
            {subjects.map((s) => (
              <a key={s.id} href={`#${s.id}`} style={{ fontSize: 14, padding: "8px 14px" }}>
                {s.name} <span className="faint">{s.n}</span>
              </a>
            ))}
          </nav>
        </section>

        {subjects.map((s) => {
          const items = books.filter((b) => b.subject === s.id);
          return (
            <section key={s.id} id={s.id} className="wrap section" style={{ scrollMarginTop: 20 }}>
              <div className="section-head">
                <h2>{s.name}</h2>
                <span className="note">{items.length} 本</span>
              </div>
              <Shelf seven size="area" areaNames={areaNames} items={items.map((b) => ({ paper: bookCover(b), href: bookHref(b), label: label(b) }))} />
            </section>
          );
        })}

        <section className="wrap section">
          <p className="faint" style={{ margin: 0, fontSize: 14, lineHeight: 1.8, maxWidth: 760 }}>
            书单来自 <a href="https://github.com/EbookFoundation/free-programming-books" target="_blank" rel="noreferrer">free-programming-books</a>（CC BY 4.0）加少量手选；
            许可证逐本到官方页面核实过。封面按书名和作者生成，不是书的真实封面。
          </p>
        </section>
      </main>
      <Footer cutoff={meta.cutoff} books />
    </>
  );
}
