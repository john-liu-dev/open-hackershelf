#!/usr/bin/env bash
# 公开站（D46）：构建 → 整理 → 检查 → 打印产物清单。不提交、不推送。
#   deploy/public/build.sh            完整构建
#   deploy/public/build.sh --no-build 只用现有的 web/.next-public 重新整理、检查
# 设了 HS_PUBLIC_REPO（GitHub Pages 仓库的工作区）时，再把站点放进 $HS_PUBLIC_REPO/site/，
# 连同 deploy/public/repo/ 里的 README、截图、工作流和新鲜书架的脚本；看过清单再自己提交、推送。
# 本机预览：node deploy/public/serve.mjs（默认 web/.next-public），打开 http://localhost:4173/shelf/
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO=${HS_PUBLIC_REPO:-}
OUT=web/.next-public

if [ "${1:-}" != "--no-build" ]; then
  echo "== 1. 构建（只认 *.public.tsx 路由，静态导出到 $OUT）"
  (cd web && rm -rf .next-public && HS_PUBLIC=1 npx next build >/dev/null)
fi
[ -f "$OUT/index.html" ] || { echo "!! $OUT 里没有 index.html，先完整构建一次"; exit 1; }

echo "== 1b. 分享图：主书架每篇一张（缓存在 data/build/og/，内容没变的不重截；要本机装了 Chrome）"
node web/scripts/og-images.mjs "$OUT" || echo "   分享图没生成，跳过：页面照常，只是分享卡片上没有图"

echo "== 2. 整理"
# 详情页用普通链接整页打开（components/PaperLink.tsx），它们的 RSC 数据文件用不到，每页 4 份，删掉
find "$OUT/p" -name '*.txt' -delete
# 开源书详情页也一样（书架、首页、搜索都用普通链接打开它们）；书架页 books/ 自己的留着：页头“图书”是站内跳转，会预取
[ -d "$OUT/books" ] && find "$OUT/books" -mindepth 2 -name '*.txt' -delete

echo "== 3. 检查私有内容和大小"
node deploy/public/check.mjs "$OUT"

if [ -z "$REPO" ]; then
  echo
  echo "没设 HS_PUBLIC_REPO：只构建和检查，不放进 Pages 仓库。"
  echo "新鲜书架（可选，会请求 Hugging Face、HN 和 arXiv）：node deploy/public/scripts/fresh.mjs --site $OUT"
  echo "本机预览：node deploy/public/serve.mjs，然后打开 http://localhost:4173/shelf/"
  exit 0
fi

echo "== 4. 放进 Pages 仓库的工作区 $REPO"
mkdir -p "$REPO/site" "$REPO/scripts" "$REPO/.github/workflows"
rsync -a --delete --exclude fresh.json "$OUT/" "$REPO/site/"
cp -L deploy/public/scripts/fresh.mjs deploy/public/scripts/parse.mjs deploy/public/scripts/fresh.config.json "$REPO/scripts/"
cp deploy/public/repo/README.md "$REPO/README.md"
[ -d deploy/public/repo/screenshots ] && rsync -a --delete deploy/public/repo/screenshots/ "$REPO/screenshots/"
cp deploy/public/repo/pages.yml "$REPO/.github/workflows/pages.yml"
cp deploy/public/repo/gitignore "$REPO/.gitignore"

echo "== 5. 本机预览用的新鲜书架（线上由 Actions 每天生成；这份不提交）"
if [ -n "$(find "$REPO/site/fresh.json" -mmin -360 2>/dev/null)" ]; then
  echo "   6 小时内抓过，沿用（不重复请求 arXiv 等来源）"
else
  node "$REPO/scripts/fresh.mjs" --site "$REPO/site" || true
fi
node deploy/public/check.mjs "$REPO/site"

echo
node deploy/public/manifest.mjs "$REPO"
echo
echo "本机预览：node deploy/public/serve.mjs \"$REPO/site\"，然后打开 http://localhost:4173/shelf/"
