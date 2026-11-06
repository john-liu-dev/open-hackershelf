import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // server-only 在 Node 测试环境里会直接抛错，这里换成空模块
  resolve: { alias: { "@": path.resolve(__dirname, "src"), "server-only": path.resolve(__dirname, "tests/stubs/server-only.ts") } },
  test: { environment: "node", include: ["tests/**/*.test.ts"] },
});
