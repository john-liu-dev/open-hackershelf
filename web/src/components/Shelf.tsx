import type { ReactNode } from "react";
import { Cover, type CoverInput, type CoverSize } from "./Cover";
import { PaperLink } from "./PaperLink";
import { withBase } from "@/lib/site";

/** 书架上一本书要的字段：封面字段就够（服务端的 Paper 和公开站浏览页的精简条目都满足）。href：开源书的详情页（不传就是论文详情页）。 */
export type ShelfItem = { paper: CoverInput; label?: ReactNode; href?: string };

/**
 * 书架行（docs/DESIGN.md 第 5 节）：一排封面底部对齐，下面一条横板，再下面一行排名和标签。
 * 每本书下面各画一段横板，左右伸进间隙里，同一排连成一整条；换行后每一排都有自己的横板。
 * row = 固定一排（首页 No.2–7、领域行、同一面书架）：窄屏时只保留整排。
 */
export function Shelf({ items, areaNames, size = "shelf", seven = false, row = false }: {
  items: ShelfItem[]; areaNames: Record<string, string>; size?: CoverSize; seven?: boolean; row?: boolean;
}) {
  return (
    <ol className={`shelf${seven ? " shelf--7" : ""}${row ? " shelf--row" : ""}`}>
      {items.map(({ paper, label, href }) => {
        const title = paper.titleZh ? `${paper.title} · ${paper.titleZh}` : paper.title;
        const inner = (
          <>
            <Cover paper={paper} areaZh={paper.area ? areaNames[paper.area] : null} size={size} />
            <span className="sr-only">{paper.title}</span>
          </>
        );
        return (
        <li key={paper.id} className="shelf-item">
          {href ? <a href={withBase(href)} data-nav-item title={title}>{inner}</a>
            : <PaperLink id={paper.id} data-nav-item title={title}>{inner}</PaperLink>}
          <div className="shelf-plank" aria-hidden="true" />
          {label && <div className="shelf-label">{label}</div>}
        </li>
        );
      })}
    </ol>
  );
}
