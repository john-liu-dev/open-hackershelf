import fs from "node:fs/promises";
import { allBooks, subjectNames } from "@/lib/books";
import type { Hit } from "@/lib/search-engine";
import { searchIndexPath } from "@/lib/paths";

export const dynamic = "force-static";

/**
 * 构建期生成的搜索索引（data/build/search-index.json），导出成静态文件给搜索页用。
 * 开源书（Phase 5）也放进来：id 是 "book:<slug>"，f = "book"，r = "b-<分类>"（封面底色），k 放简称、分类和前置知识。
 */
export async function GET(): Promise<Response> {
  const docs = JSON.parse(await fs.readFile(searchIndexPath(), "utf8")) as Hit[];
  const names = subjectNames();
  for (const b of allBooks()) {
    docs.push({
      id: `book:${b.slug}`, t: b.title, z: b.titleZh ?? "", a: b.authors, y: null, f: "book", s: b.score, p: b.people, c: 1,
      o: b.card?.oneliner_zh ?? "", k: [...b.aliases, b.subject ? names[b.subject] : "", ...(b.card?.prerequisites ?? [])].filter(Boolean).join(" "),
      r: b.subject ? `b-${b.subject}` : "", h: b.hasPositive ? 1 : 0,
    });
  }
  return new Response(JSON.stringify(docs), { headers: { "content-type": "application/json" } });
}
