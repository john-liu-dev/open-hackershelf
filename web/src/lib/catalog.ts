/**
 * catalog.db 只读访问层（管线构建、可随时重建；Web 只读）。
 * 字段约定见 docs/DATA.md。界面规则：has_positive = false 的条目写"被提及"，不写"被推荐"。
 */
import "server-only";
import Database from "better-sqlite3";
import fs from "node:fs";
import { catalogPath, searchIndexPath } from "./paths";
import { assignNoteNames } from "./note";
import { newEngine, runSearch, type Hit } from "./search-engine";

export type Card = {
  oneliner_zh?: string;
  summary_zh?: string;
  summary_en?: string;
  why_hn?: string;
  type?: string;
  difficulty?: number;
  prerequisites?: string[];
  shelf_life?: "evergreen" | "dated";
  reading_minutes?: number;
};

export type Paper = {
  id: string;
  kind: "paper";
  title: string;
  titleZh: string | null;
  authors: string[];
  year: number | null;
  abstract: string | null;
  links: { abs: string; html: string; pdf: string; alphaxiv: string };
  categories: string[];
  primaryCategory: string | null;
  field: string;
  /** core = 主书架（≥3 人、≥3 个月）；cand = 候选层（≥2/2），一律显示"被提及" */
  tier: "core" | "cand";
  area: string | null;
  topic: string | null;
  metrics: { cited_by?: number; venue?: string | null; openalex_topic?: string | null; openalex_id?: string; refs_on_shelf?: number };
  active12m: number;
  rec12m: number;
  people: number;
  threads: number;
  activeMonths: number;
  monthsRec: number;
  monthsStrong: number;
  firstMention: string;
  lastMention: string;
  byYear: Record<string, number>;
  hasPositive: boolean;
  labeled: number;
  labelable: number;
  score: number;
  card: Card | null;
  thumb: string | null;
  rank: number;
};

export type Mention = {
  commentId: number;
  itemId: string;
  by: string;
  time: string;
  storyId: number | null;
  storyTitle: string | null;
  quote: string | null;
  why: string | null;
  /** "为什么"的中文一句；没有时页面上隐藏这一行，不显示英文（docs/DESIGN.md 第 6 节） */
  whyZh: string | null;
  text: string | null;
  points: number | null;
  stance: "strong_rec" | "rec" | "reference" | "joke" | "critical" | null;
  stanceConfidence: number | null;
  /** thread_comment = 论文被提交的讨论串里的评论（只靠 story 提交入选的论文用它补"原话"；不计入统计、不标立场） */
  source: "story_url" | "comment_link" | "thread_comment";
};

export type Topic = { id: string; area: string; nameZh: string; nameEn: string; n: number; nCore: number };
export type Area = { id: string; nameZh: string; nameEn: string; n: number; topics: Topic[] };
export type Related = { paper: Paper; coPeople: number; sim: number; cites: boolean };

type Row = Record<string, unknown>;

let _db: Database.Database | null = null;
let _dbStamp = "";

/** 只读打开；catalog.db 被原子替换（deploy/sync-data.sh 用 rsync 先传临时文件再改名）后自动重新打开。 */
export function db(): Database.Database {
  const p = catalogPath();
  const st = fs.statSync(p);
  const stamp = `${st.ino}:${st.mtimeMs}`;
  if (!_db || stamp !== _dbStamp) {
    _db?.close();
    _db = new Database(p, { readonly: true, fileMustExist: true });
    _dbStamp = stamp;
  }
  return _db;
}

const j = <T>(v: unknown, d: T): T => {
  if (typeof v !== "string" || !v) return d;
  try {
    return JSON.parse(v) as T;
  } catch {
    return d;
  }
};

function toPaper(r: Row): Paper {
  return {
    id: r.id as string,
    kind: "paper",
    title: r.title as string,
    titleZh: (r.title_zh as string) || null,
    authors: j<string[]>(r.authors, []),
    year: (r.year as number) ?? null,
    abstract: (r.abstract as string) ?? null,
    links: j(r.links, { abs: "", html: "", pdf: "", alphaxiv: "" }),
    categories: j<string[]>(r.categories, []),
    primaryCategory: (r.primary_category as string) ?? null,
    field: r.field as string,
    tier: r.tier === "core" ? "core" : "cand",
    area: (r.area as string) ?? null,
    topic: (r.topic as string) ?? null,
    metrics: j(r.metrics, {}),
    active12m: (r.active_12m as number) ?? 0,
    rec12m: (r.rec_12m as number) ?? 0,
    people: r.people as number,
    threads: r.threads as number,
    activeMonths: r.active_months as number,
    monthsRec: r.months_rec as number,
    monthsStrong: r.months_strong as number,
    firstMention: r.first_mention as string,
    lastMention: r.last_mention as string,
    byYear: j<Record<string, number>>(r.by_year, {}),
    hasPositive: !!r.has_positive,
    labeled: r.labeled as number,
    labelable: r.labelable as number,
    score: r.score as number,
    card: j<Card | null>(r.card, null),
    thumb: (r.thumb as string) ?? null,
    rank: r.rank as number,
  };
}

function toMention(r: Row): Mention {
  return {
    commentId: r.comment_id as number,
    itemId: r.item_id as string,
    by: r.by as string,
    time: r.time as string,
    storyId: (r.story_id as number) ?? null,
    storyTitle: (r.story_title as string) ?? null,
    quote: (r.quote as string) ?? null,
    why: (r.why as string) ?? null,
    whyZh: (r.why_zh as string) ?? null,
    text: (r.text as string) ?? null,
    points: (r.points as number) ?? null,
    stance: (r.stance as Mention["stance"]) ?? null,
    stanceConfidence: (r.stance_confidence as number) ?? null,
    source: r.source as Mention["source"],
  };
}

/** URL 段 ↔ ID：/p/1706.03762 ↔ arxiv:1706.03762；旧式 /p/math/9404236 ↔ arxiv:math/9404236（实现在 lib/ids.ts） */
export { idFromSlug, slugFromId } from "./ids";
import { slugFromId } from "./ids";

export function getPaper(id: string): Paper | null {
  const r = db().prepare("SELECT * FROM items WHERE id = ?").get(id) as Row | undefined;
  return r ? toPaper(r) : null;
}

/** 显示顺序：strong_rec → rec → critical → reference → joke → 没有标签的评论 → 讨论串评论 → story 提交，同类按时间。 */
export const STANCE_ORDER: Record<string, number> = { strong_rec: 0, rec: 1, critical: 2, reference: 3, joke: 4 };

export function mentionRank(m: Pick<Mention, "stance" | "source">): number {
  if (m.source === "story_url") return 7;
  if (m.source === "thread_comment") return 6;
  return m.stance ? STANCE_ORDER[m.stance] : 5;
}

export function sortMentions<T extends Pick<Mention, "stance" | "source" | "time">>(ms: T[]): T[] {
  return [...ms].sort((a, b) => mentionRank(a) - mentionRank(b) || a.time.localeCompare(b.time));
}

export function getMentions(id: string): Mention[] {
  return sortMentions((db().prepare("SELECT * FROM mentions WHERE item_id = ?").all(id) as Row[]).map(toMention));
}

export type Sort = "score" | "people" | "longest" | "recent" | "rising" | "gems" | "cited" | "newest";

export const SORTS: { id: Sort; name: string; note: string }[] = [
  { id: "score", name: "推荐分", note: "有推荐的不同月份数 + 0.5 × 有强推荐的月份数" },
  { id: "people", name: "最多人", note: "提到它的不同 HN 用户数" },
  { id: "longest", name: "最长寿", note: "第一次和最近一次被提起相隔最久" },
  { id: "recent", name: "最近被提起", note: "最近一次被提起的时间" },
  { id: "rising", name: "上升中", note: "最近 12 个月里有推荐 / 被提起的月份数" },
  { id: "gems", name: "隐藏宝藏", note: "提的人不多（≤ 5 人），但跨了很多个月" },
  { id: "cited", name: "被引最多", note: "OpenAlex 被引次数" },
  { id: "newest", name: "最新发表", note: "arXiv 发表年份" },
];

// 最后都按 rank 定序：公开站浏览页在浏览器里用同样的键排序（components/public/browse-model.ts），两边分页才对得上
const ORDER: Record<Sort, string> = {
  score: "score DESC, people DESC, active_months DESC, rank ASC",
  people: "people DESC, active_months DESC, rank ASC",
  longest: "(julianday(last_mention) - julianday(first_mention)) DESC, people DESC, rank ASC",
  recent: "last_mention DESC, people DESC, rank ASC",
  rising: "rec_12m DESC, active_12m DESC, score DESC, rank ASC",
  gems: "active_months DESC, score DESC, people ASC, rank ASC",
  cited: "coalesce(cited_by, 0) DESC, people DESC, rank ASC",
  newest: "year DESC, people DESC, rank ASC",
};

export type Filters = {
  tier?: "core" | "all";
  area?: string;
  topic?: string;
  decade?: string; // "2020" = 2020–2029；"old" = 2009 及以前
  difficulty?: number;
  shelfLife?: "evergreen" | "dated";
  positive?: boolean;
  sort?: Sort;
};

function whereOf(f: Filters): { sql: string; args: Record<string, unknown> } {
  const w: string[] = [];
  const args: Record<string, unknown> = {};
  if (f.tier !== "all") w.push("tier = 'core'");
  if (f.area) (w.push("area = @area"), (args.area = f.area));
  if (f.topic) (w.push("topic = @topic"), (args.topic = f.topic));
  if (f.decade === "old") w.push("year <= 2009");
  else if (f.decade && /^\d{4}$/.test(f.decade)) (w.push("year BETWEEN @y0 AND @y1"), (args.y0 = +f.decade), (args.y1 = +f.decade + 9));
  if (f.difficulty) (w.push("difficulty = @difficulty"), (args.difficulty = f.difficulty));
  if (f.shelfLife) (w.push("shelf_life = @shelfLife"), (args.shelfLife = f.shelfLife));
  if (f.positive) w.push("has_positive = 1");
  if (f.sort === "gems") w.push("people <= 5");
  return { sql: w.length ? "WHERE " + w.join(" AND ") : "", args };
}

/** 浏览页：筛选 + 排序 + 分页。默认只看主书架。 */
export function browse(f: Filters, page = 1, perPage = 40): { papers: Paper[]; total: number } {
  const { sql, args } = whereOf(f);
  const total = (db().prepare(`SELECT count(*) AS n FROM items ${sql}`).get(args) as { n: number }).n;
  const papers = (db()
    .prepare(`SELECT * FROM items ${sql} ORDER BY ${ORDER[f.sort ?? "score"]} LIMIT @limit OFFSET @offset`)
    .all({ ...args, limit: perPage, offset: (page - 1) * perPage }) as Row[]).map(toPaper);
  return { papers, total };
}

export type Shelf = "evergreen" | "gems" | "recent" | "rising";

/** 首页书架（只取主书架）。 */
export function shelf(kind: Shelf, limit = 12): Paper[] {
  const sort: Sort = kind === "evergreen" ? "score" : kind;
  return browse({ tier: "core", sort }, 1, limit).papers;
}

export function taxonomy(): Area[] {
  const areas = db().prepare("SELECT * FROM areas ORDER BY pos").all() as Row[];
  const topics = (db().prepare("SELECT * FROM topics ORDER BY n_core DESC, n DESC").all() as Row[]).map(
    (r): Topic => ({ id: r.id as string, area: r.area as string, nameZh: r.name_zh as string, nameEn: r.name_en as string,
      n: r.n as number, nCore: r.n_core as number }));
  return areas.map((a) => ({ id: a.id as string, nameZh: a.name_zh as string, nameEn: a.name_en as string,
    n: a.n as number, topics: topics.filter((t) => t.area === a.id) }));
}

export function getTopic(id: string): (Topic & { areaName: string }) | null {
  const r = db().prepare("SELECT t.*, a.name_zh AS area_name FROM topics t JOIN areas a ON a.id = t.area WHERE t.id = ?").get(id) as Row | undefined;
  return r ? { id: r.id as string, area: r.area as string, nameZh: r.name_zh as string, nameEn: r.name_en as string,
    n: r.n as number, nCore: r.n_core as number, areaName: r.area_name as string } : null;
}

export function getRelated(id: string, limit = 8): Related[] {
  const rows = db()
    .prepare(`SELECT r.co_people, r.sim, r.cites, i.* FROM related r JOIN items i ON i.id = r.related_id
              WHERE r.item_id = ? ORDER BY r.pos LIMIT ?`)
    .all(id, limit) as Row[];
  return rows.map((r) => ({ paper: toPaper(r), coPeople: r.co_people as number, sim: r.sim as number, cites: !!r.cites }));
}

export function getPapers(ids: string[]): Paper[] {
  if (!ids.length) return [];
  const rows = db().prepare(`SELECT * FROM items WHERE id IN (${ids.map(() => "?").join(",")})`).all(...ids) as Row[];
  const by = new Map(rows.map((r) => [r.id as string, toPaper(r)]));
  return ids.map((i) => by.get(i)).filter((p): p is Paper => !!p);
}

/** 全部论文的编号，按排名（公开站给每篇生成一个详情页）。 */
export function allIds(): string[] {
  return db().prepare("SELECT id FROM items ORDER BY rank").pluck().all() as string[];
}

let _noteNames: Map<string, string> | null = null;
/** 每篇论文在 Obsidian 库里的笔记路径（公开站的“在 Obsidian 中记笔记”；规则见 lib/note.ts）。 */
export function noteNames(): Map<string, string> {
  _noteNames ??= assignNoteNames(db().prepare("SELECT id, title FROM items ORDER BY rank").all() as { id: string; title: string }[]);
  return _noteNames;
}

/** 公开站浏览页在浏览器里筛选、排序用的精简目录（browse.json；列的顺序见 components/public/browse-model.ts）。 */
export function browseRows(): unknown[][] {
  const pathIds = new Set(db().prepare("SELECT item_id FROM paths").pluck().all() as string[]);
  const rows = db().prepare(`SELECT id, title, title_zh, year, area, topic, tier, has_positive, people, active_months, score, first_mention,
      last_mention, rec_12m, active_12m, coalesce(cited_by, 0) AS cited, difficulty, shelf_life, card FROM items ORDER BY rank`).all() as Row[];
  return rows.map((r) => {
    const card = j<Card | null>(r.card, null);
    return [
      slugFromId(r.id as string), r.title, r.title_zh ?? null, r.year ?? null, r.area ?? null, r.topic ?? null, r.tier === "core" ? 1 : 0,
      r.has_positive ? 1 : 0, r.people, r.active_months, r.score, String(r.first_mention ?? "").slice(0, 10), String(r.last_mention ?? "").slice(0, 10),
      r.rec_12m ?? 0, r.active_12m ?? 0, r.cited ?? 0, r.difficulty ?? null, r.shelf_life === "evergreen" ? "e" : r.shelf_life === "dated" ? "d" : null,
      card?.oneliner_zh ?? null, pathIds.has(r.id as string) ? 1 : 0,
    ];
  });
}

/** 领域 ID → 中文名（封面上的领域名）。 */
export function areaNames(): Record<string, string> {
  const rows = db().prepare("SELECT id, name_zh FROM areas").all() as { id: string; name_zh: string }[];
  return Object.fromEntries(rows.map((r) => [r.id, r.name_zh]));
}

/** 某个领域主书架里分数最高的几篇。 */
export function areaShelf(area: string, limit = 7): Paper[] {
  return browse({ tier: "core", area, sort: "score" }, 1, limit).papers;
}

/** 一篇论文最适合放在首页的那句 HN 原话：按显示顺序取第一条有摘录的评论。 */
export function bestQuote(id: string): Mention | null {
  return getMentions(id).find((m) => m.source === "comment_link" && m.quote && m.quote.length >= 40) ?? null;
}

export function buildMeta(): Record<string, unknown> {
  const rows = db().prepare("SELECT key, value FROM build_meta").all() as { key: string; value: string }[];
  return Object.fromEntries(rows.map((r) => [r.key, j(r.value, r.value)]));
}

/** 服务端全文搜索（FTS5），前端即时搜索不可用时的退路。 */
/**
 * 服务端搜索（搜索页首屏）：和前端即时搜索同一套 MiniSearch 配置，两边结果、排序一致。
 * 第一次搜索时从 search-index.json 建索引（约 0.3 秒、常驻约 40 MB），文件更新（管线重建）后自动重建。
 */
let engineCache: { mtimeMs: number; engine: ReturnType<typeof newEngine> } | null = null;
export function searchHits(q: string, limit = 50): { hits: Hit[]; total: number } {
  if (!q.trim()) return { hits: [], total: 0 };
  const mtimeMs = fs.statSync(searchIndexPath()).mtimeMs;
  if (!engineCache || engineCache.mtimeMs !== mtimeMs) {
    const engine = newEngine();
    engine.addAll(searchIndex() as Hit[]);
    engineCache = { mtimeMs, engine };
  }
  return runSearch(engineCache.engine, q, "", limit);
}

/** FTS5 全文检索（catalog.db 的 items_fts），保留给以后的服务端接口用；搜索页首屏用的是 searchHits。 */
export function searchServer(q: string, limit = 50): Paper[] {
  const terms = q
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((t) => `"${t.replace(/"/g, '""')}"*`)
    .join(" ");
  if (!terms) return [];
  const ids = db()
    .prepare("SELECT id FROM items_fts WHERE items_fts MATCH ? ORDER BY rank LIMIT ?")
    .all(terms, limit) as { id: string }[];
  return ids.map((r) => getPaper(r.id)).filter((p): p is Paper => !!p);
}

export type SearchDoc = { id: string; t: string; z: string; a: string; y: number | null; f: string; s: number; p: number; c: 0 | 1; o: string; k: string; r: string; h: 0 | 1 };

export function searchIndex(): SearchDoc[] {
  return JSON.parse(fs.readFileSync(searchIndexPath(), "utf8")) as SearchDoc[];
}

export const FIELD_NAMES: Record<string, string> = {
  ai: "AI 与机器学习",
  cs: "计算机科学",
  math: "数学与统计",
  physics: "物理",
  bio: "生物",
  econ: "经济与金融",
  other: "其他",
};

export { STANCE_NAMES } from "./labels";

export type PathStep = { paper: Paper; why: string; focus: string };
export type LearningPath = { intro: string; steps: PathStep[]; model: string | null; builtAt: string | null };

/** 学习路径（Phase 3）：目标论文的参考文献和书架求交集，Claude Code 排好的阅读顺序。没有的返回 null。 */
export function getPath(id: string): LearningPath | null {
  let r: Row | undefined;
  try {
    r = db().prepare("SELECT * FROM paths WHERE item_id = ?").get(id) as Row | undefined;
  } catch {
    return null; // 旧的 catalog.db 没有 paths 表
  }
  if (!r) return null;
  const raw = j<{ id: string; why: string; focus: string }[]>(r.steps, []);
  const papers = new Map(getPapers(raw.map((s) => s.id)).map((p) => [p.id, p]));
  const steps = raw.filter((s) => papers.has(s.id)).map((s) => ({ paper: papers.get(s.id)!, why: s.why, focus: s.focus }));
  return steps.length ? { intro: String(r.intro ?? ""), steps, model: (r.model as string) ?? null, builtAt: (r.built_at as string) ?? null } : null;
}

