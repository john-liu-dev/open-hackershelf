/**
 * 解析小工具（不碰文件和网络，方便单测）：arXiv RSS / Atom 的 XML 字段、HTML 实体、arXiv 编号。
 * arXiv 的 RSS、Atom 格式固定，用正则取字段就够了，不引入 XML 库。
 */
const NAMED = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
export function decodeEntities(s) {
  return s
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
      if (e[0] === "#") {
        const n = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
        return Number.isFinite(n) ? String.fromCodePoint(n) : m;
      }
      return NAMED[e.toLowerCase()] ?? m;
    });
}
const esc = (n) => n.replace(/[.:]/g, (c) => `\\${c}`);
export function xmlTag(xml, name) {
  const m = xml.match(new RegExp(`<${esc(name)}(?:\\s[^>]*)?>([\\s\\S]*?)</${esc(name)}>`));
  return m ? decodeEntities(m[1]).trim() : null;
}
export function xmlTags(xml, name) {
  return [...xml.matchAll(new RegExp(`<${esc(name)}(?:\\s[^>]*)?>([\\s\\S]*?)</${esc(name)}>`, "g"))].map((m) => decodeEntities(m[1]).trim());
}
export function xmlAttrs(xml, name, attr) {
  return [...xml.matchAll(new RegExp(`<${esc(name)}\\s[^>]*?${attr}="([^"]*)"`, "g"))].map((m) => decodeEntities(m[1]));
}
export const squash = (s) => (s ?? "").replace(/\s+/g, " ").trim();

const NEW_ID = /(\d{4}\.\d{4,5})(?:v\d+)?/;
const OLD_ID = /([a-z-]+(?:\.[A-Z]{2})?\/\d{7})(?:v\d+)?/;
/** 从 arXiv 链接里取规范编号（去掉版本号），取不到返回 null。 */
export function arxivFromUrl(url) {
  const m = String(url ?? "").match(/arxiv\.org\/(?:abs|pdf|html|format)\/([^?#\s"'<>]+)/i);
  if (!m) return null;
  const raw = m[1].replace(/\.pdf$/i, "");
  const a = raw.match(new RegExp(`^${NEW_ID.source}`)) || raw.match(new RegExp(`^${OLD_ID.source}`));
  return a ? a[1] : null;
}
export function normArxiv(id) {
  const s = String(id ?? "").replace(/^arxiv:/i, "");
  const a = s.match(new RegExp(`^${NEW_ID.source}$`)) || s.match(new RegExp(`^${OLD_ID.source}$`));
  return a ? a[1] : null;
}
