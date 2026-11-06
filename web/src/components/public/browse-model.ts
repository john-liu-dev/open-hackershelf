/**
 * 公开站浏览页（D46）：筛选、排序、分页在浏览器里做，数据是构建期导出的 browse.json（lib/catalog.ts 的 browseRows）。
 * 规则和旧站的 SQL（lib/catalog.ts 的 whereOf / ORDER）一致，最后都按 rank 定序，静态首页和浏览器算的分页对得上。
 * 纯函数：服务端（静态首屏）和浏览器都用。
 */
import type { EntryPaper } from "@/components/Entry";

export type Sort = "score" | "people" | "longest" | "recent" | "rising" | "gems" | "cited" | "newest";
export const SORTS: { id: Sort; name: string; note: string }[] = [
  { id: "score", name: "推荐分", note: "有推荐的不同月份数 + 0.5 × 有强推荐的月份数" },
  { id: "people", name: "最多人", note: "提到它的不同 HN 用户数" },
  { id: "longest", name: "最长寿", note: "第一次和最近一次被提起相隔最久" },
  { id: "recent", name: "最近被提起", note: "最近一次被提起的时间" },
  { id: "rising", name: "上升中", note: "最近 12 个月里有推荐 / 被提起的月份数" },
  { id: "gems", name: "隐藏宝藏", note: "提的人不多（≤ 5 人），但跨了很多个月" },
  { id: "cited", name: "被引最多", note: "OpenAlex 被引次数" },
  { id: "newest", name: "最新发表", note: "arXiv 发表年份" },
];
export const DECADES: [string, string][] = [["old", "2009 及以前"], ["2010", "2010–2019"], ["2020", "2020 以后"]];
export const DIFF: [string, string][] = [["1", "1 入门"], ["2", "2"], ["3", "3 研究生"], ["4", "4"], ["5", "5 专门方向"]];
export const PER_PAGE = 42; // 封面网格每排 6 / 7 / 3 本都能排满

/** browse.json 的一行（列的顺序和 browseRows 一致）。 */
export type Row = [
  id: string, title: string, titleZh: string | null, year: number | null, area: string | null, topic: string | null, core: 0 | 1, pos: 0 | 1,
  people: number, months: number, score: number, first: string, last: string, rec12: number, act12: number, cited: number,
  difficulty: number | null, life: "e" | "d" | null, oneliner: string | null, path: 0 | 1,
];

export type Item = EntryPaper & { oneliner: string | null; rank: number };

export const toItem = (r: Row, rank: number): Item => ({
  id: `arxiv:${r[0]}`, title: r[1], titleZh: r[2], year: r[3], area: r[4], tier: r[6] ? "core" : "cand", hasPositive: !!r[7], people: r[8],
  oneliner: r[18], rank,
});

export type TopicLite = { id: string; area: string; nameZh: string; nameEn: string; n: number; nCore: number };
export type AreaLite = { id: string; nameZh: string; topics: TopicLite[] };

/** 地址栏参数（和旧站的名字一样，旧链接照样能用）。 */
export type State = {
  tier?: string; area?: string; topic?: string; decade?: string; difficulty?: string; shelf?: string; positive?: string; path?: string;
  sort?: string; view?: string; page?: string;
};
const KEYS: (keyof State)[] = ["tier", "area", "topic", "decade", "difficulty", "shelf", "positive", "path", "sort", "view", "page"];

export function readState(sp: URLSearchParams): State {
  const s: State = {};
  for (const k of KEYS) {
    const v = sp.get(k);
    if (v) s[k] = v;
  }
  return s;
}

/** 默认视图（主书架、推荐分、封面、第 1 页）：静态首屏就是它，不用下载 browse.json。 */
export const isDefault = (s: State) => KEYS.every((k) => !s[k] || (k === "page" && s.page === "1"));

export function href(cur: State, o: Partial<State>): string {
  const q = new URLSearchParams();
  for (const k of KEYS) {
    const v = k in o ? o[k] : k === "page" ? undefined : cur[k];
    if (v) q.set(k, v);
  }
  const s = q.toString();
  return s ? `/browse?${s}` : "/browse";
}

/** 解析出的筛选条件：topic 优先于 area（和旧站一样）。 */
export function resolve(s: State, areas: AreaLite[]) {
  const topic = s.topic ? areas.flatMap((a) => a.topics).find((t) => t.id === s.topic) : undefined;
  const area = areas.find((a) => a.id === (s.area ?? topic?.area));
  const sort = (SORTS.find((x) => x.id === s.sort)?.id ?? "score") as Sort;
  const page = Math.max(1, Number(s.page ?? 1) || 1);
  return { topic, area, sort, page, all: s.tier === "all", view: s.view === "list" ? "list" : "grid" } as const;
}

const days = (d: string) => (d ? Date.parse(`${d}T00:00:00Z`) / 86400000 : 0);
const desc = (a: number | null, b: number | null) => (b ?? -Infinity) - (a ?? -Infinity);

const ORDER: Record<Sort, (a: Row, b: Row) => number> = {
  score: (a, b) => desc(a[10], b[10]) || desc(a[8], b[8]) || desc(a[9], b[9]),
  people: (a, b) => desc(a[8], b[8]) || desc(a[9], b[9]),
  longest: (a, b) => desc(days(a[12]) - days(a[11]), days(b[12]) - days(b[11])) || desc(a[8], b[8]),
  recent: (a, b) => (a[12] < b[12] ? 1 : a[12] > b[12] ? -1 : 0) || desc(a[8], b[8]),
  rising: (a, b) => desc(a[13], b[13]) || desc(a[14], b[14]) || desc(a[10], b[10]),
  gems: (a, b) => desc(a[9], b[9]) || desc(a[10], b[10]) || a[8] - b[8],
  cited: (a, b) => desc(a[15], b[15]) || desc(a[8], b[8]),
  newest: (a, b) => desc(a[3], b[3]) || desc(a[8], b[8]),
};

/** 筛选 + 排序 + 分页。rows 按 rank 排好（browse.json 就是这个顺序），平局时保持原顺序。 */
export function query(rows: Row[], s: State, areas: AreaLite[]): { items: Item[]; total: number } {
  const r = resolve(s, areas);
  const dec = s.decade;
  const keep = rows
    .map((row, i) => ({ row, i }))
    .filter(({ row }) => {
      if (!r.all && !row[6]) return false;
      if (r.topic ? row[5] !== r.topic.id : r.area && row[4] !== r.area.id) return false;
      const y = row[3];
      if (dec === "old" ? !(y !== null && y <= 2009) : dec && /^\d{4}$/.test(dec) && !(y !== null && y >= +dec && y <= +dec + 9)) return false;
      if (s.difficulty && row[16] !== Number(s.difficulty)) return false;
      if ((s.shelf === "evergreen" && row[17] !== "e") || (s.shelf === "dated" && row[17] !== "d")) return false;
      if (s.positive === "1" && !row[7]) return false;
      if (s.path === "1" && !row[19]) return false;
      if (r.sort === "gems" && row[8] > 5) return false;
      return true;
    });
  const cmp = ORDER[r.sort];
  keep.sort((a, b) => cmp(a.row, b.row) || a.i - b.i);
  const start = (r.page - 1) * PER_PAGE;
  return { items: keep.slice(start, start + PER_PAGE).map(({ row, i }) => toItem(row, i + 1)), total: keep.length };
}
