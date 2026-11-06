import { browseRows } from "@/lib/catalog";

export const dynamic = "force-static";

/** 公开站浏览页的精简目录（构建期导出成静态文件 browse.json）。 */
export function GET(): Response {
  return Response.json(browseRows());
}
