"use client";

import dynamic from "next/dynamic";
import { useSyncExternalStore } from "react";

// Noto 的 @font-face 声明放在按需加载的块里，不进首屏阻塞渲染的 CSS（以前每页多 160 KB 压缩后的 CSS，手机 LCP 慢 1–2 秒）
const NotoSerif = dynamic(() => import("./fonts/NotoSerif"), { ssr: false });
const NotoSans = dynamic(() => import("./fonts/NotoSans"), { ssr: false });

/** 本机有没有这个字体：有的话，用它排的拉丁字母宽度和纯 monospace 不同（中文字都是全角，比不出来）。 */
function hasLocalFont(family: string): boolean {
  try {
    const c = document.createElement("canvas").getContext("2d");
    if (!c) return false;
    const text = "mmmmmmmmmmlli1WQ";
    c.font = "72px monospace";
    const base = c.measureText(text).width;
    c.font = `72px "${family}", monospace`;
    return c.measureText(text).width !== base;
  } catch {
    return false;
  }
}

let cached: string | null = null;
const snapshot = () => (cached ??= `${hasLocalFont("Songti SC") ? 1 : 0}${hasLocalFont("PingFang SC") ? 1 : 0}`);
const subscribe = () => () => {};

/**
 * 中文兜底字体：苹果设备有 Songti SC / PingFang SC，什么都不加载；缺哪个就加载对应的 Noto（next/font 自托管，按分片下载用到的字）。
 * 服务端按“都有”渲染（不输出任何东西）。
 */
export function CjkFonts() {
  const have = useSyncExternalStore(subscribe, snapshot, () => "11");
  return (
    <>
      {have[0] === "0" && <NotoSerif />}
      {have[1] === "0" && <NotoSans />}
    </>
  );
}
