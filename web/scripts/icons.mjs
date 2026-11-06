// 站点图标（分享前包装，2026-11-05）：以 src/app/icon.svg 为准，生成 Next.js 约定的另外两个文件
//   src/app/favicon.ico   16、32、48 像素三张 PNG 打包（老浏览器和收藏夹用；圆角外透明）
//   src/app/apple-icon.png 180 像素，方形满版（iOS 自己会切圆角）
// 改了 icon.svg 之后运行：node scripts/icons.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "src", "app");
const svg = fs.readFileSync(path.join(dir, "icon.svg"), "utf8");

async function render(page, source, size, transparent) {
  const sized = source.replace("<svg ", `<svg width="${size}" height="${size}" `);
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<html><body style="margin:0;background:transparent">${sized}</body></html>`);
  return page.screenshot({ omitBackground: transparent, clip: { x: 0, y: 0, width: size, height: size } });
}

/** 把几张 PNG 打成一个 .ico（每张原样存 PNG，现代浏览器和 Windows 都认）。 */
function ico(pngs) {
  const head = Buffer.alloc(6);
  head.writeUInt16LE(0, 0);
  head.writeUInt16LE(1, 2);
  head.writeUInt16LE(pngs.length, 4);
  let offset = 6 + 16 * pngs.length;
  const entries = pngs.map(({ size, buf }) => {
    const e = Buffer.alloc(16);
    e.writeUInt8(size >= 256 ? 0 : size, 0);
    e.writeUInt8(size >= 256 ? 0 : size, 1);
    e.writeUInt16LE(1, 4);
    e.writeUInt16LE(32, 6);
    e.writeUInt32LE(buf.length, 8);
    e.writeUInt32LE(offset, 12);
    offset += buf.length;
    return e;
  });
  return Buffer.concat([head, ...entries, ...pngs.map((p) => p.buf)]);
}

const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({ deviceScaleFactor: 1 });
const pngs = [];
for (const size of [16, 32, 48]) pngs.push({ size, buf: await render(page, svg, size, true) });
fs.writeFileSync(path.join(dir, "favicon.ico"), ico(pngs));
// 满版：去掉外框圆角，iOS 会按自己的形状切
const square = svg.replace(/<rect width="64" height="64" rx="14"/, '<rect width="64" height="64"');
fs.writeFileSync(path.join(dir, "apple-icon.png"), await render(page, square, 180, false));
await browser.close();
console.log(`icons: favicon.ico（${pngs.map((p) => p.size).join("、")}）、apple-icon.png（180）→ ${dir}`);
