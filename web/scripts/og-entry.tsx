// 分享卡片的 HTML（og-images.mjs 用 esbuild 打包后在 Node 里调用；PUBLIC 打包时定义成假，封面图案直接输出 SVG）。
// 版式：1200×630 深色底，左边是这篇论文（或开源书）的生成封面，右边是站名、英文标题、中文标题、推荐人数。
import { renderToStaticMarkup } from "react-dom/server";
import { Cover, coverZh } from "@/components/Cover";

export type OgPaper = {
  id: string; title: string; titleZh: string | null; year: number | null; area: string | null; areaZh: string | null;
  people: number; months: number; positive: boolean;
  /** 开源书（Phase 5）：封面右下角写短作者名，卡片底行写“开源书” */
  sub?: string | null; book?: boolean;
};

function Brand({ logo, big = false }: { logo: string; big?: boolean }) {
  return (
    <div className={big ? "og-brand og-brand-lg" : "og-brand"}>
      <span className="og-logo" dangerouslySetInnerHTML={{ __html: logo }} />
      HackerShelf
    </div>
  );
}

const cover = (p: OgPaper) => (
  <Cover paper={{ id: p.id, area: p.area, title: p.title, titleZh: p.titleZh, year: p.year, sub: p.sub }} areaZh={p.areaZh} size="spot" />
);

export function paperCard(p: OgPaper, logo: string): string {
  const n = p.title.length;
  const size = n <= 40 ? 54 : n <= 70 ? 46 : n <= 110 ? 40 : 34;
  return renderToStaticMarkup(
    <div className="og-card">
      <div className="og-cover">{cover(p)}</div>
      <div className="og-text">
        <Brand logo={logo} />
        <div className="og-title" style={{ fontSize: size }}>{p.title}</div>
        {p.titleZh && <div className="og-zh">{coverZh(p.titleZh)}</div>}
        <div className="og-meta">
          {p.people} 人在 {p.months} 个月里{p.positive ? "推荐" : "提到"}{p.book ? " · 开源书" : p.year ? ` · ${p.year}` : ""}
        </div>
      </div>
    </div>,
  );
}

export function siteCard(papers: OgPaper[], logo: string): string {
  return renderToStaticMarkup(
    <div className="og-card og-site">
      <div className="og-text">
        <Brand logo={logo} big />
        <div className="og-site-line">Hacker News 二十年里<br />被反复推荐的论文</div>
        <div className="og-site-sub">中文导读 · HN 原话 · 学习路径</div>
      </div>
      <div className="og-site-covers">
        {papers.slice(0, 3).map((p) => <div key={p.id} className="og-site-cover">{cover(p)}</div>)}
      </div>
    </div>,
  );
}
