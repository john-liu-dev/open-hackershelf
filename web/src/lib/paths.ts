import path from "node:path";

/** data/ 目录：默认是仓库根目录下的 data/（web/ 的上一级），部署时用 HS_DATA_DIR 指定。 */
export function dataDir(): string {
  return process.env.HS_DATA_DIR || path.resolve(process.cwd(), "..", "data");
}

export function catalogPath(): string {
  return process.env.CATALOG_DB || path.join(dataDir(), "build", "catalog.db");
}

export function searchIndexPath(): string {
  return path.join(dataDir(), "build", "search-index.json");
}
