import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { AREA_COLORS, COVER_FALLBACK, coverSpec } from "@/lib/cover";

describe("封面 coverSpec", () => {
  it("同一个 ID 两次结果完全一致", () => {
    const ids = ["arxiv:1706.03762", "arxiv:math/9404236", "arxiv:cs/0011047", "arxiv:2005.14165", "arxiv:1803.05316"];
    for (const id of ids) {
      const a = coverSpec(id, "llm", "Attention Is All You Need", "注意力就是你所需要的一切");
      const b = coverSpec(id, "llm", "Attention Is All You Need", "注意力就是你所需要的一切");
      expect(b).toEqual(a);
    }
  });

  it("不同 ID 的图案不同；底色只由领域决定", () => {
    const a = coverSpec("arxiv:1706.03762", "llm", "A", null);
    const b = coverSpec("arxiv:2005.14165", "llm", "A", null);
    expect(a.bg).toBe(AREA_COLORS.llm);
    expect(b.bg).toBe(AREA_COLORS.llm);
    expect(`${a.stroke}${a.fill}${a.accent}`).not.toBe(`${b.stroke}${b.fill}${b.accent}`);
    expect(coverSpec("arxiv:1706.03762", null, "A", null).bg).toBe(COVER_FALLBACK);
    expect(coverSpec("arxiv:1706.03762", "no-such-area", "A", null).bg).toBe(COVER_FALLBACK);
  });

  it("和设计稿一致：Attention 的样稿值", () => {
    // 样稿（docs/design/reference/B1-Home.dc.html）里 1706.03762 的图案种类和标题字号
    const s = coverSpec("arxiv:1706.03762", "llm", "Attention Is All You Need", "注意力就是你所需要的一切");
    expect(s.mainTitle).toBe("Attention Is All You Need");
    expect(s.titleSize).toBe(10.5);
    expect(s.zhMain).toBe("注意力就是你所需要的一切");
    // 冒号前是主标题；中文按全角冒号切
    const l = coverSpec("arxiv:2106.09685", "llm", "LoRA: Low-Rank Adaptation of Large Language Models", "LoRA：大语言模型的低秩适配");
    expect(l.mainTitle).toBe("LoRA");
    expect(l.titleSize).toBe(12.5);
    expect(l.zhMain).toBe("LoRA");
  });

  it("web 里的副本和 docs/design/cover.ts 原件一致（只允许文件头注释不同）", () => {
    const strip = (s: string) => s.replace(/^\/\*\*[\s\S]*?\*\/\s*/, "");
    const doc = fs.readFileSync(path.resolve(__dirname, "../../docs/design/cover.ts"), "utf8");
    const web = fs.readFileSync(path.resolve(__dirname, "../src/lib/cover.ts"), "utf8");
    expect(strip(web)).toBe(strip(doc));
  });

  it("五种图案都会出现，路径不为空", () => {
    const kinds = new Set<string>();
    for (let i = 0; i < 400; i++) {
      const s = coverSpec(`arxiv:2401.${String(10000 + i)}`, "ml", "T", null);
      kinds.add(s.pattern);
      expect(s.accent.length).toBeGreaterThan(4);
    }
    expect([...kinds].sort()).toEqual(["bands", "dots", "lines", "rings", "waves"]);
  });

  it("和设计稿里的封面函数逐字一致（500 个 ID）", () => {
    // 从参考稿 B1 取出画布脚本里的 cover()，直接运行它做对照
    const html = fs.readFileSync(path.resolve(__dirname, "../../docs/design/reference/B1-Home.dc.html"), "utf8");
    const src = html.split('data-dc-script')[1].split(">").slice(1).join(">").split("</script>")[0];
    const Component = new Function(`class DCLogic {}; ${src}; return Component;`)();
    const ref = new Component();
    const areas = Object.keys(AREA_COLORS);
    for (let i = 0; i < 500; i++) {
      const id = i % 3 ? `arxiv:${2000 + (i % 25)}.${String(1000 + i * 7)}` : `arxiv:math/${9400000 + i * 13}`;
      const area = areas[i % areas.length];
      const title = i % 2 ? "Seven Sketches in Compositionality: An Invitation to Applied Category Theory" : "Dancing links";
      const zh = "组合性七篇素描：应用范畴论邀请";
      const r = ref.cover(id, area, title, zh, 2018, "");
      const s = coverSpec(id, area, title, zh);
      expect([s.bg, s.stroke, s.fill, s.accent, s.titleSize, s.mainTitle, s.zhMain]).toEqual([r.bg, r.p, r.f, r.q, r.ts, r.main, r.zhMain]);
    }
  });
});

describe("封面标题字号 fitTitleSize", () => {
  it("普通标题用设计算法的字号", async () => {
    const { fitTitleSize } = await import("@/components/Cover");
    expect(fitTitleSize("Attention Is All You Need", 10.5, 81, 6)).toBe(10.5);
    expect(fitTitleSize("Language Models are Few-Shot Learners", 8.6, 81, 6)).toBe(8.6);
  });
  it("长单词、超长标题收小", async () => {
    const { fitTitleSize } = await import("@/components/Cover");
    expect(fitTitleSize("TheAgentCompany", 12.5, 81, 6)).toBeLessThan(12.5);
    const long = "Quantum principal component analysis only achieves an exponential speedup because of its state preparation assumptions";
    expect(fitTitleSize(long, 7.2, 81, 6)).toBeLessThan(7.2);
  });
});

describe("封面中文名 coverZh", () => {
  it("去掉括号里的英文原名，长问句在问号后截断", async () => {
    const { coverZh } = await import("@/components/Cover");
    expect(coverZh("循环独立机制（Recurrent Independent Mechanisms）")).toBe("循环独立机制");
    expect(coverZh("Stack Overflow 过时了吗？ChatGPT 对 Stack Overflow 问题回答特征的实证研究")).toBe("Stack Overflow 过时了吗？");
    expect(coverZh("注意力就是你所需要的一切")).toBe("注意力就是你所需要的一切");
    expect(coverZh("论智能的度量（附录）")).toBe("论智能的度量（附录）");
  });
});

describe("封面小字不透明度 mutedAlpha", () => {
  // 与 axe-core 一样：先把半透明白色和底色混成 8 位颜色，再算 WCAG 对比度
  const lin = (c: number) => (c / 255 <= 0.03928 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4);
  const lum = (x: number[]) => 0.2126 * lin(x[0]) + 0.7152 * lin(x[1]) + 0.0722 * lin(x[2]);
  const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const ratio = (bg: string, a: number) => {
    const b = hex(bg);
    const f = b.map((c) => Math.round(a * 255 + (1 - a) * c));
    return (lum(f) + 0.05) / (lum(b) + 0.05);
  };

  it("所有领域底色上领域名、中文名、年份都 ≥ 4.5:1，且不低于设计值", async () => {
    const { mutedAlpha } = await import("@/components/Cover");
    for (const bg of [...Object.values(AREA_COLORS), COVER_FALLBACK]) {
      for (const base of [0.72, 0.9, 0.7]) {
        const a = mutedAlpha(bg, base);
        expect(a).toBeGreaterThanOrEqual(base);
        expect(ratio(bg, a)).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("深色底保持设计值，只有较亮的底色调高", async () => {
    const { mutedAlpha } = await import("@/components/Cover");
    expect(mutedAlpha(AREA_COLORS.llm, 0.72)).toBe(0.72);
    expect(mutedAlpha(AREA_COLORS["rl-agents"], 0.72)).toBeGreaterThan(0.85);
  });
});
