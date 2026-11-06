/**
 * 公开站详情页的两个按钮：“复制 Markdown 笔记”（属性、导读、HN 原话，能贴进任何笔记软件）和“复制提问提示词”。
 * 纯函数，服务端（构建期算文件名）和浏览器（点按钮时生成内容）都用它。
 */

export const NOTE_DIR = "论文";

const BAD = /[/\\:*?"<>|#^[\]]/g;

/** 英文主标题（第一个冒号前），去掉文件名里不能用的字符和开头的点，最长 100 个字符。 */
export function baseName(title: string): string {
  let t = (title.includes(":") ? title.slice(0, title.indexOf(":")) : title).normalize("NFC");
  t = t.replace(BAD, "").replace(/\s+/g, " ").trim().replace(/^\.+/, "").trim();
  const chars = Array.from(t);
  if (chars.length > 100) t = chars.slice(0, 100).join("").trimEnd();
  return t || "untitled";
}

const folded = (s: string) => s.normalize("NFC").toLowerCase();

/**
 * 整个目录一起分配文件名（构建期）：重名（NFC + 不分大小写）的一组里，排名最前的用原名，其余加 “ (arXiv 编号)”。
 * items 按排名从前到后给。返回 论文 id → 不带 .md 的库内路径。
 */
export function assignNoteNames(items: { id: string; title: string }[]): Map<string, string> {
  const out = new Map<string, string>();
  const taken = new Set<string>();
  for (const it of items) {
    const stem = baseName(it.title);
    let rel = `${NOTE_DIR}/${stem}`;
    if (taken.has(folded(rel))) rel = `${NOTE_DIR}/${stem} (${it.id.replace(/^arxiv:/, "")})`;
    taken.add(folded(rel));
    out.set(it.id, rel);
  }
  return out;
}

export type NoteQuote = { by: string; ym: string; text: string; commentId: number; story: string | null };

/** 详情页交给按钮的数据（构建期从 catalog 取好）。 */
export type NoteData = {
  id: string;
  /** 建议的笔记文件名（论文/<英文主标题>），不带 .md */
  path: string;
  title: string;
  titleZh: string | null;
  authors: string[];
  nAuthors: number;
  year: number | null;
  areaZh: string | null;
  topicZh: string | null;
  people: number;
  months: number;
  oneliner: string | null;
  summary: string | null;
  /** 没有中文导读时（候选层）放 arXiv 摘要 */
  abstract: string | null;
  whyHn: string | null;
  quotes: NoteQuote[];
  siteUrl: string;
};

const ystr = (s: string) => JSON.stringify(s);
const ylist = (xs: string[]) => `[${xs.map(ystr).join(", ")}]`;
const quoteBlock = (text: string) => text.trim().split("\n").map((l) => (l ? `> ${l}` : ">")).join("\n");
const pad = (n: number) => String(n).padStart(2, "0");
export const localMinute = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;

/** 新笔记的 Markdown：属性 → 标题 → 一句话 → 导读 → 我的高亮（空）→ 我的笔记（空）→ HN 原话。status 默认 want。 */
export function renderNote(d: NoteData, now: Date): string {
  const plain = d.id.replace(/^arxiv:/, "");
  const page = `${d.siteUrl}/p/${plain}/`;
  const authors = d.nAuthors > d.authors.length ? [...d.authors, `…（共 ${d.nAuthors} 人）`] : d.authors;
  const fm = [
    "---",
    `id: ${ystr(d.id)}`,
    `title: ${ystr(d.title)}`,
    `title_zh: ${d.titleZh ? ystr(d.titleZh) : ""}`.trimEnd(),
    `aliases: ${ylist([d.titleZh, plain].filter((x): x is string => !!x))}`,
    `authors: ${ylist(authors)}`,
    `year: ${d.year ?? ""}`.trimEnd(),
    `area: ${d.areaZh ? ystr(d.areaZh) : ""}`.trimEnd(),
    `topic: ${d.topicZh ? ystr(d.topicZh) : ""}`.trimEnd(),
    `status: ${ystr("want")}`,
    "liked: false",
    `hn_people: ${d.people}`,
    `hn_months: ${d.months}`,
    `arxiv: ${ystr(plain)}`,
    `hackershelf: ${ystr(page)}`,
    "tags: [hackershelf, 论文]",
    `updated: ${localMinute(now)}`,
    "---",
  ];
  const out = [fm.join("\n"), `# ${d.title}`];
  if (d.titleZh) out.push(`*${d.titleZh}*`);
  out.push(
    [d.year ? String(d.year) : "", d.areaZh ?? "", d.topicZh ?? "", `HN 上 ${d.people} 人在 ${d.months} 个月里提到`,
      `[arXiv](https://arxiv.org/abs/${plain})`, `[在 HackerShelf 打开](${page})`].filter(Boolean).join(" · "),
  );
  if (d.oneliner) out.push(`## 一句话\n\n${d.oneliner}`);
  if (d.summary) out.push(`## 导读\n\n${d.summary}`);
  else if (d.abstract) out.push(`## 摘要（arXiv）\n\n${d.abstract}`);
  out.push("## 我的高亮", "## 我的笔记");
  if (d.quotes.length) {
    const parts = ["## HN 原话"];
    for (const q of d.quotes) {
      const head = [q.by, q.ym].filter(Boolean).join(" · ");
      parts.push(`> [!quote] ${head}\n${quoteBlock(q.text)}\n>\n> [原评论](https://news.ycombinator.com/item?id=${q.commentId})${q.story ? `（${q.story}）` : ""}`);
    }
    out.push(parts.join("\n\n"));
  }
  return `${out.join("\n\n").trimEnd()}\n`;
}

/** 复制提问提示词：提示词 + 论文链接 + 中文导读，贴进任意模型。 */
export function buildPrompt(d: NoteData): string {
  const plain = d.id.replace(/^arxiv:/, "");
  const authors = d.nAuthors > 3 ? `${d.authors.slice(0, 3).join(", ")} 等 ${d.nAuthors} 人` : d.authors.join(", ");
  const lines = [
    "请帮我读懂这篇论文。",
    "",
    `《${d.title}》${d.titleZh ? `（${d.titleZh}）` : ""}`,
    [authors, d.year ? String(d.year) : ""].filter(Boolean).join(" · "),
    `arXiv：https://arxiv.org/abs/${plain}`,
    `PDF：https://arxiv.org/pdf/${plain}`,
    "",
  ];
  if (d.summary) lines.push("中文导读：", d.summary, "");
  else if (d.abstract) lines.push("摘要（arXiv）：", d.abstract, "");
  if (d.whyHn) lines.push(`Hacker News 上为什么有人推荐它：${d.whyHn}`, "");
  lines.push(
    "先用中文讲清楚四件事：它要解决什么问题，核心想法是什么，关键结果是什么，有什么局限。术语第一次出现时附上英文原词；能读到原文就以原文为准，读不到的地方直说。讲完等我提问。",
  );
  return lines.join("\n");
}
