import type { ReactNode } from "react";
import type { CoverInput } from "./Cover";
import { recLabel } from "@/lib/labels";
import { Cover } from "./Cover";
import { PaperLink } from "./PaperLink";

/** 列表行（B1"最近被提起"、搜索、浏览的列表模式）：84px 小封面 + 标题、中文名、标签。 */
/** 列表行要的字段：封面字段 + 推荐标签用的三个。 */
export type EntryPaper = CoverInput & { tier: "core" | "cand"; hasPositive: boolean; people: number };

export function Entry({ paper, areaZh, top, children }: { paper: EntryPaper; areaZh?: string | null; top?: ReactNode; children?: ReactNode }) {
  const lab = recLabel(paper);
  return (
    <PaperLink id={paper.id} className="entry" data-nav-item>
      <Cover paper={paper} size="list" />
      <span className="entry-text">
        <span className="faint" style={{ fontSize: 12 }}>{top ?? <>{paper.year}{areaZh ? ` · ${areaZh}` : ""}</>}</span>
        <span className="entry-title">{paper.title}</span>
        {paper.titleZh && <span className="entry-zh">{paper.titleZh.split("：")[0]}</span>}
        {children}
        <span className="faint" style={{ fontSize: 13 }}>
          {lab.positive ? "被推荐" : "被提及"} · {paper.people} 人{paper.tier === "cand" ? " · 候选" : ""}
        </span>
      </span>
    </PaperLink>
  );
}
