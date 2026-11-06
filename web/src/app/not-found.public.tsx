import Link from "next/link";
import { Footer, Header } from "@/components/Header";

export const metadata = { title: "没有这一页" };

/** 公开站的 404（导出成 404.html，GitHub Pages 找不到页面时用它）。 */
export default function NotFound() {
  return (
    <>
      <Header />
      <main className="wrap" style={{ paddingTop: 72, paddingBottom: 72, display: "flex", flexDirection: "column", gap: 16 }}>
        <h1 className="t-zh" style={{ margin: 0, fontSize: 36, fontWeight: 600 }}>没有这一页</h1>
        <p className="muted" style={{ margin: 0 }}>
          可能是链接打错了，或者这篇论文已经不在书架上。去<Link href="/" className="acct">首页</Link>，或者<Link href="/search" className="acct">搜索</Link>一下。
        </p>
      </main>
      <Footer />
    </>
  );
}
