import Link from "next/link";
import { notFound } from "next/navigation";
import { Cover } from "@/components/Cover";
import { Footer, Header } from "@/components/Header";
import { Shelf } from "@/components/Shelf";
import { YearBars } from "@/components/YearBars";
import { allBooks, bookCover, bookMentions, booksMeta, cleanBookQuote, getBook, subjectNames, type Book, type BookMention } from "@/lib/books";
import { STANCE_NAMES, stancePill } from "@/lib/labels";
import { PUBLIC_SITE_URL } from "@/lib/site";

type Params = Promise<{ slug: string }>;

/** 公开站：每本上架的开源书一个静态详情页（Phase 5，D48）。 */
export const dynamicParams = false;
export function generateStaticParams() {
  // 静态导出要求至少一条路径：没有书的时候（比如一个月 demo 跳过了开源书）给一个占位，页面里 notFound()
  const books = allBooks();
  return books.length ? books.map((b) => ({ slug: b.slug })) : [{ slug: "_" }];
}

export async function generateMetadata({ params }: { params: Params }) {
  const b = getBook((await params).slug);
  if (!b) return { title: "未找到" };
  const url = `${PUBLIC_SITE_URL}/books/${b.slug}/`;
  const description = b.card?.oneliner_zh ?? b.titleZh ?? undefined;
  // 分享卡片：每本用自己的生成封面（web/scripts/og-images.mjs 生成 og/books/<slug>.jpg）
  const image = `${PUBLIC_SITE_URL}/og/books/${b.slug}.jpg`;
  return {
    title: b.title,
    description,
    openGraph: { type: "article", siteName: "HackerShelf", locale: "zh_CN", url, title: b.title, description,
      images: [{ url: image, width: 1200, height: 630, alt: b.titleZh ?? b.title }] },
    twitter: { card: "summary_large_image", title: b.title, description, images: [image] },
  };
}

const SHOW_REVIEWS = 6;

function reviewText(m: BookMention, title: string): string {
  const raw = m.quote || (m.text ? (m.text.length > 360 ? `${m.text.slice(0, 357)}…` : m.text) : "");
  return cleanBookQuote(raw, title);
}

function Review({ m, title }: { m: BookMention; title: string }) {
  return (
    <article className="review">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <span className={stancePill(m.stance)}>{m.stance ? STANCE_NAMES[m.stance] : "评论"}</span>
        <span style={{ fontSize: 13, color: "var(--ink3)" }}>{m.by} · <span className="nowrap">{m.time.slice(0, 7)}</span></span>
      </div>
      <p className="review-quote">“{reviewText(m, title)}”</p>
      {m.whyZh && <div className="review-why">{m.whyZh}</div>}
      <div className="review-foot">
        <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.storyTitle ?? ""}</span>
        <a href={`https://news.ycombinator.com/item?id=${m.commentId}`} target="_blank" rel="noreferrer" className="acct nowrap">原评论 ↗</a>
      </div>
    </article>
  );
}

/** 许可证一行：开放许可写许可证名（链到核实时看的官方页面）；没有开放许可的写“官方免费在线”。 */
function LicenseLine({ b }: { b: Book }) {
  const what = b.licenseOpen ? `许可证 ${b.licenseLabel}` : b.licenseLabel;
  return (
    <span>
      {b.licenseUrl ? <a href={b.licenseUrl} target="_blank" rel="noreferrer" className="acct">{what}</a> : what}
      {!b.licenseOpen && b.license === "free-online" ? "（版权保留，作者或出版社免费放出）" : ""}
      {b.httpOnly ? " · 官网只有 http" : ""}
    </span>
  );
}

/**
 * 开源书详情（Phase 5，D48）：版式同论文详情页。“免费阅读”去官方免费版；
 * 导读、读法由 Claude 写，HN 原话同论文（推荐在前，每本最多 20 条）；最后是同一面书架的书。
 */
export default async function BookPage({ params }: { params: Params }) {
  const { slug } = await params;
  const book = getBook(slug);
  if (!book) notFound();
  const names = subjectNames();
  const areaNames = Object.fromEntries(Object.entries(names).map(([k, v]) => [`b-${k}`, v]));
  const meta = booksMeta();
  const mentions = bookMentions(book.id);
  const reviews = mentions.filter((m) => m.source === "comment_link");
  const stories = mentions.filter((m) => m.source === "story_url");
  const card = book.card;
  const years = Object.keys(book.byYear).map(Number);
  const firstYear = Math.min(...years);
  const lastYear = Number(meta.cutoff.slice(0, 4)) || Math.max(...years);
  const same = allBooks().filter((b) => b.subject === book.subject && b.id !== book.id).slice(0, 7);
  const subjectName = book.subject ? names[book.subject] : null;

  return (
    <>
      <Header active="books" />
      <main>
        <section className="wrap detail-top" style={{ paddingTop: 48 }}>
          <div className="detail-side">
            <Cover paper={bookCover(book)} areaZh={subjectName} size="detail" />
            <YearBars byYear={book.byYear} from={firstYear} to={lastYear} />
          </div>

          <div className="detail-main">
            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 8px", fontSize: 13, color: "var(--ink3)" }}>
              <Link href="/books" className="acct">开源书</Link>
              {subjectName && <><span>›</span><Link href={`/books#${book.subject}`} className="acct">{subjectName}</Link></>}
              <span>·</span><span className="nowrap">No.{book.rank}</span>
              {!!book.aliases.length && <><span>·</span><span className="nowrap">简称 {book.aliases[0]}</span></>}
            </div>
            <h1>{book.title}</h1>
            {book.titleZh && <div className="detail-zh">{book.titleZh}</div>}
            {book.authors && <div style={{ fontSize: 15, lineHeight: 1.7, color: "var(--ink2)" }}>{book.authors}</div>}
            {card?.oneliner_zh && <p style={{ margin: "6px 0 0", fontSize: 19, lineHeight: 1.7 }}>{card.oneliner_zh}</p>}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 10 }}>
              <a href={book.url} className="btn btn-primary" target="_blank" rel="noreferrer" data-nav-item>免费阅读 ↗</a>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 14px", alignItems: "center", marginTop: 6, fontSize: 14, color: "var(--ink2)" }}>
              <span className={book.hasPositive ? "pill pill-pos" : "pill"}>{book.hasPositive ? "被推荐" : "被提及"} · {book.people} 人</span>
              {book.unfinished && <span className="pill">未写完</span>}
              <span className="nowrap">首次 {book.first} · 最近 {book.last}</span>
              <LicenseLine b={book} />
            </div>
            {book.unfinished && (
              <p className="faint" style={{ margin: 0, fontSize: 14, lineHeight: 1.8 }}>这本书还没写完，官网上能读的是已经写好的部分。</p>
            )}
            {book.note && <p className="faint" style={{ margin: 0, fontSize: 14, lineHeight: 1.8 }}>{book.note}。</p>}
            <div className="stats">
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}><span className="stat-v">{book.people}</span><span className="stat-k">不同的人</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}><span className="stat-v">{book.months}</span><span className="stat-k">活跃月份</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}><span className="stat-v">{book.monthsRec}</span><span className="stat-k">有推荐的月份</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}><span className="stat-v">{book.threads}</span><span className="stat-k">讨论串</span></div>
            </div>
          </div>
        </section>

        <nav aria-label="详情分栏" className="wrap" style={{ paddingTop: 72 }}>
          <div className="tabs">
            <a href="#guide" aria-current="true">导读</a>
            {!!card?.how_to_read?.length && <a href="#how">怎么读</a>}
            <a href="#reviews">HN 书评 {reviews.length}</a>
            {!!same.length && <a href="#related">同一面书架</a>}
          </div>
        </nav>

        <section id="guide" className="wrap" style={{ paddingTop: 44, display: "flex", flexWrap: "wrap", gap: "40px 64px", scrollMarginTop: 20 }}>
          <div style={{ flex: "999 1 560px", minWidth: 0, display: "flex", flexDirection: "column", gap: 28 }}>
            {card?.summary_zh && <p className="prose-zh">{card.summary_zh}</p>}
            {card?.why_hn && (
              <div className="callout">
                <div className="eyebrow acct">HN 为什么推荐它</div>
                <p className="t-zh" style={{ margin: 0, fontSize: 19, lineHeight: 1.9 }}>{card.why_hn}</p>
              </div>
            )}
          </div>
          {card && (
            <div style={{ flex: "1 1 320px", minWidth: 0, display: "flex", flexDirection: "column", gap: 22 }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {card.difficulty && <span className="tag">难度 {card.difficulty} / 5</span>}
                {card.reading_hours && <span className="tag">约 {card.reading_hours} 小时</span>}
                {book.licenseOpen && <span className="tag">开放许可</span>}
              </div>
              {card.audience_zh && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <div className="eyebrow">适合谁</div>
                  <p className="t-zh" style={{ margin: 0, fontSize: 16, lineHeight: 1.8 }}>{card.audience_zh}</p>
                </div>
              )}
              {!!card.prerequisites?.length && (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <div className="eyebrow" style={{ marginBottom: 6 }}>读之前最好知道</div>
                  {card.prerequisites.map((t, i) => (
                    <div key={t} className="prereq"><span className="t-display acct">{i + 1}</span><span>{t}</span></div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>

        {!!card?.how_to_read?.length && (
          <section id="how" className="wrap section" style={{ scrollMarginTop: 20 }}>
            <div className="section-head">
              <h2>怎么读</h2>
              <span className="note">由 Claude 根据这本书和 HN 上的说法整理，可能有错</span>
            </div>
            <ol className="howto">
              {card.how_to_read.map((t, i) => (
                <li key={t}><span className="howto-n">{i + 1}</span><span className="howto-t">{t}</span></li>
              ))}
            </ol>
          </section>
        )}

        <section id="reviews" className="wrap section" style={{ scrollMarginTop: 20 }}>
          <div className="section-head">
            <h2>HN 书评</h2>
            <span className="note">推荐在前，同类按时间 · 每本最多保留 20 条，统计用全部提及 · 作者本人贴的不算</span>
          </div>
          {reviews.length ? (
            <>
              <div className="reviews">{reviews.slice(0, SHOW_REVIEWS).map((m) => <Review key={m.commentId} m={m} title={book.title} />)}</div>
              {reviews.length > SHOW_REVIEWS && (
                <details style={{ marginTop: 22 }}>
                  <summary className="acct" style={{ cursor: "pointer", fontSize: 14 }}>看全部 {reviews.length} 条 →</summary>
                  <div className="reviews" style={{ marginTop: 22 }}>{reviews.slice(SHOW_REVIEWS).map((m) => <Review key={m.commentId} m={m} title={book.title} />)}</div>
                </details>
              )}
            </>
          ) : (
            <p className="muted" style={{ margin: 0 }}>没有 ≥100 字的评论，只有提交记录。</p>
          )}
          {!!stories.length && (
            <div style={{ marginTop: 32 }}>
              <div className="eyebrow" style={{ marginBottom: 8 }}>被提交为 story · {book.stories} 次</div>
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {stories.slice(0, 6).map((m) => (
                  <li key={m.commentId} className="rule-b" style={{ padding: "12px 0", fontSize: 14, display: "flex", gap: "4px 12px", flexWrap: "wrap" }}>
                    <a href={`https://news.ycombinator.com/item?id=${m.commentId}`} target="_blank" rel="noreferrer">{m.storyTitle ?? "HN story"} ↗</a>
                    <span className="faint">{m.by} · <span className="nowrap">{m.time.slice(0, 10)}</span>{m.points ? ` · ${m.points} 分` : ""}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        {!!same.length && (
          <section id="related" className="wrap section" style={{ scrollMarginTop: 20 }}>
            <div className="section-head">
              <h2>同一面书架</h2>
              <span className="note">{subjectName} · 按分数</span>
              <Link href={`/books#${book.subject}`} className="more">整面书架 →</Link>
            </div>
            <Shelf row seven size="area" areaNames={areaNames} items={same.map((b) => ({
              paper: bookCover(b), href: `/books/${b.slug}/`,
              label: <span className="shelf-note">{b.hasPositive ? "被推荐" : "被提及"} · {b.people} 人</span>,
            }))} />
          </section>
        )}
      </main>
      <Footer keys="g h 首页 · ? 帮助" books />
    </>
  );
}
