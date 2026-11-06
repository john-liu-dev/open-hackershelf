import { Footer, Header } from "@/components/Header";
import { PreloadData } from "@/components/public/PreloadData";
import { SearchClient } from "@/components/SearchClient";
import { booksMeta, subjectNames } from "@/lib/books";
import { allIds, areaNames, buildMeta } from "@/lib/catalog";
import { withBase } from "@/lib/site";

export const metadata = { title: "搜索" };

/** 公开站搜索页（D46）：没有服务端，搜索词从地址栏读，索引是静态文件 search-index.json，全在浏览器里搜。 */
export default function SearchPage() {
  const meta = buildMeta() as { hn_cutoff?: string };
  const total = allIds().length;
  const nBooks = booksMeta().total;
  // 封面和第一行用的分类名：论文的领域 + 开源书的书架分类（键是 "b-" + 分类）
  const names = { ...areaNames(), ...Object.fromEntries(Object.entries(subjectNames()).map(([k, v]) => [`b-${k}`, v])) };
  return (
    <>
      <Header active="search" />
      <main className="wrap" style={{ paddingTop: 40, maxWidth: 960, minHeight: "100vh" }}>
        <PreloadData href={withBase("/search-index.json")} />
        <h1 className="t-zh" style={{ margin: "0 0 10px", fontSize: 32, fontWeight: 600 }}>搜索</h1>
        <p className="muted" style={{ margin: "0 0 20px", fontSize: 16, lineHeight: 1.7 }}>
          {total.toLocaleString()} 篇论文（主书架和候选层）和 {nBooks} 本开源书。标题、作者、中文导读、前置知识都能搜，中英文都行；在浏览器里搜，不经过服务器。
        </p>
        <SearchClient initialQuery="" initialHits={[]} initialTotal={0} areaNames={names} indexUrl={withBase("/search-index.json")} queryFromUrl />
      </main>
      <Footer cutoff={String(meta.hn_cutoff ?? "")} />
    </>
  );
}
