import type { NextConfig } from "next";

/**
 * 公开静态站（D46）：GitHub Pages 上的 https://john-liu-dev.github.io/shelf/。
 * 只认 *.public.tsx / *.public.ts 的路由文件，静态导出到 .next-public/（deploy/public/build.sh 打包、检查）。
 * HS_BASE_PATH 改 basePath（默认 /shelf；挂在域名根目录时设成空串）。
 */
const BASE_PATH = process.env.HS_BASE_PATH ?? "/shelf";

const publicSite: NextConfig = {
  poweredByHeader: false,
  // Tailwind 4 走 Turbopack 的 CSS loader（create-next-app 16.4 的默认配置）
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  output: "export",
  basePath: BASE_PATH,
  trailingSlash: true,
  distDir: ".next-public",
  pageExtensions: ["public.tsx", "public.ts"],
  serverExternalPackages: ["better-sqlite3"],
  images: { unoptimized: true },
  // 固定的构建号：目录没变的页面，重新构建后字节不变，发布时只多出真正变了的文件
  generateBuildId: async () => "shelf",
  env: { NEXT_PUBLIC_HS_PUBLIC: "1", NEXT_PUBLIC_BASE_PATH: BASE_PATH },
};

export default publicSite;
