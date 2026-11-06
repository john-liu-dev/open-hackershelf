"use client";

import { useEffect, useState } from "react";
import { COVER_ACCENT, COVER_FILL, COVER_STROKE, coverSpec } from "@/lib/cover";

/**
 * 公开站（D46）的封面图案：在浏览器里按编号算出来再画，HTML 和水合数据里只留编号。
 * 图案只取决于编号（coverSpec 的随机数种子），每个封面能省下约 2 KB × 2；底色和文字仍在服务端渲染。
 */
export function CoverArt({ id }: { id: string }) {
  const [d, setD] = useState<{ stroke: string; fill: string; accent: string } | null>(null);
  useEffect(() => {
    const s = coverSpec(id, null, "", null);
    // 图案是按编号算的装饰，挂载后再画，不进静态 HTML
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setD({ stroke: s.stroke, fill: s.fill, accent: s.accent });
  }, [id]);
  return (
    <svg viewBox="0 0 200 300" preserveAspectRatio="xMidYMid slice" className="cover-art" aria-hidden="true">
      {d && (
        <>
          <path d={d.stroke} fill="none" stroke={COVER_STROKE} strokeWidth={1.1} />
          <path d={d.fill} fill={COVER_FILL} />
          <path d={d.accent} fill={COVER_ACCENT} />
        </>
      )}
    </svg>
  );
}
