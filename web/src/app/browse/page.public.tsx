import { Suspense } from "react";
import { BrowseClient } from "@/components/public/BrowseClient";
import { BrowseView } from "@/components/public/BrowseView";
import { PER_PAGE, type AreaLite, type Item } from "@/components/public/browse-model";
import { Footer, Header } from "@/components/Header";
import { areaNames, browse, buildMeta, taxonomy } from "@/lib/catalog";

export const metadata = { title: "浏览" };

/**
 * 公开站浏览页（D46）：构建期只渲染默认视图（主书架、推荐分、第 1 页）；
 * 筛选、排序、翻页在浏览器里用 browse.json 算（components/public/BrowseClient.tsx）。
 */
export default function Browse() {
  const areas: AreaLite[] = taxonomy().map((a) => ({ id: a.id, nameZh: a.nameZh, topics: a.topics }));
  const { papers, total } = browse({ tier: "core", sort: "score" }, 1, PER_PAGE);
  const initial: Item[] = papers.map((p) => ({
    id: p.id, title: p.title, titleZh: p.titleZh, year: p.year, area: p.area, tier: p.tier, hasPositive: p.hasPositive, people: p.people,
    oneliner: p.card?.oneliner_zh ?? null, rank: p.rank,
  }));
  const names = areaNames();
  const meta = buildMeta() as { hn_cutoff?: string };
  return (
    <>
      <Header active="browse" />
      <main className="wrap" style={{ paddingTop: 40 }}>
        {/* 静态页里是默认视图；浏览器读到地址栏参数后由 BrowseClient 接管 */}
        <Suspense fallback={<BrowseView state={{}} areas={areas} areaNames={names} items={initial} total={total} />}>
          <BrowseClient areas={areas} areaNames={names} initial={initial} initialTotal={total} />
        </Suspense>
      </main>
      <Footer cutoff={String(meta.hn_cutoff ?? "")} />
    </>
  );
}
