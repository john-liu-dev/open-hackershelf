/** 论文编号和 URL 片段互转（服务端和浏览器都能用，不碰数据库）。 */
export const idFromSlug = (parts: string[]) => `arxiv:${parts.map(decodeURIComponent).join("/")}`;
export const slugFromId = (id: string) => id.replace(/^arxiv:/, "");
