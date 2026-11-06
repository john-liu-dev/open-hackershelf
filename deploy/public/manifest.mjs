#!/usr/bin/env node
/**
 * 公开仓库的产物清单（推送前给我看）：node deploy/public/manifest.mjs <公开仓库目录>
 * 列出仓库里除 site/ 以外的文件、site/ 里的页面和数据文件、按目录和类型的大小、压缩后大约多大、最大的几个文件。
 */
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

const repo = path.resolve(process.argv[2] ?? "");
const site = path.join(repo, "site");
if (!fs.existsSync(site)) {
  console.error("用法：node deploy/public/manifest.mjs <公开仓库目录>（里面要有 site/）");
  process.exit(2);
}
const mb = (n) => `${(n / 1024 ** 2).toFixed(1)} MB`;
const kb = (n) => (n < 1024 ** 2 ? `${(n / 1024).toFixed(0)} KB` : mb(n));

function* walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === ".git") continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) yield* walk(p);
    else yield p;
  }
}

const all = [...walk(repo)].map((f) => ({ f, rel: path.relative(repo, f), size: fs.statSync(f).size }));
const outside = all.filter((x) => !x.rel.startsWith(`site${path.sep}`));
const inSite = all.filter((x) => x.rel.startsWith(`site${path.sep}`)).map((x) => ({ ...x, rel: x.rel.slice(5) }));
const sum = (xs) => xs.reduce((n, x) => n + x.size, 0);

console.log(`公开仓库 ${repo}`);
console.log(`\n== 仓库里 site/ 以外的文件（${outside.length} 个）`);
for (const x of outside.sort((a, b) => a.rel.localeCompare(b.rel))) console.log(`   ${x.rel.padEnd(36)} ${kb(x.size)}`);

let gz = 0;
for (const x of inSite) if (/\.(html|txt|js|css|json|svg)$/.test(x.rel)) gz += zlib.gzipSync(fs.readFileSync(x.f), { level: 6 }).length;
  else gz += x.size;
console.log(`\n== site/：${inSite.length.toLocaleString()} 个文件，${mb(sum(inSite))}（gzip 后约 ${mb(gz)}，GitHub Pages 上限 1 GB）`);

const pages = inSite.filter((x) => x.rel.endsWith("index.html") || x.rel === "404.html");
const detail = pages.filter((x) => x.rel.startsWith(`p${path.sep}`));
console.log(`\n== 页面（${pages.length.toLocaleString()} 个 HTML）`);
for (const x of pages.filter((p) => !detail.includes(p)).sort((a, b) => a.rel.localeCompare(b.rel))) console.log(`   /${x.rel.replace(/index\.html$/, "").padEnd(34)} ${kb(x.size)}`);
const ds = detail.map((x) => x.size).sort((a, b) => a - b);
console.log(`   /p/<arXiv 编号>/ × ${detail.length.toLocaleString()}         共 ${mb(sum(detail))}，中位数 ${kb(ds[Math.floor(ds.length / 2)] ?? 0)}，最大 ${kb(ds.at(-1) ?? 0)}`);

console.log("\n== 数据文件（浏览器运行时读取）");
for (const name of ["search-index.json", "browse.json", "fresh.json"]) {
  const x = inSite.find((y) => y.rel === name);
  console.log(`   ${name.padEnd(36)} ${x ? kb(x.size) : "（没有）"}${name === "fresh.json" ? "  ← 本机预览用，不提交；线上由 Actions 每天生成" : ""}`);
}

const byTop = new Map();
for (const x of inSite) {
  const top = x.rel.includes(path.sep) ? `${x.rel.split(path.sep)[0]}/` : "（根目录文件）";
  const v = byTop.get(top) ?? { n: 0, size: 0 };
  byTop.set(top, { n: v.n + 1, size: v.size + x.size });
}
console.log("\n== 按目录");
for (const [k, v] of [...byTop].sort((a, b) => b[1].size - a[1].size)) console.log(`   ${k.padEnd(36)} ${String(v.n).padStart(6)} 个  ${mb(v.size)}`);

const byExt = new Map();
for (const x of inSite) {
  const e = path.extname(x.rel) || "（无扩展名）";
  const v = byExt.get(e) ?? { n: 0, size: 0 };
  byExt.set(e, { n: v.n + 1, size: v.size + x.size });
}
console.log("\n== 按类型");
for (const [k, v] of [...byExt].sort((a, b) => b[1].size - a[1].size)) console.log(`   ${k.padEnd(36)} ${String(v.n).padStart(6)} 个  ${mb(v.size)}`);

console.log("\n== 最大的 5 个文件");
for (const x of [...inSite].sort((a, b) => b.size - a.size).slice(0, 5)) console.log(`   ${x.rel.padEnd(52)} ${kb(x.size)}`);

console.log(`
== 不在公开站里的
   论文 PDF 和全文、由 PDF 派生的缩略图、书的全文、任何个人数据`);
