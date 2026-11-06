import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { isDefault, query, readState, type AreaLite, type Row, type State } from "@/components/public/browse-model";
import { assignNoteNames, baseName, buildPrompt, renderNote, type NoteData } from "@/lib/note";

// 笔记文件名：英文主标题（冒号前），去掉文件名里不能用的字符和开头的点，最长 100 个字符
const PY_BASE_NAME: Record<string, string> = {
  "Attention Is All You Need": "Attention Is All You Need",
  "On proof and progress in mathematics": "On proof and progress in mathematics",
  "Mastering Chess and Shogi by Self-Play: A General RL Algorithm": "Mastering Chess and Shogi by Self-Play",
  "What Every Computer Scientist Should Know About Floating-Point Arithmetic": "What Every Computer Scientist Should Know About Floating-Point Arithmetic",
  "  .hidden/file: name?*<>|#^[x]": "hiddenfile",
  ["A".repeat(120)]: "A".repeat(100),
  "Ｆｕｌｌｗｉｄｔｈ Ｃａｆé": "Ｆｕｌｌｗｉｄｔｈ Ｃａｆé",
  "Café au lait": "Café au lait",
  "": "untitled",
  "::": "untitled",
};

describe("笔记文件名", () => {
  it("英文主标题、去掉不能用的字符、最长 100 个字符", () => {
    for (const [t, want] of Object.entries(PY_BASE_NAME)) expect(baseName(t)).toBe(want);
  });

  it("重名（不分大小写）时排名靠前的用原名，其余加编号", () => {
    const m = assignNoteNames([
      { id: "arxiv:1706.03762", title: "Attention Is All You Need" },
      { id: "arxiv:2501.00001", title: "attention is all you need: again" },
      { id: "arxiv:math/9404236", title: "On proof and progress in mathematics" },
    ]);
    expect(m.get("arxiv:1706.03762")).toBe("论文/Attention Is All You Need");
    expect(m.get("arxiv:2501.00001")).toBe("论文/attention is all you need (2501.00001)");
    expect(m.get("arxiv:math/9404236")).toBe("论文/On proof and progress in mathematics");
  });
});

const NOTE: NoteData = {
  id: "arxiv:1706.03762", path: "论文/Attention Is All You Need", title: "Attention Is All You Need", titleZh: "注意力就是你所需要的一切",
  authors: ["Ashish Vaswani", "Noam Shazeer"], nAuthors: 8, year: 2017, areaZh: "大模型与语言模型", topicZh: "序列模型与注意力机制",
  people: 93, months: 48, oneliner: "只用注意力的序列模型。", summary: "导读第一段。\n\n导读第二段。", abstract: null, whyHn: "Transformer 的起点。",
  quotes: [{ by: "alice", ym: "2019-05", text: "Read this first.\nThen the rest.", commentId: 123, story: "Show HN: x" }],
  siteUrl: "https://john-liu-dev.github.io/shelf",
};

describe("新建笔记的内容", () => {
  const md = renderNote(NOTE, new Date(2026, 10, 4, 9, 5));

  it("属性顺序固定，status 默认 want", () => {
    const fm = md.split("---\n")[1];
    expect(fm.split("\n").map((l) => l.split(":")[0]).filter(Boolean)).toEqual([
      "id", "title", "title_zh", "aliases", "authors", "year", "area", "topic", "status", "liked", "hn_people", "hn_months", "arxiv", "hackershelf", "tags", "updated",
    ]);
    expect(fm).toContain('status: "want"');
    expect(fm).toContain('authors: ["Ashish Vaswani", "Noam Shazeer", "…（共 8 人）"]');
    expect(fm).toContain('hackershelf: "https://john-liu-dev.github.io/shelf/p/1706.03762/"');
    expect(fm).toContain("updated: 2026-11-04 09:05");
  });

  it("正文：一句话 → 导读 → 我的高亮（空）→ 我的笔记（空）→ HN 原话", () => {
    const heads = md.split("\n").filter((l) => l.startsWith("## "));
    expect(heads).toEqual(["## 一句话", "## 导读", "## 我的高亮", "## 我的笔记", "## HN 原话"]);
    expect(md).toContain("> [!quote] alice · 2019-05\n> Read this first.\n> Then the rest.\n>\n> [原评论](https://news.ycombinator.com/item?id=123)（Show HN: x）");
    expect(md.endsWith("\n")).toBe(true);
  });

  it("没有导读时放 arXiv 摘要", () => {
    const m2 = renderNote({ ...NOTE, oneliner: null, summary: null, abstract: "We propose X." }, new Date());
    expect(m2).toContain("## 摘要（arXiv）\n\nWe propose X.");
    expect(m2).not.toContain("## 导读");
  });

  it("提问提示词带论文链接和中文导读", () => {
    const p = buildPrompt(NOTE);
    expect(p).toContain("https://arxiv.org/abs/1706.03762");
    expect(p).toContain("导读第一段。");
    expect(p).toContain("Ashish Vaswani, Noam Shazeer 等 8 人 · 2017");
  });
});

// 浏览页：浏览器里的筛选排序（browse-model）必须和 lib/catalog.ts 的 SQL（browse）逐条一致
const CATALOG = path.resolve(__dirname, "../../data/build/catalog.db");
describe.skipIf(!fs.existsSync(CATALOG))("公开站浏览页和 SQL 一致", async () => {
  process.env.CATALOG_DB = CATALOG;
  const { browse, browseRows, taxonomy } = await import("@/lib/catalog");
  const rows = browseRows() as Row[];
  const areas: AreaLite[] = taxonomy().map((a) => ({ id: a.id, nameZh: a.nameZh, topics: a.topics }));
  // 一个月 demo 的目录没有主题树：按领域、类目筛选的几种跳过，其余照样逐条比
  const a0 = areas[0];
  const t0 = a0?.topics.find((t) => t.nCore > 5);
  const states: State[] = [
    {}, { page: "2" }, { sort: "recent" }, { sort: "longest", tier: "all" }, { sort: "gems" }, { sort: "rising", page: "3" }, { sort: "cited" },
    { sort: "newest", tier: "all", page: "5" }, { sort: "people", positive: "1" },
    { decade: "old" }, { decade: "2010", tier: "all" }, { difficulty: "2" }, { shelf: "dated" },
    ...(a0 ? [{ area: a0.id }, { tier: "all", area: a0.id, page: "2" }] : []), ...(t0 ? [{ topic: t0.id, sort: "recent" }] : []),
  ];
  it.each(states.map((s) => [JSON.stringify(s), s] as const))("%s", (_k, s) => {
    const page = Math.max(1, Number(s.page ?? 1));
    const want = browse({
      tier: s.tier === "all" ? "all" : "core", area: s.topic ? undefined : s.area, topic: s.topic, decade: s.decade,
      difficulty: s.difficulty ? Number(s.difficulty) : undefined, shelfLife: s.shelf as "evergreen" | "dated" | undefined,
      positive: s.positive === "1", sort: (s.sort ?? "score") as never,
    }, page, 42);
    const got = query(rows, s, areas);
    expect(got.total).toBe(want.total);
    expect(got.items.map((x) => x.id)).toEqual(want.papers.map((p) => p.id));
  });

  it("有学习路径的筛选和 paths 表一致", () => {
    expect(query(rows, { path: "1", tier: "all" }, areas).total).toBe(rows.filter((r) => r[19]).length);
  });

  it("默认视图不用下载 browse.json", () => {
    expect(isDefault(readState(new URLSearchParams("")))).toBe(true);
    expect(isDefault(readState(new URLSearchParams("page=1")))).toBe(true);
    expect(isDefault(readState(new URLSearchParams("sort=recent")))).toBe(false);
  });
});
