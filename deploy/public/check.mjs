#!/usr/bin/env node
/**
 * 公开站产物检查（D46）：发布之前必须通过。
 *   node deploy/public/check.mjs <site 目录>
 * 查这些：
 *   1. 不该有的文件：PDF、数据库、.env、位图（由 PDF 派生的缩略图；分享图和图标除外）、service worker。
 *   2. 不该有的内容：本机开发服务器的地址、arXiv 正文（arXiv HTML 的 ltx_ 排版类名）、PDF 缩略图的路径、
 *      .env 里的密钥值；HS_CHECK_DENY（正则）里你自己的私有字符串，比如私网主机名、邮箱。
 *   3. 大小：总计 < 1 GB（GitHub Pages 的上限）。
 * 有问题就列出文件和上下文，退出码 1。
 */
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../..");
const site = path.resolve(process.argv[2] ?? "");
if (!process.argv[2] || !fs.existsSync(site)) {
  console.error("用法：node deploy/public/check.mjs <site 目录>");
  process.exit(2);
}
const LIMIT = 1024 ** 3;
const TEXT = new Set([".html", ".txt", ".js", ".mjs", ".css", ".json", ".xml", ".svg", ".webmanifest", ".map", ".md"]);
const BAD_EXT = new Set([".pdf", ".db", ".sqlite", ".sqlite3", ".env", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".tif", ".tiff", ".epub"]);
// 公开站自己生成的图，只许在这几个位置：分享图（web/scripts/og-images.mjs）和图标（web/scripts/icons.mjs）。
// 由 PDF 派生的缩略图（.webp、thumbs/）照样不许进来。
const OWN_IMAGES = [/^og\/.+\.jpg$/, /^og\.png$/, /^apple-icon\.png$/, /^_next\/static\/media\/apple-icon\.[a-z0-9]+\.png$/];

// .env 里的值：密钥和联系邮箱不许出现（只取长度够的，避免误报）
function envSecrets() {
  const out = [];
  try {
    for (const line of fs.readFileSync(path.join(ROOT, ".env"), "utf8").split("\n")) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
      if (!m) continue;
      const v = m[2].replace(/^["']|["']$/g, "");
      if (/(KEY|TOKEN|SECRET|PASSWORD|EMAIL)/.test(m[1]) && v.length >= 6) out.push({ name: `.env 的 ${m[1]}`, value: v });
    }
  } catch {}
  return out;
}

const RULES = [
  { name: "本机开发服务器的地址", re: /localhost:\d{2,5}|127\.0\.0\.1:\d{2,5}/ },
  // CSS 里可能有排版用的同名选择器，那只是样式名；正文只会出现在 HTML、数据文件和脚本里
  { name: "arXiv 正文（ltx_ 排版）", re: /\bltx_(?:document|para|section|title|p)\b/, skip: /\.css$/ },
  { name: "PDF 缩略图", re: /\/thumbs?\/|\/api\/thumb/ },
];
if (process.env.HS_CHECK_DENY) RULES.push({ name: "HS_CHECK_DENY 里的私有字符串", re: new RegExp(process.env.HS_CHECK_DENY, "i") });

function* walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) yield* walk(p);
    else yield p;
  }
}

const problems = [];
const add = (file, why, ctx = "") => problems.push({ file: path.relative(site, file), why, ctx });
const secrets = envSecrets();

let total = 0;
let files = 0;
for (const f of walk(site)) {
  files++;
  const st = fs.statSync(f);
  total += st.size;
  const base = path.basename(f);
  const ext = path.extname(f).toLowerCase();
  const rel = path.relative(site, f).split(path.sep).join("/");
  const own = OWN_IMAGES.some((re) => re.test(rel));
  if ((BAD_EXT.has(ext) && !own) || base === ".env" || base.startsWith(".env.")) add(f, `不该公开的文件类型（${ext || base}）`);
  if (base === "sw.js") add(f, "service worker");
  if (!TEXT.has(ext)) continue;
  const s = fs.readFileSync(f, "utf8");
  for (const r of RULES) {
    if (r.skip?.test(f)) continue;
    const m = s.match(r.re);
    if (m) add(f, r.name, s.slice(Math.max(0, m.index - 60), m.index + 60).replace(/\s+/g, " "));
  }
  for (const x of secrets) if (s.includes(x.value)) add(f, x.name, "（值不显示）");
}
if (total > LIMIT) add(site, `总大小 ${(total / 1024 ** 2).toFixed(0)} MB，超过 1 GB`);

console.log(`检查 ${files.toLocaleString()} 个文件，${(total / 1024 ** 2).toFixed(1)} MB；对照 .env 的 ${secrets.length} 个值${process.env.HS_CHECK_DENY ? "和 HS_CHECK_DENY" : ""}`);
if (problems.length) {
  for (const p of problems.slice(0, 60)) console.log(`  !! ${p.why}：${p.file}${p.ctx ? `  …${p.ctx}…` : ""}`);
  if (problems.length > 60) console.log(`  …… 还有 ${problems.length - 60} 处`);
  console.log(`没通过：${problems.length} 处`);
  process.exit(1);
}
console.log("通过：没有私有内容");
