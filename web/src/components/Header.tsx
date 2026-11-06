import Link from "next/link";
import { PUBLIC } from "@/lib/site";
import { SearchBox } from "./SearchBox";

type Nav = "papers" | "browse" | "fresh" | "books" | "search" | null;

/** 页头（B1）：字标、导航、搜索框。手机上导航换到第二行。 */
export function Header({ query = "", active = null }: { query?: string; active?: Nav }) {
  const cur = (n: Nav) => (active === n ? "page" : undefined);
  return (
    <header className="site-header">
      {/* 页头链接不预取（2026-11-06）：首页加载时四个 RSC 预取约 60 KB，在慢网下和首屏抢带宽；点了再取 */}
      <Link href="/" className="site-logo" prefetch={false}>HackerShelf</Link>
      <nav aria-label="主导航" className="site-nav">
        <Link href="/" aria-current={cur("papers")} prefetch={false}>论文</Link>
        <Link href="/browse" aria-current={cur("browse")} prefetch={false}>浏览</Link>
        <Link href="/fresh" aria-current={cur("fresh")} prefetch={false}>新鲜</Link>
        <Link href="/books" aria-current={cur("books")} prefetch={false}>图书</Link>
      </nav>
      {/* 搜索页自己有大搜索框，页头不再放一个 */}
      {active !== "search" && <SearchBox initial={query} />}
    </header>
  );
}

/**
 * 页脚：署名（ODC-By 要求写明来源）和快捷键。
 * 公开站的论文详情页不传 cutoff：每周目录更新时截止日期一变，几千个详情页都会跟着变，公开仓库会白白变大。
 */
export function Footer({ cutoff, keys = "/ 搜索 · j k 上下 · g h 首页 · ? 帮助", books = false }: { cutoff?: string; keys?: string; books?: boolean }) {
  return (
    <footer className="site-footer">
      <div>
        <span>
          HN 数据来自 open-index/hacker-news（ODC-By 1.0）和 HN Algolia API
          {cutoff ? <>，<span className="nowrap">截至 {cutoff.slice(0, 10)}</span></> : null}
          {" · "}论文元数据来自 arXiv 和 OpenAlex
          {PUBLIC ? "（Thank you to arXiv for use of its open access interoperability）" : ""}
          {books ? <>{" · "}书单来自 free-programming-books（CC BY 4.0）</> : null}
          {" · "}{PUBLIC ? "封面由论文编号或书名生成" : "封面由论文编号生成"}
          {PUBLIC ? " · 中文导读和学习路径由 Claude 撰写，可能有错" : " · 个人学习站，仅本人使用"}
          {PUBLIC && (
            <>
              {" · "}作者 <a href="https://github.com/john-liu-dev" rel="author">john-liu-dev</a>
              {" · "}<Link href="/about">关于本站</Link>
            </>
          )}
        </span>
        <span>{keys}</span>
      </div>
    </footer>
  );
}
