#!/usr/bin/env node
/**
 * HackerShelf 公开站的新鲜书架：公开仓库 shelf 的 GitHub Actions 每天跑一次，只抓元数据写 fresh.json，不调用任何模型。
 *   hf   Hugging Face 每日论文（最近三天，按点赞）
 *   hn   HN 最近 36 小时里链接到 arXiv 的帖子，以及评论里提到的 arXiv 论文
 *   cat  关注的 arXiv 分类最近一次公布的新论文（RSS；只要 new 和 cross）
 * 已在书架目录里的论文（读 site/search-index.json）标上中文标题和一句话，页面链到详情页。
 *
 * 用法：node scripts/fresh.mjs --site site [--prev <线上 fresh.json 的地址或本地文件>]
 * 某个来源失败时沿用上一份（线上那份）的这一栏，并标成 stale；脚本总是写出 site/fresh.json、退出码 0，
 * 不挡住网站发布。失败写成 GitHub Actions 的 ::warning:: 注释。
 * 只用 Node 自带的 fetch，没有依赖。源码在私有仓库 deploy/public/scripts/，由 deploy/public/build.sh 复制到公开仓库。
 */
import fs from "node:fs";
import path from "node:path";
import { arxivFromUrl, decodeEntities, squash, xmlAttrs, xmlTag, xmlTags } from "./parse.mjs";

const CFG = JSON.parse(fs.readFileSync(new URL("./fresh.config.json", import.meta.url), "utf8"));
const UA = "HackerShelf-fresh/1.0 (+https://github.com/john-liu-dev/shelf)";
const ARXIV_URL = /https?:\/\/(?:www\.|export\.)?arxiv\.org\/(?:abs|pdf|html)\/[^\s"'<>)\]]+/gi;
const MON = { Jan: "01", Feb: "02", Mar: "03", Apr: "04", May: "05", Jun: "06", Jul: "07", Aug: "08", Sep: "09", Oct: "10", Nov: "11", Dec: "12" };

function arg(name, def = null) {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const warn = (msg) => console.log(`::warning::${msg}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// arXiv 要求每 3 秒最多 1 个请求、单连接；其他站点按顺序请求，不并发
let arxivLast = 0;
async function get(url, { json = false } = {}) {
  const host = new URL(url).hostname;
  for (let attempt = 0; ; attempt++) {
    if (host.endsWith("arxiv.org")) {
      const wait = arxivLast + 3100 - Date.now();
      if (wait > 0) await sleep(wait);
      arxivLast = Date.now();
    }
    try {
      const r = await fetch(url, { headers: { "user-agent": UA, accept: json ? "application/json" : "*/*" }, signal: AbortSignal.timeout(30000) });
      if (r.ok) return json ? r.json() : r.text();
      if (attempt >= 2 || (r.status < 500 && r.status !== 429)) throw new Error(`${host} HTTP ${r.status}`);
    } catch (e) {
      if (attempt >= 2) throw e;
    }
    await sleep(5000 * (attempt + 1));
  }
}

/** Hugging Face 每日论文：列表最近三天（按 HF 页面上的日期），按点赞排。 */
async function fetchHf() {
  const list = await get(`https://huggingface.co/api/daily_papers?limit=${CFG.hf_limit}`, { json: true });
  const rows = [];
  for (const x of list) {
    const p = x.paper ?? {};
    if (!/^\d{4}\.\d{4,5}$/.test(String(p.id ?? ""))) continue;
    const authors = (p.authors ?? []).map((a) => a.name).filter(Boolean);
    rows.push({
      id: p.id,
      meta: { title: squash(p.title ?? x.title), authors, abstract: squash(p.summary ?? x.summary) || null, categories: [], year: Number(String(p.publishedAt ?? "").slice(0, 4)) || null },
      hf: { upvotes: p.upvotes ?? 0, comments: x.numComments ?? 0, day: String(p.submittedOnDailyAt ?? x.publishedAt ?? "").slice(0, 10) },
    });
  }
  const last = rows.map((r) => r.hf.day).filter(Boolean).sort().at(-1) ?? "";
  const from = last ? new Date(Date.parse(`${last}T12:00:00Z`) - 2 * 86400000).toISOString().slice(0, 10) : "";
  return rows.filter((r) => r.hf.day >= from).sort((a, b) => b.hf.upvotes - a.hf.upvotes).slice(0, CFG.hf_show);
}

/** HN：最近 36 小时链接 arXiv 的帖子（同一篇取分数最高的那帖），加上评论里提到的 arXiv 论文（数次数）。 */
async function fetchHn() {
  const since = Math.floor(Date.now() / 1000) - CFG.hn_window_hours * 3600;
  const base = "https://hn.algolia.com/api/v1/search_by_date?query=arxiv.org&hitsPerPage=100";
  const byId = new Map();
  const rec = (id) => {
    if (!byId.has(id)) byId.set(id, { points: 0, comments: 0, itemId: null, mentions: 0 });
    return byId.get(id);
  };
  for (let page = 0; page < 3; page++) {
    const r = await get(`${base}&restrictSearchableAttributes=url&tags=story&numericFilters=created_at_i%3E${since}&page=${page}`, { json: true });
    for (const h of r.hits) {
      const id = arxivFromUrl(h.url);
      if (!id) continue;
      const s = rec(id);
      if ((h.points ?? 0) >= s.points) Object.assign(s, { points: h.points ?? 0, comments: h.num_comments ?? 0, itemId: Number(h.objectID) });
    }
    if (page + 1 >= r.nbPages) break;
  }
  for (let page = 0; page < 3; page++) {
    const r = await get(`${base}&tags=comment&numericFilters=created_at_i%3E${since}&page=${page}`, { json: true });
    for (const h of r.hits) {
      const text = decodeEntities(h.comment_text ?? "");
      for (const id of new Set([...text.matchAll(ARXIV_URL)].map((m) => arxivFromUrl(m[0])).filter(Boolean))) {
        const s = rec(id);
        s.mentions += 1;
        if (!s.itemId && h.story_id) s.itemId = h.story_id;
      }
    }
    if (page + 1 >= r.nbPages) break;
  }
  return [...byId.entries()]
    .map(([id, hn]) => ({ id, hn }))
    .sort((a, b) => b.hn.points - a.hn.points || b.hn.mentions - a.hn.mentions)
    .slice(0, CFG.hn_show);
}

/** 关注的分类：RSS 是最近一次公布的那一批（周末不公布，拿到的还是上一批）。 */
async function fetchCategories() {
  const xml = await get(`https://rss.arxiv.org/rss/${CFG.categories.join("+")}`);
  const pub = (xml.match(/<pubDate>[^<]*?(\d{1,2}) (\w{3}) (\d{4})/) ?? []).slice(1);
  const day = pub.length === 3 ? `${pub[2]}-${MON[pub[1]]}-${pub[0].padStart(2, "0")}` : null;
  const rows = [];
  for (const [, item] of xml.matchAll(/<item>([\s\S]*?)<\/item>/g)) {
    const announce = xmlTag(item, "arxiv:announce_type");
    if (!CFG.announce_types.includes(announce)) continue;
    const id = arxivFromUrl(xmlTag(item, "link"));
    if (!id) continue;
    const cats = xmlTags(item, "category");
    const desc = xmlTag(item, "description") ?? "";
    rows.push({
      id,
      meta: {
        title: squash(xmlTag(item, "title")),
        authors: squash(xmlTag(item, "dc:creator")).split(/,\s*/).filter(Boolean),
        abstract: squash(desc.replace(/^[\s\S]*?Abstract:\s*/, "")) || null,
        categories: cats,
        year: day ? Number(day.slice(0, 4)) : null,
      },
      cat: { announce, follow: cats.find((c) => CFG.categories.includes(c)) ?? cats[0] ?? "其他" },
    });
  }
  return { day, rows };
}

/** export.arxiv.org 批量查元数据（每批 50 个，按 arXiv 限速）。 */
async function arxivMeta(ids) {
  const out = new Map();
  for (let i = 0; i < ids.length; i += 50) {
    const batch = ids.slice(i, i + 50);
    const xml = await get(`https://export.arxiv.org/api/query?id_list=${batch.join(",")}&max_results=${batch.length}`);
    for (const [, e] of xml.matchAll(/<entry>([\s\S]*?)<\/entry>/g)) {
      const id = arxivFromUrl(xmlTag(e, "id"));
      const title = squash(xmlTag(e, "title"));
      if (!id || !title || title === "Error") continue;
      const primary = xmlAttrs(e, "arxiv:primary_category", "term")[0];
      const cats = xmlAttrs(e, "category", "term");
      out.set(id, {
        title,
        authors: xmlTags(e, "name").map(squash),
        abstract: squash(xmlTag(e, "summary")) || null,
        categories: primary ? [primary, ...cats.filter((c) => c !== primary)] : cats,
        year: Number(String(xmlTag(e, "published") ?? "").slice(0, 4)) || null,
      });
    }
  }
  return out;
}

/** 书架目录（公开站自己的 search-index.json）：编号 → 标题、作者、中文标题、一句话。 */
function loadCatalog(site) {
  try {
    const docs = JSON.parse(fs.readFileSync(path.join(site, "search-index.json"), "utf8"));
    return new Map(docs.map((d) => [String(d.id).replace(/^arxiv:/, ""), d]));
  } catch (e) {
    warn(`读不到 search-index.json：${e.message}（新鲜书架不标“已在书架”）`);
    return new Map();
  }
}

async function loadPrev(src) {
  if (!src) return null;
  try {
    const j = /^https?:/.test(src) ? await get(src, { json: true }) : JSON.parse(fs.readFileSync(src, "utf8"));
    return j?.v === 1 ? j : null;
  } catch (e) {
    log(`没有上一份 fresh.json（${e.message}）`);
    return null;
  }
}

const clip = (s, n) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s);

async function main() {
  const site = arg("site", "site");
  const out = arg("out", path.join(site, "fresh.json"));
  const catalog = loadCatalog(site);
  const prev = await loadPrev(arg("prev"));
  const items = {};
  const sources = {};
  const sections = { hf: [], hn: [], cat: {} };
  let catDay = null;

  const put = (id, meta, extra) => {
    const c = catalog.get(id);
    const m = meta ?? (c ? { title: c.t, authors: String(c.a ?? "").split(/,\s*/).filter(Boolean), abstract: null, categories: [], year: c.y ?? null } : null);
    if (!m?.title) return false;
    const it = (items[id] ??= {
      title: m.title, authors: m.authors.slice(0, 12), nAuthors: m.authors.length, abstract: clip(m.abstract, CFG.abstract_max), categories: m.categories, year: m.year,
    });
    if (c) it.inCatalog = { titleZh: c.z || null, oneliner: c.o || null };
    Object.assign(it, extra);
    return true;
  };
  const fallback = (key, err) => {
    warn(`${key} 没抓到：${err}`);
    if (!prev) return (sources[key] = { ok: false, n: 0, error: String(err).slice(0, 200) });
    const ids = key === "cat" ? Object.values(prev.sections.cat).flat() : prev.sections[key];
    for (const id of ids) if (prev.items[id] && !items[id]) items[id] = prev.items[id];
    if (key === "cat") (sections.cat = prev.sections.cat), (catDay = prev.catDay);
    else sections[key] = prev.sections[key];
    sources[key] = { ok: false, n: ids.length, stale: true, error: String(err).slice(0, 200) };
  };

  try {
    const rows = await fetchHf();
    for (const r of rows) if (put(r.id, r.meta, { hf: r.hf })) sections.hf.push(r.id);
    sources.hf = { ok: true, n: sections.hf.length };
  } catch (e) {
    fallback("hf", e.message);
  }
  try {
    const { day, rows } = await fetchCategories();
    catDay = day;
    for (const r of rows) if (put(r.id, r.meta, { cat: r.cat })) (sections.cat[r.cat.follow] ??= []).push(r.id);
    sources.cat = { ok: true, n: rows.length };
  } catch (e) {
    fallback("cat", e.message);
  }
  try {
    const rows = await fetchHn();
    const need = rows.map((r) => r.id).filter((id) => !items[id] && !catalog.has(id));
    const meta = need.length ? await arxivMeta(need) : new Map();
    for (const r of rows) if (put(r.id, items[r.id] ? undefined : (meta.get(r.id) ?? null), { hn: r.hn })) sections.hn.push(r.id);
    sources.hn = { ok: true, n: sections.hn.length };
  } catch (e) {
    fallback("hn", e.message);
  }

  if (!Object.values(sources).some((s) => s.ok) && prev) {
    warn("三个来源都没抓到，沿用上一份 fresh.json");
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, JSON.stringify({ ...prev, sources: Object.fromEntries(Object.entries(prev.sources).map(([k, v]) => [k, { ...v, ok: false, stale: true }])) }));
    return;
  }
  const doc = { v: 1, generatedAt: new Date().toISOString(), categories: CFG.categories, catDay, sources, sections, items };
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, JSON.stringify(doc));
  const inCat = Object.values(items).filter((x) => x.inCatalog).length;
  log(`fresh.json：${Object.keys(items).length} 篇（已在书架 ${inCat}）· hf ${sources.hf.n} · hn ${sources.hn.n} · 分类 ${sources.cat.n}（${catDay}）· ${(fs.statSync(out).size / 1024).toFixed(0)} KB`);
}

main().catch((e) => {
  // 写不出来也不挡住网站发布：页面会显示“没加载出来”
  warn(`fresh.mjs 出错：${e?.stack ?? e}`);
});
