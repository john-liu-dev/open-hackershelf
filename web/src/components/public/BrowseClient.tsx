"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { withBase } from "@/lib/site";
import { isDefault, query, readState, type AreaLite, type Item, type Row } from "./browse-model";
import { BrowseView } from "./BrowseView";

// browse.json 只下载一次（换筛选条件、翻页都不重复下载）；失败了下次再试
let rowsPromise: Promise<Row[]> | null = null;
function loadRows(): Promise<Row[]> {
  rowsPromise ??= fetch(withBase("/browse.json"))
    .then((r) => {
      if (!r.ok) throw new Error(`browse.json ${r.status}`);
      return r.json() as Promise<Row[]>;
    })
    .catch((e) => {
      rowsPromise = null;
      throw e;
    });
  return rowsPromise;
}

/**
 * 公开站浏览页（静态导出没有服务端）：默认视图直接用构建期算好的首屏；换了筛选、排序或翻页，
 * 再下载 browse.json（约 0.4 MB 压缩后）在浏览器里算。地址栏参数和旧站一样。
 */
export function BrowseClient({ areas, areaNames, initial, initialTotal }: {
  areas: AreaLite[]; areaNames: Record<string, string>; initial: Item[]; initialTotal: number;
}) {
  const sp = useSearchParams();
  const state = useMemo(() => readState(new URLSearchParams(sp.toString())), [sp]);
  const def = isDefault(state);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (def || rows) return;
    let live = true;
    loadRows().then(
      (r) => live && setRows(r),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [def, rows]);

  const result = useMemo(() => (rows && !def ? query(rows, state, areas) : null), [rows, def, state, areas]);
  if (def) return <BrowseView state={state} areas={areas} areaNames={areaNames} items={initial} total={initialTotal} />;
  if (failed) {
    return (
      <>
        <BrowseView state={state} areas={areas} areaNames={areaNames} items={[]} total={0} />
        <p className="muted">目录没加载出来，刷新页面再试一次。</p>
      </>
    );
  }
  if (!result) return <BrowseView state={state} areas={areas} areaNames={areaNames} items={initial} total={null} loading />;
  return <BrowseView state={state} areas={areas} areaNames={areaNames} items={result.items} total={result.total} />;
}
