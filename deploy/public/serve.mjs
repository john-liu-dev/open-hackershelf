#!/usr/bin/env node
/**
 * 本机预览公开站：node deploy/public/serve.mjs [site 目录] [端口]
 * 默认目录 web/.next-public（deploy/public/build.sh 的产物），端口 4173；和 GitHub Pages 一样挂在 /shelf/ 下，目录自动找 index.html，
 * 不带斜杠的目录 301 到带斜杠的，找不到给 404.html；文本类文件按 gzip 压缩（GitHub Pages 也压缩，量 Lighthouse 时才可比）。
 */
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import zlib from "node:zlib";

const root = path.resolve(process.argv[2] ?? path.join(path.dirname(new URL(import.meta.url).pathname), "../../web/.next-public"));
const port = Number(process.argv[3] ?? 4173);
const BASE = "/shelf";
const TYPES = {
  ".html": "text/html; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".png": "image/png", ".jpg": "image/jpeg", ".woff2": "font/woff2", ".woff": "font/woff",
};

http
  .createServer((req, res) => {
    const u = new URL(req.url ?? "/", "http://x");
    if (!u.pathname.startsWith(`${BASE}/`) && u.pathname !== BASE) {
      res.writeHead(302, { location: `${BASE}/` }).end();
      return;
    }
    const rel = decodeURIComponent(u.pathname.slice(BASE.length)) || "/";
    let file = path.join(root, rel);
    if (!file.startsWith(root)) return res.writeHead(403).end();
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) {
      if (!rel.endsWith("/")) return res.writeHead(301, { location: `${BASE}${rel}/${u.search}` }).end();
      file = path.join(file, "index.html");
    }
    const ok = fs.existsSync(file) && fs.statSync(file).isFile();
    const f = ok ? file : path.join(root, "404.html");
    const type = TYPES[path.extname(f)] ?? "application/octet-stream";
    const gz = /gzip/.test(req.headers["accept-encoding"] ?? "") && /^(text|application\/json|image\/svg)/.test(type);
    res.writeHead(ok ? 200 : 404, { "content-type": type, "cache-control": "max-age=600", ...(gz ? { "content-encoding": "gzip", vary: "accept-encoding" } : {}) });
    const body = fs.createReadStream(f);
    if (gz) body.pipe(zlib.createGzip({ level: 6 })).pipe(res);
    else body.pipe(res);
  })
  .listen(port, "127.0.0.1", () => console.log(`公开站预览：http://localhost:${port}${BASE}/（目录 ${root}）`));
