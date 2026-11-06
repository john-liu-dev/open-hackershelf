import type { Metadata, Viewport } from "next";
import { CjkFonts } from "@/components/CjkFonts";
import { Keyboard } from "@/components/Keyboard";
import { fontVars } from "@/lib/fonts";
import { PUBLIC_SITE_URL } from "@/lib/site";
import "./globals.css";

const DESCRIPTION = "Hacker News 上被不同的人在不同月份反复推荐的论文：中文导读、HN 原话、学习路径。";
// 通用分享图（og-images.mjs 生成）；主书架的论文详情页换成各自的封面
const OG_IMAGE = { url: `${PUBLIC_SITE_URL}/og.png`, width: 1200, height: 630, alt: "HackerShelf" };

// 公开站（D46）：默认不让搜索引擎收录（和旧站一样）；要收录改 robots 这一行。分享卡片不受影响。
export const metadata: Metadata = {
  metadataBase: new URL(`${PUBLIC_SITE_URL}/`),
  title: { default: "HackerShelf", template: "%s · HackerShelf" },
  description: DESCRIPTION,
  robots: { index: false, follow: false },
  openGraph: { type: "website", siteName: "HackerShelf", locale: "zh_CN", title: "HackerShelf", description: DESCRIPTION, images: [OG_IMAGE] },
  twitter: { card: "summary_large_image", title: "HackerShelf", description: DESCRIPTION, images: [OG_IMAGE.url] },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#121316" },
    { media: "(prefers-color-scheme: light)", color: "#f2f2f0" },
  ],
};

// 深浅色（设计 v2）：?mode= 参数优先（截图用），其次本机记住的选择（按 t 切换），否则跟随系统。首帧前设置，避免闪烁。
// 没有 JS 时由 globals.css 里的 prefers-color-scheme 兜底。
const THEME_SCRIPT = `(function(){try{var u=new URL(location.href),s=localStorage,q=u.searchParams.get('mode'),m=q||s.getItem('hs-mode')||'';var h=document.documentElement;h.dataset.mode=m||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');if(q){s.setItem('hs-mode',q);s.removeItem('hs-paper')}}catch(e){}})()`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" className={fontVars} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        {children}
        <Keyboard />
        <CjkFonts />
      </body>
    </html>
  );
}
