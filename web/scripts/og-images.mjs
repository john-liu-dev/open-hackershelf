// 分享图（分享前包装，2026-11-05）：主书架每篇一张 og/<编号>.jpg（用它的生成封面），开源书每本一张 og/books/<slug>.jpg，
// 其余页面共用 og.png。
//   node scripts/og-images.mjs [构建目录]   默认 web/.next-public（先 HS_PUBLIC=1 next build；deploy/public/build.sh 会调用）
// 做法：用构建好的 CSS 和字体，在本机预览服务器上渲染卡片（scripts/og-entry.tsx），Chrome 截图。
// 结果缓存在 data/build/og/（能重建）：卡片内容没变的不重新截，月度更新时只截新进主书架的。
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";
import { build } from "esbuild";
import { chromium } from "playwright";

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = path.resolve(WEB, "..");
const OUT = path.resolve(process.argv[2] ?? path.join(WEB, ".next-public"));
const DATA = process.env.HS_DATA_DIR || path.join(ROOT, "data");
const CACHE = path.join(DATA, "build", "og");
const PORT = 4179;
const VERSION = "og-v1"; // 版式改了就加一，缓存全部作废

const CARD_CSS = `
html, body { margin: 0; background: #121316; }
.og-card { width: 1200px; height: 630px; box-sizing: border-box; padding: 56px 72px; display: flex; gap: 64px; align-items: center; background: #121316; color: #eeeeec; overflow: hidden; }
.og-cover { width: 340px; flex: none; }
.og-text { display: flex; flex-direction: column; gap: 22px; min-width: 0; }
.og-brand { display: flex; align-items: center; gap: 12px; font-family: var(--f-ui); font-size: 22px; color: #b4b6bb; letter-spacing: 0.02em; }
.og-brand-lg { font-size: 44px; gap: 18px; color: #eeeeec; font-family: var(--f-display); font-weight: 600; }
.og-logo svg { display: block; width: 34px; height: 34px; }
.og-brand-lg .og-logo svg { width: 64px; height: 64px; }
.og-title { font-family: var(--f-display); font-weight: 600; line-height: 1.1; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
.og-zh { font-family: var(--f-zh); font-size: 30px; line-height: 1.45; color: #b4b6bb; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.og-meta { font-family: var(--f-ui); font-size: 22px; color: #f2c14e; }
.og-site { justify-content: space-between; }
.og-site-line { font-family: var(--f-zh); font-size: 34px; line-height: 1.5; color: #eeeeec; max-width: 520px; }
.og-site-sub { font-family: var(--f-ui); font-size: 22px; color: #f2c14e; }
.og-site-covers { display: flex; gap: 18px; flex: none; }
.og-site-cover { width: 170px; }
`;

function papers(db) {
  const areas = Object.fromEntries(db.prepare("SELECT id, name_zh FROM areas").all().map((a) => [a.id, a.name_zh]));
  return db.prepare(`SELECT id, title, title_zh, year, area, people, active_months, has_positive, rank FROM items
                     WHERE tier = 'core' ORDER BY rank`).all().map((r) => ({
    id: r.id, title: r.title, titleZh: r.title_zh || null, year: r.year ?? null, area: r.area ?? null,
    areaZh: r.area ? areas[r.area] ?? null : null, people: r.people, months: r.active_months, positive: !!r.has_positive,
  }));
}

const slug = (id) => id.replace(/^arxiv:/, "");

/** 开源书（Phase 5）：data/build/books/shelf.json（hs.steps.books export）；没有就不出书的分享图 */
function books() {
  const p = path.join(DATA, "build", "books", "shelf.json");
  if (!fs.existsSync(p)) return [];
  const d = JSON.parse(fs.readFileSync(p, "utf8"));
  const names = Object.fromEntries(d.subjects.map((s) => [s.id, s.name]));
  return d.books.map((b) => ({
    id: b.id, slug: b.slug, title: b.title, titleZh: b.title_zh || null, year: null, area: b.subject ? `b-${b.subject}` : null,
    areaZh: b.subject ? names[b.subject] ?? null : null, people: b.people, months: b.months, positive: !!b.has_positive,
    sub: b.author_short || null, book: true,
  }));
}

async function waitForServer(url) {
  for (let i = 0; i < 50; i++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`预览服务器没起来：${url}`);
}

const index = fs.readFileSync(path.join(OUT, "index.html"), "utf8");
const htmlClass = index.match(/<html[^>]*class="([^"]*)"/)?.[1] ?? "";
const css = [...index.matchAll(/<link rel="stylesheet" href="([^"]+)"/g)].map((m) => m[1]);
const cssHash = crypto.createHash("sha1").update(css.join(",")).digest("hex").slice(0, 8);
const logo = fs.readFileSync(path.join(WEB, "src", "app", "icon.svg"), "utf8").replace(/<!--[\s\S]*?-->/g, "");

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "hs-og-"));
// 打成 CommonJS：react-dom/server 里有对 Node 内置模块的动态 require，ESM 包里跑不了
const bundle = path.join(tmp, "og-entry.cjs");
await build({
  entryPoints: [path.join(WEB, "scripts", "og-entry.tsx")], outfile: bundle, bundle: true, platform: "node", format: "cjs",
  jsx: "automatic", tsconfig: path.join(WEB, "tsconfig.json"), logLevel: "error",
  define: { "process.env.NEXT_PUBLIC_HS_PUBLIC": '"0"', "process.env.NEXT_PUBLIC_BASE_PATH": '""', "process.env.NODE_ENV": '"production"' },
});
const { paperCard, siteCard } = createRequire(import.meta.url)(bundle);

const db = new Database(path.join(DATA, "build", "catalog.db"), { readonly: true });
const list = papers(db);
db.close();
fs.mkdirSync(CACHE, { recursive: true });
const manifestPath = path.join(CACHE, "manifest.json");
const manifest = fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, "utf8")) : {};
const jobs = list.map((p) => {
  const html = paperCard(p, logo);
  const hash = crypto.createHash("sha1").update(`${VERSION}|${cssHash}|${html}`).digest("hex");
  return { key: slug(p.id), file: path.join(CACHE, `${slug(p.id)}.jpg`), html, hash };
});
const bookList = books();
for (const b of bookList) {
  const html = paperCard(b, logo);
  const hash = crypto.createHash("sha1").update(`${VERSION}|${cssHash}|${html}`).digest("hex");
  jobs.push({ key: `books/${b.slug}`, file: path.join(CACHE, "books", `${b.slug}.jpg`), html, hash });
}
const site = siteCard(list.slice(0, 3), logo);
jobs.push({ key: "__site", file: path.join(CACHE, "og.png"), html: site,
  hash: crypto.createHash("sha1").update(`${VERSION}|${cssHash}|${site}`).digest("hex"), png: true });
const todo = jobs.filter((j) => manifest[j.key] !== j.hash || !fs.existsSync(j.file));

if (todo.length) {
  const server = spawn(process.execPath, [path.join(ROOT, "deploy", "public", "serve.mjs"), OUT, String(PORT)], { stdio: "ignore" });
  try {
    const base = `http://localhost:${PORT}/shelf`;
    await waitForServer(`${base}/`);
    const browser = await chromium.launch({ channel: "chrome" });
    const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
    const template = `<!doctype html><html lang="zh-CN" class="${htmlClass}" data-mode="dark"><head><meta charset="utf-8">
      ${css.map((h) => `<link rel="stylesheet" href="${h}">`).join("")}<style>${CARD_CSS}</style></head><body><div id="card"></div></body></html>`;
    await page.route(`${base}/__og/`, (route) => route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: template }));
    await page.goto(`${base}/__og/`, { waitUntil: "load" });
    const t0 = Date.now();
    for (const [i, j] of todo.entries()) {
      await page.evaluate((html) => { document.getElementById("card").innerHTML = html; }, j.html);
      await page.evaluate(() => document.fonts.ready);
      fs.mkdirSync(path.dirname(j.file), { recursive: true });
      const shot = await page.screenshot(j.png ? { type: "png", clip: { x: 0, y: 0, width: 1200, height: 630 } }
        : { type: "jpeg", quality: 82, clip: { x: 0, y: 0, width: 1200, height: 630 } });
      fs.writeFileSync(j.file, shot);
      manifest[j.key] = j.hash;
      if ((i + 1) % 200 === 0) {
        fs.writeFileSync(manifestPath, JSON.stringify(manifest));
        console.log(`  og ${i + 1}/${todo.length}（${Math.round((Date.now() - t0) / 1000)}s）`);
      }
    }
    fs.writeFileSync(manifestPath, JSON.stringify(manifest));
    await browser.close();
  } finally {
    server.kill();
  }
}

// 放进构建目录：og/<编号>.jpg（旧式编号带斜杠，就是子目录）和 og.png
let bytes = 0;
for (const j of jobs) {
  const dest = j.key === "__site" ? path.join(OUT, "og.png") : path.join(OUT, "og", `${j.key}.jpg`);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(j.file, dest);
  bytes += fs.statSync(dest).size;
}
fs.rmSync(tmp, { recursive: true, force: true });
console.log(`og-images: 主书架 ${list.length} 张 + 开源书 ${bookList.length} 张 + 通用图 1 张，这次新截 ${todo.length} 张，共 ${(bytes / 1024 / 1024).toFixed(1)} MB → ${OUT}`);
