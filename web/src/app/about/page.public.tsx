import Link from "next/link";
import { Footer, Header } from "@/components/Header";
import { booksMeta } from "@/lib/books";
import { buildMeta } from "@/lib/catalog";

export const metadata = { title: "关于", description: "HackerShelf 怎么挑论文和开源书、数据从哪里来、多久更新一次。" };

const AUTHOR_URL = "https://github.com/john-liu-dev";

/**
 * 关于页（分享前包装，2026-11-05）：怎么选的（论文、开源书）、更新频率、导读由 Claude 写、数据署名、作者。
 * 不放头像、简介和公司信息。
 */
export default function AboutPage() {
  const m = buildMeta() as { counts?: Record<string, number> };
  const n = (k: string) => m.counts?.[k]?.toLocaleString() ?? "—";
  const nBooks = booksMeta().total;
  return (
    <>
      <Header />
      <main className="wrap about" style={{ paddingTop: 56, paddingBottom: 72 }}>
        <div style={{ maxWidth: 720, display: "flex", flexDirection: "column", gap: 28 }}>
          <h1 className="t-zh" style={{ margin: 0, fontSize: "clamp(36px, 5vw, 52px)", fontWeight: 600 }}>关于 HackerShelf</h1>
          <p className="about-lede">
            HackerShelf 收集 Hacker News 上被不同的人在不同月份反复推荐的论文和开源书，每篇配中文导读、HN 原评论和学习路径。
            读论文去 arXiv，读书去官方免费版；这里只负责帮你挑。
          </p>

          <section>
            <h2>怎么选的</h2>
            <ul>
              <li>数据是 Hacker News 从 2006 年到现在的全部帖子和评论：开源存档加官方接口补到最近。</li>
              <li>算一次“提及”：评论里链接到这篇 arXiv 论文、评论者自己写的文字不少于 100 个字符；或者把论文直接发成帖子。</li>
              <li>至少 3 个不同的人、在至少 3 个不同的月份提到过，进主书架（现在 {n("papers_core")} 篇）。只有 2 个人、2 个月的进候选层（{n("papers_cand")} 篇），一律写“被提及”。</li>
              <li>每条评论的态度（强烈推荐、推荐、引用、玩笑、批评）由 Claude 判断。排序按“有人推荐的月份数 + 0.5 × 有人强烈推荐的月份数”；同一个人最多算两个月，免得一个人反复贴同一篇。</li>
              <li>每篇最多留 20 条评论：先留推荐和批评，再用引用补满；数字仍按全部提及算。</li>
            </ul>
          </section>

          <section id="books" style={{ scrollMarginTop: 20 }}>
            <h2>开源书怎么选的</h2>
            <ul>
              <li>候选书单是 free-programming-books 的英文书单，加少量手选的数学和机器学习书。</li>
              <li>只认链接到这本书官方免费版的评论和帖子，评论者自己写的文字同样不少于 100 个字符。作者本人贴自己的书不算，链接其实不是在说这本书的也不算。</li>
              <li>入选门槛和排序同论文：至少 3 个不同的人、在至少 3 个不同的月份提到过，按有人推荐的月份数排。</li>
              <li>只收开放许可，或者作者、出版社官方免费放出的完整版；许可证逐本到官方页面核实过。先核实了 HN 上提到最多的 100 本，现在上架 {nBooks} 本；没写完的书标“未写完”。</li>
              <li>链接指向官方免费版，个别原站失效的会注明。本站不托管全文；封面按书名和作者生成，不是书的真实封面。</li>
            </ul>
          </section>

          <section>
            <h2>多久更新</h2>
            <ul>
              <li>论文主书架每月初更新一次；开源书暂时不定期更新。</li>
              <li><Link href="/fresh" className="acct">新鲜</Link>每天更新两次，GitHub 的定时任务常会晚几个小时。内容是 Hugging Face 的热门论文、HN 当天在讨论的论文、几个 arXiv 分类的新论文，只抓标题和摘要，不写导读。</li>
            </ul>
          </section>

          <section>
            <h2>中文导读</h2>
            <ul>
              <li>中文标题、一句话摘要、导读、开源书的读法、HN 评论下面的中文说明和学习路径，都是 Claude 写的，可能有错。</li>
              <li>拿不准的地方请以论文、书的原文和原评论为准。</li>
            </ul>
          </section>

          <section>
            <h2>数据和署名</h2>
            <ul>
              <li>HN 数据：open-index/hacker-news（ODC-By 1.0），以及 HN Algolia API。</li>
              <li>论文的标题、作者、摘要：arXiv API。Thank you to arXiv for use of its open access interoperability.</li>
              <li>被引数和参考文献：OpenAlex（CC0）。</li>
              <li>开源书书单：EbookFoundation/free-programming-books（CC BY 4.0）。</li>
              <li>封面上的图案按论文编号或书的编号生成，不是论文里的图，也不是书的真实封面。</li>
            </ul>
          </section>

          <section>
            <h2>作者</h2>
            <ul>
              <li>由 <a href={AUTHOR_URL} className="acct" rel="author">john-liu-dev</a> 整理，个人学习用。</li>
              <li>本站没有广告，也不放访问统计。</li>
            </ul>
          </section>
        </div>
      </main>
      <Footer />
    </>
  );
}
