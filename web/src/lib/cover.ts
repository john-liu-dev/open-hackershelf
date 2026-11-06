/**
 * 论文封面生成：同一个 ID 永远得到同一张封面。
 *
 * 算法与设计画布「HackerShelf 样式探索」B 行样稿一致（参考源码见 docs/design/reference/）。
 * 来源：docs/design/cover.ts（设计稿原件，改动要两边一起改）。coverSpec(item.id, item.area, item.title, item.title_zh)
 * 的结果交给 <Cover> 组件渲染（版式见 docs/DESIGN.md 第 4 节）。
 *
 * SVG 坐标系 200×300（2:3），preserveAspectRatio="xMidYMid slice"。
 * 只依赖 ID、领域和标题，不读论文内容，所以没有版权问题，服务端渲染即可，不生成图片文件。
 */

export type PatternKind = 'rings' | 'lines' | 'dots' | 'bands' | 'waves';

/** 领域底色。键是 catalog.db 里 items.area 的值。 */
export const AREA_COLORS: Record<string, string> = {
  llm: '#2c4a7a', // 大模型与语言模型
  ml: '#1d6b66', // 机器学习与深度学习
  physics: '#5a3d8a', // 物理与量子
  perception: '#a84b2a', // 视觉、语音与图像生成
  'ai-safety': '#7f2d3c', // AI 安全、伦理与社会影响
  math: '#23493c', // 数学、逻辑与理论
  security: '#3a3c42', // 安全、隐私与密码学
  'rl-agents': '#8f6516', // 强化学习与智能体
  systems: '#2b5c86', // 系统、数据库与网络
  society: '#6e5238', // 社会、经济与科学研究
  space: '#1c2846', // 天文、太空与生命
  pl: '#6a2e66', // 编程语言与编译器
  se: '#3d6a2c', // 软件工程与 AI 编程
  algo: '#9c3a2b', // 算法与数据结构
};

export const COVER_FALLBACK = '#333333';
/** 点缀色：所有封面共用，像同一套丛书。 */
export const COVER_ACCENT = '#f2c14e';
/** 线条图案：fill none，stroke-width 1.1。 */
export const COVER_STROKE = 'rgba(255,255,255,0.3)';
/** 填充图案。 */
export const COVER_FILL = 'rgba(255,255,255,0.2)';

export interface CoverSpec {
  bg: string;
  pattern: PatternKind;
  /** 线条图案 path，用 COVER_STROKE 描边 */
  stroke: string;
  /** 填充图案 path，用 COVER_FILL 填充 */
  fill: string;
  /** 点缀 path，用 COVER_ACCENT 填充 */
  accent: string;
  /** 英文主标题字号，单位 cqw（封面容器设 container-type: inline-size） */
  titleSize: number;
  /** 英文标题冒号前的部分 */
  mainTitle: string;
  /** 中文标题全角冒号前的部分 */
  zhMain: string;
}

const PATTERNS: PatternKind[] = ['rings', 'lines', 'dots', 'bands', 'waves'];

/** FNV-1a，32 位。 */
function hashId(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** xorshift32，返回 [0, 1)。调用顺序决定结果，改动会让所有封面变样。 */
function makeRng(seed: number): () => number {
  let s = seed || 7;
  return () => {
    s ^= s << 13;
    s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5;
    s >>>= 0;
    return (s % 10000) / 10000;
  };
}

const f1 = (n: number): number => Math.round(n * 10) / 10;

const circ = (cx: number, cy: number, r: number): string =>
  `M${f1(cx - r)} ${f1(cy)}a${f1(r)} ${f1(r)} 0 1 0 ${f1(2 * r)} 0a${f1(r)} ${f1(r)} 0 1 0 ${f1(-2 * r)} 0`;

export function coverSpec(id: string, area: string | null | undefined, title: string, titleZh?: string | null): CoverSpec {
  const h = hashId(id);
  const r = makeRng(h);
  const k = h % 5;
  let stroke = 'M0 0';
  let fill = 'M0 0';
  let accent = 'M0 0';

  if (k === 0) {
    // rings：一组同心圆，圆心在下半部
    const cx = 30 + r() * 140;
    const cy = 200 + r() * 60;
    stroke = '';
    for (let i = 1; i < 13; i++) stroke += circ(cx, cy, i * 16);
    accent = circ(cx + 48 * (r() < 0.5 ? 1 : -1), cy - 10, 10 + r() * 6);
  } else if (k === 1) {
    // lines：平行斜线 + 一条金色横带
    const sl = (r() - 0.5) * 1.4;
    stroke = '';
    for (let i = -14; i < 26; i++) {
      const x = i * 12;
      stroke += `M${x} 100L${f1(x + sl * 200)} 300`;
    }
    accent = `M0 ${f1(190 + r() * 50)}h200v12h-200z`;
  } else if (k === 2) {
    // dots：点阵，少数大点用金色
    fill = '';
    accent = '';
    for (let yy = 0; yy < 9; yy++) {
      for (let xx = 0; xx < 8; xx++) {
        const big = r() < 0.1;
        const d = circ(16 + xx * 24, 116 + yy * 19, big ? 5.5 : 1.8);
        if (big) accent += d;
        else fill += d;
      }
    }
    if (!accent) accent = circ(112, 172, 5.5);
  } else if (k === 3) {
    // bands：粗细不一的横条
    fill = '';
    let y = 100;
    while (y < 300) {
      const t = 1 + r() * 7;
      fill += `M0 ${f1(y)}h200v${f1(t)}h-200z`;
      y += t + 4 + r() * 12;
    }
    accent = `M0 ${f1(160 + r() * 70)}h200v16h-200z`;
  } else {
    // waves：十条正弦波 + 金色圆点
    stroke = '';
    for (let j = 0; j < 10; j++) {
      const y0 = 120 + j * 16;
      const A = 4 + r() * 9;
      const L = 24 + r() * 36;
      const ph = r() * 6;
      let d = `M0 ${f1(y0)}`;
      for (let x = 10; x <= 200; x += 10) d += `L${x} ${f1(y0 + A * Math.sin(x / L + ph))}`;
      stroke += d;
    }
    accent = circ(140 + r() * 30, 150 + r() * 30, 15);
  }

  const mainTitle = title.split(/:\s+/)[0];
  const n = mainTitle.length;
  const titleSize = n <= 18 ? 12.5 : n <= 30 ? 10.5 : n <= 46 ? 8.6 : 7.2;

  return {
    bg: (area && AREA_COLORS[area]) || COVER_FALLBACK,
    pattern: PATTERNS[k],
    stroke,
    fill,
    accent,
    titleSize,
    mainTitle,
    zhMain: (titleZh ?? '').split('：')[0],
  };
}
