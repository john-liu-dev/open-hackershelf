/**
 * 字体（docs/DESIGN.md 第 2 节），next/font/google 构建期下载、自托管，运行时不请求 Google。
 * - Fraunces：书外（封面、书架、详情页标题、数字）；DM Sans：界面文字。只预加载 DM Sans 的拉丁子集；
 *   Fraunces（正体、斜体）不预加载，页面排版用到时才下载（阅读页用不到）。
 * - 中文：先用苹果系统字体 Songti SC（标题、中文正文）和 PingFang SC（界面），见 globals.css 的 --f-* token。
 *   Noto Serif SC / Noto Sans SC 只给没有这两个字体的设备兜底，声明在 components/fonts/ 里按需加载（见 CjkFonts.tsx），
 *   不进首屏 CSS、不预加载。
 * - Newsreader（书内）只在阅读页用，单独在 src/app/read/fonts.ts 里声明，其他页面不加载。
 */
import { DM_Sans, Fraunces } from "next/font/google";

// 不预加载：书架类页面首屏就有 Fraunces 标题，排版时就会请求；阅读页用不到它，预加载等于白下 66 KB
export const fraunces = Fraunces({
  subsets: ["latin"],
  axes: ["opsz"],
  style: ["normal"],
  variable: "--font-fraunces",
  display: "swap",
  preload: false,
});

// 斜体单独声明：@font-face 的族名同样是 Fraunces（font-style: italic），不预加载，页面上真有斜体时才下载。
// 用 variable 而不是 className 挂到 <html> 上：className 会把整页设成斜体。
export const frauncesItalic = Fraunces({
  subsets: ["latin"],
  axes: ["opsz"],
  style: ["italic"],
  variable: "--font-fraunces-italic",
  display: "swap",
  preload: false,
});

// 界面字都在 12–17px，用默认光学尺寸就够（不带 opsz 轴，文件小一截）
export const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-dm-sans",
  display: "swap",
});

export const fontVars = [fraunces.variable, frauncesItalic.variable, dmSans.variable].join(" ");
