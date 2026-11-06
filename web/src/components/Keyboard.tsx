"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

// 公开站只有发现层的快捷键
const HELP: [string, string][] = [
  ["/", "搜索"],
  ["j / k", "下一条 / 上一条"],
  ["Enter", "打开选中的条目"],
  ["Esc", "关闭弹窗 / 返回"],
  ["g h / g b / g n", "首页 / 浏览 / 新鲜"],
  ["c", "复制提问提示词（论文页）"],
  ["o", "复制 Markdown 笔记（论文页）"],
  ["t", "切换深浅色"],
  ["?", "显示这份帮助"],
];

function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

const GO: Record<string, string> = { h: "/", b: "/browse", n: "/fresh" };

/** 全站键盘：/ 搜索，j/k 上下，Enter 打开，Esc 返回，g h 首页，? 帮助。 */
export function Keyboard() {
  const router = useRouter();
  const [help, setHelp] = useState(false);

  useEffect(() => {
    let sel = -1;
    let gPending = 0;
    const items = () => Array.from(document.querySelectorAll<HTMLElement>("[data-nav-item]"));
    const select = (i: number) => {
      const list = items();
      if (!list.length) return;
      sel = Math.max(0, Math.min(list.length - 1, i));
      list.forEach((el, k) => el.setAttribute("aria-selected", String(k === sel)));
      list[sel].scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
      list[sel].focus({ preventScroll: true });
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTyping(e.target)) {
        if (e.key === "Escape") (e.target as HTMLElement).blur();
        return;
      }
      if (e.key === "/") {
        e.preventDefault();
        const box = document.querySelector<HTMLInputElement>("[data-search-input]");
        if (box) box.focus();
        else router.push("/search");
      } else if (e.key === "j") {
        select(sel + 1);
      } else if (e.key === "k") {
        select(sel - 1);
      } else if (e.key === "Enter" && sel >= 0) {
        items()[sel]?.click();
      } else if (e.key === "Escape") {
        // 页面上有打开的浮层（高亮工具条、弹层、Aa 菜单、对话框）或者选着字：Esc 只关它们，不返回上一页
        const open = document.querySelector(".hl-bar, .hl-pop, .aa-menu, dialog[open]") || !(window.getSelection()?.isCollapsed ?? true);
        if (help) setHelp(false);
        else if (!open && window.history.length > 1) router.back();
      } else if (e.key === "?") {
        setHelp((h) => !h);
      } else if (e.key === "g") {
        gPending = Date.now();
        return;
      } else if (Date.now() - gPending < 1000 && GO[e.key]) {
        router.push(GO[e.key]);
      } else if (e.key === "t") {
        const h = document.documentElement;
        const m = h.dataset.mode === "dark" ? "light" : "dark";
        h.dataset.mode = m;
        try {
          localStorage.setItem("hs-mode", m);
        } catch {}
      }
      gPending = 0;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, help]);

  if (!help) return null;
  return (
    <div role="dialog" aria-label="键盘快捷键" onClick={() => setHelp(false)}
      style={{ position: "fixed", inset: 0, background: "color-mix(in srgb, var(--bg) 70%, transparent)", zIndex: 50,
        display: "grid", placeItems: "center", backdropFilter: "blur(2px)" }}>
      <div className="dialog">
        <div className="t-zh" style={{ fontSize: 19, fontWeight: 600, marginBottom: 12 }}>键盘快捷键</div>
        <table style={{ fontSize: 14 }}>
          <tbody>
            {HELP.map(([k, v]) => (
              <tr key={k}>
                <td style={{ padding: "4px 16px 4px 0" }}><span className="kbd">{k}</span></td>
                <td className="muted">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
