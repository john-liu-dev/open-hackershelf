"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { AREA_COLORS, COVER_ACCENT, COVER_FALLBACK } from "@/lib/cover";
import { withBase } from "@/lib/site";
import type { ShelfBook } from "@/lib/topshelf";

/**
 * 首页“一排真书”（2026-11-06，替换 1,800 根书脊的天际线；那一版留在 Skyline.tsx，以后给关于页当插图）。
 * - 只摆长青榜前 N 篇：N 按宽度算，每本约 15px（桌面最多 72 本，手机约 22 本），按第一次被 HN 提到的时间从左到右。
 * - 书脊宽 10–14px（按编号固定），高度按人数开方、在这 N 本里归一到 58–110px；颜色是领域；金色给名次最前的约十分之一。
 * - 书脊上下各一条细线（白 24%，金书用深色 35%），像站标里那本金书；最后一本斜靠 9°。
 * - 鼠标移上去：这本抬起 7px，上方提示“No.x · 标题 · 年份 · N 人”；点击进详情页。
 * - 第一次加载时一本本立起来（约 1.3 秒），每台设备只播一次（localStorage hs-shelf）；prefers-reduced-motion 时不播。
 * SVG 在浏览器里按宽度画（服务端只占位，高度固定，不会挤动下面的内容）。
 */
const PITCH = 15; // 每本约占 15px（含间隙）
const GAP = 3;
const H_MIN = 58, H_MAX = 110, LIFT = 7, LEAN = 9;
const SVG_H = H_MAX + LIFT + 6;
const BASE = SVG_H; // 书立在 SVG 底边上，下面接横板
const STAND_MS = 1300, EACH_MS = 450;
const SEEN = "hs-shelf";
const AREAS = Object.keys(AREA_COLORS);
const S = Math.sin((LEAN * Math.PI) / 180), C = Math.cos((LEAN * Math.PI) / 180);

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
/** 深色模式提亮一档：往白色混 22% */
const lift = (hex: string, t = 0.22) => `rgb(${rgb(hex).map((c) => Math.round(c + (255 - c) * t)).join(",")})`;

type Placed = ShelfBook & { x: number; h: number; gold: boolean; lean?: { xr: number } };

/** 按宽度取前 N 本、排好位置；最后一本斜靠在前一本上（左边沿顶着前一本的右上角或侧面） */
function layout(books: ShelfBook[], W: number): Placed[] {
  for (let n = Math.min(books.length, Math.max(8, Math.floor(W / PITCH))); n >= 8; n--) {
    const top = books.slice(0, n);
    const nGold = Math.round(n / 10);
    const sq = top.map((b) => Math.sqrt(b.p));
    const lo = Math.min(...sq), hi = Math.max(...sq);
    const order = [...top].sort((a, b) => (a.f < b.f ? -1 : a.f > b.f ? 1 : a.r - b.r));
    let x = 0;
    const out: Placed[] = order.map((b) => {
      const h = Math.round(H_MIN + (hi > lo ? (Math.sqrt(b.p) - lo) / (hi - lo) : 0.5) * (H_MAX - H_MIN));
      const p: Placed = { ...b, x, h, gold: b.r <= nGold };
      x += b.w + GAP;
      return p;
    });
    const last = out[out.length - 1], prev = out[out.length - 2];
    const prevRight = prev.x + prev.w + 1;
    // 左上角顶着前一本的侧面；要是这本更高，就用左边沿压在前一本的右上角上
    let xr = prevRight + C * last.w + S * last.h;
    if (C * last.h - S * last.w > prev.h) xr = prevRight + C * last.w + S * ((prev.h + S * last.w) / C);
    last.x = xr - last.w;
    last.lean = { xr };
    if (xr <= W - 2) return out;
  }
  return [];
}

export function TopShelf({ books }: { books: ShelfBook[] }) {
  const wrap = useRef<HTMLDivElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(0);
  const [standing, setStanding] = useState(false);
  const [hover, setHover] = useState<Placed | null>(null);
  const placed = useMemo(() => (W ? layout(books, W) : []), [books, W]);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    let seen = true;
    try {
      seen = localStorage.getItem(SEEN) === "1";
      localStorage.setItem(SEEN, "1");
    } catch {}
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let timer = 0;
    if (!seen && !reduce) {
      setStanding(true);
      timer = window.setTimeout(() => setStanding(false), STAND_MS + 200);
    }
    setW(el.clientWidth);
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => {
      ro.disconnect();
      clearTimeout(timer);
    };
  }, []);

  // 提示条居中对准这本书，不超出左右边
  useLayoutEffect(() => {
    const t = tip.current;
    if (!t || !hover) return;
    const cx = hover.lean ? hover.lean.xr - (C * hover.w) / 2 - (S * hover.h) / 2 : hover.x + hover.w / 2;
    t.style.left = `${Math.max(0, Math.min(W - t.offsetWidth, cx - t.offsetWidth / 2))}px`;
  }, [hover, W]);

  const n = placed.length;
  return (
    <div className="topshelf" ref={wrap}>
      <div className="topshelf-tip" ref={tip} hidden={!hover} aria-hidden="true">
        {hover && `No.${hover.r} · ${hover.t} · ${hover.y ?? "—"} · ${hover.p} 人`}
      </div>
      <svg className={standing ? "topshelf-svg is-standing" : "topshelf-svg"} width={W || undefined} height={SVG_H}
        viewBox={`0 0 ${W || 1} ${SVG_H}`} aria-hidden="true">
        {placed.map((b, k) => {
          const color = b.gold ? COVER_ACCENT : (AREA_COLORS[AREAS[b.a]] ?? COVER_FALLBACK);
          const band = Math.max(5, Math.round(b.h * 0.1));
          const line = b.gold ? "rgba(22,24,29,0.35)" : "rgba(255,255,255,0.24)";
          const book = (
            <a href={withBase(`/p/${b.s}/`)} className="bk-link" tabIndex={-1}
              onMouseEnter={() => setHover(b)} onMouseLeave={() => setHover((h) => (h === b ? null : h))}>
              <g className="bk-lift">
                <g className="bk-stand" style={standing ? { animationDelay: `${Math.round((k / n) * (STAND_MS - EACH_MS))}ms` } : undefined}>
                  <rect className="bk-body" x={b.x} y={BASE - b.h} width={b.w} height={b.h} rx={1.5}
                    style={{ ["--c" as string]: color, ["--cd" as string]: b.gold ? lift(COVER_ACCENT, 0.06) : lift(color) }} />
                  <rect x={b.x} y={BASE - b.h + band} width={b.w} height={1.6} fill={line} />
                  <rect x={b.x} y={BASE - band - 1.6} width={b.w} height={1.6} fill={line} />
                </g>
              </g>
            </a>
          );
          return b.lean ? <g key={b.s} transform={`rotate(${-LEAN} ${b.lean.xr} ${BASE})`}>{book}</g> : <g key={b.s}>{book}</g>;
        })}
      </svg>
      <div className="topshelf-plank" aria-hidden="true" />
      <div className="topshelf-note">{n ? `长青榜前 ${n} 篇 · 按第一次被 HN 提到的时间摆放` : " "}</div>
    </div>
  );
}
