import Link from "next/link";
import { Entry } from "@/components/Entry";
import { Shelf } from "@/components/Shelf";
import { recLabel } from "@/lib/labels";
import { DECADES, DIFF, href, PER_PAGE, resolve, SORTS, type AreaLite, type Item, type State } from "./browse-model";

/**
 * 公开站浏览页的界面（和旧站 app/browse/page.tsx 同一套样式）。只负责画：静态首屏（服务端）和浏览器里重算的结果都用它。
 * loading：浏览器正在下载 browse.json，先显示上一次的结果，标题下写“加载中”。
 */
export function BrowseView({ state, areas, areaNames, items, total, loading = false }: {
  state: State; areas: AreaLite[]; areaNames: Record<string, string>; items: Item[]; total: number | null; loading?: boolean;
}) {
  const { topic, area, sort, page, all, view } = resolve(state, areas);
  const pages = total === null ? 1 : Math.max(1, Math.ceil(total / PER_PAGE));
  const h = (o: Partial<State>) => href(state, o);
  const count = (t: { n: number; nCore: number }) => (all ? t.n : t.nCore);
  const seg = (key: keyof State, opts: [string, string][], label = "全部") => (
    <div className="chips scroll">
      <Link href={h({ [key]: undefined })} aria-current={!state[key]}>{label}</Link>
      {opts.map(([v, l]) => <Link key={v} href={h({ [key]: v })} aria-current={state[key] === v}>{l}</Link>)}
    </div>
  );
  const title = topic ? topic.nameZh : area ? area.nameZh : "全部论文";

  return (
    <div className="grid lg:grid-cols-[230px_minmax(0,1fr)]" style={{ gap: "24px 48px" }}>
      <nav aria-label="领域" className="hidden lg:block" style={{ fontSize: 14 }}>
        <div className="eyebrow" style={{ marginBottom: 8 }}>领域</div>
        <Link href={h({ area: undefined, topic: undefined })} className="side-link" aria-current={!area}>全部</Link>
        {areas.map((a) => (
          <div key={a.id}>
            <Link href={h({ area: a.id, topic: undefined })} className="side-link" aria-current={area?.id === a.id && !topic}>
              {a.nameZh} <span className="faint">{a.topics.reduce((n, t) => n + count(t), 0)}</span>
            </Link>
            {area?.id === a.id && (
              <div style={{ paddingLeft: 12, borderLeft: "1px solid var(--rule)", margin: "2px 0 6px" }}>
                {a.topics.filter((t) => count(t) > 0).map((t) => (
                  <Link key={t.id} href={h({ topic: t.id, area: undefined })} className="side-link" aria-current={topic?.id === t.id} style={{ fontSize: 13 }}>
                    {t.nameZh} <span className="faint">{count(t)}</span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        ))}
      </nav>

      <section style={{ minWidth: 0 }}>
        <div className="faint" style={{ marginBottom: 8, fontSize: 13 }}>
          {area && <Link href={h({ area: area.id, topic: undefined })} className="acct">{area.nameZh}</Link>}
          {topic && <> › {topic.nameEn}</>}
        </div>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <h1 className="t-zh" style={{ margin: 0, fontSize: "clamp(28px, 3.6vw, 40px)", fontWeight: 600, lineHeight: 1.15 }}>{title}</h1>
            <p className="faint" style={{ fontSize: 14, margin: "8px 0 0" }} aria-live="polite">
              {loading || total === null ? "加载中…" : `${total.toLocaleString()} 篇`} · {SORTS.find((s) => s.id === sort)?.note}
              {all ? " · 含候选层（2 人 2 个月，显示“被提及”）" : " · 只看主书架"}
            </p>
          </div>
          <div className="seg-pill" role="group" aria-label="显示方式">
            <Link href={h({ view: undefined })} aria-current={view === "grid"}>封面</Link>
            <Link href={h({ view: "list" })} aria-current={view === "list"}>列表</Link>
          </div>
        </div>

        {/* 手机上：领域和类目用横向滚动的分段 */}
        <div className="lg:hidden" style={{ marginTop: 14 }}>
          <div className="chips scroll">
            <Link href={h({ area: undefined, topic: undefined })} aria-current={!area}>全部领域</Link>
            {areas.map((a) => <Link key={a.id} href={h({ area: a.id, topic: undefined })} aria-current={area?.id === a.id}>{a.nameZh}</Link>)}
          </div>
          {area && (
            <div className="chips scroll" style={{ marginTop: 8 }}>
              <Link href={h({ area: area.id, topic: undefined })} aria-current={!topic}>全部类目</Link>
              {area.topics.filter((t) => count(t) > 0).map((t) => (
                <Link key={t.id} href={h({ topic: t.id, area: undefined })} aria-current={topic?.id === t.id}>{t.nameZh}</Link>
              ))}
            </div>
          )}
        </div>

        <div className="filters" style={{ marginTop: 22 }}>
          <div className="filter-row">
            <span className="filter-label">排序</span>
            <div className="chips scroll">
              {SORTS.map((s) => <Link key={s.id} href={h({ sort: s.id === "score" ? undefined : s.id })} aria-current={sort === s.id}>{s.name}</Link>)}
            </div>
          </div>
          <div className="filter-row"><span className="filter-label">年代</span>{seg("decade", DECADES)}</div>
          <div className="filter-row"><span className="filter-label">难度</span>{seg("difficulty", DIFF)}</div>
          <div className="filter-row"><span className="filter-label">时效</span>{seg("shelf", [["evergreen", "经得起时间"], ["dated", "有时效性"]])}</div>
          <div className="filter-row">
            <span className="filter-label">范围</span>
            <div className="chips scroll">
              <Link href={h({ tier: undefined })} aria-current={!all}>主书架</Link>
              <Link href={h({ tier: "all" })} aria-current={all}>含候选层</Link>
              <Link href={h({ positive: state.positive === "1" ? undefined : "1" })} aria-current={state.positive === "1"}>只看有推荐的</Link>
              <Link href={h({ path: state.path === "1" ? undefined : "1" })} aria-current={state.path === "1"}>有学习路径</Link>
            </div>
          </div>
        </div>

        <div style={{ marginTop: 36, opacity: loading ? 0.5 : 1, transition: "opacity .2s" }}>
          {view === "grid" ? (
            <Shelf areaNames={areaNames} items={items.map((p, i) => {
              const l = recLabel(p);
              return {
                paper: p,
                label: (
                  <>
                    <span className="shelf-note"><span className="t-display" style={{ fontSize: 15, color: "var(--ink2)" }}>{(page - 1) * PER_PAGE + i + 1}</span> · {l.positive ? "被推荐" : "被提及"} · {p.people} 人</span>
                    {p.tier === "cand" && <span className="shelf-note">候选</span>}
                  </>
                ),
              };
            })} />
          ) : (
            <ol className="entries entries--list">
              {items.map((p) => (
                <li key={p.id}>
                  <Entry paper={p} areaZh={p.area ? areaNames[p.area] : null}>
                    {p.oneliner && <span style={{ fontSize: 14, lineHeight: 1.6, color: "var(--ink2)" }}>{p.oneliner}</span>}
                  </Entry>
                </li>
              ))}
            </ol>
          )}
        </div>
        {!loading && total === 0 && <p className="muted" style={{ padding: "30px 0" }}>没有符合条件的论文。难度和时效只有主书架的论文有（来自卡片）。</p>}

        {pages > 1 && (
          <div style={{ display: "flex", gap: 12, alignItems: "center", justifyContent: "center", marginTop: 40, fontSize: 14 }}>
            {page > 1 ? <Link className="btn btn-sm" href={h({ page: String(page - 1) })}>← 上一页</Link> : <span />}
            <span className="faint">{page} / {pages}</span>
            {page < pages ? <Link className="btn btn-sm" href={h({ page: String(page + 1) })}>下一页 →</Link> : <span />}
          </div>
        )}
      </section>
    </div>
  );
}
