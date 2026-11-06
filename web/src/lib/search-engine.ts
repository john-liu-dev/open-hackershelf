/**
 * 搜索引擎配置：服务端（搜索页首屏）和浏览器（即时搜索）用同一份，两边的结果和排序完全一致。
 * 不依赖 node 模块，两边都能引用。索引数据是管线生成的 data/build/search-index.json（字段见 docs/DATA.md）。
 */
import MiniSearch from "minisearch";

/** 搜索索引的一条（字段短）：r = 领域（封面底色），h = 有正向推荐（主书架才算）。 */
export type Hit = { id: string; t: string; z: string; a: string; y: number | null; f: string; s: number; p: number; c: 0 | 1; o: string; k: string; r?: string; h?: 0 | 1 };

/** 英文按词切，中文按单字 + 双字切（MiniSearch 默认分词对中文无效）。 */
export function tokenize(s: string): string[] {
  const out: string[] = [];
  for (const part of s.toLowerCase().split(/[\s\p{P}\p{S}]+/u)) {
    if (!part) continue;
    if (/[㐀-鿿]/.test(part)) {
      const chars = Array.from(part);
      for (let i = 0; i < chars.length; i++) {
        out.push(chars[i]);
        if (i + 1 < chars.length) out.push(chars[i] + chars[i + 1]);
      }
    } else out.push(part);
  }
  return out;
}

export function newEngine(): MiniSearch<Hit> {
  return new MiniSearch<Hit>({
    fields: ["t", "z", "a", "o", "k"],
    storeFields: ["id", "t", "z", "a", "y", "f", "s", "p", "c", "o", "r", "h"],
    tokenize,
    searchOptions: {
      boost: { t: 3, z: 2, a: 1.5 }, prefix: true, fuzzy: 0.15, combineWith: "AND",
      // 相关度相近时，被更多人提到的排前面；主书架的略微靠前（候选层显示"被提及"）
      boostDocument: (_id, _term, stored) => (1 + Math.log10(1 + Number(stored?.p ?? 0))) * (stored?.c ? 1.3 : 1),
    },
  });
}

/** 前端即时搜索最多显示 100 条；服务端首屏只给前 50 条（页面轻一些，排序相同）。 */
export const MAX_HITS = 100;

export function runSearch(engine: MiniSearch<Hit>, q: string, field = "", limit = MAX_HITS): { hits: Hit[]; total: number } {
  const all = engine.search(q, { filter: field ? (h) => h.f === field : undefined }) as unknown as Hit[];
  return { hits: all.slice(0, limit), total: all.length };
}
