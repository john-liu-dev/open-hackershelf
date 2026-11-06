/**
 * 开源书书架（Phase 5，D48）的只读数据：管线导出的 data/build/books/shelf.json（`hs.steps.books export`，可随时重建）。
 * 只收开放许可或作者、出版社官方免费放出的书；链接指向官方免费版（原站失效的指向按许可维护的版本，页面上注明），不托管全文。
 * 界面规则同论文：has_positive = false 的写"被提及"，不写"被推荐"。
 */
import "server-only";
import fs from "node:fs";
import path from "node:path";
import { dataDir } from "./paths";
import { sortMentions } from "./catalog";

export type BookCard = {
  oneliner_zh?: string;
  summary_zh?: string;
  why_hn?: string;
  how_to_read?: string[];
  audience_zh?: string;
  prerequisites?: string[];
  difficulty?: number;
  reading_hours?: number;
};

export type Book = {
  id: string;
  slug: string;
  rank: number;
  title: string;
  titleZh: string | null;
  authors: string;
  /** 封面右下角的短作者名（"Abelson 等"） */
  authorShort: string;
  url: string;
  license: string | null;
  licenseLabel: string;
  licenseOpen: boolean;
  licenseUrl: string | null;
  licenseEvidence: string | null;
  unfinished: boolean;
  httpOnly: boolean;
  /** 页面上的备注（比如“原站已失效，这是按 CC BY-NC-SA 许可维护的社区版”） */
  note: string | null;
  subject: string | null;
  /** 常见简称（SICP、OSTEP），搜索和详情页用 */
  aliases: string[];
  people: number;
  months: number;
  threads: number;
  byYear: Record<string, number>;
  stories: number;
  monthsRec: number;
  monthsStrong: number;
  score: number;
  hasPositive: boolean;
  first: string;
  last: string;
  card: BookCard | null;
};

export type BookMention = {
  commentId: number;
  by: string;
  time: string;
  storyId: number | null;
  storyTitle: string | null;
  quote: string | null;
  whyZh: string | null;
  text: string | null;
  points: number | null;
  stance: "strong_rec" | "rec" | "reference" | "joke" | "critical" | null;
  source: "story_url" | "comment_link";
};

export type Subject = { id: string; name: string; n: number };

type Raw = Record<string, unknown>;
type ShelfFile = { generated_at: string; hn_cutoff: string | null; fpb_sha: string; subjects: Subject[]; books: Raw[]; mentions: Record<string, Raw[]> };

export function booksPath(): string {
  return path.join(dataDir(), "build", "books", "shelf.json");
}

let cache: { mtimeMs: number; data: ShelfFile } | null = null;

function load(): ShelfFile {
  const p = booksPath();
  if (!fs.existsSync(p)) return { generated_at: "", hn_cutoff: null, fpb_sha: "", subjects: [], books: [], mentions: {} };
  const mtimeMs = fs.statSync(p).mtimeMs;
  if (!cache || cache.mtimeMs !== mtimeMs) cache = { mtimeMs, data: JSON.parse(fs.readFileSync(p, "utf8")) as ShelfFile };
  return cache.data;
}

function toBook(r: Raw): Book {
  return {
    id: r.id as string,
    slug: r.slug as string,
    rank: r.rank as number,
    title: r.title as string,
    titleZh: (r.title_zh as string) || null,
    authors: (r.authors as string) || "",
    authorShort: (r.author_short as string) || "",
    url: r.url as string,
    license: (r.license as string) ?? null,
    licenseLabel: r.license_label as string,
    licenseOpen: !!r.license_open,
    licenseUrl: (r.license_url as string) ?? null,
    licenseEvidence: (r.license_evidence as string) ?? null,
    unfinished: !!r.unfinished,
    httpOnly: !!r.http_only,
    note: (r.note as string) || null,
    subject: (r.subject as string) ?? null,
    aliases: (r.aliases as string[]) ?? [],
    people: r.people as number,
    months: r.months as number,
    threads: r.threads as number,
    byYear: (r.by_year as Record<string, number>) ?? {},
    stories: (r.stories as number) ?? 0,
    monthsRec: r.months_rec as number,
    monthsStrong: r.months_strong as number,
    score: r.score as number,
    hasPositive: !!r.has_positive,
    first: r.first as string,
    last: r.last as string,
    card: (r.card as BookCard) ?? null,
  };
}

/** 全部上架的书，按分数排（rank 1 起）。 */
export function allBooks(): Book[] {
  return load().books.map(toBook);
}

export function getBook(slug: string): Book | null {
  const r = load().books.find((b) => b.slug === slug);
  return r ? toBook(r) : null;
}

/** 详情页显示的 HN 原话（每本最多 20 条）：推荐在前，同类按时间（和论文同一个排序）。 */
export function bookMentions(id: string): BookMention[] {
  const ms = (load().mentions[id] ?? []).map((r): BookMention => ({
    commentId: r.comment_id as number,
    by: r.by as string,
    time: r.time as string,
    storyId: (r.story_id as number) ?? null,
    storyTitle: (r.story_title as string) ?? null,
    quote: (r.quote as string) ?? null,
    whyZh: (r.why_zh as string) ?? null,
    text: (r.text as string) ?? null,
    points: (r.points as number) ?? null,
    stance: (r.stance as BookMention["stance"]) ?? null,
    source: r.source as BookMention["source"],
  }));
  return sortMentions(ms);
}

/** 书架分类（有书的才返回），按书的数量从多到少。 */
export function bookSubjects(): Subject[] {
  return load().subjects.filter((s) => s.n > 0).sort((a, b) => b.n - a.n);
}

export function subjectNames(): Record<string, string> {
  return Object.fromEntries(load().subjects.map((s) => [s.id, s.name]));
}

export function booksMeta(): { cutoff: string; fpbSha: string; total: number } {
  const d = load();
  return { cutoff: String(d.hn_cutoff ?? "").slice(0, 10), fpbSha: d.fpb_sha, total: d.books.length };
}

/** 封面要的字段：图案按书的编号生成，底色按书架分类，右下角写短作者名（论文那里是年份）。 */
export function bookCover(b: Book): { id: string; area: string | null; title: string; titleZh: string | null; year: null; sub: string } {
  return { id: b.id, area: b.subject ? `b-${b.subject}` : null, title: b.title, titleZh: b.titleZh, year: null, sub: b.authorShort };
}

/**
 * 评论原话里指向这本书的链接，标注时换成了 [BOOK]，别的链接是 [LINK]。显示时："([BOOK])" 去掉，其余换成书名的短标题；
 * [LINK] 写成"（链接）"。
 */
export function cleanBookQuote(q: string, title: string): string {
  const short = title.split(/:\s+/)[0];
  return q
    .replace(/\s*\(\s*\[BOOK\]\s*\)/g, "")
    .replace(/\[BOOK\]/g, short)
    .replace(/\[LINK\]/g, "（链接）")
    .replace(/\s+([,.;:])/g, "$1")
    .trim();
}
