import { Noto_Serif_SC } from "next/font/google";

/**
 * Noto Serif SC 的 @font-face 声明（3 个字重 × 约 100 个 unicode-range 分片，CSS 约 280 KB）。
 * 这个模块只由 CjkFonts 在设备没有 Songti SC 时按需加载；字体栈里直接写族名 "Noto Serif SC"（globals.css 的 --font-noto-serif-sc）。
 */
const noto = Noto_Serif_SC({ weight: ["500", "600", "700"], display: "swap", preload: false });

export default function NotoSerif() {
  return <span hidden className={noto.className} />;
}
