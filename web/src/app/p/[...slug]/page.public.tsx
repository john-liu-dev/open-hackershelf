import Link from "next/link";
import { notFound } from "next/navigation";
import { Cover } from "@/components/Cover";
import { Footer, Header } from "@/components/Header";
import { PaperActions } from "@/components/public/PaperActions";
import { PaperLink } from "@/components/PaperLink";
import { Shelf } from "@/components/Shelf";
import { YearBars } from "@/components/YearBars";
import { allIds, areaNames, buildMeta, getMentions, getPaper, getPath, getRelated, getTopic, idFromSlug, noteNames, slugFromId, type Mention } from "@/lib/catalog";
import { cleanQuote, recLabel, STANCE_NAMES, stancePill, TYPE_NAMES } from "@/lib/labels";
import type { NoteData, NoteQuote } from "@/lib/note";
import { PUBLIC_SITE_URL } from "@/lib/site";

type Params = Promise<{ slug: string[] }>;

/** 公开站（D46）：目录里每篇论文一个静态详情页。 */
export const dynamicParams = false;
export function generateStaticParams() {
  return allIds().map((id) => ({ slug: slugFromId(id).split("/") }));
}

export async function generateMetadata({ params }: { params: Params }) {
  const p = getPaper(idFromSlug((await params).slug));
  if (!p) return { title: "未找到" };
  // 分享卡片（分享前包装，2026-11-05）：主书架每篇用自己的生成封面（web/scripts/og-images.mjs 生成 og/<编号>.jpg），候选层用通用图
  const slug = slugFromId(p.id);
  const url = `${PUBLIC_SITE_URL}/p/${slug}/`;
  const description = p.card?.oneliner_zh ?? p.titleZh ?? undefined;
  const image = p.tier === "core" ? `${PUBLIC_SITE_URL}/og/${slug}.jpg` : `${PUBLIC_SITE_URL}/og.png`;
  return {
    title: p.title,
    description,
    openGraph: { type: "article", siteName: "HackerShelf", locale: "zh_CN", url, title: p.title, description,
      images: [{ url: image, width: 1200, height: 630, alt: p.titleZh ?? p.title }] },
    twitter: { card: "summary_large_image", title: p.title, description, images: [image] },
  };
}

const SHOW_REVIEWS = 6;

function reviewText(m: Mention, title: string): string {
  const raw = m.quote || (m.text ? (m.text.length > 360 ? `${m.text.slice(0, 357)}…` : m.text) : "");
  return cleanQuote(raw, title);
}

function Review({ m, title }: { m: Mention; title: string }) {
  return (
    <article className="review">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <span className={stancePill(m.stance)}>{m.source === "thread_comment" ? "讨论串评论" : m.stance ? STANCE_NAMES[m.stance] : "评论"}</span>
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

/** 笔记里的 HN 原话：推荐在前（getMentions 已排好），每人一条，最多 3 条。 */
function noteQuotes(reviews: Mention[], title: string): NoteQuote[] {
  const seen = new Set<string>();
  const out: NoteQuote[] = [];
  for (const m of [...reviews.filter((x) => x.source === "comment_link"), ...reviews.filter((x) => x.source !== "comment_link")]) {
    if (out.length >= 3 || seen.has(m.by)) continue;
    const text = reviewText(m, title);
    if (!text) continue;
    seen.add(m.by);
    out.push({ by: m.by, ym: m.time.slice(0, 7), text: text.length > 400 ? `${text.slice(0, 397)}…` : text, commentId: m.commentId, story: m.storyTitle ?? null });
  }
  return out;
}

/**
 * 公开站的论文详情（D46）：和旧站同一套版式，去掉 PDF 首页预览、放进书架、标星、我的笔记、申请学习路径；
 * “开始阅读”去 arXiv；加“复制提问提示词”和“在 Obsidian 中记笔记”。
 */
export default async function PaperPage({ params }: { params: Params }) {
  const { slug } = await params;
  const paper = getPaper(idFromSlug(slug));
  if (!paper) notFound();
  const names = areaNames();
  const mentions = getMentions(paper.id);
  const reviews = mentions.filter((m) => m.source === "comment_link" || m.source === "thread_comment");
  const stories = mentions.filter((m) => m.source === "story_url");
  const topic = paper.topic ? getTopic(paper.topic) : null;
  const related = getRelated(paper.id, 7);
  const meta = buildMeta() as { hn_cutoff?: string };
  const cutoff = String(meta.hn_cutoff ?? "").slice(0, 10);
  const lab = recLabel(paper);
  const card = paper.card;
  const plain = slugFromId(paper.id);
  const years = Object.keys(paper.byYear).map(Number);
  const firstYear = Math.min(...years, paper.year ?? 9999);
  const lastYear = Number(cutoff.slice(0, 4)) || Math.max(...years);
  const onlyThread = !reviews.some((m) => m.source === "comment_link");
  const path = getPath(paper.id);
  const note: NoteData = {
    id: paper.id, path: noteNames().get(paper.id) ?? `论文/${plain}`, title: paper.title, titleZh: paper.titleZh,
    authors: paper.authors.slice(0, 12), nAuthors: paper.authors.length, year: paper.year,
    areaZh: paper.area ? (names[paper.area] ?? null) : null, topicZh: topic?.nameZh ?? null, people: paper.people, months: paper.activeMonths,
    oneliner: card?.oneliner_zh ?? null, summary: card?.summary_zh ?? null, abstract: card?.summary_zh ? null : paper.abstract,
    whyHn: card?.why_hn ?? null, quotes: noteQuotes(reviews, paper.title), siteUrl: PUBLIC_SITE_URL,
  };

  return (
    <>
      <Header active="papers" />
      <main>
        <section className="wrap detail-top" style={{ paddingTop: 48 }}>
          <div className="detail-side">
            <Cover paper={paper} areaZh={paper.area ? names[paper.area] : null} size="detail" />
            <YearBars byYear={paper.byYear} from={firstYear} to={lastYear} />
          </div>

          <div className="detail-main">
            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 8px", fontSize: 13, color: "var(--ink3)" }}>
              {topic && (
                <>
                  <Link href={`/browse?area=${topic.area}`} className="acct">{topic.areaName}</Link><span>›</span>
                  <Link href={`/browse?topic=${topic.id}`} className="acct">{topic.nameZh}</Link><span>·</span>
                </>
              )}
              <span className="nowrap">arXiv:{plain} · {paper.primaryCategory}</span>
            </div>
            <h1>{paper.title}</h1>
            {paper.titleZh && <div className="detail-zh">{paper.titleZh}</div>}
            <div style={{ fontSize: 15, lineHeight: 1.7, color: "var(--ink2)" }}>
              {paper.authors.slice(0, 12).join(", ")}{paper.authors.length > 12 ? ` 等 ${paper.authors.length} 人` : ""} · {paper.year}
            </div>
            {card?.oneliner_zh && <p style={{ margin: "6px 0 0", fontSize: 19, lineHeight: 1.7 }}>{card.oneliner_zh}</p>}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 10 }}>
              <a href={paper.links.abs} className="btn btn-primary" target="_blank" rel="noreferrer" data-nav-item>开始阅读 ↗</a>
              <a className="btn btn-sm" style={{ padding: "13px 18px" }} href={paper.links.pdf} target="_blank" rel="noreferrer">PDF</a>
              <a className="btn btn-sm" style={{ padding: "13px 18px" }} href={paper.links.alphaxiv} target="_blank" rel="noreferrer">alphaXiv 讨论</a>
            </div>
            <PaperActions data={note} />
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 14px", alignItems: "center", marginTop: 6, fontSize: 14, color: "var(--ink2)" }}>
              <span className={lab.positive ? "pill pill-pos" : "pill"}>{lab.text}</span>
              <span className="nowrap">首次 {paper.firstMention} · 最近 {paper.lastMention}</span>
              {paper.metrics.venue && <span>发表于 {paper.metrics.venue}</span>}
            </div>
            <div className="stats">
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}><span className="stat-v">{paper.people}</span><span className="stat-k">不同的人</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}><span className="stat-v">{paper.activeMonths}</span><span className="stat-k">活跃月份</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}><span className="stat-v">{paper.threads}</span><span className="stat-k">讨论串</span></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span className="stat-v">{paper.metrics.cited_by !== undefined ? paper.metrics.cited_by.toLocaleString() : "—"}</span>
                <span className="stat-k">被引（OpenAlex）</span>
              </div>
            </div>
          </div>
        </section>

        <nav aria-label="详情分栏" className="wrap" style={{ paddingTop: 72 }}>
          <div className="tabs">
            <a href="#guide" aria-current="true">导读</a>
            {path && <a href="#path">学习路径 {path.steps.length}</a>}
            <a href="#reviews">HN 书评 {reviews.length}</a>
            {!!related.length && <a href="#related">相关 {related.length}</a>}
          </div>
        </nav>

        <section id="guide" className="wrap" style={{ paddingTop: 44, display: "flex", flexWrap: "wrap", gap: "40px 64px", scrollMarginTop: 20 }}>
          <div style={{ flex: "999 1 560px", minWidth: 0, display: "flex", flexDirection: "column", gap: 28 }}>
            {card?.summary_zh ? (
              <p className="prose-zh">{card.summary_zh}</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div className="eyebrow">{paper.tier === "cand" ? "arXiv 摘要（候选层不写导读）" : "arXiv 摘要"}</div>
                <p style={{ margin: 0, fontSize: 17, lineHeight: 1.8 }} lang="en">{paper.abstract}</p>
              </div>
            )}
            {card?.why_hn && (
              <div className="callout">
                <div className="eyebrow acct">HN 为什么提它</div>
                <p className="t-zh" style={{ margin: 0, fontSize: 19, lineHeight: 1.9 }}>{card.why_hn}</p>
              </div>
            )}
            {paper.tier === "cand" && (
              <p className="faint" style={{ margin: 0, fontSize: 14, lineHeight: 1.8 }}>
                候选层：至少 2 个不同的人、在 2 个不同月份提到过，还没到主书架的 3 人 3 个月。没有做立场标注，所以只写“被提及”。
              </p>
            )}
          </div>
          {card && (
            <div style={{ flex: "1 1 320px", minWidth: 0, display: "flex", flexDirection: "column", gap: 22 }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {card.type && <span className="tag">{TYPE_NAMES[card.type] ?? card.type}</span>}
                {card.difficulty && <span className="tag">难度 {card.difficulty} / 5</span>}
                {card.reading_minutes && <span className="tag">约 {card.reading_minutes} 分钟</span>}
                {card.shelf_life && <span className="tag">{card.shelf_life === "evergreen" ? "经得起时间" : "有时效性"}</span>}
              </div>
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

        {path && (
          <section id="path" className="wrap section" style={{ scrollMarginTop: 20 }}>
            <div className="section-head">
              <h2>学习路径</h2>
              <span className="note">读这篇之前，按顺序读书架上的 {path.steps.length - 1} 篇 · 参考文献来自 OpenAlex，顺序和要点由 Claude Code 排出</span>
            </div>
            {path.intro && <p className="path-intro">{path.intro}</p>}
            <ol className="path-steps">
              {path.steps.map((st, i) => {
                const self = st.paper.id === paper.id;
                return (
                  <li key={st.paper.id} className={self ? "path-step path-step--self" : "path-step"}>
                    <span className="path-n">{i + 1}</span>
                    <PaperLink id={st.paper.id} tabIndex={-1} aria-hidden="true"><Cover paper={st.paper} size="list" /></PaperLink>
                    <div className="path-body">
                      <div className="path-title">
                        {self ? <span>{st.paper.title}</span> : <PaperLink id={st.paper.id}>{st.paper.title}</PaperLink>}
                        <span className="path-meta">{st.paper.titleZh ? `${st.paper.titleZh} · ` : ""}{st.paper.year ?? ""}{self ? " · 就是这篇" : ""}</span>
                      </div>
                      <p className="path-why">{st.why}</p>
                      {st.focus && <p className="path-focus"><span>读</span>{st.focus}</p>}
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        )}

        <section id="reviews" className="wrap section" style={{ scrollMarginTop: 20 }}>
          <div className="section-head">
            <h2>HN 书评</h2>
            <span className="note">
              {onlyThread
                ? "没有评论直接链到它；下面是它被提交的讨论串里回复最多的评论（不计入统计）"
                : `推荐在前，同类按时间 · 每篇最多保留 20 条，统计用全部提及`}
            </span>
          </div>
          {reviews.length ? (
            <>
              <div className="reviews">{reviews.slice(0, SHOW_REVIEWS).map((m) => <Review key={m.commentId} m={m} title={paper.title} />)}</div>
              {reviews.length > SHOW_REVIEWS && (
                <details style={{ marginTop: 22 }}>
                  <summary className="acct" style={{ cursor: "pointer", fontSize: 14 }}>看全部 {reviews.length} 条 →</summary>
                  <div className="reviews" style={{ marginTop: 22 }}>{reviews.slice(SHOW_REVIEWS).map((m) => <Review key={m.commentId} m={m} title={paper.title} />)}</div>
                </details>
              )}
            </>
          ) : (
            <p className="muted" style={{ margin: 0 }}>讨论串里没有 ≥100 字的评论，只有提交记录。</p>
          )}
          {!!stories.length && (
            <div style={{ marginTop: 32 }}>
              <div className="eyebrow" style={{ marginBottom: 8 }}>被提交为 story · {stories.length} 次</div>
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

        {!!related.length && (
          <section id="related" className="wrap section" style={{ scrollMarginTop: 20 }}>
            <div className="section-head">
              <h2>同一面书架</h2>
              <span className="note">内容相似 + 共同提到的人 + 引用关系</span>
            </div>
            <Shelf row seven size="area" areaNames={names} items={related.map((r) => ({
              paper: r.paper,
              label: <span className="shelf-note">{r.coPeople ? `共同提到 ${r.coPeople} 人` : r.cites ? "有引用关系" : `内容相似 ${Math.round(r.sim * 100)}%`}</span>,
            }))} />
          </section>
        )}
      </main>
      <Footer keys="c 复制提示词 · o 记笔记 · g h 首页 · ? 帮助" />
    </>
  );
}
