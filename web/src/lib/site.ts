/**
 * 构建形态（D46）：HS_PUBLIC=1 时是 GitHub Pages 上的公开静态站，只有发现层。
 * NEXT_PUBLIC_* 在构建期内联进服务端和浏览器的代码，公开站的包里不会留下旧站的分支。
 */
export const PUBLIC = process.env.NEXT_PUBLIC_HS_PUBLIC === "1";

/** 公开站的 basePath（"/shelf"）；旧站是空串。<Link> 和 router 会自己加，fetch 和 <a href> 要用 withBase。 */
export const BASE = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export const withBase = (p: string) => `${BASE}${p}`;

/** 公开站的完整地址（Obsidian 笔记里的链接、提示词里的链接用它）。 */
export const PUBLIC_SITE_URL = "https://john-liu-dev.github.io/shelf";
