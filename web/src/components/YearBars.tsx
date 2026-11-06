/** 逐年提及柱状图（B2）：每年一根，峰值年金色，其他 --ink3。 */
export function YearBars({ byYear, from, to }: { byYear: Record<string, number>; from: number; to: number }) {
  const years: number[] = [];
  for (let y = from; y <= to; y++) years.push(y);
  const vals = years.map((y) => byYear[String(y)] ?? 0);
  const max = Math.max(1, ...vals);
  const peak = vals.indexOf(max);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="eyebrow">按年被提到</div>
      <div className="bars" role="img" aria-label={`按年提及：${years.map((y, i) => `${y} 年 ${vals[i]} 次`).join("，")}`}>
        {vals.map((v, i) => (
          <div key={years[i]} title={`${years[i]}：${v} 次`}
            style={{ height: v ? Math.round(4 + (v / max) * 62) : 2, background: i === peak ? "var(--acc)" : v ? "var(--ink3)" : "var(--rule)" }} />
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--ink3)" }}>
        <span>{from}</span>
        <span>{years[peak]} · {max} 次</span>
        <span>{to}</span>
      </div>
    </div>
  );
}
