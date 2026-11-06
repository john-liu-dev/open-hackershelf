/** 界面文案规则（前后端共用，不读数据库）。 */

/** has_positive = false 的条目写"被提及"，不写"被推荐"（CLAUDE.md）；2/2 候选层没有立场标注，一律"被提及"。 */
export function recLabel(p: { tier: "core" | "cand"; hasPositive: boolean; people: number }): { text: string; positive: boolean } {
  if (p.tier === "core" && p.hasPositive) return { text: `被推荐 · ${p.people} 人`, positive: true };
  return { text: `被提及 · ${p.people} 人`, positive: false };
}

export const STANCE_NAMES: Record<string, string> = {
  strong_rec: "强烈推荐",
  rec: "推荐",
  critical: "批评",
  reference: "引用",
  joke: "玩笑",
};

/** 立场胶囊的样式：推荐金色，批评深色描边，其他分隔线描边。 */
export function stancePill(s: string | null | undefined): string {
  if (s === "strong_rec" || s === "rec") return "pill pill-pos";
  if (s === "critical") return "pill pill-neg";
  return "pill";
}

export const TYPE_NAMES: Record<string, string> = {
  foundational: "奠基之作", method: "方法", survey: "综述", empirical: "实证研究", position: "观点", tutorial: "教程", other: "其他",
};

/** "2026-11-01" → "2026 年 11 月"。 */
export function ym(iso: string): string {
  return `${iso.slice(0, 4)} 年 ${Number(iso.slice(5, 7))} 月`;
}

/**
 * 立场标注时评论里指向这篇论文的链接被换成了 [PAPER]（docs/DATA.md）。显示时："([PAPER])" 去掉，其余换成论文的短标题。
 */
export function cleanQuote(q: string, title: string): string {
  const short = title.split(/:\s+/)[0];
  return q
    .replace(/\s*\(\s*\[PAPER\]\s*\)/g, "")
    .replace(/\[PAPER\]/g, short)
    .replace(/\s+([,.;:])/g, "$1")
    .trim();
}
