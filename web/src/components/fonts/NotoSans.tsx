import { Noto_Sans_SC } from "next/font/google";

/**
 * Noto Sans SC 的 @font-face 声明（2 个字重 × 约 100 个分片，CSS 约 190 KB）。
 * 只由 CjkFonts 在设备没有 PingFang SC 时按需加载；字体栈里直接写族名 "Noto Sans SC"（globals.css 的 --font-noto-sans-sc）。
 */
const noto = Noto_Sans_SC({ weight: ["400", "500"], display: "swap", preload: false });

export default function NotoSans() {
  return <span hidden className={noto.className} />;
}
