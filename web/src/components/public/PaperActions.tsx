"use client";

import { useEffect, useRef, useState } from "react";
import { buildPrompt, renderNote, type NoteData } from "@/lib/note";

/** 剪贴板：先用 Clipboard API（HTTPS 下可用），不行就退回选中隐藏文本框再复制（老 Safari）。 */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {}
    ta.remove();
    return ok;
  }
}

type Copied = { what: "prompt" | "note"; ok: boolean } | null;

/**
 * 公开站详情页的按钮：
 * - 复制提问提示词：提示词 + 论文链接 + 中文导读，贴进任意模型（快捷键 c）。
 * - 复制 Markdown 笔记：属性、导读、HN 原话，能贴进任何笔记软件（快捷键 o）。
 */
export function PaperActions({ data }: { data: NoteData }) {
  const [copied, setCopied] = useState<Copied>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function copy(what: "prompt" | "note") {
    const ok = await copyText(what === "prompt" ? buildPrompt(data) : renderNote(data, new Date()));
    setCopied({ what, ok });
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(null), 2500);
  }

  const label = (what: "prompt" | "note", idle: string, done: string) =>
    copied?.what === what ? (copied.ok ? done : "复制失败，再试一次") : idle;

  const onKey = useRef<(e: KeyboardEvent) => void>(() => {});
  useEffect(() => {
    onKey.current = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable))) return;
      if (e.key === "c") copy("prompt");
      else if (e.key === "o") copy("note");
    };
  });
  useEffect(() => {
    const h = (e: KeyboardEvent) => onKey.current(e);
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  return (
    <div className="paper-actions">
      <button type="button" className="btn btn-sm" onClick={() => copy("prompt")} aria-describedby="copy-state">
        {label("prompt", "复制提问提示词", "已复制提问提示词")}
      </button>
      <button type="button" className="btn btn-sm" onClick={() => copy("note")} aria-describedby="copy-state"
        title="Markdown 格式：属性、中文导读和 HN 原话，能贴进任何笔记软件">
        {label("note", "复制 Markdown 笔记", "已复制 Markdown 笔记")}
      </button>
      <span id="copy-state" className="sr-only" aria-live="polite">
        {copied?.ok ? (copied.what === "prompt" ? "提示词已复制到剪贴板" : "笔记已复制到剪贴板") : ""}
      </span>
    </div>
  );
}
