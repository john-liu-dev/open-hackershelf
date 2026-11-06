/** 搜索引擎配置（服务端首屏和前端即时搜索共用）。 */
import { describe, expect, it } from "vitest";
import { newEngine, runSearch, tokenize, type Hit } from "@/lib/search-engine";

const doc = (id: string, t: string, z: string, p: number, c: 0 | 1, f = "ai"): Hit => ({ id, t, z, a: "", y: 2020, f, s: 0, p, c, o: "", k: "" });

describe("search-engine", () => {
  it("中文按单字 + 双字切，英文按词、转小写", () => {
    expect(tokenize("注意力")).toEqual(["注", "注意", "意", "意力", "力"]);
    expect(tokenize("Attention Is All")).toEqual(["attention", "is", "all"]);
  });

  it("相关度相近时，被更多人提到、在主书架的排前面；结果数和总数分开给", () => {
    const e = newEngine();
    e.addAll([
      doc("arxiv:1", "Attention Residuals", "注意力残差", 2, 0),
      doc("arxiv:2", "Attention Is All You Need", "注意力就是你所需要的一切", 150, 1),
      doc("arxiv:3", "Attention Sinks", "注意力汇聚", 5, 1, "cs"),
    ]);
    const r = runSearch(e, "attention", "", 2);
    expect(r.total).toBe(3);
    expect(r.hits.map((h) => h.id)).toEqual(["arxiv:2", "arxiv:3"]);
    expect(runSearch(e, "注意力", "cs").hits.map((h) => h.id)).toEqual(["arxiv:3"]);
  });
});
