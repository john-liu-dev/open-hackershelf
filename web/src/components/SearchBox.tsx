"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** 页头搜索框：回车跳到 /search；按 / 聚焦（见 Keyboard）。 */
export function SearchBox({ initial = "" }: { initial?: string }) {
  const router = useRouter();
  const [q, setQ] = useState(initial);
  return (
    <form
      role="search"
      className="site-search"
      onSubmit={(e) => {
        e.preventDefault();
        router.push(`/search?q=${encodeURIComponent(q.trim())}`);
      }}
    >
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" style={{ flexShrink: 0 }}>
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-4-4" />
      </svg>
      <input data-search-input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索标题、作者、主题" aria-label="搜索论文" />
      <kbd className="kbd">/</kbd>
    </form>
  );
}
