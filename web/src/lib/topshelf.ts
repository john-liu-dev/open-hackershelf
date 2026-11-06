/**
 * 首页“一排真书”的数据（2026-11-06，构建时生成）：长青榜前 72 篇（按排名）。浏览器按宽度取前 N 篇（每本约 15px），
 * 再按第一次被 HN 提到的时间从左到右摆。标题、年份、人数都在这里，鼠标移上去的提示不用再取别的文件。
 */
import "server-only";
import { AREA_COLORS } from "./cover";
import { shelf } from "./catalog";
import { slugFromId } from "./ids";

export const TOPSHELF_MAX = 72;

/** 一本：s 详情页编号、t 标题、y 年份、p 人数、a 领域在 AREA_COLORS 里的序号（-1 = 没有）、r 长青榜名次、f 第一次被提到、w 书脊宽（px） */
export type ShelfBook = { s: string; t: string; y: number | null; p: number; a: number; r: number; f: string; w: number };

/** FNV-1a：同一篇论文的书脊宽度永远一样（10–14px） */
function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function topShelfBooks(): ShelfBook[] {
  const areas = Object.keys(AREA_COLORS);
  return shelf("evergreen", TOPSHELF_MAX).map((p, i) => ({
    s: slugFromId(p.id), t: p.title, y: p.year, p: p.people, a: p.area ? areas.indexOf(p.area) : -1,
    r: i + 1, f: String(p.firstMention ?? "").slice(0, 10), w: 10 + (hash(p.id) % 5),
  }));
}
