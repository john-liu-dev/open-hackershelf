import { BOOK_COLORS } from "@/lib/book-colors";
import { COVER_ACCENT, COVER_FILL, COVER_STROKE, coverSpec } from "@/lib/cover";
import { PUBLIC } from "@/lib/site";
import { CoverArt } from "./CoverArt";

/** 封面需要的最少字段（服务端 Paper 和前端搜索索引都能凑出来）。sub：右下角的字，开源书写短作者名（论文那里是年份）。 */
export type CoverInput = { id: string; area: string | null; title: string; titleZh: string | null; year: number | null; sub?: string | null };

/**
 * 尺寸档（docs/DESIGN.md 第 4 节）：外框宽度由父元素决定，字号用 cqw 跟着宽度走。
 * spot 首页聚光 300px · detail 详情页 360px · shelf 书架 150–170px · area 领域行 128–148px · list 列表 84px · mini 阅读页顶栏 22px
 */
export type CoverSize = "spot" | "detail" | "shelf" | "area" | "list" | "mini";

// 领域名 / 中文主标题 / 年份的字号（cqw），照参考稿：大封面略小，领域行略大
const TYPE: Record<Exclude<CoverSize, "list" | "mini">, [number, number, number]> = {
  spot: [4.6, 5.4, 4.6],
  detail: [4.4, 5.2, 4.4],
  shelf: [5, 6, 5],
  area: [5.4, 6.4, 5.4],
};

/**
 * 标题字号按设计算法（spec.titleSize）；只在两种情况下再收小一点，只影响渲染，不改 coverSpec（它和设计稿逐字一致）：
 * 1. 单词太长（如 "TheAgentCompany"），按最长单词的宽度收，避免单词被从中间断开；
 * 2. 标题太长（110 个字符以上），按整段宽度收，保证不超过行数上限（书架 6 行、列表 8 行）。
 * 宽度按 Fraunces 600 小字号实测偏保守地估：大写 0.78em、小写和数字 0.64em、空格 0.22em、其他 0.45em
 * （小字号时 opsz 轴让字形变宽；m、w 这类宽字母比平均宽）。
 */
const em = (c: string) => (/[A-Z]/.test(c) ? 0.78 : /[a-z0-9]/.test(c) ? 0.64 : c === " " ? 0.22 : 0.45);

export function fitTitleSize(title: string, size: number, avail: number, maxLines: number): number {
  const words = title.split(/\s+/).filter(Boolean);
  if (!words.length) return size;
  const longest = Math.max(...words.map((w) => Array.from(w).reduce((n, c) => n + em(c), 0)));
  const total = Array.from(title).reduce((n, c) => n + em(c), 0);
  // 换行浪费按 20% 算
  const cap = Math.min(avail / longest, (avail * maxLines) / (total * 1.2));
  return Math.min(size, Math.floor(cap * 10) / 10);
}

/**
 * 封面下方的中文主标题：去掉括号里的英文原名（英文标题已经印在上面），太长时在第一个问号后截断。
 * 只影响渲染，coverSpec 的 zhMain 不变。
 */
export function coverZh(zh: string): string {
  let t = zh.replace(/（[^（）]*[A-Za-z][^（）]*）/g, "").trim();
  const q = t.search(/[？！]/);
  if (t.length > 22 && q > 3 && q < t.length - 1) t = t.slice(0, q + 1);
  return t || zh;
}

/**
 * 封面右下角的作者名里有扩展拉丁字母（Lipovača 的 č）时用系统字体：DM Sans 的扩展拉丁子集要多下 18 KB，
 * 首页那一排开源书里有一本就会让手机 Lighthouse 掉 2 分（2026-11-06 实测）。名字照原样写，不改拼法。
 */
const LATIN_EXT = /[\u0100-\u02ff\u1e00-\u1eff]/;

const channel = (c: number) => {
  const v = c / 255;
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};
const luminance = ([r, g, b]: number[]) => 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

/**
 * 封面上半透明白字（领域名、年份、中文名）的不透明度：设计稿给的是 72% / 70% / 90%，
 * 但在金棕、橙这类较亮的底色上达不到 WCAG 4.5:1。按底色算出达到 target 所需的最小不透明度，和设计值取大的（只调高、不调低）。
 * 只影响渲染，coverSpec 不变。
 */
export function mutedAlpha(bg: string, base: number, target = 4.6): number {
  const b = rgb(bg);
  const lb = luminance(b);
  for (let a = Math.round(base * 100); a <= 100; a++) {
    const fg = b.map((c) => Math.round((a / 100) * 255 + (1 - a / 100) * c));
    if ((luminance(fg) + 0.05) / (lb + 0.05) >= target) return a / 100;
  }
  return 1;
}

export function Cover({ paper, areaZh, size = "shelf", className = "" }: { paper: CoverInput; areaZh?: string | null; size?: CoverSize; className?: string }) {
  const spec0 = coverSpec(paper.id, paper.area, paper.title, paper.titleZh);
  // 开源书的底色按书架分类（lib/book-colors.ts）；论文照设计稿的 coverSpec
  const spec = paper.area && BOOK_COLORS[paper.area] ? { ...spec0, bg: BOOK_COLORS[paper.area] } : spec0;
  if (size === "mini") {
    return <div className={`cover cover--mini ${className}`} style={{ background: spec.bg }} aria-hidden="true" />;
  }
  // 公开站：图案在浏览器里画（见 CoverArt），静态页面小三成
  const art = PUBLIC ? <CoverArt id={paper.id} /> : (
    <svg viewBox="0 0 200 300" preserveAspectRatio="xMidYMid slice" className="cover-art" aria-hidden="true">
      <path d={spec.stroke} fill="none" stroke={COVER_STROKE} strokeWidth={1.1} />
      <path d={spec.fill} fill={COVER_FILL} />
      <path d={spec.accent} fill={COVER_ACCENT} />
    </svg>
  );
  if (size === "list") {
    return (
      <div className={`cover cover--list ${className}`} style={{ background: spec.bg }} aria-hidden="true">
        {art}
        <div className="cover-top" style={{ background: spec.bg }}>
          <div className="cover-title" style={{ fontSize: `${fitTitleSize(spec.mainTitle, spec.titleSize, 79, 8)}cqw` }}>{spec.mainTitle}</div>
        </div>
        <div className="cover-spine" />
      </div>
    );
  }
  const [fa, fz, fy] = TYPE[size];
  return (
    // 封面是装饰：标题文字在旁边的链接里已经有了，这里对读屏隐藏
    <div className={`cover cover--${size} ${className}`} aria-hidden="true" data-cover={paper.id}
      style={{ background: spec.bg, ["--cover-area-a" as string]: mutedAlpha(spec.bg, 0.72), ["--cover-zh-a" as string]: mutedAlpha(spec.bg, 0.9), ["--cover-year-a" as string]: mutedAlpha(spec.bg, 0.7) }}>
      {art}
      <div className="cover-top" style={{ background: spec.bg }}>
        {areaZh && <div className="cover-area" style={{ fontSize: `${fa}cqw` }}>{areaZh}</div>}
        <div className="cover-title" style={{ fontSize: `${fitTitleSize(spec.mainTitle, spec.titleSize, 81, 6)}cqw` }}>{spec.mainTitle}</div>
      </div>
      <div className="cover-bottom" style={{ background: spec.bg }}>
        <div className="cover-zh" style={{ fontSize: `${fz}cqw` }}>{coverZh(spec.zhMain)}</div>
        {(paper.sub || paper.year) && (
          <div className="cover-year" style={{ fontSize: `${fy}cqw`, ...(paper.sub && LATIN_EXT.test(paper.sub) ? { fontFamily: "system-ui, sans-serif" } : {}) }}>
            {paper.sub || paper.year}
          </div>
        )}
      </div>
      <div className="cover-spine" />
    </div>
  );
}
