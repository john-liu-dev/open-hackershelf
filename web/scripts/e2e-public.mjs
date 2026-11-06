// 公开站端到端检查（Phase 6，D46）：先 deploy/public/build.sh，再 node deploy/public/serve.mjs，然后
//   node scripts/e2e-public.mjs [http://localhost:4173/shelf]
// 用手机尺寸（390×844）走一遍：首页、详情页（两个按钮、复制的内容）、浏览页（默认视图和浏览器里重算的视图）、
// 搜索（地址栏带搜索词）、新鲜、404、站内跳转；所有页面不许有控制台错误和失败的请求。
// SHOTS=<目录> 时每页存一张截图。
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const base = (process.argv[2] || "http://localhost:4173/shelf").replace(/\/$/, "");
const shots = process.env.SHOTS ? path.resolve(process.env.SHOTS) : null;
if (shots) fs.mkdirSync(shots, { recursive: true });
let failed = 0;
const ok = (cond, msg) => {
  console.log(`${cond ? "  ✓" : "  ✗"} ${msg}`);
  if (!cond) failed++;
};

const browser = await chromium.launch({ channel: "chrome" });
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: new URL(base).origin });
const page = await ctx.newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(`console: ${m.text()}`));
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("requestfailed", (r) => errors.push(`requestfailed: ${r.url()}`));
page.on("response", (r) => r.status() >= 400 && !r.url().endsWith("/does-not-exist/") && errors.push(`${r.status()}: ${r.url()}`));

async function visit(name, url, check) {
  console.log(`\n${name}  ${url}`);
  errors.length = 0;
  await page.goto(`${base}${url}`, { waitUntil: "networkidle" });
  await check();
  if (shots) await page.screenshot({ path: path.join(shots, `${name}.png`), fullPage: false });
  ok(errors.length === 0, `没有控制台错误和失败请求${errors.length ? `：${errors.slice(0, 3).join(" | ")}` : ""}`);
}

/** 分享卡片：twitter 的标题、说明、图和 og 的一致（2026-11-06：/books/ 曾沿用根布局里论文那套） */
async function shareTagsMatch() {
  const m = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll("meta[property^='og:'], meta[name^='twitter:']")]
    .map((e) => [e.getAttribute("property") ?? e.getAttribute("name"), e.getAttribute("content")])));
  const bad = ["title", "description", "image"].filter((k) => !m[`og:${k}`] || m[`og:${k}`] !== m[`twitter:${k}`])
    .map((k) => `twitter:${k}=${m[`twitter:${k}`]} ≠ og:${k}=${m[`og:${k}`]}`);
  ok(bad.length === 0, `twitter 分享标签和 og 一致${bad.length ? `：${bad.join(" | ")}` : ""}`);
}

await visit("home", "/", async () => {
  ok((await page.locator("h1").first().textContent())?.includes("长青榜"), "标题是长青榜");
  const paths = await page.locator(".cover-art path").count();
  ok(paths > 20, `封面图案在浏览器里画出来了（${paths} 个 path）`);
  const hrefs = await page.locator("a[href*='/p/']").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  ok(hrefs.length > 10 && hrefs.every((h) => h.startsWith("/shelf/p/") && h.endsWith("/")), `详情页链接带 /shelf 前缀和结尾斜杠（${hrefs.length} 个）`);
  ok(((await page.locator(".home-lede").textContent()) ?? "").includes("反复推荐"), "开场一句话");
  ok((await page.locator('.site-footer a[href="https://github.com/john-liu-dev"]').count()) === 1, "页脚有作者");
  ok((await page.locator('.site-footer a[href="/shelf/about/"]').count()) === 1, "页脚有关于本站");
  // 图标：SVG、apple-touch-icon；robots 仍是 noindex
  const icon = await page.locator('link[rel="icon"][type="image/svg+xml"]').getAttribute("href");
  const apple = await page.locator('link[rel="apple-touch-icon"]').getAttribute("href");
  ok(!!icon && (await fetch(new URL(icon, page.url())).then((r) => r.ok)), `SVG 图标（${icon}）`);
  ok(!!apple && (await fetch(new URL(apple, page.url())).then((r) => r.ok)), `apple-touch-icon（${apple}）`);
  ok((await page.locator('meta[name="robots"]').getAttribute("content"))?.includes("noindex") ?? false, "noindex 保留");
  ok((await page.locator('meta[property="og:image"]').getAttribute("content")) === "https://john-liu-dev.github.io/shelf/og.png", "首页用通用分享图");
  await shareTagsMatch();
});

// 一排真书（2026-11-06）：手机约 22 本、桌面 72 本，金色约十分之一，横板下面一行说明；桌面上鼠标移上去抬起、有提示，点击进详情页；减少动画时不播
await visit("topshelf", "/", async () => {
  await page.waitForTimeout(1600);
  const n = await page.locator(".topshelf .bk-link").count();
  ok(n >= 18 && n <= 26, `手机上摆了 ${n} 本`);
  const gold = await page.locator(".topshelf .bk-body").evaluateAll((rs) => rs.filter((r) => r.style.getPropertyValue("--c") === "#f2c14e").length);
  ok(gold === Math.round(n / 10), `金色 ${gold} 本（约十分之一）`);
  ok((await page.locator(".topshelf-note").textContent()) === `长青榜前 ${n} 篇 · 按第一次被 HN 提到的时间摆放`, "横板下面的说明");
  ok((await page.locator(".topshelf g[transform^='rotate(-9']").count()) === 1, "最后一本斜靠 9°");
  ok((await page.locator(".home-lede").textContent()) === "Hacker News 二十年里，被不同的人在不同月份反复推荐的 1,800 篇论文。怎么选的 →", "开场句只有一句，在这排书下面");
});
{
  const desk = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  const p2 = await desk.newPage();
  console.log("\ntopshelf-desktop  /");
  await p2.goto(`${base}/`, { waitUntil: "networkidle" });
  await p2.waitForSelector(".topshelf .bk-link");
  ok((await p2.locator(".topshelf .bk-link").count()) === 72, "桌面摆 72 本");
  ok((await p2.locator(".topshelf-svg.is-standing").count()) === 0, "减少动画时不播立起来的动画");
  const bk = p2.locator(".topshelf .bk-link").nth(30);
  await bk.hover();
  await p2.waitForFunction(() => !document.querySelector(".topshelf-tip")?.hidden);
  const tipText = await p2.locator(".topshelf-tip").textContent();
  ok(/^No\.\d+ · .+ · .+ · \d+ 人$/.test(tipText ?? ""), `鼠标移上去有提示（${tipText}）`);
  const lifted = await bk.locator(".bk-lift").evaluate((g) => getComputedStyle(g).transform);
  ok(lifted.includes("-7"), `这本抬起 7px（${lifted}）`);
  await Promise.all([p2.waitForURL(/\/p\//), bk.click()]);
  ok(p2.url().includes("/shelf/p/"), `点击进详情页（${p2.url().replace(base, "")}）`);
  await desk.close();
}

await visit("paper", "/p/1706.03762/", async () => {
  ok((await page.locator("h1").textContent()) === "Attention Is All You Need", "标题");
  ok((await page.locator("a.btn-primary").getAttribute("href")) === "https://arxiv.org/abs/1706.03762", "开始阅读去 arXiv");
  await page.getByRole("button", { name: "复制提问提示词" }).click();
  await page.waitForTimeout(300);
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  ok(clip.includes("https://arxiv.org/abs/1706.03762") && clip.includes("中文导读"), `复制的提示词带链接和导读（${clip.length} 字）`);
  ok((await page.getByRole("button", { name: /已复制/ }).count()) === 1, "按钮显示已复制");
  await page.getByRole("button", { name: "复制 Markdown 笔记" }).click();
  await page.waitForTimeout(300);
  const note = await page.evaluate(() => navigator.clipboard.readText());
  ok(note.startsWith("---") && note.includes("Attention Is All You Need") && note.includes("arxiv.org/abs/1706.03762"), `复制的 Markdown 笔记（${note.length} 字）`);
  ok((await page.locator("img").count()) === 0, "没有图片（PDF 首页预览不在公开站）");
  ok((await page.locator(".review").count()) >= 6, "HN 书评");
  // 分享卡片：主书架用自己的封面图
  const og = await page.locator('meta[property="og:image"]').getAttribute("content");
  ok(og === "https://john-liu-dev.github.io/shelf/og/1706.03762.jpg", `og:image（${og}）`);
  const ogLocal = await fetch(`${base}/og/1706.03762.jpg`);
  ok(ogLocal.ok && ogLocal.headers.get("content-type")?.startsWith("image/jpeg"), "分享图文件在");
  ok((await page.locator('meta[name="twitter:card"]').getAttribute("content")) === "summary_large_image", "twitter:card");
});

await visit("about", "/about/", async () => {
  ok((await page.locator("h1").textContent()) === "关于 HackerShelf", "关于页");
  ok((await page.locator('a[href="https://github.com/john-liu-dev"]').count()) >= 1, "作者 GitHub 链接");
  ok((await page.locator("img").count()) === 0, "没有头像");
});

await visit("paper-old-id", "/p/math/9404236/", async () => {
  ok((await page.locator("h1").textContent())?.startsWith("On proof and progress"), "旧式编号的详情页");
});

await visit("browse", "/browse/", async () => {
  ok((await page.locator(".shelf-item").count()) === 42, "默认视图 42 本");
  ok(!(await page.locator("text=加载中").count()), "默认视图不用等 browse.json");
});

// 篇数每月都会变（D47 月度更新），从站点自己的 browse.json 取
const total = (await (await fetch(`${base}/browse.json`)).json()).length;
const pages = Math.ceil(total / 42);
await visit("browse-recent-all", "/browse/?sort=recent&tier=all&page=2", async () => {
  await page.waitForFunction(() => !document.body.innerText.includes("加载中"));
  const note = await page.locator("[aria-live=polite]").first().textContent();
  const n = total.toLocaleString("en-US");
  ok((note ?? "").includes(`${n} 篇`), `含候选层共 ${n} 篇（${note?.slice(0, 20)}）`);
  ok((await page.locator(".shelf-item").count()) === 42, "第 2 页 42 本");
  ok((await page.locator(`text=2 / ${pages}`).count()) === 1, `分页 2 / ${pages}`);
});

await visit("browse-nav", "/browse/", async () => {
  await page.getByRole("link", { name: "列表" }).click();
  await page.waitForURL(/view=list/);
  await page.waitForFunction(() => !document.body.innerText.includes("加载中"));
  ok((await page.locator(".entries--list .entry").count()) === 42, "点“列表”后在浏览器里重算（42 行）");
});

await visit("search", "/search/?q=attention", async () => {
  await page.waitForSelector(".entries .entry", { timeout: 15000 });
  const first = await page.locator(".entries .entry .entry-title").first().textContent();
  ok(/attention/i.test(first ?? ""), `地址栏的搜索词生效，第一条：${first}`);
});

// 开源书（Phase 5，D48）：书架页、详情页、首页一排、搜索、页头导航
await visit("books", "/books/", async () => {
  ok((await page.locator("h1").first().textContent()) === "开源书", "书架页标题");
  const items = await page.locator(".shelf-item").count();
  ok(items >= 50, `书架上有书（${items} 个位置，含 No.2–7 那一排）`);
  const hrefs = await page.locator(".shelf-item a").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  ok(hrefs.every((h) => h.startsWith("/shelf/books/") && h.endsWith("/")), "书的链接带 /shelf 前缀和结尾斜杠");
  ok((await page.locator('.site-nav a[href="/shelf/books/"][aria-current="page"]').count()) === 1, "页头“图书”是当前页");
  ok(((await page.locator(".site-footer").textContent()) ?? "").includes("free-programming-books（CC BY 4.0）"), "页脚写明书单来源");
  ok(((await page.locator(".home-lede").textContent()) ?? "").includes("链接指向官方免费版，个别原站失效的会注明。"), "开场句：个别原站失效的会注明");
  ok((await page.locator('meta[property="og:title"]').getAttribute("content")) === "开源书 · HackerShelf", "og:title 是开源书");
  await shareTagsMatch();
});

await visit("book", "/books/structure-and-interpretation-of-computer-programs/", async () => {
  ok((await page.locator("h1").textContent()) === "Structure and Interpretation of Computer Programs", "标题");
  const read = await page.locator("a.btn-primary").getAttribute("href");
  ok(read?.startsWith("https://mitp-content-server.mit.edu/") ?? false, `免费阅读去 MIT Press 官方全文（${read?.slice(0, 40)}…）`);
  ok((await page.locator(".prose-zh").count()) === 1, "有中文导读");
  ok((await page.locator("#how .howto li").count()) >= 2, "有怎么读");
  ok((await page.locator("#reviews .review").count()) >= 6, "有 HN 书评");
  ok((await page.locator('meta[property="og:image"]').getAttribute("content"))?.endsWith("/og/books/structure-and-interpretation-of-computer-programs.jpg") ?? false, "分享图用这本书的封面");
  const og = await fetch(`${base}/og/books/structure-and-interpretation-of-computer-programs.jpg`);
  ok(og.ok, "分享图文件存在");
  await shareTagsMatch();
});

await visit("book-unfinished", "/books/the-book-of-shaders/", async () => {
  ok((await page.locator(".pill", { hasText: "未写完" }).count()) === 1, "没写完的书标“未写完”");
});

await visit("home-books", "/", async () => {
  const row = page.locator("section", { has: page.locator("h2", { hasText: "开源书" }) });
  ok((await row.locator(".shelf-item").count()) === 7, "首页有一排开源书（7 本）");
  ok((await row.locator('a[href="/shelf/books/"]').count()) === 1, "首页那一排链到整面书架");
});

await visit("search-book", "/search/?q=sicp", async () => {
  await page.waitForSelector(".entries .entry", { timeout: 15000 });
  const hrefs = await page.locator(".entries .entry").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  ok(hrefs.some((h) => h === "/shelf/books/structure-and-interpretation-of-computer-programs/"), "搜 SICP 能搜到这本书");
});

await visit("fresh", "/fresh/", async () => {
  await page.waitForSelector(".fresh-entry", { timeout: 15000 });
  ok((await page.locator(".fresh-entry").count()) >= 6, `新鲜书架有条目（${await page.locator(".fresh-entry").count()}）`);
});

console.log("\n404  /does-not-exist/");
const r404 = await page.goto(`${base}/does-not-exist/`);
ok(r404?.status() === 404 && (await page.locator("h1").textContent()) === "没有这一页", "404 页");

console.log("\n站内跳转");
await page.goto(`${base}/p/1706.03762/`, { waitUntil: "networkidle" });
await page.locator("header .site-nav a", { hasText: "浏览" }).click();
await page.waitForURL(/\/browse\/?$/);
ok((await page.locator(".shelf-item").count()) === 42, "页头导航到浏览页");
await page.locator(".shelf-item a").first().click();
await page.waitForURL(/\/p\/.+\/$/);
ok((await page.locator("h1").count()) === 1, `从书架点进详情页（${page.url().replace(base, "")}）`);

await browser.close();
console.log(failed ? `\n没通过：${failed} 项` : "\n全部通过");
process.exit(failed ? 1 : 0);
