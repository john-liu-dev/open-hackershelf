import { Suspense } from "react";
import { Footer, Header } from "@/components/Header";
import { FreshClient } from "@/components/public/FreshClient";
import { PreloadData } from "@/components/public/PreloadData";
import { withBase } from "@/lib/site";

export const metadata = { title: "新鲜" };

/**
 * 公开站的新鲜书架（D46）：公开仓库的 GitHub Actions 每天抓 Hugging Face 热门、HN 在讨论的、关注的 arXiv 分类，
 * 写 fresh.json；页面在浏览器里读它。不调用模型，只显示来源给的标题和摘要。
 */
export default function FreshPage() {
  return (
    <>
      <Header active="fresh" />
      <main className="wrap" style={{ paddingTop: 48, minHeight: "100vh" }}>
        <PreloadData href={withBase("/fresh.json")} />
        <div className="home-title">
          <h1 className="t-zh" style={{ fontSize: "clamp(36px, 5vw, 56px)" }}>新鲜</h1>
        </div>
        <Suspense fallback={<p className="faint" style={{ marginTop: 32 }}>加载中…</p>}>
          <FreshClient />
        </Suspense>
      </main>
      <Footer />
    </>
  );
}
